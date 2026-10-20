"""Read the persisted daily model objective without extending trade permission."""

from datetime import datetime
from hashlib import sha256
from pathlib import Path

from backend.market import calendar, strategy_history_publication as history
from backend.market import strategy_publication as publication, strategy_reference_book as ledger

VERSION = 'strategy-reference-positions/1'
BASIS = 'original_persisted_daily_reference_targets_not_viewer_holdings'


# Distinguish a reference installation from a legacy fresh-capital-only installation.
def configured(root):
    return any((Path(root)/directory).exists() for directory in (history.DIRECTORY, ledger.DIRECTORY))


# Read only original day targets; quote expiry and resolved attempts cannot replace them with fresh-capital targets.
def read(root, snapshot, now):
    if not configured(root):
        return None
    value = {'version': VERSION, 'basis': BASIS, 'status': 'unavailable', 'rows': {},
        'snapshot_id': snapshot['snapshot_id'], 'publication_receipt_sha256': snapshot['receipt_sha256'],
        'strategy_identity': snapshot['strategy_identity'], 'session': snapshot['session'],
        'valid_until': snapshot['valid_until'], 'reader_sha256': sha256(Path(__file__).read_bytes()).hexdigest()}
    try:
        publication.validate(snapshot, now, expected_sources=publication._sources())
        book = ledger.load(root, recover=False)
        book.validate()
        book.plan.reference.validate(snapshot)
        trade = datetime.fromisoformat(snapshot['valid_until']).astimezone(calendar.NEW_YORK).date().isoformat()
        if (book.plan.snapshot_id != snapshot['snapshot_id']
                or book.plan.publication_receipt_sha256 != snapshot['receipt_sha256']
                or book.trade_session != trade or {row[0] for row in book.plan.rows} != set(snapshot['rows'])):
            raise ValueError('Original daily model objective differs from publication')
        if (any(not ledger.transition._number(target) or target > 1
                or grade != snapshot['grade_signals'][name]['grade']
                for name, _, _, target, grade in book.plan.rows)
                or sum(row[3] for row in book.plan.rows) > 1 + 1e-10):
            raise ValueError('Finite complete original daily targets required')
        value.update(status='available', day_id=book.day_id(), book_sha256=book.receipt_sha256(),
            generation=book.generation, trade_session=book.trade_session,
            rows={name: {'target_weight': target, 'evidence': {**snapshot['rows'][name]['evidence'],
                'model_position_size': target, 'sizing_basis': BASIS}}
                for name, _, _, target, _ in book.plan.rows})
    except (OSError, ValueError, TypeError, KeyError, AttributeError, OverflowError):
        value['reason'] = 'Original persisted daily model objective could not be verified'
    value['receipt_sha256'] = publication._digest(value)
    ledger._bytes(value)
    return value
