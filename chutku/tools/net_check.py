"""Internet troubleshooting in plain words: net.check ("is my internet working?") and net.ping.

Read-only. net.check opens a UDP socket without sending (to learn the local address), resolves a
name, fetches Google's 204 connectivity page and (optionally) asks api.ipify.org for the public
address. net.ping runs Windows' own ping.exe with a validated host name, no shell.
"""
from __future__ import annotations

import os
from pathlib import Path
import re
import socket
import subprocess
import time
import urllib.request

from chutku.tools.registry import EMPTY_ARGUMENT_SCHEMA, Risk, Tool, ToolResult, Verification

HOST = re.compile(r"^(?=.{1,253}$)(?!-)[a-z0-9-]{1,63}(?:\.(?!-)[a-z0-9-]{1,63})*$", re.I)


def _local_ip():
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        probe.connect(("8.8.8.8", 80))  # UDP connect sends nothing; it only picks the outgoing interface
        return probe.getsockname()[0]
    except OSError:
        return None
    finally:
        probe.close()


def _timed(function):
    started = time.monotonic()
    try:
        value = function()
        return value, round((time.monotonic() - started) * 1000)
    except Exception:  # every failure is reported as a failed check
        return None, None


def _fetch(url, timeout=5):
    request = urllib.request.Request(url, headers={"User-Agent": "Chutku"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.status, response.read(64)


def diagnose(*, public_ip=True):
    local = _local_ip()
    resolved, dns_ms = _timed(lambda: socket.getaddrinfo("www.google.com", 443)[0][4][0])
    reached, web_ms = _timed(lambda: _fetch("https://www.gstatic.com/generate_204")[0])
    public = None
    if public_ip and reached:
        body, _ = _timed(lambda: _fetch("https://api.ipify.org")[1].decode("ascii", "replace").strip())
        public = body if body and re.fullmatch(r"[0-9a-f.:]{3,45}", body) else None
    if not local or local.startswith("169.254."):
        verdict = "No network connection: Wi-Fi or Ethernet is not connected."
    elif resolved is None:
        verdict = "Connected to the network, but names don't resolve (DNS). Restarting the router usually fixes this."
    elif reached is None:
        verdict = "Connected, but the internet isn't reachable (the router or provider may be down, or a login page is needed)."
    elif web_ms > 1500:
        verdict = f"Internet works but is slow ({web_ms} ms to Google)."
    else:
        verdict = f"Internet works ({web_ms} ms to Google)."
    return {"verdict": verdict, "online": reached is not None, "local_ip": local, "public_ip": public,
            "dns_ok": resolved is not None, "dns_ms": dns_ms, "web_ms": web_ms}


def ping(host, count=4):
    exe = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "PING.EXE"
    done = subprocess.run([str(exe), "-n", str(count), "-w", "2000", host], capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=30,
                          creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    text = done.stdout
    lost = re.search(r"Lost = (\d+)", text)
    average = re.search(r"Average = (\d+)ms", text)
    received = count - int(lost.group(1)) if lost else 0
    return {"host": host, "sent": count, "received": received,
            "average_ms": int(average.group(1)) if average else None,
            "unknown_host": "could not find host" in text.casefold()}


def _check(arguments, context):
    result = diagnose()
    audit = {key: ("[REDACTED]" if "ip" in key.casefold() or "address" in key.casefold() else value)
             for key, value in result.items()} if isinstance(result, dict) else None
    return ToolResult(result, Verification.PASS, audit)   # the public IP stays out of the audit trail


def _ping(arguments, context):
    try:
        result = ping(arguments["host"])
    except (OSError, subprocess.SubprocessError) as error:
        return ToolResult({"error": f"Ping could not run: {error}"}, Verification.FAIL)
    return ToolResult(result, Verification.PASS)


def _validate_none(arguments):
    if arguments != {}:
        raise ValueError("This takes no arguments.")


def _validate_ping(arguments):
    if set(arguments) != {"host"} or not isinstance(arguments["host"], str) or not HOST.match(arguments["host"]):
        raise ValueError("Give a host name like google.com.")


def register_net_check_tools(registry):
    registry.register(Tool("net.check", "Check whether the internet works and explain any problem in plain words "
        "(network connection, DNS, reachability, speed), with local and public IP.", Risk.OBSERVATION, _check,
        _validate_none, argument_schema=EMPTY_ARGUMENT_SCHEMA, reversibility="not_applicable",
        success_predicate="connectivity_checks_completed", network_egress=True))
    registry.register(Tool("net.ping", "Ping a host name (e.g. google.com) 4 times and report replies and average time.",
        Risk.OBSERVATION, _ping, _validate_ping, argument_schema={"type": "object", "properties": {
            "host": {"type": "string", "minLength": 1, "maxLength": 253}}, "required": ["host"],
            "additionalProperties": False},
        reversibility="not_applicable", success_predicate="ping_completed", network_egress=True))
