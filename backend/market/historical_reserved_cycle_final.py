"""PRIVATE reserved synthetic resolution/final composition; genuine entry stays closed.

One source/head/input-bound CAS phase precedes native flush, reconciliation and
save. Metadata recovery never resolves, folds, saves, captures or appends again.
Synthetic price proxies are not validated market packets or native Resolver use.
"""
from copy import deepcopy
from datetime import date
from hashlib import sha256
from pathlib import Path

from backend.agents.trading.desk import paper
from backend.market import historical_broker_checkpoint as codec
from backend.market import historical_conditional_nightly as legacy
from backend.market import historical_conditional_settlement as settlement
from backend.market import historical_physical_checkpoint as physical
from backend.market import historical_prepared_transition as transition
from backend.market import historical_request_admission as request_admission
from backend.market import historical_static_request_admission as static_admission
from backend.market import historical_finite_evidence_input as finite_evidence
from backend.market import historical_final_receipt_capacity as receipt_capacity
from backend.market import historical_prepared_orders as prepared_orders
from backend.market import historical_prepared_results as prepared_results
from backend.market import historical_raw_cycle as bridge
from backend.market import historical_reserved_cycle_stages as stages
from backend.market import historical_reserved_native_io as reserved_io
from backend.market import historical_reserved_protocol as protocol
from backend.market import historical_timing_packet as packet
from backend.market import replay_broker as native
from backend.market.historical_packet_store import StorePause

SCHEMA = 'synthetic-reserved-cycle-final/10'
RESULT_SCHEMA = 'synthetic-reserved-cycle-final/1'
INPUT_SCHEMA = 'synthetic-final-prepared-raw-input/1'
SAVED_SCHEMA = 'synthetic-final-saved-native-bytes/1'
REQUEST = 'synthetic-declared-native-flush/1'
FLUSH, FILL = native.ReplayBroker.flush, native.ReplayBroker._fill
PREPARED_INPUT = settlement._PreparedRawInput
RECONCILE = settlement.reconcile_raw
RECONCILE_CODE = RECONCILE.__code__
INPUT_METHODS = {name: getattr(PREPARED_INPUT, name).__code__ for name in
                 ('__init__', 'check', 'take', 'check_released', 'close')}
TRANSITION = transition.PreparedTransition
TRANSITION_METHODS = {name: getattr(TRANSITION, name).__code__ for name in
                      ('__init__', 'check', 'apply', 'check_released', 'close')}
ADMISSION, UNIQUE = static_admission.StaticAdmission, settlement._unique
UNIQUE_CODE = UNIQUE.__code__
REQUESTS, REQUESTS_CODE = settlement._requests, settlement._requests.__code__
ADMISSION_METHODS = {name: getattr(ADMISSION, name).__code__ for name in
                     ('__init__', 'check', 'consume', 'check_released', 'close')}
EVIDENCE_INPUT = finite_evidence.EvidenceInput
EVIDENCE_METHODS = {name: getattr(EVIDENCE_INPUT, name).__code__ for name in
                    ('__init__', 'check', 'consume', 'check_released', 'close')}
CAPACITY = receipt_capacity.ReceiptCapacity
CAPACITY_METHODS = {name: getattr(CAPACITY, name).__code__ for name in
                    ('__init__', 'check', 'consume', 'output', 'check_released', 'close')}
PREPARED_ORDERS = prepared_orders.PreparedOrders
ORDER_METHODS = {name: getattr(PREPARED_ORDERS, name).__code__ for name in
                 ('__init__', 'check', 'take', 'reconcile', 'check_released', 'close')}
PREPARED_RESULTS = prepared_results.PreparedResults
RESULT_METHODS = {name: getattr(PREPARED_RESULTS, name).__code__ for name in
                  ('__init__', 'check', 'begin', 'store', 'settle', 'reconcile', 'check_released', 'close')}


# Keep public genuine execution closed before constructing or reserving anything.
def execute(*args, **kwargs):
    raise StorePause('Reserved final genuine admission incomplete; PAUSED before effects')


# Bind the complete participating product sources independently of a callback identity.
def sources():
    transition.sources()
    return {**stages.sources(), str(Path(settlement.__file__)): sha256(
        Path(settlement.__file__).read_bytes()).hexdigest(),
        str(Path(transition.__file__)): sha256(Path(transition.__file__).read_bytes()).hexdigest(),
        str(Path(request_admission.__file__)): sha256(Path(request_admission.__file__).read_bytes()).hexdigest(),
        str(Path(static_admission.__file__)): sha256(Path(static_admission.__file__).read_bytes()).hexdigest(),
        str(Path(finite_evidence.__file__)): sha256(Path(finite_evidence.__file__).read_bytes()).hexdigest(),
        str(Path(receipt_capacity.__file__)): sha256(Path(receipt_capacity.__file__).read_bytes()).hexdigest(),
        str(Path(prepared_orders.__file__)): sha256(Path(prepared_orders.__file__).read_bytes()).hexdigest(),
        str(Path(prepared_results.__file__)): sha256(Path(prepared_results.__file__).read_bytes()).hexdigest(),
        str(Path(__file__)): sha256(Path(__file__).read_bytes()).hexdigest()}


# Name exactly one attempt for the original submission, independent of later input changes.
def operation(nightly, submission_head):
    physical._digest(submission_head)
    token = packet._digest({'schema': SCHEMA, 'identity': nightly.store.identity,
                            'submission_head': submission_head})
    return token, nightly.root / 'operations' / ('reserved-final-' + token)


# Validate finite explicit synthetic execution inputs without advancing any broker clock.
def request(value, session):
    raw = legacy.admitted.encoded(value)
    physical._require(len(raw) <= physical.META and type(value) is dict
        and set(value) == {'schema', 'at', 'prices', 'phase'} and value['schema'] == REQUEST
        and value['phase'] == 'market' and type(value['at']) is str
        and native._instant(value['at']).isoformat() == value['at']
        and native._instant(value['at']).astimezone(native.calendar.NEW_YORK).date().isoformat() == session
        and type(value['prices']) is dict and bool(value['prices']),
        'Exact finite synthetic resolution declaration required')
    native._prices(value['prices'])
    return legacy.admitted.decoded(raw)


# Read only the fixed final metadata under the same bounded physical contract as stages.
def read_file(nightly, path):
    raw = protocol.read(nightly, path, legacy)
    return legacy.admitted.decoded(raw), sha256(raw).hexdigest()


# Bind final bytes to the original phase and source-bound resolution declaration.
def link(value, reservation_sha, saved):
    return {'schema': SCHEMA, 'reservation_sha256': reservation_sha,
            'declaration_sha256': packet._digest(value['declaration']),
            'reserved_cas': value['native_io']['reserved_cas'], 'sources': sources(),
            'prepared_input_sha256': packet._digest(value['prepared_input']),
            'prepared_transition_sha256': packet._digest(value['prepared_transition']),
            'request_admission_sha256': packet._digest(value['request_admission']),
            'evidence_input_sha256': packet._digest(value['evidence_input']),
            'receipt_capacity_sha256': packet._digest(value['receipt_capacity']),
            'prepared_orders_sha256': packet._digest(value['prepared_orders']),
            'prepared_results_sha256': packet._digest(value['prepared_results']),
            'saved_bytes_sha256': packet._digest(saved)}


# Bind one original phase-owned save to its exact reconciled native bytes without JSON loading.
def saved_binding(value, reservation_sha, evidence, target):
    before, declared = value['prepared_input']['preimage'], value['declaration']
    physical._require(type(evidence) is dict and evidence['schema'] == reserved_io.SAVE_SCHEMA
        and type(evidence['saves']) is list and len(evidence['saves']) == 1
        and legacy.admitted.encoded({**evidence, 'saves': []}) == legacy.admitted.encoded(value['native_io'])
        and type(target) is dict and set(target) == {'schema', 'raw_sha256', 'raw_bytes'}
        and target['schema'] == 'native-paper-serialization/1'
        and type(target['raw_bytes']) is int and 0 < target['raw_bytes'] <= value['prepared_input']['raw_limit'],
        'Exact sole final save and bounded native target required')
    physical._digest(target['raw_sha256'])
    receipt = evidence['saves'][0]
    auxiliary = value['native_io']['native_directory']['save_allowance']
    physical._require(type(receipt) is dict and type(receipt['slot']) is int
        and type(auxiliary['first']) is int and type(auxiliary['count']) is int
        and auxiliary['count'] == 1 and receipt['slot'] == auxiliary['first']
        and receipt['slot'] >= 0 and legacy.admitted.encoded(receipt['prior']) == legacy.admitted.encoded(before)
        and type(receipt['state']) is dict and set(receipt['state']) == {'sha256', 'length', 'device', 'inode'}
        and all(type(receipt['state'][k]) is int and receipt['state'][k] > 0 for k in ('length', 'device', 'inode'))
        and receipt['state']['sha256'] == target['raw_sha256'] and receipt['state']['length'] == target['raw_bytes'],
        'Original phase-owned final slot/preimage/native bytes required')
    physical._digest(reservation_sha)
    return {'schema': SAVED_SCHEMA, 'identity': declared['identity'], 'account': value['prepared_input']['account'],
        'phase': 'OUTCOME_COMMITTED', 'head': declared['submission_head'], 'sources_sha256': packet._digest(sources()),
        'declaration_sha256': packet._digest(declared), 'prepared_input_sha256': packet._digest(value['prepared_input']),
        'reservation_sha256': reservation_sha, 'native_io_sha256': evidence['reservation_sha256'],
        'receipt_sha256': packet._digest(receipt), 'slot': receipt['slot'], 'state': deepcopy(receipt['state']),
        'native_bytes': deepcopy(target)}


# Own only finite saved-byte metadata while rechecking the actual original writer and file bytes.
class _SavedBytes:
    # Freeze the original sole save before later callbacks can mutate its descriptor or receipt.
    def __init__(self, owner, value, reservation_sha, target):
        self.owner = owner
        self.evidence = owner.io.evidence()
        self.target = deepcopy(target)
        self.binding = saved_binding(value, reservation_sha, self.evidence, self.target)
        self.original = legacy.admitted.encoded(self.binding)
        self.receipt = deepcopy(self.evidence['saves'][0])
        self.receipt_raw = legacy.admitted.encoded(self.receipt)
        self.check(value, reservation_sha)

    # Authenticate the phase cursor and original receipt against streaming held-file verification.
    def check(self, value, reservation_sha):
        owner = self.owner
        owner.io._lease()
        physical._require(not owner.io.failed
            and legacy.admitted.encoded(self.binding) == self.original
            and legacy.admitted.encoded(self.receipt) == self.receipt_raw
            and legacy.admitted.encoded(owner.io.evidence()) == legacy.admitted.encoded(self.evidence)
            and legacy.admitted.encoded(saved_binding(value, reservation_sha, self.evidence, self.target)) == self.original,
            'Original frozen final saved-byte binding required')
        writer = owner.io.writer
        receipt = writer.completed()
        auxiliary, _ = read_file(owner.nightly, owner.io.directory / 'reserved-native-save.json')
        expected = {'operation': None, 'next_slot': auxiliary['before']['next_slot'] + 1,
            'current': self.binding['state'], 'last': {'slot': self.binding['slot'],
                'receipt_sha256': physical._sha(physical._encoded(self.receipt))}}
        with writer._locked(shared=True):
            physical._require(legacy.admitted.encoded(receipt) == self.receipt_raw
                and auxiliary['before']['next_slot'] == self.binding['slot']
                and legacy.admitted.encoded(owner.io.cursor) == legacy.admitted.encoded(expected)
                and legacy.admitted.encoded(writer._control()) == legacy.admitted.encoded(expected)
                and reserved_io.writer_module._image(paper.state_path(owner.nightly.root)) == self.binding['state']
                and legacy.admitted.encoded(writer._control()) == legacy.admitted.encoded(expected),
                'Original final cursor/receipt/native inode bytes required')
        return deepcopy(self.binding)


# Authenticate the original pre-resolution preparation descriptor without materializing native paper.
def verify_input(nightly, checkpoint, directory, value):
    binding, declared = value['prepared_input'], value['declaration']
    physical._require(type(binding) is dict and set(binding) == {'schema', 'identity', 'account', 'phase',
        'head', 'sources_sha256', 'declaration_sha256', 'native_io_sha256', 'preimage', 'native_bytes', 'raw_limit'}
        and binding['schema'] == INPUT_SCHEMA and binding['identity'] == nightly.store.identity
        and binding['account'] == str(nightly.root) and binding['phase'] == 'OUTCOME_COMMITTED'
        and binding['head'] == declared['submission_head']
        and binding['sources_sha256'] == packet._digest(sources())
        and binding['declaration_sha256'] == packet._digest(declared)
        and binding['native_io_sha256'] == value['native_io']['reservation_sha256']
        and type(binding['raw_limit']) is int and binding['raw_limit'] == checkpoint.limits['raw_bytes']
        and type(binding['preimage']) is dict and set(binding['preimage']) == {'sha256', 'length', 'device', 'inode'}
        and binding['native_bytes'] == {'schema': 'native-paper-serialization/1',
            'raw_sha256': binding['preimage']['sha256'], 'raw_bytes': binding['preimage']['length']},
        'Exact original final input preparation binding required')
    auxiliary, _ = read_file(nightly, directory / 'reserved-native-save.json')
    physical._require(binding['preimage'] == auxiliary['before']['current'],
                      'Original prepared final input preimage required')
    return binding


# Authenticate the explicit derived transition mode without reconstructing native state on recovery.
def verify_transition(value):
    original, binding = value['prepared_input'], value['prepared_transition']
    expected = {'schema': transition.SCHEMA, 'sources': transition.sources(),
        'input_sha256': packet._digest(original), 'identity': original['identity'], 'account': original['account'],
        'phase': original['phase'], 'head': original['head'], 'native_io_sha256': original['native_io_sha256'],
        'native_bytes': original['native_bytes'], 'raw_limit': original['raw_limit']}
    physical._require(legacy.admitted.encoded(binding) == legacy.admitted.encoded(expected),
                      'Original explicitly derived transition descriptor required')
    return binding


# Read the original finite request admission without loading paper or rerunning its native-input predicate.
def verify_admission(value):
    return static_admission.read_descriptor(value['request_admission'], value['prepared_input'], REQUESTS,
        value['declaration']['request']['at'])


# Read only the original finite evidence strategy admission, never native state or settled rows.
def verify_evidence_input(value):
    return finite_evidence.read_descriptor(value['evidence_input'], value['prepared_input'])


# Read the original finite receipt byte allowance without estimating outcomes or loading native state.
def verify_capacity(value):
    capacity = receipt_capacity.read_descriptor(value['receipt_capacity'], value['prepared_input'])
    physical._require(capacity['declaration_bytes'] == len(legacy.admitted.encoded(value['declaration']))
        and capacity['source_bytes'] == len(legacy.admitted.encoded(sources()))
        and capacity['broker_sha256'] == value['declaration']['before']['broker'],
        'Original receipt allowance declaration/source/broker binding required')
    return capacity


# Read only the original prepared-container metadata without rebuilding rows or replaying reconciliation.
def verify_orders(value):
    return prepared_orders.read_descriptor(value['prepared_orders'], value['prepared_input'])


# Authenticate original result-storage membership without constructing or resolving any native record.
def verify_results(value):
    descriptor = prepared_results.read_descriptor(value['prepared_results'], value['prepared_input'])
    physical._require(descriptor['resolution_at'] == value['declaration']['request']['at'],
                      'Original prepared-result resolution clock required')
    return descriptor


# Derive exact source/head/input bindings from the original completed producer graph.
def declaration(nightly, checkpoint, submission_head, inputs):
    entry = bridge.cycle._head_entry(nightly.store, submission_head)
    graph = stages.read_committed(nightly, checkpoint, cycle=entry['cycle_sha256'],
                                  submission_head=submission_head)
    return {'schema': SCHEMA, 'identity': nightly.store.identity, 'submission_head': submission_head,
        'cycle': entry['cycle_sha256'], 'sources': sources(), 'session': graph['session'],
        'context': graph['context'], 'lineage': graph['lineage'],
        'stage_receipts': {k: graph[k]['receipt'] for k in ('prepared', 'decision', 'submission')},
        'before': graph['submission']['value']['components'], 'request': request(inputs, graph['session'])}


# Authenticate original stages, final prepared bytes and authoritative outcome without effects.
def validate(nightly, reference, checkpoint, *, require_result=True):
    store = nightly.store
    physical._require(store.blob_reservation is not None, 'Original reserved final Store required')
    final = bridge.read_final(store, reference, nightly.pins(),
        expected_head=nightly.expected_head, raw_checkpoint=checkpoint)
    submission_head, cycle = final['entry']['parent'], final['entry']['cycle_sha256']
    _, directory = operation(nightly, submission_head)
    value, reservation_sha = read_file(nightly, directory / 'reservation.json')
    physical._require(set(value) == {'schema', 'declaration', 'native_io', 'prepared_input', 'prepared_transition', 'request_admission', 'evidence_input', 'receipt_capacity', 'prepared_orders', 'prepared_results'} and value['schema'] == SCHEMA,
                      'Original reserved final reservation required')
    verify_input(nightly, checkpoint, directory, value)
    verify_transition(value)
    verify_admission(value)
    verify_evidence_input(value)
    capacity = verify_capacity(value)
    verify_orders(value)
    verify_results(value)
    physical._require(len(legacy.admitted.encoded(final['receipt'])) <= capacity['receipt_upper_bytes'],
                      'Original final receipt byte allowance differs')
    declared = value['declaration']
    protocol.verify(nightly, directory, phase='OUTCOME_COMMITTED', head=submission_head,
                    inputs=packet._digest(declared))
    physical._require(legacy.admitted.encoded(declared) == legacy.admitted.encoded(
        declaration(nightly, checkpoint, submission_head, declared['request'])),
        'Original reserved final stage/input lineage differs')
    prepared, _ = read_file(nightly, directory / 'prepared.json')
    physical._require(set(prepared) == {'schema', 'reservation_sha256', 'receipt', 'native_io', 'saved_bytes'}
        and prepared['schema'] == SCHEMA and prepared['reservation_sha256'] == reservation_sha
        and prepared['receipt'] == reference, 'Original reserved final prepared marker required')
    reserved_io.validate(nightly, directory, prepared['native_io'], [
        bridge.paper_content(final['receipt']['components']['paper'], checkpoint, store.identity)],
        legacy, value['native_io'])
    target = final['receipt']['raw_reconciliation']['evidence']['reconciled_native_serialization']
    saved = saved_binding(value, reservation_sha, prepared['native_io'], target)
    physical._require(legacy.admitted.encoded(prepared['saved_bytes']) == legacy.admitted.encoded(saved)
        and final['receipt'].get('reserved_cycle_final') == link(value, reservation_sha, saved)
        and bridge.paper_content(final['receipt']['components']['paper'], checkpoint, store.identity)
            == (saved['state']['sha256'], saved['state']['length']),
        'Original saved-byte descriptor/receipt/raw component required')
    lease = value['native_io']['reserved_cas']
    control, group = store.blob_reservation.group(lease)
    physical._require(value['native_io']['effect_binding'] == packet._digest(declared)
        and lease['head'] == submission_head
        and lease['operation'] == reserved_io.operation_identity(nightly, directory, packet._digest(declared))
        and group['status'] in ('ACTIVE', 'COMPLETE')
        and group['metadata_pending'] is None
        and (group['status'] == 'COMPLETE' or control['pending'] is None)
        and (group['result'] is None if group['status'] == 'ACTIVE' else group['result'] == reference),
        'Original reserved final phase required')
    resolved = final['receipt']['detail']['resolved']
    before_ref, after_ref = declared['before']['broker'], final['receipt']['components']['broker']
    before = codec.restore(store.read_blob(before_ref, limit=codec.CAPS['bytes']),
                           expected_sha256=before_ref, **nightly.pins())
    after = codec.restore(store.read_blob(after_ref, limit=codec.CAPS['bytes']),
                          expected_sha256=after_ref, **nightly.pins())
    physical._require(set(resolved) == {'stage', 'origin', 'request', 'fills'}
        and resolved['stage'] == 'OUTCOME_COMMITTED'
        and resolved['origin'] == 'SYNTHETIC_DECLARED_NATIVE_FLUSH_NOT_MARKET_RESOLVER'
        and resolved['request'] == declared['request'] and after._now.isoformat() == resolved['request']['at']
        and after._fills[:len(before._fills)] == before._fills
        and resolved['fills'] == after._fills[len(before._fills):]
        and set(before._orders) == set(after._orders)
        and before.attempt_history == after.attempt_history
        and all(row['client_order_id'] in before._orders for row in resolved['fills']),
        'Original resolved broker/fill declaration differs')
    marker = {'schema': RESULT_SCHEMA, 'reservation_sha256': reservation_sha,
              'receipt': reference, 'head': final['entry']['sha256']}
    if require_result:
        physical._require(group['status'] == 'COMPLETE'
            and read_file(nightly, directory / 'result.json')[0] == marker,
            'Original complete final result required before Nightly')
    return final, marker, value, prepared


# Require reserved final evidence before a private Nightly can use the generic raw bridge.
def read(nightly, reference, *, raw_checkpoint):
    return validate(nightly, reference, raw_checkpoint)[0]


# Compose one reserved native resolution, raw fold/save and original outcome commitment.
class _Final:
    # Retain the exact live producer and its already-bound native writer/checkpoint.
    def __init__(self, producer):
        physical._require(type(producer) is stages._Stages, 'Exact private stage producer required')
        self.stage, self.nightly, self.client = producer, producer.nightly, producer.client
        self.checkpoint, self.io = producer.checkpoint, producer.io
        self.prepared_input = None
        self.prepared_transition = None
        self.request_admission = None
        self.evidence_input = None
        self.receipt_capacity = None
        self.prepared_orders = None
        self.prepared_results = None
        self.saved_bytes = None
        self._guard()

    # Refuse substituted native resolution functions or changed original stage bindings.
    def _guard(self):
        self.stage._guard()
        physical._require(native.ReplayBroker.flush is FLUSH and native.ReplayBroker._fill is FILL
            and settlement._PreparedRawInput is PREPARED_INPUT
            and settlement.reconcile_raw is RECONCILE and RECONCILE.__code__ is RECONCILE_CODE
            and all(getattr(PREPARED_INPUT, name).__code__ is code for name, code in INPUT_METHODS.items()),
                          'Original native synthetic resolver required')
        physical._require(transition.PreparedTransition is TRANSITION
            and all(getattr(TRANSITION, name).__code__ is code for name, code in TRANSITION_METHODS.items()),
            'Original separately derived transition adapter required')
        transition.sources()
        physical._require(static_admission.StaticAdmission is ADMISSION
            and settlement._unique is UNIQUE and UNIQUE.__code__ is UNIQUE_CODE
            and settlement._requests is REQUESTS and REQUESTS.__code__ is REQUESTS_CODE
            and all(getattr(ADMISSION, name).__code__ is code for name, code in ADMISSION_METHODS.items()),
            'Original finite request admission and predicate required')
        static_admission.sources(REQUESTS)
        physical._require(finite_evidence.EvidenceInput is EVIDENCE_INPUT
            and all(getattr(EVIDENCE_INPUT, name).__code__ is code for name, code in EVIDENCE_METHODS.items()),
            'Original finite evidence-input admission required')
        physical._require(receipt_capacity.ReceiptCapacity is CAPACITY
            and all(getattr(CAPACITY, name).__code__ is code for name, code in CAPACITY_METHODS.items()),
            'Original finite receipt capacity admission required')
        physical._require(prepared_orders.PreparedOrders is PREPARED_ORDERS
            and all(getattr(PREPARED_ORDERS, name).__code__ is code for name, code in ORDER_METHODS.items()),
            'Original private prepared-order container implementation required')
        physical._require(prepared_results.PreparedResults is PREPARED_RESULTS
            and all(getattr(PREPARED_RESULTS, name).__code__ is code for name, code in RESULT_METHODS.items()),
            'Original private prepared-result storage implementation required')

    # Rebind every later step to original persisted inputs, current sources and active lease.
    def _active(self, value, reservation_sha, directory):
        self._guard()
        self.io._lease()
        declared = value['declaration']
        physical._require(not self.io.failed and read_file(self.nightly, directory / 'reservation.json') == (value, reservation_sha)
            and legacy.admitted.encoded(declared) == legacy.admitted.encoded(
                declaration(self.nightly, self.checkpoint, declared['submission_head'], declared['request']))
            and self.nightly.store.snapshot()['head'] == declared['submission_head']
            and self.io.directory == directory and self.io.reserved_cas == value['native_io']['reserved_cas']
            and self.io.effect_binding == value['native_io']['effect_binding'] == packet._digest(declared),
            'Original reserved final inputs/phase changed')
        binding = verify_input(self.nightly, self.checkpoint, directory, value)
        physical._require(type(self.prepared_input) is PREPARED_INPUT,
                          'Original live final input ownership required')
        if self.prepared_input.closed:
            self.prepared_input.check_released(binding)
        else:
            self.prepared_input.check(binding)
        descriptor = verify_transition(value)
        physical._require(type(self.prepared_transition) is TRANSITION, 'Original prepared transition ownership required')
        if self.prepared_transition.closed:
            self.prepared_transition.check_released(descriptor)
        else:
            self.prepared_transition.check(descriptor)
        admitted = verify_admission(value)
        physical._require(type(self.request_admission) is ADMISSION, 'Original live request admission required')
        if self.request_admission.closed:
            self.request_admission.check_released(binding, admitted)
        else:
            self.request_admission.check(self.prepared_input.prior, binding, admitted)
        evidence_input = verify_evidence_input(value)
        physical._require(type(self.evidence_input) is EVIDENCE_INPUT, 'Original evidence-input ownership required')
        if self.evidence_input.closed:
            self.evidence_input.check_released(binding, evidence_input)
        else:
            self.evidence_input.check(self.prepared_input.prior, binding, evidence_input)
        capacity = verify_capacity(value)
        physical._require(type(self.receipt_capacity) is CAPACITY, 'Original receipt capacity ownership required')
        if self.receipt_capacity.closed:
            self.receipt_capacity.check_released(binding, capacity)
        else:
            self.receipt_capacity.check(self.prepared_input.prior, self.client, binding, capacity)
        orders = verify_orders(value)
        physical._require(type(self.prepared_orders) is PREPARED_ORDERS, 'Original prepared-order ownership required')
        if self.prepared_orders.closed:
            self.prepared_orders.check_released(binding, orders)
        else:
            self.prepared_orders.check(self.client, binding, orders)
        results = verify_results(value)
        physical._require(type(self.prepared_results) is PREPARED_RESULTS, 'Original prepared-result ownership required')
        if self.prepared_results.closed:
            self.prepared_results.check_released(binding, results)
        else:
            self.prepared_results.check(self.prepared_input.prior, self.client, binding, results)
        if not self.io.saved:
            physical._require(reserved_io.writer_module._image(paper.state_path(self.nightly.root))
                == binding['preimage'], 'Live final input preimage changed')

    # Load and copy one exact native input after leases arm but before any broker resolution.
    def _prepare_input(self, declared, native_io):
        self._guard()
        self.io._lease()
        preimage = deepcopy(self.io.cursor['current'])
        physical._require(preimage is not None, 'Original final native input required')
        binding = {'schema': INPUT_SCHEMA, 'identity': self.nightly.store.identity,
            'account': str(self.nightly.root), 'phase': 'OUTCOME_COMMITTED',
            'head': declared['submission_head'], 'sources_sha256': packet._digest(sources()),
            'declaration_sha256': packet._digest(declared),
            'native_io_sha256': native_io['reservation_sha256'], 'preimage': preimage,
            'native_bytes': {'schema': 'native-paper-serialization/1', 'raw_sha256': preimage['sha256'],
                             'raw_bytes': preimage['length']}, 'raw_limit': self.checkpoint.limits['raw_bytes']}
        store = self.nightly.store
        store._point('reserved_final_input_before_load')
        state = paper.load_state(self.nightly.root)
        store._point('reserved_final_input_before_copy')
        self.prepared_input = PREPARED_INPUT(state, binding['raw_limit'], binding=binding)
        physical._require(reserved_io.writer_module._image(paper.state_path(self.nightly.root)) == preimage,
                          'Original final paper changed during preparation')
        return binding

    # Materialize the exact native-asdict output clone before any broker flush or post-fill order copy.
    def _prepare_transition(self, binding):
        descriptor = {'schema': transition.SCHEMA, 'sources': transition.sources(),
            'input_sha256': packet._digest(binding), 'identity': binding['identity'], 'account': binding['account'],
            'phase': binding['phase'], 'head': binding['head'], 'native_io_sha256': binding['native_io_sha256'],
            'native_bytes': deepcopy(binding['native_bytes']), 'raw_limit': binding['raw_limit']}
        self.nightly.store._point('reserved_final_transition_before_asdict')
        self.prepared_transition = TRANSITION(self.prepared_input.prior, binding['raw_limit'], binding=descriptor)
        return descriptor

    # Admit original intent/submission inputs while mutable execution results stay outside the descriptor.
    def _prepare_requests(self, binding, resolution_at):
        self.nightly.store._point('reserved_final_requests_before_check')
        self.request_admission = ADMISSION(self.prepared_input.prior, self.client, binding, REQUESTS, resolution_at)
        return deepcopy(self.request_admission.binding)

    # Admit only original input shape/encoding for the existing finite evidence contract before native effects.
    def _prepare_evidence_input(self, binding):
        self.nightly.store._point('reserved_final_evidence_before_check')
        self.evidence_input = EVIDENCE_INPUT(self.prepared_input.prior, binding)
        return deepcopy(self.evidence_input.binding)

    # Admit the original complete receipt allowance before output cloning or native broker resolution.
    def _prepare_receipt_capacity(self, binding, declared):
        self.receipt_capacity = CAPACITY(self.prepared_input.prior, self.client, binding, declared,
                                         self.nightly.pins(), sources())
        return deepcopy(self.receipt_capacity.binding)

    # Prepare detached order containers without copying any native execution values before resolution.
    def _prepare_orders(self, binding):
        self.nightly.store._point('reserved_final_orders_before_allocate')
        self.prepared_orders = PREPARED_ORDERS(self.client, binding, RECONCILE, self.nightly.pins())
        return deepcopy(self.prepared_orders.binding)


    # Own result storage for original due inputs while every native outcome remains unresolved.
    def _prepare_results(self, binding, resolution_at):
        self.nightly.store._point('reserved_final_results_before_allocate')
        self.prepared_results = PREPARED_RESULTS(self.prepared_input.prior, self.client, binding, RECONCILE, resolution_at)
        return deepcopy(self.prepared_results.binding)

    # Persist uncertainty after preparation or folding so caught failures cannot authorize effects.
    def _poison(self):
        self.io.failed = True
        self.nightly.store.blob_reservation.poison(self.io.reserved_cas)
        if self.nightly.store.directory_binding is not None:
            self.nightly.store.directory_binding.poison()

    # Serialize production and never open a second phase for an existing attempt.
    def _finish(self, *, submission_head, inputs):
        physical._require(legacy.LOCK.acquire(blocking=False), 'Concurrent reserved final')
        try:
            _, directory = operation(self.nightly, submission_head)
            if protocol.exists(self.nightly, directory):
                return self._recover_once(submission_head, inputs)
            return self._produce(submission_head, inputs, directory)
        except BaseException:
            self.io.failed = True
            raise
        finally:
            if self.prepared_results is not None:
                self.prepared_results.close()
                self.prepared_results = None
            if self.prepared_orders is not None:
                self.prepared_orders.close()
                self.prepared_orders = None
            if self.receipt_capacity is not None:
                self.receipt_capacity.close()
                self.receipt_capacity = None
            if self.evidence_input is not None:
                self.evidence_input.close()
                self.evidence_input = None
            if self.request_admission is not None:
                self.request_admission.close()
                self.request_admission = None
            if self.prepared_transition is not None:
                self.prepared_transition.close()
                self.prepared_transition = None
            if self.prepared_input is not None:
                self.prepared_input.close()
                self.prepared_input = None
            self.saved_bytes = None
            legacy.LOCK.release()

    # Reserve before flush and retain all uncertain native outcomes without replay authority.
    def _produce(self, submission_head, inputs, directory):
        self._guard()
        store, client, nightly = self.nightly.store, self.client, self.nightly
        physical._require(store.snapshot()['head'] == nightly.expected_head == submission_head
            and store.snapshot()['next_stage'] == 'OUTCOME_COMMITTED', 'Original submitted head required')
        physical._require(store.directory_binding is not None and store.directory_binding.reserves_saves,
                          'Exact finite native save-count mode required before final effects')
        declared = declaration(self.nightly, self.checkpoint, submission_head, inputs)
        reserved_io.current_components(nightly, client, declared['before'], self.checkpoint, legacy)
        bridge.verify_latch(store, nightly.root, declared['session'], declared['before']['latch'])
        physical._require(client._now is not None and native._instant(declared['request']['at']) > client._now,
                          'Explicit later synthetic resolution clock required')
        protocol.create(nightly, directory, phase='OUTCOME_COMMITTED', inputs=packet._digest(declared))
        self.io.begin(nightly, directory, legacy, effect_binding=packet._digest(declared))
        try:
            value = {'schema': SCHEMA, 'declaration': declared, 'native_io': self.io.evidence()}
            value['prepared_input'] = self._prepare_input(declared, value['native_io'])
            value['request_admission'] = self._prepare_requests(value['prepared_input'], declared['request']['at'])
            value['evidence_input'] = self._prepare_evidence_input(value['prepared_input'])
            value['receipt_capacity'] = self._prepare_receipt_capacity(value['prepared_input'], declared)
            value['prepared_orders'] = self._prepare_orders(value['prepared_input'])
            value['prepared_results'] = self._prepare_results(value['prepared_input'], declared['request']['at'])
            value['prepared_transition'] = self._prepare_transition(value['prepared_input'])
            raw = legacy.admitted.encoded(value)
            protocol.write(nightly, directory / 'reservation.json', raw, legacy)
            reservation_sha = sha256(raw).hexdigest()
            store._point('reserved_final_input_reserved')
            store._point('reserved_final_transition_reserved')
            store._point('reserved_final_requests_ready')
            store._point('reserved_final_evidence_ready')
            store._point('reserved_final_capacity_ready')
            store._point('reserved_final_orders_ready')
            store._point('reserved_final_results_ready')
            store._point('reserved_final_reserved')
            self._active(value, reservation_sha, directory)
            reserved_io.current_components(nightly, client, declared['before'], self.checkpoint, legacy)
            bridge.verify_latch(store, nightly.root, declared['session'], declared['before']['latch'])
            call = declared['request']
            self.prepared_input.check(value['prepared_input'], unconsumed=True)
            self.prepared_transition.check(value['prepared_transition'], unconsumed=True)
            self.request_admission.consume(self.prepared_input.prior, value['prepared_input'], value['request_admission'])
            self.evidence_input.consume(self.prepared_input.prior, value['prepared_input'], value['evidence_input'])
            self.receipt_capacity.consume(self.prepared_input.prior, client, value['prepared_input'], value['receipt_capacity'], nightly.pins())
            store._point('reserved_final_requests_consumed')
            self._active(value, reservation_sha, directory)
            fills = client.flush(call['at'], call['prices'], phase=call['phase'])
            store._point('reserved_final_resolved')
            self._active(value, reservation_sha, directory)
            resolved = {'stage': 'OUTCOME_COMMITTED',
                'origin': 'SYNTHETIC_DECLARED_NATIVE_FLUSH_NOT_MARKET_RESOLVER',
                'request': deepcopy(call), 'fills': fills}
            broker = codec.encode(client, **nightly.pins())
            detail = {'stage': 'PRE_SETTLEMENT_OUTCOME', 'submission_head': submission_head,
                'cycle': declared['cycle'], 'raw_nightly_lineage': declared['lineage'], 'resolved': resolved}
            pre = bridge.cycle._receipt(store, client, nightly.root, nightly.pins(), detail,
                session=date.fromisoformat(declared['session']), context=declared['context'],
                raw_checkpoint=self.checkpoint)
            retained = bridge.cycle._read_receipt(store, pre, nightly.pins(), raw_checkpoint=self.checkpoint)
            physical._require(bridge.paper_content(retained['components']['paper'], self.checkpoint, store.identity)
                == bridge.paper_content(declared['before']['paper'], self.checkpoint, store.identity)
                and retained['components']['latch'] == declared['before']['latch'],
                'Resolution changed original submission paper/latch')
            self._active(value, reservation_sha, directory)
            updated, evidence = self.prepared_results.reconcile(RECONCILE, client, self.prepared_input.state,
                prepared_orders=self.prepared_orders,
                pins=nightly.pins(), outcome_sha256=pre, observed_at=client._now.isoformat(),
                prior_component=retained['components']['paper'], raw_checkpoint=self.checkpoint,
                prepared_input=self.prepared_input, prepared_transition=self.prepared_transition)
            self.evidence_input.close()
            self.prepared_results.close()
            self.prepared_orders.close()
            self.receipt_capacity.close()
            self.request_admission.close()
            self.prepared_transition.close()
            self.prepared_input.close()
            store._point('reserved_final_input_released')
            self._active(value, reservation_sha, directory)
            self.io.save(nightly.root, updated)
            store._point('reserved_final_native_saved')
            self._active(value, reservation_sha, directory)
            self.saved_bytes = _SavedBytes(self, value, reservation_sha, evidence['reconciled_native_serialization'])
            saved = deepcopy(self.saved_bytes.binding)
            store._point('reserved_final_saved_bytes')
            physical._require(codec.encode(client, **nightly.pins()) == broker, 'Original resolved broker differs')
            bridge.verify_latch(store, nightly.root, declared['session'], declared['before']['latch'])
            detail = {'stage': 'OUTCOME_COMMITTED', 'settlement_submission_head': submission_head,
                'settlement_cycle': declared['cycle'], 'raw_nightly_lineage': declared['lineage'],
                'resolved': resolved}
            reference = bridge.cycle._receipt(store, client, nightly.root, nightly.pins(), detail,
                session=date.fromisoformat(declared['session']), context=declared['context'],
                raw_checkpoint=self.checkpoint, raw_reconciliation={'pre_settlement_receipt': pre, 'evidence': evidence})
            receipt = bridge.cycle._read_receipt(store, reference, nightly.pins(), raw_checkpoint=self.checkpoint)
            physical._require(bridge.paper_content(receipt['components']['paper'], self.checkpoint, store.identity)
                == (saved['state']['sha256'], saved['state']['length']), 'Original saved raw component differs')
            receipt['reserved_cycle_final'] = link(value, reservation_sha, saved)
            receipt_raw = legacy.admitted.encoded(receipt)
            self.receipt_capacity.output(receipt_raw)
            store._point('reserved_final_capacity_checked')
            reference = bridge.cycle._put(store, receipt_raw)
            prepared = {'schema': SCHEMA, 'reservation_sha256': reservation_sha,
                        'receipt': reference, 'native_io': self.io.evidence(), 'saved_bytes': saved}
            reserved_io.validate(nightly, directory, prepared['native_io'], [
                bridge.paper_content(receipt['components']['paper'], self.checkpoint, store.identity)],
                legacy, value['native_io'])
            protocol.write(nightly, directory / 'prepared.json', legacy.admitted.encoded(prepared), legacy)
            store._point('reserved_final_prepared')
            self._active(value, reservation_sha, directory)
            physical._require(legacy.admitted.encoded(read_file(self.nightly, directory / 'prepared.json')[0])
                == legacy.admitted.encoded(prepared)
                and legacy.admitted.encoded(bridge.cycle._read_receipt(store, reference, nightly.pins(),
                    raw_checkpoint=self.checkpoint)) == legacy.admitted.encoded(receipt),
                'Prepared reserved final file/receipt changed before commit')
            physical._require(self.io.evidence() == prepared['native_io']
                and codec.encode(client, **nightly.pins()) == broker, 'Prepared reserved final changed')
            physical._require(self.saved_bytes.check(value, reservation_sha) == prepared['saved_bytes'],
                              'Original final saved bytes changed before commit')
            store._point('reserved_final_saved_bytes_rechecked')
            bridge.verify_latch(store, nightly.root, declared['session'], declared['before']['latch'])
        except BaseException:
            self._poison()
            raise
        try:
            entry = store.append(expected_head=submission_head, cycle_sha256=declared['cycle'],
                                 stage='OUTCOME_COMMITTED', receipt_sha256=reference)
            store._point('reserved_final_committed')
        except BaseException:
            self.io.failed = True
            raise
        nightly.expected_head = entry['sha256']
        return self._recover_once(submission_head, inputs)

    # Recover only an original committed result marker and phase seal under the same lock.
    def _recover(self, *, submission_head, inputs):
        physical._require(legacy.LOCK.acquire(blocking=False), 'Concurrent reserved final recovery')
        try:
            return self._recover_once(submission_head, inputs)
        finally:
            legacy.LOCK.release()

    # Refuse OPEN/prepared-uncommitted attempts without flush, fold, save, capture or append.
    def _recover_once(self, submission_head, inputs):
        _, directory = operation(self.nightly, submission_head)
        try:
            value, _ = read_file(self.nightly, directory / 'reservation.json')
            physical._require(legacy.admitted.encoded(value['declaration']) == legacy.admitted.encoded(
                declaration(self.nightly, self.checkpoint, submission_head, inputs)), 'Conflicting original final inputs')
            prepared, _ = read_file(self.nightly, directory / 'prepared.json')
        except FileNotFoundError as error:
            raise StorePause('OPEN reserved final; never replay') from error
        reference = prepared['receipt']
        _, marker, value, _ = validate(self.nightly, reference, self.checkpoint, require_result=False)
        try:
            original, _ = read_file(self.nightly, directory / 'result.json')
        except FileNotFoundError:
            protocol.write(self.nightly, directory / 'result.json', legacy.admitted.encoded(marker), legacy)
        else:
            physical._require(original == marker, 'Original final result marker differs')
        self.nightly.store._point('reserved_final_result_written')
        reserved_io.complete(self.nightly, value['native_io'], reference)
        return marker
