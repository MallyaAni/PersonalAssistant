"""The independent snapshot route must enforce ownership and never fall back to a funded record."""
import importlib.util
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from backend.tests.test_strategy_publication import CONFIG, NOW, snapshot
from backend.market import strategy_publication as publication


# Retain an HTTP regression in the repository, independent of original account fixtures.
class PublicationHTTPTests(unittest.IsolatedAsyncioTestCase):
    # Owner content, foreign refusal and corrupt/missing persisted state all traverse the real route.
    async def test_owner_reads_snapshot_and_corruption_never_uses_funded_data(self):
        from fastapi import FastAPI
        from httpx import ASGITransport, AsyncClient
        from backend.config.settings import settings
        from backend.core.auth import issue_user_token
        from backend.market import alpaca_trading
        from backend.agents.trading.desk import paper
        candidate=Path('/calc/market_allocation_candidate.py')
        if candidate.exists():
            spec=importlib.util.spec_from_file_location('publication_api_regression_candidate',candidate)
            route=importlib.util.module_from_spec(spec);spec.loader.exec_module(route)
        else:
            from backend.api.v1 import market_allocation as route
        app=FastAPI();app.include_router(route.router,prefix='/api/v1')
        value=snapshot()
        # Any old funded record, broker or inference access is a failure of this route's contract.
        def forbidden(*args,**kwargs):
            raise AssertionError('Snapshot GET touched funded record, broker or inference')
        with TemporaryDirectory() as directory:
            root=Path(directory);publication.publish(root,value,NOW)
            with patch.object(settings,'AUTH_REQUIRED',True),patch.object(settings,'MARKET_DESK_USER','desk_user'),patch.object(settings,'MARKET_DATA_ROOT',str(root)),patch.object(route,'datetime',SimpleNamespace(now=lambda tz:NOW)),patch.object(publication.learned_live_holding,'read_configuration',return_value=(CONFIG,{'cost_bps':10})),patch.object(route.deskrecord,'latest_pair',side_effect=forbidden),patch.object(paper,'load_state',side_effect=forbidden),patch.object(alpaca_trading,'client_from_env',side_effect=forbidden),patch.object(publication.strategy_model_allocation,'targets_from_model',side_effect=forbidden):
                owner=issue_user_token('desk_user',scopes=['memory:read'])
                other=issue_user_token('other_user',scopes=['memory:read'])
                async with AsyncClient(transport=ASGITransport(app=app),base_url='http://test') as client:
                    url='/api/v1/market/desk_user/desk/model-allocation'
                    response=await client.get(url,headers={'Authorization':'Bearer '+owner})
                    self.assertEqual(response.status_code,200)
                    self.assertEqual({k:v for k,v in response.json().items() if k!='entry_assessment'},
                        {**value,'recorded_history_version':'strategy-recorded-entries/1'})
                    self.assertEqual(response.json()['entry_assessment']['status'],'unavailable')
                    self.assertEqual(response.headers['cache-control'],'private, no-store')
                    self.assertEqual((await client.get(url,headers={'Authorization':'Bearer '+other})).status_code,403)
                    self.assertEqual((await client.get(url)).status_code,401)
                    pointer=json.loads((root/publication.DIRECTORY/'latest.json').read_bytes())
                    stored=root/publication.DIRECTORY/(pointer['snapshot_id']+'.json')
                    changed=json.loads(stored.read_bytes());changed['rows']['AAA']['target_weight']=.18;stored.write_text(json.dumps(changed))
                    response=await client.get(url,headers={'Authorization':'Bearer '+owner})
                    self.assertEqual(response.json()['status'],'unavailable')
                    self.assertEqual(response.json()['rows'],{})
                    (root/publication.DIRECTORY/'latest.json').unlink()
                    response=await client.get(url,headers={'Authorization':'Bearer '+owner})
                    self.assertEqual(response.json()['version'],publication.VERSION)
                    self.assertEqual(response.json()['status'],'unavailable')
                    self.assertEqual(response.json()['rows'],{})


# Execute this targeted new HTTP regression without replaying the producer or older tests.
if __name__=='__main__':
    unittest.main()
