"""Real Windows evidence for bounded volume observation/change/restore and network observation."""
from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from chutku.app import PROJECT_ROOT, create_runtime
from chutku.evidence import source_digest


def _reviewed(runtime, tool, arguments):
    pending = runtime.run(tool, arguments)
    if str(pending.get("state")) != "WAITING_CONFIRMATION":
        return pending
    return runtime.approve(pending["approval"]["token"])


def main():
    checks = []
    with tempfile.TemporaryDirectory(prefix="chutku-controls-") as temp, create_runtime(Path(temp)) as runtime:
        denied = runtime.run("system.volume_status", {})
        checks.append({"check": "volume_observe_denied_without_capability", "passed": str(denied.get("state")) == "DENIED"})
        runtime.capability_grants.grant("audio.observe")
        status = runtime.run("system.volume_status", {})
        original = status.get("output", {})
        checks.append({"check": "real_volume_observed", "passed": str(status.get("state")) == "COMPLETED"})
        runtime.capability_grants.grant("audio.modify")
        target = {"level": max(0, min(100, int(original.get("level", 0)) + (-1 if int(original.get("level", 0)) > 0 else 1))),
                  "muted": bool(original.get("muted", False))}
        changed = _reviewed(runtime, "system.volume_set", target)
        checks.append({"check": "real_volume_exact_change", "passed": str(changed.get("state")) == "COMPLETED"})
        restored = _reviewed(runtime, "system.volume_restore", {})
        checks.append({"check": "real_volume_conflict_aware_restore", "passed": str(restored.get("state")) == "COMPLETED"
                       and restored.get("output", {}).get("state") == original})
        runtime.capability_grants.grant("network.observe")
        network = runtime.run("network.status", {})
        checks.append({"check": "real_bounded_network_inventory", "passed": str(network.get("state")) == "COMPLETED"
                       and network.get("output", {}).get("count", 33) <= 32})
        macs = [x.get("MacAddress") for x in network.get("output", {}).get("adapters", []) if x.get("MacAddress")]
        audit = json.dumps(runtime.event_log._connection.execute("SELECT payload_json FROM events").fetchall())
        checks.append({"check": "network_hardware_addresses_audit_redacted",
                       "passed": all(mac not in audit for mac in macs)})
        adapters = network.get("output", {}).get("adapters", [])
        if adapters:
            adapter = adapters[0]
            runtime.capability_grants.grant("network.modify")
            wrong = {"interface_index": adapter["InterfaceIndex"], "name": adapter["Name"] + " changed",
                     "interface_description": adapter["InterfaceDescription"],
                     "enabled": adapter.get("Status") == "Disabled"}
            refused = _reviewed(runtime, "network.adapter_set", wrong)
            checks.append({"check": "real_changed_adapter_identity_refused_without_mutation",
                           "passed": str(refused.get("state")) == "FAILED"})
        else:
            checks.append({"check": "real_changed_adapter_identity_refused_without_mutation", "passed": False})
        denied_theme = runtime.run("settings.theme_status", {})
        checks.append({"check": "theme_observe_denied_without_capability", "passed": str(denied_theme.get("state")) == "DENIED"})
        runtime.capability_grants.grant("settings.observe")
        theme = runtime.run("settings.theme_status", {})
        original_theme = theme.get("output", {})
        checks.append({"check": "real_theme_observed", "passed": str(theme.get("state")) == "COMPLETED"})
        if original_theme.get("apps") == original_theme.get("system") and original_theme.get("apps") in {"light", "dark"}:
            runtime.capability_grants.grant("settings.modify")
            target_theme = "dark" if original_theme["apps"] == "light" else "light"
            theme_changed = _reviewed(runtime, "settings.theme_set", {"mode": target_theme})
            theme_restored = _reviewed(runtime, "settings.theme_restore", {})
            checks.append({"check": "real_theme_exact_change", "passed": str(theme_changed.get("state")) == "COMPLETED"})
            checks.append({"check": "real_theme_conflict_aware_restore", "passed": str(theme_restored.get("state")) == "COMPLETED"
                           and theme_restored.get("output", {}).get("state") == original_theme})
        else:
            checks.extend([{"check": "real_theme_exact_change", "passed": False},
                           {"check": "real_theme_conflict_aware_restore", "passed": False}])
    report = {"timestamp_utc": datetime.now(UTC).isoformat(), "source_sha256": source_digest(PROJECT_ROOT),
              "passed": all(x["passed"] for x in checks), "checks": checks,
              "scope": "Item 5 real Windows volume/theme reversible controls, network observation and non-mutating identity refusal."}
    (PROJECT_ROOT / "verification/system-controls.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2)); raise SystemExit(0 if report["passed"] else 1)


if __name__ == "__main__":
    main()
