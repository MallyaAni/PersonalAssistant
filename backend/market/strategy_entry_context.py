"""Read original published daily inputs for account-independent entry inference.

This is a distinct input reader, not an extension of a holding forecast's
recomputation deadline. It never restores a holding head or reuses its forecasts.
The native timing feature builder receives the original price/grade/membership
prefix, authenticated against the already published recommendation snapshot.
"""

from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np

from backend.market import calendar, forward_arithmetic, grade_led_policy
from backend.market import strategy_publication as publication
from backend.market.daily_arithmetic_bridge import _hash

MAX_ARCHIVE = 16 * 1024 * 1024


# Keep the exact original daily prefix and its evidence separate from new market observations.
@dataclass(frozen=True)
class EntryContext:
    panel: SimpleNamespace
    grades: np.ndarray
    eligible: np.ndarray
    daily_as_of: datetime
    receipt: dict


# Read a finite original file once and reject symlinks or changed bytes during the read.
def _read(path, maximum):
    path = Path(path)
    if path.is_symlink():
        raise ValueError("Original context file cannot be a symlink")
    with path.open('rb') as stream:
        before = stream.fileno()
        import os
        initial = os.fstat(before)
        if not 0 < initial.st_size <= maximum:
            raise ValueError("Original context exceeds its finite input bound")
        raw = stream.read(maximum + 1)
        final = os.fstat(before)
    fields = ('st_dev', 'st_ino', 'st_size', 'st_mtime_ns')
    if len(raw) != initial.st_size or any(getattr(initial, key) != getattr(final, key) for key in fields):
        raise ValueError("Original context changed during read")
    return raw


# Authenticate stored input arrays at the real observation clock without re-running holding inference.
def load(root, snapshot, now):
    publication.validate(snapshot, now, expected_sources=publication._sources())
    identity = snapshot['identity']
    descriptor = identity['close_context']
    name = descriptor['directory']
    if (not isinstance(name, str) or len(name) != 32
            or any(letter not in '0123456789abcdef' for letter in name)
            or descriptor['receipt_sha256'] != identity['close_receipt_sha256']):
        raise ValueError("Original published close context descriptor required")
    base = Path(root) / 'desk/learned-holding/observations'
    folder = base / name
    if folder.is_symlink() or folder.resolve().parent != base.resolve():
        raise ValueError("Original context must remain in its dedicated namespace")
    raw = _read(folder / 'close.json', 131072)
    if sha256(raw).hexdigest() != descriptor['receipt_sha256']:
        raise ValueError("Original close context receipt differs")
    receipt = json.loads(raw)
    original = receipt['identity']
    if (receipt['identity_sha256'] != forward_arithmetic.base._json_hash(original)
            or original['policy'] != 'forward-holding-close/1-shadow'
            or original['model_publication_sha256'] != identity['holding_model_receipt_sha256']
            or original['prefix_sha256'] != identity['prefix_sha256']
            or original['published_at'] != snapshot['observed_at']
            or receipt['arrays_sha256'] != descriptor['arrays_sha256']):
        raise ValueError("Original published daily context identity differs")
    archive_raw = _read(folder / 'close.npz', MAX_ARCHIVE)
    if sha256(archive_raw).hexdigest() != descriptor['arrays_sha256']:
        raise ValueError("Original daily context archive differs")
    from io import BytesIO
    from zipfile import ZipFile
    with ZipFile(BytesIO(archive_raw)) as zipped:
        if sum(row.file_size for row in zipped.infolist()) > 32 * 1024 * 1024:
            raise ValueError("Original daily context expanded size exceeds its bound")
    with np.load(BytesIO(archive_raw), allow_pickle=False) as archive:
        required = {'dates', 'symbols', 'features', 'prices', 'forecasts', 'support', 'history_prices', 'history_grades'}
        if set(archive.files) != required:
            raise ValueError("Exact original context fields required")
        arrays = {key: archive[key] for key in archive.files}
    dates, symbols = arrays['dates'], tuple(arrays['symbols'].tolist())
    prices, grades = arrays['history_prices'], arrays['history_grades']
    if (dates.dtype != np.dtype('datetime64[D]') or not 1 <= len(dates) <= 10000
            or not 2 <= len(symbols) <= 512 or len(set(symbols)) != len(symbols)
            or str(dates[-1]) != snapshot['session'] or list(symbols) != original['symbols']
            or prices.shape != (len(dates), len(symbols)) or grades.shape != prices.shape
            or not np.isin(grades, (-1, 0, 1, 2, 3)).all()):
        raise ValueError("Aligned original daily context required")
    eligible = grades >= 0
    for benchmark in ('SPY', 'QQQ'):
        if benchmark not in symbols:
            raise ValueError("Original model benchmarks required")
        eligible[:, symbols.index(benchmark)] = False
    for key, value in arrays.items():
        if key != 'symbols' and _hash(value) != original['array_sha256'][key]:
            raise ValueError("Original daily context array differs: " + key)
    for key, value in (('dates', dates), ('prices', prices), ('grades', grades), ('eligible', eligible)):
        if _hash(value) != identity['prefix_sha256'][key]:
            raise ValueError("Original daily prefix differs: " + key)
    for stock, symbol in enumerate(symbols):
        if symbol in snapshot['grade_signals'] and grade_led_policy.LETTERS[int(grades[-1, stock])] != snapshot['grade_signals'][symbol]['grade']:
            raise ValueError("Original published stock grade differs")
    published = datetime.fromisoformat(original['published_at'])
    forward_arithmetic._close_window(dates[-1], published)
    years, exchange = calendar.reviewed_sessions()
    trading = datetime.fromisoformat(snapshot['valid_until']).astimezone(calendar.NEW_YORK).date()
    prior = np.busday_offset(np.datetime64(trading), -1, busdaycal=exchange)
    if trading.year not in years or dates[-1] != prior or not published <= now:
        raise ValueError("Entry context must belong to the immediately prior session")
    for array in (dates, prices, grades, eligible):
        array.flags.writeable = False
    return EntryContext(SimpleNamespace(dates=dates, tickers=symbols, adj_close=prices), grades, eligible, published,
        {'contract':'strategy-entry-context/1', 'snapshot_id':snapshot['snapshot_id'],
         'publication_receipt_sha256':snapshot['receipt_sha256'], 'close_receipt_sha256':descriptor['receipt_sha256'],
         'arrays_sha256':descriptor['arrays_sha256'], 'prior_session':snapshot['session'],
         'trade_session':trading.isoformat(),
         'source_sha256':sha256(Path(__file__).read_bytes()).hexdigest(),
         'holding_forecast_recomputed':False, 'account_inputs':False})
