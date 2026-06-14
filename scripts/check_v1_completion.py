from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
AUDIT_PATH = "docs/v1_completion_audit.md"
READINESS_SCRIPT_PATH = "scripts/check_v1_readiness.py"

AUDIT_MARKERS = (
    "# V1 Completion Audit",
    "Status: pre-final audit.",
    "Final security-focused pass: pending",
    "Can mark v1 complete",
    "## Done When Evidence",
    "## Remaining Gates Before V1 Complete",
)

DONE_WHEN_EVIDENCE = (
    {
        "id": 1,
        "name": "localhost_tts_contracts",
        "audit_marker": "Local server runs the intended TTS pipeline",
        "evidence": (
            ("scripts/smoke_service.py", "min_stream_text_chunks"),
            ("scripts/check_local_service_bootstrap.py", "smoke_service.py"),
            ("apps/tts_service/tests/test_api.py", "/v1/tts"),
            ("apps/tts_service/tests/test_streaming.py", "/v1/tts/stream"),
        ),
    },
    {
        "id": 2,
        "name": "long_page_extension_reader",
        "audit_marker": "Long page reading through the Chrome extension",
        "evidence": (
            ("scripts/check_extension_reader_flow.py", "word_count"),
            ("scripts/check_extension.py", "verify_manifest_policy"),
            ("scripts/check_chrome_extension_smoke.py", "tts-extension:speak-page"),
        ),
    },
    {
        "id": 3,
        "name": "model_management",
        "audit_marker": "Model management covers catalog listing",
        "evidence": (
            ("scripts/check_model_management_flow.py", "model-install"),
            ("apps/tts_service/tests/test_cli_models.py", "allow-missing-checksum"),
            ("apps/tts_service/src/tts_service/cli.py", "_assert_safe_archive_quota"),
            ("models/catalog.json", "vits-piper-en_US-lessac-medium"),
        ),
    },
    {
        "id": 4,
        "name": "windows_first_run_and_autostart",
        "audit_marker": "Windows first-run, bundle install, launchers",
        "evidence": (
            ("scripts/check_windows_bundle_bootstrap.py", "setup-local"),
            ("scripts/check_windows_bundle_install.py", "installer_script"),
            ("scripts/check_windows_launchers.py", "foreground_service"),
            ("scripts/check_windows_service_task.py", "ONLOGON"),
        ),
    },
    {
        "id": 5,
        "name": "security_defaults",
        "audit_marker": "Security defaults for localhost binding",
        "evidence": (
            ("scripts/check_security_defaults.py", "loopback_host"),
            ("scripts/check_extension.py", "LOCAL_SERVICE_HOST_PERMISSIONS"),
            ("apps/tts_service/src/tts_service/cli.py", "_artifact_host_resolves"),
            ("apps/tts_service/src/tts_service/main.py", "_requires_protected_http_access"),
        ),
    },
    {
        "id": 6,
        "name": "final_security_review",
        "audit_marker": "final security-focused review",
        "pending": True,
        "evidence": (
            ("docs/v1_completion_audit.md", "Final security-focused pass: pending"),
        ),
    },
    {
        "id": 7,
        "name": "documentation_current",
        "audit_marker": "Documentation is updated",
        "evidence": (
            ("README.md", "Release Check"),
            ("TESTING.md", "v1-readiness"),
            ("docs/backend_model_setup.md", "Security Notes"),
            ("docs/codex/Documentation.md", "Current Status"),
        ),
    },
    {
        "id": 8,
        "name": "validation_commands",
        "audit_marker": "Relevant automated validation passes",
        "evidence": (
            ("docs/codex/Prompt.md", "python3 -m pytest -q"),
            ("docs/codex/Prompt.md", "python3 -m ruff check ."),
            ("docs/codex/Prompt.md", "python3 scripts/release_check.py"),
            ("docs/codex/Prompt.md", "python3 scripts/check_v1_readiness.py"),
        ),
    },
    {
        "id": 9,
        "name": "repo_definition_of_done",
        "audit_marker": "Repo-level definition of done",
        "evidence": (
            ("AGENTS.md", "Definition of Done"),
            ("AGENTS.md", "Commit And Push Policy"),
            ("docs/codex/Implement.md", "Finish Checklist"),
        ),
    },
)


class V1CompletionError(RuntimeError):
    pass


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="check_v1_completion")
    parser.add_argument(
        "--require-complete",
        action="store_true",
        help="Fail while the final security-focused pass is still pending.",
    )
    args = parser.parse_args(argv)

    summary = check_v1_completion(
        repo_root=REPO_ROOT,
        require_complete=args.require_complete,
    )
    print(json.dumps(summary, indent=2, sort_keys=True))


def check_v1_completion(
    *,
    repo_root: Path,
    require_complete: bool = False,
) -> dict[str, object]:
    errors: list[str] = []
    audit_path = repo_root / AUDIT_PATH
    audit_text = _read_text(errors=errors, repo_root=repo_root, relative_path=AUDIT_PATH)

    for marker in AUDIT_MARKERS:
        if marker not in audit_text:
            errors.append(f"{AUDIT_PATH} must include {marker!r}")

    readiness_summary = _run_readiness_check(repo_root=repo_root, errors=errors)
    criteria = []
    final_security_pending = False
    for criterion in DONE_WHEN_EVIDENCE:
        evidence_errors = _check_criterion_evidence(
            repo_root=repo_root,
            audit_text=audit_text,
            criterion=criterion,
        )
        status = "ready"
        if criterion.get("pending"):
            status = "pending_final_security"
            final_security_pending = True
        if evidence_errors:
            status = "missing_evidence"
            errors.extend(evidence_errors)
        criteria.append(
            {
                "id": criterion["id"],
                "name": criterion["name"],
                "status": status,
            }
        )

    if require_complete and final_security_pending:
        errors.append(
            "Final security-focused pass is still pending; run it before marking v1 complete."
        )

    if errors:
        raise V1CompletionError("V1 completion check failed:\n" + "\n".join(errors))

    return {
        "audit_path": _display_path(repo_root=repo_root, path=audit_path),
        "criteria": criteria,
        "criteria_ready": sum(1 for criterion in criteria if criterion["status"] == "ready"),
        "criteria_pending_final_security": sum(
            1 for criterion in criteria if criterion["status"] == "pending_final_security"
        ),
        "final_security_pending": final_security_pending,
        "can_mark_v1_complete": not final_security_pending,
        "readiness": readiness_summary,
    }


def _check_criterion_evidence(
    *,
    repo_root: Path,
    audit_text: str,
    criterion: dict[str, object],
) -> list[str]:
    errors: list[str] = []
    audit_marker = str(criterion["audit_marker"])
    if audit_marker not in audit_text:
        errors.append(f"{AUDIT_PATH} must include criterion marker {audit_marker!r}")
    for relative_path, marker in criterion["evidence"]:
        text = _read_text(
            errors=errors,
            repo_root=repo_root,
            relative_path=str(relative_path),
        )
        if str(marker) not in text:
            errors.append(f"{relative_path} must include evidence marker {marker!r}")
    return errors


def _run_readiness_check(*, repo_root: Path, errors: list[str]) -> dict[str, object]:
    readiness_path = repo_root / READINESS_SCRIPT_PATH
    if not readiness_path.is_file():
        errors.append(f"Missing readiness script: {READINESS_SCRIPT_PATH}")
        return {}

    try:
        readiness_module = _load_module(
            module_name="tts_platform_check_v1_readiness_for_completion",
            path=readiness_path,
        )
        return readiness_module.check_v1_readiness(repo_root=repo_root)
    except Exception as exc:  # pragma: no cover - message is validated by caller tests.
        errors.append(f"V1 readiness check failed during completion audit: {exc}")
        return {}


def _load_module(*, module_name: str, path: Path):
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise V1CompletionError(f"Unable to load module from {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _read_text(*, errors: list[str], repo_root: Path, relative_path: str) -> str:
    path = repo_root / relative_path
    if not path.is_file():
        errors.append(f"Missing completion evidence file: {relative_path}")
        return ""
    return path.read_text(encoding="utf-8")


def _display_path(*, repo_root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(repo_root.resolve()).as_posix()
    except ValueError:
        return str(path)


if __name__ == "__main__":
    main()
