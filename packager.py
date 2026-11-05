"""Authenticated workbench operations; Docker is reached only through its local socket."""
from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
from http.client import HTTPConnection
from pathlib import Path
from urllib.parse import quote, urlencode
import io
import json
import os
import re
import shlex
import shutil
import socket
import struct
import tarfile
import threading
import time
import uuid

BASES = {'alpine': 'alpine:3.23', 'debian': 'debian:trixie-slim'}
IDENTIFIER = re.compile(r'[a-f0-9]{32}\Z')
MAX_UPLOAD = 256 * 1024 * 1024
MAX_CACHE = 10 * 1024**3


class PackageError(Exception):
    def __init__(self, message, status=400):
        self.message, self.status = message, status
        super().__init__(message)


def analyze(path):
    """Read ELF program headers without executing the uploaded file."""
    size = path.stat().st_size
    with path.open('rb') as source:
        header = source.read(64)
        if len(header) < 64 or header[:6] != b'\x7fELF\x02\x01':
            raise PackageError('请选择 Linux 64 位小端 ELF 可执行文件。')
        kind, machine = struct.unpack_from('<HH', header, 16)
        arch = {62: 'amd64', 183: 'arm64'}.get(machine)
        if kind not in (2, 3) or not arch:
            raise PackageError('仅支持 amd64 / arm64 ELF 可执行文件。')
        offset = struct.unpack_from('<Q', header, 32)[0]
        entry_size, count = struct.unpack_from('<HH', header, 54)
        if not count or count > 4096 or entry_size < 56 or offset + count * entry_size > size:
            raise PackageError('ELF 程序头无效或文件不完整。')
        interpreter, dynamic = '', False
        for i in range(count):
            source.seek(offset + i * entry_size)
            segment = source.read(56)
            segment_type = struct.unpack_from('<I', segment)[0]
            dynamic |= segment_type == 2
            if segment_type == 3:
                start, length = struct.unpack_from('<Q', segment, 8)[0], struct.unpack_from('<Q', segment, 32)[0]
                if not 0 < length <= 4096 or start + length > size:
                    raise PackageError('ELF 动态链接器信息无效。')
                source.seek(start)
                interpreter = source.read(length).rstrip(b'\0').decode('ascii', errors='replace')
    runtime = 'alpine' if not interpreter or 'musl' in interpreter else 'debian'
    basis = f'动态链接器：{interpreter}' if interpreter else '未声明外部动态链接器，按静态程序处理。'
    return {'arch': arch, 'runtime': runtime, 'interpreter': interpreter, 'basis': basis,
            'port': '', 'volume': '', 'flags': [], 'help_excerpt': '',
            'note': '启动参数保留程序默认行为。端口与数据目录等待帮助信息识别。',
            'dynamic': dynamic}


def help_defaults(text):
    # Accept explicit defaults only; arbitrary numbers and file paths are not defaults.
    result = {'port': '', 'volume': '', 'flags': []}
    result['flags'] = list(dict.fromkeys(re.findall(r'(?<![\w-])--[a-z][a-z0-9-]{1,35}', text)))[:24]
    for line in text.splitlines():
        default = re.search(r'(?i)(?:\[|\()?default\s*[:=]\s*[\x22\x27]?([^\s\]\)\x22\x27]+)', line)
        if not default:
            continue
        value = default[1].rstrip('.,;')
        if re.search(r'--(?:port|http-port|server-port|listen-port)\b', line) and value.isdigit() and 0 < int(value) < 65536:
            result['port'] = int(value)
        if re.search(r'--(?:data-dir|data-directory|storage-dir)\b', line) and valid_volume(value):
            result['volume'] = value
    return result


def valid_volume(value):
    if not isinstance(value, str) or not value.startswith('/') or len(value) > 200:
        return False
    parts = value.split('/')
    return (not any(c.isspace() or ord(c) < 32 for c in value)
            and '..' not in parts and '.' not in parts
            and value.rstrip('/') not in ('', '/app/program')
            and parts[1] not in ('proc', 'sys', 'dev', 'usr', 'bin', 'sbin', 'etc', 'lib', 'lib64'))


def settings(data):
    name, tag = data.get('image', ''), data.get('tag', 'latest')
    if not isinstance(name, str) or len(name) > 128 or not re.fullmatch(r'[a-z0-9]+(?:[._-][a-z0-9]+)*', name):
        raise PackageError('镜像名称只能包含小写字母、数字和 . _ -。')
    if not isinstance(tag, str) or not re.fullmatch(r'[a-zA-Z0-9_][a-zA-Z0-9_.-]{0,127}', tag):
        raise PackageError('镜像标签无效。')
    runtime, args, volume, port = data.get('runtime', 'auto'), data.get('args', ''), data.get('volume', ''), data.get('port', '')
    if runtime not in ('auto', *BASES) or not isinstance(args, str) or len(args) > 4096:
        raise PackageError('基础环境或启动参数无效。')
    try:
        cmd = shlex.split(args)
    except ValueError:
        raise PackageError('启动参数的引号没有成对闭合。') from None
    if any('\0' in item or '\n' in item or '\r' in item for item in cmd):
        raise PackageError('启动参数不能包含换行或空字符。')
    if volume and not valid_volume(volume):
        raise PackageError('数据目录需为独立的绝对路径，例如 /data 或 /app/config。')
    if port not in ('', None):
        try:
            if isinstance(port, bool) or str(int(port)) != str(port) or not 1 <= int(port) <= 65535:
                raise ValueError
            port = int(port)
        except (ValueError, TypeError):
            raise PackageError('服务端口需为 1–65535 的整数。') from None
    return {'image': name, 'tag': tag, 'runtime': runtime, 'cmd': cmd, 'port': port or '',
            'volume': volume, 'auto_import': data.get('auto_import') is True}


class UnixHTTP(HTTPConnection):
    def __init__(self, path, timeout):
        self.socket_path = path
        super().__init__('localhost', timeout=timeout)

    def connect(self):
        if not hasattr(socket, 'AF_UNIX'):
            raise OSError('Docker Socket is available in the Linux container deployment')
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(self.timeout)
        self.sock.connect(self.socket_path)


class Docker:
    def __init__(self, path=None):
        self.path = path or os.getenv('DOCKER_SOCKET', '/var/run/docker.sock')

    def open(self, method, path, body=None, headers=None, timeout=180):
        connection = UnixHTTP(self.path, timeout)
        try:
            connection.request(method, path, body=body, headers=headers or {})
            response = connection.getresponse()
            if response.status >= 400:
                message = response.read(8192).decode(errors='replace')
                try:
                    message = json.loads(message).get('message', message)
                except ValueError:
                    pass
                raise PackageError(f'Docker：{message[:600]}', 502)
            return connection, response
        except Exception:
            connection.close()
            raise

    def json(self, method, path, data=None, timeout=15):
        body = json.dumps(data).encode() if data is not None else None
        connection, response = self.open(method, path, body, {'Content-Type': 'application/json'}, timeout)
        try:
            payload = response.read(2 * 1024 * 1024)
            return json.loads(payload) if payload else {}
        finally:
            connection.close()

    def status(self):
        try:
            info = self.json('GET', '/info', timeout=2)
            arch = {'x86_64': 'amd64', 'aarch64': 'arm64'}.get(info.get('Architecture'), info.get('Architecture'))
            return {'connected': True, 'arch': arch, 'message': '已连接 NAS Docker'}
        except (OSError, PackageError, ValueError):
            return {'connected': False, 'arch': '', 'message': '尚未连接 Docker，请使用新版 Compose 挂载 Docker Socket。'}

    def events(self, response):
        while True:
            line = response.readline(1024 * 1024)
            if not line:
                break
            try:
                event = json.loads(line)
            except ValueError:
                continue
            if event.get('error'):
                raise PackageError('Docker：' + str(event['error'])[:600], 502)
            yield event

    def build(self, binary, runtime, arch, tag, options=None):
        options = options or {}
        lines = [f'FROM {BASES[runtime]}', 'WORKDIR /app', 'COPY program /usr/local/bin/program',
                 'ENTRYPOINT ["/usr/local/bin/program"]', 'CMD ' + json.dumps(options.get('cmd', [])),
                 'LABEL binpack.build=' + json.dumps(tag)]
        if options.get('port'):
            lines.append(f'EXPOSE {options["port"]}/tcp')
        if options.get('volume'):
            lines.append('VOLUME ' + json.dumps([options['volume']]))
        context = binary.parent / ('context-' + uuid.uuid4().hex + '.tar')
        try:
            with tarfile.open(context, 'w') as archive:
                content = ('\n'.join(lines) + '\n').encode()
                info = tarfile.TarInfo('Dockerfile')
                info.size = len(content)
                archive.addfile(info, io.BytesIO(content))
                info = archive.gettarinfo(str(binary), 'program')
                info.mode, info.uid, info.gid, info.uname, info.gname = 0o755, 0, 0, '', ''
                with binary.open('rb') as source:
                    archive.addfile(info, source)
            with context.open('rb') as source:
                connection, response = self.open('POST', '/build?' + urlencode({
                    't': tag, 'platform': 'linux/' + arch, 'rm': 1, 'forcerm': 1}), source,
                    {'Content-Type': 'application/x-tar', 'Content-Length': str(context.stat().st_size)}, 300)
                try:
                    for _ in self.events(response):
                        pass
                finally:
                    connection.close()
            return self.json('GET', '/images/' + quote(tag, safe='') + '/json')['Id']
        finally:
            context.unlink(missing_ok=True)

    def remove_image(self, tag):
        try:
            self.json('DELETE', '/images/' + quote(tag, safe=''))
        except (OSError, PackageError):
            pass

    def help(self, tag):
        container = None
        try:
            container = self.json('POST', '/containers/create', {
                'Image': tag, 'Cmd': ['--help'], 'User': '65534:65534', 'WorkingDir': '/tmp',
                'NetworkDisabled': True, 'HostConfig': {
                    'NetworkMode': 'none', 'ReadonlyRootfs': True, 'Memory': 134217728,
                    'MemorySwap': 134217728, 'NanoCpus': 500000000, 'PidsLimit': 64,
                    'CapDrop': ['ALL'], 'SecurityOpt': ['no-new-privileges:true'],
                    'Tmpfs': {'/tmp': 'rw,noexec,nosuid,size=16m'},
                    'LogConfig': {'Type': 'json-file', 'Config': {'max-size': '1m', 'max-file': '1'}}}})['Id']
            self.json('POST', f'/containers/{container}/start')
            deadline = time.monotonic() + 6
            while self.json('GET', f'/containers/{container}/json')['State']['Running']:
                if time.monotonic() >= deadline:
                    raise PackageError('帮助信息读取超时，未推断端口和目录。')
                time.sleep(.25)
            connection, response = self.open('GET', f'/containers/{container}/logs?stdout=1&stderr=1', timeout=10)
            try:
                raw = response.read(256 * 1024)
            finally:
                connection.close()
            chunks, cursor = [], 0
            while cursor + 8 <= len(raw) and raw[cursor] in (0, 1, 2) and raw[cursor + 1:cursor + 4] == b'\0\0\0':
                length = int.from_bytes(raw[cursor + 4:cursor + 8], 'big')
                chunks.append(raw[cursor + 8:cursor + 8 + length])
                cursor += 8 + length
            return (b''.join(chunks) if chunks else raw).decode('utf-8', errors='replace')[:64000]
        finally:
            if container:
                try:
                    self.json('DELETE', f'/containers/{container}?force=1')
                except (OSError, PackageError):
                    pass

    def save(self, tag, target, reference):
        original = target.with_suffix('.export')
        try:
            connection, response = self.open('GET', '/images/' + quote(tag, safe='') + '/get', timeout=300)
            try:
                with original.open('wb') as output:
                    shutil.copyfileobj(response, output, 1024 * 1024)
            finally:
                connection.close()
            found = False
            with tarfile.open(original) as source, tarfile.open(target, 'w') as output:
                for member in source:
                    stream = source.extractfile(member) if member.isfile() else None
                    if member.name == 'manifest.json':
                        manifest = json.load(stream)
                        if len(manifest) != 1:
                            raise PackageError('Docker 导出的镜像数量异常。', 502)
                        manifest[0]['RepoTags'] = [reference]
                        payload = json.dumps(manifest).encode()
                        member.size, stream = len(payload), io.BytesIO(payload)
                        found = True
                    elif member.name in ('repositories', 'index.json', 'oci-layout'):
                        # Export a Docker archive deliberately. Containerd prefers OCI index
                        # annotations over manifest.json when both formats are present.
                        continue
                    output.addfile(member, stream)
            if not found:
                raise PackageError('镜像归档缺少 Docker manifest。', 502)
        finally:
            original.unlink(missing_ok=True)

    def load(self, path, reference):
        with path.open('rb') as source:
            connection, response = self.open('POST', '/images/load?quiet=1', source,
                {'Content-Type': 'application/x-tar', 'Content-Length': str(path.stat().st_size)}, 300)
            try:
                for _ in self.events(response):
                    pass
            finally:
                connection.close()
        return self.json('GET', '/images/' + quote(reference, safe='') + '/json')['Id']


class Packager:
    def __init__(self, directory, docker=None):
        self.root = Path(directory)
        self.uploads, self.jobs = self.root / 'uploads', self.root / 'jobs'
        for path in (self.uploads, self.jobs):
            path.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.docker = docker or Docker()
        self.lock = threading.RLock()
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix='packager')
        self.pending = threading.BoundedSemaphore(4)
        self.upload_lock = threading.Lock()
        for folder in self.jobs.iterdir():
            if (folder / 'meta.json').exists():
                meta = self.read(folder)
                if meta.get('status') in ('queued', 'building', 'importing'):
                    self.write(folder, {**meta, 'status': 'failed', 'error': '服务重启中断了任务，请重新打包。'})
        for folder in self.uploads.iterdir():
            if (folder / 'meta.json').exists():
                meta = self.read(folder)
                if meta.get('status') in ('queued', 'analyzing'):
                    self.write(folder, {**meta, 'status': 'ready', 'warning': '分析被重启中断，可重新上传进行分析。'})

    def write(self, folder, data):
        with self.lock:
            temp = folder / 'meta.tmp'
            temp.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
            temp.replace(folder / 'meta.json')
        return data

    def read(self, folder):
        with self.lock:
            try:
                return json.loads((folder / 'meta.json').read_text(encoding='utf-8'))
            except FileNotFoundError:
                raise PackageError('记录不存在或已被清理。', 404) from None

    def folder(self, root, identifier):
        if not isinstance(identifier, str) or not IDENTIFIER.fullmatch(identifier):
            raise PackageError('记录编号无效。', 404)
        return root / identifier

    def submit(self, function, *args):
        if not self.pending.acquire(blocking=False):
            raise PackageError('任务队列已满，请稍后重试。', 429)
        def task():
            try:
                function(*args)
            finally:
                self.pending.release()
        try:
            self.pool.submit(task)
        except Exception:
            self.pending.release()
            raise

    def capacity(self, required):
        used = sum(p.stat().st_size for root in (self.jobs, self.uploads) for p in root.rglob('*') if p.is_file())
        if used + required > MAX_CACHE or shutil.disk_usage(self.root).free < required + 128 * 1024**2:
            raise PackageError('缓存空间不足，请先清理打包记录和未使用的上传文件。', 507)

    def upload(self, source, length, filename):
        if not 64 <= length <= MAX_UPLOAD:
            raise PackageError('文件需为 64 字节至 256 MB 的 ELF 程序。', 413)
        if not self.upload_lock.acquire(blocking=False):
            raise PackageError('正在接收另一个文件，请稍后重试。', 429)
        folder = self.uploads / uuid.uuid4().hex
        try:
            self.capacity(length)
            folder.mkdir(mode=0o700)
            digest, remaining = sha256(), length
            with (folder / 'program').open('wb') as output:
                while remaining:
                    chunk = source.read(min(remaining, 1024 * 1024))
                    if not chunk:
                        raise PackageError('上传中断，请重新选择文件。')
                    output.write(chunk)
                    digest.update(chunk)
                    remaining -= len(chunk)
            result = analyze(folder / 'program')
            filename = ''.join(c for c in filename if c.isprintable())[:160] or 'program'
            meta = self.write(folder, {'id': folder.name, 'filename': filename, 'size': length,
                'sha256': digest.hexdigest(), 'analysis': result, 'status': 'queued', 'created': time.time()})
            try:
                self.submit(self.probe, folder)
            except PackageError as error:
                meta = self.write(folder, {**meta, 'status': 'ready', 'warning': error.message})
            return meta
        except Exception:
            if folder.exists():
                shutil.rmtree(folder)
            raise
        finally:
            self.upload_lock.release()

    def probe(self, folder):
        tag = 'binpack-internal:probe-' + folder.name
        meta = self.read(folder)
        try:
            self.write(folder, {**meta, 'status': 'analyzing'})
            status = self.docker.status()
            if not status['connected']:
                raise PackageError(status['message'])
            if status['arch'] != meta['analysis']['arch']:
                raise PackageError('文件架构与 NAS 不同，已完成静态识别，跳过运行帮助信息。')
            self.docker.build(folder / 'program', meta['analysis']['runtime'], meta['analysis']['arch'], tag)
            text = self.docker.help(tag)
            values = help_defaults(text)
            analysis = {**meta['analysis'], **values, 'help_excerpt': text[:12000],
                'note': '已读取 --help。仅填入明确声明的默认值；启动参数按程序默认行为运行，可自行补充。'}
            if not values['flags']:
                raise PackageError('程序未返回可识别的帮助信息；保留静态分析结果，请按程序文档填写。')
            self.write(folder, {**meta, 'status': 'ready', 'analysis': analysis})
        except Exception as error:
            self.write(folder, {**meta, 'status': 'ready', 'warning': self.error(error)})
        finally:
            self.docker.remove_image(tag)

    @staticmethod
    def error(error):
        if isinstance(error, PackageError):
            return error.message
        if isinstance(error, OSError):
            return 'Docker 连接、网络或数据存储不可用，请检查连接与可用空间后重试。'
        return '任务处理失败，请检查文件和配置后重试。'

    def start(self, data):
        options = settings(data)
        upload = self.folder(self.uploads, data.get('upload_id'))
        with self.lock:
            source = self.read(upload)
            if source['status'] != 'ready':
                raise PackageError('文件仍在识别中，请稍后再生成镜像。', 409)
            if source.get('job_id'):
                raise PackageError('这个上传文件已经打包，请从记录下载或重新上传。', 409)
            folder = self.jobs / uuid.uuid4().hex
            folder.mkdir(mode=0o700)
            meta = {'id': folder.name, 'created': time.time(), 'status': 'queued', 'progress': 5,
                'message': '等待打包', 'options': options, 'arch': source['analysis']['arch'],
                'reference': options['image'] + ':' + options['tag'], 'filename': source['filename'],
                'binary_sha256': source['sha256'], 'imported': False, 'error': ''}
            self.write(folder, meta)
            self.write(upload, {**source, 'job_id': folder.name})
            try:
                self.submit(self.build, folder, upload, source)
            except Exception:
                self.write(upload, source)
                shutil.rmtree(folder)
                raise
            return meta

    def build(self, folder, upload, source):
        tag = 'binpack-internal:build-' + folder.name
        meta = self.read(folder)
        def update(**values):
            meta.update(values)
            self.write(folder, meta)
        try:
            self.capacity(source['size'] * 3 + 256 * 1024**2)
            if not self.docker.status()['connected']:
                raise PackageError('尚未连接 Docker，请按部署说明挂载 Docker Socket。', 503)
            options = meta['options']
            runtime = source['analysis']['runtime'] if options['runtime'] == 'auto' else options['runtime']
            update(status='building', progress=20, message='构建镜像，首次使用需下载基础环境', runtime=runtime)
            image_id = self.docker.build(upload / 'program', runtime, meta['arch'], tag, options)
            update(progress=60, message='导出镜像归档', image_id=image_id)
            self.docker.save(tag, folder / 'image.tar', meta['reference'])
            digest = sha256()
            with (folder / 'image.tar').open('rb') as archive:
                for chunk in iter(lambda: archive.read(1024 * 1024), b''):
                    digest.update(chunk)
            basename = options['image'] + '_' + options['tag']
            (folder / 'image.sha256').write_text(f'{digest.hexdigest()}  {basename}.tar\n', encoding='utf-8')
            compose = {'services': {options['image']: {'image': meta['reference'], 'restart': 'unless-stopped'}}}
            service = compose['services'][options['image']]
            if options['port']:
                service['ports'] = [f'{options["port"]}:{options["port"]}']
            if options['volume']:
                service['volumes'] = ['app-data:' + options['volume']]
                compose['volumes'] = {'app-data': {}}
            # JSON is valid YAML, with exact quoting for every user-supplied value.
            (folder / 'compose.yaml').write_text(json.dumps(compose, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
            update(progress=85, message='镜像归档已生成', archive_bytes=(folder / 'image.tar').stat().st_size,
                   archive_sha256=digest.hexdigest(), archive_ready=True)
            if options['auto_import']:
                update(status='importing', progress=92, message='导入飞牛 Docker 镜像库')
                imported = self.docker.load(folder / 'image.tar', meta['reference'])
                if imported != image_id:
                    raise PackageError('导入结果的镜像 ID 不一致，请手动检查。', 502)
                update(imported=True)
            update(status='complete', progress=100, message='已生成并导入飞牛镜像库' if meta['imported'] else '镜像包已生成')
        except Exception as error:
            update(status='failed', error=self.error(error), message='导入失败，镜像包仍可下载' if meta.get('archive_ready') else '打包失败')
        finally:
            self.docker.remove_image(tag)
            # Completed tasks no longer need a second copy of the uploaded executable.
            if meta.get('archive_ready'):
                (upload / 'program').unlink(missing_ok=True)

    def list(self):
        with self.lock:
            return sorted([self.read(folder) for folder in self.jobs.iterdir() if (folder / 'meta.json').exists()],
                          key=lambda item: item['created'], reverse=True)[:100]

    def import_job(self, identifier):
        folder = self.folder(self.jobs, identifier)
        with self.lock:
            meta = self.read(folder)
            if meta['status'] in ('queued', 'building', 'importing') or not meta.get('archive_ready'):
                raise PackageError('镜像包尚未生成或正在处理。', 409)
            def work():
                try:
                    image_id = self.docker.load(folder / 'image.tar', meta['reference'])
                    if image_id != meta['image_id']:
                        raise PackageError('导入镜像 ID 不一致。', 502)
                    self.write(folder, {**meta, 'status': 'complete', 'imported': True, 'error': '', 'message': '已导入飞牛镜像库', 'progress': 100})
                except Exception as error:
                    self.write(folder, {**meta, 'status': 'failed', 'message': '导入失败，镜像包仍可下载', 'error': self.error(error)})
            active = {**meta, 'status': 'importing', 'message': '正在导入飞牛镜像库'}
            self.write(folder, active)
            try:
                self.submit(work)
            except Exception:
                self.write(folder, meta)
                raise
            return active

    def delete(self, identifier):
        with self.lock:
            folder = self.folder(self.jobs, identifier)
            meta = self.read(folder)
            if meta['status'] in ('queued', 'building', 'importing'):
                raise PackageError('请等待任务结束后再清理。', 409)
            shutil.rmtree(folder)

    def clean_uploads(self):
        with self.upload_lock, self.lock:
            count = 0
            for folder in self.uploads.iterdir():
                meta = self.read(folder)
                active = any(job['id'] == meta.get('job_id') and job['status'] in ('queued', 'building', 'importing') for job in self.list())
                if meta['status'] == 'ready' and not active:
                    shutil.rmtree(folder)
                    count += 1
            return count

    def download(self, identifier, kind):
        folder = self.folder(self.jobs, identifier)
        with self.lock:
            meta = self.read(folder)
            if not meta.get('archive_ready'):
                raise PackageError('文件尚未生成。', 409)
            files = {'image': ('image.tar', '.tar', 'application/x-tar'),
                     'compose': ('compose.yaml', '_compose.yaml', 'application/yaml'),
                     'sha256': ('image.sha256', '.tar.sha256', 'text/plain')}
            if kind not in files:
                raise PackageError('下载文件不存在。', 404)
            filename, extension, content_type = files[kind]
            # Open under the same lock as cache deletion; existing downloads can finish.
            stream = (folder / filename).open('rb')
            return stream, meta['options']['image'] + '_' + meta['options']['tag'] + extension, content_type
