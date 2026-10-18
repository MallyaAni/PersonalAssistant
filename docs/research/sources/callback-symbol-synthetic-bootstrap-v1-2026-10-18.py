"""Bounded source staging or one separately reviewed SYNTHETIC63 owner invocation."""
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
import zlib

TOOLS = Path('/home/animallya96/scratch/callback-symbol-synthetic-tools-20261018-v1')
RUN = Path('/home/animallya96/scratch/callback-symbol-synthetic-run-20261018-v1')
PINS = {
    'parse-callback-symbol-data-v1-2026-10-18.py': ('6fe24522e57910ed2f9136762ea4f910f46fd6a6a91afe4f55c80b5e8462bd11', 13496),
    'fold-callback-symbol-data-v1-2026-10-18.py': ('a526e85d63313fac8a4de11eb31dc34964ad9eaeed6d93a4a78d25cb5b469127', 14287),
    'check-callback-symbol-data-v1-2026-10-18.py': ('847127b3a70b7522645e8901c881cb135ca2da5850400c9a282647096a9cd76d', 17574),
    'run-callback-symbol-checks-v1-2026-10-18.py': ('5bbae0ddefe3fe32ce83e163e58d72ea1b5f99d55d682149af35a42f5b6d3f0f', 9318),
}


# Retain exact decimal physical fields without a floating point representation.
def physical(value):
    return {key: str(getattr(value, key)) for key in ('st_dev', 'st_ino', 'st_mode',
        'st_uid', 'st_nlink', 'st_size', 'st_blocks', 'st_mtime_ns', 'st_ctime_ns')}


# Bind two full held reads to the same named regular source or result file.
def read(path):
    assert path.resolve(strict=True) == path
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        before = os.fstat(descriptor)
        assert stat.S_ISREG(before.st_mode) and before.st_uid == 1000 and before.st_nlink == 1
        assert 0 <= before.st_size <= 262144
        raw = os.read(descriptor, 262145)
        os.lseek(descriptor, 0, os.SEEK_SET)
        assert os.read(descriptor, 262145) == raw and len(raw) == before.st_size
        assert physical(before) == physical(os.fstat(descriptor)) == physical(path.stat(follow_symlinks=False))
        return raw, {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(), 'physical': physical(before)}
    finally:
        os.close(descriptor)


# Sync a finite new root and its resolved parent after exclusive file persistence.
def sync(root):
    for directory in (root, root.resolve(strict=True).parent):
        descriptor = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)


# Gate staging or execution on fresh host headroom without claiming a reservation.
def resources():
    available = None
    for line in Path('/proc/meminfo').read_text().splitlines():
        fields = line.split()
        if fields and fields[0] == 'MemAvailable:':
            assert len(fields) == 3 and fields[2] == 'kB'
            available = int(fields[1]) * 1024
    assert available is not None and available >= 2147483648
    filesystems = {}
    for directory in (TOOLS.parent, Path('/tmp')):
        value = os.statvfs(directory)
        free = value.f_bavail * value.f_frsize
        assert free >= 33554432 and value.f_favail >= 128
        filesystems[str(directory)] = {'available_bytes': str(free), 'available_inodes': str(value.f_favail)}
    return {'MemAvailable_bytes': str(available), 'filesystems': filesystems, 'reservation': False}


# Authenticate a finite compressed source envelope and stage or run exactly once by explicit phase.
def main():
    assert __debug__ and sys.platform == 'linux' and os.getuid() == 1000
    assert socket.gethostname() == 'animallya-spark1'
    assert len(sys.argv) == 3 and sys.argv[1] in ('stage', 'run')
    phase, stage_sha = sys.argv[1:]
    assert (phase == 'stage' and stage_sha == 'NONE') or (phase == 'run' and len(stage_sha) == 64 and all(c in '0123456789abcdef' for c in stage_sha))
    resource.setrlimit(resource.RLIMIT_AS, (536870912, 536870912))
    resource.setrlimit(resource.RLIMIT_CPU, (20, 20))
    resource.setrlimit(resource.RLIMIT_FSIZE, (262144, 262144))
    signal.alarm(30)
    os.umask(0o077)
    raw = sys.stdin.buffer.read(65537)
    assert len(raw) <= 65536
    packet = json.loads(raw)
    assert type(packet) is dict and set(packet) == set(PINS)
    sources = {}
    for name, (digest, size) in PINS.items():
        compressed = base64.b64decode(packet[name], validate=True)
        assert len(compressed) <= 262144 and size <= 262144
        decoder = zlib.decompressobj(31)
        body = decoder.decompress(compressed, size + 1)
        assert len(body) == size and decoder.eof and not decoder.unused_data and not decoder.unconsumed_tail
        assert hashlib.sha256(body).hexdigest() == digest
        sources[name] = body
    assert TOOLS.parent.resolve(strict=True) == TOOLS.parent
    assert not os.path.lexists(RUN)
    headroom = resources()
    inventory = {}
    if phase == 'stage':
        assert not os.path.lexists(TOOLS)
        TOOLS.mkdir(mode=0o700, exist_ok=False)
        for name, body in sources.items():
            with (TOOLS / name).open('xb') as output:
                output.write(body)
                output.flush()
                os.fsync(output.fileno())
            retained, row = read(TOOLS / name)
            assert retained == body
            inventory[name] = row
        proof = {'schema': 'callback-symbol-synthetic-stage/1', 'scope': 'SOURCE_ONLY_ALL63_UNRUN',
            'inventory': inventory, 'resources': headroom, 'uid': os.getuid(), 'hostname': socket.gethostname(),
            'python': sys.version, 'wire_bytes': len(raw), 'wire_sha256': hashlib.sha256(raw).hexdigest(),
            'source_envelope': 'exact-size-bounded-single-gzip-member/1', 'run_root_absent': True}
        body = json.dumps(proof, sort_keys=True).encode() + b'\n'
        with (TOOLS / 'stage.json').open('xb') as output:
            output.write(body)
            output.flush()
            os.fsync(output.fileno())
        assert read(TOOLS / 'stage.json')[0] == body
        sync(TOOLS)
        print(body.decode(), end='', flush=True)
    else:
        stage_body, stage_row = read(TOOLS / 'stage.json')
        assert stage_row['sha256'] == stage_sha
        stage = json.loads(stage_body)
        assert stage['scope'] == 'SOURCE_ONLY_ALL63_UNRUN' and set(stage['inventory']) == set(PINS)
        for name, body in sources.items():
            retained, row = read(TOOLS / name)
            assert retained == body and row == stage['inventory'][name]
            inventory[name] = row
        admission = {'schema': 'callback-symbol-synthetic-scoped-invocation/1',
            'stage_sha256': stage_sha, 'resources': headroom, 'source_inventory': inventory,
            'scope': 'ONE_NEW_SYNTHETIC63_ONLY', 'host_python_not_N2_runtime': True}
        body = json.dumps(admission, sort_keys=True).encode() + b'\n'
        with (TOOLS / 'invocation.json').open('xb') as output:
            output.write(body)
            output.flush()
            os.fsync(output.fileno())
        assert read(TOOLS / 'invocation.json')[0] == body
        sync(TOOLS)
        signal.alarm(0)
        name = 'run-callback-symbol-checks-v1-2026-10-18.py'
        sys.argv = [str(TOOLS / name)]
        exec(compile(sources[name], str(TOOLS / name), 'exec', dont_inherit=True),
            {'__name__': '__main__', '__file__': str(TOOLS / name)})
        signal.alarm(30)
        retained = {}
        for name in ('stage.json', 'invocation.json'):
            body, row = read(TOOLS / name)
            retained['tools/' + name] = dict(row, base64=base64.b64encode(body).decode())
        for path in sorted(RUN.iterdir()):
            body, row = read(path)
            retained['run/' + path.name] = dict(row, base64=base64.b64encode(body).decode())
        for name, row in inventory.items():
            assert read(TOOLS / name)[1] == row
        assert read(TOOLS / 'stage.json')[1] == stage_row
        result = json.dumps({'schema': 'callback-symbol-synthetic-return/1', 'retained': retained}, sort_keys=True).encode()
        assert len(result) <= 262144
        print(result.decode(), flush=True)
    signal.alarm(0)


if __name__ == '__main__':
    main()
