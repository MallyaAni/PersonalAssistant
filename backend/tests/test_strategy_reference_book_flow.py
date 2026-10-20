"""Normal collector and authenticated original history with observed hypothetical model positions."""

import base64
from copy import deepcopy
from dataclasses import asdict
from datetime import timedelta
from hashlib import sha256
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from backend.market import strategy_reference_book as ledger, strategy_reference_entries as reference
from backend.market import strategy_entries as entries, strategy_entry_history as history
from backend.market import strategy_publication as publication
from backend.tests.test_strategy_entries import NOW
from backend.tests.test_strategy_reference_entries import fixture,packet_for,publish


# Select the actual observed-book adapter with an explicitly synthetic original reference and native parsed packet.
def flow_fixture(root):
    snapshot,cache,quotes,page=fixture(root)
    book=ledger.initial(cache['reference_plan'],NOW.date().isoformat())
    ledger.commit(root,None,book,cache['reference_evidence'])
    cache.update(reference_book=book,reference_plan=ledger.current_plan(book),reference_evidence=asdict(book))
    return snapshot,cache,quotes,page


# Attach the real native quote receipt to a projected view before using the unchanged normal publication writer.
def publish_view(root,snapshot,cache,quotes,page,now):
    value=entries.project(snapshot,cache,quotes,now)
    value['quote_receipt']={key:page[key] for key in ('url','requested_at','received_at','status','sha256')}
    value['quote_receipt']['body_base64']=base64.b64encode(page['body']).decode()
    value['receipt_sha256']=publication._digest({k:v for k,v in value.items() if k!='receipt_sha256'})
    entries.publish(root,value)
    return value


# Exercise actual current/original metadata and normal collector ownership without account or provider operations.
class ReferenceBookFlowTests(unittest.TestCase):
    # The first Sell is advice only; one later original quote advances units and never generates a repeated Sell.
    def test_normal_collector_advances_only_later_quote_and_preserves_original(self):
        from backend.services.current_opportunity_collector import CurrentOpportunityCollector
        with TemporaryDirectory() as folder:
            root=Path(folder);snapshot,cache,quotes,page=flow_fixture(root)
            first=publish(root,snapshot,cache,quotes,page,NOW)
            self.assertEqual(first['version'],reference.PROGRESSING_VERSION)
            self.assertEqual(first['rows']['AAA']['action'],'Sell')
            book=ledger.load(root);self.assertEqual(book.generation,0)
            at=NOW+timedelta(seconds=10);_,later,_=packet_for(at)
            path=root/entries.learned_live_timing.CONFIG;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(cache['config_bytes'])
            collector=CurrentOpportunityCollector(root,enabled=False);collector._entry_cache=cache
            original_collect=entries.collect
            # Return only the current IEX quote endpoint; the current original forecast remains in cache.
            def transport(url,headers):
                self.assertIn('/quotes/',url);return 200,json.dumps({'quotes':later}).encode()
            # Exercise the ordinary collector with an explicit unit-only observation clock, never the real feed.
            def collect(root,cache):
                return original_collect(root,cache,clock=lambda:at,transport=transport)
            with patch.object(history.learned_live_holding,'read_configuration',return_value=(b'synthetic',{'cost_bps':10})), \
                    patch.object(entries.alpaca,'credentials',return_value={}),patch.object(entries,'collect',side_effect=collect), \
                    patch.object(entries.learned_live_timing,'market_transport',side_effect=transport), \
                    patch.object(entries,'acquire',side_effect=AssertionError('no repeated forecast or native capture')):
                self.assertEqual(collector._collect_once()['status'],'collected')
                changed=ledger.load(root);self.assertEqual(changed.generation,1)
                self.assertLess(dict(changed.positions)['AAA'],dict(book.positions)['AAA'])
                current=entries.read(root,snapshot,at)
                self.assertEqual(current['rows']['AAA']['state'],'no_trade')
                self.assertTrue(current['rows']['AAA']['attempt_resolved'])
                self.assertEqual(current['rows']['AAA']['size_weight'],0)
                original=history.read(root,'AAA',first['completed_at'],snapshot['snapshot_id'],at+timedelta(hours=1))
                self.assertEqual(original['original']['action'],'Sell')
                self.assertEqual(original['original']['size_weight'],first['rows']['AAA']['size_weight'])
                self.assertEqual(len(history.recent(root,'AAA',at+timedelta(hours=1))['items']),1)
                self.assertEqual(collector._collect_once()['status'],'collected')
                self.assertEqual(ledger.load(root),changed)

    # Missing later price evidence resolves an expired attempt without inventing either proceeds or a fill.
    def test_expired_quote_is_not_a_hypothetical_fill(self):
        with TemporaryDirectory() as folder:
            root=Path(folder);snapshot,cache,quotes,page=flow_fixture(root)
            first=publish(root,snapshot,cache,quotes,page,NOW);before=ledger.load(root)
            later=NOW+timedelta(seconds=40);_,fresh,page=packet_for(later)
            with patch.object(history.learned_live_holding,'read_configuration',return_value=(b'synthetic',{'cost_bps':10})):
                reference.observe_book(root,snapshot,cache,page,later)
                after=ledger.load(root)
                self.assertEqual((after.positions,after.cash,after.fees),(before.positions,before.cash,before.fees))
                value=publish_view(root,snapshot,cache,fresh,page,later)
                self.assertEqual(value['rows']['AAA']['size_weight'],0)
                restored=history.read(root,'AAA',first['completed_at'],snapshot['snapshot_id'],later)
                self.assertEqual(restored['original']['evidence'],first['rows']['AAA']['evidence'])

    # A pointer interruption restores its original result before another current view can repeat the model trade.
    def test_interrupted_book_pointer_resumes_original_result_before_projection(self):
        with TemporaryDirectory() as folder:
            root=Path(folder);snapshot,cache,quotes,page=flow_fixture(root)
            first=publish(root,snapshot,cache,quotes,page,NOW);later=NOW+timedelta(seconds=10);_,fresh,page=packet_for(later)
            with patch.object(history.learned_live_holding,'read_configuration',return_value=(b'synthetic',{'cost_bps':10})):
                with patch.object(ledger,'_point',side_effect=OSError('explicit first pointer interruption')):
                    with self.assertRaises(OSError):reference.observe_book(root,snapshot,cache,page,later)
                self.assertEqual(ledger.load(root).generation,0)
                restored=reference.prepare_book(root,snapshot,later)
                self.assertEqual(restored.generation,1)
                reference.observe_book(root,snapshot,cache,page,later)
                self.assertEqual(ledger.load(root),restored)
                current=publish_view(root,snapshot,cache,fresh,page,later)
                self.assertIsNone(current['rows']['AAA']['action'])
                self.assertEqual(current['rows']['AAA']['original_intent']['receipt_sha256'],first['rows']['AAA']['original_intent']['receipt_sha256'])

    # Complete reference calculations are shared while per-stock originals remain below the unchanged131072-byte cap.
    def test_shared_original_proof_is_finite_and_immutable(self):
        with TemporaryDirectory() as folder:
            root=Path(folder);snapshot,cache,quotes,page=flow_fixture(root)
            publication.publish(root,snapshot,NOW);cache['stored_forecast']=entries.store_forecast(root,cache['forecast'])
            value=entries.project(snapshot,cache,quotes,NOW)
            value['quote_receipt']={key:page[key] for key in ('url','requested_at','received_at','status','sha256')}
            value['quote_receipt']['body_base64']=base64.b64encode(page['body']).decode()
            for number in range(94):
                value['rows']['S'+str(number)]=deepcopy(value['rows']['AAA'])
                value['rows']['S'+str(number)]['evidence']['features']={f'bounded_feature_{i}':float(i) for i in range(30)}
            original=reference.original_intent(root,value,'AAA')
            encoded=json.dumps(original,sort_keys=True,allow_nan=False).encode()
            self.assertLess(len(encoded),history.MAX_RECORD_BYTES)
            self.assertGreater(original['reference_proof_ref']['bytes'],history.MAX_RECORD_BYTES)
            self.assertLessEqual(original['reference_proof_ref']['bytes'],entries.MAX_BYTES)
            proof=reference.read_proof(root,original['reference_proof_ref'])
            self.assertEqual(len(proof['rows']),95)
            again=reference.original_intent(root,value,'AAA')
            self.assertEqual(again,original)
            path=root/entries.DIRECTORY/'reference-proofs'/(original['reference_proof_ref']['sha256']+'.json')
            path.write_bytes(path.read_bytes()+b' ')
            with self.assertRaises(ValueError):reference.read_proof(root,original['reference_proof_ref'])


# Read the same current and historical hypothetical state over the real authenticated API without advancing it.
class ReferenceBookHTTPTests(unittest.IsolatedAsyncioTestCase):
    # GETs preserve model units and first Sell evidence while current state shows no duplicate trade after its proxy execution.
    async def test_owner_original_after_hypothetical_execution_and_get_is_read_only(self):
        from fastapi import FastAPI
        from httpx import ASGITransport,AsyncClient
        from backend.api.v1 import market_allocation,market_simulation
        from backend.config.settings import settings
        from backend.core.auth import issue_user_token
        from backend.agents.trading.desk import paper
        from backend.market import alpaca_trading
        app=FastAPI();app.include_router(market_allocation.router,prefix='/api/v1');app.include_router(market_simulation.router,prefix='/api/v1')
        with TemporaryDirectory() as folder:
            root=Path(folder);snapshot,cache,quotes,page=flow_fixture(root)
            first=publish(root,snapshot,cache,quotes,page,NOW);later=NOW+timedelta(seconds=10);_,fresh,page=packet_for(later)
            with patch.object(history.learned_live_holding,'read_configuration',return_value=(b'synthetic',{'cost_bps':10})), \
                    patch.object(settings,'AUTH_REQUIRED',True),patch.object(settings,'MARKET_DESK_USER','desk_user'),patch.object(settings,'MARKET_DATA_ROOT',str(root)), \
                    patch.object(market_allocation,'datetime',SimpleNamespace(now=lambda tz:later)), \
                    patch.object(market_simulation,'datetime',SimpleNamespace(now=lambda tz:later+timedelta(hours=1))), \
                    patch.object(paper,'load_state',side_effect=AssertionError('no paper access')), \
                    patch.object(alpaca_trading,'client_from_env',side_effect=AssertionError('no broker access')):
                reference.observe_book(root,snapshot,cache,page,later);publish_view(root,snapshot,cache,fresh,page,later)
                history.remember_latest(root,later);before=ledger.load(root)
                owner={'Authorization':'Bearer '+issue_user_token('desk_user',scopes=['memory:read'])}
                foreign={'Authorization':'Bearer '+issue_user_token('other_user',scopes=['memory:read'])}
                async with AsyncClient(transport=ASGITransport(app=app),base_url='http://test') as client:
                    url='/api/v1/market/desk_user/desk/model-allocation'
                    response=await client.get(url,headers=owner)
                    self.assertEqual(response.status_code,200)
                    self.assertEqual(response.json()['entry_assessment']['rows']['AAA']['size_weight'],0)
                    self.assertEqual(response.json()['entry_assessment']['version'],reference.PROGRESSING_VERSION)
                    self.assertEqual((await client.get(url,headers=foreign)).status_code,403)
                    self.assertEqual((await client.get(url)).status_code,401)
                    original=await client.get('/api/v1/market/desk_user/desk/strategy-simulation/AAA/recommendation',
                        headers=owner,params={'completed_at':first['completed_at'],'snapshot_id':snapshot['snapshot_id']})
                    self.assertEqual(original.status_code,200)
                    self.assertEqual(original.json()['original']['action'],'Sell')
                self.assertEqual(ledger.load(root),before)
