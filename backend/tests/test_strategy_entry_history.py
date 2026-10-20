"""Original numerical advice remains source-bound and readable after quote expiry."""

import base64
from copy import deepcopy
from datetime import timedelta
import importlib.util
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from backend.market import strategy_entries as entries, strategy_entry_history as history, strategy_publication as publication
from backend.tests.test_strategy_entries import fixture,timing_cache,NOW


# Persist an actual collector-format quote receipt, immutable publication and original first recommendation.
def original(root):
    snapshot,_,_=fixture(root)
    publication.publish(root,snapshot,NOW)
    cache,quotes,_=timing_cache(snapshot)
    cache['stored_forecast']=entries.store_forecast(root,cache['forecast'])
    # Keep the response parser and receipt generation real while supplying explicit synthetic market inputs.
    def transport(url,headers):
        return 200,json.dumps({'quotes':quotes}).encode()
    page=entries.market.capture_quotes(cache['forecast'].receipt['symbols'],transport=transport,headers={},clock=lambda:NOW)
    value=entries.project(snapshot,cache,quotes,NOW)
    value['quote_receipt']={key:page[key] for key in ('url','requested_at','received_at','status','sha256')}
    value['quote_receipt']['body_base64']=base64.b64encode(page['body']).decode()
    value['receipt_sha256']=publication._digest({k:v for k,v in value.items() if k!='receipt_sha256'})
    entries.publish(root,value)
    path=next((root/entries.DIRECTORY/'recommendations'/'2026-01-07').glob('*.json'))
    return snapshot,value,path


# Test exact original content and independent historical expiry behavior, not a regenerated recommendation.
class OriginalEntryTests(unittest.TestCase):
    # Expired quotes and damaged latest pointers cannot replace the original decision, price or technical evidence.
    def test_original_after_expiry_ignores_latest_and_never_acquires(self):
        with TemporaryDirectory() as directory:
            root=Path(directory);snapshot,value,path=original(root);raw=path.read_bytes()
            (root/publication.DIRECTORY/'latest.json').write_text('foreign latest publication')
            (root/entries.DIRECTORY/'latest.json').write_text('later numerical observation')
            with patch.object(history.learned_live_holding,'read_configuration',return_value=(b'fixture',{'cost_bps':10})),patch.object(entries,'acquire',side_effect=AssertionError('must not acquire')),patch.object(publication,'read',side_effect=AssertionError('must not read latest')):
                result=history.read(root,'AAA',value['completed_at'],snapshot['snapshot_id'],NOW+timedelta(days=10))
            self.assertEqual(result['original'],json.loads(raw))
            self.assertEqual(result['original']['size_weight'],.17)
            self.assertEqual(result['original']['evidence']['observed_price'],100)
            self.assertFalse(result['current_instruction'])
            self.assertTrue(result['recommendation_not_fill'])
            self.assertEqual(result['snapshot_identity'],snapshot['identity'])
            self.assertEqual(path.read_bytes(),raw)

    # Rehashed local edits cannot change original model features or the actual quote-bound midpoint.
    def test_rehashed_evidence_and_quote_drift_refuse(self):
        with TemporaryDirectory() as directory:
            root=Path(directory);snapshot,value,path=original(root);saved=json.loads(path.read_bytes())
            with patch.object(history.learned_live_holding,'read_configuration',return_value=(b'fixture',{'cost_bps':10})):
                for field in ('features','observed_price'):
                    changed=deepcopy(saved)
                    if field=='features':changed['evidence'][field]['ema_21_distance']=.99
                    else:changed['evidence'][field]=200
                    changed['receipt_sha256']=publication._digest({k:v for k,v in changed.items() if k!='receipt_sha256'})
                    path.write_text(json.dumps(changed))
                    with self.assertRaises(ValueError):history.read(root,'AAA',value['completed_at'],snapshot['snapshot_id'],NOW)

    # A different installed cost, forming candle, foreign snapshot or changed original forecast cannot be shown as matching advice.
    def test_foreign_identity_clock_cost_and_forecast_refuse(self):
        with TemporaryDirectory() as directory:
            root=Path(directory);snapshot,value,path=original(root)
            with patch.object(history.learned_live_holding,'read_configuration',return_value=(b'fixture',{'cost_bps':20})):
                with self.assertRaisesRegex(ValueError,'economics'):history.read(root,'AAA',value['completed_at'],snapshot['snapshot_id'],NOW)
            with self.assertRaisesRegex(ValueError,'completed'):history.read(root,'AAA',(NOW+timedelta(minutes=1)).isoformat(),snapshot['snapshot_id'],NOW)
            with self.assertRaises(OSError):history.read(root,'AAA',value['completed_at'],'0'*64,NOW)
            record=json.loads(path.read_bytes())
            folder=root/entries.DIRECTORY/Path(record['forecast_evidence']['path']).parent
            (folder/'000.part').write_bytes(b'foreign')
            with patch.object(history.learned_live_holding,'read_configuration',return_value=(b'fixture',{'cost_bps':10})):
                with self.assertRaises(ValueError):history.read(root,'AAA',value['completed_at'],snapshot['snapshot_id'],NOW)


# Exercise authentication and immutable returned content through the actual endpoint rather than a handler mock.
class OriginalEntryHTTPTests(unittest.IsolatedAsyncioTestCase):
    # Only the owner can retrieve original advice, and a damaged original becomes unavailable without account fallback.
    async def test_owner_foreign_anonymous_and_corrupt(self):
        from fastapi import FastAPI
        from httpx import ASGITransport,AsyncClient
        from backend.config.settings import settings
        from backend.core.auth import issue_user_token
        candidate=Path('/calc/market_simulation_candidate.py')
        if candidate.exists():
            spec=importlib.util.spec_from_file_location('original_entry_route_candidate',candidate)
            route=importlib.util.module_from_spec(spec);spec.loader.exec_module(route)
        else:
            from backend.api.v1 import market_simulation as route
        app=FastAPI();app.include_router(route.router,prefix='/api/v1')
        with TemporaryDirectory() as directory:
            root=Path(directory);snapshot,value,path=original(root);before=path.read_bytes()
            with patch.object(settings,'AUTH_REQUIRED',True),patch.object(settings,'MARKET_DESK_USER','desk_user'),patch.object(settings,'MARKET_DATA_ROOT',str(root)),patch.object(history.learned_live_holding,'read_configuration',return_value=(b'fixture',{'cost_bps':10})),patch.object(entries,'acquire',side_effect=AssertionError('must not infer')):
                async with AsyncClient(transport=ASGITransport(app=app),base_url='http://test') as client:
                    url='/api/v1/market/desk_user/desk/strategy-simulation/AAA/recommendation'
                    params={'completed_at':value['completed_at'],'snapshot_id':snapshot['snapshot_id']}
                    owner={'Authorization':'Bearer '+issue_user_token('desk_user',scopes=['memory:read'])}
                    response=await client.get(url,params=params,headers=owner)
                    self.assertEqual(response.status_code,200)
                    self.assertEqual(response.json()['original'],json.loads(before))
                    self.assertEqual(response.headers['cache-control'],'private, no-store')
                    self.assertEqual(path.read_bytes(),before)
                    foreign={'Authorization':'Bearer '+issue_user_token('other_user',scopes=['memory:read'])}
                    self.assertEqual((await client.get(url,params=params,headers=foreign)).status_code,403)
                    self.assertEqual((await client.get(url,params=params)).status_code,401)
                    path.write_text('damaged original')
                    self.assertEqual((await client.get(url,params=params,headers=owner)).status_code,503)


# Run only this newly added original-entry read acceptance when invoked in the bounded container.
if __name__=='__main__':
    unittest.main()
