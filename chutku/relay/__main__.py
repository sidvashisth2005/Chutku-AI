import argparse

from chutku.relay.server import serve

parser = argparse.ArgumentParser(description="Chutku account relay (put HTTPS in front of it in production)")
parser.add_argument("--port", type=int, default=8780)
parser.add_argument("--host", default="0.0.0.0")
parser.add_argument("--db", default="relay.sqlite3")
parser.add_argument("--tls-cert")
parser.add_argument("--tls-key")
args = parser.parse_args()
serve(args.port, args.db, args.host, args.tls_cert, args.tls_key)
