"""Action Lab (App Mastery A2): prove each app action on this PC before Chutku trusts it.

Each action runs through the normal runtime (policy, action log) with its `drill` parameters, `runs` times. Its own
check decides pass/fail. After `VERIFY_AFTER` passes in a row the action is **verified**; one failure makes it
unverified again. Results live in data/apps/<app>/lab.json and every run is also written to the reliability ledger
(S16). Only verified actions get instant phrase routing (A3).

Lab rules (the owner's PC is real, not a sandbox):
- only `safe` actions by default; `changes` only with include_changes (they add things to the owner's apps);
  `consequential` and `destructive` actions are never run by the lab;
- actions marked `"lab": {"skip": "..."}` are skipped with that reason (e.g. quitting the app mid-lab);
- `"lab": {"pair": true}` toggles (shuffle) run twice per try so the app ends as it started; `"pair": 2` for a
  three-way cycle (repeat: off, all, one);
- `"lab": {"setup": "<action id>"}` runs that (parameterless, safe) action before each try, `"after"` after it
  (e.g. close the tab the action opened);
- music that was paused before the lab is paused again afterwards.
"""
from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
import statistics
import time

VERIFY_AFTER = 3
LAB_RISKS = {"safe"}


def lab_path(base, app):
    return Path(base) / "data" / "apps" / app / "lab.json"


def load(base, app):
    try:
        return json.loads(lab_path(base, app).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"app": app, "actions": {}}


def verified(base, app, action_id):
    entry = load(base, app)["actions"].get(action_id) or {}
    return bool(entry.get("verified"))


def verified_actions(base):
    """{app: {action ids}} that the lab has verified."""
    folder = Path(base) / "data" / "apps"
    found = {}
    for path in folder.glob("*/lab.json") if folder.exists() else []:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        found[data.get("app", path.parent.name)] = {a for a, e in data.get("actions", {}).items() if e.get("verified")}
    return found


def failed_actions(base):
    """{app: {action ids}} whose latest lab run failed."""
    folder = Path(base) / "data" / "apps"
    found = {}
    for path in folder.glob("*/lab.json") if folder.exists() else []:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        found[data.get("app", path.parent.name)] = {
            a for a, e in data.get("actions", {}).items() if e.get("runs") and not e["runs"][-1].get("ok")}
    return found


def _record(state, action_id, ok, seconds, error, now):
    entry = state["actions"].setdefault(action_id, {"runs": [], "streak": 0, "verified": False})
    entry["runs"] = (entry["runs"] + [{"at": now, "ok": ok, "seconds": seconds, **({"error": error} if error else {})}])[-20:]
    entry["streak"] = entry["streak"] + 1 if ok else 0
    entry["verified"] = entry["streak"] >= VERIFY_AFTER
    if not ok:
        entry["last_error"] = error
    return entry


def run_lab(base, runtime, atlas, *, only=None, runs=VERIFY_AFTER, include_changes=False, media=None, pause=1.0):
    """Run the lab for one app. Returns a report {"app", "tried", "verified", "skipped", "failed", "median_seconds"}."""
    from chutku.core.ledger import target_key
    app = atlas["app"]
    allowed = LAB_RISKS | ({"changes"} if include_changes else set())
    state = load(base, app)
    state["app"] = app
    if media is None:
        from chutku.tools.everyday import media
    try:
        was = media("status") or {}
    except OSError:
        was = {}
    report = {"app": app, "tried": [], "skipped": {}, "failed": {}, "seconds": []}
    for action in atlas["actions"]:
        action_id = action["id"]
        if only and action_id not in only:
            continue
        lab = action.get("lab") or {}
        if lab.get("skip"):
            report["skipped"][action_id] = lab["skip"]
            continue
        if action["risk"] not in allowed:
            report["skipped"][action_id] = f"{action['risk']} actions are not run by the lab"
            continue
        params = action.get("drill") or {}
        if set(action.get("params") or {}) - set(params):
            report["skipped"][action_id] = "no drill values for its parameters"
            continue
        tool = f"app.{app}.{action_id}"
        report["tried"].append(action_id)
        for _ in range(runs):
            if lab.get("setup"):
                runtime.run(f"app.{app}.{lab['setup']}", {})   # e.g. "next" first, so "previous" has a song to go back to
                time.sleep(pause)
            started = time.monotonic()
            result = runtime.run(tool, params)
            if lab.get("pair") and str(result.get("state")) == "COMPLETED":
                for _ in range(1 if lab["pair"] is True else int(lab["pair"])):
                    runtime.run(tool, params)   # toggle back to where it started
            if lab.get("after"):
                runtime.run(f"app.{app}.{lab['after']}", {})   # tidy up, e.g. close the tab the action opened
            output = result.get("output") or {}
            ok = str(result.get("state")) == "COMPLETED" and bool(output.get("ok"))
            seconds = output.get("seconds") or round(time.monotonic() - started, 2)
            error = None if ok else (output.get("error") or result.get("reason") or result.get("error")
                                     or str(result.get("state")))
            _record(state, action_id, ok, seconds, error, datetime.now().isoformat(timespec="seconds"))
            try:
                runtime.ledger.record(tool, target_key(tool, params), expected="check passes",
                                      observed="ok" if ok else str(error)[:180], verdict="PASS" if ok else "FAIL",
                                      seconds=seconds, autonomy="lab")
            except Exception:
                pass
            report["seconds"].append(seconds)
            if not ok:
                report["failed"][action_id] = error
                break   # a failing action is not hammered
            time.sleep(pause)
    if was.get("status") in {"Paused", "Stopped"}:
        try:
            if (media("status") or {}).get("status") == "Playing":
                media("pause")
        except OSError:
            pass
    path = lab_path(base, app)
    path.parent.mkdir(parents=True, exist_ok=True)
    state["updated"] = datetime.now().isoformat(timespec="seconds")
    path.write_text(json.dumps(state, indent=1, ensure_ascii=False), encoding="utf-8")
    report["verified"] = sorted(a for a, e in state["actions"].items() if e.get("verified"))
    report["median_seconds"] = round(statistics.median(report["seconds"]), 2) if report["seconds"] else None
    report.pop("seconds")
    report["total_actions"] = len(atlas["actions"])
    return report


def describe(report):
    lines = [f"{report['app']}: {len(report['verified'])}/{report['total_actions']} actions verified"
             + (f", median {report['median_seconds']} s" if report["median_seconds"] is not None else "")]
    for action_id, error in report["failed"].items():
        lines.append(f"  FAILED {action_id}: {error}")
    for action_id, why in report["skipped"].items():
        lines.append(f"  skipped {action_id}: {why}")
    return "\n".join(lines)
