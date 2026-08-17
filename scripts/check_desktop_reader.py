from __future__ import annotations

import argparse
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
import zipfile
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


class DesktopReaderCheckError(RuntimeError):
    pass


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate the .NET desktop Reader, live paging, and portable WPF package."
    )
    parser.add_argument("--require-dotnet", action="store_true")
    parser.add_argument(
        "--require-windows-audio",
        action="store_true",
        help="Require a real Windows shared-mode audio endpoint smoke.",
    )
    parser.add_argument(
        "--require-windows-integration",
        action="store_true",
        help="Require Windows clipboard-listener, hotkey, tray, and audio smoke checks.",
    )
    parser.add_argument("--dotnet", type=Path)
    parser.add_argument("--skip-build", action="store_true")
    return parser


def _run(command: list[str], *, cwd: Path, env: dict[str, str] | None = None) -> str:
    completed = subprocess.run(
        command,
        cwd=cwd,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    if completed.returncode != 0:
        raise DesktopReaderCheckError(
            f"Command failed ({completed.returncode}): {' '.join(command)}\n{completed.stdout}"
        )
    return completed.stdout


def _dotnet_candidates(explicit: Path | None) -> Iterator[Path]:
    if explicit is not None:
        yield explicit
    configured = os.environ.get("TTS_PLATFORM_DOTNET")
    if configured:
        yield Path(configured)
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        yield Path(local_app_data) / "TTSPlatform" / "dotnet" / "dotnet.exe"
    executable = shutil.which("dotnet")
    if executable:
        yield Path(executable)


def _resolve_dotnet(explicit: Path | None, *, required: bool) -> Path | None:
    checked: set[Path] = set()
    for candidate in _dotnet_candidates(explicit):
        candidate = candidate.resolve()
        if candidate in checked or not candidate.is_file():
            continue
        checked.add(candidate)
        completed = subprocess.run(
            [str(candidate), "--version"],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        version = completed.stdout.strip()
        if completed.returncode == 0 and version.split(".", 1)[0].isdigit() and int(
            version.split(".", 1)[0]
        ) >= 10:
            return candidate
    if required:
        raise DesktopReaderCheckError(
            ".NET SDK 10 or newer was not found. Set TTS_PLATFORM_DOTNET or pass --dotnet."
        )
    return None


def _check_source_shape(repo_root: Path) -> dict[str, object]:
    reader_root = repo_root / "apps" / "desktop_reader"
    required = [
        reader_root / "TtsPlatform.Reader.sln",
        reader_root / "src" / "TtsPlatform.Reader.Client" / "ReaderServiceClient.cs",
        reader_root / "src" / "TtsPlatform.Reader.Application" / "Onboarding.cs",
        reader_root / "src" / "TtsPlatform.Reader.Windows" / "JsonDesktopSettingsStore.cs",
        reader_root / "src" / "TtsPlatform.Reader.Windows" / "WasapiAudioOutput.cs",
        reader_root
        / "src"
        / "TtsPlatform.Reader.Windows"
        / "JsonlPlaybackPerformanceSink.cs",
        reader_root / "src" / "TtsPlatform.Reader.Windows" / "ClipboardIntegration.cs",
        reader_root / "src" / "TtsPlatform.Reader.Windows" / "GlobalHotkeys.cs",
        reader_root / "src" / "TtsPlatform.Reader.Windows" / "ReaderTrayIcon.cs",
        reader_root / "src" / "TtsPlatform.Reader.Windows" / "ScheduledServiceController.cs",
        reader_root / "src" / "TtsPlatform.Reader.Windows" / "ReaderServiceProcessLeaseStore.cs",
        reader_root / "src" / "TtsPlatform.Reader.Client" / "ReaderStreamClient.cs",
        reader_root / "src" / "TtsPlatform.Reader.Application" / "Playback.cs",
        reader_root / "src" / "TtsPlatform.Reader.Application" / "ClipboardCapture.cs",
        reader_root / "src" / "TtsPlatform.Reader.Application" / "ReadingWindowPager.cs",
        reader_root / "src" / "TtsPlatform.Reader.Application" / "ContinuousDocumentText.cs",
        reader_root / "src" / "TtsPlatform.Reader.Application" / "ArticleFind.cs",
        reader_root / "src" / "TtsPlatform.Reader.App" / "MainWindow.xaml",
        reader_root / "src" / "TtsPlatform.Reader.App" / "Assets" / "TtsPlatformReader.ico",
        reader_root / "src" / "TtsPlatform.Reader.App" / "Assets" / "TtsPlatformReader.png",
        reader_root / "src" / "TtsPlatform.Reader.App" / "ClipboardCaptureDialog.xaml",
        reader_root / "src" / "TtsPlatform.Reader.App" / "ClipboardDuplicateDialog.xaml",
        reader_root / "src" / "TtsPlatform.Reader.App" / "ClipboardDuplicateDialog.xaml.cs",
        reader_root / "src" / "TtsPlatform.Reader.App" / "RenameDocumentDialog.xaml",
        reader_root / "src" / "TtsPlatform.Reader.App" / "RenameDocumentDialog.xaml.cs",
        reader_root / "src" / "TtsPlatform.Reader.App" / "ImportPreviewDialog.xaml",
        reader_root / "src" / "TtsPlatform.Reader.App" / "RuleEditorDialog.xaml",
        reader_root / "src" / "TtsPlatform.Reader.App" / "LibraryWorkflowDialog.xaml",
        reader_root / "src" / "TtsPlatform.Reader.App" / "LibraryWorkflowDialog.xaml.cs",
        reader_root / "src" / "TtsPlatform.Reader.App" / "CompactControllerWindow.xaml",
        repo_root / "docs" / "reader_milestone5_manual_checklist.md",
        reader_root / "src" / "TtsPlatform.Reader.App" / "Resources" / "Strings.en-US.resx",
        reader_root / "src" / "TtsPlatform.Reader.App" / "Resources" / "Strings.da-DK.resx",
    ]
    missing = [str(path.relative_to(repo_root)) for path in required if not path.is_file()]
    if missing:
        raise DesktopReaderCheckError(f"Desktop Reader files are missing: {missing}")

    source_text = "\n".join(
        path.read_text(encoding="utf-8")
        for path in reader_root.rglob("*")
        if path.is_file() and path.suffix.lower() in {".cs", ".csproj", ".xaml"}
    )
    clipboard_features = [
        "AddClipboardFormatListener",
        "RegisterHotKey(",
        "Forms.Clipboard",
        "CopySelectionHelper",
        "ReaderTrayIcon",
        "ClipboardCaptureAction.AppendToOpenDocument",
    ]
    missing_features = [
        value for value in clipboard_features if value.casefold() not in source_text.casefold()
    ]
    if missing_features:
        raise DesktopReaderCheckError(
            f"Milestone 5 Windows capture features are missing: {missing_features}"
        )
    if "<TargetFramework>net10.0-windows</TargetFramework>" not in source_text:
        raise DesktopReaderCheckError("The WPF application does not target net10.0-windows.")
    if "NAudio" not in source_text or "ReaderStreamProtocolParser" not in source_text:
        raise DesktopReaderCheckError("Milestone 4 audio or stream protocol code is missing.")
    import_features = [
        "PreviewImportAsync",
        "DuplicateAsEditableTextAsync",
        "ImportPreviewDialog",
        "ReadingWindowPager",
        "VirtualizingPanel.IsVirtualizing",
        "FollowReadingCheckBox",
    ]
    missing_import_features = [
        value for value in import_features if value.casefold() not in source_text.casefold()
    ]
    if missing_import_features:
        raise DesktopReaderCheckError(
            f"Milestone 6 import or virtualized-reading features are missing: "
            f"{missing_import_features}"
        )
    rule_features = [
        "PreviewRulesAsync",
        "RuleEditorDialog",
        "Create rule from selection",
        "DisableWarningRuleButton",
        "ReaderStreamWarning",
    ]
    missing_rule_features = [
        value for value in rule_features if value.casefold() not in source_text.casefold()
    ]
    if missing_rule_features:
        raise DesktopReaderCheckError(
            f"Milestone 7 speech-rule features are missing: {missing_rule_features}"
        )
    library_features = [
        "LibraryWorkflowDialog",
        "LibraryStateComboBox",
        "AutoAdvanceCheckBox",
        "UpdateDocumentStateAsync",
        "AdvanceQueueAsync",
        "ReorderQueueAsync",
        "CreateBookmarkAsync",
        "CreateExportAsync",
        "CancelExportAsync",
        "DeleteExportAsync",
        "DownloadExportResultAsync",
        "Delete selected...",
        "VoiceSelectionPolicy",
        "DesktopConnectionPolicy.RequiresReconnect",
        "ConnectionState.RateLimited",
        "PreferredVoiceId",
        "SelectedVoiceId() ?? _settings.PreferredVoiceId",
        "Reading voice",
        "Voice: SelectedVoiceId()",
        "VoiceId: _voiceId",
        "Audio export format",
        "AudioFormat",
        'Value="{Binding ProgressPercent, Mode=OneWay}"',
    ]
    missing_library_features = [
        value for value in library_features if value.casefold() not in source_text.casefold()
    ]
    if missing_library_features:
        raise DesktopReaderCheckError(
            f"Milestone 8 library-workflow features are missing: {missing_library_features}"
        )
    browser_handoff_features = [
        "GetNextDesktopOpenRequestAsync",
        "AcknowledgeDesktopOpenRequestAsync",
        "DesktopOpenTimer_Tick",
        "CheckDesktopOpenRequestAsync",
        "Opened a document saved from the browser.",
        "DesktopOpenPollInterval = TimeSpan.FromSeconds(10)",
        "DesktopOpenRateLimitBackoff = TimeSpan.FromMinutes(1)",
        'exception.ErrorType == "rate_limited"',
    ]
    missing_browser_handoff_features = [
        value
        for value in browser_handoff_features
        if value.casefold() not in source_text.casefold()
    ]
    if missing_browser_handoff_features:
        raise DesktopReaderCheckError(
            "Milestone 9 browser handoff features are missing: "
            f"{missing_browser_handoff_features}"
        )
    clipboard_duplicate_features = [
        "reader_duplicate_document",
        "ClipboardDuplicateDialog",
        "Open existing",
        "Create anyway",
        "Clipboard capture:",
    ]
    missing_clipboard_duplicate_features = [
        value
        for value in clipboard_duplicate_features
        if value.casefold() not in source_text.casefold()
    ]
    if missing_clipboard_duplicate_features:
        raise DesktopReaderCheckError(
            "Clipboard duplicate or error-handling features are missing: "
            f"{missing_clipboard_duplicate_features}"
        )
    document_display_features = [
        "RenameDocumentDialog",
        "Save title",
        "RenameAsync",
        "ReadingBlockTemplate",
        "ReadingBlocksList.Visibility = showReadingView",
    ]
    missing_document_display_features = [
        value
        for value in document_display_features
        if value.casefold() not in source_text.casefold()
    ]
    if missing_document_display_features:
        raise DesktopReaderCheckError(
            "Full-document display or title-editing features are missing: "
            f"{missing_document_display_features}"
        )
    workstation_usability_features = [
        "ContinuousDocumentText",
        "TryGetCharacterOffset",
        "TryMapCrossBlockDeletion",
        "RestorePausedEditorViewport",
        "ShowContinuousEditorHighlight",
        "PlaybackHighlightAdorner",
        "TryGetTrailingCharacterEdge",
        "DrawRangeHighlight",
        "VisualLineRangePlanner.Build",
        'IsInactiveSelectionHighlightEnabled="True"',
        "BringHighlightedTextIntoView",
        "Continuous document text",
        "InvisibleReadingBlockContainerStyle",
        "UseLoadedDocument",
        "Reader will retry automatically in one minute",
        "PlayFromCursorButton",
        "startCursor: cursor",
        "After Stop, starts at the beginning",
        'Topmost="True"',
        'ShowInTaskbar="True"',
        "FollowPlaybackAsync",
        "FindNextSectionAsync",
        "FindPreviousSectionAsync",
        "TotalSections > 1",
        "No next section in this article.",
        "<ApplicationIcon>Assets\\TtsPlatformReader.ico</ApplicationIcon>",
        'Icon="Assets/TtsPlatformReader.ico"',
        "PrimaryButtonStyle",
        "restartFromBeginning: true",
        "Start local TTS service",
        "Stop local TTS service",
        "FindLocalServiceLauncher",
        "ReaderServiceProcessLeaseStore",
        "service-process.json",
        "stopped after reconnecting to it",
        "No unrelated Python process was terminated",
        "DeleteDocumentAsync",
        "Delete selected article",
        "JsonlPlaybackPerformanceSink",
        "SuspectedUnderrunCount",
        "ArticleFindEngine",
        "ArticleFindDocumentLoader",
        "OpenFindPanel",
        "FindPanel.Visibility",
        "Key.F3",
        "ShowFind",
        "FindStart",
        "BringFindTextIntoView",
    ]
    missing_workstation_usability_features = [
        value
        for value in workstation_usability_features
        if value.casefold() not in source_text.casefold()
    ]
    if missing_workstation_usability_features:
        raise DesktopReaderCheckError(
            "Service control, inline editing, or cursor playback features are missing: "
            f"{missing_workstation_usability_features}"
        )
    main_window_source = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (
            reader_root / "src" / "TtsPlatform.Reader.App" / "MainWindow.xaml",
            reader_root / "src" / "TtsPlatform.Reader.App" / "MainWindow.xaml.cs",
        )
    )
    if "_useTextCursorOnNextPlay" in main_window_source:
        raise DesktopReaderCheckError(
            "Implicit caret playback intent is still present."
        )
    return {
        "required_files": len(required),
        "clipboard_features": "implemented",
        "structured_import": "implemented",
        "speech_rules": "implemented",
        "library_workflow": "implemented",
        "browser_handoff": "implemented",
        "clipboard_duplicate_choice": "implemented",
        "full_document_display": "implemented",
        "title_editing": "implemented",
        "inline_editing": "implemented",
        "cursor_playback": "implemented",
        "smart_playback": "implemented",
        "document_section_navigation": "implemented",
        "application_icon": "implemented",
        "service_controls": "implemented",
        "article_deletion": "implemented",
        "playback_performance_logging": "implemented",
        "article_find": "implemented",
    }


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


@contextmanager
def _live_reader_service(repo_root: Path, temporary: Path) -> Iterator[tuple[str, Path]]:
    for source_root in (
        repo_root / "apps" / "tts_service" / "src",
        repo_root / "packages" / "tts_core" / "src",
        repo_root / "packages" / "reader_core" / "src",
        repo_root / "packages" / "document_import" / "src",
        repo_root / "packages" / "speech_rules" / "src",
    ):
        sys.path.insert(0, str(source_root))

    import uvicorn
    from tts_service.config import AppConfig
    from tts_service.main import create_app

    token_path = temporary / "service" / "token.txt"
    reader_home = temporary / "reader"
    config = AppConfig.from_mapping(
        {
            "auth": {"enabled": True, "token_file": str(token_path)},
            "backend": {"mode": "stub"},
            "tts": {"warmup_on_start": False},
            "limits": {"requests_per_minute": 1000},
            "reader": {"enabled": True, "home_path": str(reader_home)},
        }
    )
    app = create_app(config=config, repo_root=temporary)
    port = _free_port()
    server = uvicorn.Server(
        uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning", access_log=False)
    )
    thread = threading.Thread(target=server.run, name="desktop-reader-live-smoke", daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not server.started:
        if not thread.is_alive() or time.monotonic() >= deadline:
            raise DesktopReaderCheckError("The temporary local Reader service did not start.")
        time.sleep(0.05)

    base_url = f"http://127.0.0.1:{port}/"
    try:
        token = token_path.read_text(encoding="utf-8").strip()
        for index in range(2):
            request = urllib.request.Request(
                f"{base_url}v1/reader/documents",
                data=json.dumps(
                    {
                        "title": f"Desktop paging smoke {index + 1}",
                        "source_type": "plain_text",
                        "text": f"Live 😀 paging document {index + 1}.",
                        "allow_duplicate": False,
                    }
                ).encode("utf-8"),
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                },
                method="POST",
            )
            with urllib.request.urlopen(request, timeout=5) as response:
                if response.status != 201:
                    raise DesktopReaderCheckError("A live smoke document could not be created.")
        yield base_url, token_path
    finally:
        server.should_exit = True
        thread.join(timeout=10)
        if thread.is_alive() and sys.exc_info()[0] is None:
            raise DesktopReaderCheckError("The temporary local Reader service did not stop.")


def _check_live_paging(repo_root: Path, dotnet: Path, temporary: Path) -> dict[str, object]:
    smoke_dll = (
        repo_root
        / "apps"
        / "desktop_reader"
        / "tools"
        / "TtsPlatform.Reader.Client.Smoke"
        / "bin"
        / "Release"
        / "net10.0"
        / "TtsPlatform.Reader.Client.Smoke.dll"
    )
    with _live_reader_service(repo_root, temporary) as (base_url, token_path):
        output = _run(
            [str(dotnet), str(smoke_dll), base_url, str(token_path)],
            cwd=repo_root,
        )
        structured_import = _check_live_structured_import(base_url, token_path)
        speech_rules = _check_live_speech_rules(base_url, token_path)
    payload = json.loads(output)
    if payload.get("live_reader_paging") is not True:
        raise DesktopReaderCheckError("The .NET client did not confirm live Reader paging.")
    if payload.get("live_utf16_edit") is not True:
        raise DesktopReaderCheckError("The .NET client did not confirm a live UTF-16 edit.")
    if (
        payload.get("live_reader_stream") is not True
        or payload.get("live_position_resume") is not True
    ):
        raise DesktopReaderCheckError(
            "The .NET client did not confirm Reader WebSocket streaming and durable resume."
        )
    if (
        payload.get("live_clipboard_no_persist") is not True
        or payload.get("live_clipboard_append_undo") is not True
        or payload.get("live_cross_block_delete_undo") is not True
    ):
        raise DesktopReaderCheckError(
            "The .NET client did not confirm private immediate speech and clipboard append/undo."
        )
    payload["live_structured_import"] = structured_import
    payload["live_speech_rules"] = speech_rules
    return payload


def _check_live_structured_import(base_url: str, token_path: Path) -> bool:
    token = token_path.read_text(encoding="utf-8").strip()
    boundary = "----tts-platform-reader-smoke"
    html = (
        b"<html><head><title>Structured smoke</title><script>PRIVATE()</script></head>"
        b"<body><h1>Chapter</h1><p>Readable paragraph.</p></body></html>"
    )
    body = b"".join(
        [
            f"--{boundary}\r\n".encode(),
            b'Content-Disposition: form-data; name="file"; filename="article.htm"\r\n',
            b"Content-Type: text/html\r\n\r\n",
            html,
            f"\r\n--{boundary}--\r\n".encode(),
        ]
    )
    preview_request = urllib.request.Request(
        f"{base_url}v1/reader/imports/preview",
        data=body,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": f"multipart/form-data; boundary={boundary}",
        },
        method="POST",
    )
    with urllib.request.urlopen(preview_request, timeout=10) as response:
        preview = json.load(response)
    warning_codes = {warning["code"] for warning in preview["warnings"]}
    if (
        preview["source_type"] != "html"
        or preview["total_blocks"] != 2
        or "html_active_content_ignored" not in warning_codes
        or "PRIVATE" in json.dumps(preview)
    ):
        raise DesktopReaderCheckError("The live structured-import preview was unsafe or invalid.")

    commit_request = urllib.request.Request(
        f"{base_url}v1/reader/imports/{preview['preview_id']}/commit",
        data=b'{"allow_duplicate":false}',
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(commit_request, timeout=10) as response:
        document = json.load(response)
    if (
        document["source_type"] != "html"
        or not document["metadata"]["import"]["warnings"]
        or document["metadata"]["import"]["network_requests"] != 0
    ):
        raise DesktopReaderCheckError("Structured import warnings were not durable.")

    editable_request = urllib.request.Request(
        f"{base_url}v1/reader/documents/{document['id']}/duplicate-as-editable",
        data=b"",
        headers={"Authorization": f"Bearer {token}"},
        method="POST",
    )
    with urllib.request.urlopen(editable_request, timeout=10) as response:
        editable = json.load(response)
    if editable["source_type"] != "plain_text":
        raise DesktopReaderCheckError("Structured import did not produce an editable copy.")
    return True


def _check_live_speech_rules(base_url: str, token_path: Path) -> bool:
    token = token_path.read_text(encoding="utf-8").strip()
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }

    def send(path: str, payload: dict[str, object]) -> dict[str, object]:
        request = urllib.request.Request(
            f"{base_url}{path}",
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=10) as response:
            return json.load(response)

    rule_set = send("v1/reader/rule-sets", {"name": "Live speech-rule smoke"})
    rule = send(
        f"v1/reader/rule-sets/{rule_set['id']}/rules",
        {
            "name": "Expand API",
            "stage": "pronunciation",
            "rule_type": "literal_replace",
            "pattern": "API",
            "replacement": "A P I",
        },
    )
    preview = send(
        "v1/reader/rules/preview",
        {"text": "API test", "rule_set_ids": [rule_set["id"]]},
    )
    if (
        preview["spoken_text"] != "A P I test"
        or preview["trace"][0]["rule_id"] != rule["id"]
        or len(preview["source_spans"]) != len(preview["spoken_text"])
        or preview["rules_version"] <= 1
    ):
        raise DesktopReaderCheckError("The live speech-rule preview was invalid.")

    timeout_rule = send(
        f"v1/reader/rule-sets/{rule_set['id']}/rules",
        {
            "name": "Timeout guard",
            "stage": "cleanup",
            "rule_type": "regex_replace",
            "pattern": "(a+)+$",
            "replacement": "x",
            "regex_timeout_ms": 1,
            "priority": -100,
        },
    )
    started = time.monotonic()
    guarded = send(
        "v1/reader/rules/preview",
        {"text": "a" * 4_095 + "!", "rule_set_ids": [rule_set["id"]]},
    )
    elapsed = time.monotonic() - started
    if (
        elapsed >= 5
        or not any(
            warning.get("code") == "rule_timeout"
            and warning.get("rule_id") == timeout_rule["id"]
            for warning in guarded["warnings"]
        )
    ):
        raise DesktopReaderCheckError("The live regex timeout guard did not respond safely.")
    return True


def _check_preview_snapshot(repo_root: Path, temporary: Path) -> dict[str, object]:
    output = _run(
        [
            sys.executable,
            str(repo_root / "scripts" / "create_reader_preview_snapshot.py"),
            "--output",
            str(temporary / "preview" / "reader-preview.db"),
        ],
        cwd=repo_root,
    )
    payload = json.loads(output)
    if payload.get("integrity_ok") is not True or payload.get("document_count") != 2:
        raise DesktopReaderCheckError("The Reader preview snapshot is not consistent.")
    return payload


def _check_windows_audio(
    repo_root: Path,
    dotnet: Path,
    *,
    required: bool,
) -> dict[str, object]:
    if os.name != "nt":
        if required:
            raise DesktopReaderCheckError(
                "The required Windows audio smoke cannot run off Windows."
            )
        return {"status": "skipped", "reason": "Windows audio requires Windows"}
    if not required:
        return {"status": "skipped", "reason": "pass --require-windows-audio"}

    smoke_dll = (
        repo_root
        / "apps"
        / "desktop_reader"
        / "tools"
        / "TtsPlatform.Reader.Audio.Smoke"
        / "bin"
        / "Release"
        / "net10.0-windows"
        / "TtsPlatform.Reader.Audio.Smoke.dll"
    )
    payload = json.loads(_run([str(dotnet), str(smoke_dll)], cwd=repo_root))
    if payload.get("windows_audio") is not True:
        raise DesktopReaderCheckError("NAudio did not confirm the default Windows audio endpoint.")
    return {"status": "passed", **payload}


def _check_windows_integration(
    repo_root: Path,
    dotnet: Path,
    *,
    required: bool,
) -> dict[str, object]:
    if os.name != "nt":
        if required:
            raise DesktopReaderCheckError(
                "The required Windows integration smoke cannot run off Windows."
            )
        return {"status": "skipped", "reason": "Windows integration requires Windows"}
    if not required:
        return {"status": "skipped", "reason": "pass --require-windows-integration"}

    smoke_dll = (
        repo_root
        / "apps"
        / "desktop_reader"
        / "tools"
        / "TtsPlatform.Reader.WindowsIntegration.Smoke"
        / "bin"
        / "Release"
        / "net10.0-windows"
        / "TtsPlatform.Reader.WindowsIntegration.Smoke.dll"
    )
    payload = json.loads(_run([str(dotnet), str(smoke_dll)], cwd=repo_root))
    if (
        payload.get("windows_integration") is not True
        or payload.get("clipboard_listener_registered") is not True
        or payload.get("monitoring_off_unregistered") is not True
        or payload.get("monitoring_restart") is not True
        or payload.get("invalid_hotkey_nonfatal") is not True
        or payload.get("clipboard_read_or_write_performed") is not False
    ):
        raise DesktopReaderCheckError(
            "Windows did not confirm the privacy-safe clipboard/hotkey/tray lifecycle."
        )
    return {"status": "passed", **payload}


def _build_development_package(
    repo_root: Path, dotnet: Path, temporary: Path
) -> tuple[Path, dict[str, object]]:
    archive = temporary / "TTSPlatform.Reader-development-win-x64.zip"
    output = _run(
        [
            sys.executable,
            str(repo_root / "scripts" / "package_desktop_reader.py"),
            "--dotnet",
            str(dotnet),
            "--output",
            str(archive),
            "--development-only",
        ],
        cwd=repo_root,
    )
    json_start = output.rfind("{")
    if json_start < 0:
        raise DesktopReaderCheckError("The desktop package command returned no summary.")
    summary = json.loads(output[json_start:])
    with zipfile.ZipFile(archive) as package:
        names = set(package.namelist())
    required = {
        "TtsPlatform.Reader.App.exe",
        "TtsPlatform.Reader.App.dll",
        "TtsPlatform.Reader.App.runtimeconfig.json",
        "THIRD_PARTY_NOTICES.md",
        "DEVELOPMENT-ONLY.txt",
    }
    if not required.issubset(names):
        raise DesktopReaderCheckError(
            f"The desktop package is missing runtime files: {sorted(required - names)}"
        )
    forbidden_names = {"settings.json", "token.txt"}
    forbidden = [
        name for name in names if Path(name).name.casefold() in forbidden_names
    ]
    if forbidden:
        raise DesktopReaderCheckError(
            f"Desktop package contains local secret/settings files: {forbidden}"
        )
    return archive, summary


def _check_wpf_render(archive: Path, temporary: Path) -> dict[str, object]:
    if os.name != "nt":
        return {"status": "skipped", "reason": "WPF render requires Windows"}
    extracted = temporary / "portable"
    with zipfile.ZipFile(archive) as package:
        package.extractall(extracted)
    marker = temporary / "wpf-rendered.json"
    environment = os.environ.copy()
    environment["TTS_PLATFORM_READER_SMOKE_MARKER"] = str(marker)
    _run(
        [str(extracted / "TtsPlatform.Reader.App.exe"), "--smoke-test"],
        cwd=extracted,
        env=environment,
    )
    if not marker.is_file():
        raise DesktopReaderCheckError("The WPF process exited without rendering its main window.")
    payload = json.loads(marker.read_text(encoding="utf-8"))
    if payload.get("rendered") is not True:
        raise DesktopReaderCheckError("The WPF render marker is invalid.")
    return {"status": "passed", "title": payload.get("title")}


def main() -> int:
    args = _parser().parse_args()
    repo_root = Path(__file__).resolve().parents[1]
    try:
        source = _check_source_shape(repo_root)
        dotnet = _resolve_dotnet(
            args.dotnet,
            required=args.require_dotnet or args.require_windows_integration,
        )
        if dotnet is None:
            print(json.dumps({"source": source, "dotnet": "skipped"}, indent=2))
            return 0
        solution = repo_root / "apps" / "desktop_reader" / "TtsPlatform.Reader.sln"
        if not args.skip_build:
            _run([str(dotnet), "restore", str(solution)], cwd=repo_root)
            _run(
                [str(dotnet), "build", str(solution), "-c", "Release", "--no-restore"],
                cwd=repo_root,
            )
            _run(
                [str(dotnet), "test", str(solution), "-c", "Release", "--no-build"],
                cwd=repo_root,
            )
        with tempfile.TemporaryDirectory(prefix="tts-reader-check-") as temporary_value:
            temporary = Path(temporary_value)
            live_paging = _check_live_paging(repo_root, dotnet, temporary)
            preview_snapshot = _check_preview_snapshot(repo_root, temporary)
            windows_audio = _check_windows_audio(
                repo_root,
                dotnet,
                required=args.require_windows_audio or args.require_windows_integration,
            )
            windows_integration = _check_windows_integration(
                repo_root,
                dotnet,
                required=args.require_windows_integration,
            )
            archive, package = _build_development_package(repo_root, dotnet, temporary)
            wpf = _check_wpf_render(archive, temporary)
        print(
            json.dumps(
                {
                    "source": source,
                    "dotnet": str(dotnet),
                    "live_paging": live_paging,
                    "preview_snapshot": preview_snapshot,
                    "windows_audio": windows_audio,
                    "windows_integration": windows_integration,
                    "portable_package": package,
                    "wpf_render": wpf,
                },
                indent=2,
            )
        )
        return 0
    except DesktopReaderCheckError as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
