"""Private raw Cycle settlement/commit tail; genuine execution remains closed.

The source-bound reservation precedes native fold/save. Prepared receipt bytes
precede the Store OUTCOME commit. Recovery can finish only its result marker after
that exact commit; an OPEN or uncertain operation never authorizes native replay.
This is not a full physical-capacity, resolver, sender or native-adoption protocol.
"""
from datetime import UTC, date, datetime
from hashlib import sha256
from pathlib import Path

from backend.agents.trading.desk import paper
from backend.market import historical_broker_checkpoint as codec
from backend.market import historical_conditional_nightly as legacy
from backend.market import historical_packet_store as storage
from backend.market import historical_raw_cycle as bridge
from backend.market import historical_raw_nightly as raw_nightly
from backend.market import historical_reserved_native_io as reserved_io
from backend.market import historical_timing_packet as packet
from backend.market import replay_broker as native
from backend.market.historical_packet_registry import digest
from backend.market.historical_packet_store import Store, StorePause

SCHEMA = 'standalone-current-raw-cycle-final/1'
SAVE_STATE = paper.save_state
RESERVATION_KEYS = {'schema', 'identity', 'operation', 'sources', 'submission',
                    'decision', 'cycle', 'session', 'context', 'lineage',
                    'resolved', 'before', 'actual_reserved_at', 'native_io'}
LINK_KEYS = {'schema', 'operation', 'reservation_sha256', 'sources',
             'native_operation_committed', 'durable_simulator_adoption'}


# Close the public final producer before reservation, capture or any native effect.
def finalize(*args, **kwargs):
    raise StorePause('Raw Cycle final genuine admission incomplete; PAUSED before effects')


# Keep public metadata completion behind the same unimplemented genuine admission.
def recover(*args, **kwargs):
    raise StorePause('Raw Cycle final genuine admission incomplete; PAUSED before effects')


# Bind this tail and all participating source identities without changing old adapters.
def sources():
    modules = (raw_nightly, bridge, legacy, paper, codec, storage, bridge.cycle._settlement_source())
    return {**raw_nightly.sources(), **{str(Path(module.__file__)):
        sha256(Path(module.__file__).read_bytes()).hexdigest() for module in modules},
        str(Path(__file__)): sha256(Path(__file__).read_bytes()).hexdigest()}


# Require exact private composition types and a same-account finite raw checkpoint.
def guard(nightly, checkpoint):
    legacy.admitted.require(type(nightly) is raw_nightly.RawNightly
        and type(nightly.store) is Store
        and nightly.root.resolve().is_relative_to(nightly.store.root.resolve()),
        'Exact private raw Cycle final account required')
    nightly._checkpoint(checkpoint)
    legacy.admitted.require(nightly.store.identity == nightly.pins()['identity_sha256'],
                            'Raw Cycle final account identity differs')


# Fix one attempt namespace independently of mutable resolved or context declarations.
def operation(nightly, submission_head):
    digest(submission_head)
    token = packet._digest({'schema': SCHEMA, 'identity': nightly.store.identity,
                            'submission_head': submission_head})
    return token, nightly.root / 'operations' / ('raw-cycle-final-' + token)


# Read exact bounded physical metadata rather than accepting caller-owned dictionaries.
def read(path):
    raw = legacy.physical(path)
    return legacy.admitted.decoded(raw), sha256(raw).hexdigest()


# Authenticate committed submission/decision and the earlier reserved Nightly identity.
def anchors(nightly, submission_head, checkpoint):
    store, pins, cycle = nightly.store, nightly.pins(), bridge.cycle
    entry = cycle._head_entry(store, submission_head)
    cycle_sha = entry['cycle_sha256']
    if pins['identity']['source_revision'] != cycle.CURRENT:
        raise ValueError('Exact CURRENT raw final profile required')
    submission_entry = bridge.committed_operation(store, submission_head, cycle_sha, 'SUBMISSION_CAPTURED')
    decision_entry = bridge.committed_operation(store, entry['parent'], cycle_sha, 'DECISION_FROZEN')
    submission = cycle._read_receipt(store, entry['receipt_sha256'], pins, raw_checkpoint=checkpoint)
    decision = cycle._read_receipt(store, decision_entry['receipt_sha256'], pins, raw_checkpoint=checkpoint)
    lineage = submission['detail'].get('raw_nightly_lineage')
    if (type(lineage) is not dict or set(lineage) != bridge.LINEAGE_KEYS
            or lineage['schema'] != bridge.LINEAGE):
        raise ValueError('Exact raw final Nightly lineage required')
    for key in bridge.LINEAGE_KEYS - {'schema'}:
        digest(lineage[key])
    for record, stage in ((submission, 'SUBMISSION_CAPTURED'), (decision, 'DECISION_FROZEN')):
        if (record['schema'] != 'private-conditional-cycle-receipt/2'
                or record['actual_historical_clocks_or_fills'] is not False
                or record['session'] != submission['session'] or record['context'] != submission['context']
                or set(record['components']) != {'broker', 'paper', 'latch'}
                or record['detail'].get('stage') != stage
                or record['detail'].get('raw_nightly_lineage') != lineage
                or 'raw_reconciliation' in record or 'raw_final_operation' in record):
            raise ValueError('Original raw final reserved stage lineage differs')
    prior = nightly.read_lifecycle(lineage['previous_nightly'], raw_checkpoint=checkpoint)['value']
    birth = nightly.read_raw_birth(lineage['birth'], raw_checkpoint=checkpoint)
    session = date.fromisoformat(submission['session'])
    if (session.isoformat() != submission['session'] or prior['phase'] != 'NIGHTLY_CLOSE'
            or prior['detail']['status'] != 'NATIVE_NIGHTLY_RETURNED'
            or any(prior[key] != lineage[key] for key in ('birth', 'context', 'context_identity'))
            or any(birth[key] != lineage[key] for key in ('context', 'context_identity'))
            or session != legacy.intraday_orders.next_session(date.fromisoformat(prior['session']))
            or bridge.paper_content(prior['components']['paper'], checkpoint, store.identity)
                != bridge.paper_content(decision['components']['paper'], checkpoint, store.identity)):
        raise ValueError('Original raw final preceding Nightly differs')
    context = submission['context']
    if type(context) is not dict or set(context) != {'raw', 'sha256'}:
        raise ValueError('Distinct raw final Cycle context required')
    parsed = cycle.market.read_context(cycle.market.Context(context['raw'].encode(), context['sha256']))
    if parsed['window']['completed_at'][:10] != submission['session']:
        raise ValueError('Original raw final context session differs')
    return {'submission': submission_entry, 'decision': decision_entry, 'cycle': cycle_sha,
            'session': submission['session'], 'context': context, 'lineage': lineage,
            'submission_receipt': submission}


# Match current native inputs without recapturing or changing the submitted paper bytes.
def current(nightly, client, checkpoint, anchor):
    if type(client) is not native.ReplayBroker or client._now is None or paper.save_state is not SAVE_STATE:
        raise ValueError('Original observed native raw final bindings required')
    refs = anchor['submission_receipt']['components']
    state = paper.load_state(nightly.root)
    encoded = bridge.cycle._settlement_source()._native_serialization(state, checkpoint.limits['raw_bytes'])
    if (encoded['raw_sha256'], encoded['raw_bytes']) != bridge.paper_content(
            refs['paper'], checkpoint, nightly.store.identity):
        raise ValueError('Raw final current submission paper differs')
    bridge.verify_latch(nightly.store, nightly.root, anchor['session'], refs['latch'])
    broker = codec.encode(client, **nightly.pins())
    return state, broker, {'broker_sha256': sha256(broker).hexdigest(), 'broker_bytes': len(broker),
                           'paper': refs['paper'], 'latch': refs['latch']}


# Bind final receipt metadata to its original source-bound physical reservation.
def link(reservation, reservation_sha):
    return {'schema': SCHEMA, 'operation': reservation['operation'],
            'reservation_sha256': reservation_sha, 'sources': reservation['sources'],
            'native_operation_committed': False, 'durable_simulator_adoption': False}


# Validate original reservation bytes and committed anchors without touching native files.
def reservation(nightly, submission_head, resolved, checkpoint):
    token, directory = operation(nightly, submission_head)
    value, reference = read(directory / 'reservation.json')
    anchor = anchors(nightly, submission_head, checkpoint)
    if (type(value) is not dict or set(value) != RESERVATION_KEYS
            or value['schema'] != SCHEMA or value['identity'] != nightly.store.identity
            or value['operation'] != token or value['sources'] != sources()
            or any(value[key] != anchor[key] for key in
                   ('submission', 'decision', 'cycle', 'session', 'context', 'lineage'))
            or legacy.admitted.encoded(value['resolved']) != legacy.admitted.encoded(resolved)
            or type(value['before']) is not dict
            or set(value['before']) != {'broker_sha256', 'broker_bytes', 'paper', 'latch'}
            or value['before']['paper'] != anchor['submission_receipt']['components']['paper']
            or value['before']['latch'] != anchor['submission_receipt']['components']['latch']):
        raise ValueError('Original raw final reservation differs')
    digest(value['before']['broker_sha256'])
    if type(value['before']['broker_bytes']) is not int or not 0 < value['before']['broker_bytes'] <= codec.CAPS['bytes']:
        raise ValueError('Bounded original raw final broker declaration required')
    return value, reference


# Authenticate the prepared graph before commit and again during metadata-only recovery.
def prepared_receipt(nightly, value, reservation_sha, receipt_sha, checkpoint):
    cycle, store, pins = bridge.cycle, nightly.store, nightly.pins()
    receipt = cycle._read_receipt(store, receipt_sha, pins, raw_checkpoint=checkpoint)
    expected = {'stage': 'OUTCOME_COMMITTED',
        'settlement_submission_head': value['submission']['sha256'],
        'settlement_cycle': value['cycle'], 'raw_nightly_lineage': value['lineage'],
        'resolved': value['resolved']}
    if (receipt['schema'] != 'private-conditional-cycle-receipt/2'
            or receipt['actual_historical_clocks_or_fills'] is not False
            or receipt['session'] != value['session'] or receipt['context'] != value['context']
            or receipt['detail'] != expected
            or legacy.admitted.encoded(receipt.get('raw_final_operation'))
                != legacy.admitted.encoded(link(value, reservation_sha))
            or set(receipt['raw_final_operation']) != LINK_KEYS
            or receipt['components']['broker'] != value['before']['broker_sha256']
            or len(store.read_blob(receipt['components']['broker'], limit=codec.CAPS['bytes']))
                != value['before']['broker_bytes']
            or receipt['components']['latch'] != value['before']['latch']):
        raise ValueError('Original prepared raw final receipt differs')
    pre = cycle._read_receipt(store, receipt['raw_reconciliation']['pre_settlement_receipt'],
                              pins, raw_checkpoint=checkpoint)
    if (pre['detail'] != {'stage': 'PRE_SETTLEMENT_OUTCOME',
            'submission_head': value['submission']['sha256'], 'cycle': value['cycle'],
            'raw_nightly_lineage': value['lineage'], 'resolved': value['resolved']}
            or pre['components']['latch'] != value['before']['latch']
            or bridge.paper_content(pre['components']['paper'], checkpoint, store.identity)
                != bridge.paper_content(value['before']['paper'], checkpoint, store.identity)):
        raise ValueError('Original prepared raw final pre-fold graph differs')
    return receipt


# Complete only the result marker after an exact already-committed authoritative outcome.
def result(nightly, submission_head, resolved, checkpoint, expected_head):
    value, reservation_sha = reservation(nightly, submission_head, resolved, checkpoint)
    _, directory = operation(nightly, submission_head)
    try:
        prepared, _ = read(directory / 'prepared.json')
    except FileNotFoundError as error:
        raise StorePause('Interrupted raw final lacks prepared result; never re-execute') from error
    reserved = value['native_io'] is not None
    if not reserved and (directory / 'reserved-native-save.json').exists():
        raise ValueError('Raw final native IO reservation mode differs')
    prepared_keys = {'schema', 'reservation_sha256', 'receipt_sha256'}
    if reserved:
        prepared_keys.add('reserved_native_io')
    if (type(prepared) is not dict or set(prepared) != prepared_keys
            or prepared['schema'] != SCHEMA or prepared['reservation_sha256'] != reservation_sha):
        raise ValueError('Original raw final prepared marker differs')
    reference = digest(prepared['receipt_sha256'])
    receipt = prepared_receipt(nightly, value, reservation_sha, reference, checkpoint)
    if reserved:
        reserved_io.validate(nightly, directory, prepared['reserved_native_io'],
            [bridge.paper_content(receipt['components']['paper'], checkpoint, nightly.store.identity)],
            legacy, value['native_io'])
    committed = bridge.read_final(nightly.store, reference, nightly.pins(),
                                 expected_head=expected_head, raw_checkpoint=checkpoint)
    if committed['entry']['parent'] != submission_head or committed['lineage'] != value['lineage']:
        raise ValueError('Original raw final committed descendant differs')
    marker = {'schema': SCHEMA, 'reservation_sha256': reservation_sha,
              'receipt_sha256': reference, 'head': committed['entry']['sha256']}
    try:
        retained, _ = read(directory / 'result.json')
    except FileNotFoundError:
        legacy.write_once(directory / 'result.json', legacy.admitted.encoded(marker))
    else:
        if retained != marker:
            raise ValueError('Original raw final result marker differs')
    return {**marker, 'entry': committed['entry'], 'native_operation_committed': False,
            'durable_simulator_adoption': False}


# Recover committed metadata without folding, saving, capturing, appending or restoring account files.
def _recover(nightly, *, submission_head, resolved, raw_checkpoint):
    guard(nightly, raw_checkpoint)
    legacy.admitted.require(legacy.LOCK.acquire(blocking=False), 'Concurrent raw final recovery')
    try:
        try:
            return result(nightly, submission_head, resolved, raw_checkpoint, nightly.expected_head)
        except FileNotFoundError as error:
            raise StorePause('Interrupted raw final metadata missing; never re-execute') from error
    finally:
        legacy.LOCK.release()


# Reserve once, reconcile/save once and commit the prepared raw receipt without replay.
def _finalize(nightly, client, *, submission_head, resolved, raw_checkpoint, native_io=None):
    guard(nightly, raw_checkpoint)
    legacy.admitted.require(nightly.store.blob_reservation is None,
                            'Reserved CAS Cycle stage admission incomplete; PAUSED before effects')
    token, directory = operation(nightly, submission_head)
    if directory.exists():
        return _recover(nightly, submission_head=submission_head, resolved=resolved,
                        raw_checkpoint=raw_checkpoint)
    legacy.admitted.require(legacy.LOCK.acquire(blocking=False), 'Concurrent raw final production')
    try:
        store, pins, cycle = nightly.store, nightly.pins(), bridge.cycle
        if (store.snapshot()['head'] != nightly.expected_head or nightly.expected_head != submission_head
                or store.snapshot()['next_stage'] != 'OUTCOME_COMMITTED'):
            raise StorePause('Original raw final committed submission head required')
        if type(resolved) is not dict or resolved.get('stage') != 'OUTCOME_COMMITTED':
            raise ValueError('Finite original resolved outcome declaration required')
        declared = legacy.admitted.decoded(legacy.admitted.encoded(resolved))
        anchor = anchors(nightly, submission_head, raw_checkpoint)
        state, broker, before = current(nightly, client, raw_checkpoint, anchor)
        directory.mkdir(mode=0o700)
        legacy.sync_directory(directory.parent)
        if native_io is not None:
            legacy.admitted.require(type(native_io) is reserved_io.SyntheticNativeIO,
                                    'Exact synthetic native IO required')
            native_io.begin(nightly, directory, legacy)
        value = {'schema': SCHEMA, 'identity': store.identity, 'operation': token,
            'sources': sources(), **{key: anchor[key] for key in
                ('submission', 'decision', 'cycle', 'session', 'context', 'lineage')},
            'resolved': declared, 'before': before,
            'native_io': None if native_io is None else native_io.evidence(),
            'actual_reserved_at': datetime.now(UTC).isoformat()}
        raw = legacy.admitted.encoded(value)
        legacy.write_once(directory / 'reservation.json', raw)
        reservation_sha = sha256(raw).hexdigest()
        store._point('raw_final_reserved')
        pre_detail = {'stage': 'PRE_SETTLEMENT_OUTCOME', 'submission_head': submission_head,
            'cycle': anchor['cycle'], 'raw_nightly_lineage': anchor['lineage'], 'resolved': declared}
        pre = cycle._receipt(store, client, nightly.root, pins, pre_detail,
            session=date.fromisoformat(anchor['session']), context=anchor['context'], raw_checkpoint=raw_checkpoint)
        retained = cycle._read_receipt(store, pre, pins, raw_checkpoint=raw_checkpoint)
        updated, evidence = cycle._settlement_source().reconcile_raw(client, state, pins=pins,
            outcome_sha256=pre, observed_at=client._now.isoformat(),
            prior_component=retained['components']['paper'], raw_checkpoint=raw_checkpoint)
        store._point('raw_final_reconciled')
        if paper.save_state is not SAVE_STATE:
            raise ValueError('Original raw final native writer changed')
        if native_io is None:
            paper.save_state(nightly.root, updated)
        else:
            native_io.save(nightly.root, updated)
        store._point('raw_final_native_saved')
        if (codec.encode(client, **pins) != broker
                or cycle._settlement_source()._native_serialization(paper.load_state(nightly.root),
                    raw_checkpoint.limits['raw_bytes']) != evidence['reconciled_native_serialization']):
            raise StorePause('Raw final native save/read or broker changed')
        bridge.verify_latch(store, nightly.root, anchor['session'], before['latch'])
        detail = {'stage': 'OUTCOME_COMMITTED', 'settlement_submission_head': submission_head,
            'settlement_cycle': anchor['cycle'], 'raw_nightly_lineage': anchor['lineage'], 'resolved': declared}
        reference = cycle._receipt(store, client, nightly.root, pins, detail,
            session=date.fromisoformat(anchor['session']), context=anchor['context'],
            raw_checkpoint=raw_checkpoint, raw_reconciliation={'pre_settlement_receipt': pre, 'evidence': evidence})
        receipt = cycle._read_receipt(store, reference, pins, raw_checkpoint=raw_checkpoint)
        receipt['raw_final_operation'] = link(value, reservation_sha)
        reference = cycle._put(store, legacy.admitted.encoded(receipt))
        reservation(nightly, submission_head, declared, raw_checkpoint)
        prepared_receipt(nightly, value, reservation_sha, reference, raw_checkpoint)
        prepared = {'schema': SCHEMA, 'reservation_sha256': reservation_sha, 'receipt_sha256': reference}
        if native_io is not None:
            prepared['reserved_native_io'] = native_io.evidence()
            reserved_io.validate(nightly, directory, prepared['reserved_native_io'],
                [bridge.paper_content(receipt['components']['paper'], raw_checkpoint, store.identity)],
                legacy, value['native_io'])
        legacy.write_once(directory / 'prepared.json', legacy.admitted.encoded(prepared))
        store._point('raw_final_prepared')
        reservation(nightly, submission_head, declared, raw_checkpoint)
        if native_io is not None:
            if native_io.evidence() != prepared['reserved_native_io']:
                raise StorePause('Prepared reserved native cursor changed before commit')
            reserved_io.validate(nightly, directory, prepared['reserved_native_io'],
                [bridge.paper_content(receipt['components']['paper'], raw_checkpoint, store.identity)],
                legacy, value['native_io'])
        if (paper.save_state is not SAVE_STATE or codec.encode(client, **pins) != broker
                or cycle._settlement_source()._native_serialization(paper.load_state(nightly.root),
                    raw_checkpoint.limits['raw_bytes']) != evidence['reconciled_native_serialization']):
            raise StorePause('Prepared raw final native components changed before commit')
        bridge.verify_latch(store, nightly.root, anchor['session'], before['latch'])
        entry = store.append(expected_head=submission_head, cycle_sha256=anchor['cycle'],
                             stage='OUTCOME_COMMITTED', receipt_sha256=reference)
        store._point('raw_final_outcome_committed')
        return result(nightly, submission_head, declared, raw_checkpoint, entry['sha256'])
    finally:
        legacy.LOCK.release()
