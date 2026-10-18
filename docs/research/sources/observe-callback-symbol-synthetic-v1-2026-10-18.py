"""Independently read retained new synthetic controls and results, without rerunning fixtures."""
import base64
import hashlib
import json
import os
from pathlib import Path
import resource
import signal
import socket
import stat
import sys

TOOLS = Path('/home/animallya96/scratch/callback-symbol-synthetic-tools-20261018-v1')
RUN = Path('/home/animallya96/scratch/callback-symbol-synthetic-run-20261018-v1')


# Preserve exact identity, allocation and nanosecond fields as decimal strings.
def physical(value):
    return {key: str(getattr(value, key)) for key in ('st_dev', 'st_ino', 'st_mode',
        'st_uid', 'st_nlink', 'st_size', 'st_blocks', 'st_mtime_ns', 'st_ctime_ns')}


# Read complete bounded file bytes twice and bind their held and named physical identities.
def read(path):
    assert path.resolve(strict=True) == path
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        before = os.fstat(descriptor)
        assert stat.S_ISREG(before.st_mode) and before.st_nlink == 1 and before.st_uid == 1000
        assert 0 <= before.st_size <= 262144
        first = os.read(descriptor, 262145)
        os.lseek(descriptor, 0, os.SEEK_SET)
        second = os.read(descriptor, 262145)
        assert first == second and len(first) == before.st_size
        assert physical(before) == physical(os.fstat(descriptor)) == physical(path.stat(follow_symlinks=False))
        return first, {'bytes': len(first), 'sha256': hashlib.sha256(first).hexdigest(), 'physical': physical(before)}
    finally:
        os.close(descriptor)


# Observe every immediate retained control and run file with a later complete source and result bookend.
def main():
    assert __debug__ and sys.platform == 'linux' and os.getuid() == 1000 and socket.gethostname() == 'animallya-spark1'
    resource.setrlimit(resource.RLIMIT_AS, (536870912, 536870912))
    resource.setrlimit(resource.RLIMIT_CPU, (20, 20))
    resource.setrlimit(resource.RLIMIT_FSIZE, (262144, 262144))
    signal.alarm(30)
    assert sys.argv[1:] == ['observe', 'NONE'] and sys.stdin.buffer.read(3) == b'{}'
    files, inventories, total = {}, {}, 0
    for label, root in (('tools', TOOLS), ('run', RUN)):
        assert root.resolve(strict=True) == root and root.is_dir()
        names = sorted(p.name for p in root.iterdir())
        assert 1 <= len(names) <= 16
        inventories[label] = names
        for name in names:
            raw, row = read(root / name)
            total += len(raw)
            assert total <= 131072
            files[label + '/' + name] = dict(row, base64=base64.b64encode(raw).decode())
    for key, row in files.items():
        label, name = key.split('/', 1)
        root = TOOLS if label == 'tools' else RUN
        raw, current = read(root / name)
        assert current == {k: v for k, v in row.items() if k != 'base64'}
    for label, root in (('tools', TOOLS), ('run', RUN)):
        assert sorted(p.name for p in root.iterdir()) == inventories[label]
    body = json.dumps({'schema': 'callback-symbol-synthetic-independent-observation/1',
        'scope': 'RETAINED_DATA_ONLY_NO_FIXTURE_OR_DECODER_REPLAY', 'files': files,
        'inventories': inventories, 'full_input_bytes': total, 'python': sys.version}, sort_keys=True).encode()
    assert len(body) <= 262144
    print(body.decode(), flush=True)
    signal.alarm(0)


if __name__ == '__main__':
    main()
