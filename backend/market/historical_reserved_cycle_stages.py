"""PRIVATE synthetic Cycle stages; final resolution and genuine entry stay closed.

Exact source/head/input-bound allowances precede preparation and each callback.
Native broker/paper/latch effects are explicit bounded capabilities, not a model
or native send_due replacement. SQLite/directory/latch capacity is unadmitted.
"""
from copy import deepcopy
from contextlib import contextmanager
from datetime import UTC, date, datetime
from hashlib import sha256
import json
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
from backend.market import historical_reserved_protocol as protocol
from backend.market import historical_timing_packet as packet
from backend.market import replay_broker as native
from backend.market.historical_packet_store import Store, StorePause

SCHEMA = 'synthetic-reserved-cycle-stages/2'
PAPER_SCHEMA = 'synthetic-cycle-prepared-paper/1'
PHASES = ('PREPARE', 'DECISION_FROZEN', 'SUBMISSION_CAPTURED')
OBSERVE = native.ReplayBroker.observe
SUBMIT = native.ReplayBroker._submit
SUBMIT_MARKET = native.ReplayBroker.submit_market
DUE = intraday_orders.due
LOAD_STATE = paper.load_state
LOAD_CODE = paper.load_state.__code__
STATE_JSON = paper._state_json
STATE_JSON_CODE = paper._state_json.__code__
STATE_TYPE = paper.PaperState


# Preserve public genuine refusal before constructing a producer or allocating anything.
def execute(*args, **kwargs):
    raise StorePause('Reserved Cycle genuine admission incomplete; PAUSED before effects')


# Bind every source participating in these private stage receipts and reservations.
def sources():
    return {**raw_nightly.sources(), **{str(Path(module.__file__)):
        sha256(Path(module.__file__).read_bytes()).hexdigest() for module in
        (bridge, bridge.cycle, codec, cas, paper, intraday_orders)},
        str(Path(__file__)): sha256(Path(__file__).read_bytes()).hexdigest()}


# Hash the original native representation without saving, normalizing or copying its state graph.
def prepared_bytes(state, limit):
    physical._require(type(state) is paper.PaperState, 'Exact owned native PaperState required')
    hashed, length = sha256(), 0
    for text in json.JSONEncoder(indent=2, default=paper._state_json).iterencode(state):
        raw = text.encode()
        length += len(raw)
        physical._require(length <= limit, 'Finite prepared native paper byte bound')
        hashed.update(raw)
    return {'sha256': hashed.hexdigest(), 'length': length}


# Authenticate persisted preparation metadata without loading or reconstructing a native state object.
def verify_prepared_paper(nightly, original):
    value, declared = original['prepared_paper'], original['declaration']
    if declared['phase'] != 'SUBMISSION_CAPTURED':
        physical._require(value is None, 'Only submission owns prepared native paper')
        return None
    physical._require(type(value) is dict and set(value) == {'schema', 'identity', 'account',
        'source_sha256', 'head', 'declaration_sha256', 'native_io_sha256', 'preimage', 'native_bytes'}
        and value['schema'] == PAPER_SCHEMA and value['identity'] == nightly.store.identity
        and value['account'] == str(nightly.root)
        and value['source_sha256'] == sha256(Path(__file__).read_bytes()).hexdigest()
        and value['head'] == original['pre_head']
        and value['declaration_sha256'] == packet._digest(declared)
        and value['native_io_sha256'] == original['native_io']['reservation_sha256']
        and type(value['preimage']) is dict and set(value['preimage']) == {'sha256', 'length', 'device', 'inode'}
        and type(value['native_bytes']) is dict and set(value['native_bytes']) == {'sha256', 'length'}
        and value['native_bytes'] == {key: value['preimage'][key] for key in ('sha256', 'length')},
        'Exact original prepared native paper binding required')
    auxiliary = legacy.admitted.decoded(protocol.read(nightly,
        nightly.root / 'operations' / ('reserved-cycle-' + declared['cycle']) / declared['phase']
            / 'reserved-native-save.json', legacy))
    physical._require(value['preimage'] == auxiliary['before']['current'],
                      'Prepared native paper must bind the original native preimage')
    return value


# Retain one exact pre-effect native object; this is not full transition or RAM admission.
class _PreparedPaper:
    # Materialize before the callback and bind exact native bytes to the original armed phase.
    def __init__(self, owner, declaration):
        self.owner, self.state, self.original, self.closed, self.handed = owner, None, None, False, False
        try:
            owner._guard()
            owner.io._lease()
            preimage = deepcopy(owner.io.cursor['current'])
            path = paper.state_path(owner.nightly.root)
            physical._require(preimage is not None and reserved_io.writer_module._image(path) == preimage,
                              'Original prepared paper preimage required')
            owner.nightly.store._point('reserved_paper_before_load')
            self.state = self.original = paper.load_state(owner.nightly.root)
            native_bytes = prepared_bytes(self.state, owner.checkpoint.limits['raw_bytes'])
            physical._require(native_bytes == {key: preimage[key] for key in ('sha256', 'length')}
                and reserved_io.writer_module._image(path) == preimage,
                'Prepared native load/serialization changed the original bytes')
            self.binding = {'schema': PAPER_SCHEMA, 'identity': owner.nightly.store.identity,
                'account': str(owner.nightly.root), 'source_sha256': sha256(Path(__file__).read_bytes()).hexdigest(),
                'head': owner.nightly.expected_head, 'declaration_sha256': packet._digest(declaration),
                'native_io_sha256': owner.io.evidence()['reservation_sha256'],
                'preimage': preimage, 'native_bytes': native_bytes}
            self.raw = legacy.admitted.encoded(self.binding)
            owner._order(declaration['inputs']['order'], state=self.state)
            owner._guard()
            owner.io._lease()
            owner.nightly.store._point('reserved_paper_prepared')
        except BaseException:
            self.close()
            raise

    # Check frozen metadata and original preimage before every capability, without rereading native JSON.
    def check(self, original, verb, counts):
        physical._require(not self.closed and self.state is self.original
            and type(self.state) is paper.PaperState
            and legacy.admitted.encoded(self.binding) == self.raw
            and verify_prepared_paper(self.owner.nightly, original) == self.binding,
            'Original owned prepared native paper required')
        if counts.get('save', 0) == 0:
            physical._require(reserved_io.writer_module._image(paper.state_path(self.owner.nightly.root))
                == self.binding['preimage'], 'Live prepared paper preimage changed')
        if verb in ('observe', 'submit'):
            physical._require(not self.handed and prepared_bytes(self.state,
                self.owner.checkpoint.limits['raw_bytes']) == self.binding['native_bytes'],
                'Unhanded prepared native paper changed before effects')

    # Release only this scope's references, including on preparation failure or callback exceptions.
    def close(self):
        self.closed, self.state, self.original = True, None, None


# Expose only the once-per-stage effects whose exact inputs were already reserved.
class _Effects:
    # Keep a detached declaration and private counters under one exact source-bound lease.
    def __init__(self, owner, phase, declaration):
        self.owner, self.phase, self.declaration = owner, phase, deepcopy(declaration)
        self.counts, self.order = {}, None

    # Bind every effect to the original persisted inputs and lease before charging or acting.
    def _claim(self, verb):
        owner = self.owner
        owner._guard()
        owner.io._lease()
        directory = owner._directory(self.phase)
        original, _ = owner._read(directory / 'reservation.json')
        declaration = owner._declaration(self.phase, self.declaration)
        physical._require(not owner.io.failed and owner.io.directory == directory
            and legacy.admitted.encoded(original['declaration']) == legacy.admitted.encoded(declaration)
            and original['sources'] == sources()
            and original['native_io']['reserved_cas'] == owner.io.reserved_cas
            and original['native_io']['effect_binding'] == owner.io.effect_binding == packet._digest(declaration),
            'Original reserved Cycle capability inputs/lease changed')
        physical._require(self.phase == 'SUBMISSION_CAPTURED' and self.counts.get(verb, 0) == 0,
                          'Unreserved/repeated Cycle capability')
        physical._require(owner.prepared is not None, 'Original prepared native paper scope required')
        owner.prepared.check(original, verb, self.counts)
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
            self.owner._poison_prepared()
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

    # Return only the exact pre-effect owned object once after actual submission, without loading JSON.
    def load(self):
        with self._scope('load'):
            prepared = self.owner.prepared
            physical._require(self.order is not None and not prepared.handed,
                              'Original prepared paper may be handed off once after submit')
            prepared.handed = True
            self.owner.nightly.store._point('reserved_paper_handed')
            return prepared.state

    # Save the complete native state through the original reserved writer after actual submit.
    def save(self, state):
        with self._scope('save'):
            physical._require(self.order is not None, 'Original native submission required before save')
            physical._require(self.counts.get('load') == 1 and self.owner.prepared.handed
                and state is self.owner.prepared.state, 'Save requires the exact once-handed prepared state')
            return self.owner.io.save(self.owner.nightly.root, state)

    # Publish the preclaimed fixed latch when bound, retaining ordinary path semantics otherwise.
    def latch(self):
        with self._scope('latch'):
            physical._require(self.counts.get('save') == 1, 'Native submission save must precede latch')
            owner = self.owner
            path = bridge.cycle.entry_timing.latch_path(owner.nightly.root, date.fromisoformat(owner.session))
            namespace = protocol.pool(owner.nightly)
            if namespace is None:
                path.parent.mkdir(mode=0o700, exist_ok=True)
                legacy.write_once(path, legacy.admitted.encoded(self.declaration['latch']))
            else:
                namespace.write_once(owner._directory(self.phase), 'latch',
                                     legacy.admitted.encoded(self.declaration['latch']))
            return str(path)


# Produce only private synthetic preparation/decision/submission, never resolve or finalize.
class _Stages:
    # Bind exact objects and stable context/lineage independently of mutable stage inputs.
    def __init__(self, nightly, client, checkpoint, native_io, *, session, context, lineage):
        physical._require(type(nightly) is raw_nightly.RawNightly and type(client) is native.ReplayBroker
            and type(nightly.store) is Store and type(nightly.store.blob_reservation) is cas.ReservedCAS
            and type(native_io) is reserved_io.SyntheticNativeIO, 'Exact private reserved Cycle objects required')
        self.nightly, self.client, self.checkpoint, self.io = nightly, client, checkpoint, native_io
        self.prepared = None
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
            and native.ReplayBroker.submit_market is SUBMIT_MARKET and intraday_orders.due is DUE
            and paper.load_state is LOAD_STATE and paper.load_state.__code__ is LOAD_CODE
            and paper._state_json is STATE_JSON and paper._state_json.__code__ is STATE_JSON_CODE
            and paper.PaperState is STATE_TYPE,
            'Original private Cycle native bindings required')

    # Read bounded original protocol metadata without capturing or invoking a callback.
    def _read(self, path):
        raw = protocol.read(self.nightly, path, legacy)
        return legacy.admitted.decoded(raw), sha256(raw).hexdigest()

    # Durably refuse later capabilities after caught preparation or owned-object uncertainty.
    def _poison_prepared(self):
        self.io.failed = True
        self.nightly.store.blob_reservation.poison(self.io.reserved_cas)
        if self.nightly.store.directory_binding is not None:
            self.nightly.store.directory_binding.poison()

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
        protocol.verify(self.nightly, directory, phase=phase, head=original['pre_head'],
                        inputs=packet._digest(declaration))
        physical._require(set(original) == {'schema', 'declaration', 'sources', 'pre_head', 'native_io', 'prepared_paper'}
            and original['schema'] == SCHEMA
            and original['declaration'] == declaration and original['sources'] == sources()
            and original['pre_head'] == original['native_io']['reserved_cas']['head']
            and original['native_io']['effect_binding'] == packet._digest(declaration),
            'Conflicting reserved Cycle declaration')
        preparation = verify_prepared_paper(self.nightly, original)
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
        physical._require(receipt['detail'].get('prepared_paper') == preparation,
                          'Original receipt/pre-effect native paper binding differs')
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
            protocol.write(self.nightly, directory / 'result.json', legacy.admitted.encoded(marker), legacy)
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
        if protocol.exists(self.nightly, directory):
            return declaration, self._recover(phase, declaration)
        store = self.nightly.store
        physical._require(store.snapshot()['head'] == self.nightly.expected_head,
                          'Original reserved Cycle authoritative head required')
        if phase == 'PREPARE':
            physical._require(store.snapshot()['next_stage'] == 'PRIOR_VERIFIED', 'Original empty Cycle stage required')
            self._prior()
            if protocol.pool(self.nightly) is None:
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
        protocol.create(self.nightly, directory, phase=phase, inputs=packet._digest(declaration),
            latch_session=inputs['latch']['session'] if phase == 'SUBMISSION_CAPTURED' else None)
        self.io.begin(self.nightly, directory, legacy, effect_binding=packet._digest(declaration))
        try:
            self.prepared = _PreparedPaper(self, declaration) if phase == 'SUBMISSION_CAPTURED' else None
            value = {'schema': SCHEMA, 'declaration': declaration, 'sources': sources(),
                'pre_head': self.nightly.expected_head, 'native_io': self.io.evidence(),
                'prepared_paper': None if self.prepared is None else deepcopy(self.prepared.binding)}
            raw = legacy.admitted.encoded(value)
            protocol.write(self.nightly, directory / 'reservation.json', raw, legacy)
            if self.prepared is not None:
                self.nightly.store._point('reserved_paper_reserved')
        except BaseException:
            self._poison_prepared()
            raise
        return declaration, (directory, sha256(raw).hexdigest())

    # Persist the exact prepared receipt before any authoritative stage/head commitment.
    def _prepared(self, phase, directory, reservation_sha, reference):
        value = {'schema': SCHEMA, 'reservation_sha256': reservation_sha, 'receipt': reference,
                 'native_io': self.io.evidence()}
        protocol.write(self.nightly, directory / 'prepared.json', legacy.admitted.encoded(value), legacy)
        self.nightly.store._point('reserved_cycle_prepared_' + phase)

    # Recheck source/input/current bytes after preparation and before the Store commitment.
    def _before_commit(self, phase, declaration, directory, reference):
        self._guard()
        self.io._lease()
        original, reservation_sha = self._read(directory / 'reservation.json')
        prepared, _ = self._read(directory / 'prepared.json')
        receipt = bridge.cycle._read_receipt(self.nightly.store, reference, self.nightly.pins(),
                                            raw_checkpoint=self.checkpoint)
        preparation = verify_prepared_paper(self.nightly, original)
        physical._require(receipt['detail'].get('prepared_paper') == preparation
            and (phase != 'SUBMISSION_CAPTURED' or self.prepared is not None
                and legacy.admitted.encoded(preparation) == self.prepared.raw
                == legacy.admitted.encoded(self.prepared.binding)),
            'Original prepared native paper changed before commitment')
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
            if self.prepared is not None:
                self.prepared.close()
                self.prepared = None
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
        self._order(inputs['candidate'] if phase == 'DECISION_FROZEN' else inputs['order'],
                    state=None if self.prepared is None else self.prepared.state)
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
        latch_before = bridge.latch_bytes(store, self.nightly.root, self.session)
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
                and latch_before == bridge.latch_bytes(store, self.nightly.root, self.session),
                'Decision changed native paper/broker/latch/effects')
            physical._require(type(output) is dict and set(output) == {'order'}
                and output['order'] == inputs['candidate'], 'Original reserved single-order decision required')
            self._order(output['order'])
        else:
            physical._require(effects.counts == {'observe': 1, 'submit': 1, 'load': 1, 'save': 1, 'latch': 1},
                              'Complete original bounded submission effects required')
        store._point('reserved_cycle_effect_returned_' + phase)
        reference = self._receipt(phase, {'output': output, 'effects': effects.counts,
            'prepared_paper': None if self.prepared is None else deepcopy(self.prepared.binding)}, reservation_sha)
        self._prepared(phase, directory, reservation_sha, reference)
        self._before_commit(phase, declaration, directory, reference)
        return reference

    # Require an unsent native due row in this narrow synthetic market-order lane.
    def _order(self, selected, *, state=None):
        physical._require(type(selected) is dict
            and set(selected) == {'symbol', 'side', 'qty', 'client_order_id'},
            'Finite single-order decision declaration required')
        state = paper.load_state(self.nightly.root) if state is None else state
        physical._require(type(state) is paper.PaperState, 'Original native due-row state required')
        matches = [row for row in intraday_orders.due(state,
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


# Read completed producer stages without constructing its broker, executor or write scope.
class _StageReader:
    # Derive one original metadata view from the fixed preparation reservation.
    def __init__(self, nightly, checkpoint, cycle):
        self.nightly, self.checkpoint, self.cycle = nightly, checkpoint, physical._digest(cycle)
        self._guard()
        self.root = nightly.root / 'operations' / ('reserved-cycle-' + cycle)
        original, _ = self._read(self._directory('PREPARE') / 'reservation.json')
        declared = original['declaration']
        self.session, self.context, self.lineage = declared['session'], declared['context'], declared['lineage']
        physical._require(cycle == packet._digest({'schema': SCHEMA, 'identity': nightly.store.identity,
            'previous_nightly': self.lineage['previous_nightly'], 'session': self.session}),
            'Original reserved stage cycle identity required')

    # Check only metadata authority; no live broker, callback, save or CAS arm occurs.
    def _guard(self):
        physical._require(type(self.nightly) is raw_nightly.RawNightly
            and type(self.nightly.store) is Store
            and type(self.nightly.store.blob_reservation) is cas.ReservedCAS
            and self.nightly.root.resolve().is_relative_to(self.nightly.store.root.resolve()),
            'Original reserved stage metadata reader required')
        self.nightly._checkpoint(self.checkpoint)

    # Reuse the producer's bounded physical reader without constructing a producer.
    def _read(self, path):
        return _Stages._read(self, path)

    # Reuse only its fixed phase-to-directory mapping, never a caller-supplied path.
    def _directory(self, phase):
        return _Stages._directory(self, phase)

    # Validate original stage evidence and completed lease with all mutation disabled.
    def read(self, phase):
        directory = self._directory(phase)
        original, _ = self._read(directory / 'reservation.json')
        declaration = original['declaration']
        physical._require(set(declaration) == {'schema', 'phase', 'cycle', 'identity', 'sources',
            'session', 'context', 'lineage', 'inputs', 'executor_sha256', 'executor_name'}
            and declaration['schema'] == SCHEMA and declaration['phase'] == phase
            and declaration['cycle'] == self.cycle and declaration['identity'] == self.nightly.store.identity
            and declaration['sources'] == sources() and declaration['session'] == self.session
            and declaration['context'] == self.context and declaration['lineage'] == self.lineage,
            'Original source/context-bound stage declaration required')
        value = _Stages._recover(self, phase, declaration, finish=False)
        auxiliary, _ = self._read(directory / 'reserved-native-save.json')
        lease = original['native_io']['reserved_cas']
        _, group = self.nightly.store.blob_reservation.group(lease)
        physical._require(group['status'] == 'COMPLETE' and group['result'] == value['receipt']
            and lease['operation'] == reserved_io.operation_identity(self.nightly, directory, packet._digest(declaration))
            and auxiliary['trade_sha256'] == declaration['executor_sha256']
            and Path(auxiliary['trade_path']).is_absolute()
            and declaration['executor_name'] in {node.co_name for node in compile(
                Path(auxiliary['trade_path']).read_bytes(), auxiliary['trade_path'], 'exec',
                dont_inherit=True).co_consts if hasattr(node, 'co_name')},
            'Original completed stage lease/executor required')
        return value


# Authenticate every original stage and complete preparation/page ancestry before continuation.
def read_committed(nightly, checkpoint, *, cycle, submission_head):
    reader = _StageReader(nightly, checkpoint, cycle)
    prepared, decision, submitted = (reader.read(phase) for phase in PHASES)
    physical._require(submitted['head'] == submission_head
        and submitted['entry']['parent'] == decision['head']
        and decision['entry']['parent'] == prepared['head'],
        'Original reserved stage immediate ancestry required')
    return {'prepared': prepared, 'decision': decision, 'submission': submitted,
            'session': reader.session, 'context': reader.context, 'lineage': reader.lineage}
