"""Original recorded recommendations stay discoverable after their current quote expires."""
import base64
from copy import deepcopy
from datetime import timedelta
from hashlib import sha256
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from backend.market import strategy_entries as entries, strategy_entry_history as history, strategy_publication as publication
from backend.services.current_opportunity_collector import CurrentOpportunityCollector
from backend.tests.test_strategy_entry_history import original
from backend.tests.test_strategy_entries import NOW,timing_cache,fixture


# Publish a distinct synthetic reviewed-configuration identity without changing the original model economics or first record.
def second_view(root, snapshot):
    changed=deepcopy(snapshot)
    changed['identity']['config_sha256']='c'*64
    changed['snapshot_id']=publication._digest(changed['identity'])
    changed['receipt_sha256']=publication._digest({key:value for key,value in changed.items() if key!='receipt_sha256'})
    at=NOW+timedelta(seconds=5)
    publication.publish(root,changed,at)
    cache,quotes,_=timing_cache(changed)
    cache['stored_forecast']=entries.store_forecast(root,cache['forecast'])
    quotes['AAA']['t']=at.isoformat()
    # Feed explicit synthetic quote JSON through the original request and receipt parser.
    def transport(url,headers):
        return 200,json.dumps({'quotes':quotes}).encode()
    page=entries.market.capture_quotes(cache['forecast'].receipt['symbols'],transport=transport,headers={},clock=lambda:at)
    value=entries.project(changed,cache,quotes,at)
    value['quote_receipt']={key:page[key] for key in ('url','requested_at','received_at','status','sha256')}
    value['quote_receipt']['body_base64']=base64.b64encode(page['body']).decode()
    value['receipt_sha256']=publication._digest({key:item for key,item in value.items() if key!='receipt_sha256'})
    entries.publish(root,value)
    return changed,value


# Check durable discovery, interruption and source refusal against real temporary files and unchanged original decisions.
class RecordedIndexTests(unittest.TestCase):
    # An independent snapshot advertises the new history route without loading a funded record or a broker.
    def test_independent_snapshot_advertises_recorded_history_capability(self):
        from backend.api.v1 import market_allocation as allocation
        with TemporaryDirectory() as directory:
            root=Path(directory);snapshot,_,_=fixture(root)
            snapshot['identity']['config_sha256']=sha256(b'fixture').hexdigest()
            snapshot['snapshot_id']=publication._digest(snapshot['identity'])
            snapshot['receipt_sha256']=publication._digest({key:value for key,value in snapshot.items() if key!='receipt_sha256'})
            publication.publish(root,snapshot,NOW)
            with patch.object(history.learned_live_holding,'read_configuration',return_value=(b'fixture',{'cost_bps':10})),patch.object(allocation.deskrecord,'latest_pair',side_effect=AssertionError('must not read funded record')):
                value=allocation.allocation(root,NOW)
            self.assertEqual(value['recorded_history_version'],history.PAGE_SCHEMA)
            self.assertEqual(value['snapshot_id'],snapshot['snapshot_id'])
            self.assertEqual(value['rows'],snapshot['rows'])

    # Repeated metadata completion is idempotent, and damaged current pointers do not replace a saved original.
    def test_index_reopen_preserves_original_without_acquisition(self):
        with TemporaryDirectory() as directory:
            root=Path(directory);snapshot,value,path=original(root);before=path.read_bytes()
            with patch.object(history.learned_live_holding,'read_configuration',return_value=(b'fixture',{'cost_bps':10})),patch.object(entries,'acquire',side_effect=AssertionError('must not acquire')):
                self.assertEqual(history.remember_latest(root,NOW),1)
                indexed=list((root/entries.DIRECTORY/history.INDEX_DIRECTORY/snapshot['strategy_identity']/'AAA').rglob('*.json'))[0]
                saved=indexed.read_bytes()
                self.assertEqual(history.remember_latest(root,NOW+timedelta(days=10)),0)
                self.assertEqual(indexed.read_bytes(),saved)
                (root/entries.DIRECTORY/'latest.json').write_text('damaged latest')
                page=history.recent(root,'AAA',NOW+timedelta(days=10))
                self.assertEqual(page['items'][0]['at'],value['generated_at'])
                self.assertEqual(page['items'][0]['original_bytes_sha256'],sha256(before).hexdigest())
                self.assertEqual(page['indexed_through'],value['generated_at'])
                self.assertEqual(history.recent(root,'UNHELD',NOW+timedelta(days=10))['items'],[])
                self.assertEqual(path.read_bytes(),before)

    # A loose record without a published view is not converted into a discoverable historical recommendation.
    def test_unpublished_loose_record_is_not_adopted(self):
        with TemporaryDirectory() as directory:
            root=Path(directory);_,_,path=original(root);before=path.read_bytes()
            (root/entries.DIRECTORY/'latest.json').unlink()
            self.assertEqual(history.remember_latest(root,NOW),0)
            self.assertFalse((root/entries.DIRECTORY/history.INDEX_DIRECTORY).exists())
            page=history.recent(root,'AAA',NOW+timedelta(days=10))
            self.assertEqual(page['items'],[]);self.assertIsNone(page['indexed_through'])
            self.assertEqual(path.read_bytes(),before)

    # Interrupted coverage cannot expose partial index work or allow a new collection before metadata completion.
    def test_missing_coverage_recovers_only_original_metadata(self):
        with TemporaryDirectory() as directory:
            root=Path(directory);snapshot,_,path=original(root);before=path.read_bytes()
            collector=CurrentOpportunityCollector(root,enabled=False)
            with patch.object(history.learned_live_holding,'read_configuration',return_value=(b'fixture',{'cost_bps':10})),patch.object(entries,'collect') as collect:
                with patch.object(history,'_publish_checkpoint',side_effect=OSError('explicit injected index failure')):
                    result=collector._collect_once()
                self.assertEqual(result['status'],'unavailable');collect.assert_not_called()
                indexed=list((root/entries.DIRECTORY/history.INDEX_DIRECTORY/snapshot['strategy_identity']/'AAA').rglob('*.json'))[0]
                saved=indexed.read_bytes()
                with self.assertRaisesRegex(ValueError,'incomplete'):
                    history.recent(root,'AAA',NOW+timedelta(days=10))
                self.assertEqual(history.remember_latest(root,NOW+timedelta(days=10)),0)
                self.assertEqual(indexed.read_bytes(),saved)
                self.assertEqual(len(history.recent(root,'AAA',NOW+timedelta(days=10))['items']),1)
                self.assertEqual(path.read_bytes(),before)

    # Rehashed discovery metadata and changed original bytes cannot be accepted through a valid current pointer.
    def test_tampered_index_and_original_refuse_without_fallback(self):
        with TemporaryDirectory() as directory:
            root=Path(directory);snapshot,value,path=original(root);before=path.read_bytes()
            with patch.object(history.learned_live_holding,'read_configuration',return_value=(b'fixture',{'cost_bps':10})),patch.object(entries,'acquire',side_effect=AssertionError('must not infer')):
                history.remember_latest(root,NOW)
                indexed=list((root/entries.DIRECTORY/history.INDEX_DIRECTORY/snapshot['strategy_identity']/'AAA').rglob('*.json'))[0]
                saved=indexed.read_bytes();changed=json.loads(saved)
                changed['original_bytes_sha256']='0'*64
                changed['receipt_sha256']=publication._digest({key:item for key,item in changed.items() if key!='receipt_sha256'})
                indexed.write_text(json.dumps(changed))
                with self.assertRaisesRegex(ValueError,'decision bytes'):
                    history.recent(root,'AAA',NOW+timedelta(days=10))
                self.assertEqual(history.read(root,'AAA',value['completed_at'],snapshot['snapshot_id'],NOW)['original_bytes_sha256'],sha256(before).hexdigest())
                indexed.unlink()
                with self.assertRaisesRegex(ValueError,'coverage count'):
                    history.recent(root,'AAA',NOW+timedelta(days=10))
                indexed.write_bytes(saved);path.write_text('changed original')
                with self.assertRaises(ValueError):history.recent(root,'AAA',NOW+timedelta(days=10))

    # Pagination crosses original snapshot identities in clock order without duplicating, inferring or substituting latest values.
    def test_pages_use_original_clocks_and_reject_bad_cursors(self):
        with TemporaryDirectory() as directory:
            root=Path(directory);snapshot,value,path=original(root);before=path.read_bytes()
            with patch.object(history.learned_live_holding,'read_configuration',return_value=(b'fixture',{'cost_bps':10})),patch.object(entries,'acquire',side_effect=AssertionError('must not infer')):
                history.remember_latest(root,NOW)
                second,later=second_view(root,snapshot)
                history.remember_latest(root,NOW+timedelta(seconds=5))
                newest=history.recent(root,'AAA',NOW+timedelta(days=10),limit=1)
                self.assertEqual(newest['items'][0]['snapshot_id'],second['snapshot_id'])
                self.assertEqual(newest['items'][0]['at'],later['generated_at'])
                older=history.recent(root,'AAA',NOW+timedelta(days=10),limit=1,before=newest['next_cursor'])
                self.assertEqual(older['items'][0]['snapshot_id'],snapshot['snapshot_id'])
                self.assertEqual(older['items'][0]['at'],value['generated_at'])
                self.assertIsNone(older['next_cursor'])
                for cursor in ('../../','not a cursor',base64.urlsafe_b64encode(json.dumps([(NOW+timedelta(days=11)).isoformat(),'0'*64]).encode()).decode()):
                    with self.assertRaises(ValueError):history.recent(root,'AAA',NOW+timedelta(days=10),before=cursor)
                with self.assertRaises(ValueError):history.recent(root,'AAA',NOW,limit=True)
                self.assertEqual(path.read_bytes(),before)

    # A self-consistent current-view edit with foreign source bindings cannot allocate or advance recording metadata.
    def test_foreign_view_source_refuses_before_index_creation(self):
        with TemporaryDirectory() as directory:
            root=Path(directory);_,_,path=original(root);before=path.read_bytes()
            target=root/entries.DIRECTORY/'latest.json';value=json.loads(target.read_bytes())
            value['sources']['backend/market/strategy_entries.py']='0'*64
            value['receipt_sha256']=publication._digest({key:item for key,item in value.items() if key!='receipt_sha256'})
            target.write_text(json.dumps(value))
            with self.assertRaisesRegex(ValueError,'published numerical'):
                history.remember_latest(root,NOW)
            self.assertFalse((root/entries.DIRECTORY/history.INDEX_DIRECTORY).exists())
            self.assertEqual(path.read_bytes(),before)


# Walk the existing collector and actual owner API against original temporary files without market or account operations.
class RecordedIndexHTTPTests(unittest.IsolatedAsyncioTestCase):
    # An original decision remains listed after expiry and damaged latest pointers, with owner isolation and unchanged bytes.
    async def test_expired_original_is_discoverable_over_http(self):
        from fastapi import FastAPI
        from httpx import ASGITransport,AsyncClient
        from backend.api.v1 import market_simulation as route
        from backend.config.settings import settings
        from backend.core.auth import issue_user_token
        app=FastAPI();app.include_router(route.router,prefix='/api/v1')
        with TemporaryDirectory() as directory:
            root=Path(directory);snapshot,value,path=original(root);before=path.read_bytes()
            collector=CurrentOpportunityCollector(root,enabled=False)
            with patch.object(settings,'AUTH_REQUIRED',True),patch.object(settings,'MARKET_DESK_USER','desk_user'),patch.object(settings,'MARKET_DATA_ROOT',str(root)),patch.object(history.learned_live_holding,'read_configuration',return_value=(b'fixture',{'cost_bps':10})),patch.object(entries,'collect',return_value={'status':'closed'}),patch.object(entries,'acquire',side_effect=AssertionError('must not infer')):
                collector._collect_once()
                (root/entries.DIRECTORY/'latest.json').write_text('later or damaged current view')
                async with AsyncClient(transport=ASGITransport(app=app),base_url='http://test') as client:
                    url='/api/v1/market/desk_user/desk/strategy-simulation/AAA/recommendations'
                    owner={'Authorization':'Bearer '+issue_user_token('desk_user',scopes=['memory:read'])}
                    response=await client.get(url,headers=owner)
                    self.assertEqual(response.status_code,200,response.text)
                    body=response.json()
                    self.assertFalse(body['current_instruction']);self.assertFalse(body['account_inputs'])
                    self.assertEqual(response.headers['cache-control'],'private, no-store')
                    self.assertEqual(len(body['items']),1)
                    item=body['items'][0]
                    self.assertEqual(item['size_weight'],.17)
                    self.assertEqual(item['at'],value['generated_at'])
                    self.assertEqual(item['snapshot_id'],snapshot['snapshot_id'])
                    self.assertEqual(item['original_bytes_sha256'],sha256(before).hexdigest())
                    self.assertIsNone(body['next_cursor'])
                    self.assertEqual(path.read_bytes(),before)
                    foreign={'Authorization':'Bearer '+issue_user_token('other_user',scopes=['memory:read'])}
                    self.assertEqual((await client.get(url,headers=foreign)).status_code,403)
                    self.assertEqual((await client.get(url)).status_code,401)


# Run only this new metadata discovery seam in an isolated bounded process.
if __name__=='__main__':
    unittest.main()
