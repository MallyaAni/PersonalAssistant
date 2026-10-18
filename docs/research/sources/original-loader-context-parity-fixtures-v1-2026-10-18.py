"""UNRUN tiny SYNTHETIC fixtures; inert source copies never become genuine accounts."""
import ast
import builtins
import copy
import dataclasses
import gzip
import hashlib
import io
import json
import math
import os
import shutil
import stat
import tempfile
import types
from collections.abc import Mapping
from pathlib import Path
from types import MappingProxyType

AUDIT = Path('/audit')


# Hash exact bytes used by fixtures, source declarations and observations.
def sha(raw):
    return hashlib.sha256(raw).hexdigest()


# Write one new bounded synthetic file without adopting an existing fixture.
def write(path, raw):
    assert type(raw) is bytes and len(raw) <= 262144
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('xb') as output:
        output.write(raw)
        output.flush()
        os.fsync(output.fileno())
    assert path.read_bytes() == raw
    return sha(raw)


# Encode finite synthetic controls without changing the original parser's semantics.
def encoded(value):
    return json.dumps(value, sort_keys=True, allow_nan=False).encode()


# Import only real small candidate modules from their authenticated actual file paths.
def load():
    pins = json.loads((AUDIT / 'pins.json').read_bytes())
    for name, item in pins.items():
        raw = (AUDIT / name).read_bytes()
        assert len(raw) == item['bytes'] <= 262144 and sha(raw) == item['sha256']
    app = AUDIT / 'app'
    assert {str(p.relative_to(app)) for p in app.rglob('*') if p.is_file()} == {n[4:] for n in pins if n.startswith('app/')}
    import sys
    sys.path.insert(0, str(app))
    from backend.market import capacity_original_archives_v1 as context
    from backend.market import capacity_original_admission_lifecycle_v1 as lifecycle
    from backend.market import capacity_original_calendar_v1 as calendar
    modules = {n: m for n, m in sys.modules.items() if n == 'backend' or n.startswith('backend.')}
    expected = {'backend', 'backend.market'} | {'backend.market.' + n for n in (
        'capacity_original_archives_v1', 'capacity_original_admission_lifecycle_v1',
        'capacity_original_admissions_v1', 'capacity_original_calendar_v1',
        'capacity_original_archive_adaptations_v1', 'capacity_original_metadata_v1',
        'capacity_original_evidence_v1', 'live_model_history_input_auth', 'original_history_json')}
    assert set(modules) == expected
    origins = {n: str(Path(m.__file__).resolve()) for n, m in sorted(modules.items())}
    assert all(Path(p).is_relative_to(app) for p in origins.values())
    for n, p in origins.items():
        relative = str(Path(p).relative_to(AUDIT))
        assert sha(Path(p).read_bytes()) == pins[relative]['sha256']
    import numpy as np
    assert np.__version__ == '2.5.3' and Path(np.__file__).resolve() == Path('/usr/local/lib/python3.12/site-packages/numpy/__init__.py')
    assert not any(n.startswith(('sklearn', 'scipy', 'pandas')) for n in sys.modules)
    return types.SimpleNamespace(context=context, lifecycle=lifecycle, calendar=calendar,
        evidence=context.evidence, adapt=context.adaptations, metadata=context.metadata,
        streamed=context.streamed, np=np, origins=origins)


# Bind selected original CodeTypes in explicitly synthetic globals without original module execution.
def reference(env):
    names = ('live_model_history_stream_audit', 'live_model_history_pending_audit',
             'live_model_history_receipts', 'live_policy_replay', 'live_model_history_nightly_model')
    paths = {n: AUDIT / 'reference/backend/market' / (n + '.py') for n in names}
    compiled = {n: compile(p.read_bytes(), str(p), 'exec', dont_inherit=True) for n, p in paths.items()}
    ns = {'__name__': 'ISOLATED_SYNTHETIC_CONTEXT_REFERENCE', '__builtins__': builtins.__dict__,
          '__file__': str(paths['live_model_history_stream_audit']), 'ast': ast,
          'gzip': gzip, 'io': io, 'json': json, 'math': math, 'os': os, 'stat': stat,
          'sha256': hashlib.sha256, 'Path': Path, 'tempfile': tempfile,
          'streamed': env.streamed, 'Mapping': Mapping, 'MappingProxyType': MappingProxyType,
          'deepcopy': copy.deepcopy, 'dataclass': dataclasses.dataclass, 'np': env.np,
          'MAX_METADATA_BYTES': 16 * 1024**2, 'HASH_CHUNK_BYTES': 1024**2}
    # Instantiate only a selected function declaration from a complete inert compilation.
    def bind(name, origin):
        code = next(c for c in compiled[origin].co_consts if isinstance(c, types.CodeType) and c.co_name == name)
        fn = types.FunctionType(code, ns, name)
        if name == 'pinned':
            fn.__kwdefaults__ = {'max_bytes': None}
        ns[name] = fn
        return fn
    bind('require', 'live_model_history_receipts')
    for n in ('unique', 'reject_constant', 'finite_float'):
        bind(n, 'live_model_history_pending_audit')
    ns['pending'] = types.SimpleNamespace(**{n: ns[n] for n in ('unique', 'reject_constant', 'finite_float')},
        MAX_COMPRESSED_BYTES=64 * 1024**2, MAX_JSON_BYTES=256 * 1024**2)
    stream = 'live_model_history_stream_audit'
    for n in ('expected_digest', 'file_identity', 'stable_file', 'pinned', 'authenticate_file', 'strict_json', '_immutable', '_freeze', 'archive_value'):
        bind(n, stream)
    for n, base in (('_ReadOnlyDict', dict), ('_ReadOnlyList', list)):
        code = next(c for c in compiled[stream].co_consts if isinstance(c, types.CodeType) and c.co_name == n)
        ns[n] = builtins.__build_class__(types.FunctionType(code, ns), n, base)
    ns['live_policy_replay'] = types.SimpleNamespace(plain=bind('plain', 'live_policy_replay'))
    ns['numerical'] = types.SimpleNamespace(serialized=bind('serialized', 'live_model_history_nightly_model'))
    bind('digest', stream)
    code = next(c for c in compiled[stream].co_consts if isinstance(c, types.CodeType) and c.co_name == 'OriginalArchives')
    # Construct only the synthetic reference class; never import or execute the original module.
    cls = builtins.__build_class__(types.FunctionType(code, ns), 'OriginalArchives')
    cls = dataclasses.dataclass(frozen=True, slots=True)(cls)
    ns['OriginalArchives'] = cls
    return types.SimpleNamespace(**ns)


# Copy authenticated inert N2 and original legacy bytes into a distinct synthetic source root.
def source_copy(target):
    shutil.copytree(AUDIT / 'inert-source', target)
    pins = json.loads((AUDIT / 'native31.json').read_bytes())
    for n, expected in pins.items():
        assert sha((target / n).read_bytes()) == expected
    return pins


# Build all seventeen layout fields from source metadata without creating PaperState.
def state(env, *, nonfinite=False):
    fields = env.metadata.paper_descriptor((AUDIT / 'inert-source/backend/agents/trading/desk/paper.py').read_bytes())['physical_state_fields']
    result = {n: None for n in fields}
    result.update(sessions_seen=2, order_seq=0, history=[{'session': '2019-02-28', 'value': None if nonfinite else 1},
        {'session': '2019-03-01', 'value': 'é😀'}, {'session': '2019-03-04', 'value': -0.0}],
        pending=[], journal=[], opened={}, event_outcomes={}, deferred_buys={}, rebalance_targets={})
    return result


# Retain tiny real parser inputs and explicit synthetic predecessor rather than genuine account data.
class Fixture:
    # Make separate roots, source copies, maps and spools for each candidate or reference control.
    def __init__(self, env, target, *, external=True, completion_change=None, physical_change=None, nonfinite=False):
        self.env, self.target = env, target
        target.mkdir()
        self.source = target / 'source'
        self.native = source_copy(self.source)
        self.reader = env.context.CapacitySourceReaderV1(self.source, self.native)
        self.root, self.market = target / 'account', target / 'market'
        self.root.mkdir()
        self.market.mkdir()
        data_sha = write(self.market / 'quotes.json', encoded({'x': 1, 'unicode': 'é'}))
        capture = {'files': {'quotes.json': data_sha}, 'source_sha256': {}}
        self.capture_sha = write(self.market / 'capture.json', encoded(capture))
        first = json.loads((self.source / env.context.CATALOG_PATHS[0]).read_bytes())
        second = json.loads((self.source / env.context.CATALOG_PATHS[1]).read_bytes())
        predecessor = dict(self.native)
        predecessor.pop('backend/market/live_model_decision.py')
        predecessor['backend/api/v1/market.py'] = first['previous_approved_sha256']
        predecessor['backend/market/learned_live_holding.py'] = second['source_changes']['backend/market/learned_live_holding.py']['before_sha256']
        self.ending = state(env, nonfinite=nonfinite)
        initial = gzip.compress(encoded({'initial': 'SYNTHETIC_COMPARISON_ONLY'}), mtime=0)
        self.initial_sha = write(self.root / 'initial.json.gz', initial)
        sessions = []
        for date in ('2019-03-01', '2019-03-04'):
            digest = write(self.root / 'sessions' / (date + '.json.gz'), gzip.compress(encoded({'session': date, 'SYNTHETIC': True}), mtime=0))
            sessions.append({'session': date, 'sha256': digest})
        value = {'status': 'COMPLETED_UNVERIFIED_CURRENT_MODEL_ACCOUNT', 'paper_state': copy.deepcopy(self.ending),
            'input_sha256': {str(self.market / 'quotes.json'): data_sha, '/unused/SYNTHETIC': 'a' * 64},
            'capture_sha256': self.capture_sha, 'source_sha256': predecessor, 'sessions': sessions,
            'first': '2019-03-01', 'through': '2019-03-04'}
        if completion_change is not None:
            completion_change(value)
        self.completion_sha = write(self.root / 'completion.json', encoded(value))
        manifest = {'files': {n: sha(p.read_bytes()) for p in sorted(self.source.rglob('*')) if p.is_file() for n in [str(p.relative_to(self.source))]}}
        self.manifest = target / 'manifest.json'
        self.manifest_sha = write(self.manifest, encoded(manifest))
        physical = copy.deepcopy(self.ending)
        if physical_change is not None:
            physical_change(physical)
        if nonfinite:
            physical['history'][0]['value'] = float('nan')
        self.physical = self.root / 'state/paper/state.json'
        raw = json.dumps(physical, sort_keys=True, allow_nan=nonfinite).encode()
        self.physical_sha = write(self.physical, raw)
        self.physical_size = len(raw)
        self.scratch = target / 'spools'
        self.external = external
        self.archives = None

    # Instantiate only the actual new context on independently generated synthetic inputs.
    def candidate(self, **kwargs):
        arguments = dict(source_reader=self.reader, scratch=self.scratch, external_inputs=self.external)
        arguments.update(kwargs)
        self.archives = self.env.context.CapacityOriginalArchivesV1(self.root, self.completion_sha,
            self.initial_sha, self.manifest, self.manifest_sha, **arguments)
        return self.archives

    # Instantiate the isolated original class only with its own tiny synthetic files and scratch.
    def original(self, ref):
        return ref.OriginalArchives(self.root, self.completion_sha, self.initial_sha, self.manifest,
            self.manifest_sha, scratch=self.scratch, external_inputs=self.external)


# Require explicit expected exception classes/reasons and retain the first observed boundary.
def outcome(rows, case, action, *, refusal=None, scope='ACTUAL_SYNTHETIC_CANDIDATE', reference=None):
    try:
        value = action()
    except Exception as caught:
        assert refusal is not None, (case, type(caught).__name__, str(caught))
        kind, reason = refusal
        assert type(caught).__name__ == kind and (reason is None or str(caught) == reason), (case, type(caught).__name__, str(caught), refusal)
        row = {'case': case, 'status': 'EXPECTED_REFUSAL', 'exception': kind, 'reason': str(caught), 'scope': scope}
    else:
        assert refusal is None, (case, 'EXPECTED_REFUSAL_ABSENT')
        if type(value) is bool:
            assert value, (case, 'POSITIVE_PREDICATE_FALSE')
        if reference is not None:
            assert value == reference(), (case, 'REFERENCE_VALUE_DIFFERS')
        row = {'case': case, 'status': 'PASS', 'scope': scope, 'value_sha256': sha(encoded(value))}
    rows.append(row)
    return row
