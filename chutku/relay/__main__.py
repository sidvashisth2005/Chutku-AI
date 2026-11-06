import argparse

from chutku.relay.server import serve

parser = argparse.ArgumentParser(description="Chutku account relay (put HTTPS in front of it in production)")
parser.add_argument("--port", type=int, default=8780)
parser.add_argument("--host", default="0.0.0.0")
parser.add_argument("--db", default="relay.sqlite3")
parser.add_argument("--tls-cert")
parser.add_argument("--tls-key")
parser.add_argument("--behind-proxy", action="store_true",
                    help="a local HTTPS proxy sets X-Forwarded-For (sign-up limits then count real clients)")
args = parser.parse_args()
serve(args.port, args.db, args.host, args.tls_cert, args.tls_key, args.behind_proxy)
