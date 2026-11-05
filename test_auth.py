"""Authentication boundary tests. Run: python -m unittest -v test_auth.py"""
from concurrent.futures import ThreadPoolExecutor
from http.client import HTTPConnection
from http.cookies import SimpleCookie
from pathlib import Path
from tempfile import TemporaryDirectory
import json
import threading
import time
import unittest

from server import AuthError, AuthStore, CSRF_COOKIE, SESSION_COOKIE, Server

PASSWORD = 'test-only-long-password-2026'
NEW_PASSWORD = 'new-test-only-password-2026'


class Client:
    def __init__(self, server):
        self.server = server
        self.cookies = {}
        self.csrf = ''

    def request(self, method, path, data=None, extra_headers=None):
        host, port = self.server.server_address
        headers = {'Cookie': '; '.join(f'{k}={v}' for k, v in self.cookies.items())}
        payload = None
        if method == 'POST':
            headers.update({'Origin': f'http://{host}:{port}', 'X-CSRF-Token': self.csrf, 'Content-Type': 'application/json'})
            payload = json.dumps({} if data is None else data).encode()
        headers.update(extra_headers or {})
        connection = HTTPConnection(host, port, timeout=10)
        try:
            connection.request(method, path, payload, headers)
            response = connection.getresponse()
            response_headers = response.getheaders()
            body = response.read()
            for name, value in response_headers:
                if name.lower() == 'set-cookie':
                    jar = SimpleCookie(value)
                    for key, morsel in jar.items():
                        self.cookies[key] = morsel.value
            if response.getheader('Content-Type', '').startswith('application/json'):
                body = json.loads(body) if body else {}
            return response.status, body, dict(response_headers)
        finally:
            connection.close()

    def state(self):
        status, result, _ = self.request('GET', '/api/auth/state')
        assert status == 200
        self.csrf = result['csrf']
        return result

    def login(self, username='test-admin', password=PASSWORD, remember=False):
        self.state()
        return self.request('POST', '/api/auth/login', {'username': username, 'password': password, 'remember': remember})


class AuthenticationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = TemporaryDirectory()
        self.now = time.time()
        self.store = AuthStore(self.temporary.name, clock=lambda: self.now)
        self.server = Server(('127.0.0.1', 0), self.store)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.client = Client(self.server)

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.temporary.cleanup()

    def initialize(self):
        self.client.state()
        status, result, headers = self.client.request('POST', '/api/auth/setup', {
            'setup_token': self.store.bootstrap.read_text(), 'username': 'test-admin', 'password': PASSWORD})
        self.assertEqual((status, result), (200, {'ok': True}))
        return headers

    def test_protected_pages_and_future_operations(self):
        for path in ['/', '/index.html', '/preview.html', '/account', '/studio.js', '/server.py']:
            status, _, headers = self.client.request('GET', path)
            self.assertEqual(status, 303, path)
            self.assertEqual(headers['Location'], '/setup')
        for path in ['/api/jobs', '/downloads/example.tar']:
            self.assertEqual(self.client.request('GET', path)[0], 401)
        self.assertEqual(self.client.request('POST', '/api/jobs', {})[0], 401)
        self.assertEqual(self.client.request('GET', '/login')[0], 200)

    def test_first_setup_token_and_private_storage(self):
        self.client.state()
        self.assertEqual(self.client.request('POST', '/api/auth/setup', {
            'setup_token': 'wrong', 'username': 'test-admin', 'password': PASSWORD})[0], 403)
        self.assertFalse(self.store.initialized())
        headers = self.initialize()
        self.assertFalse(self.store.bootstrap.exists())
        self.assertIn('HttpOnly', headers['Set-Cookie'])
        self.assertNotIn('Max-Age', headers['Set-Cookie'])
        self.assertNotIn(PASSWORD.encode(), self.store.database.read_bytes())
        self.assertNotIn(self.client.cookies[SESSION_COOKIE].encode(), self.store.database.read_bytes())
        self.assertEqual(self.client.state()['user'], 'test-admin')
        self.assertEqual(self.client.request('GET', '/')[0], 200)
        for path in ['/server.py', '/data/auth.sqlite3', '/auth.sqlite3', '/%2e%2e/server.py']:
            self.assertEqual(self.client.request('GET', path)[0], 404)

    def test_csrf_origin_and_body_validation(self):
        self.initialize()
        for headers in [{'Origin': 'https://other.example'}, {'Origin': 'http://['}, {'X-CSRF-Token': 'wrong'}]:
            self.assertEqual(self.client.request('POST', '/api/auth/logout', {}, headers)[0], 403)
        self.server.public_origin = f'http://127.0.0.1:{self.server.server_port}'
        self.assertEqual(self.client.request('POST', '/api/auth/logout', {}, {'Origin': 'http://é.example'})[0], 403)
        self.server.public_origin = ''
        self.assertEqual(self.client.state()['user'], 'test-admin')
        self.assertEqual(self.client.request('POST', '/api/auth/logout', {}, {'Content-Type': 'text/plain'})[0], 415)
        self.assertEqual(self.client.request('POST', '/api/auth/logout', [1, 2])[0], 400)
        self.assertEqual(self.client.request('POST', '/api/auth/logout', {'large': 'x' * 9000})[0], 400)

    def test_login_logout_and_cookie_flags(self):
        self.initialize()
        other = Client(self.server)
        status, wrong, _ = other.login(password='wrong')
        self.assertEqual(status, 401)
        self.assertEqual(wrong['error'], '账号或密码不正确。')
        self.assertEqual(other.login(username='different-user')[0], 401)
        status, _, headers = other.login(remember=True)
        self.assertEqual(status, 200)
        self.assertIn('Max-Age=604800', headers['Set-Cookie'])
        self.assertIn('HttpOnly', headers['Set-Cookie'])
        self.assertIn('SameSite=Strict', headers['Set-Cookie'])
        old_token = other.cookies[SESSION_COOKIE]
        self.assertEqual(other.request('POST', '/api/auth/logout')[0], 200)
        other.cookies[SESSION_COOKIE] = old_token
        self.assertEqual(other.request('GET', '/api/jobs')[0], 401)

    def test_password_change_revokes_all_devices(self):
        self.initialize()
        other = Client(self.server)
        self.assertEqual(other.login()[0], 200)
        old_token = self.client.cookies[SESSION_COOKIE]
        self.assertEqual(self.client.request('POST', '/api/auth/password', {
            'current_password': 'wrong', 'new_password': NEW_PASSWORD})[0], 403)
        self.assertEqual(self.client.request('POST', '/api/auth/password', {
            'current_password': PASSWORD, 'new_password': NEW_PASSWORD})[0], 200)
        self.assertIsNone(self.store.user(old_token))
        self.assertIsNone(other.state()['user'])
        self.assertEqual(other.login()[0], 401)
        self.assertEqual(other.login(password=NEW_PASSWORD)[0], 200)

    def test_expiration_restart_and_secure_cookie(self):
        self.initialize()
        token = self.client.cookies[SESSION_COOKIE]
        reopened = AuthStore(self.temporary.name, clock=lambda: self.now)
        self.assertEqual(reopened.user(token), 'test-admin')
        self.now += 8 * 3600 + 1
        self.assertIsNone(self.store.user(token))
        self.assertEqual(self.client.login(remember=True)[0], 200)
        token = self.client.cookies[SESSION_COOKIE]
        self.now += 7 * 86400 + 1
        self.assertIsNone(self.store.user(token))
        self.server.secure_cookie = True
        _, _, headers = self.client.login()
        self.assertIn('; Secure', headers['Set-Cookie'])

    def test_failed_login_throttling_and_recovery(self):
        self.initialize()
        other = Client(self.server)
        for _ in range(10):
            self.assertEqual(other.login(password='wrong')[0], 401)
        status, _, headers = other.login()
        self.assertEqual(status, 429)
        self.assertGreater(int(headers['Retry-After']), 0)
        # Logout remains available even when credential attempts are throttled.
        self.assertEqual(self.client.request('POST', '/api/auth/logout')[0], 200)
        self.now += 61
        self.assertEqual(other.login()[0], 200)
        self.assertEqual(other.login(password='wrong')[0], 401)

    def test_only_one_concurrent_setup_wins(self):
        token = self.store.bootstrap.read_text()
        def setup(username):
            try:
                self.store.setup(token, username, PASSWORD)
                return 200
            except AuthError as error:
                return error.status
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(setup, ['first-admin', 'second-admin']))
        self.assertEqual(sorted(results), [200, 409])


if __name__ == '__main__':
    unittest.main()
