"""Persistent daily model objectives remain distinct from expiring trade advice."""

from copy import deepcopy
from dataclasses import asdict
from datetime import timedelta
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from backend.market import strategy_position_view as view, strategy_publication as publication
from backend.market import strategy_reference_book as ledger, strategy_reference_entries as reference
from backend.market import strategy_reference_transition as transition, strategy_entries as entries
from backend.tests.test_strategy_reference_transition import snapshot_for, book_for
from backend.tests.test_strategy_entries import NOW


# Seed actual native continuous-target arithmetic where preserving an existing position changes fresh-capital targets.
def prepared(root):
    snapshot = snapshot_for(root, {'AAA': 0., 'BBB': .25, 'CCC': .25, 'DDD': .25, 'EEE': .25}, {'AAA': None})
    snapshot['identity']['config_sha256'] = sha256(b'synthetic').hexdigest()
    snapshot['snapshot_id'] = publication._digest(snapshot['identity'])
    snapshot['receipt_sha256'] = publication._digest({k:v for k,v in snapshot.items() if k!='receipt_sha256'})
    plan = transition.prepare(snapshot, book_for(snapshot, {'AAA': .007}, .3), NOW)
    book = ledger.initial(plan, NOW.date().isoformat())
    ledger.commit(root, None, book, {'explicit_synthetic_objective': True})
    publication.publish(root, snapshot, NOW)
    return snapshot, book


# Assert on persisted original objectives, source/clock refusal and ordinary collector ownership.
class PositionViewTests(unittest.TestCase):
    # A later candle reads the same original native objective, not fresh-capital allocation or recalculation.
    def test_original_target_survives_entry_expiry_and_reads_do_not_write(self):
        with TemporaryDirectory() as folder:
            root = Path(folder); snapshot, book = prepared(root)
            original = deepcopy(snapshot)
            before = {str(path.relative_to(root)): path.read_bytes() for path in root.rglob('*') if path.is_file()}
            with patch.object(reference, 'prepare_book', side_effect=AssertionError('GET cannot prepare')), \
                    patch.object(transition, 'prepare', side_effect=AssertionError('GET cannot calculate')):
                first = view.read(root, snapshot, NOW)
                later = view.read(root, snapshot, NOW + timedelta(hours=2))
            self.assertEqual(first, later)
            self.assertEqual(first['status'], 'available')
            self.assertAlmostEqual(first['rows']['BBB']['target_weight'], .075)
            self.assertEqual(first['rows']['BBB']['target_weight'], dict((row[0], row[3]) for row in book.plan.rows)['BBB'])
            self.assertEqual(snapshot['rows']['BBB']['target_weight'], .25)
            self.assertEqual(snapshot, original)
            self.assertEqual(before, {str(path.relative_to(root)): path.read_bytes() for path in root.rglob('*') if path.is_file()})

    # Invalid reference state never becomes a fresh-capital fallback and GET never repairs a pointer.
    def test_missing_corrupt_and_foreign_reference_refuse(self):
        with TemporaryDirectory() as folder:
            root = Path(folder); snapshot, _ = prepared(root)
            pointer = root/ledger.DIRECTORY/'latest.json'; original = pointer.read_bytes()
            for body in (None, b'{', original.replace(b'"generation": 0', b'"generation": 999')):
                if body is None: pointer.unlink()
                else: pointer.write_bytes(body)
                self.assertEqual(view.read(root, snapshot, NOW)['rows'], {})
                self.assertEqual(pointer.exists(), body is not None)
            pointer.write_bytes(original)
            changed = deepcopy(snapshot); changed['identity']['model_revision'] = 'foreign'
            changed['snapshot_id'] = publication._digest(changed['identity'])
            changed['receipt_sha256'] = publication._digest({k:v for k,v in changed.items() if k!='receipt_sha256'})
            self.assertEqual(view.read(root, changed, NOW)['status'], 'unavailable')
            self.assertEqual(view.read(root, snapshot, NOW.replace(hour=16))['status'], 'unavailable')

    # History installation requires an initialized book; truly legacy installations keep their old response contract.
    def test_uninitialized_history_is_explicit_but_legacy_is_absent(self):
        with TemporaryDirectory() as folder:
            root = Path(folder); snapshot = snapshot_for(root, {'AAA': .17})
            self.assertIsNone(view.read(root, snapshot, NOW))
            (root/view.history.DIRECTORY).mkdir(parents=True)
            self.assertEqual(view.read(root, snapshot, NOW)['status'], 'unavailable')

    # The writer prepares a closed-session objective before provider collection, with no preparation in API GETs.
    def test_closed_normal_collector_prepares_before_collection(self):
        from backend.services import current_opportunity_collector as service
        with TemporaryDirectory() as folder:
            root = Path(folder); snapshot, _ = prepared(root)
            order = []
            # Observe writer ownership without substituting a provider or invoking an account.
            def prepare(root, snapshot, now):
                order.append('prepare')
                return ledger.load(root)
            # A closed numerical collection performs no provider operation.
            def collect(root, cache):
                order.append('collect')
                return {'status': 'closed'}
            with patch.object(service, 'datetime', SimpleNamespace(now=lambda tz: NOW.replace(hour=8))), \
                    patch.object(publication.learned_live_holding, 'read_configuration', return_value=(b'synthetic', {'cost_bps':10})), \
                    patch.object(reference, 'prepare_book', side_effect=prepare), \
                    patch.object(entries, 'collect', side_effect=collect):
                self.assertEqual(service.CurrentOpportunityCollector(root, enabled=False)._collect_once()['status'], 'closed')
            self.assertEqual(order, ['prepare', 'collect'])


# Verify the original owner-only HTTP read and no-write behavior after current numerical evidence has expired.
class PositionViewHTTPTests(unittest.IsolatedAsyncioTestCase):
    # Repeated owner GETs retain one original objective; foreign/anonymous reads fail and damaged books remain unavailable.
    async def test_owner_current_read_preserves_original_position_and_never_repairs(self):
        from fastapi import FastAPI
        from httpx import ASGITransport, AsyncClient
        from backend.api.v1 import market_allocation
        from backend.config.settings import settings
        from backend.core.auth import issue_user_token
        app = FastAPI(); app.include_router(market_allocation.router, prefix='/api/v1')
        with TemporaryDirectory() as folder:
            root = Path(folder); snapshot, book = prepared(root); later = NOW + timedelta(hours=2)
            with patch.object(settings, 'AUTH_REQUIRED', True), patch.object(settings, 'MARKET_DESK_USER', 'desk_user'), \
                    patch.object(settings, 'MARKET_DATA_ROOT', str(root)), \
                    patch.object(market_allocation, 'datetime', SimpleNamespace(now=lambda tz: later)), \
                    patch.object(publication.learned_live_holding, 'read_configuration', return_value=(b'synthetic', {'cost_bps':10})), \
                    patch.object(reference, 'prepare_book', side_effect=AssertionError('GET writer refused')):
                owner = {'Authorization': 'Bearer '+issue_user_token('desk_user', scopes=['memory:read'])}
                foreign = {'Authorization': 'Bearer '+issue_user_token('other', scopes=['memory:read'])}
                url = '/api/v1/market/desk_user/desk/model-allocation'
                async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
                    response = await client.get(url, headers=owner)
                    self.assertEqual(response.status_code, 200)
                    value = response.json()
                    self.assertEqual(value['rows'], snapshot['rows'])
                    self.assertAlmostEqual(value['reference_positions']['rows']['BBB']['target_weight'], .075)
                    self.assertEqual(value['reference_positions']['book_sha256'], book.receipt_sha256())
                    self.assertEqual(response.headers['cache-control'], 'private, no-store')
                    self.assertEqual((await client.get(url, headers=foreign)).status_code, 403)
                    self.assertEqual((await client.get(url)).status_code, 401)
                    pointer = root/ledger.DIRECTORY/'latest.json'; pointer.unlink()
                    bad = (await client.get(url, headers=owner)).json()
                    self.assertEqual(bad['status'], 'available')
                    self.assertEqual(bad['reference_positions']['rows'], {})
                    self.assertFalse(pointer.exists())
