'UNRUN native-origin stage/prerequisite/observation transport; no dispatch admitted.'
import base64
import hashlib
import json
import os
from pathlib import Path
import resource
import shlex
import signal
import subprocess
import stat
import sys
import time

REPO = Path('/Users/animallya/.codex/worktrees/learned-live-release-20261006/PersonalAssistant')
LOCAL = Path('/tmp/native-origin-' + sys.argv[1] + '-transport-20261018-v1')
TRUSTED = Path('/tmp/checkpoint-image-hostkeys-20261017-v1')
KEYS = b'172.16.8.3 ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAINHTL/KivuZJ4KwrNAPy+2RnonvooU7mqwOvqA8anY8s\n192.168.100.2 ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIBUse1bIT4RgPgnmirFkc+tr3tcBTKsLCJpQkbZS9QGm\n'
PINS = {'observe-retained-native-json-v1-2026-10-18.py': 'b7f6ffb0b968c08caa0b6133c0d2aa20d75c54f87b0abc80326c28c9096a6e5b', 'origin-contract.json': '4a6ef7b722e4b4eb5e77df8de1be7b3fd2ca604d555985d8048409b5748180f5', 'native-proof.json': '1355771ff667f81e02dbe07885914dd5be8bf5cf395a3e74ef3bfdfd4988c6f7', 'native-inspect.json': 'd5265be87b979e83e396e18d1d9d4571cc6e1db5aa09239200004a2809bd90d2'}
BOOTSTRAP = '"""UNRUN bounded stage/prerequisite/observer control; no native or genuine execution admission."""\nimport base64\nimport hashlib\nimport json\nimport os\nfrom pathlib import Path\nimport resource\nimport signal\nimport socket\nimport stat\nimport sys\nimport time\nimport zlib\n\nTOOLS = Path(\'/home/animallya96/scratch/capacity-native-origin-observer-tools-20261018-v1\')\nOUT = Path(\'/home/animallya96/scratch/capacity-native-origin-observation-20261018-v1\')\nREADER = \'observe-retained-native-json-v1-2026-10-18.py\'\nPINS = {\n    READER: {\'bytes\': 14395, \'sha256\': \'b7f6ffb0b968c08caa0b6133c0d2aa20d75c54f87b0abc80326c28c9096a6e5b\'},\n    \'origin-contract.json\': {\'bytes\': 24905, \'sha256\': \'4a6ef7b722e4b4eb5e77df8de1be7b3fd2ca604d555985d8048409b5748180f5\'},\n    \'native-proof.json\': {\'bytes\': 46814, \'sha256\': \'1355771ff667f81e02dbe07885914dd5be8bf5cf395a3e74ef3bfdfd4988c6f7\'},\n    \'native-inspect.json\': {\'bytes\': 9755, \'sha256\': \'d5265be87b979e83e396e18d1d9d4571cc6e1db5aa09239200004a2809bd90d2\'},\n}\nFIELDS = (\'st_dev\', \'st_ino\', \'st_mode\', \'st_uid\', \'st_nlink\', \'st_size\', \'st_blocks\', \'st_mtime_ns\', \'st_ctime_ns\')\nWORK = 0\nREAD_CALLS = 0\n\n\n# Keep exact physical fields as decimal strings in every receipt.\ndef physical(value):\n    return {name: str(getattr(value, name)) for name in FIELDS}\n\n\n# Precharge every control digest to one separate finite staging/authentication ledger.\ndef digest(raw):\n    global WORK\n    assert len(raw) <= 4194304 - WORK, \'NATIVE_CONTROL_HASH_WORK_BOUND\'\n    WORK += len(raw)\n    return hashlib.sha256(raw).hexdigest()\n\n\n# Reject duplicate object fields in all bounded protocol and receipt JSON.\ndef unique(entries):\n    assert len(entries) <= 256\n    result = {}\n    for name, item in entries:\n        assert type(name) is str and len(name.encode(\'utf-8\')) <= 4096 and name not in result\n        result[name] = item\n    return result\n\n\n# Refuse noninteger numeric values in this integer-and-string control protocol.\ndef invalid_number(text):\n    raise ValueError(\'NATIVE_CONTROL_NONINTEGER_NUMBER_\' + text)\n\n\n# Parse only complete bounded control objects without duplicate or nonfinite values.\ndef parse(raw):\n    assert len(raw) <= 65536\n    return json.loads(raw, object_pairs_hook=unique, parse_constant=invalid_number, parse_float=invalid_number)\n\n\n# Read one fixed ordinary file twice with complete physical and SHA bookends.\ndef read(path, pin=None):\n    global READ_CALLS\n    assert READ_CALLS < 1024 and path.resolve(strict=True) == path\n    READ_CALLS += 1\n    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)\n    try:\n        before = os.fstat(fd)\n        assert stat.S_ISREG(before.st_mode) and before.st_uid == 1000 and before.st_nlink == 1\n        assert 0 <= before.st_size <= 262144\n        raw = os.read(fd, 262145)\n        os.lseek(fd, 0, os.SEEK_SET)\n        assert os.read(fd, 262145) == raw and len(raw) == before.st_size\n        assert physical(before) == physical(os.fstat(fd)) == physical(os.lstat(path))\n        row = {\'bytes\': len(raw), \'sha256\': digest(raw), \'physical\': physical(before)}\n        if pin is not None:\n            assert all(row[name] == value for name, value in pin.items())\n        return raw, row\n    finally:\n        os.close(fd)\n\n\n# Persist an exclusive bounded stage file and verify the complete fsynced content.\ndef write(name, raw):\n    assert name in set(PINS) | {\'stage.json\'} and len(raw) <= 262144\n    expected = {\'bytes\': len(raw), \'sha256\': digest(raw)}\n    with (TOOLS / name).open(\'xb\') as output:\n        output.write(raw)\n        output.flush()\n        os.fsync(output.fileno())\n    observed, row = read(TOOLS / name, expected)\n    assert observed == raw\n    return row\n\n\n# Expand one exact single gzip member without concatenation, trailing data or cap relaxation.\ndef expand(name, item):\n    assert type(item) is dict and set(item) == {\'bytes\', \'sha256\', \'gzip_bytes\', \'gzip_sha256\', \'gzip_base64\'}\n    assert {key: item[key] for key in (\'bytes\', \'sha256\')} == PINS[name]\n    assert type(item[\'gzip_bytes\']) is int and 0 < item[\'gzip_bytes\'] <= 65536\n    assert type(item[\'gzip_base64\']) is str and len(item[\'gzip_base64\']) <= 65536\n    compressed = base64.b64decode(item[\'gzip_base64\'], validate=True)\n    assert len(compressed) == item[\'gzip_bytes\'] and digest(compressed) == item[\'gzip_sha256\']\n    inflater = zlib.decompressobj(31)\n    raw = inflater.decompress(compressed, item[\'bytes\'] + 1)\n    assert inflater.eof and not inflater.unused_data and not inflater.unconsumed_tail\n    assert len(raw) == item[\'bytes\'] <= 262144 and digest(raw) == item[\'sha256\']\n    return raw\n\n\n# Validate a complete historical headroom declaration without treating it as a reservation.\ndef check_resources(value):\n    assert type(value) is dict and set(value) == {\'MemAvailable_bytes\', \'scratch_available_bytes\', \'scratch_available_inodes\', \'headroom_is_reservation\'}\n    assert value[\'headroom_is_reservation\'] is False\n    for key, minimum in ((\'MemAvailable_bytes\', 2147483648), (\'scratch_available_bytes\', 33554432), (\'scratch_available_inodes\', 512)):\n        text = value[key]\n        assert type(text) is str and 0 < len(text) <= 32 and text.isascii() and text.isdecimal() and str(int(text)) == text and int(text) >= minimum\n\n\n# Observe bounded current host headroom without reading process environments or dependencies.\ndef resources():\n    fd = os.open(\'/proc/meminfo\', os.O_RDONLY | os.O_NOFOLLOW)\n    try:\n        raw = os.read(fd, 65537)\n        assert len(raw) <= 65536\n    finally:\n        os.close(fd)\n    matches = [line.split() for line in raw.decode(\'ascii\').splitlines() if line.split()[:1] == [\'MemAvailable:\']]\n    assert len(matches) == 1 and len(matches[0]) == 3 and matches[0][2] == \'kB\'\n    assert matches[0][1].isascii() and matches[0][1].isdecimal()\n    available = int(matches[0][1]) * 1024\n    space = os.statvfs(TOOLS.parent)\n    assert available >= 2147483648 and space.f_bavail * space.f_frsize >= 33554432 and space.f_favail >= 512\n    return {\'MemAvailable_bytes\': str(available), \'scratch_available_bytes\': str(space.f_bavail * space.f_frsize),\n        \'scratch_available_inodes\': str(space.f_favail), \'headroom_is_reservation\': False}\n\n\n# Bound the direct staging namespace before constructing its exact name set.\ndef staged_names():\n    result = set()\n    with os.scandir(TOOLS) as entries:\n        for entry in entries:\n            assert len(result) < 16 and len(entry.name.encode(\'utf-8\')) <= 256\n            result.add(entry.name)\n    return result\n\n\n# Authenticate only the new staged files and stage receipt, never historical page or target bodies.\ndef snapshot(staged, control_sha, packet_sha):\n    assert TOOLS.parent.resolve(strict=True) == TOOLS.parent and OUT.parent == TOOLS.parent\n    assert not os.path.lexists(OUT)\n    files, root_physical, stage_sha = {}, None, None\n    if not staged:\n        assert not os.path.lexists(TOOLS)\n    else:\n        assert TOOLS.resolve(strict=True) == TOOLS\n        root_before = TOOLS.stat(follow_symlinks=False)\n        assert stat.S_ISDIR(root_before.st_mode) and root_before.st_uid == 1000\n        assert staged_names() == set(PINS) | {\'stage.json\'}\n        for name, pin in PINS.items():\n            _, files[name] = read(TOOLS / name, pin)\n        raw, files[\'stage.json\'] = read(TOOLS / \'stage.json\')\n        stage = parse(raw)\n        assert set(stage) == {\'schema\', \'control_source_sha256\', \'base_packet_sha256\', \'source_pins\', \'files\',\n            \'root_physical\', \'prerequisite_sha256\', \'resources\', \'observed_at_ns\', \'reader_executed\', \'native_runtime_admission\'}\n        assert stage[\'schema\'] == \'native-origin-source-stage/1\' and stage[\'control_source_sha256\'] == control_sha\n        assert stage[\'base_packet_sha256\'] == packet_sha and stage[\'source_pins\'] == PINS\n        assert stage[\'files\'] == {name: files[name] for name in PINS}\n        assert stage[\'reader_executed\'] is False and stage[\'native_runtime_admission\'] is None\n        prior_sha = stage[\'prerequisite_sha256\']\n        assert type(prior_sha) is str and len(prior_sha) == 64 and set(prior_sha) <= set(\'0123456789abcdef\')\n        observed = stage[\'observed_at_ns\']\n        assert type(observed) is str and 0 < len(observed) <= 32 and observed.isascii() and observed.isdecimal() and str(int(observed)) == observed\n        assert int(observed) <= time.time_ns()\n        check_resources(stage[\'resources\'])\n        assert physical(root_before) == stage[\'root_physical\']\n        for name, pin in files.items():\n            read(TOOLS / name, pin)\n        assert staged_names() == set(PINS) | {\'stage.json\'}\n        assert physical(root_before) == physical(TOOLS.stat(follow_symlinks=False))\n        root_physical, stage_sha = physical(root_before), files[\'stage.json\'][\'sha256\']\n    return {\'tools_absent\': not staged, \'output_absent\': True, \'root_physical\': root_physical,\n        \'stage_sha256\': stage_sha, \'files\': files, \'resources\': resources()}\n\n\n# Bind an independently reviewed actual prerequisite and refuse stale or mismatched observations.\ndef prerequisite(raw, expected_sha, phase, state, control_sha, packet_sha):\n    assert raw and len(raw) <= 65536 and digest(raw) == expected_sha\n    value = parse(raw)\n    assert set(value) == {\'schema\', \'phase\', \'control_source_sha256\', \'base_packet_sha256\', \'source_pins\',\n        \'hostname\', \'uid\', \'python\', \'observed_at_ns\', \'state\', \'native_runtime_admission\', \'reader_executed\'}\n    assert value[\'schema\'] == \'native-origin-readonly-prerequisite/1\' and value[\'phase\'] == phase\n    assert value[\'control_source_sha256\'] == control_sha and value[\'base_packet_sha256\'] == packet_sha and value[\'source_pins\'] == PINS\n    assert value[\'hostname\'] == socket.gethostname() == \'animallya-spark1\' and type(value[\'uid\']) is int and value[\'uid\'] == 1000\n    assert value[\'python\'] == sys.version and value[\'reader_executed\'] is False and value[\'native_runtime_admission\'] is None\n    observed = value[\'observed_at_ns\']\n    assert type(observed) is str and observed.isascii() and observed.isdecimal() and str(int(observed)) == observed\n    assert 0 <= time.time_ns() - int(observed) <= 300000000000\n    assert set(value[\'state\']) == set(state)\n    assert all(value[\'state\'][key] == state[key] for key in state if key != \'resources\')\n    check_resources(value[\'state\'][\'resources\'])\n\n\n# Escape ordinary termination and wall deadlines before incomplete work can be called accepted.\ndef stop(number, frame):\n    raise KeyboardInterrupt(\'NATIVE_ORIGIN_CONTROL_SIGNAL_\' + str(number))\n\n\n# Stage or observe only through separate explicit routes after complete source and prerequisite binding.\ndef main(arguments):\n    assert len(arguments) == 3\n    phase, packet_sha, prerequisite_sha = arguments\n    assert phase in (\'before-stage\', \'stage\', \'before-observe\', \'observe\')\n    assert __debug__ and sys.platform == \'linux\' and os.getuid() == 1000 and socket.gethostname() == \'animallya-spark1\'\n    os.umask(0o077)\n    os.nice(10)\n    for limit, value in ((resource.RLIMIT_AS, 536870912), (resource.RLIMIT_CPU, 20), (resource.RLIMIT_FSIZE, 262144)):\n        resource.setrlimit(limit, (value, value))\n    for number in (signal.SIGALRM, signal.SIGINT, signal.SIGHUP, signal.SIGTERM):\n        signal.signal(number, stop)\n    signal.alarm(30)\n    wire = sys.stdin.buffer.read(65537)\n    assert len(wire) <= 65536\n    envelope = parse(wire)\n    assert set(envelope) == {\'base_packet_base64\', \'prerequisite_base64\'}\n    packet_raw = base64.b64decode(envelope[\'base_packet_base64\'], validate=True)\n    assert digest(packet_raw) == packet_sha\n    packet = parse(packet_raw)\n    assert set(packet) == {\'schema\', \'control_source_sha256\', \'files\'} and packet[\'schema\'] == \'native-origin-control-packet/1\'\n    assert type(packet[\'files\']) is dict and set(packet[\'files\']) == set(PINS)\n    control_sha = packet[\'control_source_sha256\']\n    assert type(control_sha) is str and len(control_sha) == 64 and set(control_sha) <= set(\'0123456789abcdef\')\n    payload = {name: expand(name, item) for name, item in packet[\'files\'].items()}\n    assert sum(map(len, payload.values())) == 95869\n    state = snapshot(phase in (\'before-observe\', \'observe\'), control_sha, packet_sha)\n    if phase.startswith(\'before-\'):\n        assert prerequisite_sha == \'NONE\' and envelope[\'prerequisite_base64\'] is None\n        proof = {\'schema\': \'native-origin-readonly-prerequisite/1\', \'phase\': phase,\n            \'control_source_sha256\': control_sha, \'base_packet_sha256\': packet_sha, \'source_pins\': PINS,\n            \'hostname\': socket.gethostname(), \'uid\': os.getuid(), \'python\': sys.version,\n            \'observed_at_ns\': str(time.time_ns()), \'state\': state, \'native_runtime_admission\': None, \'reader_executed\': False}\n    else:\n        prior = base64.b64decode(envelope[\'prerequisite_base64\'], validate=True)\n        prerequisite(prior, prerequisite_sha, \'before-stage\' if phase == \'stage\' else \'before-observe\', state, control_sha, packet_sha)\n        if phase == \'stage\':\n            dispatch_resources = resources()\n            TOOLS.mkdir(mode=0o700, exist_ok=False)\n            files = {name: write(name, body) for name, body in payload.items()}\n            proof = {\'schema\': \'native-origin-source-stage/1\', \'control_source_sha256\': control_sha,\n                \'base_packet_sha256\': packet_sha, \'source_pins\': PINS, \'files\': files,\n                \'root_physical\': None, \'prerequisite_sha256\': prerequisite_sha, \'resources\': dispatch_resources,\n                \'observed_at_ns\': str(time.time_ns()), \'reader_executed\': False, \'native_runtime_admission\': None}\n            fd = os.open(TOOLS / \'stage.json\', os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)\n            try:\n                info = os.fstat(fd)\n                assert info.st_size == 0 and info.st_nlink == 1 and info.st_uid == 1000 and stat.S_ISREG(info.st_mode)\n                proof[\'root_physical\'] = physical(TOOLS.stat(follow_symlinks=False))\n                body = (json.dumps(proof, sort_keys=True, separators=(\',\', \':\'), allow_nan=False) + \'\\n\').encode(\'ascii\')\n                assert len(body) <= 65536\n                assert physical(info) == physical(os.fstat(fd)) == physical(os.lstat(TOOLS / \'stage.json\'))\n                assert os.write(fd, body) == len(body)\n                os.fsync(fd)\n                held = physical(os.fstat(fd))\n                assert held == physical(os.lstat(TOOLS / \'stage.json\'))\n            finally:\n                os.close(fd)\n            observed, _ = read(TOOLS / \'stage.json\', {\'bytes\': len(body), \'sha256\': digest(body), \'physical\': held})\n            assert observed == body\n            snapshot(True, control_sha, packet_sha)\n            for directory in (TOOLS, TOOLS.parent):\n                descriptor = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)\n                try:\n                    os.fsync(descriptor)\n                finally:\n                    os.close(descriptor)\n        else:\n            assert phase == \'observe\'\n            source, _ = read(TOOLS / READER, PINS[READER])\n            assert source == payload[READER]\n            resources()\n            signal.alarm(0)\n            sys.argv = [str(TOOLS / READER), \'--observe-retained-native-json-v1\']\n            exec(compile(source, str(TOOLS / READER), \'exec\', dont_inherit=True),\n                {\'__name__\': \'__main__\', \'__file__\': str(TOOLS / READER)})\n            return\n    raw = (json.dumps(proof, sort_keys=True, separators=(\',\', \':\'), allow_nan=False) + \'\\n\').encode(\'ascii\')\n    assert len(raw) <= 65536\n    digest(raw)\n    print(raw.decode(\'ascii\'), end=\'\', flush=True)\n    signal.alarm(0)\n\n\nif __name__ == \'__main__\':\n    main(sys.argv[1:])\n'

PREPARATION = Path('/tmp/native-origin-control-preparation-20261018-v1')
PACKET_SHA = '3581a65f6bed8c5e5eaee081712502e7835820f6dbad71352b84c3ff17346151'
PACKET_BYTES = 30745
BOOTSTRAP_SHA = '70fb388a8cf1271a4eb0957a9071594490ef26318dc52ab9392b4572a6eacb67'
SOURCE_ROWS = {'observe-retained-native-json-v1-2026-10-18.py': {'bytes': 14395, 'sha256': 'b7f6ffb0b968c08caa0b6133c0d2aa20d75c54f87b0abc80326c28c9096a6e5b'}, 'origin-contract.json': {'bytes': 24905, 'sha256': '4a6ef7b722e4b4eb5e77df8de1be7b3fd2ca604d555985d8048409b5748180f5'}, 'native-proof.json': {'bytes': 46814, 'sha256': '1355771ff667f81e02dbe07885914dd5be8bf5cf395a3e74ef3bfdfd4988c6f7'}, 'native-inspect.json': {'bytes': 9755, 'sha256': 'd5265be87b979e83e396e18d1d9d4571cc6e1db5aa09239200004a2809bd90d2'}}
FIELDS = ('st_dev', 'st_ino', 'st_mode', 'st_uid', 'st_nlink', 'st_size', 'st_blocks', 'st_mtime_ns', 'st_ctime_ns')
LOCAL_INPUTS = {}

"""UNRUN transport source fragment; supplied constants exist only in the generated proposed transport."""


# Authenticate a bounded local packet or actual prerequisite with two held/named reads.
def local_read(path, pin, record=True):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        before = os.fstat(fd)
        assert stat.S_ISREG(before.st_mode) and before.st_uid == os.getuid() and before.st_nlink == 1 and 0 <= before.st_size <= 65536
        raw = os.read(fd, 65537)
        os.lseek(fd, 0, os.SEEK_SET)
        assert os.read(fd, 65537) == raw and len(raw) == before.st_size
        physical = {key: str(getattr(before, key)) for key in FIELDS}
        assert physical == {key: str(getattr(os.fstat(fd), key)) for key in FIELDS} == {key: str(getattr(os.lstat(path), key)) for key in FIELDS}
        row = {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(), 'physical': physical}
        assert all(row[key] == value for key, value in pin.items())
        if record:
            LOCAL_INPUTS[str(path)] = row
        return raw, row
    finally:
        os.close(fd)


# Build only a bounded wire from the frozen packet and an externally pinned actual prerequisite.
def prepare():
    assert hashlib.sha256(BOOTSTRAP.encode('utf-8')).hexdigest() == BOOTSTRAP_SHA
    raw, _ = local_read(PREPARATION / 'packet.json', {'bytes': PACKET_BYTES, 'sha256': PACKET_SHA})
    prior = None
    if sys.argv[1] in ('stage', 'observe'):
        expected = sys.argv[2]
        assert len(expected) == 64 and set(expected) <= set('0123456789abcdef')
        phase = 'before-stage' if sys.argv[1] == 'stage' else 'before-observe'
        path = Path('/tmp/native-origin-' + phase + '-transport-20261018-v1/stdout')
        prior, _ = local_read(path, {'sha256': expected})
        proof = json.loads(prior)
        assert proof['schema'] == 'native-origin-readonly-prerequisite/1' and proof['phase'] == phase
        assert proof['control_source_sha256'] == BOOTSTRAP_SHA and proof['base_packet_sha256'] == PACKET_SHA
        assert proof['source_pins'] == SOURCE_ROWS and proof['hostname'] == 'animallya-spark1' and type(proof['uid']) is int and proof['uid'] == 1000
        assert proof['reader_executed'] is False and proof['native_runtime_admission'] is None
        observed = proof['observed_at_ns']
        assert type(observed) is str and observed.isascii() and observed.isdecimal() and str(int(observed)) == observed
        assert 0 <= time.time_ns() - int(observed) <= 300000000000
    wire = json.dumps({'base_packet_base64': base64.b64encode(raw).decode('ascii'),
        'prerequisite_base64': None if prior is None else base64.b64encode(prior).decode('ascii')},
        sort_keys=True, separators=(',', ':'), allow_nan=False).encode('ascii') + b'\n'
    assert len(wire) <= 65536
    return wire


# Apply the existing finite SSH-log bound and remove the short parent registration signal mask.
def limits():
    resource.setrlimit(resource.RLIMIT_FSIZE, (262144, 262144))
    signal.pthread_sigmask(signal.SIG_UNBLOCK, {signal.SIGINT, signal.SIGTERM, signal.SIGHUP})


# Enter finite owned SSH cleanup when an ordinary signal interrupts the transport owner.
def interrupt(signum, frame):
    raise InterruptedError('SOURCE_TRANSPORT_INTERRUPTED')


# Dispatch one explicit phase after pinned local prerequisite checks without retries.
def main():
    assert __debug__ and len(sys.argv) in (2, 3) and sys.argv[1] in ('before-stage', 'stage', 'before-observe', 'observe')
    assert len(sys.argv) == (2 if sys.argv[1].startswith('before-') else 3)
    assert TRUSTED.read_bytes() == KEYS
    raw = prepare()
    LOCAL.mkdir(mode=0o700, exist_ok=False)
    with (LOCAL / 'wire.json').open('xb') as retained:
        retained.write(raw); retained.flush(); os.fsync(retained.fileno())
    _, wire_row = local_read(LOCAL / 'wire.json', {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}, record=False)
    command = ['ssh', '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=yes',
        '-o', 'HostKeyAlgorithms=ssh-ed25519', '-o', 'ConnectTimeout=10',
        '-o', 'ServerAliveInterval=10', '-o', 'ServerAliveCountMax=2',
        '-o', 'GlobalKnownHostsFile=/dev/null', '-o', 'UserKnownHostsFile=' + str(TRUSTED),
        'animallya96@172.16.8.3', shlex.join(['python3', '-I', '-S', '-B', '-c', BOOTSTRAP, sys.argv[1], PACKET_SHA, 'NONE' if len(sys.argv) == 2 else sys.argv[2]])]
    watched = {signal.SIGINT, signal.SIGTERM, signal.SIGHUP}
    previous = {signum: signal.signal(signum, interrupt) for signum in watched}
    process, stopped, failure = None, None, None
    stdout, stderr = (LOCAL / 'stdout').open('xb'), (LOCAL / 'stderr').open('xb')
    try:
        blocked = signal.pthread_sigmask(signal.SIG_BLOCK, watched)
        try:
            process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=stdout,
                stderr=stderr, preexec_fn=limits, start_new_session=True)
        finally:
            signal.pthread_sigmask(signal.SIG_SETMASK, blocked)
        process.communicate(input=raw, timeout=70)
    except BaseException as exc:
        failure = type(exc).__name__
        raise
    finally:
        blocked = signal.pthread_sigmask(signal.SIG_BLOCK, watched)
        cleanup_failure = None
        try:
            try:
                if process is not None and process.poll() is None:
                    stopped = 'TERM'
                    try:
                        os.killpg(process.pid, signal.SIGTERM)
                    except ProcessLookupError:
                        pass
                    try:
                        process.wait(timeout=1)
                    except subprocess.TimeoutExpired:
                        stopped = 'KILL'
                        try:
                            os.killpg(process.pid, signal.SIGKILL)
                        except ProcessLookupError:
                            pass
                        process.wait(timeout=1)
            except BaseException as exc:
                cleanup_failure = type(exc).__name__
                raise
            finally:
                if process is not None and process.stdin is not None:
                    process.stdin.close()
                for stream in (stdout, stderr):
                    stream.flush()
                    os.fsync(stream.fileno())
                    stream.close()
                receipt = {'pid': None if process is None else str(process.pid),
                    'exit': None if process is None else process.returncode, 'owned_SSH_group_stop': stopped,
                    'failure_class': failure, 'cleanup_failure_class': cleanup_failure,
                    'source_sha256': PINS, 'command': command,
                    'input_wire': wire_row, 'base_packet_sha256': PACKET_SHA,
                    'control_source_sha256': BOOTSTRAP_SHA, 'local_input_inventory': LOCAL_INPUTS,
                    'remote_quiescence_inferred_from_SSH_exit': False}
                body = json.dumps(receipt, sort_keys=True, indent=2).encode() + b'\n'
                assert len(body) <= 262144
                with (LOCAL / 'exit.json').open('xb') as stream:
                    stream.write(body); stream.flush(); os.fsync(stream.fileno())
                for directory in (LOCAL, LOCAL.resolve().parent):
                    descriptor = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
                    os.fsync(descriptor); os.close(descriptor)
        finally:
            for signum, handler in previous.items():
                signal.signal(signum, handler)
            signal.pthread_sigmask(signal.SIG_SETMASK, blocked)
    assert process.returncode == 0 and stopped is None and (LOCAL / 'stderr').stat().st_size == 0
    print((LOCAL / 'stdout').read_text(), end='')


if __name__ == '__main__':
    main()
