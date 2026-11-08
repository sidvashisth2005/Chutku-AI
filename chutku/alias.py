"""Type chutku.localhost in any browser to open Chutku (owner 2026-11-08: "if someone types chutku in the browser's
address bar, the dashboard should open").

Browsers send every *.localhost name to this PC by themselves, so no hosts file and no administrator rights are
needed. A tiny server on 127.0.0.1:80 answers only that name, with a redirect to the running dashboard's session link.
(A bare single word such as "chutku" is searched by every browser, so it cannot be claimed without admin rights.)
If port 80 is already taken, nothing starts: the Start-menu app, the desktop icon and the tray still open Chutku.

The redirect carries the session token in the URL fragment only. Another web page cannot read it: a cross-origin
fetch of this address gets an unreadable answer, and a fragment is never sent to any server.
"""
from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import threading

NAMES = {"chutku.localhost", "chutku"}
PORT = 80


class _Exclusive(ThreadingHTTPServer):
    """Never share the port: Python's HTTP server sets SO_REUSEADDR, which on Windows lets a second program bind the
    same port (test 2026-11-08: a second start on a busy port succeeded). Exclusive use, or nothing."""
    allow_reuse_address = False
    daemon_threads = True

    def server_bind(self):
        import socket
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()


def start(link, *, port=PORT):
    """Serve the redirect in the background. `link()` returns the dashboard's session URL. None if the port is busy."""
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            host = (self.headers.get("Host") or "").rsplit(":", 1)[0].lower()
            if host not in NAMES:
                self.send_response(404)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            self.send_response(302)
            self.send_header("Location", link())
            self.send_header("Cache-Control", "no-store")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Content-Length", "0")
            self.end_headers()

        def log_message(self, *_):
            pass
    try:
        server = _Exclusive(("127.0.0.1", port), Handler)
    except OSError:
        return None
    threading.Thread(target=server.serve_forever, name="chutku-alias", daemon=True).start()
    return server
