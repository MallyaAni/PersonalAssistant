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
from backend.market import historical_raw_cycle as bridge
from backend.market import historical_reserved_cycle_stages as stages
from backend.market import historical_reserved_native_io as reserved_io
from backend.market import historical_timing_packet as packet
from backend.market import replay_broker as native
from backend.market.historical_packet_store import StorePause

SCHEMA = 'synthetic-reserved-cycle-final/1'
REQUEST = 'synthetic-declared-native-flush/1'
FLUSH, FILL = native.ReplayBroker.flush, native.ReplayBroker._fill


# Keep public genuine execution closed before constructing or reserving anything.
def execute(*args, **kwargs):
    raise StorePause('Reserved final genuine admission incomplete; PAUSED before effects')


# Bind the complete participating product sources independently of a callback identity.
def sources():
    return {**stages.sources(), str(Path(settlement.__file__)): sha256(
        Path(settlement.__file__).read_bytes()).hexdigest(),
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
def read_file(path):
    raw = legacy.physical(path)
    return legacy.admitted.decoded(raw), sha256(raw).hexdigest()


# Bind final bytes to the original phase and source-bound resolution declaration.
def link(value, reservation_sha):
    return {'schema': SCHEMA, 'reservation_sha256': reservation_sha,
            'declaration_sha256': packet._digest(value['declaration']),
            'reserved_cas': value['native_io']['reserved_cas'], 'sources': sources()}


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
    value, reservation_sha = read_file(directory / 'reservation.json')
    physical._require(set(value) == {'schema', 'declaration', 'native_io'} and value['schema'] == SCHEMA,
                      'Original reserved final reservation required')
    declared = value['declaration']
    physical._require(legacy.admitted.encoded(declared) == legacy.admitted.encoded(
        declaration(nightly, checkpoint, submission_head, declared['request']))
        and final['receipt'].get('reserved_cycle_final') == link(value, reservation_sha),
        'Original reserved final stage/input lineage differs')
    prepared, _ = read_file(directory / 'prepared.json')
    physical._require(set(prepared) == {'schema', 'reservation_sha256', 'receipt', 'native_io'}
        and prepared['schema'] == SCHEMA and prepared['reservation_sha256'] == reservation_sha
        and prepared['receipt'] == reference, 'Original reserved final prepared marker required')
    reserved_io.validate(nightly, directory, prepared['native_io'], [
        bridge.paper_content(final['receipt']['components']['paper'], checkpoint, store.identity)],
        legacy, value['native_io'])
    lease = value['native_io']['reserved_cas']
    control, group = store.blob_reservation.group(lease)
    physical._require(value['native_io']['effect_binding'] == packet._digest(declared)
        and lease['head'] == submission_head
        and lease['operation'] == sha256(physical._encoded({'directory': str(directory),
            'effect_binding': packet._digest(declared)})).hexdigest()
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
    marker = {'schema': SCHEMA, 'reservation_sha256': reservation_sha,
              'receipt': reference, 'head': final['entry']['sha256']}
    if require_result:
        physical._require(group['status'] == 'COMPLETE'
            and read_file(directory / 'result.json')[0] == marker,
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
        self._guard()

    # Refuse substituted native resolution functions or changed original stage bindings.
    def _guard(self):
        self.stage._guard()
        physical._require(native.ReplayBroker.flush is FLUSH and native.ReplayBroker._fill is FILL,
                          'Original native synthetic resolver required')

    # Rebind every later step to original persisted inputs, current sources and active lease.
    def _active(self, value, reservation_sha, directory):
        self._guard()
        self.io._lease()
        declared = value['declaration']
        physical._require(not self.io.failed and read_file(directory / 'reservation.json') == (value, reservation_sha)
            and legacy.admitted.encoded(declared) == legacy.admitted.encoded(
                declaration(self.nightly, self.checkpoint, declared['submission_head'], declared['request']))
            and self.nightly.store.snapshot()['head'] == declared['submission_head']
            and self.io.directory == directory and self.io.reserved_cas == value['native_io']['reserved_cas']
            and self.io.effect_binding == value['native_io']['effect_binding'] == packet._digest(declared),
            'Original reserved final inputs/phase changed')

    # Serialize production and never open a second phase for an existing attempt.
    def _finish(self, *, submission_head, inputs):
        physical._require(legacy.LOCK.acquire(blocking=False), 'Concurrent reserved final')
        try:
            _, directory = operation(self.nightly, submission_head)
            if directory.exists():
                return self._recover_once(submission_head, inputs)
            return self._produce(submission_head, inputs, directory)
        except BaseException:
            self.io.failed = True
            raise
        finally:
            legacy.LOCK.release()

    # Reserve before flush and retain all uncertain native outcomes without replay authority.
    def _produce(self, submission_head, inputs, directory):
        self._guard()
        store, client, nightly = self.nightly.store, self.client, self.nightly
        physical._require(store.snapshot()['head'] == nightly.expected_head == submission_head
            and store.snapshot()['next_stage'] == 'OUTCOME_COMMITTED', 'Original submitted head required')
        declared = declaration(self.nightly, self.checkpoint, submission_head, inputs)
        reserved_io.current_components(nightly, client, declared['before'], self.checkpoint, legacy)
        bridge.verify_latch(store, nightly.root, declared['session'], declared['before']['latch'])
        physical._require(client._now is not None and native._instant(declared['request']['at']) > client._now,
                          'Explicit later synthetic resolution clock required')
        directory.mkdir(mode=0o700)
        legacy.sync_directory(directory.parent)
        self.io.begin(nightly, directory, legacy, effect_binding=packet._digest(declared))
        value = {'schema': SCHEMA, 'declaration': declared, 'native_io': self.io.evidence()}
        raw = legacy.admitted.encoded(value)
        legacy.write_once(directory / 'reservation.json', raw)
        reservation_sha = sha256(raw).hexdigest()
        try:
            store._point('reserved_final_reserved')
            self._active(value, reservation_sha, directory)
            reserved_io.current_components(nightly, client, declared['before'], self.checkpoint, legacy)
            bridge.verify_latch(store, nightly.root, declared['session'], declared['before']['latch'])
            call = declared['request']
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
            updated, evidence = settlement.reconcile_raw(client, paper.load_state(nightly.root),
                pins=nightly.pins(), outcome_sha256=pre, observed_at=client._now.isoformat(),
                prior_component=retained['components']['paper'], raw_checkpoint=self.checkpoint)
            self._active(value, reservation_sha, directory)
            self.io.save(nightly.root, updated)
            store._point('reserved_final_native_saved')
            self._active(value, reservation_sha, directory)
            physical._require(codec.encode(client, **nightly.pins()) == broker
                and settlement._native_serialization(paper.load_state(nightly.root), self.checkpoint.limits['raw_bytes'])
                    == evidence['reconciled_native_serialization'], 'Original resolved native save differs')
            bridge.verify_latch(store, nightly.root, declared['session'], declared['before']['latch'])
            detail = {'stage': 'OUTCOME_COMMITTED', 'settlement_submission_head': submission_head,
                'settlement_cycle': declared['cycle'], 'raw_nightly_lineage': declared['lineage'],
                'resolved': resolved}
            reference = bridge.cycle._receipt(store, client, nightly.root, nightly.pins(), detail,
                session=date.fromisoformat(declared['session']), context=declared['context'],
                raw_checkpoint=self.checkpoint, raw_reconciliation={'pre_settlement_receipt': pre, 'evidence': evidence})
            receipt = bridge.cycle._read_receipt(store, reference, nightly.pins(), raw_checkpoint=self.checkpoint)
            receipt['reserved_cycle_final'] = link(value, reservation_sha)
            reference = bridge.cycle._put(store, legacy.admitted.encoded(receipt))
            prepared = {'schema': SCHEMA, 'reservation_sha256': reservation_sha,
                        'receipt': reference, 'native_io': self.io.evidence()}
            reserved_io.validate(nightly, directory, prepared['native_io'], [
                bridge.paper_content(receipt['components']['paper'], self.checkpoint, store.identity)],
                legacy, value['native_io'])
            legacy.write_once(directory / 'prepared.json', legacy.admitted.encoded(prepared))
            store._point('reserved_final_prepared')
            self._active(value, reservation_sha, directory)
            physical._require(legacy.admitted.encoded(read_file(directory / 'prepared.json')[0])
                == legacy.admitted.encoded(prepared)
                and legacy.admitted.encoded(bridge.cycle._read_receipt(store, reference, nightly.pins(),
                    raw_checkpoint=self.checkpoint)) == legacy.admitted.encoded(receipt),
                'Prepared reserved final file/receipt changed before commit')
            physical._require(self.io.evidence() == prepared['native_io']
                and codec.encode(client, **nightly.pins()) == broker
                and settlement._native_serialization(paper.load_state(nightly.root), self.checkpoint.limits['raw_bytes'])
                    == evidence['reconciled_native_serialization'], 'Prepared reserved final changed')
            bridge.verify_latch(store, nightly.root, declared['session'], declared['before']['latch'])
        except BaseException:
            self.io.failed = True
            store.blob_reservation.poison(self.io.reserved_cas)
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
            value, _ = read_file(directory / 'reservation.json')
            physical._require(legacy.admitted.encoded(value['declaration']) == legacy.admitted.encoded(
                declaration(self.nightly, self.checkpoint, submission_head, inputs)), 'Conflicting original final inputs')
            prepared, _ = read_file(directory / 'prepared.json')
        except FileNotFoundError as error:
            raise StorePause('OPEN reserved final; never replay') from error
        reference = prepared['receipt']
        _, marker, value, _ = validate(self.nightly, reference, self.checkpoint, require_result=False)
        try:
            original, _ = read_file(directory / 'result.json')
        except FileNotFoundError:
            legacy.write_once(directory / 'result.json', legacy.admitted.encoded(marker))
        else:
            physical._require(original == marker, 'Original final result marker differs')
        self.nightly.store._point('reserved_final_result_written')
        reserved_io.complete(self.nightly, value['native_io'], reference)
        return marker
