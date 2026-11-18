"""Start the prepared local question bank without requiring Internet access."""
import argparse
from contextlib import contextmanager
from functools import partial
import hashlib
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import secrets
import sqlite3
import subprocess
import sys
from threading import Thread
import time
from urllib.error import URLError
from urllib.parse import urlsplit
from urllib.request import ProxyHandler, Request, build_opener
import webbrowser

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / 'dist'
STATE = ROOT / 'work/local-site/state.json'
IDENTITY = hashlib.sha256(str(ROOT.resolve()).encode('utf8')).hexdigest()
HEALTH = '/__chemy_local__/status'
OPENER = build_opener(ProxyHandler({}))  # Loopback requests must stay on this PC.


def read_state():
    try:
        value = json.loads(STATE.read_text(encoding='utf8'))
        if (isinstance(value, dict) and value.get('identity') == IDENTITY
                and type(value.get('port')) is int and 8765 <= value['port'] < 8795
                and type(value.get('pid')) is int and value['pid'] > 0
                and isinstance(value.get('token'), str) and len(value['token']) == 64
                and all(char in '0123456789abcdef' for char in value['token'])):
            value['url'] = f"http://127.0.0.1:{value['port']}"
            return value
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return None


def active(state):
    if not state:
        return False
    try:
        with OPENER.open(state['url'] + HEALTH, timeout=.5) as response:
            value = json.load(response)
            return isinstance(value, dict) and value.get('identity') == IDENTITY
    except (OSError, ValueError, URLError):
        return False


@contextmanager
def launch_lock():
    # A transaction serializes simultaneous double-clicks and releases its lock
    # automatically if a launcher process exits unexpectedly.
    STATE.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(STATE.parent / 'launcher.sqlite3', timeout=15)
    try:
        connection.execute('BEGIN IMMEDIATE')
        yield
        connection.commit()
    finally:
        connection.close()


def check_prepared():
    required = ['index.html', 'questions.json', 'presentation.json', 'numbering.json',
                'vendor/pdf-lib.min.js', 'export-parts/manifest.json']
    missing = [name for name in required if not (DIST / name).is_file()]
    if missing:
        raise RuntimeError('本地文件不完整：' + '、'.join(missing))
    manifest = json.loads((DIST / 'export-parts/manifest.json').read_text(encoding='utf8'))
    books = manifest.get('books', {})
    if (not isinstance(books, dict) or len(books) != 18
            or not all(isinstance(book, dict) and book.get('complete') for book in books.values())):
        raise RuntimeError('分题 PDF 尚未完整生成，请先运行 scripts/build_export_parts.py。')
    numbering = json.loads((DIST / 'numbering.json').read_text(encoding='utf8'))
    if (manifest.get('bookVersion') != numbering.get('pdfVersion')
            or sum(book.get('count', 0) for book in books.values()) != 2 * len(numbering['numberById'])):
        raise RuntimeError('本地 PDF 与当前题库版本不一致，请先完成 scripts/build_export_parts.py 的生成。')


class Handler(SimpleHTTPRequestHandler):
    def log_message(self, format, *args):
        pass

    def local_host(self):
        return self.headers.get('Host') == f'127.0.0.1:{self.server.server_port}'

    def send_json(self, value):
        raw = json.dumps(value, ensure_ascii=False).encode('utf8')
        self.send_response(200)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(raw)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        if not self.local_host():
            self.send_error(403)
            return
        name = urlsplit(self.path).path
        if name == HEALTH:
            self.send_json({'identity': IDENTITY, 'mode': 'local'})
        elif name == '/account-config.json':
            self.send_json({'url': '', 'publishableKey': ''})
        elif name == '/ai-config.json':
            self.send_json({'mode': 'local', 'backendUrl': ''})
        else:
            super().do_GET()

    def do_POST(self):
        if (self.local_host() and urlsplit(self.path).path == '/__chemy_local__/stop'
                and secrets.compare_digest(self.headers.get('X-Chemy-Local-Token', ''), self.server.stop_token)):
            self.send_json({'stopped': True})
            Thread(target=self.server.shutdown, daemon=True).start()
        else:
            self.send_error(403)

    def list_directory(self, path):
        self.send_error(404)
        return None


def serve():
    check_prepared()
    STATE.parent.mkdir(parents=True, exist_ok=True)
    server = None
    for port in range(8765, 8795):
        try:
            server = ThreadingHTTPServer(('127.0.0.1', port), partial(Handler, directory=str(DIST)))
            break
        except OSError:
            continue
    if server is None:
        raise RuntimeError('本地端口 8765–8794 均不可用，请关闭其他本地预览服务后重试。')
    server.stop_token = secrets.token_hex(32)
    state = {'identity': IDENTITY, 'port': server.server_port, 'pid': os.getpid(),
             'url': f'http://127.0.0.1:{server.server_port}', 'token': server.stop_token}
    temporary = STATE.with_name(f'state-{os.getpid()}.tmp')
    temporary.write_text(json.dumps(state), encoding='utf8')
    temporary.replace(STATE)
    try:
        server.serve_forever(poll_interval=.2)
    finally:
        server.server_close()
        current = read_state()
        if current and current.get('pid') == os.getpid():
            STATE.unlink(missing_ok=True)


def _start(open_browser):
    check_prepared()
    state = read_state()
    if not active(state):
        STATE.parent.mkdir(parents=True, exist_ok=True)
        options = {'creationflags': subprocess.CREATE_NO_WINDOW} if os.name == 'nt' else {'start_new_session': True}
        with (STATE.parent / 'server.log').open('ab') as log:
            child = subprocess.Popen([sys.executable, '-X', 'utf8', str(Path(__file__).resolve()), '--serve'],
                                     cwd=str(ROOT), stdin=subprocess.DEVNULL, stdout=log, stderr=log, **options)
        for _ in range(100):
            state = read_state()
            if active(state):
                break
            if child.poll() is not None:
                raise RuntimeError('本地服务启动失败，请查看 work/local-site/server.log。')
            time.sleep(.1)
        else:
            raise RuntimeError('本地服务未能及时启动，请查看 work/local-site/server.log。')
    address = state['url'] + '/'
    print(address)
    if open_browser:
        webbrowser.open(address)


def _stop():
    state = read_state()
    if active(state):
        request = Request(state['url'] + '/__chemy_local__/stop', data=b'', method='POST',
                          headers={'X-Chemy-Local-Token': state['token']})
        with OPENER.open(request, timeout=3) as response:
            json.load(response)
        for _ in range(30):
            if not active(state):
                break
            time.sleep(.1)
        else:
            raise RuntimeError('本地服务尚未关闭，请稍后重试。')
    print('本地题库服务已关闭。')


def start(open_browser):
    with launch_lock():
        _start(open_browser)


def stop():
    with launch_lock():
        _stop()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--open', action='store_true', help='start and open the local browser')
    mode.add_argument('--stop', action='store_true', help='stop this checkout\'s local server')
    mode.add_argument('--serve', action='store_true', help=argparse.SUPPRESS)
    args = parser.parse_args()
    try:
        if args.serve:
            serve()
        elif args.stop:
            stop()
        else:
            start(args.open)
    except (OSError, RuntimeError, ValueError, sqlite3.Error) as error:
        print(f'本地题库：{error}', file=sys.stderr)
        raise SystemExit(1)
