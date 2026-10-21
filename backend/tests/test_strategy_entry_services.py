"""Independent quote-universe selection and owner-authorized historical projections."""
import importlib.util
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from backend.market import strategy_publication as publication, strategy_history_publication as history
from backend.services.session_price_collector import SessionPriceCollector
from backend.tests.test_strategy_history_publication import original


# Validate data that the existing quote service selected and persisted through its normal callback.
class IndependentQuoteUniverseTests(unittest.TestCase):
    # A paper-related record cannot omit names from an installed independent model's quote collection.
    def test_quote_universe_comes_from_independent_publication(self):
        with TemporaryDirectory() as directory:
            root=Path(directory);(root/publication.DIRECTORY).mkdir(parents=True)
            # Save the actual selected scope so the test reads the resulting state, rather than only a mock call.
            def collect(root,symbols,interval_seconds):
                (root/'quote-scope.json').write_text(json.dumps({'symbols':symbols,'interval':interval_seconds}))
                return {'status':'collected'}
            service=SessionPriceCollector(root,enabled=False,collect=collect)
            with patch.object(publication,'read',return_value={'rows':{'NEW':{},'OTHER':{}}}),patch('backend.services.session_price_collector.deskrecord.latest_pair',side_effect=AssertionError('must not read funded record')):
                self.assertEqual(service._collect_once()['status'],'collected')
            self.assertEqual(json.loads((root/'quote-scope.json').read_text())['symbols'],['NEW','OTHER'])

    # A damaged independent namespace does not downgrade to stale funded names.
    def test_invalid_independent_publication_cannot_fall_back(self):
        with TemporaryDirectory() as directory:
            root=Path(directory);(root/publication.DIRECTORY).mkdir(parents=True)
            service=SessionPriceCollector(root,enabled=False)
            with patch.object(publication,'read',side_effect=ValueError('invalid snapshot')),patch('backend.services.session_price_collector.deskrecord.latest_pair',side_effect=AssertionError('must not fall back')):
                self.assertEqual(service._collect_once()['status'],'unavailable')


# Exercise the actual history API, preserving authentication and unavailable responses on corrupt files.
class IndependentHistoryHTTPTests(unittest.IsolatedAsyncioTestCase):
    # Owner content, foreign refusal and damaged original history traverse the real endpoint.
    async def test_original_owner_content_and_corrupt_refusal(self):
        from fastapi import FastAPI
        from httpx import ASGITransport,AsyncClient
        from backend.config.settings import settings
        from backend.core.auth import issue_user_token
        candidate=Path('/calc/market_simulation_candidate.py')
        if candidate.exists():
            spec=importlib.util.spec_from_file_location('history_route_candidate',candidate)
            route=importlib.util.module_from_spec(spec);spec.loader.exec_module(route)
        else:
            from backend.api.v1 import market_simulation as route
        app=FastAPI();app.include_router(route.router,prefix='/api/v1')
        with TemporaryDirectory() as directory:
            root=Path(directory);source,binding,stock,_,_=original(root)
            history.import_original(root,source,binding,manifest_sha256=binding['history_sha256'],audit_path=root/'audit.json',audit_sha256=binding['audit_sha256'])
            with patch.object(settings,'AUTH_REQUIRED',True),patch.object(settings,'MARKET_DESK_USER','desk_user'),patch.object(settings,'MARKET_DATA_ROOT',str(root)),patch.object(history.learned_live_holding,'read_configuration',return_value=(b'fixture',{'cost_bps':10})),patch.object(route.strategy_research,'read',side_effect=AssertionError('must not load old account-derived history')):
                async with AsyncClient(transport=ASGITransport(app=app),base_url='http://test') as client:
                    url='/api/v1/market/desk_user/desk/strategy-simulation/AAA'
                    owner={'Authorization':'Bearer '+issue_user_token('desk_user',scopes=['memory:read'])}
                    other={'Authorization':'Bearer '+issue_user_token('other_user',scopes=['memory:read'])}
                    response=await client.get(url,headers=owner)
                    self.assertEqual(response.status_code,200)
                    # The route stamps each row's sample against the frozen fit date; the sealed bytes carry no stamp.
                    self.assertEqual([{k:v for k,v in row.items() if k!='sample'} for row in response.json()['decisions']],stock['decisions'])
                    self.assertEqual(response.json()['grade_rows'][-1]['at'],'2026-10-20T09:30:00-04:00')
                    self.assertTrue(response.json()['provenance']['verified_against_installed_strategy'])
                    self.assertEqual(response.headers['cache-control'],'private, no-store')
                    self.assertEqual((await client.get(url,headers=other)).status_code,403)
                    self.assertEqual((await client.get(url)).status_code,401)
                    selected=root/history.DIRECTORY/binding['history_sha256']/'AAA.json';selected.write_text('damaged')
                    self.assertEqual((await client.get(url,headers=owner)).status_code,503)


# Run only the new service and history-route assertions when invoked by the bounded harness.
if __name__=='__main__':
    unittest.main()
