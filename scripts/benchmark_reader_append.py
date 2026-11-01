"""Measure Reader chapter appends through a real isolated localhost service.

Only synthetic fixtures are used. The benchmark owns its temporary service,
database snapshots and instrumentation; the normal profile/port is never used.
Run from the repository root with ``py -3 scripts/benchmark_reader_append.py``.
"""

from __future__ import annotations

import argparse
import functools
import hashlib
import inspect
import json
import logging
import os
import platform
import shutil
import socket
import sqlite3
import statistics
import sys
import tempfile
import threading
import time
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
for _source in (
    "packages/tts_core/src",
    "packages/reader_core/src",
    "packages/document_import/src",
    "packages/speech_rules/src",
    "apps/tts_service/src",
    "apps/reader_agent/src",
):
    sys.path.insert(0, str(REPO_ROOT / _source))

import httpx  # noqa: E402
import uvicorn  # noqa: E402
from reader_core.agent_parts import normalized_wrapper  # noqa: E402
from reader_core.sqlite import repository as repository_module  # noqa: E402
from reader_core.sqlite.agent_imports import AgentImportsMixin  # noqa: E402
from reader_core.sqlite.agent_repository import SqliteReaderAgentRepository  # noqa: E402
from reader_core.sqlite.repository import SqliteReaderRepository  # noqa: E402
from tts_service.config import AppConfig  # noqa: E402
from tts_service.main import create_app  # noqa: E402
from tts_service.reader_agent_service import ReaderAgentService  # noqa: E402

WRAPPER_TITLE = "Append benchmark"
WRAPPER_INTRO = "Synthetic fixture."
WRAPPER = normalized_wrapper(WRAPPER_TITLE, WRAPPER_INTRO)
MEASURED_PAYLOAD = "Measured chapter\n\n" + "m" * (4_000 - len("Measured chapter\n\n") - 2) + "😀."


@dataclass(frozen=True)
class Case:
    name: str
    comparison: str
    source_characters: int
    seed_chapters: int
    seed_blocks: int = 270


DEFAULT_CASES = (
    Case("size-small", "source-size", 50_000, 5),
    Case("size-medium", "source-size", 400_000, 5),
    Case("size-near-limit", "source-size", 880_000, 5),
    Case("history-medium", "chapter-history", 400_000, 40),
    Case("history-high", "chapter-history", 400_000, 90),
)


def synthetic_chapters(case: Case) -> list[dict]:
    """Hold total source blocks/characters fixed while varying chapter history."""
    if not 1 <= case.seed_chapters <= min(99, case.seed_blocks) or case.seed_blocks > 10_000:
        raise ValueError("Fixture requires 1..99 chapters and at least one block per chapter")
    # Every supplied paragraph is nonempty; Reader inserts exactly two newlines
    # between all source blocks, including the fixed two-block wrapper.
    total_blocks = case.seed_blocks + 2
    prose_characters = case.source_characters - len(WRAPPER) - case.seed_blocks * 2
    block_length, remainder = divmod(prose_characters, case.seed_blocks)
    if block_length < 40:
        raise ValueError("Fixture paragraphs require at least 40 characters")
    paragraphs = []
    for index in range(case.seed_blocks):
        prefix = f"Synthetic source block {index:05d}: "
        length = block_length + int(index < remainder)
        paragraphs.append(prefix + "s" * (length - len(prefix)))
    chapters = []
    cursor = 0
    for index in range(case.seed_chapters):
        count = case.seed_blocks // case.seed_chapters + int(
            index < case.seed_blocks % case.seed_chapters
        )
        body = "\n\n".join(paragraphs[cursor : cursor + count])
        cursor += count
        if len(body) > 200_000:
            raise ValueError("A synthetic seed chapter exceeds the public write limit")
        chapters.append(chapter_payload(index + 1, body))
    text = WRAPPER + "".join("\n\n" + item["text"] for item in chapters)
    if len(text) != case.source_characters or len(text.split("\n\n")) != total_blocks:
        raise AssertionError("Synthetic fixture counters do not match its source")
    return chapters


def chapter_payload(number: int, text: str) -> dict:
    return {
        "story_key": "synthetic-append-benchmark",
        "chapter_key": str(number),
        "retry_key": "benchmark-chapter-" + str(number),
        "source_url": f"https://example.invalid/append-benchmark/{number}",
        "title": f"Synthetic chapter {number}",
        "text": text,
        "order_index": number,
    }


class PhaseCollector:
    """Thread-local nesting gives disjoint self time, with inclusive time retained."""

    def __init__(self):
        self.enabled = False
        self._local = threading.local()
        self._lock = threading.Lock()
        self._phases = {}

    def start(self):
        with self._lock:
            self._phases = {}
        self.enabled = True

    def finish(self):
        self.enabled = False
        with self._lock:
            return {
                name: {
                    "calls": values[0],
                    "inclusive_ms": values[1] / 1_000_000,
                    "self_ms": values[2] / 1_000_000,
                }
                for name, values in sorted(self._phases.items())
            }

    @contextmanager
    def span(self, name):
        if not self.enabled:
            yield
            return
        stack = getattr(self._local, "stack", None)
        if stack is None:
            stack = self._local.stack = []
        frame = [time.perf_counter_ns(), 0, name]
        stack.append(frame)
        try:
            yield
        finally:
            duration = time.perf_counter_ns() - frame[0]
            stack.pop()
            if stack:
                stack[-1][1] += duration
            with self._lock:
                values = self._phases.setdefault(name, [0, 0, 0])
                values[0] += 1
                values[1] += duration
                values[2] += max(0, duration - frame[1])

    def sql_label(self, label):
        stack = getattr(self._local, "stack", ())
        return label + (":" + stack[-1][2] if stack else "")


class TimedConnection(sqlite3.Connection):
    collector: PhaseCollector

    def execute(self, *arguments, **keywords):
        with self.collector.span(self.collector.sql_label("sqlite_execute")):
            return super().execute(*arguments, **keywords)

    def executemany(self, *arguments, **keywords):
        with self.collector.span(self.collector.sql_label("sqlite_executemany")):
            return super().executemany(*arguments, **keywords)

    def commit(self):
        with self.collector.span("sqlite_commit"):
            return super().commit()

    def rollback(self):
        with self.collector.span("sqlite_rollback"):
            return super().rollback()

    def close(self):
        with self.collector.span("sqlite_close"):
            return super().close()


@contextmanager
def instrument(collector: PhaseCollector):
    """Patch only this standalone benchmark process; restore all descriptors."""
    patches = []

    def wrap(owner, attribute, label):
        descriptor = inspect.getattr_static(owner, attribute)
        original = descriptor.__func__ if isinstance(descriptor, staticmethod) else descriptor

        @functools.wraps(original)
        def measured(*arguments, **keywords):
            with collector.span(label):
                return original(*arguments, **keywords)

        patches.append((owner, attribute, descriptor))
        setattr(
            owner,
            attribute,
            staticmethod(measured) if isinstance(descriptor, staticmethod) else measured,
        )

    original_connection = repository_module.connect_sqlite

    def connect(database_path):
        with collector.span("connection_open"):
            connection = sqlite3.connect(
                database_path, timeout=5.0, isolation_level=None, factory=TimedConnection
            )
            connection.collector = collector
            connection.row_factory = sqlite3.Row
            for statement in (
                "PRAGMA foreign_keys = ON",
                "PRAGMA journal_mode = WAL",
                "PRAGMA synchronous = NORMAL",
                "PRAGMA busy_timeout = 5000",
            ):
                connection.execute(statement)
            return connection

    try:
        repository_module.connect_sqlite = connect
        for owner, attribute, label in (
            (ReaderAgentService, "run", "application"),
            (SqliteReaderAgentRepository, "authorize", "authorization"),
            (SqliteReaderAgentRepository, "import_target", "managed_target"),
            (SqliteReaderAgentRepository, "deliver_chapter", "chapter_delivery"),
            (AgentImportsMixin, "deliver_import_chapter", "managed_delivery"),
            (AgentImportsMixin, "_validate_part_after_append", "managed_part_validation"),
            (SqliteReaderRepository, "append_text", "append"),
            (SqliteReaderRepository, "_insert_edit", "history_insert"),
            (SqliteReaderRepository, "_record_chapter_history", "chapter_markers"),
            (SqliteReaderRepository, "_trim_history", "history_trim"),
            (SqliteReaderRepository, "_advance_saved_cursor_revisions", "cursor_revisions"),
            (SqliteReaderRepository, "_update_document_content", "document_counters"),
        ):
            wrap(owner, attribute, label)
        yield
    finally:
        repository_module.connect_sqlite = original_connection
        for owner, attribute, descriptor in reversed(patches):
            setattr(owner, attribute, descriptor)


@contextmanager
def isolated_service(root: Path):
    config = AppConfig.from_mapping(
        {
            "auth": {"enabled": True, "token_file": str(root / "token.txt")},
            "backend": {"mode": "stub"},
            "tts": {"warmup_on_start": False},
            "limits": {"requests_per_minute": 1_000},
            "reader": {"home_path": str(root / "reader"), "exports": {"formats": ["wav"]}},
        }
    )
    app = create_app(config=config, repo_root=root)
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
        if port == 7777:
            raise RuntimeError("Benchmark refuses the normal Reader service port")
        server = uvicorn.Server(uvicorn.Config(app, log_level="error", access_log=False))
        thread = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
        thread.start()
        try:
            deadline = time.monotonic() + 15
            while not server.started:
                if not thread.is_alive() or time.monotonic() >= deadline:
                    raise RuntimeError("Isolated benchmark service did not start")
                time.sleep(0.01)
            with httpx.Client(
                base_url=f"http://127.0.0.1:{port}", timeout=30, trust_env=False
            ) as client:
                yield client, app
        finally:
            server.should_exit = True
            thread.join(15)
            if thread.is_alive():
                raise RuntimeError("Isolated benchmark service did not stop")


class PublicClient:
    def __init__(self, client: httpx.Client, credential: str):
        self.client = client
        self.headers = {"Authorization": "Bearer " + credential}
        self.requests = 0

    def call(self, method, path, **arguments):
        self.requests += 1
        result = self.client.request(method, path, headers=self.headers, **arguments)
        if result.is_error:
            # No server body/path/credential is included in retained failures.
            raise BenchmarkFailure("http_error", result.status_code)
        return result.json()


class BenchmarkFailure(Exception):
    def __init__(self, code, status=None):
        super().__init__(code)
        self.code = code
        self.status = status


def read_back(api: PublicClient, article_id: str) -> tuple[str, dict]:
    page = api.call("GET", "/v1/reader/agent/articles/" + article_id)
    article = page["article"]
    parts = [page["text"]]
    while page["next_offset"] is not None:
        page = api.call(
            "GET",
            "/v1/reader/agent/articles/" + article_id,
            params={"offset": page["next_offset"], "expected_row_version": article["row_version"]},
        )
        parts.append(page["text"])
    return "".join(parts), article


def seed(root: Path, case: Case, mode: str) -> dict:
    chapters = synthetic_chapters(case)
    measured = chapter_payload(case.seed_chapters + 1, MEASURED_PAYLOAD)
    expected = WRAPPER + "".join("\n\n" + item["text"] for item in chapters)
    with isolated_service(root) as (client, app):
        owner = PublicClient(client, app.state.container.auth.token)
        folder = owner.call("POST", "/v1/reader/folders", json={"name": "Append benchmark"})
        provision = owner.call(
            "POST", "/v1/reader/agent-access/grants", json={"folder_id": folder["id"]}
        )
        api = PublicClient(client, provision["credential"])
        plan_id = None
        if mode == "m1":
            article = api.call(
                "POST", "/v1/reader/agent/articles", json={"title": WRAPPER_TITLE, "text": WRAPPER}
            )
            version = article["row_version"]
            article_id = article["id"]
            for item in chapters:
                result = api.call(
                    "POST",
                    f"/v1/reader/agent/articles/{article_id}/chapters",
                    json=item | {"expected_row_version": version},
                )
                version = result["result_row_version"]
            endpoint = f"/v1/reader/agent/articles/{article_id}/chapters"
            payload = measured | {"expected_row_version": version}
        elif mode == "m2":
            preview = api.call(
                "POST",
                "/v1/reader/agent/import-plans",
                json={
                    "title": WRAPPER_TITLE,
                    "intro": WRAPPER_INTRO,
                    "retry_key": "benchmark-plan",
                    "chapters": chapters + [measured],
                },
            )
            if len(preview["parts"]) != 1:
                raise BenchmarkFailure("fixture_unexpected_rollover")
            plan_id = preview["plan_id"]
            endpoint = f"/v1/reader/agent/import-plans/{plan_id}/chapters"
            for item in chapters:
                result = api.call("POST", endpoint, json={"chapter": item})
            article_id = result["document_id"]
            version = result["receipt"]["result_row_version"]
            payload = {"chapter": measured}
        else:
            raise ValueError("Unknown benchmark mode")
        # Baselines are verified before snapshotting. Near-limit readback would
        # exceed the agent budget after 90 seed calls, so its chapter-count case
        # has only ~20 read pages; the total remains below 120/minute.
        actual, _ = read_back(api, article_id)
        if actual != expected:
            raise BenchmarkFailure("seed_readback_mismatch")
        return {
            "credential": provision["credential"],
            "article_id": article_id,
            "plan_id": plan_id,
            "endpoint": endpoint,
            "payload": payload,
            "expected": expected + "\n\n" + MEASURED_PAYLOAD,
            "source_row_version": version,
            "seed_requests": owner.requests + api.requests,
            "result_chapter_receipts": case.seed_chapters + 1,
        }


def run_sample(snapshot: Path, root: Path, fixture: dict, collector: PhaseCollector) -> dict:
    shutil.copytree(snapshot / "reader", root / "reader")
    result = {"status": "FAIL", "latency_ms": None, "phases": {}}
    with isolated_service(root) as (client, _):
        api = PublicClient(client, fixture["credential"])
        api.call("GET", "/v1/reader/agent/workspace")  # Warm TCP/auth outside timing.
        before = api.requests
        collector.start()
        started = time.perf_counter_ns()
        try:
            try:
                response = api.call("POST", fixture["endpoint"], json=fixture["payload"])
            finally:
                result["latency_ms"] = (time.perf_counter_ns() - started) / 1_000_000
                result["phases"] = collector.finish()
                result["measured_requests"] = api.requests - before
        except Exception as error:
            return _failure_record(error, result)
        outcome = response.get("outcome")
        if outcome != "imported":
            return _failure_record(BenchmarkFailure("append_not_imported"), result)
        verification_start = api.requests
        try:
            actual, metadata = read_back(api, fixture["article_id"])
            if actual != fixture["expected"]:
                raise BenchmarkFailure("full_readback_mismatch")
            receipts = api.call(
                "GET",
                f"/v1/reader/agent/articles/{fixture['article_id']}/chapters",
                params={"limit": 100},
            )
            if len(receipts["items"]) != fixture["result_chapter_receipts"]:
                raise BenchmarkFailure("chapter_receipt_count_mismatch")
        except Exception as error:
            return _failure_record(error, result)
        result.update(
            {
                "status": "PASS",
                "full_readback_equal": True,
                "normalized_characters": len(actual),
                "utf16_units": len(actual.encode("utf-16-le")) // 2,
                "source_blocks": len(actual.split("\n\n")),
                "chapter_receipts": len(receipts["items"]),
                "source_sha256": hashlib.sha256(actual.encode("utf-8")).hexdigest(),
                "result_row_version": metadata["row_version"],
                "verification_requests": api.requests - verification_start,
                "instrumented_self_ms": sum(item["self_ms"] for item in result["phases"].values()),
            }
        )
        result["http_framework_uninstrumented_ms"] = max(
            0, result["latency_ms"] - result["instrumented_self_ms"]
        )
    return result


def _failure_record(error: Exception, partial=None):
    return (partial or {}) | {
        "status": "FAIL",
        "error_class": type(error).__name__,
        "error_code": error.code if isinstance(error, BenchmarkFailure) else "sample_error",
        "http_status": error.status if isinstance(error, BenchmarkFailure) else None,
    }


def summarize(samples: list[dict]) -> dict:
    measured = [item for item in samples if not item["warmup"]]
    passing = [item for item in measured if item["status"] == "PASS"]
    values = [item["latency_ms"] for item in passing]
    return {
        "measured_samples": len(measured),
        "passing_samples": len(passing),
        "failed_samples": len(measured) - len(passing),
        "latency_ms": (
            {"median": statistics.median(values), "minimum": min(values), "maximum": max(values)}
            if values
            else None
        ),
        "phase_median_self_ms": {
            name: statistics.median(
                item["phases"].get(name, {}).get("self_ms", 0) for item in passing
            )
            for name in sorted({name for item in passing for name in item["phases"]})
        },
        "all_full_readbacks_equal": bool(passing) and len(passing) == len(measured),
    }


def run_benchmark(*, repeats=5, warmups=1, cases=DEFAULT_CASES, progress=None):
    if not 1 <= repeats <= 10 or not 0 <= warmups <= 2:
        raise ValueError("Use 1..10 measured samples and 0..2 warmups")
    report = {
        "schema": 1,
        "status": "FAIL",
        "synthetic_only": True,
        "started_at_utc": datetime.now(timezone.utc).isoformat(),
        "environment": {
            "platform": platform.platform(),
            "python": platform.python_version(),
            "sqlite": sqlite3.sqlite_version,
            "logical_cpus": os.cpu_count(),
            "perf_counter_resolution_seconds": time.get_clock_info("perf_counter").resolution,
        },
        "method": {
            "measured_repeats": repeats,
            "warmups": warmups,
            "transport": "real-loopback-http",
            "service_port": "ephemeral-not-7777",
            "backend": "stub-no-synthesis",
            "snapshot_per_sample": True,
            "same_appended_payload_characters": len(MEASURED_PAYLOAD),
            "seed_block_count_excludes_two_wrapper_blocks": True,
            "phase_timings": "nested-exclusive-self-and-inclusive; no SQL/text/credential logging",
            "sqlite_execute_scope": "execute calls only; iteration belongs to parent phase",
            "residual_scope": "HTTP/framework/serialization/uninstrumented work; not network alone",
            "profiling_scope": "all timed calls are instrumented; timer overhead is not subtracted",
            "cache_scope": "fresh app/DB copy; warm TCP; OS file cache not flushed",
            "failures": "retained without automatic retry; warmups excluded only from summary",
        },
        "cases": [],
    }
    collector = PhaseCollector()
    with tempfile.TemporaryDirectory(prefix="reader-append-benchmark-") as temporary:
        work = Path(temporary)
        with instrument(collector):
            for case in cases:
                for mode in ("m1", "m2"):
                    result = {"case": asdict(case), "mode": mode, "samples": []}
                    report["cases"].append(result)
                    seed_root = work / (case.name + "-" + mode + "-seed")
                    try:
                        fixture = seed(seed_root, case, mode)
                        result["seed_requests"] = fixture["seed_requests"]
                        for index in range(warmups + repeats):
                            if progress:
                                progress(case.name, mode, index, warmups + repeats)
                            try:
                                sample = run_sample(
                                    seed_root,
                                    work / f"{case.name}-{mode}-{index}",
                                    fixture,
                                    collector,
                                )
                            except Exception as error:
                                sample = {
                                    "status": "FAIL",
                                    "error_class": type(error).__name__,
                                    "error_code": error.code
                                    if isinstance(error, BenchmarkFailure)
                                    else "sample_error",
                                    "http_status": error.status
                                    if isinstance(error, BenchmarkFailure)
                                    else None,
                                }
                            sample["warmup"] = index < warmups
                            sample["index"] = index
                            result["samples"].append(sample)
                        result["summary"] = summarize(result["samples"])
                    except Exception as error:
                        result["seed_failure"] = {
                            "error_class": type(error).__name__,
                            "error_code": error.code
                            if isinstance(error, BenchmarkFailure)
                            else "seed_error",
                            "http_status": error.status
                            if isinstance(error, BenchmarkFailure)
                            else None,
                        }
    if report["cases"] and all(
        "seed_failure" not in case and all(sample["status"] == "PASS" for sample in case["samples"])
        for case in report["cases"]
    ):
        report["status"] = "PASS"
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument("--warmups", type=int, default=1)
    arguments = parser.parse_args()
    logging.disable(logging.CRITICAL)
    report = run_benchmark(
        repeats=arguments.repeats,
        warmups=arguments.warmups,
        progress=lambda case, mode, index, total: print(
            f"{case} {mode}: sample {index + 1}/{total}", flush=True
        ),
    )
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "cases": len(report["cases"])}))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
