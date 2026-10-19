"""Read committed raw Cycle finals without admitting execution or native adoption.

The distinct bridge binds reserved Store decisions/submissions, the final raw
reconciliation graph and an explicit earlier Nightly lineage. It does not run a
Cycle, model, sender, settlement or restore an account.
"""
from datetime import date
from hashlib import sha256
from pathlib import Path

from backend.market import historical_conditional_cycle as cycle
from backend.market import historical_paper_component as component
from backend.market import historical_timing_packet as packet
from backend.market.historical_packet_registry import digest
from backend.market.historical_packet_store import Store, StorePause

LINEAGE = 'raw-nightly-cycle-lineage/1'
LINEAGE_KEYS = {'schema', 'birth', 'previous_nightly', 'context', 'context_identity'}
FINAL_KEYS = {'stage', 'settlement_submission_head', 'settlement_cycle',
              'raw_nightly_lineage', 'resolved'}


# Include both bridge and unchanged Cycle sources in the raw Nightly reservation.
def sources():
    return {str(Path(module.__file__)): sha256(Path(module.__file__).read_bytes()).hexdigest()
            for module in (cycle,)} | {str(Path(__file__)): sha256(Path(__file__).read_bytes()).hexdigest()}


# Compare exact opaque paper content across separately captured component references.
def paper_content(reference, checkpoint, identity):
    root = component.verify(reference, checkpoint, expected_identity=identity)
    return root['raw_sha256'], root['raw_bytes']


# Require actual committed reserved operations and their indexed immediate ancestry.
def committed_operation(store, head, cycle_sha256, stage):
    operation = packet._digest({'cycle': cycle_sha256, 'stage': stage})
    entry = store.recover_operation(operation)
    if (entry['sha256'] != head or entry['cycle_sha256'] != cycle_sha256
            or entry['stage'] != stage or cycle._head_entry(store, head) != entry):
        raise ValueError('Exact committed raw Cycle operation required')
    return entry


# Read semantic latch absence or exact bytes from the explicitly bound namespace.
def latch_bytes(store, root, session):
    namespace = store.metadata_reservation
    if namespace is None:
        return cycle._file(cycle.entry_timing.latch_path(root, date.fromisoformat(session)), absent=True)
    if namespace.header['account'] != str(root):
        raise ValueError('Original metadata latch workspace differs')
    return namespace.read_latch(session)


# Require the exact final current-session latch before allowing a Nightly observation.
def verify_latch(store, root, session, reference):
    expected = None if reference is None else store.read_blob(reference, limit=cycle.META_CAP)
    if latch_bytes(store, root, session) != expected:
        raise ValueError('Raw Cycle current latch differs')


# Authenticate a final raw save only when its exact receipt is the authoritative head.
def read_final(store, reference, pins, *, expected_head, raw_checkpoint):
    if (type(store) is not Store or store.identity != pins['identity_sha256']
            or pins['identity']['source_revision'] != cycle.CURRENT):
        raise ValueError('Exact same-account raw Cycle Store required')
    digest(reference); digest(expected_head)
    state = store.snapshot()
    if state['head'] != expected_head or state['next_stage'] != 'PRIOR_VERIFIED':
        raise StorePause('Authoritative committed raw Cycle head required')
    entry = cycle._head_entry(store, expected_head)
    if (entry['stage'] != 'OUTCOME_COMMITTED' or entry['receipt_sha256'] != reference
            or entry['cycle_sha256'] != state['cycle']):
        raise ValueError('Exact committed final raw Cycle receipt required')
    receipt = cycle._read_receipt(store, reference, pins, raw_checkpoint=raw_checkpoint)
    if (receipt['schema'] != 'private-conditional-cycle-receipt/2'
            or receipt['actual_historical_clocks_or_fills'] is not False
            or 'raw_reconciliation' not in receipt):
        raise ValueError('Source-bound final raw reconciliation required')
    detail = receipt['detail']
    if (type(detail) is not dict or set(detail) != FINAL_KEYS
            or detail['stage'] != 'OUTCOME_COMMITTED'
            or detail['settlement_submission_head'] != entry['parent']
            or detail['settlement_cycle'] != entry['cycle_sha256']
            or type(detail['resolved']) is not dict
            or detail['resolved'].get('stage') != 'OUTCOME_COMMITTED'):
        raise ValueError('Exact raw final settlement detail required')
    lineage = detail['raw_nightly_lineage']
    if type(lineage) is not dict or set(lineage) != LINEAGE_KEYS or lineage['schema'] != LINEAGE:
        raise ValueError('Distinct raw Nightly Cycle lineage required')
    for key in LINEAGE_KEYS - {'schema'}:
        digest(lineage[key])
    submission_entry = committed_operation(
        store, entry['parent'], entry['cycle_sha256'], 'SUBMISSION_CAPTURED')
    decision_entry = committed_operation(
        store, submission_entry['parent'], entry['cycle_sha256'], 'DECISION_FROZEN')
    submission = cycle._read_receipt(store, submission_entry['receipt_sha256'], pins, raw_checkpoint=raw_checkpoint)
    decision = cycle._read_receipt(store, decision_entry['receipt_sha256'], pins, raw_checkpoint=raw_checkpoint)
    pre = cycle._read_receipt(store, receipt['raw_reconciliation']['pre_settlement_receipt'],
                 pins, raw_checkpoint=raw_checkpoint)
    for record, stage in ((submission, 'SUBMISSION_CAPTURED'), (decision, 'DECISION_FROZEN')):
        if (record['schema'] != 'private-conditional-cycle-receipt/2'
                or record['session'] != receipt['session'] or record['context'] != receipt['context']
                or record['detail'].get('stage') != stage
                or record['detail'].get('raw_nightly_lineage') != lineage
                or 'raw_reconciliation' in record
                or record['actual_historical_clocks_or_fills'] is not False):
            raise ValueError('Reserved raw Cycle context/lineage differs')
    if pre['detail'] != {'stage': 'PRE_SETTLEMENT_OUTCOME',
            'submission_head': entry['parent'], 'cycle': entry['cycle_sha256'],
            'raw_nightly_lineage': lineage, 'resolved': detail['resolved']}:
        raise ValueError('Original raw final resolved outcome differs')
    if (pre['components']['latch'] != submission['components']['latch']
            or paper_content(pre['components']['paper'], raw_checkpoint, store.identity)
            != paper_content(submission['components']['paper'], raw_checkpoint, store.identity)):
        raise ValueError('Raw settlement changed submission paper or latch before fold')
    session = date.fromisoformat(receipt['session'])
    context = receipt['context']
    if type(context) is not dict or set(context) != {'raw', 'sha256'}:
        raise ValueError('Distinct original Cycle context required')
    parsed = cycle.market.read_context(cycle.market.Context(context['raw'].encode(), context['sha256']))
    if (session.isoformat() != receipt['session']
            or parsed['window']['completed_at'][:10] != receipt['session']):
        raise ValueError('Raw Cycle context session differs')
    cycle._raw_reconciliation(store, receipt, pins, raw_checkpoint)
    if store.snapshot() != state:
        raise StorePause('Raw Cycle head changed during final read')
    return {'receipt': receipt, 'entry': entry, 'lineage': lineage,
            'submission': submission, 'decision': decision}
