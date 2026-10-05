"""Deterministic 1,200-request reliability benchmark across success and refusal paths."""
from __future__ import annotations
from datetime import UTC, datetime
import json
from pathlib import Path
import statistics
import sys
import tempfile
import time
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from chutku.app import PROJECT_ROOT, create_runtime
from chutku.evidence import source_digest
from chutku.orchestration import OrchestrationCoordinator

def main():
    categories={}; latencies=[]; failures=[]
    def record(category,index,started,passed,observed):
        latencies.append((time.perf_counter()-started)*1000)
        item=categories.setdefault(category,{"total":0,"passed":0}); item["total"]+=1; item["passed"]+=int(passed)
        if not passed and len(failures)<20: failures.append({"category":category,"index":index,"observed":observed})
    with tempfile.TemporaryDirectory(prefix="chutku-reliability-") as temp, create_runtime(Path(temp)) as runtime:
      runtime.capability_grants.grant("desktop.input")
      for i in range(200):
        started=time.perf_counter(); result=runtime.run("system.get_time",{}); record("read_success",i,started,str(result.get("state"))=="COMPLETED",str(result.get("state")))
      for i in range(200):
        started=time.perf_counter(); result=runtime.run("filesystem.create_directory",{"path":f"bench-{i:03d}"}); ok=str(result.get("state"))=="COMPLETED" and (runtime.granted_root/f"bench-{i:03d}").is_dir(); record("verified_local_effect",i,started,ok,str(result.get("state")))
      for i in range(200):
        started=time.perf_counter(); result=runtime.run("system.get_time",{"unexpected":i}); record("malformed_input_refused",i,started,str(result.get("state"))=="FAILED",str(result.get("state")))
      for i in range(200):
        started=time.perf_counter(); result=runtime.run("screen.displays",{}); record("missing_capability_denied",i,started,str(result.get("state"))=="DENIED",str(result.get("state")))
      for i in range(200):
        started=time.perf_counter(); pending=runtime.run("apps.close",{"app":"calculator"}); result=runtime.approve(pending["approval"]["token"],cancel=True) if str(pending.get("state"))=="WAITING_CONFIRMATION" else pending; record("review_cancelled",i,started,str(result.get("state"))=="DENIED",str(result.get("state")))
      coordinator=OrchestrationCoordinator(runtime)
      for i in range(200):
        started=time.perf_counter(); prepared=coordinator.prepare([{"tool":"system.get_time","arguments":{},"compensation":None}]); first=coordinator.execute(prepared["token"])
        try: coordinator.execute(prepared["token"]); replay=False
        except ValueError: replay=True
        record("orchestration_single_use",i,started,first.get("state")=="COMPLETED" and replay,first.get("state"))
    total=sum(x["total"] for x in categories.values()); passed=sum(x["passed"] for x in categories.values())
    ordered=sorted(latencies); p95=ordered[min(len(ordered)-1,int(len(ordered)*.95))]
    report={"timestamp_utc":datetime.now(UTC).isoformat(),"source_sha256":source_digest(PROJECT_ROOT),"passed":total>=1000 and passed==total,
            "requests":total,"correct":passed,"accuracy":passed/total,"categories":categories,"failures":failures,
            "latency_ms":{"median":statistics.median(latencies),"p95":p95,"maximum":max(latencies)},
            "scope":"1,200 deterministic runtime requests; not a human-language or arbitrary-PC-task success benchmark."}
    (PROJECT_ROOT/"verification/reliability-1200.json").write_text(json.dumps(report,indent=2),encoding="utf-8")
    print(json.dumps(report,indent=2)); raise SystemExit(0 if report["passed"] else 1)

if __name__=="__main__": main()
