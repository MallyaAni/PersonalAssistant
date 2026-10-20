"""Release assets preserve original audited history without simulation or account access."""
from copy import deepcopy
from datetime import UTC,datetime
import gzip
from hashlib import sha256
import json
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from backend.market import strategy_history_installation as installation
from backend.market import strategy_history_publication as history
from backend.tests.test_strategy_history_publication import original


# Encode the existing explicit synthetic audited fixture as release assets with exact compressed and original hashes.
def assets(root):
    source,binding,stock,manifest,_=original(root)
    compressed=gzip.compress((source/'AAA.json').read_bytes(),mtime=0)
    (source/'AAA.json.gz').write_bytes(compressed)
    audit=(root/'audit.json').read_bytes();(source/'audit.json').write_bytes(audit)
    binding_raw=json.dumps(binding,sort_keys=True).encode();(source/'binding.json').write_bytes(binding_raw)
    review={'schema':'strategy-history-install-review/1','counterfactual':True,'real_orders':False,'stocks':1,'recommendations':manifest['counters']['decisions'],
        'history_sha256':binding['history_sha256'],'audit_sha256':binding['audit_sha256'],'binding_sha256':sha256(binding_raw).hexdigest(),
        'raw_stock_bytes':manifest['files']['AAA']['bytes'],'compressed_files':{'AAA':{'bytes':len(compressed),'sha256':sha256(compressed).hexdigest()}}}
    return source,review,stock


# Exercise real files, original reader and selector rollback with no simulator, model or account calls.
class HistoryInstallationTests(unittest.TestCase):
    # Installation preserves exact advice, repeated completed selection is idempotent, and rollback never deletes history bodies.
    def test_install_original_read_idempotence_and_rollback(self):
        with TemporaryDirectory() as directory:
            root=Path(directory);source,review,stock=assets(root)
            prepared=installation.prepare(source,review,10)
            with patch.object(history.learned_live_holding,'read_configuration',return_value=(b'approved',{'cost_bps':10})):
                receipt=installation.install(root,prepared,root/'archives')
                value=history.read(root,'AAA',datetime.now(UTC))
                self.assertEqual(
                    [{k:v for k,v in row.items() if k!='sample'}
                     for row in value['decisions']],
                    stock['decisions'])
                self.assertEqual(
                    [row['sample'] for row in value['decisions']],
                    ['in_sample','out_of_sample'])
                self.assertEqual(value['grade_rows'][-1]['at'],'2026-10-20T09:30:00-04:00')
                folder=root/history.DIRECTORY/review['history_sha256']
                bodies={path.name:path.read_bytes() for path in folder.iterdir()}
                with patch.object(history,'import_original',side_effect=AssertionError('no repeat import')):
                    self.assertEqual(installation.install(root,prepared,root/'archives')['status'],'ORIGINAL_HISTORY_ALREADY_INSTALLED')
                self.assertEqual(installation.rollback(root,receipt['archive'])['status'],'ORIGINAL_HISTORY_SELECTION_RESTORED')
                self.assertFalse((root/history.DIRECTORY/'latest.json').exists())
                self.assertEqual({path.name:path.read_bytes() for path in folder.iterdir()},bodies)
                with self.assertRaisesRegex(ValueError,'cannot be adopted'):
                    installation.install(root,prepared,root/'archives')

    # Altered compressed data, raw byte expectations, accounting or cost refuse before any selected output exists.
    def test_finite_original_assets_and_foreign_economics_refuse(self):
        with TemporaryDirectory() as directory:
            root=Path(directory);source,review,_=assets(root)
            with self.assertRaisesRegex(ValueError,'economics differ'):installation.prepare(source,review,20)
            altered=deepcopy(review);altered['raw_stock_bytes']+=1
            with self.assertRaisesRegex(ValueError,'extent differs'):installation.prepare(source,altered,10)
            (source/'AAA.json.gz').write_bytes(gzip.compress(b'altered original',mtime=0))
            with self.assertRaisesRegex(ValueError,'compressed history asset differs'):installation.prepare(source,review,10)
            self.assertFalse((root/history.DIRECTORY).exists())

    # A disk failure leaves immutable failed evidence unselected and cannot be retried by adopting the incomplete folder.
    def test_partial_installation_never_becomes_selected_or_adopted(self):
        with TemporaryDirectory() as directory:
            root=Path(directory);source,review,_=assets(root);prepared=installation.prepare(source,review,10)
            # Retain an explicitly injected partial output at the actual import boundary.
            def fail(root,*args,**kwargs):
                folder=Path(root)/history.DIRECTORY/review['history_sha256'];folder.mkdir()
                (folder/'failure.json').write_text('retained incomplete output')
                raise OSError('injected disk failure')
            with patch.object(history.learned_live_holding,'read_configuration',return_value=(b'approved',{'cost_bps':10})):
                with patch.object(history,'import_original',side_effect=fail),self.assertRaisesRegex(OSError,'disk failure'):
                    installation.install(root,prepared,root/'archives')
                self.assertFalse((root/history.DIRECTORY/'latest.json').exists())
                self.assertEqual(len(list((root/'archives').glob('*/receipt.json'))),1)
                with self.assertRaisesRegex(ValueError,'cannot be adopted'):installation.install(root,prepared,root/'archives')
                self.assertTrue((root/history.DIRECTORY/review['history_sha256']/'failure.json').exists())

    # Failure after selector publication restores its original absence while retaining the newly written immutable evidence.
    def test_postpublication_failure_restores_selector_without_erasing_history(self):
        with TemporaryDirectory() as directory:
            root=Path(directory);source,review,_=assets(root);prepared=installation.prepare(source,review,10)
            with patch.object(history.learned_live_holding,'read_configuration',return_value=(b'approved',{'cost_bps':10})),patch.object(history,'read',side_effect=ValueError('injected final read failure')):
                with self.assertRaisesRegex(ValueError,'final read failure'):installation.install(root,prepared,root/'archives')
            self.assertFalse((root/history.DIRECTORY/'latest.json').exists())
            self.assertEqual((root/history.DIRECTORY/review['history_sha256']/'AAA.json').read_bytes(),(source/'AAA.json').read_bytes())

    # The CLI accepts only the reviewed bytes from a real committed revision, never a rehashed working-copy edit.
    def test_committed_release_review_and_asset_identity(self):
        from backend.cli import strategy_history_install as cli
        with TemporaryDirectory() as directory:
            root=Path(directory);source,review,_=assets(root)
            code=root/'code';target=code/'backend/market/data/original';target.mkdir(parents=True)
            (code/'backend/cli').mkdir()
            for name in ('result.json','audit.json','binding.json','AAA.json.gz'):(target/name).write_bytes((source/name).read_bytes())
            review['source_directory']='backend/market/data/original'
            relative='docs/research/history-review.json';path=code/relative;path.parent.mkdir(parents=True)
            raw=json.dumps(review,sort_keys=True).encode();path.write_bytes(raw)
            for args in (['init','-q'],['config','user.name','Test'],['config','user.email','test@example.invalid'],['add','.'],['commit','-q','-m','Explicit synthetic history assets']):
                subprocess.run(['git','-C',str(code),*args],capture_output=True,check=True)
            revision=subprocess.check_output(['git','-C',str(code),'rev-parse','HEAD'],text=True).strip()
            config=root/history.learned_live_holding.CONFIG;config.parent.mkdir(parents=True,exist_ok=True);config.write_text('{"cost_bps":10}')
            with patch.object(cli,'__file__',str(code/'backend/cli/strategy_history_install.py')):
                self.assertEqual(len(cli.reviewed(root,relative,sha256(raw).hexdigest(),revision)['files']),1)
                changed={**review,'recommendations':review['recommendations']+1};altered=json.dumps(changed).encode();path.write_bytes(altered)
                with self.assertRaisesRegex(ValueError,'committed original'):cli.reviewed(root,relative,sha256(altered).hexdigest(),revision)


# Walk the deployed reader route immediately after an actual original-history installation.
class HistoryInstallationHTTPTests(unittest.IsolatedAsyncioTestCase):
    # Only the owner sees original actions and evidence; no funded record, simulator or model is consulted.
    async def test_installed_original_history_over_owner_http(self):
        from fastapi import FastAPI
        from httpx import ASGITransport,AsyncClient
        from backend.api.v1 import market_simulation as route
        from backend.config.settings import settings
        from backend.core.auth import issue_user_token
        app=FastAPI();app.include_router(route.router,prefix='/api/v1')
        with TemporaryDirectory() as directory:
            root=Path(directory);source,review,stock=assets(root);prepared=installation.prepare(source,review,10)
            with patch.object(history.learned_live_holding,'read_configuration',return_value=(b'approved',{'cost_bps':10})),patch.object(settings,'AUTH_REQUIRED',True),patch.object(settings,'MARKET_DESK_USER','desk_user'),patch.object(settings,'MARKET_DATA_ROOT',str(root)),patch.object(route.strategy_research,'read',side_effect=AssertionError('must not use legacy history')):
                installation.install(root,prepared,root/'archives')
                async with AsyncClient(transport=ASGITransport(app=app),base_url='http://test') as client:
                    url='/api/v1/market/desk_user/desk/strategy-simulation/AAA'
                    owner={'Authorization':'Bearer '+issue_user_token('desk_user',scopes=['memory:read'])}
                    response=await client.get(url,headers=owner)
                    self.assertEqual(response.status_code,200,response.text)
                    self.assertEqual(response.headers['cache-control'],'private, no-store')
                    self.assertEqual(
                        [{k:v for k,v in row.items() if k!='sample'}
                         for row in response.json()['decisions']],
                        stock['decisions'])
                    self.assertTrue(response.json()['provenance']['verified_against_installed_strategy'])
                    self.assertEqual((await client.get(url)).status_code,401)
                    foreign={'Authorization':'Bearer '+issue_user_token('other_user',scopes=['memory:read'])}
                    self.assertEqual((await client.get(url,headers=foreign)).status_code,403)


if __name__=='__main__':
    unittest.main()
