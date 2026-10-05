"""Real-desktop verification of everyday tools (apps, files, web, windows, media).

Uses a temporary state directory with its own grants so the owner's grants are
untouched. Opens and closes Calculator and a Notepad document it creates; opens
one web-search tab in the default browser (left open so no user tab is closed).
"""
from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from chutku.app import create_runtime  # noqa: E402
from chutku.evidence import source_digest  # noqa: E402


def main():
    checks = []

    def check(name, passed, detail=""):
        checks.append({"check": name, "passed": bool(passed), "detail": detail})
        print(("PASS " if passed else "FAIL ") + name, detail, flush=True)

    with tempfile.TemporaryDirectory() as temp, create_runtime(Path(temp)) as runtime:
        grants = runtime.capability_grants
        denied = runtime.run("apps.launch", {"name": "Calculator"})
        check("launch_denied_without_capability", str(denied["state"]) == "DENIED")
        for capability in ("apps.launch", "browser.navigate", "desktop.input", "audio.observe"):
            grants.grant(capability)

        installed = runtime.run("apps.installed", {"query": "calc"})
        names = [a["name"] for a in installed.get("output", {}).get("apps", [])]
        check("installed_apps_listed", str(installed["state"]) == "COMPLETED" and "Calculator" in names, str(names))

        launched = runtime.run("apps.launch", {"name": "Calculator"})
        window = launched.get("output", {}).get("window", {})
        check("launch_calculator_verified_window", str(launched["state"]) == "COMPLETED" and window,
              f"{launched.get('output', {}).get('observed')} pid={window.get('process_id')}")
        if window:
            identity = {k: window[k] for k in ("window_id", "process_id", "executable")}
            time.sleep(0.5)
            minimized = runtime.run("windows.manage", identity | {"action": "minimize"})
            check("minimize_read_back", str(minimized["state"]) == "COMPLETED")
            restored = runtime.run("windows.manage", identity | {"action": "restore"})
            check("restore_read_back", str(restored["state"]) == "COMPLETED")
            wrong = runtime.run("windows.manage", identity | {"process_id": identity["process_id"] + 1,
                                                               "action": "minimize"})
            check("changed_identity_refused", str(wrong["state"]) == "FAILED")
            pending = runtime.run("windows.close", identity)
            check("close_requires_confirmation", str(pending["state"]) == "WAITING_CONFIRMATION")
            if str(pending["state"]) == "WAITING_CONFIRMATION":
                closed = runtime.approve(pending["approval"]["token"])
                check("close_verified_after_approval", str(closed["state"]) == "COMPLETED")

        document = runtime.granted_root / "chutku-open-test.txt"
        document.write_text("Opened by Chutku verification.", encoding="utf-8")
        opened = runtime.run("files.open", {"path": document.name})
        doc_window = opened.get("output", {}).get("window", {})
        check("file_opened_in_default_app", str(opened["state"]) == "COMPLETED",
              str(doc_window.get("executable")))
        if doc_window and "notepad" in (doc_window.get("executable") or "").casefold():
            pending = runtime.run("windows.close", {k: doc_window[k] for k in ("window_id", "process_id", "executable")})
            if str(pending["state"]) == "WAITING_CONFIRMATION":
                runtime.approve(pending["approval"]["token"])

        script = runtime.granted_root / "evil.bat"
        script.write_text("echo no", encoding="utf-8")
        refused = runtime.run("files.open", {"path": script.name})
        check("script_open_refused", str(refused["state"]) == "FAILED")
        uninstall = runtime.run("apps.launch", {"name": "Uninstall"})
        check("uninstaller_or_ambiguous_refused", str(uninstall["state"]) == "FAILED")
        bad_url = runtime.run("web.open", {"url": "file:///C:/Windows/win.ini"})
        check("non_http_url_refused", str(bad_url["state"]) == "FAILED")

        searched = runtime.run("web.search", {"query": "Chutku local Windows agent", "site": "duckduckgo"})
        check("web_search_browser_window", str(searched["state"]) == "COMPLETED",
              str(searched.get("output", {}).get("browser")))
        status = runtime.run("media.status", {})
        check("media_status_read", str(status["state"]) == "COMPLETED", json.dumps(status.get("output", {}).get("session")))

    report = {"generated_at": datetime.now(UTC).isoformat(), "source_digest": source_digest(ROOT),
              "passed": all(c["passed"] for c in checks), "checks": checks,
              "scope": "Real desktop: installed-app launch, exact window manage/close, default-app file open, "
                       "default-browser search, media status, and negative boundaries."}
    (ROOT / "verification/everyday.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"{sum(c['passed'] for c in checks)}/{len(checks)} passed")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
