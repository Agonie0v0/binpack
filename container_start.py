"""Prepare the private data mount, then run the service without root privileges."""
import argparse
import os
from pathlib import Path
import sys
import tempfile
import stat


def prepare(directory):
    directory = Path(directory).absolute()
    if directory.is_symlink():
        raise ValueError('DATA_DIR must be a real directory, not a symbolic link')
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    private_files = [directory / name for name in (
        'auth.sqlite3', 'auth.sqlite3-journal', 'auth.sqlite3-wal',
        'auth.sqlite3-shm', 'setup-token')]
    for path in private_files:
        if path.is_symlink():
            raise ValueError(f'{path.name} must not be a symbolic link')
    if os.geteuid() == 0:
        # Only the mount directory and known account files; never recurse into user files.
        for path, mode in [(directory, 0o700), *((p, 0o600) for p in private_files if p.exists())]:
            info = path.stat()
            if (info.st_uid, info.st_gid) != (10001, 10001):
                os.chown(path, 10001, 10001, follow_symlinks=False)
            if info.st_mode & 0o777 != mode:
                os.chmod(path, mode)
        docker_socket = Path(os.getenv('DOCKER_SOCKET', '/var/run/docker.sock'))
        groups = [docker_socket.stat().st_gid] if docker_socket.exists() and stat.S_ISSOCK(docker_socket.stat().st_mode) else []
        os.setgroups(groups)
        os.setgid(10001)
        os.setuid(10001)
    # Check using the final service identity before SQLite attempts to create its files.
    with tempfile.TemporaryFile(dir=directory):
        pass
    for path in private_files:
        if path.exists() and not os.access(path, os.R_OK | os.W_OK):
            raise PermissionError(f'{path.name} is not readable and writable')
    return directory


def main():
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument('--data-dir', default=os.getenv('DATA_DIR', '/data'))
    args, _ = parser.parse_known_args()
    os.umask(0o077)
    try:
        prepare(args.data_dir)
    except (OSError, ValueError) as error:
        print(f'[binpack] Cannot prepare data directory {args.data_dir}: {error}. '
              '请检查数据目录是否可写、磁盘是否有剩余空间，以及 NAS ACL 是否允许访问。'
              '容器服务使用 UID/GID 10001:10001；手动指定 user 时需自行赋予目录权限。',
              file=sys.stderr, flush=True)
        return 1
    os.execv(sys.executable, [sys.executable, '/opt/image-packager/server.py', *sys.argv[1:]])


if __name__ == '__main__':
    sys.exit(main())
