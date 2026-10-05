"""Real cross-component failure and reverse recovery using theme plus Edge inspection."""
from __future__ import annotations
from datetime import UTC, datetime
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import sys
import tempfile
from threading import Thread
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from chutku.app import PROJECT_ROOT, create_runtime
from chutku.evidence import source_digest
from chutku.orchestration import OrchestrationCoordinator
from chutku.tools.windows_settings import _invoke as theme_invoke

def main():
    original=theme_invoke({"action":"get"}); checks=[]
    if original.get("apps")!=original.get("system"): raise SystemExit("Mixed theme cannot be safely fixture-restored.")
    target="dark" if original["apps"]=="light" else "light"
    server=ThreadingHTTPServer(("127.0.0.1",0),partial(SimpleHTTPRequestHandler,directory=str(PROJECT_ROOT/"tests/fixtures")))
    thread=Thread(target=server.serve_forever,daemon=True); thread.start()
    url=f"http://127.0.0.1:{server.server_port}/browser_fixture.html"
    try:
      with tempfile.TemporaryDirectory(prefix="chutku-orchestration-") as temp, create_runtime(Path(temp)) as runtime:
        runtime.capability_grants.grant("settings.modify"); runtime.capability_grants.grant("browser.navigate")
        coordinator=OrchestrationCoordinator(runtime)
        prepared=coordinator.prepare([
          {"tool":"settings.theme_set","arguments":{"mode":target},"compensation":{"tool":"settings.theme_restore","arguments":{}}},
          {"tool":"browser.inspect","arguments":{"url":url,"browser":"edge"},"compensation":None},
          {"tool":"browser.inspect","arguments":{"url":"http://127.0.0.1:1/unreachable","browser":"edge"},"compensation":None}])
        checks.append({"check":"server_owned_review_token_created","passed":prepared.get("single_use") is True and len(prepared.get("token",""))>=32})
        result=coordinator.execute(prepared["token"],approve=lambda approval:True)
        checks.append({"check":"failure_stopped_forward_plan","passed":result.get("state")=="FAILED" and [x["state"] for x in result.get("forward",[])]==["COMPLETED","COMPLETED","FAILED"]})
        checks.append({"check":"declared_reverse_recovery_completed","passed":result.get("recovered") is True and result.get("recovery",[{}])[0].get("tool")=="settings.theme_restore"})
        try: coordinator.execute(prepared["token"]); replay=False
        except ValueError: replay=True
        checks.append({"check":"review_token_replay_refused","passed":replay})
    finally:
      server.shutdown(); server.server_close(); thread.join(timeout=5)
      final=theme_invoke({"action":"get"})
      if final!=original: theme_invoke({"action":"set","mode":original["apps"]}); final=theme_invoke({"action":"get"})
      checks.append({"check":"original_theme_and_fixture_cleanup_verified","passed":final==original and not thread.is_alive()})
    report={"timestamp_utc":datetime.now(UTC).isoformat(),"source_sha256":source_digest(PROJECT_ROOT),"passed":all(x["passed"] for x in checks),"checks":checks,"scope":"Item 7 real settings-plus-browser orchestration failure with declared reverse recovery."}
    (PROJECT_ROOT/"verification/orchestration.json").write_text(json.dumps(report,indent=2),encoding="utf-8")
    print(json.dumps(report,indent=2)); raise SystemExit(0 if report["passed"] else 1)

if __name__=="__main__": main()
