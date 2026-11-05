"""NAS binary image workbench with server-side authentication."""
from contextlib import contextmanager
from hashlib import pbkdf2_hmac, sha256
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit, unquote
import argparse
import getpass
import hmac
import json
import os
import re
import secrets
import sqlite3
import threading
import time
from packager import Packager, PackageError

ROOT = Path(__file__).resolve().parent
ITERATIONS = 600_000
SESSION_COOKIE = 'image_packager_session'
CSRF_COOKIE = 'image_packager_csrf'
USERNAME = re.compile(r'[a-zA-Z0-9][a-zA-Z0-9_.-]{2,31}\Z')
TOKEN = re.compile(r'[a-zA-Z0-9_-]{43}\Z')


class AuthError(Exception):
    def __init__(self, status, message, retry=0):
        self.status, self.message, self.retry = status, message, retry


def credentials(username, password):
    if not isinstance(username, str) or not USERNAME.fullmatch(username):
        raise AuthError(400, '账号需为 3–32 位字母、数字、点、下划线或连字符。')
    if not isinstance(password, str) or not 12 <= len(password) <= 128:
        raise AuthError(400, '密码长度需为 12–128 个字符。')


class AuthStore:
    def __init__(self, directory, clock=time.time):
        self.directory = Path(directory).resolve()
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.database = self.directory / 'auth.sqlite3'
        self.bootstrap = self.directory / 'setup-token'
        self.clock = clock
        with self.db() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS admin (
                    id INTEGER PRIMARY KEY CHECK(id=1), username TEXT NOT NULL,
                    salt BLOB NOT NULL, digest BLOB NOT NULL, generation INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS sessions (
                    digest TEXT PRIMARY KEY, expires REAL NOT NULL,
                    last_seen REAL NOT NULL, idle REAL NOT NULL, generation INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS attempts (
                    key TEXT PRIMARY KEY, started REAL NOT NULL, count INTEGER NOT NULL,
                    blocked_until REAL NOT NULL
                );
            ''')
        os.chmod(self.database, 0o600)
        if not self.initialized():
            try:
                fd = os.open(self.bootstrap, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(fd, 'w', encoding='ascii') as output:
                    output.write(secrets.token_urlsafe(24))
            except FileExistsError:
                pass

    @contextmanager
    def db(self):
        db = sqlite3.connect(self.database, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def initialized(self):
        with self.db() as db:
            return db.execute('SELECT 1 FROM admin').fetchone() is not None

    def check_rate(self, client):
        key = sha256(client.encode()).hexdigest()
        with self.db() as db:
            row = db.execute('SELECT blocked_until FROM attempts WHERE key=?', (key,)).fetchone()
        if row and row['blocked_until'] > self.clock():
            retry = max(1, int(row['blocked_until'] - self.clock()) + 1)
            raise AuthError(429, f'尝试过于频繁，请在 {retry} 秒后重试。', retry)

    def failure(self, client):
        now = self.clock()
        key = sha256(client.encode()).hexdigest()
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            db.execute('DELETE FROM attempts WHERE started<? AND blocked_until<?', (now - 900, now))
            row = db.execute('SELECT * FROM attempts WHERE key=?', (key,)).fetchone()
            count = row['count'] + 1 if row and row['started'] > now - 600 else 1
            started = row['started'] if row and row['started'] > now - 600 else now
            blocked = now + 60 if count >= 10 else 0
            db.execute('INSERT OR REPLACE INTO attempts VALUES(?,?,?,?)', (key, started, count, blocked))

    def clear_failures(self, client):
        with self.db() as db:
            db.execute('DELETE FROM attempts WHERE key=?', (sha256(client.encode()).hexdigest(),))

    def _new_session(self, db, generation, remember):
        now = self.clock()
        token = secrets.token_urlsafe(32)
        lifetime = 7 * 86400 if remember else 86400
        idle = 86400 if remember else 8 * 3600
        db.execute('DELETE FROM sessions WHERE expires<=? OR last_seen+idle<=?', (now, now))
        # Bound persistent sessions for this single administrator.
        db.execute('DELETE FROM sessions WHERE digest IN (SELECT digest FROM sessions ORDER BY last_seen DESC LIMIT -1 OFFSET 19)')
        db.execute('INSERT INTO sessions VALUES(?,?,?,?,?)',
                   (sha256(token.encode()).hexdigest(), now + lifetime, now, idle, generation))
        return token

    def setup(self, token, username, password):
        credentials(username, password)
        salt = secrets.token_bytes(32)
        digest = pbkdf2_hmac('sha256', password.encode(), salt, ITERATIONS)
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            if db.execute('SELECT 1 FROM admin').fetchone():
                raise AuthError(409, '管理员已设置，请直接登录。')
            stored = self.bootstrap.read_text(encoding='ascii') if self.bootstrap.exists() else ''
            if not stored or not isinstance(token, str) or not hmac.compare_digest(token.encode(), stored.encode()):
                raise AuthError(403, '初始化凭证不正确，请查看容器启动日志。')
            db.execute('INSERT INTO admin VALUES(1,?,?,?,1)', (username, salt, digest))
            session = self._new_session(db, 1, False)
        self.bootstrap.unlink(missing_ok=True)
        return session

    def login(self, username, password, remember=False):
        if not isinstance(username, str) or not isinstance(password, str) or len(username) > 128 or len(password) > 128:
            raise AuthError(401, '账号或密码不正确。')
        with self.db() as db:
            row = db.execute('SELECT * FROM admin').fetchone()
        if not row:
            raise AuthError(409, '请先设置管理员账号。')
        digest = pbkdf2_hmac('sha256', password.encode(), row['salt'], ITERATIONS)
        if not hmac.compare_digest(username.encode(), row['username'].encode()) or not hmac.compare_digest(digest, row['digest']):
            raise AuthError(401, '账号或密码不正确。')
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            current = db.execute('SELECT generation FROM admin').fetchone()
            if current['generation'] != row['generation']:
                raise AuthError(401, '密码已变更，请重新登录。')
            return self._new_session(db, row['generation'], remember)

    def user(self, token):
        if not isinstance(token, str) or not TOKEN.fullmatch(token):
            return None
        now = self.clock()
        digest = sha256(token.encode()).hexdigest()
        with self.db() as db:
            row = db.execute('''SELECT sessions.*,admin.username,admin.generation AS current_generation
                FROM sessions CROSS JOIN admin WHERE sessions.digest=?''', (digest,)).fetchone()
            if not row:
                return None
            if row['expires'] <= now or row['last_seen'] + row['idle'] <= now or row['generation'] != row['current_generation']:
                db.execute('DELETE FROM sessions WHERE digest=?', (digest,))
                return None
            db.execute('UPDATE sessions SET last_seen=? WHERE digest=?', (now, digest))
        return row['username']

    def logout(self, token):
        with self.db() as db:
            db.execute('DELETE FROM sessions WHERE digest=?', (sha256(token.encode()).hexdigest(),))

    def change_password(self, token, current_password, new_password):
        if not self.user(token):
            raise AuthError(401, '登录已过期，请重新登录。')
        with self.db() as db:
            row = db.execute('SELECT * FROM admin').fetchone()
        credentials(row['username'], new_password)
        if not isinstance(current_password, str) or len(current_password) > 128:
            raise AuthError(400, '当前密码不正确。')
        old = pbkdf2_hmac('sha256', current_password.encode(), row['salt'], ITERATIONS)
        if not hmac.compare_digest(old, row['digest']):
            raise AuthError(403, '当前密码不正确。')
        if hmac.compare_digest(current_password.encode(), new_password.encode()):
            raise AuthError(400, '新密码需与当前密码不同。')
        self.reset_password(new_password, expected_generation=row['generation'])

    def reset_password(self, password, expected_generation=None):
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT * FROM admin').fetchone()
            if not row:
                raise AuthError(409, '尚未设置管理员。')
            if expected_generation is not None and expected_generation != row['generation']:
                raise AuthError(409, '账号信息已更新，请重新登录。')
            credentials(row['username'], password)
            salt = secrets.token_bytes(32)
            digest = pbkdf2_hmac('sha256', password.encode(), salt, ITERATIONS)
            db.execute('UPDATE admin SET salt=?,digest=?,generation=generation+1 WHERE id=1', (salt, digest))
            db.execute('DELETE FROM sessions')


class Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address, store, secure_cookie=False, public_origin=''):
        self.store, self.secure_cookie, self.public_origin = store, secure_cookie, public_origin.rstrip('/')
        self.packager = Packager(store.directory)
        self.capacity = threading.BoundedSemaphore(24)
        super().__init__(address, Handler)

    def process_request(self, request, client_address):
        if not self.capacity.acquire(blocking=False):
            try:
                request.sendall(b'HTTP/1.1 503 Service Unavailable\r\nConnection: close\r\nContent-Length: 0\r\n\r\n')
            finally:
                self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except Exception:
            self.capacity.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self.capacity.release()


class Handler(BaseHTTPRequestHandler):
    server_version = 'ImagePackager'
    sys_version = ''

    def setup(self):
        super().setup()
        self.connection.settimeout(15)

    def cookies(self):
        jar = SimpleCookie()
        try:
            jar.load(self.headers.get('Cookie', '')[:8192])
        except Exception:
            return {}
        return {key: value.value for key, value in jar.items()}

    def cookie(self, name, value, max_age=None):
        result = f'{name}={value}; Path=/; HttpOnly; SameSite=Strict'
        if self.server.secure_cookie:
            result += '; Secure'
        if max_age is not None:
            result += f'; Max-Age={max_age}'
        return ('Set-Cookie', result)

    def respond(self, status, body=b'', content_type='application/json; charset=utf-8', headers=()):
        self.send_response(status)
        for key, value in [('Content-Type', content_type), ('Content-Length', str(len(body))),
                           ('Cache-Control', 'no-store'), ('X-Content-Type-Options', 'nosniff'),
                           ('Referrer-Policy', 'same-origin'), ('X-Frame-Options', 'DENY'),
                           ('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'; object-src 'none'"), *headers]:
            self.send_header(key, value)
        self.end_headers()
        if self.command != 'HEAD':
            self.wfile.write(body)

    def json(self, status, data, headers=()):
        self.respond(status, json.dumps(data, ensure_ascii=False).encode(), headers=headers)

    def redirect(self, target):
        self.respond(303, headers=[('Location', target)])

    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        path = urlsplit(self.path).path
        jar = self.cookies()
        user = self.server.store.user(jar.get(SESSION_COOKIE))
        if path == '/api/auth/state':
            csrf = jar.get(CSRF_COOKIE, '')
            if not TOKEN.fullmatch(csrf):
                csrf = secrets.token_urlsafe(32)
            self.json(200, {'initialized': self.server.store.initialized(), 'user': user, 'csrf': csrf},
                      [self.cookie(CSRF_COOKIE, csrf, 7 * 86400)])
            return
        if path == '/healthz':
            self.json(200, {'ok': True})
            return
        if user and (path.startswith('/api/') or path.startswith('/downloads/')):
            try:
                packager = self.server.packager
                if path == '/api/system':
                    self.json(200, packager.docker.status())
                    return
                if path == '/api/jobs':
                    self.json(200, {'jobs': packager.list()})
                    return
                match = re.fullmatch(r'/api/(uploads|jobs)/([a-f0-9]{32})', path)
                if match:
                    root = packager.uploads if match[1] == 'uploads' else packager.jobs
                    self.json(200, packager.read(packager.folder(root, match[2])))
                    return
                match = re.fullmatch(r'/downloads/([a-f0-9]{32})/(image|compose|sha256)', path)
                if match:
                    stream, name, content_type = packager.download(match[1], match[2])
                    with stream:
                        self.send_response(200)
                        self.send_header('Content-Type', content_type)
                        self.send_header('Content-Length', str(os.fstat(stream.fileno()).st_size))
                        self.send_header('Content-Disposition', f'attachment; filename="{name}"')
                        self.send_header('Cache-Control', 'no-store')
                        self.send_header('X-Content-Type-Options', 'nosniff')
                        self.end_headers()
                        if self.command != 'HEAD':
                            import shutil
                            shutil.copyfileobj(stream, self.wfile, 1024 * 1024)
                    return
            except PackageError as error:
                self.json(error.status, {'error': error.message})
                return
            except OSError:
                self.json(500, {'error': '读取文件失败，请检查数据目录和可用空间。'})
                return
        public = {'/login': 'login.html', '/login.html': 'login.html', '/setup': 'setup.html',
                  '/setup.html': 'setup.html', '/studio.css': 'studio.css', '/auth.css': 'auth.css',
                  '/auth.js': 'auth.js', '/auth-client.js': 'auth-client.js', '/favicon.svg': 'favicon.svg'}
        protected = {'/': 'index.html', '/index.html': 'index.html', '/preview.html': 'index.html',
                     '/history': 'history.html', '/history.html': 'history.html', '/history.js': 'history.js',
                     '/studio.js': 'studio.js', '/session.js': 'session.js', '/account': 'account.html',
                     '/account.html': 'account.html', '/account.js': 'account.js'}
        if path not in public and not user:
            if path.startswith('/api/') or path.startswith('/downloads/'):
                self.json(401, {'error': '请先登录。'})
            else:
                self.redirect('/login' if self.server.store.initialized() else '/setup')
            return
        filename = public.get(path) or protected.get(path)
        if not filename:
            self.json(404, {'error': '页面不存在。'})
            return
        content_type = {'html': 'text/html', 'css': 'text/css', 'js': 'text/javascript', 'svg': 'image/svg+xml'}[filename.rsplit('.', 1)[1]]
        self.respond(200, (ROOT / 'design' / filename).read_bytes(), content_type + '; charset=utf-8')

    def check_csrf(self):
        origin = self.headers.get('Origin', '')
        try:
            parsed = urlsplit(origin)
        except ValueError:
            raise AuthError(403, '请求来源无效。') from None
        expected = self.server.public_origin
        if expected:
            allowed = hmac.compare_digest(origin.encode(), expected.encode())
        else:
            allowed = parsed.scheme in ('http', 'https') and parsed.netloc == self.headers.get('Host', '') and not parsed.path
        if not allowed or self.headers.get('Sec-Fetch-Site') == 'cross-site':
            raise AuthError(403, '请求来源无效，请刷新页面后重试。')
        csrf = self.cookies().get(CSRF_COOKIE, '')
        supplied = self.headers.get('X-CSRF-Token', '')
        if not TOKEN.fullmatch(csrf) or not hmac.compare_digest(csrf.encode(), supplied.encode()):
            raise AuthError(403, '页面凭证已失效，请刷新后重试。')

    def post_body(self):
        self.check_csrf()
        if self.headers.get_content_type() != 'application/json' or self.headers.get('Transfer-Encoding'):
            raise AuthError(415, '请求格式不正确。')
        try:
            length = int(self.headers.get('Content-Length', '0'))
            if not 0 < length <= 8192:
                raise ValueError
            payload = self.rfile.read(length)
            if len(payload) != length:
                raise ValueError
            data = json.loads(payload)
            if not isinstance(data, dict):
                raise ValueError
            return data
        except (ValueError, UnicodeError):
            raise AuthError(400, '请求内容无效。') from None

    def do_POST(self):
        path = urlsplit(self.path).path
        store = self.server.store
        jar = self.cookies()
        client = self.client_address[0]  # Deliberately ignore untrusted forwarding headers.
        try:
            user = store.user(jar.get(SESSION_COOKIE))
            if path not in ('/api/auth/login', '/api/auth/setup') and not user:
                raise AuthError(401, '登录已过期，请重新登录。')
            if path in ('/api/auth/login', '/api/auth/setup', '/api/auth/password'):
                store.check_rate(client)
            if path == '/api/uploads':
                self.check_csrf()
                if self.headers.get_content_type() != 'application/octet-stream' or self.headers.get('Transfer-Encoding'):
                    raise AuthError(415, '请使用文件上传格式。')
                try:
                    if len(self.headers.get_all('Content-Length', [])) != 1:
                        raise ValueError
                    length = int(self.headers.get('Content-Length', '0'))
                except ValueError:
                    raise AuthError(400, '上传文件长度无效。') from None
                self.connection.settimeout(60)
                result = self.server.packager.upload(self.rfile, length, unquote(self.headers.get('X-Filename', 'program')))
                self.json(201, result)
                return
            data = self.post_body()
            if path == '/api/auth/setup':
                token = store.setup(data.get('setup_token'), data.get('username'), data.get('password'))
                store.clear_failures(client)
                self.json(200, {'ok': True}, [self.cookie(SESSION_COOKIE, token)])
            elif path == '/api/auth/login':
                remember = data.get('remember') is True
                token = store.login(data.get('username'), data.get('password'), remember)
                store.clear_failures(client)
                self.json(200, {'ok': True}, [self.cookie(SESSION_COOKIE, token, 7 * 86400 if remember else None)])
            elif path == '/api/auth/logout':
                store.logout(jar.get(SESSION_COOKIE, ''))
                self.json(200, {'ok': True}, [self.cookie(SESSION_COOKIE, '', 0)])
            elif path == '/api/auth/password':
                store.change_password(jar.get(SESSION_COOKIE), data.get('current_password'), data.get('new_password'))
                store.clear_failures(client)
                self.json(200, {'ok': True}, [self.cookie(SESSION_COOKIE, '', 0)])
            elif path == '/api/jobs':
                self.json(202, self.server.packager.start(data))
            elif path == '/api/uploads/clean':
                self.json(200, {'removed': self.server.packager.clean_uploads()})
            elif re.fullmatch(r'/api/jobs/[a-f0-9]{32}/import', path):
                self.json(202, self.server.packager.import_job(path.split('/')[3]))
            elif re.fullmatch(r'/api/jobs/[a-f0-9]{32}/delete', path):
                self.server.packager.delete(path.split('/')[3])
                self.json(200, {'ok': True})
            else:
                raise AuthError(404, '接口不存在。')
        except AuthError as error:
            if path in ('/api/auth/login', '/api/auth/setup', '/api/auth/password') and error.status in (400, 401, 403):
                store.failure(client)
            headers = [('Retry-After', str(error.retry))] if error.retry else []
            self.json(error.status, {'error': error.message}, headers)
        except PackageError as error:
            self.json(error.status, {'error': error.message})
        except (OSError, sqlite3.Error):
            self.json(500, {'error': '账号服务暂时不可用，请检查数据目录权限或稍后重试。'})

    def log_message(self, format, *args):
        # Never log passwords, cookies, request bodies, or URL query strings.
        print(f'{self.command} {urlsplit(self.path).path} {args[1] if len(args) > 1 else ""}', flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host', default=os.getenv('BIND_HOST', '0.0.0.0'))
    parser.add_argument('--port', type=int, default=int(os.getenv('PORT', '8088')))
    parser.add_argument('--data-dir', type=Path, default=Path(os.getenv('DATA_DIR', str(ROOT / 'data'))))
    parser.add_argument('--reset-password', action='store_true')
    args = parser.parse_args()
    store = AuthStore(args.data_dir)
    if args.reset_password:
        password = getpass.getpass('New password (12-128 characters): ')
        if password != getpass.getpass('Confirm password: '):
            parser.error('Passwords do not match')
        store.reset_password(password)
        print('Password reset. All sessions have been revoked.')
        return
    server = Server((args.host, args.port), store, os.getenv('COOKIE_SECURE') == '1', os.getenv('PUBLIC_ORIGIN', ''))
    if not store.initialized():
        print('FIRST SETUP TOKEN: ' + store.bootstrap.read_text(encoding='ascii'), flush=True)
    print(f'Workbench: http://{args.host}:{server.server_port}', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == '__main__':
    main()
