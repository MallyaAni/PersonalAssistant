"""UNRUN bounded stage/prerequisite/observer control; no native or genuine execution admission."""
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
import time
import zlib

TOOLS = Path('/home/animallya96/scratch/capacity-native-origin-observer-tools-20261018-v1')
OUT = Path('/home/animallya96/scratch/capacity-native-origin-observation-20261018-v1')
READER = 'observe-retained-native-json-v1-2026-10-18.py'
PINS = {
    READER: {'bytes': 14395, 'sha256': 'b7f6ffb0b968c08caa0b6133c0d2aa20d75c54f87b0abc80326c28c9096a6e5b'},
    'origin-contract.json': {'bytes': 24905, 'sha256': '4a6ef7b722e4b4eb5e77df8de1be7b3fd2ca604d555985d8048409b5748180f5'},
    'native-proof.json': {'bytes': 46814, 'sha256': '1355771ff667f81e02dbe07885914dd5be8bf5cf395a3e74ef3bfdfd4988c6f7'},
    'native-inspect.json': {'bytes': 9755, 'sha256': 'd5265be87b979e83e396e18d1d9d4571cc6e1db5aa09239200004a2809bd90d2'},
}
FIELDS = ('st_dev', 'st_ino', 'st_mode', 'st_uid', 'st_nlink', 'st_size', 'st_blocks', 'st_mtime_ns', 'st_ctime_ns')
WORK = 0
READ_CALLS = 0


# Keep exact physical fields as decimal strings in every receipt.
def physical(value):
    return {name: str(getattr(value, name)) for name in FIELDS}


# Precharge every control digest to one separate finite staging/authentication ledger.
def digest(raw):
    global WORK
    assert len(raw) <= 4194304 - WORK, 'NATIVE_CONTROL_HASH_WORK_BOUND'
    WORK += len(raw)
    return hashlib.sha256(raw).hexdigest()


# Reject duplicate object fields in all bounded protocol and receipt JSON.
def unique(entries):
    assert len(entries) <= 256
    result = {}
    for name, item in entries:
        assert type(name) is str and len(name.encode('utf-8')) <= 4096 and name not in result
        result[name] = item
    return result


# Refuse noninteger numeric values in this integer-and-string control protocol.
def invalid_number(text):
    raise ValueError('NATIVE_CONTROL_NONINTEGER_NUMBER_' + text)


# Parse only complete bounded control objects without duplicate or nonfinite values.
def parse(raw):
    assert len(raw) <= 65536
    return json.loads(raw, object_pairs_hook=unique, parse_constant=invalid_number, parse_float=invalid_number)


# Read one fixed ordinary file twice with complete physical and SHA bookends.
def read(path, pin=None):
    global READ_CALLS
    assert READ_CALLS < 1024 and path.resolve(strict=True) == path
    READ_CALLS += 1
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        before = os.fstat(fd)
        assert stat.S_ISREG(before.st_mode) and before.st_uid == 1000 and before.st_nlink == 1
        assert 0 <= before.st_size <= 262144
        raw = os.read(fd, 262145)
        os.lseek(fd, 0, os.SEEK_SET)
        assert os.read(fd, 262145) == raw and len(raw) == before.st_size
        assert physical(before) == physical(os.fstat(fd)) == physical(os.lstat(path))
        row = {'bytes': len(raw), 'sha256': digest(raw), 'physical': physical(before)}
        if pin is not None:
            assert all(row[name] == value for name, value in pin.items())
        return raw, row
    finally:
        os.close(fd)


# Persist an exclusive bounded stage file and verify the complete fsynced content.
def write(name, raw):
    assert name in set(PINS) | {'stage.json'} and len(raw) <= 262144
    expected = {'bytes': len(raw), 'sha256': digest(raw)}
    with (TOOLS / name).open('xb') as output:
        output.write(raw)
        output.flush()
        os.fsync(output.fileno())
    observed, row = read(TOOLS / name, expected)
    assert observed == raw
    return row


# Expand one exact single gzip member without concatenation, trailing data or cap relaxation.
def expand(name, item):
    assert type(item) is dict and set(item) == {'bytes', 'sha256', 'gzip_bytes', 'gzip_sha256', 'gzip_base64'}
    assert {key: item[key] for key in ('bytes', 'sha256')} == PINS[name]
    assert type(item['gzip_bytes']) is int and 0 < item['gzip_bytes'] <= 65536
    assert type(item['gzip_base64']) is str and len(item['gzip_base64']) <= 65536
    compressed = base64.b64decode(item['gzip_base64'], validate=True)
    assert len(compressed) == item['gzip_bytes'] and digest(compressed) == item['gzip_sha256']
    inflater = zlib.decompressobj(31)
    raw = inflater.decompress(compressed, item['bytes'] + 1)
    assert inflater.eof and not inflater.unused_data and not inflater.unconsumed_tail
    assert len(raw) == item['bytes'] <= 262144 and digest(raw) == item['sha256']
    return raw


# Validate a complete historical headroom declaration without treating it as a reservation.
def check_resources(value):
    assert type(value) is dict and set(value) == {'MemAvailable_bytes', 'scratch_available_bytes', 'scratch_available_inodes', 'headroom_is_reservation'}
    assert value['headroom_is_reservation'] is False
    for key, minimum in (('MemAvailable_bytes', 2147483648), ('scratch_available_bytes', 33554432), ('scratch_available_inodes', 512)):
        text = value[key]
        assert type(text) is str and 0 < len(text) <= 32 and text.isascii() and text.isdecimal() and str(int(text)) == text and int(text) >= minimum


# Observe bounded current host headroom without reading process environments or dependencies.
def resources():
    fd = os.open('/proc/meminfo', os.O_RDONLY | os.O_NOFOLLOW)
    try:
        raw = os.read(fd, 65537)
        assert len(raw) <= 65536
    finally:
        os.close(fd)
    matches = [line.split() for line in raw.decode('ascii').splitlines() if line.split()[:1] == ['MemAvailable:']]
    assert len(matches) == 1 and len(matches[0]) == 3 and matches[0][2] == 'kB'
    assert matches[0][1].isascii() and matches[0][1].isdecimal()
    available = int(matches[0][1]) * 1024
    space = os.statvfs(TOOLS.parent)
    assert available >= 2147483648 and space.f_bavail * space.f_frsize >= 33554432 and space.f_favail >= 512
    return {'MemAvailable_bytes': str(available), 'scratch_available_bytes': str(space.f_bavail * space.f_frsize),
        'scratch_available_inodes': str(space.f_favail), 'headroom_is_reservation': False}


# Bound the direct staging namespace before constructing its exact name set.
def staged_names():
    result = set()
    with os.scandir(TOOLS) as entries:
        for entry in entries:
            assert len(result) < 16 and len(entry.name.encode('utf-8')) <= 256
            result.add(entry.name)
    return result


# Authenticate only the new staged files and stage receipt, never historical page or target bodies.
def snapshot(staged, control_sha, packet_sha):
    assert TOOLS.parent.resolve(strict=True) == TOOLS.parent and OUT.parent == TOOLS.parent
    assert not os.path.lexists(OUT)
    files, root_physical, stage_sha = {}, None, None
    if not staged:
        assert not os.path.lexists(TOOLS)
    else:
        assert TOOLS.resolve(strict=True) == TOOLS
        root_before = TOOLS.stat(follow_symlinks=False)
        assert stat.S_ISDIR(root_before.st_mode) and root_before.st_uid == 1000
        assert staged_names() == set(PINS) | {'stage.json'}
        for name, pin in PINS.items():
            _, files[name] = read(TOOLS / name, pin)
        raw, files['stage.json'] = read(TOOLS / 'stage.json')
        stage = parse(raw)
        assert set(stage) == {'schema', 'control_source_sha256', 'base_packet_sha256', 'source_pins', 'files',
            'root_physical', 'prerequisite_sha256', 'resources', 'observed_at_ns', 'reader_executed', 'native_runtime_admission'}
        assert stage['schema'] == 'native-origin-source-stage/1' and stage['control_source_sha256'] == control_sha
        assert stage['base_packet_sha256'] == packet_sha and stage['source_pins'] == PINS
        assert stage['files'] == {name: files[name] for name in PINS}
        assert stage['reader_executed'] is False and stage['native_runtime_admission'] is None
        prior_sha = stage['prerequisite_sha256']
        assert type(prior_sha) is str and len(prior_sha) == 64 and set(prior_sha) <= set('0123456789abcdef')
        observed = stage['observed_at_ns']
        assert type(observed) is str and 0 < len(observed) <= 32 and observed.isascii() and observed.isdecimal() and str(int(observed)) == observed
        assert int(observed) <= time.time_ns()
        check_resources(stage['resources'])
        assert physical(root_before) == stage['root_physical']
        for name, pin in files.items():
            read(TOOLS / name, pin)
        assert staged_names() == set(PINS) | {'stage.json'}
        assert physical(root_before) == physical(TOOLS.stat(follow_symlinks=False))
        root_physical, stage_sha = physical(root_before), files['stage.json']['sha256']
    return {'tools_absent': not staged, 'output_absent': True, 'root_physical': root_physical,
        'stage_sha256': stage_sha, 'files': files, 'resources': resources()}


# Bind an independently reviewed actual prerequisite and refuse stale or mismatched observations.
def prerequisite(raw, expected_sha, phase, state, control_sha, packet_sha):
    assert raw and len(raw) <= 65536 and digest(raw) == expected_sha
    value = parse(raw)
    assert set(value) == {'schema', 'phase', 'control_source_sha256', 'base_packet_sha256', 'source_pins',
        'hostname', 'uid', 'python', 'observed_at_ns', 'state', 'native_runtime_admission', 'reader_executed'}
    assert value['schema'] == 'native-origin-readonly-prerequisite/1' and value['phase'] == phase
    assert value['control_source_sha256'] == control_sha and value['base_packet_sha256'] == packet_sha and value['source_pins'] == PINS
    assert value['hostname'] == socket.gethostname() == 'animallya-spark1' and type(value['uid']) is int and value['uid'] == 1000
    assert value['python'] == sys.version and value['reader_executed'] is False and value['native_runtime_admission'] is None
    observed = value['observed_at_ns']
    assert type(observed) is str and observed.isascii() and observed.isdecimal() and str(int(observed)) == observed
    assert 0 <= time.time_ns() - int(observed) <= 300000000000
    assert set(value['state']) == set(state)
    assert all(value['state'][key] == state[key] for key in state if key != 'resources')
    check_resources(value['state']['resources'])


# Escape ordinary termination and wall deadlines before incomplete work can be called accepted.
def stop(number, frame):
    raise KeyboardInterrupt('NATIVE_ORIGIN_CONTROL_SIGNAL_' + str(number))


# Stage or observe only through separate explicit routes after complete source and prerequisite binding.
def main(arguments):
    assert len(arguments) == 3
    phase, packet_sha, prerequisite_sha = arguments
    assert phase in ('before-stage', 'stage', 'before-observe', 'observe')
    assert __debug__ and sys.platform == 'linux' and os.getuid() == 1000 and socket.gethostname() == 'animallya-spark1'
    os.umask(0o077)
    os.nice(10)
    for limit, value in ((resource.RLIMIT_AS, 536870912), (resource.RLIMIT_CPU, 20), (resource.RLIMIT_FSIZE, 262144)):
        resource.setrlimit(limit, (value, value))
    for number in (signal.SIGALRM, signal.SIGINT, signal.SIGHUP, signal.SIGTERM):
        signal.signal(number, stop)
    signal.alarm(30)
    wire = sys.stdin.buffer.read(65537)
    assert len(wire) <= 65536
    envelope = parse(wire)
    assert set(envelope) == {'base_packet_base64', 'prerequisite_base64'}
    packet_raw = base64.b64decode(envelope['base_packet_base64'], validate=True)
    assert digest(packet_raw) == packet_sha
    packet = parse(packet_raw)
    assert set(packet) == {'schema', 'control_source_sha256', 'files'} and packet['schema'] == 'native-origin-control-packet/1'
    assert type(packet['files']) is dict and set(packet['files']) == set(PINS)
    control_sha = packet['control_source_sha256']
    assert type(control_sha) is str and len(control_sha) == 64 and set(control_sha) <= set('0123456789abcdef')
    payload = {name: expand(name, item) for name, item in packet['files'].items()}
    assert sum(map(len, payload.values())) == 95869
    state = snapshot(phase in ('before-observe', 'observe'), control_sha, packet_sha)
    if phase.startswith('before-'):
        assert prerequisite_sha == 'NONE' and envelope['prerequisite_base64'] is None
        proof = {'schema': 'native-origin-readonly-prerequisite/1', 'phase': phase,
            'control_source_sha256': control_sha, 'base_packet_sha256': packet_sha, 'source_pins': PINS,
            'hostname': socket.gethostname(), 'uid': os.getuid(), 'python': sys.version,
            'observed_at_ns': str(time.time_ns()), 'state': state, 'native_runtime_admission': None, 'reader_executed': False}
    else:
        prior = base64.b64decode(envelope['prerequisite_base64'], validate=True)
        prerequisite(prior, prerequisite_sha, 'before-stage' if phase == 'stage' else 'before-observe', state, control_sha, packet_sha)
        if phase == 'stage':
            dispatch_resources = resources()
            TOOLS.mkdir(mode=0o700, exist_ok=False)
            files = {name: write(name, body) for name, body in payload.items()}
            proof = {'schema': 'native-origin-source-stage/1', 'control_source_sha256': control_sha,
                'base_packet_sha256': packet_sha, 'source_pins': PINS, 'files': files,
                'root_physical': None, 'prerequisite_sha256': prerequisite_sha, 'resources': dispatch_resources,
                'observed_at_ns': str(time.time_ns()), 'reader_executed': False, 'native_runtime_admission': None}
            fd = os.open(TOOLS / 'stage.json', os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
            try:
                info = os.fstat(fd)
                assert info.st_size == 0 and info.st_nlink == 1 and info.st_uid == 1000 and stat.S_ISREG(info.st_mode)
                proof['root_physical'] = physical(TOOLS.stat(follow_symlinks=False))
                body = (json.dumps(proof, sort_keys=True, separators=(',', ':'), allow_nan=False) + '\n').encode('ascii')
                assert len(body) <= 65536
                assert physical(info) == physical(os.fstat(fd)) == physical(os.lstat(TOOLS / 'stage.json'))
                assert os.write(fd, body) == len(body)
                os.fsync(fd)
                held = physical(os.fstat(fd))
                assert held == physical(os.lstat(TOOLS / 'stage.json'))
            finally:
                os.close(fd)
            observed, _ = read(TOOLS / 'stage.json', {'bytes': len(body), 'sha256': digest(body), 'physical': held})
            assert observed == body
            snapshot(True, control_sha, packet_sha)
            for directory in (TOOLS, TOOLS.parent):
                descriptor = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
                try:
                    os.fsync(descriptor)
                finally:
                    os.close(descriptor)
        else:
            assert phase == 'observe'
            source, _ = read(TOOLS / READER, PINS[READER])
            assert source == payload[READER]
            resources()
            signal.alarm(0)
            sys.argv = [str(TOOLS / READER), '--observe-retained-native-json-v1']
            exec(compile(source, str(TOOLS / READER), 'exec', dont_inherit=True),
                {'__name__': '__main__', '__file__': str(TOOLS / READER)})
            return
    raw = (json.dumps(proof, sort_keys=True, separators=(',', ':'), allow_nan=False) + '\n').encode('ascii')
    assert len(raw) <= 65536
    digest(raw)
    print(raw.decode('ascii'), end='', flush=True)
    signal.alarm(0)


if __name__ == '__main__':
    main(sys.argv[1:])
