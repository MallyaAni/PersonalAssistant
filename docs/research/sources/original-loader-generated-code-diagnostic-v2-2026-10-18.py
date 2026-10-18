"""SOURCE ONLY: tiny dataclass fingerprint comparison, never a guard-suite replay.

The two proposed fresh children execute only the frozen 74-byte dataclass
declaration in synthetic module namespaces. They never instantiate Sample or
import a backend, fixture, harness, model, account or numerical package.
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
import struct
import subprocess
import sys
import types
from pathlib import Path

FROZEN_SHA = 'c8f28b55394b0ef64442f95f021a965dd6ebf1c9b25080f4fcc055a18446fc1e'
TINY_SHA = '1247f21782dae095b2028e24d8c8039cb47440ebe7470a4c9cb7c32758a776da'
DATACLASS = 'from dataclasses import dataclass\n@dataclass\nclass Sample:\n    value: int\n'
MODULE = 'backend.market.replay_broker'
KIND = 'stdlib-dataclass-exact-native-code'
HARNESS_SHA = '737d4236345ebfbc90a0ecf33e3e9ce733e5f06afb2e53c3125e465e9b1a2eea'
SELF = Path(__file__)


# Name complete input, code or output bytes without reserializing them first.
def sha(raw):
    return hashlib.sha256(raw).hexdigest()


# Write one exclusive bounded observation and verify durable exact readback.
def save(path, value):
    raw = json.dumps(value, sort_keys=True, indent=2, allow_nan=False).encode() + b'\n'
    assert len(raw) <= 262144
    with path.open('xb') as output:
        output.write(raw)
        output.flush()
        os.fsync(output.fileno())
    assert path.read_bytes() == raw


# Retain typed CodeType content only after the first relevant marshal operation.
def content(code):
    budget = [0]
    # Describe constants without calling their repr or treating unlike types alike.
    def constant(value, depth):
        budget[0] += 1
        assert budget[0] <= 10000 and depth <= 10
        kind = type(value)
        if value is None or value is Ellipsis:
            return {'type': 'None' if value is None else 'Ellipsis'}
        if kind in (bool, int, str):
            assert kind is not str or len(value) <= 4096
            return {'type': kind.__name__, 'value': value}
        if kind is bytes:
            assert len(value) <= 65536
            return {'type': 'bytes', 'hex': value.hex()}
        if kind is float:
            return {'type': 'float64-bits', 'hex': struct.pack('>d', value).hex()}
        if kind is complex:
            return {'type': 'complex128-bits', 'hex': struct.pack('>dd', value.real, value.imag).hex()}
        if kind is tuple:
            assert len(value) <= 1024
            return {'type': 'tuple', 'items': [constant(item, depth + 1) for item in value]}
        assert kind is types.CodeType
        return code_fields(value, depth + 1)

    # Record every marshalled CodeType field explicitly, preserving bytes and tuples.
    def code_fields(value, depth):
        numeric = ('co_argcount', 'co_posonlyargcount', 'co_kwonlyargcount', 'co_nlocals', 'co_stacksize', 'co_flags', 'co_firstlineno')
        fields = ('co_code', 'co_consts', 'co_names', 'co_varnames', 'co_filename', 'co_name', 'co_qualname', 'co_linetable', 'co_exceptiontable', 'co_freevars', 'co_cellvars')
        return {'type': 'code', 'integers': {key: getattr(value, key) for key in numeric}, 'fields': {key: constant(getattr(value, key), depth + 1) for key in fields}}

    return code_fields(code, 0)


# Build the guard's six preceding record fields before hashing, with metadata later.
def record(code, module, producer):
    row = {'kind': KIND, 'phase': 'BOOTSTRAP', 'module': module, 'qualname': code.co_qualname,
           'line': code.co_firstlineno, 'filename': code.co_filename}
    raw = marshal.dumps(code)
    row['code_sha256'] = sha(raw)
    row['producer_source_sha256'] = producer
    return row, raw


# Mirror original preparation's capture and retention before later record hashing.
def deferred_codes(module_name):
    captured = {}
    # Keep original call-time key hashing and code retention, without extra metadata.
    def capture(frame, event, argument):
        code = frame.f_code
        if event == 'call' and code.co_filename == '<string>' and frame.f_globals.get('__name__') == module_name:
            assert code.co_qualname == '<module>' or code.co_qualname.startswith('__create_fn__')
            captured[sha(marshal.dumps(code))] = code
    module = types.ModuleType(module_name)
    assert module_name not in sys.modules and sys.getprofile() is None
    sys.modules[module_name] = module
    try:
        sys.setprofile(capture)
        exec(compile(DATACLASS, '/app/' + module_name.replace('.', '/') + '.py', 'exec', dont_inherit=True), module.__dict__)
        sys.setprofile(None)
        captured[sha(marshal.dumps(module.Sample.__init__.__code__))] = module.Sample.__init__.__code__
    finally:
        sys.setprofile(None)
        del sys.modules[module_name]
    return list(captured.values())


# Stop this diagnostic immediately after observing the first generated wrapper.
class FirstObserved(Exception):
    pass


# Observe an unchanged full-compilation profile method only after its first refusal.
def live_first(producer, manifest):
    observations = []
    module = types.ModuleType(MODULE)
    assert MODULE not in sys.modules and sys.getprofile() is None
    sys.modules[MODULE] = module
    raw = Path('/audit/harness-source.txt').read_bytes()
    assert len(raw) == 30408 and sha(raw) == HARNESS_SHA
    tree = ast.parse(raw)
    constants = {}
    for node in tree.body:
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
    namespace = {'__builtins__': __builtins__, 'sys': sys, 'hashlib': hashlib, 'marshal': marshal, **constants}
    profile = types.FunctionType(profiles[0], namespace)
    source_code = compile(DATACLASS, '/prepared/source/backend/market/replay_broker.py', 'exec', dont_inherit=True, optimize=0)
    codes, pending = {}, [source_code]
    while pending:
        code = pending.pop()
        codes[id(code)] = (code, 'backend/market/replay_broker.py', code.co_qualname, code.co_firstlineno)
        pending.extend(item for item in code.co_consts if isinstance(item, types.CodeType))
    # Read the original method's computed record after hashing, never wrap its hash.
    def trip(reason, identity=''):
        frame = sys._getframe(1)
        assert frame.f_code is profiles[0]
        generated = frame.f_locals.get('generated')
        code = frame.f_locals['code']
        observations.append((None if generated is None else dict(generated), code, reason, identity))
        raise FirstObserved('DIAGNOSTIC_PROFILE_REFUSAL_ONLY')
    fence = types.SimpleNamespace(active=True, installing=False, phase='BOOTSTRAP', codes=codes, seen=set(),
                                  manifest=manifest, book=types.SimpleNamespace(root='/prepared/source'),
                                  dataclass_source=producer, trip=trip)
    try:
        sys.setprofile(types.MethodType(profile, fence))
        try:
            exec(source_code, module.__dict__)
        except FirstObserved as error:
            assert str(error) == 'DIAGNOSTIC_PROFILE_REFUSAL_ONLY'
        else:
            raise AssertionError('PROFILE_REFUSAL_NOT_OBSERVED')
    finally:
        fence.active = False
        sys.setprofile(None)
        del sys.modules[MODULE]
    assert len(observations) == 1
    generated, code, reason, identity = observations[0]
    # This marshal is a labelled post-observation control, never the original bytes.
    post_raw = marshal.dumps(code)
    return generated, code, reason, identity, post_raw


# Execute only tiny definitions in one fresh child and preserve its first fingerprint.
def probe(mode, output):
    assert mode in ('deferred', 'live') and sha(DATACLASS.encode()) == TINY_SHA
    assert not any(name == 'backend' or name.startswith('backend.') for name in sys.modules)
    source = Path(dataclasses.__file__).read_bytes()
    assert len(source) <= 262144
    producer = sha(source)
    frozen_raw = Path('/audit/frozen-calls.json').read_bytes()
    assert len(frozen_raw) == 11817 and sha(frozen_raw) == FROZEN_SHA
    if mode == 'deferred':
        # Preserve original preparation order and retain preceding namespace rows.
        warm_codes = deferred_codes('backend.capacity_dataclass')
        warm_rows = [record(code, 'backend.capacity_dataclass', producer)[0] for code in warm_codes]
        del warm_codes
        codes = deferred_codes(MODULE)
        observations = []
        for code in codes:
            row, raw = record(code, MODULE, producer)
            observations.append((row, raw, code))
        assert warm_rows and observations
    else:
        manifest = json.loads(frozen_raw)
        frozen = manifest['generated']
        generated, code, reason, identity, post_raw = live_first(producer, manifest)
        save(output / 'observation.json', {'scope': 'INJECTED_PROFILE_DIAGNOSTIC_NOT_COMPLETE_CALLFENCE_ACCEPTANCE',
             'mode': mode, 'python': sys.version, 'dataclasses_source_sha256': producer,
             'tiny_source_sha256': TINY_SHA, 'frozen_manifest_sha256': FROZEN_SHA, 'harness_source_sha256': HARNESS_SHA,
             'observed_record_computed_by_unchanged_profile': generated, 'refusal_reason': reason, 'refusal_identity': identity,
             'complete_frozen_matches': [] if generated is None else [index for index, item in enumerate(frozen) if item == generated],
             'code_content_after_primary_hash': content(code), 'post_observation_marshal_base64': base64.b64encode(post_raw).decode(),
             'post_observation_hash_is_primary_record': generated is not None and sha(post_raw) == generated['code_sha256'],
             'injected_fence_and_registration': True, 'audit_hook_or_failure_slot_or_full_SourceBook': False,
             'original_failed_guard_hash_recovered': False, 'backend_imports_or_Sample_instances': False})
        return
    frozen = json.loads(frozen_raw)['generated']
    items = []
    # Metadata and additional marshal calls occur only after all primary hashes.
    for ordinal, (row, raw, code) in enumerate(observations):
        assert len(raw) <= 65536 and row['code_sha256'] == sha(raw)
        items.append({'ordinal': ordinal, 'record': row, 'marshal_base64': base64.b64encode(raw).decode(),
                      'complete_frozen_matches': [index for index, item in enumerate(frozen) if item == row],
                      'code_content_after_primary_hash': content(code)})
    save(output / 'observation.json', {'scope': 'TINY_SYNTHETIC_DIAGNOSTIC_NOT_GUARD_ACCEPTANCE',
         'mode': mode, 'python': sys.version, 'dataclasses_source_sha256': producer,
         'tiny_source_sha256': TINY_SHA, 'frozen_manifest_sha256': FROZEN_SHA,
         'original_preparation_order_warmup_rows': warm_rows, 'observations': items,
         'first_marshal_eval_order': 'deferred observer helper: six record fields held in dict, then marshal; frozen membership required before inference',
         'backend_imports_or_Sample_instances': False, 'original_failed_guard_hash_recovered': False})


# Bound each child CPU and log file without claiming a daemon memory reservation.
def child_limits():
    resource.setrlimit(resource.RLIMIT_CPU, (5, 5))
    resource.setrlimit(resource.RLIMIT_FSIZE, (262144, 262144))


# Interrupt the parent deadline while preserving bounded owned-child cleanup.
def alarm(signum, frame):
    raise KeyboardInterrupt('TINY_DIAGNOSTIC_WALL_DEADLINE')


# Run exactly two fresh probes and compare every candidate full record, not one key.
def diagnose():
    assert os.getuid() == 1000
    root = Path('/out')
    assert list(root.iterdir()) == []
    signal.signal(signal.SIGALRM, alarm)
    signal.setitimer(signal.ITIMER_REAL, 20)
    try:
        for mode in ('deferred', 'live'):
            target = root / mode
            target.mkdir(mode=0o700)
            stdout, stderr = (target / 'stdout.log').open('xb'), (target / 'stderr.log').open('xb')
            process, stopped = None, None
            try:
                prior = signal.pthread_sigmask(signal.SIG_BLOCK, {signal.SIGALRM})
                try:
                    process = subprocess.Popen([sys.executable, '-I', '-S', '-B', str(SELF), 'probe', mode, str(target)], stdin=subprocess.DEVNULL, stdout=stdout, stderr=stderr, preexec_fn=child_limits)
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
        deferred = json.loads((root / 'deferred/observation.json').read_bytes())['observations']
        live = json.loads((root / 'live/observation.json').read_bytes())
        live_record = live['observed_record_computed_by_unchanged_profile']
        first = deferred[0]
        differences = None if live_record is None else [{key: [item['record'][key], live_record[key]] for key in live_record if item['record'][key] != live_record[key]} for item in deferred]
        reproduced = bool(first['complete_frozen_matches'])
        save(root / 'comparison.json', {'status': 'DIAGNOSTIC_OBSERVATIONS_COMPLETE', 'deferred_first_frozen_reproduced': reproduced,
             'live_complete_frozen_matches': live['complete_frozen_matches'], 'live_vs_every_deferred_record_differences': differences,
             'live_refusal_reason': live['refusal_reason'], 'live_refusal_identity': live['refusal_identity'],
             'first_typed_code_content_equal': first['code_content_after_primary_hash'] == live['code_content_after_primary_hash'],
             'post_observation_hash_is_primary_record': live['post_observation_hash_is_primary_record'],
             'cause_attribution_allowed_without_deferred_reproduction': False,
             'original_failed_guard_hash_recovered': False, 'genuine_or_guard_suite_acceptance': False})
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)


# Require explicit tiny-diagnostic routes; default invocation performs no probe.
def main(arguments):
    if arguments == ['diagnose']:
        diagnose()
    elif len(arguments) == 3 and arguments[0] == 'probe':
        probe(arguments[1], Path(arguments[2]))
    else:
        raise SystemExit('SOURCE_ONLY_NO_DIAGNOSTIC_ADMISSION')


if __name__ == '__main__':
    main(sys.argv[1:])
