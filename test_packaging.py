"""Static boundary tests plus opt-in end-to-end tests against the built container."""
from http.cookiejar import CookieJar
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.error import HTTPError
from urllib.request import HTTPCookieProcessor, Request, build_opener
from unittest import mock
import hashlib
import io
import json
import os
import struct
import subprocess
import tarfile
import time
import unittest

from packager import PackageError, Packager, analyze, help_defaults, settings


def elf(machine=62, interpreter=b''):
    data = bytearray(120 + len(interpreter))
    data[:6] = b'\x7fELF\x02\x01'
    struct.pack_into('<HH', data, 16, 2, machine)
    struct.pack_into('<Q', data, 32, 64)
    struct.pack_into('<HH', data, 54, 56, 1)
    struct.pack_into('<I', data, 64, 3 if interpreter else 1)
    if interpreter:
        struct.pack_into('<Q', data, 72, 120)
        struct.pack_into('<Q', data, 96, len(interpreter))
        data[120:] = interpreter
    return bytes(data)


class PackagingBoundaries(unittest.TestCase):
    def test_elf_runtime_and_invalid_offsets(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / 'program'
            for machine, loader, arch, runtime in [(62, b'', 'amd64', 'alpine'),
                (183, b'/lib/ld-musl-aarch64.so.1\0', 'arm64', 'alpine'),
                (62, b'/lib64/ld-linux-x86-64.so.2\0', 'amd64', 'debian')]:
                path.write_bytes(elf(machine, loader))
                result = analyze(path)
                self.assertEqual((result['arch'], result['runtime']), (arch, runtime))
            bad = bytearray(elf())
            struct.pack_into('<Q', bad, 32, 99999999)
            for data in (b'not a binary', elf(999), bad):
                path.write_bytes(data)
                with self.assertRaises(PackageError):
                    analyze(path)

    def test_explicit_help_defaults_only(self):
        result = help_defaults('--port <PORT> [default: 18765]\n--data-dir <DIR> [default: /data]\n--config <PATH>\nversion 1234 /tmp/cache')
        self.assertEqual(result['port'], 18765)
        self.assertEqual(result['volume'], '/data')
        self.assertIn('--config', result['flags'])
        self.assertEqual(help_defaults('port 8080\nconfig /tmp/default')['port'], '')
        self.assertEqual(help_defaults('--port [default: 99999]')['port'], '')
        self.assertEqual(help_defaults('--data-dir [default: /]')['volume'], '')

    def test_settings_cannot_inject_dockerfile_or_shell(self):
        result = settings({'image': 'my-app', 'args': '--label "a b" ; touch /tmp/x', 'port': '8080', 'volume': '/app/config'})
        self.assertEqual(result['cmd'], ['--label', 'a b', ';', 'touch', '/tmp/x'])
        for field, value in [('image', 'a\nRUN evil'), ('runtime', 'https://evil'), ('volume', '/'),
                             ('volume', '/usr/local/bin'), ('volume', '/data/../etc'), ('args', '"bad'),
                             ('port', '65536'), ('port', True), ('tag', 'x\nRUN evil')]:
            with self.assertRaises(PackageError):
                settings({'image': 'my-app', field: value})

    def test_invalid_upload_cleanup_and_cache_isolation(self):
        with TemporaryDirectory() as directory:
            account = Path(directory) / 'auth.sqlite3'
            account.write_bytes(b'keep account')
            packager = Packager(directory)
            with self.assertRaises(PackageError):
                packager.upload(io.BytesIO(b'x' * 100), 100, 'test')
            self.assertEqual(list(packager.uploads.iterdir()), [])
            with mock.patch.object(packager, 'submit'):
                meta = packager.upload(io.BytesIO(elf()), len(elf()), 'test-app')
            folder = packager.uploads / meta['id']
            packager.write(folder, {**meta, 'status': 'ready'})
            self.assertEqual(packager.clean_uploads(), 1)
            self.assertEqual(account.read_bytes(), b'keep account')
            for key in ('../auth.sqlite3', '/etc/passwd', None):
                with self.assertRaises(PackageError):
                    packager.folder(packager.jobs, key)
            packager.pool.shutdown()


@unittest.skipUnless(os.getenv('BINPACK_URL'), 'Set BINPACK_URL for Docker integration test')
class ContainerFlow(unittest.TestCase):
    def test_upload_analyze_build_export_import_and_cleanup(self):
        base = os.environ['BINPACK_URL']
        fixture = Path(os.environ['BINPACK_FIXTURE']).read_bytes()
        container = os.environ['BINPACK_CONTAINER']
        client = build_opener(HTTPCookieProcessor(CookieJar()))
        csrf = ''

        def request(path, data=None, raw=False):
            headers = {}
            if data is not None:
                headers = {'Origin': base, 'X-CSRF-Token': csrf,
                    'Content-Type': 'application/octet-stream' if raw else 'application/json'}
                if raw:
                    headers['X-Filename'] = 'fixture-linux-amd64'
                else:
                    data = json.dumps(data).encode()
            with client.open(Request(base + path, data, headers), timeout=90) as response:
                payload = response.read()
                return json.loads(payload) if response.headers.get('Content-Type', '').startswith('application/json') else payload

        def wait(path, active):
            deadline = time.monotonic() + 300
            while True:
                value = request(path)
                if value['status'] not in active:
                    return value
                self.assertLess(time.monotonic(), deadline, value)
                time.sleep(.4)

        # Upload and arbitrary downloads are rejected before any file is processed.
        with self.assertRaises(HTTPError) as failure:
            request('/api/uploads', fixture, True)
        self.assertEqual(failure.exception.code, 401)
        csrf = request('/api/auth/state')['csrf']
        token = subprocess.check_output(['docker', 'exec', container, 'cat', '/data/setup-token'], text=True).strip()
        request('/api/auth/setup', {'setup_token': token, 'username': 'flow-admin', 'password': 'test-only-flow-password'})
        self.assertTrue(request('/api/system')['connected'])
        with self.assertRaises(HTTPError) as failure:
            client.open(Request(base + '/api/uploads', fixture, {'Origin': base, 'Content-Type': 'application/octet-stream'}))
        self.assertEqual(failure.exception.code, 403)
        upload = request('/api/uploads', fixture, True)
        upload = wait('/api/uploads/' + upload['id'], ('queued', 'analyzing'))
        self.assertFalse(upload.get('warning'), upload)
        self.assertEqual(upload['analysis']['port'], 18765)
        self.assertEqual(upload['analysis']['volume'], '/data')
        self.assertIn('--config', upload['analysis']['flags'])

        options = {'upload_id': upload['id'], 'image': 'binpack-flow-test', 'tag': 'ci', 'runtime': 'auto',
            'args': '--label "two words"', 'port': 18765, 'volume': '/data', 'auto_import': False}
        job = request('/api/jobs', options)
        job = wait('/api/jobs/' + job['id'], ('queued', 'building', 'importing'))
        self.assertEqual(job['status'], 'complete', job)
        self.assertFalse(job['imported'])
        # Download-only must not leave the requested image tag in the host image library.
        self.assertNotEqual(subprocess.run(['docker', 'image', 'inspect', 'binpack-flow-test:ci'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode, 0)
        archive = request('/downloads/' + job['id'] + '/image')
        checksum = request('/downloads/' + job['id'] + '/sha256').decode().split()[0]
        self.assertEqual(hashlib.sha256(archive).hexdigest(), checksum)
        with tarfile.open(fileobj=io.BytesIO(archive)) as saved:
            manifest = json.load(saved.extractfile('manifest.json'))
            self.assertEqual(manifest[0]['RepoTags'], ['binpack-flow-test:ci'])
        compose = json.loads(request('/downloads/' + job['id'] + '/compose'))
        self.assertEqual(compose['services']['binpack-flow-test']['ports'], ['18765:18765'])
        request('/api/jobs/' + job['id'] + '/import', {})
        imported = wait('/api/jobs/' + job['id'], ('importing',))
        self.assertTrue(imported['imported'], imported)
        output = subprocess.check_output(['docker', 'run', '--rm', 'binpack-flow-test:ci'], text=True)
        self.assertIn('fixture-ready --label two words', output)
        request('/api/jobs/' + job['id'] + '/delete', {})
        self.assertEqual(request('/api/jobs')['jobs'], [])
        subprocess.check_call(['docker', 'image', 'inspect', 'binpack-flow-test:ci'], stdout=subprocess.DEVNULL)
        request('/api/uploads/clean', {})
        self.assertEqual(request('/api/auth/state')['user'], 'flow-admin')

        # Exercise the checkbox route as well as importing an existing archive.
        upload = request('/api/uploads', fixture, True)
        upload = wait('/api/uploads/' + upload['id'], ('queued', 'analyzing'))
        job = request('/api/jobs', {**options, 'upload_id': upload['id'], 'tag': 'automatic', 'auto_import': True})
        job = wait('/api/jobs/' + job['id'], ('queued', 'building', 'importing'))
        self.assertEqual(job['status'], 'complete', job)
        self.assertTrue(job['imported'])
        subprocess.check_call(['docker', 'image', 'inspect', 'binpack-flow-test:automatic'], stdout=subprocess.DEVNULL)
        internal = subprocess.check_output(['docker', 'image', 'ls', '--format', '{{.Repository}}', 'binpack-internal'], text=True)
        self.assertEqual(internal.strip(), '')


if __name__ == '__main__':
    unittest.main()
