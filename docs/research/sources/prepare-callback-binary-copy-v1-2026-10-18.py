"""Build distinct single-path binary controls; never dispatch or import native bytes."""
import ast
import hashlib
import json
from pathlib import Path
import sys

SOURCES = Path(__file__).resolve().parent
RESEARCH = SOURCES.parent


# Retrieve an exact operational source without importing or executing it.
def source(name, sha):
    raw = (SOURCES / name).read_bytes()
    assert hashlib.sha256(raw).hexdigest() == sha
    return raw.decode()


# Copy a top-level operational function and its immediately preceding purpose comment.
def function(text, name):
    node, = [n for n in ast.parse(text).body if isinstance(n, ast.FunctionDef) and n.name == name]
    return '\n'.join(text.splitlines()[node.lineno - 2:node.end_lineno])


# Save an exclusive parseable control and return its complete source pin.
def write(name, text):
    raw = text.encode()
    ast.parse(raw)
    with (SOURCES / name).open('xb') as stream:
        stream.write(raw)
    assert (SOURCES / name).read_bytes() == raw
    return hashlib.sha256(raw).hexdigest(), len(raw)


# Select only the exact below-cap binary reference from independently authenticated HEAD data.
def declaration():
    raw = (RESEARCH / 'original-loader-native-path-head-independent-v1-2026-10-18.json').read_bytes()
    assert hashlib.sha256(raw).hexdigest() == '6f3696b006cb335a06656501446d2976723ec4649117dd33a31cd03c825adaaa'
    head = json.loads(raw)
    row, = [r for r in head['path_observations'] if r['path_metadata']['stat']['size'] <= 262144]
    assert row['path_metadata']['stat']['size'] == 216280 and row['path_metadata']['stat']['linkTarget'] == ''
    assert row['declaration']['declared_size_decimal'] == '216280'
    assert row['declaration']['declared_hash']['algorithm'] == 'sha256'
    seam = (RESEARCH / 'original-loader-package-metadata-record-seams-v1-2026-10-18.json').read_bytes()
    assert hashlib.sha256(seam).hexdigest() == '15f8249875d0aef99b9f48d0e3eb9c1971cf85d23fefc09d27d9ed7538325128'
    assert row['declaration'] in json.loads(seam)['native_filename_declarations']['selected_candidates']
    return row['declaration']


# Pin a new one-shot SSH transport to generated binary-control bytes only.
def transport(role, name, sha, size):
    text = source('capacity-native-package-text-transport-v1-2026-10-18.py',
        '518ded7394ae1b04db85f32b89e15693086f8e184c231ac2b891391d2f749b08')
    changes = {
        'capacity-native-package-text-census-v1-2026-10-18.py': name,
        '296d0e8dd4d58883388a5c8f5b2d5c0b6d09ccfdbf82cb44c060333637bb1428': sha,
        '13080': str(size),
        'capacity-native-package-text-transport-20261018-v1': 'capacity-callback-binary-' + role + '-transport-20261018-v1',
        'capacity-native-package-text-census-tools-20261018-v1': 'capacity-callback-binary-' + role + '-tools-20261018-v1',
        'collect-new-native-package-texts': 'collect-one-callback-binary' if role == 'primary' else 'verify-one-callback-binary',
    }
    if role == 'independent':
        changes['timeout=120'] = 'timeout=70'
    for old, new in changes.items():
        assert old in text
        text = text.replace(old, new)
    return write('callback-binary-' + role + '-transport-v1-2026-10-18.py', text)


# Generate distinct binary-only source from reviewed transport/file controls and new exact bindings.
def main(arguments):
    assert arguments == ['primary'] or (len(arguments) == 2 and arguments[0] == 'independent'
        and len(arguments[1]) == 64 and all(c in '0123456789abcdef' for c in arguments[1]))
    role = arguments[0]
    collector = source('capacity-package-metadata-text-census-v2-2026-10-18.py',
        'd9cadb938ca5d78d722c4b1974a778130962f4d84d69fcfac43d5f7eaa32960c')
    verifier = source('verify-package-metadata-text-census-v2-2026-10-18.py',
        '4ad058e882c789d4fc9aa7d85d0005775c0cd770c32ca1dc3164d9d4067b6cec')
    reference = declaration()
    prefix = '''"""Copy or verify exactly one binary as inert bytes; no package or ELF execution."""
import hashlib
import io
import json
import os
from pathlib import Path
import resource
import selectors
import signal
import socket
import stat
import subprocess
import sys
import tarfile
import time

CID = '803718a62e3cbd1f6070abab25a58e1fbc0ee5d04b5444f57c817d7e47b8bf57'
IMAGE = 'sha256:e0a54c1f3b293c241ea0eae767d8ba017d0e1a05679965935b336910faa63237'
BASELINE = 'd5265be87b979e83e396e18d1d9d4571cc6e1db5aa09239200004a2809bd90d2'
BASELINE_INSPECT = Path('/home/animallya96/scratch/capacity-package-metadata-head-20261018-v1/inspect-before.stdout')
PRIOR = Path('/home/animallya96/scratch/capacity-native-path-head-independent-20261018-v1/proof.json')
HEAD_SHA = '6f3696b006cb335a06656501446d2976723ec4649117dd33a31cd03c825adaaa'
ROOT = Path('/home/animallya96/scratch/capacity-callback-binary-copy-20261018-v1')
REVIEW = Path('/home/animallya96/scratch/capacity-callback-binary-independent-20261018-v1')
DOCKER = ('docker', '--host', 'unix:///var/run/docker.sock')
CAP = 262144
'''
    prefix += 'DECLARATION = ' + repr(reference) + '\n'
    prefix += "PATHS = (DECLARATION['lexical_absolute_path'],)\nSIZES = (216280,)\nBINARY_SHA = DECLARATION['declared_hash']['digest_hex']\n"
    if role == 'independent':
        prefix += 'CANDIDATE_SHA = ' + repr(arguments[1]) + '\n'
    control = collector if role == 'primary' else verifier
    parts = [function(control, n) for n in ('digest', 'save', 'save_json', 'alarm', 'client_limits', 'command',
        'physical', 'read', 'inspection')]
    if role == 'primary':
        parts.append(function(collector, 'inspect_source'))
        parts.append(r'''
# Validate one plain regular tar member and retain exact binary bytes without filesystem extraction.
def binary_member(raw):
    assert 1024 <= len(raw) <= CAP and len(raw) % 512 == 0
    with tarfile.open(fileobj=io.BytesIO(raw), mode='r:') as archive:
        members = archive.getmembers()
        assert len(members) == 1
        member = members[0]
        assert member.name == Path(PATHS[0]).name
        assert member.type in (tarfile.REGTYPE, tarfile.AREGTYPE) and member.sparse is None and not member.linkname
        assert not any(key.startswith('GNU.sparse.') for key in member.pax_headers)
        assert member.size == 216280 <= CAP
        with archive.extractfile(member) as stream:
            body = stream.read(CAP + 1)
        assert len(body) == 216280 and digest(body) == BINARY_SHA
        end = member.offset_data + ((member.size + 511) // 512) * 512
        assert end + 1024 <= len(raw) and not any(raw[end:])
        metadata = {'member': member.name, 'size': member.size, 'mode': member.mode,
            'uid': member.uid, 'gid': member.gid, 'pax_headers': member.pax_headers,
            'mtime_representation': repr(member.mtime),
            'identity_scope': 'ARCHIVE_METADATA_NOT_CONTAINER_SOURCE_HELD_FD_OR_IMAGE_ATTESTATION'}
    return body, metadata


# Copy the sole bounded binary twice between complete stopped-container inspection bookends.
def main(arguments):
    assert arguments == ['collect-one-callback-binary'] and __debug__
    assert os.getuid() == 1000 and socket.gethostname() == 'animallya-spark1'
    assert signal.pthread_sigmask(signal.SIG_BLOCK, set()) == set()
    os.umask(0o077); os.nice(10)
    resource.setrlimit(resource.RLIMIT_AS, (536870912, 4294967296))
    resource.setrlimit(resource.RLIMIT_CPU, (30, 30))
    resource.setrlimit(resource.RLIMIT_FSIZE, (CAP, CAP))
    assert ROOT.parent.resolve(strict=True) == ROOT.parent
    space = os.statvfs(ROOT.parent)
    assert space.f_bavail * space.f_frsize >= 1073741824 and space.f_favail >= 512
    memory_raw = Path('/proc/meminfo').read_bytes()
    assert len(memory_raw) <= CAP
    available_fields, = [line.split()[1:] for line in memory_raw.splitlines() if line.startswith(b'MemAvailable:')]
    assert available_fields[1:] == [b'kB']
    available = int(available_fields[0]) * 1024
    assert available >= 2147483648
    ROOT.mkdir(mode=0o700, exist_ok=False)
    previous = {s: signal.signal(s, alarm) for s in (signal.SIGALRM, signal.SIGHUP, signal.SIGINT, signal.SIGTERM)}
    signal.alarm(95)
    try:
        deadline = time.monotonic() + 90
        save_json('prerequisites.json', {'hostname': socket.gethostname(), 'uid': os.getuid(),
            'MemAvailable_bytes': str(available), 'scratch_available_bytes': str(space.f_bavail * space.f_frsize),
            'scratch_available_inodes': str(space.f_favail), 'reservation': False})
        prior_raw, prior_row = read(PRIOR)
        assert digest(prior_raw) == HEAD_SHA and len(prior_raw) == 86271
        prior = json.loads(prior_raw)
        selected, = [r for r in prior['path_observations'] if r['container_path'] == PATHS[0]]
        assert selected['declaration'] == DECLARATION and selected['path_metadata']['http_status'] == 200
        assert selected['path_metadata']['stat']['size'] == 216280 and selected['path_metadata']['stat']['linkTarget'] == ''
        assert prior['status'] == 'VERIFIED_RETAINED_PAIRED_DAEMON_PATH_METADATA_ONLY'
        saved_prior = save('prior-head-proof.json', prior_raw)
        baseline_raw, baseline_row = read(BASELINE_INSPECT)
        assert digest(baseline_raw) == BASELINE and len(baseline_raw) == 9755
        saved_baseline = save('baseline-inspect.json', baseline_raw)
        before_raw = command('inspect-before', ('container', 'inspect', CID), deadline)
        before = inspection(before_raw, baseline_raw)
        bodies, reads = [], []
        for turn in range(2):
            wire = command('binary-read-%d' % turn, ('container', 'cp', CID + ':' + PATHS[0], '-'), deadline)
            body, metadata = binary_member(wire)
            bodies.append(body)
            reads.append({'wire_sha256': digest(wire), 'wire_bytes': len(wire), 'archive': metadata})
        assert bodies[0] == bodies[1]
        retained = save('callback.bin', bodies[0])
        after_raw = command('inspect-after', ('container', 'inspect', CID), deadline)
        after = inspection(after_raw, baseline_raw)
        assert read(PRIOR) == (prior_raw, prior_row) and read(BASELINE_INSPECT) == (baseline_raw, baseline_row)
        pointer = save_json('candidate.json', {'schema': 'stopped-n2-callback-binary-copy/1',
            'status': 'PAIRED_BINARY_BYTES_REQUIRE_INDEPENDENT_REVIEW', 'container': CID, 'image': IMAGE,
            'declaration': DECLARATION, 'retained': retained, 'reads': reads,
            'prior_head_proof': saved_prior, 'prior_head_physical': prior_row,
            'inspection_binding': {'baseline': saved_baseline, 'baseline_physical': baseline_row,
                'before': before, 'after': after, 'raw_before_after_equal': before_raw == after_raw},
            'binary_interpretation_import_or_execution': False, 'native_runtime_or_model_RAM_admission': None})
        print(json.dumps(pointer, sort_keys=True), flush=True)
    finally:
        signal.alarm(0)
        for s, handler in previous.items():
            signal.signal(s, handler)
''')
        name = 'capacity-callback-binary-copy-v1-2026-10-18.py'
    else:
        parts.append(r'''
# Independently validate all retained binary bytes, tar members, terminals and complete stopped state.
def main(arguments):
    assert arguments == ['verify-one-callback-binary'] and __debug__ and os.getuid() == 1000
    assert signal.pthread_sigmask(signal.SIG_BLOCK, set()) == set()
    os.umask(0o077); os.nice(10)
    resource.setrlimit(resource.RLIMIT_AS, (536870912, 4294967296))
    resource.setrlimit(resource.RLIMIT_CPU, (20, 20))
    resource.setrlimit(resource.RLIMIT_FSIZE, (CAP, CAP))
    assert ROOT.resolve(strict=True) == ROOT and REVIEW.parent.resolve(strict=True) == REVIEW.parent
    previous = {s: signal.signal(s, alarm) for s in (signal.SIGALRM, signal.SIGHUP, signal.SIGINT, signal.SIGTERM)}
    signal.alarm(30)
    try:
        REVIEW.mkdir(mode=0o700, exist_ok=False)
        first, first_row = read(ROOT / 'candidate.json')
        assert digest(first) == CANDIDATE_SHA
        candidate = json.loads(first)
        assert candidate['schema'] == 'stopped-n2-callback-binary-copy/1'
        assert candidate['status'] == 'PAIRED_BINARY_BYTES_REQUIRE_INDEPENDENT_REVIEW'
        assert candidate['container'] == CID and candidate['image'] == IMAGE
        assert candidate['declaration'] == DECLARATION
        assert candidate['binary_interpretation_import_or_execution'] is False
        assert candidate['native_runtime_or_model_RAM_admission'] is None
        commands = [('inspect-before', ['container', 'inspect', CID]), ('inspect-after', ['container', 'inspect', CID])]
        commands += [('binary-read-%d' % i, ['container', 'cp', CID + ':' + PATHS[0], '-']) for i in range(2)]
        names = {'candidate.json', 'prerequisites.json', 'prior-head-proof.json', 'baseline-inspect.json', 'callback.bin'}
        for label, argv in commands:
            names.update(label + suffix for suffix in ('.stdout', '.stderr', '.exit.json'))
        assert len(names) == 17 and {p.name for p in ROOT.iterdir()} == names
        bodies, inventory = {}, {}
        for n in sorted(names):
            bodies[n], inventory[n] = read(ROOT / n)
        assert bodies['candidate.json'] == first and inventory['candidate.json'] == first_row
        for label, argv in commands:
            terminal = json.loads(bodies[label + '.exit.json'])
            assert terminal['arguments'] == list(DOCKER) + argv
            assert terminal['exit'] == 0 and terminal['owned_CLI_group_stop'] is None
            assert terminal['failure_class'] is None and terminal['cleanup_failure_class'] is None
            assert terminal['overflow_first_extra_byte_hex'] == {} and bodies[label + '.stderr'] == b''
            for channel in ('stdout', 'stderr'):
                value = inventory[label + '.' + channel]
                assert terminal['outputs'][channel] == {'file': label + '.' + channel, 'bytes': value['bytes'], 'sha256': value['sha256']}
        binary = bodies['callback.bin']
        assert len(binary) == 216280 and digest(binary) == BINARY_SHA
        assert candidate['retained'] == {'file': 'callback.bin', 'bytes': 216280, 'sha256': BINARY_SHA}
        assert len(candidate['reads']) == 2
        for i in range(2):
            wire, observed = bodies['binary-read-%d.stdout' % i], candidate['reads'][i]
            assert 1024 <= len(wire) <= CAP and len(wire) % 512 == 0
            assert observed['wire_sha256'] == digest(wire) and observed['wire_bytes'] == len(wire)
            with tarfile.open(fileobj=io.BytesIO(wire), mode='r:') as archive:
                members = archive.getmembers()
                assert len(members) == 1
                member = members[0]
                assert member.name == PATHS[0].rsplit('/', 1)[1] and member.type in (b'0', b'\0')
                assert member.size == 216280 and member.linkname == '' and member.sparse is None
                assert all(not key.startswith('GNU.sparse.') for key in member.pax_headers)
                with archive.extractfile(member) as stream:
                    assert stream.read(CAP + 1) == binary
                end = member.offset_data + ((216280 + 511) // 512) * 512
                assert end + 1024 <= len(wire) and not any(wire[end:])
                assert observed['archive'] == {'member': member.name, 'size': member.size,
                    'mode': member.mode, 'uid': member.uid, 'gid': member.gid,
                    'pax_headers': member.pax_headers, 'mtime_representation': repr(member.mtime),
                    'identity_scope': 'ARCHIVE_METADATA_NOT_CONTAINER_SOURCE_HELD_FD_OR_IMAGE_ATTESTATION'}
        prior_raw, prior_row = read(PRIOR)
        baseline_raw, baseline_row = read(BASELINE_INSPECT)
        assert digest(prior_raw) == HEAD_SHA and len(prior_raw) == 86271 and bodies['prior-head-proof.json'] == prior_raw
        assert digest(baseline_raw) == BASELINE and len(baseline_raw) == 9755 and bodies['baseline-inspect.json'] == baseline_raw
        assert candidate['prior_head_proof'] == {'file': 'prior-head-proof.json', 'bytes': 86271, 'sha256': HEAD_SHA}
        assert candidate['prior_head_physical'] == prior_row
        selected, = [r for r in json.loads(prior_raw)['path_observations'] if r['container_path'] == PATHS[0]]
        assert selected['declaration'] == DECLARATION and selected['path_metadata']['stat']['size'] == 216280
        binding = candidate['inspection_binding']
        assert binding['baseline'] == {'file': 'baseline-inspect.json', 'bytes': 9755, 'sha256': BASELINE}
        assert binding['baseline_physical'] == baseline_row
        assert binding['before'] == inspection(bodies['inspect-before.stdout'], baseline_raw)
        assert binding['after'] == inspection(bodies['inspect-after.stdout'], baseline_raw)
        assert binding['raw_before_after_equal'] == (bodies['inspect-before.stdout'] == bodies['inspect-after.stdout'])
        prerequisites = json.loads(bodies['prerequisites.json'])
        assert prerequisites['hostname'] == 'animallya-spark1' and prerequisites['uid'] == 1000
        assert prerequisites['reservation'] is False and int(prerequisites['MemAvailable_bytes']) >= 2147483648
        assert int(prerequisites['scratch_available_bytes']) >= 1073741824 and int(prerequisites['scratch_available_inodes']) >= 512
        fresh = command('inspect-fresh', ('container', 'inspect', CID), time.monotonic() + 5)
        fresh_binding = inspection(fresh, baseline_raw)
        for n in sorted(names):
            assert read(ROOT / n) == (bodies[n], inventory[n])
        assert read(PRIOR) == (prior_raw, prior_row) and read(BASELINE_INSPECT) == (baseline_raw, baseline_row)
        saved = save_json('proof.json', {'schema': 'stopped-n2-callback-binary-independent/1',
            'status': 'VERIFIED_ONE_BINARY_BYTE_COPY_RECORD_SHA_ONLY_NOT_ELF_OR_RUNTIME',
            'candidate_sha256': CANDIDATE_SHA, 'declaration': DECLARATION, 'source_bytes': 216280,
            'full_readback_files': 17, 'source_inventory': inventory, 'prior_head_physical': prior_row,
            'original_baseline_physical': baseline_row, 'inspection_binding': binding, 'fresh_inspection_binding': fresh_binding,
            'binary_hash_matches_RECORD': True, 'archive_wire_bytes': [len(bodies['binary-read-%d.stdout' % i]) for i in range(2)],
            'ELF_parse_import_native_load_or_body_execution': False, 'native_model_RAM_admission': None,
            'container_source_held_FD_or_every_file_image_attestation': False})
        raw = read(REVIEW / 'proof.json')[0]
        assert digest(raw) == saved['sha256']
        print(raw.decode(), end='')
    finally:
        signal.alarm(0)
        for s, handler in previous.items():
            signal.signal(s, handler)
''')
        name = 'verify-callback-binary-copy-v1-2026-10-18.py'
    text = prefix + '\n\n\n'.join([''] + parts) + "\n\nif __name__ == '__main__':\n    main(sys.argv[1:])\n"
    sha, size = write(name, text)
    tsha, tsize = transport(role, name, sha, size)
    print(json.dumps({'role': role, 'helper': name, 'sha256': sha, 'bytes': size,
        'transport_sha256': tsha, 'transport_bytes': tsize}, sort_keys=True))


if __name__ == '__main__':
    main(sys.argv[1:])
