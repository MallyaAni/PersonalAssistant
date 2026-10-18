"""UNEXECUTED tiny-fixture suite proposal; this is not a genuine loader route.

Every guarded case owns a fresh interpreter. Injected SourceBook and runtime
metadata are deliberately labelled synthetic. Actual kernel memory counters
are read by the unchanged harness. Neither genuine artifacts nor application
modules may be mounted. A separate source-reviewed controller is required.
"""

import hashlib
import importlib
import json
import os
import resource
import shutil
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

IMAGE = 'sha256:e0a54c1f3b293c241ea0eae767d8ba017d0e1a05679965935b336910faa63237'
ORIGINAL_ACCOUNT_DECLARATION_ONLY = '/home/animallya96/scratch/live-model-history-full-20261013-v1/output/account'
FINGERPRINT = {'algorithm': 'cpython-code-marshal-format-2-sha256/1', 'marshal_version': 2}
HARNESS_SHA = '030cb5bb25f89c2785e6acbd55aceff5c99b632a5eb538079ee027362ae6178a'
MANIFEST_SCHEMA = 'n2-capacity-call-manifest/2'

OWNED = []
TOTAL_CHILDREN = 0
LAST_ALARM = None


# Produce finite deterministic fixture records, never native state.
def encoded(value):
    return json.dumps(value, sort_keys=True, indent=2, allow_nan=False).encode() + b'\n'


# Name complete bounded source or evidence bytes.
def sha(raw):
    return hashlib.sha256(raw).hexdigest()


# Mutate one known fixture field while refusing an unchanged mutation proposal.
def replace_one(raw, old, new):
    assert raw.count(old) == 1
    return raw.replace(old, new, 1)


# Persist an absent bounded evidence file with exact readback.
def save(path, raw):
    assert len(raw) <= 262144
    with path.open('xb') as output:
        output.write(raw)
        output.flush()
        os.fsync(output.fileno())
    assert path.read_bytes() == raw


# Hold a fully allocated regular failure inode before a guard is constructed.
def slot(path):
    descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_RDWR, 0o600)
    os.posix_fallocate(descriptor, 0, 65536)
    assert os.pread(descriptor, 65536, 0) == bytes(65536)
    os.fsync(descriptor)
    return descriptor


# Build an explicitly injected tiny SourceBook without weakening its constructor.
def injected_book(harness, root, pins):
    book = object.__new__(harness.SourceBook)
    book.root = str(root)
    book.fd = harness.directory_fd(str(root))
    book.pins = dict(pins)
    book.bookends = {}
    book.authenticated = False
    return book


# Add a declared tiny source and its exact code keys before installing any guard.
def add_source(harness, fixture, root, pins, manifest, name, raw):
    target = root / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(raw)
    pins[name] = sha(raw)
    for rows in manifest['calls'].values():
        rows[:] = [row for row in rows if row[0] != name]
    for code in fixture.codes(compile(raw, str(target), 'exec', dont_inherit=True, optimize=0)):
        for phase in fixture.phases_for(name, code):
            manifest['calls'][phase].append([name, code.co_qualname, code.co_firstlineno])


# Prepare fake inspection declarations without pretending they describe Docker.
def fake_invocation(harness, book, proof, case_root):
    host = socket.gethostname()
    mounts = [
        {'Type': 'bind', 'RW': False, 'Source': ORIGINAL_ACCOUNT_DECLARATION_ONLY, 'Destination': '/synthetic-account'},
        {'Type': 'bind', 'RW': False, 'Source': '/synthetic-host-market', 'Destination': '/synthetic-market'},
        {'Type': 'bind', 'RW': False, 'Source': '/synthetic-host-source', 'Destination': '/app'},
        {'Type': 'bind', 'RW': True, 'Source': '/synthetic-host-output', 'Destination': str(proof)},
    ]
    actual = [{'_INJECTED_SYNTHETIC_NOT_ACTUAL_INSPECT': True, 'Id': host + '0' * 64, 'Image': IMAGE,
               'Config': {'Hostname': host, 'User': '1000:1000'},
               'HostConfig': {'NetworkMode': 'none', 'ReadonlyRootfs': True, 'NanoCpus': 1000000000,
                              'Memory': 2147483648, 'MemorySwap': 2147483648,
                              'Tmpfs': {'/tmp': 'rw,size=64m'}, 'Privileged': False, 'CapAdd': None, 'Devices': []},
               'Mounts': mounts}]
    value = {'profile': 'original-full-27471', 'account': '/synthetic-account', 'market': '/synthetic-market',
             'proof_parent': str(proof), 'audit_source_sha256': book.pins,
             'manifest': '/synthetic-manifest', 'execution': '/synthetic-execution', 'physical_bytes': 0}
    for field in ('completion_sha256', 'initial_sha256', 'manifest_sha256', 'execution_sha256', 'physical_sha256'):
        value[field] = 'a' * 64
    return value, actual


# Advance through the actual fixed phase API without changing its clock or metrics.
def load_phase(fence):
    fence.advance('ADMISSION')
    fence.advance('BEFORE')
    fence.advance('LOAD')


# Stop an exact compiled prefix before its first fixture-only dependency proceeds.
def dependency_stop(*arguments, **keywords):
    Path(os.environ['CASE_OUT'], 'prefix-dependency.marker').write_text('stopped-before-data')
    raise LookupError('SYNTHETIC_FIRST_DEPENDENCY_STOP')


# Exercise one new fixture case in a fresh interpreter with a permanent guard.
def child(row, case_root, prepared, harness, fixture):
    group, variant = row['group'], row['variant']
    proof = case_root / 'proof'
    proof.mkdir(mode=0o700)
    os.environ['CASE_OUT'] = str(proof)
    os.environ['CASE_VARIANT'] = variant
    failure = slot(proof / 'guard-failure.bin')
    summary = json.loads((prepared / 'prepared.json').read_bytes())
    pins = {name: record['sha256'] for name, record in summary['files'].items()}
    manifest = json.loads((prepared / 'calls.json').read_bytes())
    assert sha((prepared / 'calls.json').read_bytes()) == summary['calls_sha256']
    workflow = group in ('G14', 'G15', 'G16', 'G17') or (group == 'G13' and variant == 'path')
    root = Path('/app') if workflow else prepared / 'source'
    if group in ('G03', 'G04', 'G05', 'G07') or (group == 'G17' and variant == 'source'):
        root = case_root / 'source'
        shutil.copytree(prepared / 'source', root)
        os.environ['CASE_SOURCE'] = str(root)
    if group == 'G03':
        name = 'backend/capacity_fixture.py'
        raw = (root / name).read_bytes() + b'\nhidden()\n'
        add_source(harness, fixture, root, pins, manifest, name, raw)
    if group in ('G02', 'G03'):
        for rows in manifest['calls'].values():
            rows[:] = [item for item in rows if item[1] != 'hidden']
    if group == 'G04':
        # Ambient files and bytecode must not satisfy a missing recipe entry.
        if variant == 'shadow':
            (root / 'backend/shadow.py').write_text("raise AssertionError('AMBIENT_FALLBACK')\n")
        if variant == 'pyc':
            (root / 'backend/shadow.pyc').write_bytes(b'NOT_VALID_BYTECODE')
    if group == 'G07' and variant != 'stateful':
        raw = ("from pathlib import Path\nimport os\n# Mark only a guard failure.\ndef " + variant + "():\n    Path(os.environ['CASE_OUT'], 'forbidden.marker').write_text('entered')\n").encode()
        add_source(harness, fixture, root, pins, manifest, 'backend/capacity_forbidden.py', raw)
    if group == 'G09' and variant != 'generated-positive':
        field = 'code_sha256' if variant == 'generated-code' else 'producer_source_sha256'
        for item in manifest['generated']:
            if item['module'] == 'backend.capacity_dataclass':
                item[field] = '0' * 64
    if group == 'G10':
        if variant in ('prefix-wrapper', 'prefix-inputs'):
            qualname = '<module>' if variant == 'prefix-wrapper' else 'inputs'
            manifest['generated'] = [item for item in manifest['generated'] if not (item['module'] == 'backend.cli.market_strategy_continue' and item['qualname'] == qualname)]
        if variant == 'prefix-producer':
            for item in manifest['generated']:
                if item['module'] == 'backend.cli.market_strategy_continue':
                    item['producer_source_sha256'] = '0' * 64
    if group == 'G13':
        if variant in ('readonly', 'append'):
            os.close(failure)
            failure = os.open(proof / 'guard-failure.bin', os.O_RDONLY if variant == 'readonly' else os.O_RDWR | os.O_APPEND)
        elif variant == 'sparse':
            os.ftruncate(failure, 0)
            os.ftruncate(failure, 65536)
        elif variant == 'size':
            os.ftruncate(failure, 65535)
        elif variant == 'link':
            os.link(proof / 'guard-failure.bin', case_root / 'extra-link')
        elif variant == 'nonzero':
            os.pwrite(failure, b'x', 0)
    if group == 'G05' and variant == 'root-link':
        link = case_root / 'root-link'
        link.symlink_to(root, target_is_directory=True)
        root = link
    book = injected_book(harness, root, pins)
    book.authenticate_all()
    if group == 'G17' and variant == 'source':
        # This explicit synthetic FD/root injection is not genuine admission:
        # compile names stay /app while a private writable copy supplies bytes.
        book.root = '/app'
    if group == 'G05':
        target = root / 'backend/capacity_fixture.py'
        if variant == 'middle-link':
            (root / 'backend').rename(root / 'backend-old')
            (root / 'backend').symlink_to(root / 'backend-old', target_is_directory=True)
        elif variant == 'file-link':
            target.rename(target.with_suffix('.saved'))
            target.symlink_to(target.with_suffix('.saved'))
        elif variant == 'replace':
            replacement = target.with_suffix('.replacement')
            replacement.write_bytes(target.read_bytes())
            os.replace(replacement, target)
        elif variant == 'tamper':
            target.write_bytes(target.read_bytes() + b'x')
        elif variant == 'grow':
            # Parent prepared this exact oversized fixture before the capped
            # child. Replacement performs no write beyond its per-file cap.
            os.replace(case_root / 'growth.bin', target)
    raw = encoded(manifest)
    expected = sha(raw)
    if group == 'G06':
        if variant == 'manifest-sha':
            expected = '0' * 64
        elif variant == 'manifest-schema':
            manifest['schema'] = 'wrong'
            raw = encoded(manifest)
        elif variant == 'manifest-duplicate':
            raw = raw[:-2] + b', "schema": "duplicate"}\n'
        else:
            raw = raw[:-2] + b', "extra": NaN}\n'
        if variant != 'manifest-sha':
            expected = sha(raw)
    fence = harness.CallFence(book, raw, expected, failure)
    finder = harness.PinnedBackendFinder(book, fence)
    if not (group == 'G14' and variant == 'no-finder'):
        sys.meta_path.insert(0, finder)
    if not (group == 'G14' and variant == 'no-fence'):
        fence.install()
    if group == 'G14' and variant == 'no-auth':
        book.authenticated = False
    if group == 'G13' and variant == 'path':
        (proof / 'guard-failure.bin').rename(case_root / 'held-original-slot.bin')
        replacement = slot(proof / 'guard-failure.bin')
        os.close(replacement)
    if workflow:
        value, actual = fake_invocation(harness, book, proof, case_root)
        if group == 'G15':
            if variant == 'runtime':
                actual[0]['Image'] = 'sha256:' + '0' * 64
            elif variant == 'profile':
                value['profile'] = 'CURRENT_NOT_ORIGINAL'
            elif variant == 'mapping':
                actual[0]['Mounts'][0]['Source'] = '/synthetic-wrong-account'
        runtime_raw = encoded(actual)
        if group == 'G15' and variant == 'runtime-duplicate':
            runtime_raw = replace_one(runtime_raw, b'"Image":', b'"Image": "duplicate", "Image":')
        elif group == 'G15' and variant == 'runtime-nan':
            runtime_raw = replace_one(runtime_raw, b'"_INJECTED_SYNTHETIC_NOT_ACTUAL_INSPECT": true', b'"_INJECTED_SYNTHETIC_NOT_ACTUAL_INSPECT": NaN')
        value['runtime_sha256'] = sha(runtime_raw)
        if group == 'G15' and variant == 'runtime-hash':
            value['runtime_sha256'] = '0' * 64
        invocation_raw = encoded(value)
        if group == 'G15' and variant == 'invocation-duplicate':
            invocation_raw = replace_one(invocation_raw, b'"profile":', b'"profile": "duplicate", "profile":')
        path = case_root / 'invocation.json'
        save(path, invocation_raw)
        save(case_root / 'INJECTED-NOT-ACTUAL-runtime.json', runtime_raw)
        expected_invocation = '0' * 64 if group == 'G15' and variant == 'invocation-hash' else sha(invocation_raw)
        harness._capacity_steps(path, expected_invocation, runtime_raw, book, fence)
    elif group in ('G01', 'G02', 'G03', 'G04', 'G05', 'G11'):
        module = importlib.import_module('backend.shadow' if group == 'G04' else 'backend.capacity_fixture')
        if group == 'G02':
            alias = module.hidden
            alias()
        elif group == 'G11':
            try:
                # Deliberately register the forbidden effect body but omit its phase key.
                fence.manifest['calls']['BOOTSTRAP'] = [item for item in fence.manifest['calls']['BOOTSTRAP'] if item[1] != 'hidden']
                module.hidden()
            except BaseException:
                (proof / 'caught.marker').write_text('GUARD_WAS_CATCHABLE')
        elif group == 'G01':
            module.safe()
    elif group == 'G07':
        if variant == 'stateful':
            module = importlib.import_module('backend.market.live_model_history_stream_audit')
            module.StreamAudit()
        else:
            module = importlib.import_module('backend.capacity_forbidden')
            getattr(module, variant)()
    elif group == 'G08':
        module = importlib.import_module('backend.market.replay_broker' if variant == 'effect-generated' else 'backend.market.alpaca_trading')
        if variant == 'effect-generated':
            module.Sample(3)
        else:
            module.hidden()
    elif group == 'G09':
        module = importlib.import_module('backend.capacity_dataclass')
        assert module.Sample(3).value == 3
    elif group == 'G10':
        if variant != 'prefix-phase':
            load_phase(fence)
        namespace = {'__name__': 'backend.cli.market_strategy_continue', 'MarketStore': dependency_stop}
        prefix = fixture.daily_code((prepared / 'continuation-source.txt').read_bytes())
        exec(prefix, namespace)
        try:
            namespace['inputs']('/synthetic-not-read', None, None)
        except LookupError as error:
            assert str(error) == 'SYNTHETIC_FIRST_DEPENDENCY_STOP'
    elif group == 'G12':
        if variant == 'profile':
            sys.setprofile(None)
        elif variant == 'trace':
            sys.settrace(None)
        elif variant == 'thread':
            import _thread
            _thread.start_new_thread(time.sleep, (30,))
        elif variant == 'socket':
            socket.socket()
        else:
            subprocess.Popen([sys.executable, '-I', '-S', '-B', '-c', 'raise SystemExit(0)'])
    else:
        raise AssertionError('NEGATIVE_CASE_UNEXPECTEDLY_RETURNED')
    save(case_root / 'returned.json', encoded({'case': row['id'], 'status': 'SYNTHETIC_RETURNED', 'backend_modules': sorted(name for name in sys.modules if name == 'backend' or name.startswith('backend.'))}))


# Write bounded refusal evidence for ordinary metadata exceptions only.
def child_entry(row, case_root, prepared, harness, fixture):
    try:
        child(row, case_root, prepared, harness, fixture)
    except BaseException as error:
        save(case_root / 'error.json', encoded({'class': type(error).__name__, 'message': str(error)[:1024],
                                               'errno': getattr(error, 'errno', None),
                                               'backend_modules': sorted(name for name in sys.modules if name == 'backend' or name.startswith('backend.'))}))
        return 1
    return 0


# Make parent timeouts raise so an outer finally always performs owned cleanup.
def alarm(signum, frame):
    global LAST_ALARM
    LAST_ALARM = {'signum': signum, 'monotonic': time.monotonic()}
    raise KeyboardInterrupt('SYNTHETIC_SUITE_WALL_DEADLINE')


# Bound each owned child independently without relabelling per-file limits quotas.
def limits():
    resource.setrlimit(resource.RLIMIT_FSIZE, (262144, 262144))
    resource.setrlimit(resource.RLIMIT_CPU, (3, 3))


# Register each exact child while blocking the suite alarm across Popen.
def start(command, root):
    global TOTAL_CHILDREN
    assert TOTAL_CHILDREN < 128
    stdout = (root / 'stdout.log').open('xb')
    stderr = (root / 'stderr.log').open('xb')
    prior = signal.pthread_sigmask(signal.SIG_BLOCK, {signal.SIGALRM})
    try:
        process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=stdout, stderr=stderr, preexec_fn=limits)
        OWNED.append((process, root, stdout, stderr))
        TOTAL_CHILDREN += 1
    finally:
        signal.pthread_sigmask(signal.SIG_SETMASK, prior)
    return process


# Reap only registered exact PIDs and retain physical terminal evidence.
def finish(process, root, timeout=3):
    stopped = None
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
        if process.stdin is not None:
            process.stdin.close()
    record = {'pid': str(process.pid), 'returncode': process.returncode, 'owned_stop': stopped}
    save(root / 'terminal.json', encoded(record))
    return record


# Close logs and stop remaining registered children without touching other jobs.
def cleanup():
    for process, root, stdout, stderr in OWNED:
        if not (root / 'terminal.json').exists():
            finish(process, root, timeout=0.05)
        stdout.flush()
        stderr.flush()
        os.fsync(stdout.fileno())
        os.fsync(stderr.fileno())
        stdout.close()
        stderr.close()


# Observe a real child's physical readiness before testing a wait or interrupt.
def ready(root, process):
    deadline = time.monotonic() + 1
    while time.monotonic() < deadline:
        assert process.poll() is None
        if (root / 'stdout.log').read_bytes() == b'READY\n':
            return
        time.sleep(0.01)
    raise AssertionError('WAITING_CHILD_NOT_READY')


# Prepare one finite oversized source before the child's unchanged file-size cap.
def prepare_growth(root, prepared):
    base = (prepared / 'source/backend/capacity_fixture.py').read_bytes()
    assert len(base) <= 4096
    raw = base + bytes(1048577)
    path = root / 'growth.bin'
    with path.open('xb') as output:
        offset = 0
        while offset < len(raw):
            count = output.write(raw[offset:offset + 65536])
            assert count > 0
            offset += count
        output.flush()
        os.fsync(output.fileno())
        value = os.fstat(output.fileno())
    assert path.read_bytes() == raw
    save(root / 'growth.json', encoded({'sha256': sha(raw), 'bytes': len(raw), 'inode': str(value.st_ino),
                                      'parent_pid': str(os.getpid()), 'scope': 'BOUNDED_OVERSIZED_REPLACEMENT_NOT_INPLACE_GROWTH'}))


# Check the specific declared guard or source boundary, never a generic exit code.
def assess(row, root, terminal):
    group, variant = row['group'], row['variant']
    forbidden = root / 'proof/forbidden.marker'
    assert not forbidden.exists() and not (root / 'proof/caught.marker').exists()
    assert terminal['owned_stop'] is None
    if group in ('G02', 'G03', 'G07', 'G08', 'G11', 'G12') or (group == 'G09' and variant != 'generated-positive') or (group == 'G10' and variant != 'prefix-positive'):
        assert terminal['returncode'] == 86
        body = (root / 'proof/guard-failure.bin').read_bytes()
        failure = json.loads(body.rstrip(b'\0'))
        if group in ('G02', 'G03', 'G11'):
            reasons = {'UNREVIEWED_PHASE_CALL'}
        elif group == 'G07':
            reasons = {'FORBIDDEN_STATEFUL_CLASS'} if variant == 'stateful' else {'FORBIDDEN_FUNCTION'}
        elif group == 'G08':
            reasons = {'BROKER_OR_ACCOUNT_FUNCTION'}
        elif group in ('G09', 'G10'):
            reasons = {'UNREVIEWED_GENERATED_CODE', 'UNREGISTERED_OR_GENERATED_CODE'}
        else:
            reasons = {'PROFILE_REPLACEMENT', 'PROFILE_OR_TRACE_REPLACEMENT'} if variant in ('profile', 'trace') else {'UNADMITTED_PYTHON_THREAD'} if variant == 'thread' else {'FORBIDDEN_AUDIT_EVENT'}
        assert failure['reason'] in reasons and failure['publication'] == 'CLOSED'
        if group == 'G08' and variant == 'effect-generated':
            # A factory refusal is narrower than proof of instance denial.
            assert '__create_fn__' in failure['identity']
        return {'kind': 'EXPECTED_GUARD_REFUSAL', 'failure': failure}
    if group in ('G01', 'G16') or (group == 'G09' and variant == 'generated-positive') or (group == 'G10' and variant == 'prefix-positive'):
        assert terminal['returncode'] == 0 and (root / 'returned.json').is_file()
        assert (root / 'proof/guard-failure.bin').read_bytes() == bytes(65536)
        if group == 'G01':
            assert (root / 'proof/safe.marker').read_text() == 'safe'
        if group == 'G10':
            assert (root / 'proof/prefix-dependency.marker').read_text() == 'stopped-before-data'
        if group == 'G16':
            destination = root / 'proof/original-loader-capacity'
            candidate = json.loads((destination / 'candidate.json').read_bytes())
            assert candidate['risk_bank_rows'] == candidate['full_fixed_calibration_dates'] == 3
            assert len(candidate['retained_arrays']) == 1 and candidate['retained_arrays'][0]['view_nbytes'] == '2'
            assert candidate['historical_publication_authorized'] is False and candidate['account_or_orders'] is False
            assert len(list(destination.glob('phase-*.json'))) == 5
            for index in (1, 2):
                observed = json.loads((root / ('proof/coexist-' + str(index) + '.json')).read_bytes())
                assert observed['loaded_alive'] and observed['distinct_receipts']
                assert observed['has_serialized'] == observed['has_encoded'] == (index == 2)
            assert (root / 'proof/load.json').is_file()
            assert (root / 'proof/auth-1.json').is_file() and (root / 'proof/auth-2.json').is_file()
        return {'kind': 'SYNTHETIC_RETURN_PATH'}
    assert terminal['returncode'] == 1 and (root / 'error.json').is_file()
    error = json.loads((root / 'error.json').read_bytes())
    tokens = {
        'G04': ('EXACT_BACKEND_MODULE_REQUIRED',),
        'G05': ('SOURCE_BYTES_DIFFER', 'SOURCE_CHANGED_SINCE_ADMISSION', 'BOUNDED_REGULAR_SOURCE_REQUIRED', 'Too many levels', 'Not a directory'),
        'G06': ('EXTERNALLY_PINNED_CALL_MANIFEST_REQUIRED', 'CALL_MANIFEST_BINDING_DIFFERS', 'DUPLICATE_METADATA_FIELD', 'NONFINITE_METADATA_TOKEN'),
        'G13': ('READWRITE_NONAPPEND_FAILURE_SLOT_REQUIRED', 'PREALLOCATED_FAILURE_SLOT_REQUIRED', 'FAILURE_SLOT_NOT_EMPTY', 'RESERVED_FAILURE_FD_PATH_DIFFERS'),
        'G14': ('PREIMPORT_CALL_GUARD_REQUIRED', 'COMPLETE_SOURCE_ADMISSION_REQUIRED', 'PINNED_IMPORT_FINDER_MUST_BE_FIRST'),
        'G15': ('EXACT_ORIGINAL_AUDITOR_REQUIRED', 'EXACT_ORIGINAL_ACCOUNT_MAPPING_REQUIRED', 'EXACT_NATIVE_PACKAGES_REQUIRED', 'DUPLICATE_METADATA_FIELD', 'NONFINITE_METADATA_TOKEN', 'EXTERNAL_RUNTIME_BYTES_REQUIRED', 'EXTERNAL_INVOCATION_BYTES_REQUIRED'),
        'G17': ('COMPLETE_BYTE_RECEIPTS_CHANGED', 'ORIGINAL_STATE_CHANGED', 'Out of range float', 'File exists', 'SOURCE_BYTES_DIFFER', 'SOURCE_CHANGED_SINCE_ADMISSION', 'RETAINED_STACK_BOUND', 'CAPACITY_RESULT_BOUND_EXCEEDED'),
    }
    assert any(token in error['message'] for token in tokens[group]), error
    if group in ('G04', 'G05', 'G06', 'G14') or (group == 'G13' and variant != 'path') or (group == 'G15' and variant != 'version'):
        assert 'backend.cli.audit_original_live_model_history' not in error['backend_modules']
    if group == 'G17' and variant == 'collision':
        assert (root / 'proof/original-loader-capacity/candidate.json').read_bytes() == b'ORPHAN_DO_NOT_REPLACE'
    if group == 'G13' and variant == 'path':
        assert (root / 'held-original-slot.bin').stat().st_ino != (root / 'proof/guard-failure.bin').stat().st_ino
    if group == 'G17' and variant in ('source', 'inventory-growth', 'output-growth'):
        assert not (root / 'proof/original-loader-capacity/candidate.json').exists()
    return {'kind': 'EXPECTED_METADATA_REFUSAL', 'error': error}


# Exercise real waits, deadline interruption and exact ownership with tiny children.
def cleanup_controls(output):
    sentinel_root = output / 'G18-sentinel'
    sentinel_root.mkdir()
    waiting = "import time; print('READY', flush=True); time.sleep(30)"
    sentinel = start([sys.executable, '-I', '-S', '-B', '-c', waiting], sentinel_root)
    ready(sentinel_root, sentinel)
    results = []
    for name in ('timeout', 'interrupt', 'exit7'):
        root = output / ('G18-' + name)
        root.mkdir()
        code = 'raise SystemExit(7)' if name == 'exit7' else waiting
        process = start([sys.executable, '-I', '-S', '-B', '-c', code], root)
        if name != 'exit7':
            ready(root, process)
        if name == 'interrupt':
            armed = time.monotonic()
            signal.setitimer(signal.ITIMER_REAL, 0.1)
            try:
                process.wait(timeout=2)
                raise AssertionError('REAL_ALARM_DID_NOT_INTERRUPT')
            except KeyboardInterrupt as error:
                assert str(error) == 'SYNTHETIC_SUITE_WALL_DEADLINE'
                assert LAST_ALARM['signum'] == signal.SIGALRM
                assert 0.05 <= LAST_ALARM['monotonic'] - armed <= 2
                save(root / 'alarm.json', encoded(dict(LAST_ALARM, armed=armed, child_pid=str(process.pid), message=str(error))))
            finally:
                signal.setitimer(signal.ITIMER_REAL, 0)
        terminal = finish(process, root, timeout=0.05 if name != 'exit7' else 3)
        assert sentinel.poll() is None
        assert terminal['returncode'] == 7 if name == 'exit7' else terminal['owned_stop'] in ('TERM', 'KILL')
        results.append({'case': name, 'terminal': terminal, 'sentinel_alive': True})
    finish(sentinel, sentinel_root, timeout=0.05)
    return results


# Run only the frozen tiny suite with a real finite alarm and owned cleanup.
def run(output, prepared, bundle_path, bundle_sha):
    assert sys.flags.isolated and sys.flags.no_site and sys.flags.dont_write_bytecode and os.getuid() == 1000
    assert not any(name == 'backend' or name.startswith('backend.') for name in sys.modules)
    bundle_raw = bundle_path.read_bytes()
    assert sha(bundle_raw) == bundle_sha
    bundle = json.loads(bundle_raw)
    assert bundle['scope'] == 'SOURCE_REVIEWED_SYNTHETIC_ONLY'
    assert bundle['schema'] == 'n2-guard-source-review/3' and bundle['guard_manifest_schema'] == MANIFEST_SCHEMA
    assert bundle['generated_fingerprint'] == FINGERPRINT and bundle['source_sha256']['harness.py'] == HARNESS_SHA
    assert sha((prepared / 'prepared.json').read_bytes()) == bundle['prepared_sha256']
    rows = json.loads((prepared / 'scenarios.json').read_bytes())
    assert sha((prepared / 'scenarios.json').read_bytes()) == bundle['scenarios_sha256']
    assert len(rows) < 120 and len({row['id'] for row in rows}) == len(rows)
    output.mkdir(mode=0o700, exist_ok=False)
    signal.signal(signal.SIGALRM, alarm)
    signal.setitimer(signal.ITIMER_REAL, 60)
    results = []
    try:
        for row in rows:
            root = output / row['id']
            root.mkdir(mode=0o700)
            if row['id'] == 'G05-grow':
                prepare_growth(root, prepared)
            command = [sys.executable, '-I', '-S', '-B', '/audit/bootstrap.py', 'child', str(bundle_path), bundle_sha, row['id'], str(root)]
            process = start(command, root)
            terminal = finish(process, root)
            result = assess(row, root, terminal)
            results.append({'case': row['id'], 'terminal': terminal, 'acceptance': result})
        signal.setitimer(signal.ITIMER_REAL, 0)
        controls = cleanup_controls(output)
        summary = {'schema': 'n2-guard-synthetic-suite/3', 'guard_manifest_schema': MANIFEST_SCHEMA, 'generated_fingerprint': dict(FINGERPRINT), 'scope': 'SYNTHETIC_ONLY_NOT_GENUINE_SOURCE_OR_RUNTIME_ADMISSION',
                   'cases': results, 'cleanup': controls, 'total_children': TOTAL_CHILDREN,
                   'genuine_model_or_account_calls': False, 'combined_memory_acceptance': False,
                   'effect_generated_limit': 'FACTORY_IMPORT_REFUSAL_NOT_INSTANCE_OR_GENUINE_IMPORT_ACCEPTANCE'}
        save(output / 'suite.json', encoded(summary))
        return summary
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        cleanup()


if __name__ == '__main__':
    raise SystemExit('SOURCE_ONLY_REQUIRES_REVIEWED_BOOTSTRAP_AND_CONTROLLER')
