"""Temporary loopback form for pasting provider keys without exposing them in logs.

Run only during local setup, then stop the process. Keys are saved to ignored .env.
"""
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs
import html
import os
import secrets

from dotenv import set_key

ROOT = Path(__file__).resolve().parents[1]
TOKEN = secrets.token_urlsafe(32)
NAMES = {'ELEVENLABS_API_KEY', 'DAYTONA_API_KEY'}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_args):
        pass

    def page(self, message=''):
        body = f'''<!doctype html><meta charset="utf-8"><title>EmergencyOS provider setup</title>
        <style>body{{font:18px system-ui;max-width:650px;margin:60px auto;padding:24px}}
        input,select,button{{font:inherit;padding:12px;display:block;margin:14px 0;width:100%;box-sizing:border-box}}
        .ok{{color:#17613e}}</style><h1>EmergencyOS provider setup</h1>
        <p>This temporary page saves a provider key to this project's local, Git-ignored .env file.</p>
        <p class="ok">{html.escape(message)}</p><form method="post" action="/save" autocomplete="off">
        <input type="hidden" name="csrf" value="{TOKEN}">
        <label>Provider<select name="name"><option>ELEVENLABS_API_KEY</option><option>DAYTONA_API_KEY</option></select></label>
        <label>API key<input type="password" name="value" required autocomplete="off" spellcheck="false"></label>
        <button>Save key locally</button></form><p>Key values are never returned by this page.</p>'''.encode()
        self.send_response(200)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Content-Security-Policy', "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; frame-ancestors 'none'")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.headers.get('Host') != '127.0.0.1:8765' or self.path != '/':
            self.send_error(404)
            return
        self.page()

    def do_POST(self):
        if self.path != '/save' or self.headers.get('Origin') != 'http://127.0.0.1:8765' or self.headers.get('Host') != '127.0.0.1:8765':
            self.send_error(403)
            return
        size = int(self.headers.get('Content-Length', 0))
        if not 0 < size < 8192:
            self.send_error(400)
            return
        data = parse_qs(self.rfile.read(size).decode())
        name = data.get('name', [''])[0]
        value = data.get('value', [''])[0].strip()
        if not secrets.compare_digest(data.get('csrf', [''])[0], TOKEN) or name not in NAMES or not value or any(c.isspace() for c in value):
            self.send_error(400)
            return
        path = ROOT / '.env'
        fd = os.open(path, os.O_CREAT | os.O_WRONLY, 0o600)
        os.close(fd)
        os.chmod(path, 0o600)
        set_key(path, name, value)
        os.chmod(path, 0o600)
        self.page(f'{name} saved locally. You can close this tab after saving both keys.')


if __name__ == '__main__':
    print('Temporary provider setup: http://127.0.0.1:8765', flush=True)
    HTTPServer(('127.0.0.1', 8765), Handler).serve_forever()
