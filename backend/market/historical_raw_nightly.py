"""Private raw Nightly lifecycle composition; genuine execution remains unadmitted.

Public entry points refuse before effects. Separately tested private bodies retain
birth/close/previous/write lineage without changing legacy Nightly or Cycle routes.
Local checkpoint/Store persistence does not establish native operation adoption.
"""
from copy import deepcopy
from datetime import UTC, date, datetime, timedelta
from hashlib import sha256
import io
import json
from pathlib import Path
import time

from backend.agents.trading.desk import paper
from backend.market import historical_broker_checkpoint as codec
from backend.market import historical_conditional_nightly as legacy
from backend.market import historical_native_metadata as metadata
from backend.market import historical_paper_component as component
from backend.market import historical_physical_checkpoint as physical
from backend.market import historical_timing_packet as packet
from backend.market import replay_broker as native
from backend.market.historical_packet_registry import digest
from backend.market.historical_packet_store import StorePause

SCHEMA = 'standalone-current-raw-nightly-lifecycle/1'
VALUE_KEYS = {'phase', 'session', 'context', 'context_identity', 'birth', 'previous',
              'components', 'entry', 'decisions', 'native_writes', 'detail'}
RECORD_KEYS = {'schema', 'identity', 'sources', 'operation', 'reservation_sha256',
               'value', 'native_operation_committed', 'durable_simulator_adoption',
               'publication_barrier', 'packet_pipeline_integrated'}
WRITE_KEYS = {'schema', 'checkpoint', 'raw_sha256', 'raw_bytes', 'identity_sha256',
              'local_capture_committed', 'native_operation_committed',
              'durable_simulator_adoption'}


# Bind this composition independently from the unchanged native/legacy source map.
def sources():
    return {**legacy.sources(), str(Path(__file__)): sha256(Path(__file__).read_bytes()).hexdigest()}


# Keep every genuine raw entry closed until complete lifecycle admission is implemented.
def execution_admission():
    raise StorePause('Raw Nightly genuine lifecycle admission incomplete; PAUSED before effects')


# Compare authenticated raw content without equating newly captured checkpoint references.
def content(refs, checkpoint, identity):
    root = component.verify(refs['paper'], checkpoint, expected_identity=identity)
    return refs['broker'], root['raw_sha256'], root['raw_bytes']


# Preserve one actual native save observation with the observer's existing vocabulary.
def write_reference(checkpoint, reference):
    root = checkpoint.verify(reference)
    return {'schema': 'native-observer-raw-write/1', 'checkpoint': reference,
            'raw_sha256': root['raw_sha256'], 'raw_bytes': root['raw_bytes'],
            'identity_sha256': root['identity_sha256'], 'local_capture_committed': True,
            'native_operation_committed': False, 'durable_simulator_adoption': False}


# Compose raw lifecycle bodies without widening legacy execution or Cycle admission.
class RawNightly(legacy.Nightly):
    # Refuse public raw birth before reservation, broker creation or native writes.
    def initialize(self, context, *, raw_checkpoint):
        execution_admission()
        return self._initialize(context, raw_checkpoint=raw_checkpoint)

    # Refuse public raw closes before policy, broker observation or native work.
    def close(self, context, client, session, *, birth, previous, raw_checkpoint):
        execution_admission()
        return self._close(context, client, session, birth=birth, previous=previous,
                           raw_checkpoint=raw_checkpoint)

    # Authenticate same-account checkpoint mode before any lifecycle effect.
    def _checkpoint(self, checkpoint):
        legacy.admitted.require(type(checkpoint) is physical.PhysicalCheckpoint
            and checkpoint.header['identity_sha256'] == self.store.identity,
            'Exact same-account raw lifecycle checkpoint required')

    # Reserve source-bound raw lineage before native work without claiming capacity.
    def _reserve(self, phase, session, context, birth, previous, before):
        legacy.admitted.require(self.store.snapshot()['head'] == self.expected_head,
                                'Stale raw lifecycle pre-head')
        directory = self.operation(phase, session)
        directory.mkdir(mode=0o700)
        legacy.sync_directory(directory.parent)
        value = {'schema': SCHEMA, 'identity': self.store.identity,
                 'pre_head': self.expected_head, 'phase': phase, 'session': session,
                 'source_sha256': sources(), 'context_sha256': context,
                 'birth': birth, 'previous': previous, 'before': before,
                 'actual_reserved_at': datetime.now(UTC).isoformat()}
        raw = legacy.admitted.encoded(value)
        legacy.write_once(directory / 'reservation.json', raw)
        return directory, sha256(raw).hexdigest()

    # Validate exact typed metadata and all native write observations before publication.
    def _value(self, value, checkpoint):
        self._checkpoint(checkpoint)
        legacy.admitted.require(type(value) is dict and set(value) == VALUE_KEYS
            and value['phase'] in ('BIRTH', 'NIGHTLY_CLOSE')
            and type(value['components']) is dict and set(value['components']) == {'broker', 'paper'}
            and type(value['decisions']) is list and len(value['decisions']) <= 320
            and type(value['native_writes']) is list and len(value['native_writes']) <= 320,
            'Exact raw lifecycle value required')
        date.fromisoformat(value['session'])
        digest(value['context_identity'])
        self.store.read_blob(value['context'], limit=legacy.CAP)
        self.store.read_blob(value['components']['broker'], limit=codec.CAPS['bytes'])
        final = content(value['components'], checkpoint, self.store.identity)
        producer = sha256(Path(__file__).read_bytes()).hexdigest()
        decision_producer = sha256(Path(legacy.__file__).read_bytes()).hexdigest()
        references = [(value['entry'], 'nightly-entry', producer)]
        references.extend((ref, 'holding-decision', decision_producer) for ref in value['decisions'])
        total = 0
        for reference, kind, source in references:
            metadata._declaration(self.store, reference, kind, source)
            total += reference['raw_bytes']
        legacy.admitted.require(total <= metadata.LIMIT, 'Raw lifecycle metadata aggregate bound')
        for reference, kind, source in references:
            metadata.read_bytes(self.store, reference, kind=kind, producer_sha256=source)
        for write in value['native_writes']:
            legacy.admitted.require(type(write) is dict and set(write) == WRITE_KEYS
                and legacy.admitted.encoded(write) == legacy.admitted.encoded(
                    write_reference(checkpoint, write['checkpoint'])),
                'Original native write observation differs')
        if value['native_writes']:
            last = value['native_writes'][-1]
            legacy.admitted.require((last['raw_sha256'], last['raw_bytes']) == final[1:],
                                    'Final native write differs from saved component')
        if value['phase'] == 'BIRTH':
            broker = codec.restore(self.store.read_blob(value['components']['broker'], limit=codec.CAPS['bytes']),
                                   expected_sha256=value['components']['broker'], **self.pins())
            empty = json.dumps(paper.PaperState(), indent=2, default=paper._state_json).encode()
            legacy.admitted.require(value['session'] == '2019-02-28'
                and value['birth'] is None and value['previous'] is None
                and value['decisions'] == [] and len(value['native_writes']) == 1
                and metadata.read_bytes(self.store, value['entry'], kind='nightly-entry',
                    producer_sha256=producer) == b'null'
                and value['detail']['initial_cash'] == 100000
                and value['detail']['initial_holdings'] == {} and value['detail']['cost_bps'] == 10
                and broker._cash == 100000 and broker._held == {} and broker.cost_bps == 10
                and broker._now is None and final[1:] == (sha256(empty).hexdigest(), len(empty)),
                'Exact raw zero-account birth required')
        else:
            digest(value['birth']); digest(value['previous'])
            detail = value['detail']
            legacy.admitted.require(detail['status'] in ('NATIVE_NIGHTLY_RETURNED', 'NIGHTLY_BROKER_UNAVAILABLE')
                and detail['raw_submissions'] == [] and detail['accepted'] == []
                and type(detail['holding_policy_calls']) is int
                and detail['holding_policy_calls'] == len(value['decisions'])
                and type(detail['actual_elapsed_ns']) is int and detail['actual_elapsed_ns'] >= 0,
                'Exact no-submission raw lifecycle observation required')
            if detail['status'] == 'NATIVE_NIGHTLY_RETURNED':
                legacy.admitted.require(bool(value['native_writes'])
                    and detail['entry_native_sha256'] == value['entry']['raw_sha256']
                    and detail['entry_native_bytes'] == value['entry']['raw_bytes'],
                    'Returned entry/final write lineage required')
            else:
                legacy.admitted.require(not value['native_writes'] and not value['decisions']
                    and value['components']['broker'] == detail['before_broker_sha256']
                    and metadata.read_bytes(self.store, value['entry'], kind='nightly-entry',
                        producer_sha256=producer) == b'null', 'Unavailable raw lifecycle changed state')
        return value

    # Publish one finite raw lifecycle result after all source/reservation links match.
    def _publish(self, directory, reservation, value, checkpoint):
        self._value(value, checkpoint)
        raw = legacy.physical(directory / 'reservation.json')
        operation = legacy.admitted.decoded(raw)
        legacy.admitted.require(sha256(raw).hexdigest() == reservation
            and operation['schema'] == SCHEMA and operation['source_sha256'] == sources()
            and operation['identity'] == self.store.identity and operation['pre_head'] == self.expected_head
            and self.store.snapshot()['head'] == self.expected_head
            and directory == self.operation(value['phase'], value['session'])
            and all(operation[key] == value[key] for key in ('phase', 'session', 'birth', 'previous'))
            and operation['context_sha256'] == value['context'], 'Raw lifecycle reservation differs')
        if value['phase'] == 'NIGHTLY_CLOSE' and value['detail']['status'] == 'NIGHTLY_BROKER_UNAVAILABLE':
            legacy.admitted.require(content(operation['before'], checkpoint, self.store.identity)
                [1:] == content(value['components'], checkpoint, self.store.identity)[1:],
                'Unavailable raw lifecycle persisted bytes differ')
        record = {'schema': SCHEMA, 'identity': self.store.identity, 'sources': sources(),
                  'operation': operation, 'reservation_sha256': reservation, 'value': value,
                  'native_operation_committed': False, 'durable_simulator_adoption': False,
                  'publication_barrier': 'CLOSED', 'packet_pipeline_integrated': False}
        reference = legacy.put(self.store, legacy.admitted.encoded(record))
        legacy.write_once(directory / 'result.json', legacy.admitted.encoded({'schema': SCHEMA, 'receipt': reference}))
        return reference

    # Read only physically reserved raw lifecycle receipts, never legacy or raw Cycle outcomes.
    def read_lifecycle(self, reference, *, raw_checkpoint):
        record = legacy.admitted.decoded(self.store.read_blob(reference, limit=legacy.CAP))
        legacy.admitted.require(type(record) is dict and set(record) == RECORD_KEYS
            and record['schema'] == SCHEMA and record['identity'] == self.store.identity
            and record['sources'] == sources() and record['native_operation_committed'] is False
            and record['durable_simulator_adoption'] is False and record['publication_barrier'] == 'CLOSED'
            and record['packet_pipeline_integrated'] is False, 'Exact reserved raw lifecycle receipt required')
        value, operation = record['value'], record['operation']
        directory = self.operation(operation['phase'], operation['session'], operation['pre_head'])
        raw = legacy.physical(directory / 'reservation.json')
        legacy.admitted.require(legacy.admitted.decoded(raw) == operation
            and sha256(raw).hexdigest() == record['reservation_sha256']
            and operation['schema'] == SCHEMA and operation['source_sha256'] == sources()
            and operation['identity'] == self.store.identity
            and all(operation[key] == value[key] for key in ('phase', 'session', 'birth', 'previous'))
            and operation['context_sha256'] == value['context']
            and legacy.admitted.decoded(legacy.physical(directory / 'result.json'))
                == {'schema': SCHEMA, 'receipt': reference}, 'Raw lifecycle physical lineage differs')
        self._value(value, raw_checkpoint)
        if value['phase'] == 'NIGHTLY_CLOSE' and value['detail']['status'] == 'NIGHTLY_BROKER_UNAVAILABLE':
            legacy.admitted.require(content(operation['before'], raw_checkpoint, self.store.identity)
                [1:] == content(value['components'], raw_checkpoint, self.store.identity)[1:], 'Unavailable persisted bytes differ')
        return record

    # Recover the originally reserved result without any model or broker reexecution.
    def recover_lifecycle(self, phase, session, *, context_sha256, birth, raw_checkpoint, previous=None):
        directory = self.operation(phase, session)
        operation = legacy.admitted.decoded(legacy.physical(directory / 'reservation.json'))
        expected = {'schema': SCHEMA, 'identity': self.store.identity, 'pre_head': self.expected_head,
                    'phase': phase, 'session': session, 'source_sha256': sources(),
                    'context_sha256': context_sha256, 'birth': birth, 'previous': previous}
        legacy.admitted.require(all(operation.get(key) == value for key, value in expected.items()),
                                'Conflicting raw lifecycle reservation')
        try:
            result = legacy.admitted.decoded(legacy.physical(directory / 'result.json'))
        except FileNotFoundError as error:
            raise StorePause('Interrupted raw lifecycle; never re-execute') from error
        legacy.admitted.require(type(result) is dict and set(result) == {'schema', 'receipt'}
                                and result['schema'] == SCHEMA, 'Raw lifecycle result marker required')
        self.read_lifecycle(result['receipt'], raw_checkpoint=raw_checkpoint)
        return result['receipt']

    # Require a reserved raw birth rather than adopting a standalone metadata receipt.
    def read_raw_birth(self, reference, *, raw_checkpoint):
        record = self.read_lifecycle(reference, raw_checkpoint=raw_checkpoint)
        legacy.admitted.require(record['value']['phase'] == 'BIRTH', 'Original raw birth required')
        return record['value']

    # Admit only raw Nightly lineage until raw Cycle final continuation is implemented.
    def raw_predecessor(self, reference, *, raw_checkpoint):
        return self.read_lifecycle(reference, raw_checkpoint=raw_checkpoint)['value']

    # Execute the isolated raw birth body once under the existing exclusive writer scope.
    def _initialize(self, context, *, raw_checkpoint):
        self._checkpoint(raw_checkpoint)
        legacy.admitted.require(type(context) is legacy.HoldingContext, 'Exact holding context required')
        context_hash = sha256(context.provenance).hexdigest()
        if self.operation('BIRTH', '2019-02-28').exists():
            return None, self.recover_lifecycle('BIRTH', '2019-02-28',
                context_sha256=context_hash, birth=None, raw_checkpoint=raw_checkpoint)
        legacy.admitted.require(legacy.LOCK.acquire(blocking=False), 'Concurrent raw lifecycle')
        try:
            data = context.validate()
            legacy.admitted.require(paper.save_state is legacy.SAVE_STATE
                and native.ReplayBroker._submit is legacy.SUBMIT, 'Original native birth bindings required')
            directory, reservation = self._reserve('BIRTH', '2019-02-28', context_hash, None, None, None)
            client = native.ReplayBroker(100000, 10)
            paper.save_state(self.root, paper.PaperState())
            refs = legacy.components(self.store, client, self.root, self.pins(), raw_checkpoint=raw_checkpoint)
            entry = metadata.capture(self.store, None, kind='nightly-entry',
                                     producer_sha256=sha256(Path(__file__).read_bytes()).hexdigest())
            context.validate()
            value = {'phase': 'BIRTH', 'session': '2019-02-28', 'context': legacy.put(self.store, context.provenance),
                'context_identity': legacy.context_identity(data), 'birth': None, 'previous': None,
                'components': refs, 'entry': entry, 'decisions': [],
                'native_writes': [write_reference(raw_checkpoint, refs['paper']['checkpoint'])],
                'detail': {'initial_cash': 100000, 'initial_holdings': {}, 'cost_bps': 10,
                           'cohort': data['symbols'], 'first': '2019-03-01', 'through': '2026-10-12'}}
            return client, self._publish(directory, reservation, value, raw_checkpoint)
        finally:
            legacy.LOCK.release()

    # Run the complete raw no-submission close body with explicit native evidence lineage.
    def _close(self, context, client, session, *, birth, previous, raw_checkpoint):
        self._checkpoint(raw_checkpoint)
        legacy.admitted.require(type(context) is legacy.HoldingContext and type(client) is native.ReplayBroker,
                                'Exact private context/broker required')
        context_hash = sha256(context.provenance).hexdigest()
        if self.operation('NIGHTLY_CLOSE', session).exists():
            result = self.recover_lifecycle('NIGHTLY_CLOSE', session, context_sha256=context_hash,
                                            birth=birth, previous=previous, raw_checkpoint=raw_checkpoint)
            legacy.admitted.require(self.read_lifecycle(result, raw_checkpoint=raw_checkpoint)['value']['previous']
                                    == previous, 'Conflicting raw predecessor')
            return result
        legacy.admitted.require(legacy.LOCK.acquire(blocking=False), 'Concurrent raw lifecycle')
        try:
            data = context.validate()
            birth_record = self.read_raw_birth(birth, raw_checkpoint=raw_checkpoint)
            prior = self.raw_predecessor(previous, raw_checkpoint=raw_checkpoint)
            legacy.admitted.require(birth_record['context_identity'] == prior['context_identity']
                == legacy.context_identity(data) and birth_record['context'] == prior['context'] == context_hash
                and (previous == birth or prior['birth'] == birth), 'Raw account/context lineage differs')
            current = legacy.components(self.store, client, self.root, self.pins(), raw_checkpoint=raw_checkpoint)
            legacy.admitted.require(content(current, raw_checkpoint, self.store.identity)
                == content(prior['components'], raw_checkpoint, self.store.identity), 'Raw pre-close components differ')
            if prior['phase'] == 'BIRTH':
                legacy.admitted.require(session == '2019-02-28', 'Original prior-close initialization required')
            else:
                legacy.admitted.require(date.fromisoformat(session) == legacy.intraday_orders.next_session(
                    date.fromisoformat(prior['session'])), 'Sequential raw nightly sessions required')
                legacy.admitted.require(prior['detail']['status'] == 'NATIVE_NIGHTLY_RETURNED',
                                        'Unavailable raw close cannot advance sessions')
            report, policy, index = context.select(session)
            at = legacy.live_policy_replay.instant(context.panel.dates[index],
                legacy.calendar.session_close(date.fromisoformat(session))) + timedelta(minutes=1)
            legacy.admitted.require(not legacy.live_policy_replay.due_actions(context.raw, index, at),
                                    'Raw economic coordinator evidence required before actions')
            directory, reservation = self._reserve('NIGHTLY_CLOSE', session, context_hash, birth, previous, current)
            began, tick = datetime.now(UTC), time.monotonic_ns()
            client.observe(at, legacy.live_policy_replay.account_marks(context.raw, index, at,
                           context.raw.daily_close[index]), False)
            before = codec.encode(client, **self.pins())
            old_attempts, old_orders = len(client.attempt_history), set(client._orders)
            output = io.StringIO()
            import contextlib

            with legacy.NativeCapture(self.store, self.root, client, policy, raw_checkpoint=raw_checkpoint) as capture:
                try:
                    with contextlib.redirect_stdout(output):
                        entry = legacy.market_daily.paper_trade(report, self.root, session, True,
                            client_factory=lambda: client, decision_at=at, holding_policy=policy)
                    status, reason = 'NATIVE_NIGHTLY_RETURNED', None
                except legacy.AlpacaTradingError as error:
                    entry, status, reason = None, 'NIGHTLY_BROKER_UNAVAILABLE', str(error)
                    after_error = legacy.components(self.store, client, self.root, self.pins(), raw_checkpoint=raw_checkpoint)
                    legacy.admitted.require(content(after_error, raw_checkpoint, self.store.identity)
                        [1:] == content(current, raw_checkpoint, self.store.identity)[1:]
                        and codec.encode(client, **self.pins()) == before
                        and not capture.decisions and not capture.raw_writes,
                        'Unavailable close changed native state or invoked policy')
            decisions = capture.finish()
            remaining = metadata.LIMIT - sum(ref['raw_bytes'] for ref in decisions)
            entry_ref = metadata.capture(self.store, entry, kind='nightly-entry',
                producer_sha256=sha256(Path(__file__).read_bytes()).hexdigest(), byte_limit=remaining)
            if status == 'NATIVE_NIGHTLY_RETURNED':
                saved = paper.load_state(self.root)
                legacy.admitted.require(bool(saved.history), 'Native close omitted saved history')
                encoder = json.JSONEncoder(indent=2, default=paper._state_json)
                hashed, length = sha256(), 0
                for text in encoder.iterencode(saved.history[-1]):
                    raw = text.encode(); length += len(raw)
                    legacy.admitted.require(length <= metadata.LIMIT, 'Saved entry metadata bound')
                    hashed.update(raw)
                legacy.admitted.require(hashed.hexdigest() == entry_ref['raw_sha256']
                    and length == entry_ref['raw_bytes'], 'Returned entry differs from native saved history')
            attempts = list(client.attempt_history[old_attempts:])
            accepted = [deepcopy(client._orders[key]) for key in client._orders if key not in old_orders]
            legacy.admitted.require(not attempts and not accepted and not capture.submissions,
                                    'Raw lifecycle native submission is not admitted')
            refs = legacy.components(self.store, client, self.root, self.pins(), raw_checkpoint=raw_checkpoint)
            context.validate()
            value = {'phase': 'NIGHTLY_CLOSE', 'session': session, 'context': legacy.put(self.store, context.provenance),
                'context_identity': legacy.context_identity(data), 'birth': birth, 'previous': previous,
                'components': refs, 'entry': entry_ref, 'decisions': decisions, 'native_writes': capture.raw_writes,
                'detail': {'status': status, 'reason': reason, 'hypothetical_decision_at': at.isoformat(),
                    'actual_compute_started_at': began.isoformat(), 'actual_compute_finished_at': datetime.now(UTC).isoformat(),
                    'actual_elapsed_ns': time.monotonic_ns() - tick, 'raw_submissions': attempts, 'accepted': accepted,
                    'holding_policy_calls': len(capture.decisions), 'native_stdout': output.getvalue(),
                    'before_broker_sha256': sha256(before).hexdigest(),
                    'entry_native_sha256': entry_ref['raw_sha256'], 'entry_native_bytes': entry_ref['raw_bytes']}}
            return self._publish(directory, reservation, value, raw_checkpoint)
        finally:
            legacy.LOCK.release()
