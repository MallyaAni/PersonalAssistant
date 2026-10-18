"""Tiny synthetic fixture preparation only; no genuine backend import or data read.

This source has not been executed. All backend modules below are new fixture
bytes. The two original source texts are inert compiler inputs only. They must
be SHA-pinned and are never imported as application modules.
"""

import ast
import dataclasses
import hashlib
import json
import marshal
import os
import sys
import types
from pathlib import Path

HARNESS_SHA = '030cb5bb25f89c2785e6acbd55aceff5c99b632a5eb538079ee027362ae6178a'
FINGERPRINT = {'algorithm': 'cpython-code-marshal-format-2-sha256/1', 'marshal_version': 2}
PRODUCER_SHA = 'fae5bfc7d7438071094f31f42e884cb48e3709c55f364954e51c28302d3c3e30'
CONTINUATION_SHA = '14357ed7b87618ee514dd3cd4e4a71e2c27290875c3df257e692773e524cfaaf'
DAILY_SHA = '40d0d7cf482591ba28e6426ca87d23d3ed1b1cf42e31fd74a24a1287129221d9'
PHASES = ('BOOTSTRAP', 'ADMISSION', 'BEFORE', 'LOAD', 'FROZEN', 'AFTER', 'SERIALIZE', 'DONE')
BASE = '''from pathlib import Path
import os
# Leave a tiny fixture-only marker when an explicitly allowed body runs.
def safe():
    Path(os.environ['CASE_OUT'], 'safe.marker').write_text('safe')
# Leave a forbidden marker only if the guard fails to stop this body.
def hidden():
    Path(os.environ['CASE_OUT'], 'forbidden.marker').write_text('hidden')
# Keep an inert class definition in the positive import path.
class Literal:
    value = 7
'''
DATACLASS = '''from dataclasses import dataclass
@dataclass
class Sample:
    value: int
'''
AUDIT = '''import json
import os
import sys
import weakref
from pathlib import Path
from types import SimpleNamespace as NS
_auth_calls = 0
_eq_calls = 0
_loaded_ref = None
_nan = float('nan')
_large_text = None
class Array:
    # Describe a tiny synthetic array without allocating any numerical buffer.
    def __init__(self):
        self.base = None
        self.shape = (2,)
        self.dtype = 'synthetic-byte'
        self.nbytes = 2
        self.flags = NS(writeable=False, owndata=True)
np = NS(__version__='2.5.3', ndarray=Array)
sklearn = NS(__version__='1.9.1')
# Persist only fixture state, never account or model state.
def _mark(name, value):
    target = Path(os.environ['CASE_OUT']) / (name + '.json')
    with target.open('x') as output:
        json.dump(value, output, sort_keys=True)
# Decode the tiny synthetic invocation instead of reading genuine artifacts.
def invocation(path, expected):
    return json.loads(Path(path).read_bytes())
# Label the injected runtime explicitly synthetic.
def runtime_admission(value):
    if os.environ.get('CASE_VARIANT') == 'version':
        np.__version__ = '0'
    return {'status': 'INJECTED_SYNTHETIC_NOT_RUNTIME_ADMISSION'}
class OriginalArchives:
    # Keep the source shape but read no original account path.
    def __init__(self, *args, scratch, **kwargs):
        Path(scratch).mkdir()
# Return only labelled source fixture metadata.
def source_admission(value, archives):
    return {'synthetic': True}
# Return only labelled producer fixture metadata.
def producer_admission(value):
    return {'synthetic': True}
# Return only labelled calendar fixture metadata.
def calendar_admission(archives, profile):
    return {'synthetic': True}
# Produce controlled equal or unequal synthetic preservation observations.
def preserved_archives(archives, expected, length):
    return 'changed' if os.environ.get('CASE_VARIANT') == 'state' and _auth_calls == 2 else 'synthetic-state'
class Receipt(dict):
    # Observe both roots in the real harness caller without changing its values.
    def __eq__(self, other):
        global _eq_calls
        _eq_calls += 1
        parent = sys._getframe(1).f_locals
        _mark('coexist-' + str(_eq_calls), {
            'distinct_receipts': self is not other,
            'loaded_alive': _loaded_ref is not None and _loaded_ref() is not None,
            'has_serialized': isinstance(parent.get('serialized'), str),
            'has_encoded': isinstance(parent.get('encoded'), bytes),
        })
        return dict.__eq__(self, other)
class Auth:
    class Pins:
        # Accept fixture selector arguments without asserting genuine admission.
        def __init__(self, *args):
            pass
    # Resolve only the synthetic writable output directory.
    def physical(self, path):
        return Path(path)
    # Return two full tiny graphs, with an explicit controlled mutation option.
    def authenticate(self, *args, scratch, **kwargs):
        global _auth_calls, _large_text
        _auth_calls += 1
        Path(scratch).mkdir()
        _mark('auth-' + str(_auth_calls), {'synthetic': True})
        value = Receipt({'files': {str(i): {'bytes': 3, 'sha256': 'a' * 64} for i in range(8)}})
        if _auth_calls == 2 and os.environ.get('CASE_VARIANT') == 'receipt':
            value['changed'] = True
        if os.environ.get('CASE_VARIANT') == 'nan':
            value['not_finite'] = _nan
        if os.environ.get('CASE_VARIANT') == 'output-growth':
            if _large_text is None:
                _large_text = 'x' * (256 * 1024 ** 2)
            value['bounded_synthetic_stress_text'] = _large_text
        if _auth_calls == 2 and os.environ.get('CASE_VARIANT') == 'source':
            target = Path(os.environ['CASE_SOURCE']) / 'backend/capacity_fixture.py'
            with target.open('ab') as output:
                output.write(b'# SYNTHETIC_PRIVATE_COPY_CHANGED')
                output.flush()
                os.fsync(output.fileno())
        if _auth_calls == 2 and os.environ.get('CASE_VARIANT') == 'collision':
            (Path(os.environ['CASE_OUT']) / 'original-loader-capacity/candidate.json').write_bytes(b'ORPHAN_DO_NOT_REPLACE')
        return value
class Loaded:
    pass
# Construct one tiny weak-referenceable context, never a model or array.
def _load(archives, market, *, observed_at):
    global _loaded_ref
    value = Loaded()
    value.reader = NS(_parent=NS(_frozen_dates=[1, 2, 3], _bank={'dates': [1, 2, 3]}))
    value.same_reader = value.reader
    value.array = Array()
    value.array_alias = value.array
    if os.environ.get('CASE_VARIANT') == 'inventory-growth':
        value.oversized_inventory = [None] * 100001
    _loaded_ref = weakref.ref(value)
    _mark('load', {'synthetic': True})
    return value
byte_auth = Auth()
loader = NS(load=_load)
'''


# Keep metadata deterministic and finite before it is externally pinned.
def encode(value):
    return json.dumps(value, sort_keys=True, indent=2, allow_nan=False).encode() + b'\n'


# Name bytes without importing any application dependency.
def digest(raw):
    return hashlib.sha256(raw).hexdigest()


# Write only absent fixture outputs and verify the exact readback bytes.
def write(root, name, raw):
    path = root / name
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    with path.open('xb') as output:
        output.write(raw)
        output.flush()
        os.fsync(output.fileno())
    assert path.read_bytes() == raw
    return {'sha256': digest(raw), 'bytes': len(raw)}


# Enumerate exact compiler code objects without running their function bodies.
def codes(code):
    todo, result = [code], []
    while todo:
        value = todo.pop()
        result.append(value)
        assert len(result) <= 20000
        todo.extend(item for item in value.co_consts if isinstance(item, types.CodeType))
    return result


# Reproduce the exact reviewed daily-prefix AST seam without executing inputs.
def daily_code(raw):
    assert digest(raw) == CONTINUATION_SHA
    tree = ast.parse(raw)
    node = next(item for item in tree.body if isinstance(item, ast.FunctionDef) and item.name == 'inputs')
    source = ast.get_source_segment(raw.decode(), node) + '\n'
    assert digest(source.encode()) == DAILY_SHA
    body = ast.parse(source)
    function = body.body[0]
    stops = [i for i, item in enumerate(function.body) if isinstance(item, ast.Assign) and any(isinstance(target, ast.Name) and target.id == 'shape' for target in item.targets)]
    assert len(stops) == 1
    function.body = function.body[:stops[0]] + [ast.Return(ast.Tuple([ast.Name(name, ast.Load()) for name in ('panel', 'grades', 'eligible', 'factors', 'actions', 'sources')], ast.Load()))]
    return compile(ast.fix_missing_locations(body), '<pinned daily prefix>', 'exec', dont_inherit=True, optimize=0)


# Freeze an explicit format-2 generated-code record independently of the guard.
def generated(code, module, producer, kind, phase='BOOTSTRAP'):
    return {'kind': kind, 'phase': phase, 'module': module, 'qualname': code.co_qualname, 'line': code.co_firstlineno, 'filename': code.co_filename, 'code_sha256': digest(marshal.dumps(code, 2)), 'producer_source_sha256': producer}


# Observe only compiler-generated factory code for the new tiny dataclass fixture.
def dataclass_codes(module_name):
    captured = {}
    # Freeze exact generated templates, never discover a financial call allowlist.
    def capture(frame, event, argument):
        code = frame.f_code
        if event == 'call' and code.co_filename == '<string>' and frame.f_globals.get('__name__') == module_name:
            assert code.co_qualname == '<module>' or code.co_qualname.startswith('__create_fn__')
            captured[digest(marshal.dumps(code, 2))] = code
    module = types.ModuleType(module_name)
    assert module_name not in sys.modules and sys.getprofile() is None
    sys.modules[module_name] = module
    try:
        sys.setprofile(capture)
        exec(compile(DATACLASS, '/app/' + module_name.replace('.', '/') + '.py', 'exec', dont_inherit=True), module.__dict__)
        sys.setprofile(None)
        captured[digest(marshal.dumps(module.Sample.__init__.__code__, 2))] = module.Sample.__init__.__code__
    finally:
        sys.setprofile(None)
        del sys.modules[module_name]
    return list(captured.values())


# Select exact fixture function phases from declarations, never from observed calls.
def phases_for(name, code):
    q = code.co_qualname
    if not code.co_flags & 2:
        return ('BOOTSTRAP',)
    if name.endswith('audit_original_live_model_history.py'):
        if q.startswith('Receipt.__eq__'):
            return ('AFTER', 'SERIALIZE')
        if q.startswith('Auth.authenticate'):
            return ('BEFORE', 'AFTER')
        if q.startswith('_load'):
            return ('LOAD',)
        if q.startswith('Array.__init__'):
            return ('LOAD',)
        if q.startswith('preserved_archives'):
            return ('ADMISSION', 'AFTER')
        if q.startswith('_mark'):
            return ('ADMISSION', 'BEFORE', 'LOAD', 'AFTER', 'SERIALIZE')
        return ('ADMISSION',)
    return ('BOOTSTRAP',)


# Describe every controlled child outcome before any synthetic test is started.
def scenarios():
    rows = []
    for group, variants in (
        ('G01', ['positive']), ('G02', ['alias']), ('G03', ['import-call']),
        ('G04', ['missing', 'shadow', 'pyc']),
        ('G05', ['root-link', 'middle-link', 'file-link', 'tamper', 'replace', 'grow']),
        ('G06', ['manifest-sha', 'manifest-schema', 'manifest-duplicate', 'manifest-nan']),
        ('G07', ['distribution', 'select', 'fit', 'submit_order', 'audit', 'stateful']),
        ('G08', ['effect-function', 'effect-generated']),
        ('G09', ['generated-positive', 'generated-code', 'generated-producer']),
        ('G10', ['prefix-positive', 'prefix-wrapper', 'prefix-inputs', 'prefix-producer', 'prefix-phase']),
        ('G11', ['catch']),
        ('G12', ['profile', 'trace', 'thread', 'socket', 'process']),
        ('G13', ['readonly', 'append', 'sparse', 'size', 'link', 'nonzero', 'path']),
        ('G14', ['no-fence', 'no-finder', 'no-auth']),
        ('G15', ['runtime', 'profile', 'mapping', 'version', 'runtime-duplicate', 'runtime-nan', 'invocation-duplicate', 'runtime-hash', 'invocation-hash']),
        ('G16', ['journey']),
        ('G17', ['receipt', 'state', 'nan', 'collision', 'source', 'inventory-growth', 'output-growth']),
    ):
        for variant in variants:
            rows.append({'id': group + '-' + variant, 'group': group, 'variant': variant})
    assert len(rows) < 128
    return rows


# Materialize only tiny fixture modules and exact native compiler declarations.
def prepare(root, producer_raw, continuation_raw):
    assert digest(producer_raw) == PRODUCER_SHA and digest(continuation_raw) == CONTINUATION_SHA
    assert not any(name == 'backend' or name.startswith('backend.') for name in sys.modules)
    root.mkdir(mode=0o700, exist_ok=False)
    source = {
        'backend/__init__.py': b'', 'backend/cli/__init__.py': b'',
        'backend/market/__init__.py': b'',
        'backend/capacity_fixture.py': BASE.encode(),
        'backend/capacity_dataclass.py': DATACLASS.encode(),
        'backend/market/alpaca_trading.py': BASE.encode(),
        'backend/market/replay_broker.py': DATACLASS.encode(),
        'backend/market/live_model_history_stream_audit.py': b"from pathlib import Path\nimport os\nclass StreamAudit:\n    # Leave evidence only if a forbidden constructor is actually entered.\n    def __init__(self):\n        Path(os.environ['CASE_OUT'], 'forbidden.marker').write_text('stateful')\n",
        'backend/cli/audit_original_live_model_history.py': AUDIT.encode(),
        'backend/market/live_model_history_audit_inputs.py': producer_raw,
    }
    records = {}
    for name, raw in source.items():
        records[name] = write(root, 'source/' + name, raw)
    calls = {phase: [] for phase in PHASES}
    # The original producer text is inert: never compile or import its module.
    for name, raw in source.items():
        if name.endswith('live_model_history_audit_inputs.py'):
            continue
        for code in codes(compile(raw, '/app/' + name, 'exec', dont_inherit=True, optimize=0)):
            for phase in phases_for(name, code):
                calls[phase].append([name, code.co_qualname, code.co_firstlineno])
    # This module contains only the new two-line Sample declaration. Executing
    # its definitions freezes stdlib-generated code, never a Sample instance.
    module_name = 'backend.capacity_dataclass'
    generated_rows = [generated(code, module_name, digest(Path(dataclasses.__file__).read_bytes()), 'stdlib-dataclass-exact-native-code') for code in dataclass_codes(module_name)]
    effect_name = 'backend.market.replay_broker'
    generated_rows.extend(generated(code, effect_name, digest(Path(dataclasses.__file__).read_bytes()), 'stdlib-dataclass-exact-native-code') for code in dataclass_codes(effect_name))
    prefix = daily_code(continuation_raw)
    generated_rows.extend(generated(code, 'backend.cli.market_strategy_continue', PRODUCER_SHA, 'exact-original-daily-prefix-transformation-40d0d7cf', 'LOAD') for code in codes(prefix) if code.co_qualname in ('<module>', 'inputs'))
    manifest = {'schema': 'n2-capacity-call-manifest/2', 'fingerprint': dict(FINGERPRINT), 'recipe_sha256': '503e8d508ebe5fdc82a17c11974ccce5366c60ce8e78fc549c129fc6c6d81e03', 'contract_sha256': 'ecc58ad7f6ec65bb42a28ef0c2bea8d116b0e9be5ea59e490388fa0e74dfddc8', 'calls': calls, 'generated': generated_rows}
    write(root, 'calls.json', encode(manifest))
    write(root, 'continuation-source.txt', continuation_raw)
    write(root, 'scenarios.json', encode(scenarios()))
    summary = {'schema': 'guard-fixtures/3', 'guard_manifest_schema': 'n2-capacity-call-manifest/2', 'generated_fingerprint': dict(FINGERPRINT), 'scope': 'SYNTHETIC_ONLY_NO_GENUINE_ADMISSION', 'files': records, 'calls_sha256': digest(encode(manifest)), 'scenarios_sha256': digest(encode(scenarios())), 'continuation_sha256': CONTINUATION_SHA, 'python': sys.version, 'generated': generated_rows, 'model_or_account_calls': False}
    write(root, 'prepared.json', encode(summary))
    descriptor = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
    os.fsync(descriptor)
    os.close(descriptor)
    return summary
