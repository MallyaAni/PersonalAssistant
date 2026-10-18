"""PRIVATE synthetic Cycle stages; final resolution and genuine entry stay closed.

Exact source/head/input-bound allowances precede preparation and each callback.
Native broker/paper/latch effects are explicit bounded capabilities, not a model
or native send_due replacement. SQLite/directory/latch capacity is unadmitted.
"""
from copy import deepcopy
from contextlib import contextmanager
from datetime import UTC, date, datetime
from hashlib import sha256
from pathlib import Path

from backend.agents.trading.desk import paper, intraday_orders
from backend.market import historical_broker_checkpoint as codec
from backend.market import historical_conditional_nightly as legacy
from backend.market import historical_packet_demand as demand
from backend.market import historical_packet_registry as registry
from backend.market import historical_physical_checkpoint as physical
from backend.market import historical_raw_cycle as bridge
from backend.market import historical_raw_nightly as raw_nightly
from backend.market import historical_reserved_blob_store as cas
from backend.market import historical_reserved_native_io as reserved_io
from backend.market import historical_timing_packet as packet
from backend.market import replay_broker as native
from backend.market.historical_packet_store import Store, StorePause

SCHEMA = 'synthetic-reserved-cycle-stages/1'
PHASES = ('PREPARE', 'DECISION_FROZEN', 'SUBMISSION_CAPTURED')
OBSERVE = native.ReplayBroker.observe
SUBMIT = native.ReplayBroker._submit
SUBMIT_MARKET = native.ReplayBroker.submit_market
DUE = intraday_orders.due


# Preserve public genuine refusal before constructing a producer or allocating anything.
def execute(*args, **kwargs):
    raise StorePause('Reserved Cycle genuine admission incomplete; PAUSED before effects')


# Bind every source participating in these private stage receipts and reservations.
def sources():
    return {**raw_nightly.sources(), **{str(Path(module.__file__)):
        sha256(Path(module.__file__).read_bytes()).hexdigest() for module in
        (bridge, bridge.cycle, codec, cas, paper, intraday_orders)},
        str(Path(__file__)): sha256(Path(__file__).read_bytes()).hexdigest()}


# Expose only the once-per-stage effects whose exact inputs were already reserved.
class _Effects:
    # Keep a detached declaration and private counters under one exact source-bound lease.
    def __init__(self, owner, phase, declaration):
        self.owner, self.phase, self.declaration = owner, phase, deepcopy(declaration)
        self.counts, self.order = {}, None

    # Charge before any selected effect and refuse changed native functions or CAS uncertainty.
    def _claim(self, verb):
        owner = self.owner
        owner._guard()
        owner.io._lease()
        physical._require(self.phase == 'SUBMISSION_CAPTURED' and self.counts.get(verb, 0) == 0,
                          'Unreserved/repeated Cycle capability')
        self.counts[verb] = 1

    # Retain uncertainty even when the source-bound program catches an effect failure.
    @contextmanager
    def _scope(self, verb):
        try:
            self._claim(verb)
            yield
            self.owner._guard()
            self.owner.io._lease()
        except BaseException:
            self.owner.io.failed = True
            self.owner.nightly.store.blob_reservation.poison(self.owner.io.reserved_cas)
            raise

    # Observe only the exact supplied synthetic submission clock and marks, once.
    def observe(self):
        with self._scope('observe'):
            value = self.declaration['observe']
            self.owner.client.observe(value['at'], value['marks'], value['market_open'])

    # Submit only the exact committed decision's order after its reserved observation.
    def submit(self):
        with self._scope('submit'):
            physical._require(self.counts.get('observe') == 1, 'Reserved observation must precede submit')
            value = self.declaration['order']
            self.order = self.owner.client.submit_market(value['symbol'], value['qty'], value['side'],
                                                         value['client_order_id'])
            return deepcopy(self.order)

    # Read native paper only while the original submission lease remains active.
    def load(self):
        with self._scope('load'):
            return paper.load_state(self.owner.nightly.root)

    # Save the complete native state through the original reserved writer after actual submit.
    def save(self, state):
        with self._scope('save'):
            physical._require(self.order is not None, 'Original native submission required before save')
            return self.owner.io.save(self.owner.nightly.root, state)

    # Persist the declared synthetic latch once without claiming its directory/file capacity.
    def latch(self):
        with self._scope('latch'):
            physical._require(self.counts.get('save') == 1, 'Native submission save must precede latch')
            owner = self.owner
            path = bridge.cycle.entry_timing.latch_path(owner.nightly.root, date.fromisoformat(owner.session))
            path.parent.mkdir(mode=0o700, exist_ok=True)
            legacy.write_once(path, legacy.admitted.encoded(self.declaration['latch']))
            return str(path)


# Produce only private synthetic preparation/decision/submission, never resolve or finalize.
class _Stages:
    # Bind exact objects and stable context/lineage independently of mutable stage inputs.
    def __init__(self, nightly, client, checkpoint, native_io, *, session, context, lineage):
        physical._require(type(nightly) is raw_nightly.RawNightly and type(client) is native.ReplayBroker
            and type(nightly.store) is Store and type(nightly.store.blob_reservation) is cas.ReservedCAS
            and type(native_io) is reserved_io.SyntheticNativeIO, 'Exact private reserved Cycle objects required')
        self.nightly, self.client, self.checkpoint, self.io = nightly, client, checkpoint, native_io
        self.session, self.context, self.lineage = session, deepcopy(context), deepcopy(lineage)
        self._guard()
        physical._require(date.fromisoformat(session).isoformat() == session
            and type(context) is dict and set(context) == {'raw', 'sha256'}
            and sha256(context['raw'].encode()).hexdigest() == context['sha256']
            and type(lineage) is dict and set(lineage) == bridge.LINEAGE_KEYS
            and lineage['schema'] == bridge.LINEAGE, 'Exact Cycle context/Nightly lineage required')
        parsed = bridge.cycle.market.read_context(bridge.cycle.market.Context(context['raw'].encode(), context['sha256']))
        physical._require(parsed['window']['completed_at'][:10] == session, 'Cycle context session differs')
        self.window = parsed['window']
        self.cycle = packet._digest({'schema': SCHEMA, 'identity': nightly.store.identity,
            'previous_nightly': lineage['previous_nightly'], 'session': session})
        self.root = nightly.root / 'operations' / ('reserved-cycle-' + self.cycle)

    # Recheck the original account, source program, broker methods and finite checkpoint.
    def _guard(self):
        self.nightly._checkpoint(self.checkpoint)
        self.io.guard()
        physical._require(self.nightly.root == self.io.writer.root / 'work'
            and self.nightly.store.identity == self.io.writer.header['identity_sha256']
            and type(self.nightly.store.blob_reservation) is cas.ReservedCAS
            and native.ReplayBroker.observe is OBSERVE and native.ReplayBroker._submit is SUBMIT
            and native.ReplayBroker.submit_market is SUBMIT_MARKET and intraday_orders.due is DUE,
            'Original private Cycle native bindings required')

    # Read bounded original protocol metadata without capturing or invoking a callback.
    def _read(self, path):
        raw = legacy.physical(path)
        return legacy.admitted.decoded(raw), sha256(raw).hexdigest()

    # Fix the attempt by cycle/stage so changed inputs cannot obtain another operation.
    def _directory(self, phase):
        physical._require(phase in PHASES, 'Reserved Cycle phase required')
        return self.root / phase

    # Build the immutable stage declaration before allocating its operation or native work.
    def _declaration(self, phase, inputs):
        raw = legacy.admitted.encoded(inputs)
        physical._require(len(raw) <= physical.META, 'Finite reserved Cycle input bound')
        return {'schema': SCHEMA, 'phase': phase, 'cycle': self.cycle,
            'identity': self.nightly.store.identity, 'sources': sources(), 'session': self.session,
            'context': deepcopy(self.context), 'lineage': deepcopy(self.lineage), 'inputs': legacy.admitted.decoded(raw),
            'executor_sha256': self.io.trade_sha256, 'executor_name': self.io.trade.__name__}

    # Compare current paper/broker against the prior committed Nightly without CAS writes.
    def _prior(self):
        prior = self.nightly.read_lifecycle(self.lineage['previous_nightly'],
                                           raw_checkpoint=self.checkpoint)['value']
        birth = self.nightly.read_raw_birth(self.lineage['birth'], raw_checkpoint=self.checkpoint)
        physical._require(prior['phase'] == 'NIGHTLY_CLOSE'
            and prior['detail']['status'] == 'NATIVE_NIGHTLY_RETURNED'
            and all(prior[key] == self.lineage[key] for key in ('birth', 'context', 'context_identity'))
            and all(birth[key] == self.lineage[key] for key in ('context', 'context_identity'))
            and date.fromisoformat(self.session) == legacy.intraday_orders.next_session(date.fromisoformat(prior['session'])),
            'Original prior Nightly identity/session required')
        return reserved_io.current_components(self.nightly, self.client, prior['components'],
                                               self.checkpoint, legacy)

    # Capture only after arm and bind the stage's source/declaration link in its real receipt.
    def _receipt(self, phase, detail, reservation_sha):
        store, cycle = self.nightly.store, bridge.cycle
        reference = cycle._receipt(store, self.client, self.nightly.root, self.nightly.pins(),
            {'stage': phase, 'raw_nightly_lineage': self.lineage, **detail},
            session=date.fromisoformat(self.session), context=self.context, raw_checkpoint=self.checkpoint)
        value = cycle._read_receipt(store, reference, self.nightly.pins(), raw_checkpoint=self.checkpoint)
        value['reserved_cycle_stage'] = {'schema': SCHEMA, 'cycle': self.cycle, 'phase': phase,
            'reservation_sha256': reservation_sha, 'sources': sources()}
        return cycle._put(store, legacy.admitted.encoded(value))

    # Authenticate committed original bytes and optionally finish only their missing marker/seal.
    def _recover(self, phase, declaration, *, finish=True):
        self._guard()
        store, cycle, directory = self.nightly.store, bridge.cycle, self._directory(phase)
        original, reservation_sha = self._read(directory / 'reservation.json')
        physical._require(set(original) == {'schema', 'declaration', 'sources', 'pre_head', 'native_io'}
            and original['schema'] == SCHEMA
            and original['declaration'] == declaration and original['sources'] == sources()
            and original['pre_head'] == original['native_io']['reserved_cas']['head']
            and original['native_io']['effect_binding'] == packet._digest(declaration),
            'Conflicting reserved Cycle declaration')
        try:
            prepared, _ = self._read(directory / 'prepared.json')
        except FileNotFoundError as error:
            raise StorePause('OPEN reserved Cycle stage; never replay') from error
        physical._require(set(prepared) == {'schema', 'reservation_sha256', 'receipt', 'native_io'}
            and prepared['schema'] == SCHEMA and prepared['reservation_sha256'] == reservation_sha,
            'Original prepared Cycle stage required')
        reference = prepared['receipt']
        receipt = cycle._read_receipt(store, reference, self.nightly.pins(), raw_checkpoint=self.checkpoint)
        physical._require(receipt['reserved_cycle_stage'] == {'schema': SCHEMA, 'cycle': self.cycle,
            'phase': phase, 'reservation_sha256': reservation_sha, 'sources': sources()}
            and receipt['session'] == self.session and receipt['context'] == self.context
            and receipt['detail']['raw_nightly_lineage'] == self.lineage
            and prepared['native_io']['reserved_cas'] == original['native_io']['reserved_cas'],
            'Original reserved stage receipt/source differs')
        physical._require(receipt['detail']['stage'] == phase, 'Original reserved stage detail required')
        contents = [] if phase != 'SUBMISSION_CAPTURED' else [bridge.paper_content(
            receipt['components']['paper'], self.checkpoint, store.identity)]
        reserved_io.validate(self.nightly, directory, prepared['native_io'], contents,
                             legacy, original['native_io'])
        if phase == 'PREPARE':
            state = store.snapshot()
            try:
                result, _ = self._read(directory / 'result.json')
                head = result['head']
            except FileNotFoundError:
                head = state['head']
            entry = cycle._head_entry(store, head)
            physical._require(entry['stage'] == 'PACKETS_FINALIZED' and entry['cycle_sha256'] == self.cycle
                and entry['receipt_sha256'] == reference, 'Original prepared Cycle head required')
            detail, inputs = receipt['detail'], declaration['inputs']
            evidence = {key: body.encode() for key, body in inputs['evidence']}
            entity_registry = registry.registry(inputs['registry'].encode(), inputs['registry_sha256'], evidence)
            physical._require(detail['registry'] == entity_registry.sha256
                and store.read_blob(detail['registry'], limit=physical.META) == entity_registry.raw
                and detail['evidence'] == {key: key for key in evidence}
                and all(store.read_blob(key, limit=physical.META) == body for key, body in evidence.items())
                and store.read_blob(detail['packet'], limit=physical.META) == legacy.admitted.encoded(inputs['packet']),
                'Original retained registry/packet bytes differ')
            manifest = demand.read(demand.Demand(store.read_blob(detail['manifest'], limit=physical.META),
                                                detail['manifest']), entity_registry)
            pages = {query['sha256']: store.page_manifest(detail['manifest'], query['sha256'])
                     for query in manifest['queries']}
            physical._require(detail['pages'] == pages and all(len(pages[query['sha256']]) == 1
                and store.read_blob(pages[query['sha256']][0]['receipt']['body_sha256'], limit=65536)
                    == legacy.admitted.encoded(inputs['packet']['pages'][query['kind']])
                for query in manifest['queries']), 'Original synthetic query pages required')
            wait = cycle._head_entry(store, entry['parent'])
            frozen = cycle._head_entry(store, wait['parent'])
            prior = cycle._head_entry(store, frozen['parent'])
            physical._require([wait['stage'], frozen['stage'], prior['stage']]
                == ['WAIT_PACKETS', 'DEMAND_FROZEN', 'PRIOR_VERIFIED']
                and all(row['cycle_sha256'] == self.cycle for row in (wait, frozen, prior))
                and frozen['receipt_sha256'] == detail['manifest']
                and wait['receipt_sha256'] == detail['packet']
                and manifest['parent_sha256'] == prior['sha256']
                and manifest['prior']['inputs'] == prior['receipt_sha256']
                and prior['parent'] == original['pre_head'],
                'Original complete reserved preparation ancestry required')
            prior_receipt = cycle._read_receipt(store, prior['receipt_sha256'], self.nightly.pins(),
                                               raw_checkpoint=self.checkpoint)
            physical._require(prior_receipt['reserved_cycle_stage'] == {'schema': SCHEMA, 'cycle': self.cycle,
                'phase': 'PRIOR_VERIFIED', 'reservation_sha256': reservation_sha, 'sources': sources()}
                and prior_receipt['detail']['raw_nightly_lineage'] == self.lineage
                and prior_receipt['context'] == self.context,
                'Original reserved prior receipt required')
        else:
            entry = store.recover_operation(packet._digest({'cycle': self.cycle, 'stage': phase}))
            operation_row = store.connection.execute('SELECT inputs,parent FROM operations WHERE id=?',
                (packet._digest({'cycle': self.cycle, 'stage': phase}),)).fetchone()
            physical._require(entry['parent'] == original['pre_head'] and entry['receipt_sha256'] == reference
                and entry['stage'] == phase and entry['cycle_sha256'] == self.cycle
                and operation_row['inputs'] == packet._digest(declaration)
                and operation_row['parent'] == original['pre_head'],
                'Exact committed reserved Cycle operation required')
        marker = {'schema': SCHEMA, 'receipt': reference, 'head': entry['sha256'],
                  'reservation_sha256': reservation_sha}
        try:
            retained, _ = self._read(directory / 'result.json')
        except FileNotFoundError:
            physical._require(finish and store.snapshot()['head'] == entry['sha256'],
                              'Uncommitted/stale stage cannot finish result')
            legacy.write_once(directory / 'result.json', legacy.admitted.encoded(marker))
        else:
            physical._require(retained == marker, 'Original Cycle stage result differs')
        if finish:
            reserved_io.complete(self.nightly, original['native_io'], reference)
            if store.snapshot()['head'] == entry['sha256']:
                self.nightly.expected_head = entry['sha256']
        return {**marker, 'value': receipt, 'entry': entry}

    # Reserve source/head/inputs before preparation or a real decision/submission callback.
    def _start(self, phase, inputs):
        self._guard()
        declaration, directory = self._declaration(phase, inputs), self._directory(phase)
        if directory.exists():
            return declaration, self._recover(phase, declaration)
        store = self.nightly.store
        physical._require(store.snapshot()['head'] == self.nightly.expected_head,
                          'Original reserved Cycle authoritative head required')
        if phase == 'PREPARE':
            physical._require(store.snapshot()['next_stage'] == 'PRIOR_VERIFIED', 'Original empty Cycle stage required')
            self._prior()
            self.root.mkdir(mode=0o700)
        else:
            physical._require(store.snapshot()['cycle'] == self.cycle and store.snapshot()['next_stage'] == phase,
                              'Original next reserved Cycle stage required')
            previous_phase = 'PREPARE' if phase == 'DECISION_FROZEN' else 'DECISION_FROZEN'
            previous, _ = self._read(self._directory(previous_phase) / 'reservation.json')
            retained = self._recover(previous_phase, previous['declaration'], finish=False)
            physical._require(retained['head'] == self.nightly.expected_head,
                              'Original preceding reserved Cycle head required')
            reserved_io.current_components(self.nightly, self.client, retained['value']['components'],
                                           self.checkpoint, legacy)
            bridge.verify_latch(store, self.nightly.root, self.session, retained['value']['components']['latch'])
        directory.mkdir(mode=0o700)
        legacy.sync_directory(directory.parent)
        self.io.begin(self.nightly, directory, legacy, effect_binding=packet._digest(declaration))
        value = {'schema': SCHEMA, 'declaration': declaration, 'sources': sources(),
            'pre_head': self.nightly.expected_head, 'native_io': self.io.evidence()}
        raw = legacy.admitted.encoded(value)
        legacy.write_once(directory / 'reservation.json', raw)
        return declaration, (directory, sha256(raw).hexdigest())

    # Persist the exact prepared receipt before any authoritative stage/head commitment.
    def _prepared(self, phase, directory, reservation_sha, reference):
        value = {'schema': SCHEMA, 'reservation_sha256': reservation_sha, 'receipt': reference,
                 'native_io': self.io.evidence()}
        legacy.write_once(directory / 'prepared.json', legacy.admitted.encoded(value))
        self.nightly.store._point('reserved_cycle_prepared_' + phase)

    # Recheck source/input/current bytes after preparation and before the Store commitment.
    def _before_commit(self, phase, declaration, directory, reference):
        self._guard()
        self.io._lease()
        original, reservation_sha = self._read(directory / 'reservation.json')
        prepared, _ = self._read(directory / 'prepared.json')
        receipt = bridge.cycle._read_receipt(self.nightly.store, reference, self.nightly.pins(),
                                            raw_checkpoint=self.checkpoint)
        physical._require(original['declaration'] == declaration == self._declaration(phase, declaration['inputs'])
            and original['sources'] == sources() and self.io.evidence() == prepared['native_io']
            and prepared['receipt'] == reference and prepared['reservation_sha256'] == reservation_sha
            and receipt['reserved_cycle_stage'] == {'schema': SCHEMA, 'cycle': self.cycle,
                'phase': phase, 'reservation_sha256': reservation_sha, 'sources': sources()}
            and receipt['detail']['stage'] == phase and receipt['session'] == self.session
            and receipt['context'] == declaration['context']
            and receipt['detail']['raw_nightly_lineage'] == declaration['lineage'],
            'Prepared reserved Cycle inputs or cursor changed')
        reserved_io.current_components(self.nightly, self.client, receipt['components'], self.checkpoint, legacy)
        bridge.verify_latch(self.nightly.store, self.nightly.root, self.session, receipt['components']['latch'])
        if phase != 'PREPARE':
            physical._require(self.nightly.store.snapshot()['head'] == original['pre_head'],
                              'Prepared reserved Cycle pre-head changed')

    # Serialize the entire preparation boundary against private Nightly/native observers.
    def _prepare(self, entity_registry, packet_declaration):
        physical._require(legacy.LOCK.acquire(blocking=False), 'Concurrent reserved Cycle preparation')
        try:
            return self._prepare_once(entity_registry, packet_declaration)
        except BaseException:
            self.io.failed = True
            raise
        finally:
            legacy.LOCK.release()

    # Own the real prior/demand/wait/packet Store progression under one pre-effect lease.
    def _prepare_once(self, entity_registry, packet_declaration):
        physical._require(type(entity_registry) is registry.Registry
            and packet_declaration.get('origin') == 'SYNTHETIC_RESERVED_CYCLE_INPUTS',
            'Explicit synthetic registry/packet declaration required')
        registry.registry(entity_registry.raw, entity_registry.sha256, dict(entity_registry.evidence))
        inputs = {'registry': entity_registry.raw.decode(), 'registry_sha256': entity_registry.sha256,
            'evidence': [[digest, body.decode()] for digest, body in entity_registry.evidence],
            'packet': packet_declaration}
        declaration, opened = self._start('PREPARE', inputs)
        if type(opened) is dict:
            return opened
        directory, reservation_sha = opened
        store = self.nightly.store
        try:
            reference = self._prepare_evidence(entity_registry, packet_declaration, declaration, directory, reservation_sha)
        except BaseException:
            self.io.failed = True
            store.blob_reservation.poison(self.io.reserved_cas)
            raise
        entry = store.append(expected_head=store.snapshot()['head'], cycle_sha256=self.cycle,
                             stage='PACKETS_FINALIZED', receipt_sha256=reference)
        store._point('reserved_cycle_committed_PREPARE')
        self.nightly.expected_head = entry['sha256']
        return self._recover('PREPARE', declaration)

    # Serialize the whole callback stage against private Nightly/native observers.
    def _run(self, phase, inputs):
        physical._require(legacy.LOCK.acquire(blocking=False), 'Concurrent reserved Cycle stage')
        try:
            return self._run_once(phase, inputs)
        except BaseException:
            self.io.failed = True
            raise
        finally:
            legacy.LOCK.release()

    # Execute a source-bound synthetic decision/submission only after both reservations exist.
    def _run_once(self, phase, inputs):
        physical._require(phase in PHASES[1:], 'Decision/submission phase required')
        declaration, opened = self._start(phase, inputs)
        if type(opened) is dict:
            return opened
        directory, reservation_sha = opened
        store = self.nightly.store
        operation = packet._digest({'cycle': self.cycle, 'stage': phase})
        store.reserve_operation(operation=operation, expected_head=self.nightly.expected_head,
            cycle=self.cycle, stage=phase, inputs=packet._digest(declaration))
        try:
            reference = self._produce(phase, inputs, declaration, directory, reservation_sha)
        except BaseException:
            self.io.failed = True
            store.blob_reservation.poison(self.io.reserved_cas)
            raise
        entry = store.complete_operation(operation, reference)
        store._point('reserved_cycle_committed_' + phase)
        self.nightly.expected_head = entry['sha256']
        return self._recover(phase, declaration)

    # Produce and validate evidence before commitment; any failure poisons the original lease.
    def _produce(self, phase, inputs, declaration, directory, reservation_sha):
        store = self.nightly.store
        self._order(inputs['candidate'] if phase == 'DECISION_FROZEN' else inputs['order'])
        if phase == 'SUBMISSION_CAPTURED':
            decision_dir = self._directory('DECISION_FROZEN')
            original, _ = self._read(decision_dir / 'reservation.json')
            prior = self._recover('DECISION_FROZEN', original['declaration'], finish=False)
            physical._require(prior['head'] == self.nightly.expected_head
                and inputs['order'] == prior['value']['detail']['output']['order']
                and inputs['latch']['session'] == self.session, 'Submission differs from frozen decision')
        before = reserved_io.writer_module._image(paper.state_path(self.nightly.root))
        broker_before = codec.encode(self.client, **self.nightly.pins())
        latch_path = bridge.cycle.entry_timing.latch_path(self.nightly.root, date.fromisoformat(self.session))
        latch_before = bridge.cycle._file(latch_path, absent=True)
        self.io._lease()
        effects = _Effects(self, phase, inputs)
        output = self.io.trade(phase=phase, inputs=deepcopy(inputs), effects=effects)
        self.io._lease()
        self.io.guard()
        raw_output = legacy.admitted.encoded(output)
        physical._require(len(raw_output) <= physical.META, 'Finite Cycle program output bound')
        output = legacy.admitted.decoded(raw_output)
        if phase == 'DECISION_FROZEN':
            physical._require(not effects.counts and before == reserved_io.writer_module._image(
                paper.state_path(self.nightly.root)) and broker_before == codec.encode(self.client, **self.nightly.pins())
                and latch_before == bridge.cycle._file(latch_path, absent=True),
                'Decision changed native paper/broker/latch/effects')
            physical._require(type(output) is dict and set(output) == {'order'}
                and output['order'] == inputs['candidate'], 'Original reserved single-order decision required')
            self._order(output['order'])
        else:
            physical._require(effects.counts == {'observe': 1, 'submit': 1, 'load': 1, 'save': 1, 'latch': 1},
                              'Complete original bounded submission effects required')
        store._point('reserved_cycle_effect_returned_' + phase)
        reference = self._receipt(phase, {'output': output, 'effects': effects.counts}, reservation_sha)
        self._prepared(phase, directory, reservation_sha, reference)
        self._before_commit(phase, declaration, directory, reference)
        return reference

    # Require an unsent native due row in this narrow synthetic market-order lane.
    def _order(self, selected):
        physical._require(type(selected) is dict
            and set(selected) == {'symbol', 'side', 'qty', 'client_order_id'},
            'Finite single-order decision declaration required')
        matches = [row for row in intraday_orders.due(paper.load_state(self.nightly.root),
            date.fromisoformat(self.session)) if row['client_order_id'] == selected['client_order_id']
            and row['symbol'] == selected['symbol'] and row['side'] == selected['side']]
        physical._require(len(matches) == 1 and type(selected['qty']) is int
            and 0 < selected['qty'] <= matches[0]['qty']
            and 'execution_policy' not in matches[0] and 'timing_policy' not in matches[0],
            'Original unsent due intent without native execution-policy admission required')

    # Retain preparation evidence under the original lease before its terminal head commit.
    def _prepare_evidence(self, entity_registry, packet_declaration, declaration, directory, reservation_sha):
        store = self.nightly.store
        retained_evidence = {digest: bridge.cycle._put(store, body) for digest, body in entity_registry.evidence}
        physical._require(all(key == value for key, value in retained_evidence.items()), 'Original registry evidence digest')
        prior = self._receipt('PRIOR_VERIFIED', {'origin': 'SYNTHETIC_RESERVED_CYCLE_INPUTS'}, reservation_sha)
        entry = store.append(expected_head=self.nightly.expected_head, cycle_sha256=self.cycle,
                             stage='PRIOR_VERIFIED', receipt_sha256=prior)
        state = paper.load_state(self.nightly.root)
        prior_refs = bridge.cycle._read_receipt(store, prior, self.nightly.pins(), raw_checkpoint=self.checkpoint)['components']
        value = demand.build(entity_registry, identity_sha256=store.identity, parent_sha256=entry['sha256'],
            completed_at=self.window['completed_at'], used=store.snapshot()['used'],
            prior={'ledger': prior_refs['broker'],
                'pending': packet._digest(state.pending), 'reservations': packet._digest(self.client.open_orders()),
                'actions': packet._digest(codec._pack(self.client._actions)), 'inputs': prior},
            held=sorted(name for name, qty in self.client._held.items() if qty > 0),
            legs=[{'client_order_id': row['client_order_id'], 'symbol': row['symbol'], 'side': row['side'],
                'qty': row['qty'], 'phase': 'market', 'session': self.session}
                for row in intraday_orders.due(state, date.fromisoformat(self.session))])
        store.declare(value, entity_registry)
        store.append(expected_head=store.snapshot()['head'], cycle_sha256=self.cycle,
                     stage='DEMAND_FROZEN', receipt_sha256=value.sha256)
        packet_ref = bridge.cycle._put(store, legacy.admitted.encoded(packet_declaration))
        store.append(expected_head=store.snapshot()['head'], cycle_sha256=self.cycle,
                     stage='WAIT_PACKETS', receipt_sha256=packet_ref)
        pages = self._pages(value, entity_registry, packet_declaration)
        reference = self._receipt('PREPARE', {'manifest': value.sha256, 'packet': packet_ref,
            'registry': bridge.cycle._put(store, entity_registry.raw), 'evidence': retained_evidence,
            'pages': pages}, reservation_sha)
        self._prepared('PREPARE', directory, reservation_sha, reference)
        self._before_commit('PREPARE', declaration, directory, reference)
        return reference

    # Retain explicitly synthetic terminal pages through real charged Store ingress, never HTTP.
    def _pages(self, manifest, entity_registry, declaration):
        parsed = demand.read(manifest, entity_registry)
        pages, result = declaration['pages'], {}
        physical._require(type(pages) is dict and set(pages) <= {'quotes', 'trades'}
            and len(parsed['queries']) <= 2
            and len({query['kind'] for query in parsed['queries']}) == len(parsed['queries']),
            'Finite one-page-per-kind synthetic ingress required')
        store = self.nightly.store
        for query in parsed['queries']:
            self.io._lease()
            raw = legacy.admitted.encoded(pages[query['kind']])
            physical._require(0 < len(raw) <= 65536 and pages[query['kind']].get('next_page_token') is None,
                              'Bounded synthetic terminal page required')
            attempt = packet._digest({'cycle': self.cycle, 'query': query['sha256'], 'page': 0})
            read = packet._digest({'attempt': attempt, 'read': 0})
            store.begin_attempt(attempt=attempt, demand_sha256=manifest.sha256,
                                query_sha256=query['sha256'], page=0, token=None)
            requested = datetime.now(UTC).isoformat()
            store.reserve_read(attempt, read, len(raw))
            store.confirm_read(read, raw)
            receipt = store.finish_attempt(attempt, status=200, complete=True, failure=None,
                requested_at=requested, received_at=datetime.now(UTC).isoformat())
            physical._require(receipt['market_packet_validation'] == 'NOT_PERFORMED',
                              'Synthetic pages must not claim market validation')
            result[query['sha256']] = store.page_manifest(manifest.sha256, query['sha256'])
        return result
