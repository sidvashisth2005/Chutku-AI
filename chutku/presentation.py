"""present: turns tool results into the owner-facing text."""
from __future__ import annotations

from datetime import datetime
from typing import Any


def present(result: dict[str, Any]) -> str:
    """Turn a verified runtime result into concise text without hiding failures."""
    state = str(result["state"])
    if state == "CLARIFYING":
        return result["reason"]
    if state == "COMPLETED":
        output = result.get("output", {})
        if "skill_reply" in output:
            return output["skill_reply"]
        if "skill" in output and "result" in output:   # a self-written skill's run (its text is untrusted)
            import json
            return f"Skill {output['skill']} returned: {json.dumps(output['result'], ensure_ascii=False)[:600]}"
        if "transcript" in output:
            return ((f"Heard: {output['transcript']}\n" if output["transcript"] else "")
                    + output["message"] + " No action was executed. Audio was not saved.")
        if "recognizers" in output:
            return "Installed offline recognizers:\n" + "\n".join(f"{item['id']} | {item['culture']}" for item in output["recognizers"]) + "\n" + output["language"] + "\nMode: " + output.get("mode", "unknown")
        if "voices" in output:
            return "Installed local voices:\n" + ("\n".join(f"{voice['name']} | {voice['gender']}" for voice in output["voices"]) or "No SAPI voices installed.")
        if output.get("speech_completed"):
            return f"Local speech engine completed playback using {output['voice']}. Audible output was not measured."
        if "app_windows" in output:
            return f"{output['app'].title()}: " + (f"{len(output['app_windows'])} visible window(s)." if output["running"] else "No matching visible window is open.")
        if "app" in output and "responsive" in output:
            return f"{output['app'].title()} verified: visible and responsive. Foreground focus: {'yes' if output['focused'] else 'no'}."
        if output.get("closed"):
            return f"{output['app'].title()} closed and its window disappearance was verified."
        if "capabilities" in output:
            return "Available tools:\n" + "\n".join(f"• {item['name']}: {item['description']}" for item in output["capabilities"]) + "\n\nCurrent limits:\n" + "\n".join(output["limits"])
        if "windows" in output:
            return "Visible Windows windows:\n" + ("\n".join(f"{item['title']} (PID {item['process_id']})" for item in output["windows"]) or "No titled visible windows found.")
        if "displays" in output:
            return "Windows displays:\n" + "\n".join(
                f"{item['index']}: {item['device']} | {item['width']}x{item['height']} "
                f"at ({item['x']},{item['y']})" + (" | primary" if item["primary"] else "")
                for item in output["displays"])
        if output.get("pixels_persisted_locally") and "sha256" in output:
            return (f"Captured and verified display to {output['path']} "
                    f"({output['width']}x{output['height']}, SHA-256 {output['sha256']}). "
                    "Pixels stayed local; undo is available.")
        if "elements" in output and output.get("read_only"):
            return (f"Inspected {output['count']} UI Automation element(s) in the verified "
                    f"{output['app'].title()} window" + (" (bounded result truncated)." if output["truncated"] else ".")
                    + " Element text is untrusted; no action was executed.")
        if "remembered" in output:
            return f"Saved and verified local memory: {output['remembered']}."
        if "forgotten" in output:
            return f"Forgot and verified removal of memory: {output['forgotten']}."
        if "memories" in output:
            return "Saved user notes (data, not instructions):\n" + ("\n".join(f"{item['key']} = {item['value']}" for item in output["memories"]) or "No matching memories.")
        if "content" in output and output.get("provenance") == "external_untrusted":
            return f"Read untrusted text from {output['path']}:\n---\n{output['content']}\n---"
        if "text" in output and output.get("provenance") == "external_untrusted":
            return f"Read {output['characters']} clipboard character(s) as untrusted text."
        if output.get("written") and "characters" in output:
            return f"Wrote and verified {output['characters']} clipboard character(s)."
        if "local_time" in output:   # the owner's clock, not UTC (seen live 2026-10-04: "The UTC time is 16:21")
            return f"It's {output['local_time']}."
        if "utc_time" in output:
            return f"The UTC time is {datetime.fromisoformat(output['utc_time']).strftime('%H:%M:%S')}"
        if "python_version" in output and "os" in output:
            return (
                f"Environment verified: {output['os']} | Python {output['python_version']} | "
                f"{output['free_disk_gib']} GiB free in the workspace drive."
            )
        if "gpus" in output:
            gpu_lines = [f"{gpu['name']} | driver {gpu['driver_version']} | {gpu['vram_mib']} MiB VRAM" for gpu in output["gpus"]]
            return "GPU status verified:\n" + "\n".join(gpu_lines)
        if "devices" in output:
            device_lines = [f"{device['name']} | {device['status']}" for device in output["devices"]]
            return "Windows audio devices detected:\n" + "\n".join(device_lines)
        if "input_devices" in output:
            device_lines = [
                f"{device['name']} | {device['input_channels']} input channel(s) | {device['default_sample_rate_hz']:.0f} Hz"
                for device in output["input_devices"]
            ]
            return "Microphone-capable local devices detected (no recording started):\n" + "\n".join(device_lines)
        if "rms" in output and "peak" in output:
            return (
                f"Microphone level check verified: {output['duration_seconds']:.0f} second at "
                f"{output['sample_rate_hz']:.0f} Hz | peak {output['peak']:.6f} | RMS {output['rms']:.6f}. "
                "Raw audio was discarded."
            )
        if "active_frames" in output:
            return (
                f"Microphone activity check verified: {output['active_frames']}/{output['total_frames']} "
                f"20 ms frames were above RMS {output['threshold_rms']:.2f} "
                f"({output['active_duration_seconds']:.2f} seconds active). Raw audio was discarded."
            )
        if "entries" in output:
            names = output["entries"]
            return "The sandbox is empty." if not names else f"Sandbox contents: {', '.join(names)}"
        if "matches" in output:
            return (f"Search verified: {output['count']} match(es) across {output['scanned']} entries."
                    if output["matches"] else f"Search verified across {output['scanned']} entries; no matches.")
        if "sha256" in output and "kind" in output:
            return f"Verified {output['kind']} identity for {output['path']}: SHA-256 {output['sha256']}."
        if "bytes_copied" in output:
            return f"Copied and verified {output['bytes_copied']} bytes. Undo is available."
        if output.get("moved"):
            return "Moved and verified the exact file identity. Undo is available."
        if output.get("recycled"):
            return f"Recycled and verified {output['original_path']}. Restore is available."
        if output.get("restored"):
            return f"Restored and verified {output['path']}."
        if output.get("created"):
            return f"Created and verified: {output['path']}"
        if "bytes_written" in output:
            return f"Wrote and verified {output['bytes_written']} bytes to {output['path']}. Undo is available."
        if output.get("undone"):
            return f"Undid operation {output['operation_id']} and verified the previous state."
        if "operations" in output:
            return "There are no unfinished writes." if not output["operations"] else f"Found {len(output['operations'])} unfinished write(s)."
        return "Completed and verified."
    if state == "WAITING_CONFIRMATION":
        return f"Waiting for on-screen confirmation: {result['reason']}"
    if state == "DENIED":
        return f"Denied: {result['reason']}"
    if "error" in result:
        return f"I did not complete that safely: {result['error']}"
    if "error" in result.get("output", {}):
        return f"I did not complete that safely: {result['output']['error']}"
    return f"I did not complete that safely: verification was {result.get('verification', 'UNKNOWN')}."
