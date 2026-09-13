"""
Run a celery process and give Railway something real to health-check.

A Railway service with no health check reports SUCCESS forever, so a crash-looping
worker or beat is invisible. Neither process speaks HTTP, so this wrapper starts
the real command as a child and answers /healthz on $PORT for as long as that
child is alive - which is what turns an exited celery process into a failed
deployment instead of a green one.

Usage: child_health.py -- /start-worker
"""

import os
import signal
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT = int(os.environ.get('PORT', '8080'))

argv = sys.argv[1:]
if argv and argv[0] == '--':
    argv = argv[1:]
if not argv:
    raise SystemExit('usage: child_health.py -- <command> [args...]')

child = subprocess.Popen(argv)


class Handler(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'
    server_version = 'wger-health'

    def log_message(self, fmt, *args):
        pass

    def do_GET(self):
        alive = child.poll() is None
        body = (b'ok\n' if alive else b'child exited\n')
        self.send_response(200 if alive else 503)
        self.send_header('Content-Type', 'text/plain; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def forward(signum, _frame):
    if child.poll() is None:
        child.send_signal(signum)


for sig in (signal.SIGTERM, signal.SIGINT):
    signal.signal(sig, forward)

server = ThreadingHTTPServer(('0.0.0.0', PORT), Handler)
threading.Thread(target=server.serve_forever, daemon=True).start()
print(f'[health] probing {argv[0]} on port {PORT}', file=sys.stderr, flush=True)

sys.exit(child.wait())
