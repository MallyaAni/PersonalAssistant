"""Narrow actual candidate-fence tests; never a replay of the failed v2 suite.

The tiny SourceBook recipe is explicitly INJECTED, not genuine2446 admission.
CallFence construction, register/install/profile/audit and failure-slot writes
are actual unmodified candidate methods. No marshal adapter or metric patch.
"""

import ast
import base64
import dataclasses
import hashlib
import importlib
import json
import marshal
import os
import resource
import signal
import subprocess
import sys
import types
from pathlib import Path

HARNESS_SHA = '030cb5bb25f89c2785e6acbd55aceff5c99b632a5eb538079ee027362ae6178a'
PRODUCER_SHA = 'fae5bfc7d7438071094f31f42e884cb48e3709c55f364954e51c28302d3c3e30'
CONTINUATION_SHA = '14357ed7b87618ee514dd3cd4e4a71e2c27290875c3df257e692773e524cfaaf'
DAILY_SHA = '40d0d7cf482591ba28e6426ca87d23d3ed1b1cf42e31fd74a24a1287129221d9'
TINY = 'from dataclasses import dataclass\n@dataclass\nclass Sample:\n    value: int\n'
FIELDS = ('kind', 'phase', 'module', 'qualname', 'line', 'filename', 'code_sha256', 'producer_source_sha256')


# Name complete authenticated bytes without changing their representation.
def sha(raw):
    return hashlib.sha256(raw).hexdigest()


# Encode finite metadata without accepting duplicate or nonfinite external fields.
def encode(value):
    return json.dumps(value, sort_keys=True, indent=2, allow_nan=False).encode() + b'\n'


# Write one absent bounded observation and authenticate durable exact readback.
def save(path, raw):
    assert len(raw) <= 262144
    with path.open('xb') as output:
        output.write(raw)
        output.flush()
        os.fsync(output.fileno())
    assert path.read_bytes() == raw


# Preserve stable physical fields as exact decimal strings, excluding atime.
def physical(value):
    return {key: str(getattr(value, key)) for key in ('st_dev', 'st_ino', 'st_mode', 'st_uid', 'st_nlink', 'st_size', 'st_blocks', 'st_mtime_ns', 'st_ctime_ns')}


# Authenticate every tiny prepared file with held-FD/path physical bookends.
def prepared_files(root):
    result = {}
    for path in sorted(root.rglob('*')):
        assert not path.is_symlink() and path.resolve(strict=True) == path
        if path.is_dir():
            continue
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        try:
            before = os.fstat(descriptor)
            assert before.st_uid == 1000 and before.st_nlink == 1 and 0 <= before.st_size <= 262144
            raw = os.read(descriptor, 262145)
            assert len(raw) == before.st_size
            assert physical(before) == physical(os.fstat(descriptor)) == physical(path.stat(follow_symlinks=False))
        finally:
            os.close(descriptor)
        result[str(path.relative_to(root))] = {'sha256': sha(raw), 'bytes': len(raw), 'physical': physical(before)}
    assert len(result) == 8
    return result


# Load only the exact new candidate in a non-backend module namespace.
def harness():
    path = Path('/audit/harness-source.txt')
    raw = path.read_bytes()
    assert len(raw) == 31002 and sha(raw) == HARNESS_SHA
    module = types.ModuleType('tiny_actual_candidate_harness')
    module.__file__ = str(path)
    sys.modules[module.__name__] = module
    exec(compile(raw, str(path), 'exec', dont_inherit=True, optimize=0), module.__dict__)
    return module


# Enumerate exact compiled code identities without running their bodies.
def codes(code):
    pending, result = [code], []
    while pending:
        item = pending.pop()
        result.append(item)
        assert len(result) <= 20000
        pending.extend(value for value in item.co_consts if isinstance(value, types.CodeType))
    return result


# Freeze explicit format-2 records while keeping all eight original bindings.
def generated(code, module, producer, kind, phase='BOOTSTRAP'):
    return {'kind': kind, 'phase': phase, 'module': module, 'qualname': code.co_qualname,
            'line': code.co_firstlineno, 'filename': code.co_filename,
            'code_sha256': sha(marshal.dumps(code, 2)), 'producer_source_sha256': producer}


# Retain tiny stdlib factory CodeTypes without creating financial objects.
def dataclass_codes(name):
    retained = {}
    # Retain generated call identities before independent deferred fingerprinting.
    def capture(frame, event, argument):
        code = frame.f_code
        if event == 'call' and code.co_filename == '<string>' and frame.f_globals.get('__name__') == name:
            assert code.co_qualname == '<module>' or code.co_qualname.startswith('__create_fn__')
            retained[sha(marshal.dumps(code, 2))] = code
    module = types.ModuleType(name)
    assert name not in sys.modules and sys.getprofile() is None
    sys.modules[name] = module
    try:
        sys.setprofile(capture)
        exec(compile(TINY, '/prepared/' + name.replace('.', '/') + '.py', 'exec', dont_inherit=True), module.__dict__)
        sys.setprofile(None)
        retained[sha(marshal.dumps(module.Sample.__init__.__code__, 2))] = module.Sample.__init__.__code__
    finally:
        sys.setprofile(None)
        del sys.modules[name]
    assert len(retained) == 7
    return list(retained.values())


# Compile only the authenticated original inputs-function prefix, never its module.
def daily_code():
    raw = Path('/audit/continuation-source.txt').read_bytes()
    assert sha(raw) == CONTINUATION_SHA
    node = next(item for item in ast.parse(raw).body if isinstance(item, ast.FunctionDef) and item.name == 'inputs')
    source = ast.get_source_segment(raw.decode(), node) + '\n'
    assert sha(source.encode()) == DAILY_SHA
    tree = ast.parse(source)
    function = tree.body[0]
    stop = [index for index, item in enumerate(function.body) if isinstance(item, ast.Assign) and any(isinstance(target, ast.Name) and target.id == 'shape' for target in item.targets)]
    assert len(stop) == 1
    function.body = function.body[:stop[0]] + [ast.Return(ast.Tuple([ast.Name(name, ast.Load()) for name in ('panel', 'grades', 'eligible', 'factors', 'actions', 'sources')], ast.Load()))]
    return compile(ast.fix_missing_locations(tree), '<pinned daily prefix>', 'exec', dont_inherit=True, optimize=0)


# Declare each narrow new acceptance path and its exact first expected boundary.
def scenarios():
    rows = [{'id': 'dataclass-positive', 'exit': 0, 'marker': 'dataclass'},
            {'id': 'broker-effect', 'exit': 86, 'reason': 'BROKER_OR_ACCOUNT_FUNCTION', 'identity': 'backend.market.replay_broker.__create_fn__'}]
    for field in FIELDS:
        reason = 'EXACT_DAILY_PREFIX_RECORD_REQUIRED' if field == 'kind' else 'EXACT_DATACLASS_FILENAME_REQUIRED' if field == 'filename' else 'UNREVIEWED_GENERATED_CODE'
        rows.append({'id': 'binding-' + field, 'exit': 1 if field in ('kind', 'filename') else 86, 'reason': reason,
                     **({} if field in ('kind', 'filename') else {'identity': 'backend.capacity_dataclass.<module>'})})
    for label in ('changed-bytecode', 'changed-constant'):
        rows.append({'id': label, 'exit': 86, 'reason': 'UNREVIEWED_GENERATED_CODE', 'identity': 'backend.capacity_dataclass.<module>'})
    rows.append({'id': 'prefix-positive', 'exit': 0, 'marker': 'prefix'})
    for label in ('wrapper', 'inputs', 'producer', 'phase'):
        rows.append({'id': 'prefix-' + label, 'exit': 86,
                     'reason': 'UNREGISTERED_OR_GENERATED_CODE' if label == 'phase' else 'UNREVIEWED_GENERATED_CODE',
                     'identity': 'backend.cli.market_strategy_continue.' + ('inputs' if label == 'inputs' else '<module>')})
    for label, reason in (('schema-old', 'CALL_MANIFEST_BINDING_DIFFERS'), ('schema-missing-fingerprint', 'EXACT_CALL_MANIFEST_REQUIRED'),
                          ('algorithm', 'GENERATED_FINGERPRINT_BINDING_DIFFERS'), ('version', 'GENERATED_FINGERPRINT_BINDING_DIFFERS'),
                          ('bool-version', 'GENERATED_FINGERPRINT_BINDING_DIFFERS')):
        rows.append({'id': label, 'exit': 1, 'reason': reason})
    assert len(rows) == 22
    return rows


# Build only tiny source, a separately versioned manifest and inert compiler inputs.
def prepare(root):
    h = harness()
    target = root / 'prepared'
    target.mkdir(mode=0o700)
    source = target / 'source'
    source.mkdir(mode=0o700)
    producer = Path('/audit/producer-source.txt').read_bytes()
    assert sha(producer) == PRODUCER_SHA
    bodies = {'backend/__init__.py': b'', 'backend/cli/__init__.py': b'', 'backend/market/__init__.py': b'',
              'backend/capacity_dataclass.py': TINY.encode(), 'backend/market/replay_broker.py': TINY.encode(),
              'backend/market/live_model_history_audit_inputs.py': producer}
    pins, calls = {}, {phase: [] for phase in h.PHASES}
    for name, raw in bodies.items():
        path = source / name
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        save(path, raw)
        pins[name] = sha(raw)
        if name.endswith('live_model_history_audit_inputs.py'):
            continue
        for code in codes(compile(raw, str(path), 'exec', dont_inherit=True, optimize=0)):
            calls['BOOTSTRAP'].append([name, code.co_qualname, code.co_firstlineno])
    dataclass_sha = sha(Path(dataclasses.__file__).read_bytes())
    ordinary = dataclass_codes('backend.capacity_dataclass')
    rows = [generated(code, 'backend.capacity_dataclass', dataclass_sha, 'stdlib-dataclass-exact-native-code') for code in ordinary]
    rows.extend(generated(code, 'backend.market.replay_broker', dataclass_sha, 'stdlib-dataclass-exact-native-code') for code in dataclass_codes('backend.market.replay_broker'))
    rows.extend(generated(code, 'backend.cli.market_strategy_continue', PRODUCER_SHA, 'exact-original-daily-prefix-transformation-40d0d7cf', 'LOAD') for code in codes(daily_code()) if code.co_qualname in ('<module>', 'inputs'))
    assert len(rows) == 16
    manifest = {'schema': 'n2-capacity-call-manifest/2', 'recipe_sha256': h.RECIPE_SHA256, 'contract_sha256': h.CONTRACT_SHA256,
                'fingerprint': {'algorithm': h.GENERATED_FINGERPRINT_ALGORITHM, 'marshal_version': 2}, 'calls': calls, 'generated': rows}
    raw = encode(manifest)
    save(target / 'calls.json', raw)
    save(target / 'summary.json', encode({'scope': 'INJECTED_TINY_RECIPE_NOT_GENUINE2446', 'pins': pins, 'calls_sha256': sha(raw),
         'first_wrapper_base64': base64.b64encode(marshal.dumps(ordinary[0], 2)).decode(), 'python': sys.version,
         'dataclasses_source_sha256': dataclass_sha, 'harness_sha256': HARNESS_SHA, 'scenario_ids': [row['id'] for row in scenarios()]}))


# Stop the exact original prefix at its first non-backend dependency before data.
def dependency_stop(*arguments, **keywords):
    save(Path(os.environ['TINY_CASE']) / 'prefix.marker', b'FIRST_DEPENDENCY_BEFORE_DATA')
    raise LookupError('TINY_PREFIX_FIRST_DEPENDENCY_STOP')


# Exercise real candidate constructor/profile/slot methods over the injected recipe.
def child(label, target):
    h = harness()
    root = target.parent.parent / 'prepare/prepared'
    summary = h.metadata((root / 'summary.json').read_bytes())
    raw = (root / 'calls.json').read_bytes()
    assert sha(raw) == summary['calls_sha256']
    manifest = h.metadata(raw)
    if label.startswith('binding-'):
        field = label[len('binding-'):]
        first = manifest['generated'][0]
        first[field] = first[field] + 1 if field == 'line' else '0' * 64 if field.endswith('sha256') else 'ADMISSION' if field == 'phase' else 'backend.wrong' if field == 'module' else 'wrong'
    if label.startswith('prefix-') and label not in ('prefix-positive', 'prefix-phase'):
        variant = label[len('prefix-'):]
        if variant in ('wrapper', 'inputs'):
            name = '<module>' if variant == 'wrapper' else 'inputs'
            manifest['generated'] = [item for item in manifest['generated'] if not (item['module'] == 'backend.cli.market_strategy_continue' and item['qualname'] == name)]
        else:
            for item in manifest['generated']:
                if item['module'] == 'backend.cli.market_strategy_continue':
                    item['producer_source_sha256'] = '0' * 64
    if label == 'schema-old':
        manifest['schema'] = 'n2-capacity-call-manifest/1'
    elif label == 'schema-missing-fingerprint':
        del manifest['fingerprint']
    elif label == 'algorithm':
        manifest['fingerprint']['algorithm'] = 'implicit-default-marshal'
    elif label in ('version', 'bool-version'):
        manifest['fingerprint']['marshal_version'] = True if label == 'bool-version' else 4
    book = object.__new__(h.SourceBook)
    book.root, book.fd, book.pins = str(root / 'source'), h.directory_fd(str(root / 'source')), dict(summary['pins'])
    book.bookends, book.authenticated = {}, False
    book.authenticate_all()
    fd = os.open(target / 'failure.bin', os.O_RDWR | os.O_NOFOLLOW)
    manifest_raw = encode(manifest)
    save(target / 'manifest.json', manifest_raw)
    try:
        fence = h.CallFence(book, manifest_raw, sha(manifest_raw), fd)
    except RuntimeError as error:
        save(target / 'constructor-refusal.json', encode({'reason': str(error), 'backend_modules': [name for name in sys.modules if name == 'backend' or name.startswith('backend.')]}))
        return 1
    finder = h.PinnedBackendFinder(book, fence)
    sys.meta_path.insert(0, finder)
    os.environ['TINY_CASE'] = str(target)
    fence.install()
    if label.startswith('prefix-'):
        if label != 'prefix-phase':
            for phase in ('ADMISSION', 'BEFORE', 'LOAD'):
                fence.advance(phase)
        namespace = {'__name__': 'backend.cli.market_strategy_continue', 'MarketStore': dependency_stop}
        exec(daily_code(), namespace)
        try:
            namespace['inputs']('/synthetic-never-read', None, None)
        except LookupError as error:
            assert str(error) == 'TINY_PREFIX_FIRST_DEPENDENCY_STOP'
    elif label in ('changed-bytecode', 'changed-constant'):
        code = marshal.loads(base64.b64decode(summary['first_wrapper_base64'], validate=True))
        assert isinstance(code, types.CodeType) and code.co_qualname == '<module>'
        if label == 'changed-bytecode':
            changed = code.replace(co_code=code.co_code + bytes((9, 0)))
            assert changed.co_code != code.co_code
        else:
            constants = list(code.co_consts)
            assert len(constants) == 2 and isinstance(constants[0], types.CodeType) and constants[1] is None
            nested = constants[0]
            assert nested.co_qualname == '__create_fn__' and nested.co_consts[1] == 'value'
            values = list(nested.co_consts)
            values[1] = 'changed-value-constant'
            constants[0] = nested.replace(co_consts=tuple(values))
            changed = code.replace(co_consts=tuple(constants))
        assert sha(marshal.dumps(changed, 2)) != manifest['generated'][0]['code_sha256']
        types.FunctionType(changed, {'__name__': 'backend.capacity_dataclass'})()
    else:
        module = importlib.import_module('backend.market.replay_broker' if label == 'broker-effect' else 'backend.capacity_dataclass')
        assert module.Sample(3).value == 3
        save(target / 'dataclass.marker', b'TINY_SAMPLE_VALUE_3')
    save(target / 'returned.json', encode({'phase': fence.phase, 'injected_recipe': True, 'actual_candidate_constructor_profile_audit': True,
         'marshal_adapter': False, 'genuine_admission': False, 'seen': sorted([list(item) for item in fence.seen])}))
    return 0


# Bound every fresh child without changing the guard's limits or physical metrics.
def limits():
    resource.setrlimit(resource.RLIMIT_CPU, (5, 5))
    resource.setrlimit(resource.RLIMIT_FSIZE, (262144, 262144))


# Interrupt the bounded suite while allowing registered-child cleanup.
def alarm(signum, frame):
    raise KeyboardInterrupt('V3_TINY_WALL_DEADLINE')


# Run one exact child with fsynced logs and a retained bounded reaping receipt.
def run_child(arguments, target):
    stdout, stderr = (target / 'stdout.log').open('xb'), (target / 'stderr.log').open('xb')
    process, stopped = None, None
    try:
        prior = signal.pthread_sigmask(signal.SIG_BLOCK, {signal.SIGALRM})
        try:
            process = subprocess.Popen([sys.executable, '-I', '-S', '-B', __file__, *arguments], stdin=subprocess.DEVNULL, stdout=stdout, stderr=stderr, preexec_fn=limits)
        finally:
            signal.pthread_sigmask(signal.SIG_SETMASK, prior)
        process.wait(timeout=7)
    finally:
        if process is not None and process.poll() is None:
            stopped = 'TERM'
            process.terminate()
            try:
                process.wait(timeout=1)
            except subprocess.TimeoutExpired:
                stopped = 'KILL'
                process.kill()
                process.wait(timeout=1)
        for stream in (stdout, stderr):
            stream.flush()
            os.fsync(stream.fileno())
            stream.close()
        result = {'pid': None if process is None else str(process.pid), 'exit': None if process is None else process.returncode, 'owned_stop': stopped}
        save(target / 'terminal.json', encode(result))
    assert process is not None and stopped is None
    assert (target / 'stdout.log').read_bytes() == (target / 'stderr.log').read_bytes() == b''
    return result


# Exercise only new narrow cases and independently check durable slot contents.
def diagnose():
    root = Path('/out')
    assert os.getuid() == 1000 and list(root.iterdir()) == []
    signal.signal(signal.SIGALRM, alarm)
    signal.setitimer(signal.ITIMER_REAL, 60)
    try:
        preparation = root / 'prepare'
        preparation.mkdir(mode=0o700)
        assert run_child(['prepare', str(preparation)], preparation)['exit'] == 0
        prepared = prepared_files(preparation / 'prepared')
        save(root / 'prepared-before.json', encode(prepared))
        case_root = root / 'cases'
        case_root.mkdir(mode=0o700)
        outcomes = []
        for row in scenarios():
            target = case_root / row['id']
            target.mkdir(mode=0o700)
            fd = os.open(target / 'failure.bin', os.O_CREAT | os.O_EXCL | os.O_RDWR, 0o600)
            try:
                os.posix_fallocate(fd, 0, 65536)
                os.fsync(fd)
                before = physical(os.fstat(fd))
                assert os.pread(fd, 65536, 0) == bytes(65536)
            finally:
                os.close(fd)
            save(target / 'slot-before.json', encode(before))
            actual = run_child(['child', row['id'], str(target)], target)
            assert actual['exit'] == row['exit']
            body = (target / 'failure.bin').read_bytes()
            after = physical((target / 'failure.bin').stat(follow_symlinks=False))
            assert all(before[key] == after[key] for key in before if key not in ('st_mtime_ns', 'st_ctime_ns'))
            assert len(body) == 65536 and int(after['st_blocks']) * 512 >= 65536
            if row['exit'] == 86:
                raw = body.rstrip(b'\x00')
                observed = json.loads(raw)
                assert body == raw + bytes(65536 - len(raw))
                assert observed == {'status': 'FAILED_CLOSED', 'phase': 'LOAD' if row['id'].startswith('prefix-') and row['id'] != 'prefix-phase' else 'BOOTSTRAP', 'reason': row['reason'], 'identity': row['identity'], 'publication': 'CLOSED'}
                assert not (target / 'returned.json').exists()
            else:
                assert body == bytes(65536)
                if row['exit'] == 1:
                    assert json.loads((target / 'constructor-refusal.json').read_bytes()) == {'reason': row['reason'], 'backend_modules': []}
                else:
                    assert (target / (row['marker'] + '.marker')).exists() and (target / 'returned.json').exists()
            if row['id'] != 'prefix-positive':
                assert not (target / 'prefix.marker').exists()
            if row['id'] != 'dataclass-positive':
                assert not (target / 'dataclass.marker').exists()
            outcomes.append({'id': row['id'], 'exit': actual['exit'], 'pid': actual['pid'], 'slot_sha256': sha(body), 'slot_after': after})
        after_prepared = prepared_files(preparation / 'prepared')
        assert after_prepared == prepared
        save(root / 'prepared-after.json', encode(after_prepared))
        save(root / 'comparison.json', encode({'status': 'V3_TINY_ACTUAL_FENCE_COMPLETE', 'cases': outcomes, 'case_count': 22,
             'candidate_harness_sha256': HARNESS_SHA, 'marshal_adapter': False, 'injected_recipe_not_genuine2446': True,
             'genuine_or_full_guard_suite_acceptance': False}))
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)


# Require explicit finite routes and refuse ordinary source invocation.
def main(arguments):
    if arguments == ['diagnose']:
        diagnose()
        return 0
    if len(arguments) == 2 and arguments[0] == 'prepare':
        prepare(Path(arguments[1]))
        return 0
    if len(arguments) == 3 and arguments[0] == 'child':
        return child(arguments[1], Path(arguments[2]))
    raise SystemExit('SOURCE_ONLY_NO_V3_TINY_ADMISSION')


if __name__ == '__main__':
    raise SystemExit(main(sys.argv[1:]))
