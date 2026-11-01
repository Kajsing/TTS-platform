from __future__ import annotations

import json
import runpy
from pathlib import Path
from types import SimpleNamespace

import pytest

BENCHMARK = SimpleNamespace(
    **runpy.run_path(
        str(Path(__file__).resolve().parents[3] / "scripts/benchmark_reader_append.py")
    )
)


def test_fixtures_separate_source_size_and_history_without_block_count_drift():
    for case in BENCHMARK.DEFAULT_CASES:
        chapters = BENCHMARK.synthetic_chapters(case)
        text = BENCHMARK.WRAPPER + "".join("\n\n" + item["text"] for item in chapters)
        assert len(text) == case.source_characters
        assert len(text.split("\n\n")) == 272
        assert len(chapters) == case.seed_chapters
        assert all(len(chapter["text"]) <= 200_000 for chapter in chapters)
    history = [case for case in BENCHMARK.DEFAULT_CASES if case.comparison == "chapter-history"]
    assert len({case.source_characters for case in history}) == 1
    assert len({case.seed_blocks for case in history}) == 1
    assert len(BENCHMARK.MEASURED_PAYLOAD) == 4_000


def test_exclusive_phase_time_does_not_double_count_nested_spans(monkeypatch):
    moments = iter([0, 10, 30, 50])
    monkeypatch.setattr(BENCHMARK.time, "perf_counter_ns", lambda: next(moments))
    collector = BENCHMARK.PhaseCollector()
    collector.start()
    with collector.span("outer"):
        with collector.span("inner"):
            pass
    phases = collector.finish()
    assert phases["outer"] == {"calls": 1, "inclusive_ms": 0.00005, "self_ms": 0.00003}
    assert phases["inner"] == {"calls": 1, "inclusive_ms": 0.00002, "self_ms": 0.00002}
    assert sum(item["self_ms"] for item in phases.values()) == pytest.approx(0.00005)


def test_sql_instrumentation_stores_counts_and_timings_only_and_restores_patches(tmp_path):
    repository_module = BENCHMARK.repository_module
    original = repository_module.connect_sqlite
    collector = BENCHMARK.PhaseCollector()
    with BENCHMARK.instrument(collector):
        collector.start()
        connection = repository_module.connect_sqlite(tmp_path / "test.db")
        assert (
            connection.execute("SELECT 'secret source text'").fetchone()[0] == "secret source text"
        )
        connection.commit()
        connection.close()
        phases = collector.finish()
    assert repository_module.connect_sqlite is original
    assert phases["sqlite_execute"]["calls"] == 1
    assert phases["sqlite_execute:connection_open"]["calls"] == 4
    assert phases["sqlite_commit"]["calls"] == 1
    assert "secret source text" not in json.dumps(phases)
    assert "SELECT" not in json.dumps(phases)


def test_failed_samples_remain_visible_and_are_not_counted_as_passing_latency():
    samples = [
        {"warmup": True, "status": "PASS", "latency_ms": 100, "phases": {}},
        {"warmup": False, "status": "PASS", "latency_ms": 2, "phases": {}},
        {"warmup": False, "status": "FAIL", "latency_ms": 7, "phases": {}},
    ]
    summary = BENCHMARK.summarize(samples)
    assert summary["measured_samples"] == 2
    assert summary["passing_samples"] == summary["failed_samples"] == 1
    assert summary["latency_ms"] == {"median": 2, "minimum": 2, "maximum": 2}
    assert summary["all_full_readbacks_equal"] is False
    assert samples[2]["latency_ms"] == 7
    failed = BENCHMARK._failure_record(
        RuntimeError("private source and credential"),
        {"latency_ms": 7, "phases": {"append": {"calls": 1}}},
    )
    assert failed["latency_ms"] == 7 and failed["phases"]["append"]["calls"] == 1
    assert "private source" not in json.dumps(failed)


def test_real_http_benchmark_isolated_paths_and_complete_readback():
    report = BENCHMARK.run_benchmark(
        repeats=1,
        warmups=0,
        cases=[BENCHMARK.Case("test-tiny", "test", 5_000, 2, 12)],
    )
    assert report["status"] == "PASS", report
    assert report["synthetic_only"] is True
    assert [case["mode"] for case in report["cases"]] == ["m1", "m2"]
    for case in report["cases"]:
        sample = case["samples"][0]
        assert sample["status"] == "PASS"
        assert sample["measured_requests"] == 1
        assert sample["verification_requests"] == 2
        assert sample["full_readback_equal"] is True
        assert sample["normalized_characters"] == 9_002
        assert sample["utf16_units"] == 9_003
        assert sample["source_blocks"] == 16
        assert sample["chapter_receipts"] == 3
        assert sample["phases"]["history_insert"]["calls"] == 1
        assert sample["phases"]["chapter_markers"]["calls"] == 1
        assert sample["phases"]["sqlite_commit"]["calls"] >= 1
        assert sample["phases"]["sqlite_close"]["calls"] >= 1
        assert sample["instrumented_self_ms"] <= sample["latency_ms"]
    serialized = json.dumps(report)
    assert "rdr_agent_" not in serialized
    assert "Synthetic source block" not in serialized
