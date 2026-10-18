"""Fresh read-only source/image/resources/native folds; never invoke synthetic73 bodies."""
import hashlib
import json
import os
import signal
import socket
import stat
import subprocess
import sys
import time
import types
from pathlib import Path

BASE = Path('/home/animallya96/scratch')
SOURCE = BASE / 'capacity-context-parity-source-20261018-v1'
TOOLS = BASE / 'capacity-context-parity-tools-source-20261018-v1'
TRANSFER = BASE / 'capacity-context-parity-transfer-20261018-v1'
PRE = BASE / 'capacity-context-parity-prerequisites-20261018-v1'
RUN = BASE / 'capacity-context-parity-20261018-v1'
NATIVE = BASE / 'capacity-context-native-probe-20261018-v1'
NATIVE_REVIEW = BASE / 'capacity-context-native-probe-review-20261018-v1'
BOOK = '371af1dfa4fb82fea78888044cb7165c266bf50f16fc17752c52ebf363224f33'
IMAGE = 'sha256:e0a54c1f3b293c241ea0eae767d8ba017d0e1a05679965935b336910faa63237'
QUERY = '8d3f17d41e5b13b98e697138facadb3f00fe68e5822130fc9d4ad2b5929acc38'


# Preserve exact named and held physical identities with decimal nanosecond fields.
def physical(value):
    return {key: str(getattr(value, key)) for key in ('st_dev', 'st_ino', 'st_mode', 'st_uid', 'st_nlink', 'st_size', 'st_blocks', 'st_mtime_ns', 'st_ctime_ns')}


# Authenticate one bounded source or metadata file without importing its payload.
def read(path, expected=None):
    assert path.resolve(strict=True) == path
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        before = os.fstat(descriptor)
        assert stat.S_ISREG(before.st_mode) and before.st_uid == 1000 and before.st_nlink == 1 and 0 <= before.st_size <= 262144
        raw = os.read(descriptor, 262145)
        item = {'sha256': hashlib.sha256(raw).hexdigest(), 'bytes': len(raw), 'physical': physical(before)}
        assert len(raw) == before.st_size and physical(before) == physical(os.fstat(descriptor)) == physical(path.stat(follow_symlinks=False))
        if expected is not None:
            assert item['sha256'] == expected
        return raw, item
    finally:
        os.close(descriptor)


# Persist only a new bounded independent observation with exact fsynced readback.
def save(path, value):
    raw = json.dumps(value, sort_keys=True, indent=2, allow_nan=False).encode() + b'\n'
    assert len(raw) <= 262144
    with path.open('xb') as output:
        output.write(raw)
        output.flush()
        os.fsync(output.fileno())
    assert read(path)[0] == raw
    descriptor = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    return hashlib.sha256(raw).hexdigest()


# Bind only an exact utility module without dispatching its old or new main route.
def library(path, expected):
    raw = read(path, expected)[0]
    module = types.ModuleType('context_metadata_utility_' + path.stem)
    module.__file__ = str(path)
    exec(compile(raw, str(path), 'exec', dont_inherit=True), module.__dict__)
    return module


# Rehash every staged packet/tool source and retain complete full physical bookends.
def source_fold(tools_sha):
    result = {}
    for root, pin, label in ((SOURCE, BOOK, 'source'), (TOOLS, tools_sha, 'tools')):
        book_raw, book_item = read(root / 'source-book.json', pin)
        book = json.loads(book_raw)
        assert 1 <= len(book['files']) <= 128
        result[label + '/source-book.json'] = book_item
        for name, expected in book['files'].items():
            assert not Path(name).is_absolute() and '..' not in Path(name).parts and str(Path(name)) == name
            raw, item = read(root / name)
            assert expected == {key: item[key] for key in ('sha256', 'bytes')}
            result[label + '/' + name] = item
        if label == 'source':
            assert len(book['files']) == 83 and book['schema'] == 'capacity-context-parity-source/1'
            assert {str(p.relative_to(root)) for p in (root / 'audit').rglob('*') if p.is_file()} == {n for n in book['files'] if n.startswith('audit/')}
        else:
            assert book['schema'] == 'capacity-context-parity-tools/1'
            assert {str(p.relative_to(root)) for p in root.rglob('*') if not p.is_dir()} == set(book['files']) | {'source-book.json'}
    return result


# Read new image/jobs/headroom immediately before a separate metadata or parity admission.
def fresh(root, target):
    root.mkdir(mode=0o700, exist_ok=False)
    query = library(TOOLS / 'query-library.py', QUERY)
    code, jobs, error = query.query(root, 'jobs', ['ps', '--filter', 'label=anios.synthetic.guard-owner', '--format', '{{json .}}'])
    assert code == 0 and jobs == error == b''
    code, raw, error = query.query(root, 'image', ['image', 'inspect', IMAGE])
    image = json.loads(raw)
    assert code == 0 and not error and len(image) == 1 and image[0]['Id'] == IMAGE and image[0]['Os'] == 'linux' and image[0]['Architecture'] == 'arm64'
    memory = dict(line.split(':', 1) for line in Path('/proc/meminfo').read_text().splitlines())
    disk = os.statvfs(BASE)
    host = {'host': socket.gethostname(), 'uid': os.getuid(), 'observed_at_ns': str(time.time_ns()), 'jobs_empty': True,
        'MemAvailable_bytes': str(int(memory['MemAvailable'].split()[0]) * 1024), 'scratch_available_bytes': str(disk.f_bavail * disk.f_frsize),
        'scratch_inodes_available': str(disk.f_favail), 'run_target_lexists': os.path.lexists(target), 'reservation': False}
    assert host['host'] == 'animallya-spark1' and host['uid'] == 1000 and host['run_target_lexists'] is False
    assert int(host['MemAvailable_bytes']) >= 5 * 1024**3 and int(host['scratch_available_bytes']) >= 4 * 1024**3 and int(host['scratch_inodes_available']) >= 8192
    evidence = [{'path': str(root / 'host-resources.json'), 'sha256': save(root / 'host-resources.json', host)},
                {'path': str(root / 'runtime-image.json'), 'sha256': save(root / 'runtime-image.json', image)}]
    return host, evidence


# Check all independent prerequisite source and actual host observations without creating any runtime.
def prerequisites(tools_sha):
    before = source_fold(tools_sha)
    host, evidence = fresh(PRE, RUN)
    targets = [NATIVE, NATIVE_REVIEW, SOURCE / 'admission', BASE / 'capacity-context-parity-independent-review-20261018-v1',
        BASE / 'capacity-context-parity-evidence-20261018-v1', BASE / 'capacity-context-parity-evidence-review-20261018-v1']
    absent = {str(path): os.path.lexists(path) for path in targets}
    assert not any(absent.values()) and source_fold(tools_sha) == before
    proof = {'schema': 'capacity-context-prerequisites/1', 'status': 'VERIFIED_SOURCE_IMAGE_HOST_ONLY_ALL73_AND_NATIVE_UNRUN',
        'source_physical': before, 'resources': host, 'evidence': evidence, 'absent_targets': absent,
        'source_book_sha256': BOOK, 'tools_book_sha256': tools_sha, 'runtime_created': False, 'genuine_admission': False}
    pin = save(PRE / 'proof.json', proof)
    print(json.dumps({'proof_sha256': pin, 'resources': host, 'files_checked': len(before)}, sort_keys=True))


# Independently inspect only the exact stopped native metadata container and preserve raw full records.
def inspect_native(cid):
    stdout, stderr = NATIVE_REVIEW / 'fresh-inspect.json', NATIVE_REVIEW / 'fresh-inspect.stderr'
    environment = dict(os.environ)
    for key in ('DOCKER_HOST', 'DOCKER_CONTEXT', 'DOCKER_TLS_VERIFY', 'DOCKER_CERT_PATH'):
        environment.pop(key, None)
    with stdout.open('xb') as out, stderr.open('xb') as err:
        process = subprocess.Popen(['/usr/bin/docker', '--host', 'unix:///var/run/docker.sock', 'inspect', '--type=container', cid],
            stdin=subprocess.DEVNULL, stdout=out, stderr=err, env=environment)
        try:
            code = process.wait(timeout=10)
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=1)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=1)
        out.flush()
        err.flush()
        os.fsync(out.fileno())
        os.fsync(err.fileno())
    assert code == 0 and read(stderr)[0] == b''
    rows = json.loads(read(stdout)[0])
    assert len(rows) == 1 and rows[0]['Id'] == cid
    return rows[0], read(stdout)[1]['sha256']


# Fold native facts separately from the still-unrun synthetic73 suite, with fresh exact runtime/source bookends.
def native_fold(tools_sha):
    NATIVE_REVIEW.mkdir(mode=0o700, exist_ok=False)
    before = source_fold(tools_sha)
    terminal = json.loads(read(NATIVE / 'terminal.json')[0])
    assert terminal['status'] == 'CONTEXT_NUMPY_METADATA_ONLY_NOT_PARITY_ACCEPTANCE'
    created = json.loads(read(NATIVE / 'prepare-before.json')[0])
    stopped = json.loads(read(NATIVE / 'prepare-after.json')[0])
    row, inspect_sha = inspect_native(terminal['cid'])
    probe_raw, probe = read(TOOLS / 'native-audit/bootstrap.py')
    assert terminal['review_sha256'] == hashlib.sha256(b'CONTEXT73_NATIVE_METADATA_ONLY\0' + probe_raw).hexdigest()
    label = hashlib.sha256((str(NATIVE) + ':' + terminal['review_sha256']).encode()).hexdigest()
    for observation in (created, stopped, row):
        host, config = observation['HostConfig'], observation['Config']
        assert observation['Id'] == terminal['cid'] and observation['Image'] == IMAGE
        assert observation['Name'] == '/n2-guard-' + label[:20] + '-prepare' and config['Labels']['anios.synthetic.guard-owner'] == label
        assert config['Entrypoint'] == ['python'] and config['Cmd'] == ['-I', '-S', '-B', '/audit/bootstrap.py', 'diagnose']
        assert config['User'] == '1000:1000' and host['NetworkMode'] == 'none' and host['ReadonlyRootfs'] is True
        assert host['Memory'] == host['MemorySwap'] == 2147483648 and host['NanoCpus'] == 1000000000 and host['PidsLimit'] == 32
        assert host['Tmpfs'] == {'/tmp': 'rw,size=64m'} and host['LogConfig']['Type'] == 'none' and config['Healthcheck']['Test'] == ['NONE']
        assert host['CapDrop'] == ['ALL'] and not host['CapAdd'] and not host['Devices'] and not host['Privileged'] and 'no-new-privileges:true' in host['SecurityOpt']
        mounts = observation['Mounts']
        assert len(mounts) == len({m['Destination'] for m in mounts}) == 2
        assert {(m['Source'], m['Destination'], m['RW'], m['Type']) for m in mounts} == {
            (str(TOOLS / 'native-audit'), '/audit', False, 'bind'), (str(NATIVE / 'output'), '/out', True, 'bind')}
    assert created['State']['Status'] == 'created' and stopped['State'] == row['State']
    assert row['State']['Running'] is False and row['State']['ExitCode'] == 0 and row['State']['OOMKilled'] is False
    assert {k: v for k, v in stopped.items() if k != 'Mounts'} == {k: v for k, v in row.items() if k != 'Mounts'}
    assert {m['Destination']: m for m in created['Mounts']} == {m['Destination']: m for m in stopped['Mounts']} == {m['Destination']: m for m in row['Mounts']}
    first_host = dict(created['HostConfig'])
    if first_host.get('OomKillDisable') is False and stopped['HostConfig'].get('OomKillDisable') is None:
        first_host['OomKillDisable'] = None
    assert first_host == stopped['HostConfig'] == row['HostConfig'] and created['Config'] == stopped['Config'] == row['Config']
    assert json.loads(read(NATIVE / 'source-before.json')[0]) == json.loads(read(NATIVE / 'source-after.json')[0]) == probe
    facts = json.loads(read(NATIVE / 'output/native.json')[0])
    assert facts['schema'] == 'capacity-context-native-probe/1' and facts['python'] == '3.12.14' and facts['uid'] == 1000
    assert facts['numpy']['version'] == '2.5.3' and facts['numpy']['path'] == '/usr/local/lib/python3.12/site-packages/numpy/__init__.py'
    assert facts['backend_modules'] == [] and set(facts['threads']) == {'OPENBLAS_NUM_THREADS', 'OMP_NUM_THREADS', 'MKL_NUM_THREADS', 'NUMEXPR_NUM_THREADS', 'VECLIB_MAXIMUM_THREADS', 'BLIS_NUM_THREADS'} and set(facts['threads'].values()) == {'1'}
    admission_raw = read(TRANSFER / 'native-admission/admission.json', terminal['admission_sha256'])[0]
    assert json.loads(admission_raw)['genuine_or_parity_execution'] is False
    assert source_fold(tools_sha) == before
    proof = {'schema': 'capacity-context-native-metadata/1', 'status': 'VERIFIED_NATIVE_METADATA_ONLY', 'cid': row['Id'],
        'image': IMAGE, 'uid': 1000, 'stopped': True, 'exit': 0, 'OOMKilled': False, 'observed_at_ns': str(time.time_ns()),
        'probe_observed_at_ns': facts['observed_at_ns'], 'finished': row['State']['FinishedAt'], 'python': facts['python'],
        'numpy': facts['numpy'], 'threads': facts['threads'], 'backend_modules': [], 'inspect_sha256': inspect_sha,
        'source_physical': before, 'native_source': probe, 'admission_sha256': terminal['admission_sha256'], 'genuine_or_parity_acceptance': False}
    pin = save(NATIVE_REVIEW / 'proof.json', proof)
    print(json.dumps({'proof_sha256': pin, 'cid': row['Id'], 'numpy': facts['numpy'], 'genuine_or_parity_acceptance': False}, sort_keys=True))


# Refuse all routes except exact self-pinned independent prerequisite/native metadata observation.
def main(arguments):
    assert len(arguments) == 3 and arguments[0] in ('prerequisites', 'native-fold')
    route, self_sha, tools_sha = arguments
    read(Path(__file__), self_sha)
    assert os.getuid() == 1000 and socket.gethostname() == 'animallya-spark1'
    {'prerequisites': prerequisites, 'native-fold': native_fold}[route](tools_sha)


if __name__ == '__main__':
    main(sys.argv[1:])
