"""Loopback-only, ephemeral browser presentation for the existing scan pipeline."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.resources import files
import secrets
from threading import Lock
from urllib.parse import parse_qs

from legible import core
from legible.output.web import render_page


class WebServer(ThreadingHTTPServer):
    def __init__(self, address):
        super().__init__(address, WebHandler)
        self.form_token = secrets.token_urlsafe(32)
        self.scan_lock = Lock()


class WebHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass  # Domain input and evidence need not become server logs.

    def respond(self, status, body, content_type='text/html; charset=utf-8'):
        data = body.encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Content-Security-Policy', "default-src 'none'; style-src 'self'; script-src 'self'; form-action 'self'; base-uri 'none'; frame-ancestors 'none'")
        self.end_headers()
        self.wfile.write(data)

    def local_request(self):
        # Reject rebinding and cross-origin browser requests before any scan.
        port = self.server.server_address[1]
        authorities = {f'127.0.0.1:{port}', f'localhost:{port}'}
        host = self.headers.get('Host', '')
        origin = self.headers.get('Origin')
        return host in authorities and (origin is None or origin == f'http://{host}')

    def do_GET(self):
        if not self.local_request():
            self.respond(403, 'This service is available from its local address only.')
        elif self.path == '/':
            self.respond(200, render_page(self.server.form_token))
        elif self.path in {'/style.css', '/app.js'}:
            name = self.path[1:]
            content = files('legible.output').joinpath('assets', name).read_text(encoding='utf-8')
            self.respond(200, content, 'text/css' if name.endswith('.css') else 'text/javascript')
        else:
            self.respond(404, 'Page not found.')

    def do_POST(self):
        if not self.local_request():
            self.respond(403, 'This service is available from its local address only.')
            return
        if self.path != '/scan':
            self.respond(404, 'Page not found.')
            return
        try:
            length = int(self.headers.get('Content-Length', '0'))
            if not 0 < length <= 16384:
                raise ValueError
            if self.headers.get('Content-Type', '').split(';')[0] != 'application/x-www-form-urlencoded':
                raise ValueError
            form = parse_qs(self.rfile.read(length).decode('utf-8'), max_num_fields=4)
            target, = form.get('domain', [''])
            token, = form.get('token', [''])
        except (ValueError, UnicodeError):
            self.respond(400, render_page(self.server.form_token, error='Provide one domain or HTTP(S) URL.'))
            return
        if not secrets.compare_digest(token.encode('utf-8'), self.server.form_token.encode('utf-8')):
            self.respond(403, render_page(self.server.form_token, error='Reload the page before starting a scan.'))
            return
        try:
            core.normalize_target(target)
        except ValueError as exc:
            self.respond(400, render_page(self.server.form_token, target=target, error=str(exc)))
            return
        if not self.server.scan_lock.acquire(blocking=False):
            self.respond(409, render_page(self.server.form_token, target=target,
                                         error='A scan is already running. Wait for it to finish, then try again.'))
            return
        try:
            report = core.scan_report(target)
            self.respond(200, render_page(self.server.form_token, report, target))
        except Exception:
            self.respond(500, render_page(self.server.form_token, target=target,
                                         error='The scan could not complete. Try again or inspect this domain with the CLI.'))
        finally:
            self.server.scan_lock.release()


def serve(port: int = 8765):
    if not 1 <= port <= 65535:
        raise ValueError('Choose a port between 1 and 65535.')
    with WebServer(('127.0.0.1', port)) as server:
        print(f'Legible is ready at http://127.0.0.1:{port} — press Ctrl+C to stop.', flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
