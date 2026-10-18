"""Tiny candidate experiment; this does not change or admit the capacity guard.

The unchanged pinned profile CodeType receives an explicitly INJECTED marshal
format-2 adapter after a separate versioned candidate manifest is validated.
No application module is imported and no Sample is instantiated.
"""

import ast
import base64
import dataclasses
import hashlib
import json
import marshal
import os
import resource
import signal
import subprocess
import sys
import types
from pathlib import Path

TINY = 'from dataclasses import dataclass\n@dataclass\nclass Sample:\n    value: int\n'
TINY_SHA = '1247f21782dae095b2028e24d8c8039cb47440ebe7470a4c9cb7c32758a776da'
HARNESS_SHA = '737d4236345ebfbc90a0ecf33e3e9ce733e5f06afb2e53c3125e465e9b1a2eea'
MODULE = 'backend.market.replay_broker'
ALGORITHM = 'cpython-code-marshal-format-2-sha256/1'
SCHEMA = 'tiny-generated-code-format2-candidate/1'
FIELDS = {'kind', 'phase', 'module', 'qualname', 'line', 'filename', 'code_sha256', 'producer_source_sha256'}


# Name complete bytes without another serialization step.
def sha(raw):
    return hashlib.sha256(raw).hexdigest()


# Persist one exclusive bounded result with durable exact readback.
def save(path, value):
    raw = json.dumps(value, sort_keys=True, indent=2, allow_nan=False).encode() + b'\n'
    assert len(raw) <= 262144
    with path.open('xb') as output:
        output.write(raw)
        output.flush()
        os.fsync(output.fileno())
    assert path.read_bytes() == raw


# Bind all eight generated-record fields to the explicitly selected serializer.
def record(code, module, producer):
    return {'kind': 'stdlib-dataclass-exact-native-code', 'phase': 'BOOTSTRAP',
            'module': module, 'qualname': code.co_qualname, 'line': code.co_firstlineno,
            'filename': code.co_filename, 'code_sha256': sha(marshal.dumps(code, 2)),
            'producer_source_sha256': producer}


# Capture tiny generated CodeTypes in original namespace order without instances.
def capture(module_name):
    captured = {}
    # Retain call-time fingerprints and CodeTypes before deferred format-2 hashing.
    def observe(frame, event, argument):
        code = frame.f_code
        if event == 'call' and code.co_filename == '<string>' and frame.f_globals.get('__name__') == module_name:
            assert code.co_qualname == '<module>' or code.co_qualname.startswith('__create_fn__')
            captured[sha(marshal.dumps(code, 2))] = code
    module = types.ModuleType(module_name)
    assert module_name not in sys.modules and sys.getprofile() is None
    sys.modules[module_name] = module
    try:
        sys.setprofile(observe)
        exec(compile(TINY, '/app/' + module_name.replace('.', '/') + '.py', 'exec', dont_inherit=True), module.__dict__)
        sys.setprofile(None)
        captured[sha(marshal.dumps(module.Sample.__init__.__code__, 2))] = module.Sample.__init__.__code__
    finally:
        sys.setprofile(None)
        del sys.modules[module_name]
    return list(captured.values())


# Refuse old schemas or implicit serializer semantics before adapting any rows.
def candidate(value):
    assert set(value) == {'schema', 'fingerprint_algorithm', 'marshal_version', 'python', 'producer_source_sha256', 'tiny_source_sha256', 'generated'}
    assert value['schema'] == SCHEMA and value['fingerprint_algorithm'] == ALGORITHM
    assert type(value['marshal_version']) is int and value['marshal_version'] == 2
    assert value['python'] == sys.version and value['tiny_source_sha256'] == TINY_SHA
    assert value['producer_source_sha256'] == sha(Path(dataclasses.__file__).read_bytes())
    assert len(value['generated']) == 7
    for item in value['generated']:
        assert set(item) == FIELDS and type(item['line']) is int
        assert all(type(item[key]) is str for key in FIELDS - {'line'})
    return value['generated']


# Extract the original full-compilation profile without executing its module code.
def profile_code():
    raw = Path('/audit/harness-source.txt').read_bytes()
    assert len(raw) == 30408 and sha(raw) == HARNESS_SHA
    constants = {}
    for node in ast.parse(raw).body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            name = node.targets[0].id
            if name == 'FORBIDDEN_NAMES':
                assert isinstance(node.value, ast.Call) and isinstance(node.value.func, ast.Name) and node.value.func.id == 'frozenset' and len(node.value.args) == 1 and not node.value.keywords
                constants[name] = frozenset(ast.literal_eval(node.value.args[0]))
            elif name in ('EFFECT_MODULES', 'FORBIDDEN_CLASSES'):
                constants[name] = ast.literal_eval(node.value)
    assert set(constants) == {'FORBIDDEN_NAMES', 'EFFECT_MODULES', 'FORBIDDEN_CLASSES'}
    compiled = compile(raw, '/audit/harness.py', 'exec', dont_inherit=True, optimize=0)
    classes = [code for code in compiled.co_consts if isinstance(code, types.CodeType) and code.co_name == 'CallFence']
    assert len(classes) == 1
    profiles = [code for code in classes[0].co_consts if isinstance(code, types.CodeType) and code.co_name == 'profile']
    assert len(profiles) == 1
    return profiles[0], constants


# Stop the synthetic import at the original profile's first refusal.
class Refused(Exception):
    pass


# Exercise exact profile membership with an explicitly injected format-2 adapter.
def live(rows, producer, replacement=None):
    code, constants = profile_code()
    hashes, refusals = [], []
    # Return only explicit format-2 bytes and retain the actual adapter input/output.
    def dumps(value):
        raw = marshal.dumps(value, 2)
        hashes.append({'record': record(value, MODULE, producer), 'raw_base64': base64.b64encode(raw).decode()})
        assert hashes[-1]['record']['code_sha256'] == sha(raw)
        return raw
    namespace = {'__builtins__': __builtins__, 'sys': sys, 'hashlib': hashlib,
                 'marshal': types.SimpleNamespace(dumps=dumps), **constants}
    profile = types.FunctionType(code, namespace)
    source = compile(TINY, '/prepared/source/backend/market/replay_broker.py', 'exec', dont_inherit=True, optimize=0)
    registry, pending = {}, [source]
    while pending:
        item = pending.pop()
        registry[id(item)] = (item, 'backend/market/replay_broker.py', item.co_qualname, item.co_firstlineno)
        pending.extend(child for child in item.co_consts if isinstance(child, types.CodeType))
    calls = [[item[1], item[2], item[3]] for item in registry.values()]
    # Retain original reason and identity, then prevent the refused body executing.
    def trip(reason, identity=''):
        refusals.append({'reason': reason, 'identity': identity})
        raise Refused('TINY_CANDIDATE_FIRST_REFUSAL')
    fence = types.SimpleNamespace(active=True, installing=False, phase='BOOTSTRAP', codes=registry,
                                  seen=set(), manifest={'calls': {'BOOTSTRAP': calls}, 'generated': rows},
                                  book=types.SimpleNamespace(root='/prepared/source'), dataclass_source=producer, trip=trip)
    module = types.ModuleType(MODULE)
    assert MODULE not in sys.modules and sys.getprofile() is None
    sys.modules[MODULE] = module
    try:
        sys.setprofile(types.MethodType(profile, fence))
        try:
            if replacement is None:
                exec(source, module.__dict__)
            else:
                types.FunctionType(replacement, module.__dict__)()
        except Refused as error:
            assert str(error) == 'TINY_CANDIDATE_FIRST_REFUSAL'
        else:
            raise AssertionError('EXPECTED_REFUSAL_ABSENT')
    finally:
        fence.active = False
        sys.setprofile(None)
        del sys.modules[MODULE]
    assert len(refusals) == 1 and len(hashes) == 1
    return {'refusal': refusals[0], 'hash_observations': hashes, 'registered_calls_seen': len(fence.seen)}


# Prepare the separate candidate or test its equality and refusal controls.
def probe(mode, target):
    assert sha(TINY.encode()) == TINY_SHA
    assert not any(name == 'backend' or name.startswith('backend.') for name in sys.modules)
    producer = sha(Path(dataclasses.__file__).read_bytes())
    if mode == 'prepare':
        warm = capture('backend.capacity_dataclass')
        warm_rows = [record(code, 'backend.capacity_dataclass', producer) for code in warm]
        del warm
        codes = capture(MODULE)
        rows = [record(code, MODULE, producer) for code in codes]
        manifest = {'schema': SCHEMA, 'fingerprint_algorithm': ALGORITHM, 'marshal_version': 2,
                    'python': sys.version, 'producer_source_sha256': producer, 'tiny_source_sha256': TINY_SHA, 'generated': rows}
        assert candidate(manifest) == rows and warm_rows
        save(target / 'observation.json', {'candidate_manifest': manifest, 'warmup_rows': warm_rows,
             'first_wrapper_raw_base64': base64.b64encode(marshal.dumps(codes[0], 2)).decode(),
             'first_wrapper_is_module': codes[0].co_qualname == '<module>'})
        return
    assert mode == 'controls'
    manifest = json.loads((target.parent / 'prepare/observation.json').read_bytes())['candidate_manifest']
    rows = candidate(manifest)
    results = [{'case': 'positive-format2', 'actual': live(rows, producer)}]
    assert results[0]['actual']['refusal'] == {'reason': 'BROKER_OR_ACCOUNT_FUNCTION', 'identity': MODULE + '.__create_fn__'}
    assert results[0]['actual']['hash_observations'][0]['record'] == rows[0]
    for field in sorted(FIELDS):
        changed = [dict(item) for item in rows]
        changed[0][field] = changed[0][field] + 1 if field == 'line' else changed[0][field] + '-wrong'
        observed = live(changed, producer)
        assert observed['refusal'] == {'reason': 'UNREVIEWED_GENERATED_CODE', 'identity': MODULE + '.<module>'}
        assert observed['hash_observations'][0]['record'] == rows[0]
        results.append({'case': 'wrong-' + field, 'actual': observed})
    raw = base64.b64decode(json.loads((target.parent / 'prepare/observation.json').read_bytes())['first_wrapper_raw_base64'], validate=True)
    original = marshal.loads(raw)
    assert isinstance(original, types.CodeType) and original.co_qualname == '<module>' and sha(raw) == rows[0]['code_sha256']
    changed_code = original.replace(co_code=original.co_code + bytes((9, 0)))
    assert changed_code.co_code != original.co_code
    constants = list(original.co_consts)
    assert len(constants) == 2 and isinstance(constants[0], types.CodeType) and constants[1] is None
    nested = constants[0]
    assert nested.co_qualname == '__create_fn__' and nested.co_consts[1] == 'value'
    nested_constants = list(nested.co_consts)
    nested_constants[1] = 'changed-value-constant'
    constants[0] = nested.replace(co_consts=tuple(nested_constants))
    changed_constant = original.replace(co_consts=tuple(constants))
    for label, changed in (('changed-bytecode', changed_code), ('changed-constant', changed_constant)):
        assert record(changed, MODULE, producer)['code_sha256'] != rows[0]['code_sha256']
        observed = live(rows, producer, changed)
        assert observed['refusal'] == {'reason': 'UNREVIEWED_GENERATED_CODE', 'identity': MODULE + '.<module>'}
        results.append({'case': label, 'actual': observed})
    schema_results = []
    for field, value in (('schema', 'n2-capacity-call-manifest/1'), ('fingerprint_algorithm', 'implicit-default-marshal'), ('marshal_version', 4), ('marshal_version', True)):
        changed = dict(manifest)
        changed[field] = value
        try:
            candidate(changed)
        except AssertionError:
            schema_results.append({'field': field, 'value': value, 'rejected_before_live': True})
        else:
            raise AssertionError('VERSION_CONTROL_ACCEPTED')
    save(target / 'observation.json', {'cases': results, 'schema_controls': schema_results,
         'scope': 'INJECTED_FORMAT2_ADAPTER_NOT_FULL_GUARD_ACCEPTANCE', 'python': sys.version,
         'guard_modified': False, 'original_failure_hash_recovered': False, 'Sample_instances': 0})


# Cap each fresh child CPU and individual output files.
def limits():
    resource.setrlimit(resource.RLIMIT_CPU, (5, 5))
    resource.setrlimit(resource.RLIMIT_FSIZE, (262144, 262144))


# Interrupt the finite parent while retaining owned-child cleanup.
def alarm(signum, frame):
    raise KeyboardInterrupt('FORMAT2_HYPOTHESIS_WALL_DEADLINE')


# Run two fresh children and require exact bytes and all proposed controls.
def diagnose():
    root = Path('/out')
    assert os.getuid() == 1000 and list(root.iterdir()) == []
    signal.signal(signal.SIGALRM, alarm)
    signal.setitimer(signal.ITIMER_REAL, 20)
    try:
        for mode in ('prepare', 'controls'):
            target = root / mode
            target.mkdir(mode=0o700)
            stdout, stderr = (target / 'stdout.log').open('xb'), (target / 'stderr.log').open('xb')
            process, stopped = None, None
            try:
                prior = signal.pthread_sigmask(signal.SIG_BLOCK, {signal.SIGALRM})
                try:
                    process = subprocess.Popen([sys.executable, '-I', '-S', '-B', __file__, 'probe', mode, str(target)], stdin=subprocess.DEVNULL, stdout=stdout, stderr=stderr, preexec_fn=limits)
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
                for output in (stdout, stderr):
                    output.flush()
                    os.fsync(output.fileno())
                    output.close()
                save(target / 'terminal.json', {'pid': None if process is None else str(process.pid), 'exit': None if process is None else process.returncode, 'owned_stop': stopped})
            assert process.returncode == 0 and stopped is None
            assert (target / 'stdout.log').read_bytes() == (target / 'stderr.log').read_bytes() == b''
        prepared = json.loads((root / 'prepare/observation.json').read_bytes())
        controls = json.loads((root / 'controls/observation.json').read_bytes())
        raw = prepared['first_wrapper_raw_base64']
        assert prepared['first_wrapper_is_module'] is True
        assert len(controls['cases']) == 11 and len(controls['schema_controls']) == 4
        assert controls['cases'][0]['actual']['hash_observations'][0]['raw_base64'] == raw
        save(root / 'comparison.json', {'status': 'FORMAT2_HYPOTHESIS_CONTROLS_COMPLETE', 'candidate_schema': SCHEMA,
             'fingerprint_algorithm': ALGORITHM, 'marshal_version': 2, 'first_wrapper_raw_bytes_equal': True,
             'profile_cases': 11, 'version_controls': 4, 'genuine_or_guard_suite_acceptance': False})
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)


# Refuse ordinary execution and expose only explicit tiny experimental routes.
def main(arguments):
    if arguments == ['diagnose']:
        diagnose()
    elif len(arguments) == 3 and arguments[0] == 'probe':
        probe(arguments[1], Path(arguments[2]))
    else:
        raise SystemExit('SOURCE_ONLY_NO_FORMAT2_ADMISSION')


if __name__ == '__main__':
    main(sys.argv[1:])
