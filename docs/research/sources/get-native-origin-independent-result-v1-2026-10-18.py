"""Retrieve only the exact new independent historical-DATA proof and its stage receipt."""
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

ROOT = Path('/home/animallya96/scratch/capacity-native-origin-independent-20261018-v1')
TOOLS = Path('/home/animallya96/scratch/capacity-native-origin-independent-tools-20261018-v1')
PIN = {'bytes': 14794, 'sha256': '13f2f1e95d2b9d2c8125536dbf53dc9fa77bb4adf1818d820852b1063413a6ad'}
FIELDS = ('st_dev', 'st_ino', 'st_mode', 'st_uid', 'st_nlink', 'st_size', 'st_blocks', 'st_mtime_ns', 'st_ctime_ns')
USED = 0


# Charge every result-getter digest before hashing, independently of the completed reader.
def digest(raw):
    global USED
    assert len(raw) <= 4194304 - USED
    USED += len(raw)
    return hashlib.sha256(raw).hexdigest()


# Retain exact physical identities without lossy numeric projection.
def physical(value):
    return {key: str(getattr(value, key)) for key in FIELDS}


# Read one fixed bounded result file twice and later permit exact physical reauthentication.
def read(path, expected):
    assert path.resolve(strict=True) == path
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        before = os.fstat(fd)
        assert stat.S_ISREG(before.st_mode) and before.st_uid == 1000 and before.st_nlink == 1 and 0 <= before.st_size <= 262144
        raw = os.read(fd, 262145)
        os.lseek(fd, 0, os.SEEK_SET)
        assert os.read(fd, 262145) == raw and len(raw) == before.st_size
        row = {'bytes': len(raw), 'sha256': digest(raw), 'physical': physical(before)}
        assert physical(before) == physical(os.fstat(fd)) == physical(os.lstat(path))
        assert all(row[key] == value for key, value in expected.items())
        return raw, row
    finally:
        os.close(fd)


# Escape signals and deadlines rather than returning partial result evidence.
def stop(number, frame):
    raise KeyboardInterrupt('NATIVE_ORIGIN_RESULT_SIGNAL_' + str(number))


# Bound the owned output namespace before comparing the single exact proof filename.
def names():
    found = set()
    with os.scandir(ROOT) as entries:
        for entry in entries:
            assert len(found) < 3 and len(entry.name.encode('utf-8')) <= 256
            found.add(entry.name)
    return found


# Retrieve only the pinned independent proof and its stage, without rerunning either historical reader.
def main():
    assert __debug__ and sys.platform == 'linux' and socket.gethostname() == 'animallya-spark1' and os.getuid() == 1000
    for limit, value in ((resource.RLIMIT_AS, 536870912), (resource.RLIMIT_CPU, 20), (resource.RLIMIT_FSIZE, 262144)):
        resource.setrlimit(limit, (value, value))
    for number in (signal.SIGALRM, signal.SIGINT, signal.SIGHUP, signal.SIGTERM):
        signal.signal(number, stop)
    signal.alarm(30)
    os.nice(10)
    fd = os.open('/proc/meminfo', os.O_RDONLY | os.O_NOFOLLOW)
    try:
        memory = os.read(fd, 65537)
        assert len(memory) <= 65536
    finally:
        os.close(fd)
    available = [line.split() for line in memory.decode('ascii').splitlines() if line.split()[:1] == ['MemAvailable:']]
    assert len(available) == 1 and len(available[0]) == 3 and available[0][2] == 'kB'
    assert available[0][1].isascii() and available[0][1].isdecimal()
    space = os.statvfs(ROOT.parent)
    resources = {'MemAvailable_bytes': str(int(available[0][1]) * 1024),
        'scratch_available_bytes': str(space.f_bavail * space.f_frsize), 'scratch_available_inodes': str(space.f_favail),
        'headroom_is_reservation': False}
    assert int(resources['MemAvailable_bytes']) >= 2147483648 and int(resources['scratch_available_bytes']) >= 33554432 and space.f_favail >= 512
    assert ROOT.resolve(strict=True) == ROOT and TOOLS.resolve(strict=True) == TOOLS
    assert names() == {'proof.json'}
    roots = {str(path): physical(os.stat(path, follow_symlinks=False)) for path in (ROOT, TOOLS)}
    body, row = read(ROOT / 'proof.json', PIN)
    proof = json.loads(body)
    assert proof['schema'] == 'independent-retained-native-json/1' and proof['status'] == 'HISTORICAL_ARTIFACT_BYTES_ONLY'
    assert proof['complete_raw_equal'] is True and proof['complete_canonical_summary_equal'] is True
    assert proof['native_runtime_admission'] is None and proof['genuine_execution_authorized'] is False
    stage, stage_row = read(TOOLS / 'stage.json',
        {'bytes': 1285, 'sha256': 'f640b131690a5d3332d1ddc1d16e64f8a1cca54b6b4f0884e66966d0d5c76c97'})
    inventory = {str(ROOT / 'proof.json'): row, str(TOOLS / 'stage.json'): stage_row}
    for path, pin in inventory.items():
        read(Path(path), pin)
    assert names() == {'proof.json'}
    assert roots == {str(path): physical(os.stat(path, follow_symlinks=False)) for path in (ROOT, TOOLS)}
    result = {'schema': 'native-origin-independent-result-retrieval/1', 'inventory': inventory,
        'retained': {'proof.json': base64.b64encode(body).decode('ascii'), 'stage.json': base64.b64encode(stage).decode('ascii')},
        'resources': resources, 'root_physical': roots, 'hash_work_before_output': USED,
        'reader_rerun': False, 'native_runtime_admission': None}
    raw = json.dumps(result, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('ascii') + b'\n'
    assert len(raw) <= 262144
    digest(raw)
    print(raw.decode('ascii'), end='', flush=True)
    signal.alarm(0)


if __name__ == '__main__':
    main()
