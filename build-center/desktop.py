"""Portable Windows launcher and loopback-only local web application."""
from __future__ import annotations
import argparse
import http.server
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import threading
import time
import urllib.parse
import webbrowser

from center_core import CenterError, checked_file, request

ROOT = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parent))
WEB = ROOT / 'web'
VERSION = json.loads((ROOT/'config.json').read_text())['version']


class CenterServer(http.server.ThreadingHTTPServer):
    daemon_threads = True
    def __init__(self, address, mode='web'):
        super().__init__(address, Handler)
        self.mode = mode
        self.files = {}
        self.file_lock = threading.Lock()
        self.heartbeat = time.monotonic()


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(WEB), **kwargs)

    def log_message(self, *args):
        pass

    def valid_origin(self):
        expected = f'127.0.0.1:{self.server.server_port}'
        return (self.headers.get('Host') == expected
                and self.headers.get('Origin', 'http://' + expected) == 'http://' + expected)

    def json(self, data, status=200):
        raw = json.dumps(data, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Content-Length', str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        if not self.valid_origin():
            return self.json({'error': 'Ungültiger Host oder Origin.'}, 403)
        path = urllib.parse.urlsplit(self.path).path
        if path == '/api/info':
            return self.json({'app': 'SukiSU Build Center', 'mode': self.server.mode, 'version': VERSION})
        if path.startswith('/api/file/'):
            key = path.removeprefix('/api/file/')
            with self.server.file_lock:
                entry = self.server.files.pop(key, None)
            if entry is None:
                return self.json({'error': 'Download abgelaufen. Bitte erneut laden.'}, 404)
            raw, filename, _ = entry
            self.send_response(200)
            self.send_header('Content-Type', 'application/octet-stream')
            self.send_header('Content-Length', str(len(raw)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Content-Disposition', "attachment; filename*=UTF-8''" + urllib.parse.quote(filename, safe=''))
            self.end_headers()
            return self.wfile.write(raw)
        if path.startswith('/api/'):
            return self.json({'error': 'Unbekannter Endpunkt.'}, 404)
        # Serve only the packaged web tree, with no symlink escape.
        target = Path(self.translate_path(path)).resolve()
        if not target.is_relative_to(WEB.resolve()):
            return self.json({'error': 'Ungültiger Pfad.'}, 403)
        return super().do_GET()

    def list_directory(self, path):
        self.send_error(404)

    def do_POST(self):
        if not self.valid_origin() or self.headers.get('X-Center-Request') != '1':
            return self.json({'error': 'Ungültiger Anforderungskontext.'}, 403)
        if self.path == '/api/heartbeat':
            self.server.heartbeat = time.monotonic()
            return self.json({'ok': True})
        try:
            size = int(self.headers.get('Content-Length', '0'))
            if not 0 < size < 32768:
                raise CenterError('Ungültige Anfragegröße.')
            body = json.loads(self.rfile.read(size))
            if self.path == '/api/proxy':
                return self.json(request(body['url'], body.get('token', ''), body.get('method', 'GET'), body.get('data'), allow_http_errors=True))
            if self.path == '/api/download':
                raw = request(body['url'], body.get('token', ''), binary=True)
                raw, name, digest = checked_file(raw, body['filename'], body.get('digest', ''), body.get('kind', 'file'))
                key = secrets.token_urlsafe(32)
                with self.server.file_lock:
                    self.server.files = {k: v for k, v in self.server.files.items() if time.monotonic()-v[2] < 600}
                    if len(self.server.files) >= 8:
                        raise CenterError('Bitte zuerst die bereitgestellten Downloads speichern.')
                    self.server.files[key] = (raw, name, time.monotonic())
                return self.json({'href': '/api/file/' + key, 'filename': name, 'sha256': digest})
            return self.json({'error': 'Unbekannter Endpunkt.'}, 404)
        except (CenterError, ValueError, KeyError, TypeError) as exc:
            return self.json({'error': str(exc)}, 400)
        except Exception:
            return self.json({'error': 'Die Anfrage konnte nicht abgeschlossen werden.'}, 502)


def main():
    parser = argparse.ArgumentParser(description='KAOSLAB SukiSU Build Center')
    parser.add_argument('--web', action='store_true', help='Im normalen Browser öffnen')
    parser.add_argument('--no-browser', action='store_true')
    parser.add_argument('--stay', action='store_true', help='Server nach Schließen der Oberfläche weiter betreiben')
    parser.add_argument('--port', type=int, default=0)
    args = parser.parse_args()
    mode = 'web' if args.web or sys.platform != 'win32' else 'windows'
    server = CenterServer(('127.0.0.1', args.port), mode)
    url = f'http://127.0.0.1:{server.server_port}/'
    if not args.no_browser:
        edge = Path(os.environ.get('PROGRAMFILES(X86)', 'C:/Program Files (x86)')) / 'Microsoft/Edge/Application/msedge.exe'
        if mode == 'windows' and edge.exists():
            profile = Path(os.environ['LOCALAPPDATA']) / 'KAOSLAB/BuildCenter/Browser'
            subprocess.Popen([str(edge), '--app=' + url, '--user-data-dir=' + str(profile), '--no-first-run'],
                             creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        else:
            webbrowser.open(url)
    if not getattr(sys, 'frozen', False):
        print(url, flush=True)
    if not args.stay:
        def idle_stop():
            while time.monotonic() - server.heartbeat < 180:
                time.sleep(10)
            server.shutdown()
        threading.Thread(target=idle_stop, daemon=True).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == '__main__':
    main()
