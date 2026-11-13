"""Load, stress, spike and soak test of the account relay (Security & Testing Checklist, Part 3).

    python scripts/load_test_relay.py                      # load + stress ramp + recovery, about a minute
    python scripts/load_test_relay.py --soak-minutes 30    # also hold normal load for 30 minutes (memory growth)
    python scripts/load_test_relay.py --json out.json      # the numbers as JSON (benchmarking between versions)

A real RelayServer runs on 127.0.0.1 with a temporary database. Simulated users are threads with their own
connections: half sign-in checks (GET /relay/me) and half full phone -> relay -> laptop -> phone round trips
(POST /t/e2e), answered by fake laptops that long-poll and reply like chutku/relay/client.py. Each level reports
throughput, error rate and p50/p95/p99 latency, plus the relay's memory. The relay is the only Chutku server that
many people share; the dashboard and phone server serve one owner on loopback/tailnet.
"""
from __future__ import annotations

import argparse
import ctypes
import http.client
import json
from pathlib import Path
import statistics
import sys
from tempfile import TemporaryDirectory
import threading
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from chutku.relay import server as relay_server  # noqa: E402

ENVELOPE = {"v": 1, "iv": "AAAAAAAAAAAAAAAA", "ct": "c2VhbGVk"}


def rss_mb():
    """This process's working set in MB (Windows), else 0."""
    try:
        from ctypes import wintypes

        class Counters(ctypes.Structure):
            _fields_ = [("cb", wintypes.DWORD), ("faults", wintypes.DWORD)] + \
                       [(n, ctypes.c_size_t) for n in ("peak", "working", "qpp", "qp", "qnpp", "qnp", "page",
                                                      "peak_page")]
        counters = Counters()
        counters.cb = ctypes.sizeof(counters)
        kernel32, psapi = ctypes.WinDLL("kernel32"), ctypes.WinDLL("psapi")
        kernel32.GetCurrentProcess.restype = wintypes.HANDLE   # a 64-bit handle: the default int would truncate it
        psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD]
        psapi.GetProcessMemoryInfo(kernel32.GetCurrentProcess(), ctypes.byref(counters), counters.cb)
        return round(counters.working / 2 ** 20, 1)
    except (AttributeError, OSError):
        return 0.0


class Rig:
    def __init__(self, folder, accounts):
        self.relay = relay_server.RelayServer(("127.0.0.1", 0), Path(folder) / "relay.sqlite3")
        threading.Thread(target=self.relay.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True).start()
        self.port, self.stop = self.relay.server_port, threading.Event()
        self.phones = []
        for number in range(accounts):
            name = f"user{number:03d}"
            self.relay.accounts.register(name, "load-test-pass-1")
            laptop = self.relay.accounts.login(name, "load-test-pass-1", "laptop", "l")
            self.phones.append(self.relay.accounts.login(name, "load-test-pass-1", "phone", "p"))
            threading.Thread(target=self.laptop, args=(laptop,), daemon=True).start()
        time.sleep(0.5)                         # every laptop has polled once: online

    def call(self, connection, method, path, token, body=None):
        headers = {"Authorization": "Bearer " + token, "Content-Type": "application/json"}
        connection.request(method, path, body=json.dumps(body).encode() if body is not None else None, headers=headers)
        response = connection.getresponse()
        data = response.read()
        return response.status, data

    def laptop(self, token):
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=60)
        while not self.stop.is_set():
            try:
                _, data = self.call(connection, "POST", "/relay/poll", token, {})
                for request in json.loads(data).get("requests", []):
                    self.call(connection, "POST", "/relay/reply", token, {"rid": request["rid"], "e2e": ENVELOPE})
            except (OSError, http.client.HTTPException, ValueError):
                connection.close()
                connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=60)
                time.sleep(0.1)

    def level(self, users, seconds):
        """Run `users` concurrent simulated users for `seconds`; return the measurements."""
        latencies, errors, lock, deadline = [], [0], threading.Lock(), time.monotonic() + seconds

        def user(index):
            token = self.phones[index % len(self.phones)]
            connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=30)
            turn = index
            while time.monotonic() < deadline:
                turn += 1
                start = time.perf_counter()
                try:
                    if turn % 2:
                        status, _ = self.call(connection, "GET", "/relay/me", token)
                    else:
                        status, _ = self.call(connection, "POST", "/t/e2e", token, ENVELOPE)
                    ok = status == 200
                except (OSError, http.client.HTTPException):
                    ok = False
                    connection.close()
                    connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=30)
                took = time.perf_counter() - start
                with lock:
                    if ok:
                        latencies.append(took)
                    else:
                        errors[0] += 1
            connection.close()
        threads = [threading.Thread(target=user, args=(i,), daemon=True) for i in range(users)]
        started = time.perf_counter()
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        elapsed = time.perf_counter() - started
        total = len(latencies) + errors[0]
        cuts = statistics.quantiles(latencies, n=100) if len(latencies) >= 2 else [0] * 99
        return {"users": users, "requests": total, "per_second": round(total / elapsed, 1),
                "error_rate": round(errors[0] / total, 4) if total else 1.0,
                "p50_ms": round(cuts[49] * 1000, 1), "p95_ms": round(cuts[94] * 1000, 1),
                "p99_ms": round(cuts[98] * 1000, 1), "relay_mb": rss_mb()}

    def close(self):
        self.stop.set()
        self.relay.shutdown()
        self.relay.server_close()
        self.relay.accounts.db.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--accounts", type=int, default=20)
    parser.add_argument("--seconds", type=float, default=6.0, help="per load level")
    parser.add_argument("--soak-minutes", type=float, default=0)
    parser.add_argument("--json", type=Path)
    args = parser.parse_args(argv)
    report = {"levels": []}
    with TemporaryDirectory() as folder:
        rig = Rig(folder, args.accounts)
        try:
            for users in (10, 50, 200, 450, relay_server.MAX_CONNECTIONS + 200):   # load, then past the cap
                row = rig.level(users, args.seconds)
                report["levels"].append(row)
                print(json.dumps(row), flush=True)
            recovery = rig.level(10, 3)        # after the spike: back to normal?
            report["recovery"] = recovery
            print("recovery", json.dumps(recovery), flush=True)
            if args.soak_minutes:
                before = rss_mb()
                soak = rig.level(50, args.soak_minutes * 60)
                report["soak"] = dict(soak, memory_growth_mb=round(soak["relay_mb"] - before, 1))
                print("soak", json.dumps(report["soak"]), flush=True)
        finally:
            rig.close()
    if args.json:
        args.json.write_text(json.dumps(report, indent=1), encoding="utf-8")
    healthy = report["levels"][0]["error_rate"] == 0 and report["recovery"]["error_rate"] == 0
    print("PASS" if healthy else "FAIL", "(no errors at normal load, and full recovery after the spike)")
    return 0 if healthy else 1


if __name__ == "__main__":
    sys.exit(main())
