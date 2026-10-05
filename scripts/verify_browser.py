"""Real local-only Playwright inspection and semantic workflow proof."""
from __future__ import annotations
from datetime import UTC, datetime
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import sys
import tempfile
from threading import Thread
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from chutku.app import PROJECT_ROOT, create_runtime
from chutku.evidence import source_digest

def reviewed(runtime, tool, arguments):
    pending=runtime.run(tool, arguments)
    return runtime.approve(pending["approval"]["token"]) if str(pending.get("state"))=="WAITING_CONFIRMATION" else pending

def main():
    fixture=PROJECT_ROOT/"tests/fixtures"
    server=ThreadingHTTPServer(("127.0.0.1",0),partial(SimpleHTTPRequestHandler,directory=str(fixture)))
    thread=Thread(target=server.serve_forever,daemon=True); thread.start()
    url=f"http://127.0.0.1:{server.server_port}/browser_fixture.html"; checks=[]
    try:
        with tempfile.TemporaryDirectory(prefix="chutku-browser-") as temp, create_runtime(Path(temp)) as runtime:
            denied=runtime.run("browser.inspect",{"url":url,"browser":"edge"})
            checks.append({"check":"browser_denied_without_capability","passed":str(denied.get("state"))=="DENIED"})
            runtime.capability_grants.grant("browser.navigate")
            inspected=runtime.run("browser.inspect",{"url":url,"browser":"edge"})
            checks.append({"check":"real_local_page_inspected","passed":str(inspected.get("state"))=="COMPLETED" and inspected.get("output",{}).get("title")=="Chutku Browser Fixture"})
            runtime.capability_grants.grant("browser.input")
            steps=[
              {"action":"fill","locator":{"by":"label","value":"Name"},"text":"Ada","expect":{"locator":{"by":"label","value":"Name"},"property":"value","expected":"Ada"}},
              {"action":"select","locator":{"by":"test_id","value":"choice"},"option":"Beta","expect":{"locator":{"by":"test_id","value":"choice"},"property":"value","expected":"Beta"}},
              {"action":"click","locator":{"by":"role","role":"button","value":"Run"},"expect":{"locator":{"by":"test_id","value":"status"},"property":"text","expected":"Ran Ada Beta"}}]
            result=reviewed(runtime,"browser.workflow",{"url":url,"browser":"edge","steps":steps})
            workflow_passed=str(result.get("state"))=="COMPLETED" and result.get("output",{}).get("steps_completed")==3
            checks.append({"check":"real_semantic_workflow_postconditions","passed":workflow_passed,
                           "failure":None if workflow_passed else result.get("error") or result.get("output",{}).get("error")})
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=5)
        checks.append({"check":"local_fixture_cleanup","passed":not thread.is_alive()})
    report={"timestamp_utc":datetime.now(UTC).isoformat(),"source_sha256":source_digest(PROJECT_ROOT),"passed":all(x["passed"] for x in checks),"checks":checks,"scope":"Item 6 real Playwright against a local disposable fixture using installed Microsoft Edge."}
    (PROJECT_ROOT/"verification/browser.json").write_text(json.dumps(report,indent=2),encoding="utf-8")
    print(json.dumps(report,indent=2)); raise SystemExit(0 if report["passed"] else 1)

if __name__=="__main__": main()
