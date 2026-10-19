"""NEW marker/latch setup-only composition; full CodeTypes, no closed test body."""
import ast
import builtins
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import asdict, fields
from datetime import UTC, date, datetime, timedelta
import hashlib
import io
import json
import os
import stat
from pathlib import Path
import tempfile
from threading import Lock, get_ident
import time
from types import CodeType, FunctionType, SimpleNamespace

from backend.agents.trading.desk import paper, intraday_orders
from backend.market import historical_broker_checkpoint as codec
from backend.market import historical_native_metadata as metadata
from backend.market import historical_packet_checkpoint as checkpoint
from backend.market import historical_packet_demand as demand
from backend.market import historical_packet_registry as registry
from backend.market import historical_paper_component as component
from backend.market import historical_physical_checkpoint as physical
from backend.market import historical_reserved_blob_store as cas
from backend.market import historical_reserved_native_io as reserved_io
from backend.market import historical_reserved_protocol as protocol
from backend.market import historical_reserved_sqlite as sqlbanks
from backend.market import historical_synthetic_native_write as writer_module
from backend.market import historical_timing_packet as packet
from backend.market import replay_broker as native
from backend.market.alpaca_trading import AlpacaTradingError
from backend.market.historical_packet_store import Store, StorePause

CALLS = []


# Enforce declared fixture conditions without importing genuine forecast/model startup.
def require(ok, reason):
    if not ok:
        raise ValueError(reason)


# Preserve the unchanged conditional forecast's regular-file identity contract.
def identity(path):
    path = Path(path).absolute()
    for component in (path, *path.parents):
        require(not component.is_symlink(), "Regular conditional source paths required")
    info = path.stat()
    require(stat.S_ISREG(info.st_mode), "Regular conditional source file required")
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


# Instantiate complete-source function/class CodeTypes with explicit synthetic globals.
def load(path, given, names=None, classes=()):
    raw = path.read_bytes()
    code = compile(raw, str(path), 'exec', dont_inherit=True)
    codes = {n.co_name: n for n in code.co_consts if type(n) is CodeType}
    tree = ast.parse(raw)
    ns = {**given, '__builtins__': builtins.__dict__, '__file__': str(path),
          '__name__': 'SYNTHETIC_RESERVED_OUTCOME'}
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and (names is None or node.name in names):
            fn = FunctionType(codes[node.name], ns)
            defaults = node.args.defaults
            fn.__defaults__ = tuple(ns[n.id] if isinstance(n, ast.Name) else ast.literal_eval(n)
                                    for n in defaults) or None
            fn.__kwdefaults__ = {arg.arg: ns[n.id] if isinstance(n, ast.Name) else ast.literal_eval(n)
                for arg, n in zip(node.args.kwonlyargs, node.args.kw_defaults) if n is not None}
            ns[node.name] = fn
    for name, bases in classes:
        ns[name] = builtins.__build_class__(FunctionType(codes[name], ns), name, *bases)
    return ns


# Extract literal protocol constants only, without evaluating product module startup.
def constants(path, names):
    return {n.targets[0].id: ast.literal_eval(n.value) for n in ast.parse(path.read_bytes()).body
            if isinstance(n, ast.Assign) and isinstance(n.targets[0], ast.Name) and n.targets[0].id in names}


# Give the private synthetic latch a deterministic source-bound path.
def latch_path(root, session):
    return Path(root) / 'synthetic-latch' / (session.isoformat() + '.json')


# Bind the legacy source while explicitly declining its genuine full source manifest.
def synthetic_sources():
    path = Path('/audit/backend/market/historical_conditional_nightly.py')
    return {'SYNTHETIC_SOURCE_MANIFEST_ONLY': hashlib.sha256(path.read_bytes()).hexdigest()}


# Expose one fixture date transition without replacing the native broker calendar.
def next_session(day):
    return {date(2019, 2, 28): date(2019, 3, 1)}.get(day)


# Produce the declared hypothetical close clock while datetime.now remains real.
def instant(day, clock):
    return datetime.combine(day, clock, tzinfo=native.calendar.NEW_YORK).astimezone(UTC)


# Declare an empty synthetic corporate-action set; genuine economics remain unadmitted.
def due_actions(*args):
    return []


# Return only explicit synthetic marks to the actual native observer.
def account_marks(raw, index, at, marks):
    return marks


# Count actual synthetic policy invocations and return large native-domain decision data.
class Policy:
    # Bind one context so every invocation is observable.
    def __init__(self, context):
        self.context = context

    # Preserve native NaN values instead of normalizing them into finite JSON.
    def decide(self):
        self.context.policy_calls += 1
        return {'AAPL': float('nan')}, {'text': 'q' * 270000, 'scope': 'SYNTHETIC_POLICY'}


# Supply finite declared context/session selection, without a native model or constructor.
class Context:
    # Keep the two fixture sessions and explicit marks separate from actual execution time.
    def __init__(self):
        self.provenance, self.policy_calls = b'SYNTHETIC_RESERVED_OUTCOME_CONTEXT', 0
        self.panel = SimpleNamespace(dates=[date(2019, 2, 28), date(2019, 3, 1)])
        self.raw = SimpleNamespace(daily_close=[{'AAPL': 100}, {'AAPL': 101}])

    # Return only this synthetic cohort declaration.
    def validate(self):
        return {'symbols': ['AAPL'], 'scope': 'SYNTHETIC_CONTEXT_NO_MODEL'}

    # Select a synthetic report/policy at one explicitly declared date.
    def select(self, session):
        return self, Policy(self), self.panel.dates.index(date.fromisoformat(session))


# Supply a distinct synthetic intraday context to complete raw Cycle receipt bodies.
class CycleContext:
    # Retain the supplied bytes without invoking a model/context constructor.
    def __init__(self, raw, sha256):
        self.raw, self.sha256 = raw, sha256


# Check exact synthetic context bytes without admitting native market packet parsing.
def read_context(value):
    require(hashlib.sha256(value.raw).hexdigest() == value.sha256, 'Synthetic context SHA')
    return packet._decode(value.raw)


# Save real native snapshots and create only the fixture's original unsent intent.
def nightly_program(report, root, session, force, *, client_factory, decision_at, holding_policy, native_save):
    holding_policy.decide()
    state = paper.load_state(root)
    state.start_equity = float('nan')
    entry = paper.snapshot(state, session, 100000, 100000,
        [{'z': 'é' + str(i) + 'x' * 25000, 'a': float('nan')} for i in range(12)])
    if not state.pending and not state.journal:
        state.pending = [{'client_order_id': 'SYNTHETIC-reserved-outcome', 'symbol': 'AAPL',
            'side': 'buy', 'qty': 8, 'session': session, 'execute_on': '2019-03-01',
            'execution_timing': 'dip_or_close'}]
    native_save(root, state)
    return entry


# Use only once-per-stage producer capabilities for the original synthetic order.
def stage_program(*, phase, inputs, effects):
    CALLS.append(phase)
    if phase == 'DECISION_FROZEN':
        return {'order': inputs['candidate']}
    effects.observe()
    order = effects.submit()
    state = effects.load()
    state.pending[0].update({'sent': {'qty': int(order['qty']), 'at': order['submitted_at']},
        'execution': {'created_at': order['created_at'], 'submitted_at': order['submitted_at']}})
    effects.save(state)
    effects.latch()
    return {'submitted_qty': int(order['qty'])}


# Build the real registry from explicit synthetic evidence, never provider metadata.
def mapping():
    evidence, review = b'SYNTHETIC metadata only', b'SYNTHETIC mapping review'
    a, b = hashlib.sha256(evidence).hexdigest(), hashlib.sha256(review).hexdigest()
    raw = demand.encoded({'schema': 'historical-entity-registry/1', 'entries': [{
        'cohort_key': 'AAPL', 'query_symbol': 'AAPL', 'entity_asof': '2026-10-12',
        'status': 'REVIEWED_CONDITIONAL_MAPPING', 'issuer_identity': None,
        'assumption': 'Synthetic fixture only', 'review_sha256': b,
        'sources': [{'kind': 'request_metadata', 'sha256': a, 'source_label': 'synthetic'}]}]})
    return registry.registry(raw, hashlib.sha256(raw).hexdigest(), {a: evidence, b: review})


# Allocate only fresh private state and exact whole product bodies for the new assertions.
class Fixture:
    # Bind complete source namespaces before source-bound executors capture their globals.
    def __init__(self, name):
        parent = Path('/out/cases')
        parent.mkdir(mode=0o700, exist_ok=True)
        self.root = Path(tempfile.mkdtemp(prefix=name + '-', dir=parent))
        profile = json.loads(Path('/fixture/current-identity.json').read_bytes())
        self.identity = physical._sha(physical._encoded(profile))
        self.sql = sqlbanks.reserve(self.root / 'store', self.identity, source_paths=[Path(__file__)])
        self.store = Store(self.root / 'store', self.identity, None, create=True, sqlite_reservation=self.sql)
        self.cas = cas.reserve(self.store)
        self.store.bind_reserved_blobs(self.cas)
        self.writer = writer_module.reserve(self.store.root / 'SYNTHETIC-reserved-workspace',
            writer=paper.save_state, writer_source=Path(paper.__file__), identity=profile,
            identity_sha256=self.identity, slots=8)
        self.raw = physical.reserve(self.root / 'checkpoint', identity=profile,
            identity_sha256=self.identity, writer=Path(paper.__file__), limits={
                'span_bytes': 512 * 1024, 'raw_bytes': 1024 * 1024, 'history_rows': 32,
                'body_slots': 32, 'page_slots': 32, 'directory_headroom_bytes': 65536})
        marker = SimpleNamespace(__file__=__file__, Context=CycleContext, read_context=read_context)
        common = {**globals(), 'sha256': hashlib.sha256, 'stat': __import__('stat'),
            'Store': Store, 'StorePause': StorePause, 'CAP': 262144, 'META_CAP': 262144,
            'DAY': date(2019, 3, 1), 'CURRENT': physical.CURRENT,
            'admitted': SimpleNamespace(require=require, identity=identity,
                encoded=demand.encoded, decoded=packet._decode),
            'get_ident': get_ident, 'LOCK': Lock(), 'SAVE_STATE': paper.save_state,
            'SUBMIT': native.ReplayBroker._submit, 'FrozenCurrentGradePolicy': Policy, 'HoldingContext': Context,
            'calendar': native.calendar, 'intraday_orders': SimpleNamespace(next_session=next_session),
            'live_policy_replay': SimpleNamespace(instant=instant, due_actions=due_actions, account_marks=account_marks),
            'market_daily': marker, 'AlpacaTradingError': AlpacaTradingError, 'sources': synthetic_sources}
        base = Path('/audit/backend/market')
        legacy_ns = load(Path('/audit/backend/market/historical_conditional_nightly.py'), common,
            ('physical', 'physical_identity', 'put', 'components', 'context_identity', 'write_once', 'sync_directory'),
            (('Nightly', ()), ('NativeCapture', ())))
        self.legacy = SimpleNamespace(**legacy_ns)
        daily = load(Path('/native/backend/cli/market_daily.py'), {'datetime': datetime, 'date': date},
                     ('_acknowledged', '_reconciliation_pending'))
        self.settlement = SimpleNamespace(**load(base / 'historical_conditional_settlement.py',
            {**common, 'asdict': asdict, 'market_daily': SimpleNamespace(**daily)}))
        cycle_ns = load(Path('/audit/backend/market/historical_conditional_cycle.py'),
            {**common, 'market': marker, 'completion': marker, 'entities': registry,
             'checkpoint': checkpoint, 'entry_timing': SimpleNamespace(latch_path=latch_path),
             '_settlement_source': self.source, **constants(
                 Path('/audit/backend/market/historical_conditional_cycle.py'), {'SETTLEMENT_SHA256'})},
            ('sha', '_file', '_put', '_components', '_receipt', '_read_receipt', '_raw_reconciliation', '_head_entry'))
        self.bridge = SimpleNamespace(**load(base / 'historical_raw_cycle.py',
            {**common, 'cycle': SimpleNamespace(**cycle_ns), 'digest': registry.digest,
             **constants(base / 'historical_raw_cycle.py', {'LINEAGE', 'LINEAGE_KEYS', 'FINAL_KEYS'})}))
        raw_ns = load(base / 'historical_raw_nightly.py',
            {**common, 'legacy': self.legacy, 'raw_cycle': self.bridge, 'digest': registry.digest,
             **constants(base / 'historical_raw_nightly.py', {'SCHEMA', 'VALUE_KEYS', 'RECORD_KEYS', 'WRITE_KEYS'})},
            classes=(('RawNightly', (legacy_ns['Nightly'],)),))
        self.nightly = object.__new__(raw_ns['RawNightly'])
        self.nightly.store, self.nightly.root = self.store, self.writer.root / 'work'
        self.nightly.expected_head, self.nightly.pin_bytes = None, demand.encoded({
            'identity': profile, 'identity_sha256': self.identity})
        (self.nightly.root / 'operations').mkdir(mode=0o700)
        stage_ns = load(base / 'historical_reserved_cycle_stages.py',
            {**common, 'legacy': self.legacy, 'bridge': self.bridge, 'cas': cas, 'registry': registry,
             'raw_nightly': SimpleNamespace(__file__=raw_ns['__file__'],
                 RawNightly=raw_ns['RawNightly'], sources=raw_ns['sources']),
             'intraday_orders': intraday_orders, 'DUE': intraday_orders.due, 'contextmanager': contextmanager,
             'OBSERVE': native.ReplayBroker.observe, 'SUBMIT': native.ReplayBroker._submit,
             'SUBMIT_MARKET': native.ReplayBroker.submit_market,
             **constants(base / 'historical_reserved_cycle_stages.py', {'SCHEMA', 'PHASES'})},
            classes=(('_Effects', ()), ('_Stages', ()), ('_StageReader', ())))
        self.stage_ns = stage_ns
        self.final_ns = load(base / 'historical_reserved_cycle_final.py',
            {**common, 'legacy': self.legacy, 'settlement': self.settlement, 'bridge': self.bridge,
             'stages': SimpleNamespace(**stage_ns), 'FLUSH': native.ReplayBroker.flush, 'FILL': native.ReplayBroker._fill,
             **constants(base / 'historical_reserved_cycle_final.py', {'SCHEMA', 'REQUEST'})},
            classes=(('_Final', ()),))
        raw_ns['reserved_final'] = SimpleNamespace(**self.final_ns)
        self.context = Context()
        source_sha = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
        self.nightly_io = reserved_io.SyntheticNativeIO(self.writer, nightly_program, trade_sha256=source_sha)
        self.io = reserved_io.SyntheticNativeIO(self.writer, stage_program, trade_sha256=source_sha)
        self.metadata = protocol.reserve(self.store, self.nightly.root,
            source_paths=[Path(__file__)], latch_sessions=['2019-03-01'])
        self.store.bind_reserved_metadata(self.metadata)
        self.before = self.inventory()
        self.metadata_before = self.metadata_inventory()
        self.sql_before = self.sql_inventory()

    # Return only the pinned isolated settlement namespace, never native CLI startup.
    def source(self):
        expected = constants(Path('/audit/backend/market/historical_conditional_cycle.py'), {'SETTLEMENT_SHA256'})
        require(hashlib.sha256(Path(self.settlement.__file__).read_bytes()).hexdigest()
                == expected['SETTLEMENT_SHA256'], 'Original Cycle settlement source pin differs')
        return self.settlement

    # Record all original allocation fields without projecting nanosecond timestamps.
    def inventory(self):
        return {name: [str(getattr((self.cas.root / name).stat(), key)) for key in
            ('st_dev', 'st_ino', 'st_size', 'st_blocks')] for name in self.cas.inodes}

    # Observe original marker extents and names even when a negative case corrupts content.
    def metadata_inventory(self):
        return {name: protocol.inode(self.metadata.root if name == '.' else self.metadata.root / name)
                for name in self.metadata.header['inodes']}

    # Observe every original initialized SQLite bank/mode/owner allocation before and after new work.
    def sql_inventory(self):
        return {**{name: protocol.inode(self.sql.directory if name == '.' else self.sql.directory / name)
            for name in self.sql.header['inodes']},
            'sqlite-mode': protocol.inode(self.store.root / 'sqlite-mode'),
            'store-lock': protocol.inode(self.store.root / 'lock')}

    # Produce the real graph once, optionally stopping before the original submission effect.
    def submitted(self, *, submit=True):
        self.client, self.birth = self.nightly._initialize(self.context, raw_checkpoint=self.raw, native_io=self.nightly_io)
        self.previous = self.nightly._close(self.context, self.client, '2019-02-28', birth=self.birth,
            previous=self.birth, raw_checkpoint=self.raw, native_io=self.nightly_io)
        prior = self.nightly.read_lifecycle(self.previous, raw_checkpoint=self.raw)['value']
        body = demand.encoded({'scope': 'SYNTHETIC_RESERVED_OUTCOME_CONTEXT',
                              'window': {'completed_at': '2019-03-01T14:45:00Z'}})
        self.stage = self.stage_ns['_Stages'](self.nightly, self.client, self.raw, self.io,
            session='2019-03-01', context={'raw': body.decode(), 'sha256': hashlib.sha256(body).hexdigest()},
            lineage={'schema': self.bridge.LINEAGE, 'birth': self.birth, 'previous_nightly': self.previous,
                'context': prior['context'], 'context_identity': prior['context_identity']})
        registry_value = mapping()
        pages = {'origin': 'SYNTHETIC_RESERVED_CYCLE_INPUTS', 'declaration': 'NO_PROVIDER_ACQUISITION',
            'pages': {kind: {kind: {'AAPL': []}, 'next_page_token': None} for kind in ('quotes', 'trades')}}
        self.stage._prepare(registry_value, pages)
        order = {'symbol': 'AAPL', 'side': 'buy', 'qty': 5, 'client_order_id': 'SYNTHETIC-reserved-outcome'}
        self.stage._run('DECISION_FROZEN', {'candidate': order})
        self.order = order
        self.inputs = {'schema': self.final_ns['REQUEST'], 'at': '2019-03-01T14:45:33+00:00',
                       'prices': {'AAPL': 100}, 'phase': 'market'}
        if submit:
            self.submit_original()

    # Submit only the original frozen order through its actual bounded stage capabilities.
    def submit_original(self):
        self.submission = self.stage._run('SUBMISSION_CAPTURED', {'order': self.order,
            'observe': {'at': '2019-03-01T14:45:31.200000+00:00', 'marks': {'AAPL': 100}, 'market_open': True},
            'latch': {'session': '2019-03-01', 'scope': 'SYNTHETIC_LATCH'}})
        self.final = self.final_ns['_Final'](self.stage)

    # Close the original Store without deleting any native or evidence files.
    def close(self):
        require(paper.save_state is self.legacy.SAVE_STATE and native.ReplayBroker._submit is self.legacy.SUBMIT,
                'Original native globals changed')
        self.store.close()
