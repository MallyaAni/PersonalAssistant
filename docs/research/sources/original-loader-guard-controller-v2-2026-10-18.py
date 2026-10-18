"""SOURCE ONLY: proposed single-host owner for the tiny N2 guard fixtures.

There is no active launch entry point. A future caller must pin these exact
bytes and an external source-only review. No image load, pull, service change,
genuine artifact mount or model operation is supported. Docker client limits
are not daemon RAM limits. All stopped/failed containers and roots are kept.
"""

import hashlib
import json
import os
import resource
import signal
import stat
import subprocess
from pathlib import Path

IMAGE = 'sha256:e0a54c1f3b293c241ea0eae767d8ba017d0e1a05679965935b336910faa63237'
DOCKER = ['/usr/bin/docker', '--host', 'unix:///var/run/docker.sock']
LABEL = 'anios.synthetic.guard-owner'


# Name exact finite source or persisted metadata bytes.
def digest(raw):
    return hashlib.sha256(raw).hexdigest()


# Encode exact integers as JSON integers without a JavaScript number roundtrip.
def encode(value):
    return json.dumps(value, sort_keys=True, indent=2, allow_nan=False).encode() + b'\n'


# Preserve a new bounded receipt and verify its physical byte readback.
def save(path, raw):
    assert len(raw) <= 262144
    with path.open('xb') as output:
        output.write(raw)
        output.flush()
        os.fsync(output.fileno())
    assert path.read_bytes() == raw


# Preserve source-file identity using exact decimal strings for nanoseconds.
def identity(path):
    value = path.stat(follow_symlinks=False)
    assert stat.S_ISREG(value.st_mode) and not path.is_symlink()
    return {key: str(getattr(value, key)) for key in ('st_dev', 'st_ino', 'st_uid', 'st_mode', 'st_nlink', 'st_size', 'st_blocks', 'st_mtime_ns', 'st_ctime_ns')}


# Freeze every prepared file before suite mounts and require exact preservation.
def prepared_files(root, names):
    actual = sorted(str(path.relative_to(root)) for path in root.rglob('*') if not path.is_dir())
    assert actual == sorted(names) and len(actual) == 15
    result = {}
    for name in actual:
        path = root / name
        assert path.resolve(strict=True) == path
        before = identity(path)
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        try:
            held_before = os.fstat(descriptor)
            assert {key: str(getattr(held_before, key)) for key in before} == before
            chunks, count = [], 0
            while block := os.read(descriptor, 65536):
                count += len(block)
                assert count <= 262144
                chunks.append(block)
            held_after = os.fstat(descriptor)
            assert {key: str(getattr(held_after, key)) for key in before} == before
            assert identity(path) == before
        finally:
            os.close(descriptor)
        raw = b''.join(chunks)
        assert len(raw) == int(before['st_size'])
        result[name] = {'sha256': digest(raw), 'physical': before}
    return result


# Check fresh ordinary headroom without calling it a reservation or capacity proof.
def headroom(root):
    memory = dict(line.split(':', 1) for line in Path('/proc/meminfo').read_text().splitlines())
    available = int(memory['MemAvailable'].split()[0]) * 1024
    disk = os.statvfs(root)
    assert available >= 5 * 1024 ** 3 and disk.f_bavail * disk.f_frsize >= 4 * 1024 ** 3 and disk.f_favail >= 8192
    return {'MemAvailable': str(available), 'disk_available': str(disk.f_bavail * disk.f_frsize), 'inodes_available': str(disk.f_favail), 'reservation': False}


# Raise at the real controller deadline so owned cleanup still runs.
def alarm(signum, frame):
    raise KeyboardInterrupt('SYNTHETIC_OWNER_WALL_DEADLINE')


# Limit each Docker CLI log file without pretending to constrain the daemon.
def cli_limits():
    resource.setrlimit(resource.RLIMIT_FSIZE, (262144, 262144))
    os.nice(10)


# Keep a finite registry of exact owned CLI processes and container names.
class Owner:
    # Bind the exclusive root and immutable source review to this one proposal.
    def __init__(self, root, source, review_sha):
        assert os.getuid() == 1000 and root.is_absolute() and source.is_absolute()
        assert root.parent.is_dir() and not root.exists() and not source.is_relative_to(root)
        assert source.resolve(strict=True) == source and root.parent.resolve(strict=True) == root.parent
        root.mkdir(mode=0o700)
        self.root, self.source, self.review_sha = root, source, review_sha
        self.children, self.names, self.counter = [], [], 0
        self.label = digest((str(root) + ':' + review_sha).encode())

    # Run a bounded local-daemon command and retain logs and the exact child exit.
    def command(self, arguments, *, timeout=10, allow_failure=False):
        self.counter += 1
        assert self.counter <= 48
        stem = str(self.counter).zfill(3)
        stdout = (self.root / (stem + '.stdout')).open('xb')
        stderr = (self.root / (stem + '.stderr')).open('xb')
        environment = dict(os.environ)
        for key in ('DOCKER_HOST', 'DOCKER_CONTEXT', 'DOCKER_TLS_VERIFY', 'DOCKER_CERT_PATH'):
            environment.pop(key, None)
        process, stopped = None, None
        try:
            prior = signal.pthread_sigmask(signal.SIG_BLOCK, {signal.SIGALRM})
            try:
                process = subprocess.Popen(DOCKER + arguments, stdin=subprocess.DEVNULL, stdout=stdout, stderr=stderr, env=environment, preexec_fn=cli_limits)
                self.children.append((process, stdout, stderr))
            finally:
                signal.pthread_sigmask(signal.SIG_SETMASK, prior)
            try:
                process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                stopped = 'TERM'
                process.terminate()
                try:
                    process.wait(timeout=1)
                except subprocess.TimeoutExpired:
                    stopped = 'KILL'
                    process.kill()
                    process.wait(timeout=1)
        finally:
            # An outer alarm can interrupt wait or unmasking after registration.
            # Reap and persist that exact CLI even while propagating the failure.
            if process is not None and process.poll() is None:
                stopped = 'INTERRUPTED_TERM'
                process.terminate()
                try:
                    process.wait(timeout=1)
                except subprocess.TimeoutExpired:
                    stopped = 'INTERRUPTED_KILL'
                    process.kill()
                    process.wait(timeout=1)
            stdout.flush()
            stderr.flush()
            os.fsync(stdout.fileno())
            os.fsync(stderr.fileno())
            save(self.root / (stem + '.exit.json'), encode({'pid': None if process is None else str(process.pid),
                                                          'returncode': None if process is None else process.returncode,
                                                          'owned_stop': stopped, 'arguments': arguments}))
            if process is None:
                stdout.close()
                stderr.close()
        raw = (self.root / (stem + '.stdout')).read_bytes()
        error = (self.root / (stem + '.stderr')).read_bytes()
        assert len(raw) <= 262144 and len(error) <= 262144
        assert stopped is None
        if not allow_failure:
            assert process.returncode == 0 and not error
        return process.returncode, raw, error

    # Validate a known owned container without admitting a genuine backend profile.
    def inspect(self, name, binds, *, stopped):
        code, raw, error = self.command(['inspect', '--type=container', name])
        rows = json.loads(raw)
        assert len(rows) == 1
        row = rows[0]
        host, config = row['HostConfig'], row['Config']
        assert row['Name'] == '/' + name and config['Labels'][LABEL] == self.label and row['Image'] == IMAGE
        assert config['User'] == '1000:1000' and host['NetworkMode'] == 'none' and host['ReadonlyRootfs'] is True
        assert host['Memory'] == host['MemorySwap'] == 2147483648 and host['NanoCpus'] == 1000000000
        assert host['PidsLimit'] == 32 and host['Tmpfs'] == {'/tmp': 'rw,size=64m'}
        assert host['Privileged'] is False and not host['CapAdd'] and not host['Devices']
        assert host['CapDrop'] == ['ALL'] and 'no-new-privileges:true' in host['SecurityOpt']
        assert host['LogConfig']['Type'] == 'none' and config.get('Healthcheck', {}).get('Test') == ['NONE']
        actual = {(item['Source'], item['Destination'], item['RW']) for item in row['Mounts']}
        assert len(actual) == len(row['Mounts']) and actual == set(binds)
        if stopped:
            assert row['State']['Running'] is False and row['State']['ExitCode'] == 0 and row['State']['OOMKilled'] is False
        return row

    # Create one named tiny-runtime phase with no genuine artifacts or socket mount.
    def phase(self, role, binds, arguments, *, timeout):
        assert role in ('prepare', 'suite') and len(self.names) < 2
        name = 'n2-guard-' + self.label[:20] + '-' + role
        self.names.append(name)
        save(self.root / (role + '-headroom.json'), encode(headroom(self.root)))
        command = ['create', '--pull=never', '--name', name, '--label', LABEL + '=' + self.label,
                   '--user', '1000:1000', '--network', 'none', '--read-only', '--cpus', '1',
                   '--memory', '2g', '--memory-swap', '2g', '--pids-limit', '32',
                   '--tmpfs', '/tmp:rw,size=64m', '--no-healthcheck', '--log-driver', 'none',
                   '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges:true', '--entrypoint', 'python']
        for source, target, writable in binds:
            assert ',' not in source and ',' not in target
            command += ['--mount', 'type=bind,src=' + source + ',dst=' + target + ('' if writable else ',readonly')]
        command += [IMAGE, '-I', '-S', '-B', '/audit/bootstrap.py'] + arguments
        code, raw, error = self.command(command)
        cid = raw.decode().strip()
        assert len(cid) == 64 and all(char in '0123456789abcdef' for char in cid)
        before = self.inspect(name, binds, stopped=False)
        assert before['Id'] == cid and before['State']['Status'] == 'created'
        save(self.root / (role + '-before.json'), encode(before))
        self.command(['start', '--attach', cid], timeout=timeout)
        after = self.inspect(name, binds, stopped=True)
        save(self.root / (role + '-after.json'), encode(after))
        return cid

    # Stop only exact labelled names registered before create, retaining containers.
    def cleanup(self):
        failures = []
        for process, stdout, stderr in self.children:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=1)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=1)
            stdout.close()
            stderr.close()
        # There are at most two names and two finite inspections/stops per name.
        for name in self.names:
            try:
                code, raw, error = self.command(['inspect', '--type=container', name], timeout=3, allow_failure=True)
                if code != 0:
                    save(self.root / (name + '-cleanup-unobserved.json'), encode({'status': 'UNVERIFIED_CONTAINER_STATE', 'exit': code}))
                    failures.append(name + ':UNOBSERVED')
                    continue
                rows = json.loads(raw)
                assert len(rows) == 1 and rows[0]['Name'] == '/' + name and rows[0]['Config']['Labels'].get(LABEL) == self.label
                if rows[0]['State']['Running']:
                    self.command(['stop', '--time=1', rows[0]['Id']], timeout=3)
                    code, terminal_raw, error = self.command(['inspect', '--type=container', rows[0]['Id']], timeout=3)
                    terminal = json.loads(terminal_raw)[0]
                    assert terminal['State']['Running'] is False
                    save(self.root / (name + '-owned-stop.json'), terminal_raw)
            except BaseException as error:
                failures.append(name + ':' + type(error).__name__)
        for process, stdout, stderr in self.children:
            if not stdout.closed:
                stdout.close()
                stderr.close()
        assert not failures, failures


# Describe a fully concrete future two-phase invocation without authorizing it.
def proposed_run(root, source, review_sha):
    review_path = source / 'review.json'
    review_raw = review_path.read_bytes()
    assert len(review_raw) <= 262144 and digest(review_raw) == review_sha
    review = json.loads(review_raw)
    assert review['scope'] == 'SOURCE_REVIEWED_SYNTHETIC_ONLY'
    assert set(review['source_sha256']) == {'bootstrap.py', 'fixture.py', 'suite.py', 'harness.py', 'producer-source.txt', 'continuation-source.txt'}
    assert {path.name for path in source.iterdir()} == set(review['source_sha256']) | {'review.json'}
    bookends = {}
    for name, checksum in review['source_sha256'].items():
        path = source / name
        raw = path.read_bytes()
        assert len(raw) <= 262144 and digest(raw) == checksum
        bookends[name] = identity(path)
    owner = Owner(root, source, review_sha)
    signal.signal(signal.SIGALRM, alarm)
    signal.setitimer(signal.ITIMER_REAL, 120)
    try:
        owner.command(['image', 'inspect', IMAGE])
        preparation = root / 'preparation'
        preparation.mkdir(mode=0o700)
        owner.phase('prepare', [(str(source), '/audit', False), (str(preparation), '/out', True)],
                    ['prepare', '/audit/review.json', review_sha], timeout=15)
        prepared = preparation / 'prepared'
        summary_raw = (prepared / 'prepared.json').read_bytes()
        assert len(summary_raw) <= 262144
        summary = json.loads(summary_raw)
        assert summary['scope'] == 'SYNTHETIC_ONLY_NO_GENUINE_ADMISSION' and summary['model_or_account_calls'] is False
        assert len(summary['files']) == 10
        for name, record in summary['files'].items():
            assert name.startswith('backend/') and '..' not in Path(name).parts
            path = prepared / 'source' / name
            raw = path.read_bytes()
            assert len(raw) == record['bytes'] <= 262144 and digest(raw) == record['sha256']
        assert digest((prepared / 'calls.json').read_bytes()) == summary['calls_sha256']
        assert digest((prepared / 'scenarios.json').read_bytes()) == summary['scenarios_sha256']
        bundle = dict(review, fixture_path='/fixture', prepared_sha256=digest(summary_raw), scenarios_sha256=summary['scenarios_sha256'])
        bundle_raw = encode(bundle)
        save(prepared / 'bundle.json', bundle_raw)
        frozen_names = ['source/' + name for name in summary['files']] + ['prepared.json', 'calls.json', 'scenarios.json', 'continuation-source.txt', 'bundle.json']
        prepared_before = prepared_files(prepared, frozen_names)
        save(root / 'prepared-before.json', encode(prepared_before))
        output = root / 'suite-output'
        output.mkdir(mode=0o700)
        owner.phase('suite', [(str(source), '/audit', False), (str(prepared), '/fixture', False),
                              (str(prepared / 'source'), '/app', False), (str(output), '/out', True)],
                    ['suite', '/fixture/bundle.json', digest(bundle_raw)], timeout=75)
        prepared_after = prepared_files(prepared, frozen_names)
        assert prepared_before == prepared_after
        save(root / 'prepared-after.json', encode(prepared_after))
        final_raw = (output / 'suite/suite.json').read_bytes()
        assert len(final_raw) <= 262144
        final = json.loads(final_raw)
        assert final['scope'] == 'SYNTHETIC_ONLY_NOT_GENUINE_SOURCE_OR_RUNTIME_ADMISSION'
        assert len(final['cases']) == len(json.loads((prepared / 'scenarios.json').read_bytes()))
        for name, before in bookends.items():
            assert identity(source / name) == before and digest((source / name).read_bytes()) == review['source_sha256'][name]
        save(root / 'owner-candidate.json', encode({'status': 'REQUIRES_INDEPENDENT_REVIEW', 'suite_sha256': digest(final_raw),
                                                  'source_bookends': bookends, 'genuine_loader': False,
                                                  'combined_model_memory': False, 'publication': 'CLOSED'}))
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        owner.cleanup()


if __name__ == '__main__':
    raise SystemExit('SOURCE_ONLY_NO_SYNTHETIC_RUNTIME_ADMISSION')
