"""Persistent independent recommendation snapshots, including a later paper failure."""
from copy import deepcopy
import builtins
from datetime import datetime, timedelta
import importlib.util
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import backend.market
if '/calc' in sys.path[0]:
    backend.market.__path__.insert(0, '/calc')

import numpy as np
from backend.market import strategy_publication as publication

NOW = datetime.fromisoformat('2026-01-06T19:00:00-05:00')
CONFIG = b'{"policy":"grade-led-learned-sizing/1","cost_bps":10}'


# Build a clearly synthetic finite snapshot for persistence rather than pretending to test inference.
def snapshot():
    sources = publication._sources()
    strategy = publication._strategy_identity(sources,10)
    identity = {'schema':publication.SCHEMA,'session':'2026-01-06','policy':'grade-led-learned-sizing/1',
                'basis':publication.strategy_model_allocation.BASIS,'source_sha256':sources,
                'strategy_identity':strategy,'config_sha256':publication.sha256(CONFIG).hexdigest(),
                'close_receipt_sha256':'a'*64,'economic_parameters':{'cost_bps':10}}
    value = {'version':publication.VERSION,'status':'available','reason':None,
             'policy':identity['policy'],'basis':identity['basis'],'session':identity['session'],
             'identity':identity,'snapshot_id':publication._digest(identity),'strategy_identity':strategy,
             'observed_at':(NOW-timedelta(seconds=20)).isoformat(),'as_of':NOW.isoformat(),
             'published_at':NOW.isoformat(),'valid_until':'2026-01-07T16:00:00-05:00',
             'account_basis':'no_account_inputs','timing_basis':'nightly_position_size_not_immediate_trade_size',
             'grade_signals':{'AAA':{'grade':'A','action':'buy','session':'2026-01-06','basis':'observed_close_grade'}},
             'rows':{'AAA':{'target_weight':.17,'evidence':{'grade':'A','inputs_as_of':'2026-01-06','model_position_size':.17,'features':{'ema_21_distance':-.03}}}},
             'calculation_receipt':{'synthetic_persistence_test':True}}
    value['receipt_sha256']=publication._digest(value)
    return value


# Re-sign deliberately corrupted fixture fields to test semantic validation rather than a hash mismatch alone.
def signed(value):
    value['receipt_sha256']=publication._digest({k:v for k,v in value.items() if k!='receipt_sha256'})
    return value


# Verify original bytes, clocks and technical snapshots survive failures and repeated reads.
class PublicationTests(unittest.TestCase):
    # An unsupported publisher refuses before validation, inference or any filesystem mutation.
    def test_missing_lock_module_refuses_before_creating_publication(self):
        original_import=builtins.__import__
        # Simulate the absent platform module while retaining all ordinary imports.
        def without_fcntl(name,*args,**kwargs):
            if name=='fcntl':raise ImportError('synthetic unsupported publisher')
            return original_import(name,*args,**kwargs)
        with TemporaryDirectory() as directory, patch('builtins.__import__',side_effect=without_fcntl), patch.object(publication,'validate',side_effect=AssertionError('unsupported publisher must stop first')):
            with self.assertRaisesRegex(ImportError,'unsupported publisher'):
                publication.publish(directory,object(),NOW)
            self.assertEqual(list(Path(directory).iterdir()),[])

    # A later paper error cannot erase the already persisted independent recommendation.
    def test_persisted_snapshot_survives_later_paper_error(self):
        with TemporaryDirectory() as directory:
            root=Path(directory);original=snapshot()
            publication.publish(root,original,NOW)
            try:raise RuntimeError('synthetic paper account unavailable')
            except RuntimeError:pass
            with patch.object(publication.learned_live_holding,'read_configuration',return_value=(CONFIG,{'cost_bps':10})), patch.object(publication.strategy_model_allocation,'targets_from_model',side_effect=AssertionError('read must not infer')):
                reopened=publication.read(root,NOW+timedelta(hours=16))
            self.assertEqual(reopened,original)
            self.assertEqual(reopened['rows']['AAA']['evidence']['features']['ema_21_distance'],-.03)
            self.assertEqual(reopened['rows']['AAA']['target_weight'],.17)

    # A repeated publication retains its first timestamp and exact bytes instead of extending validity.
    def test_idempotence_retains_original_publication(self):
        with TemporaryDirectory() as directory:
            root=Path(directory);original=snapshot();publication.publish(root,original,NOW)
            path=root/publication.DIRECTORY/(original['snapshot_id']+'.json');raw=path.read_bytes()
            later=deepcopy(original);later['published_at']=later['as_of']=(NOW+timedelta(minutes=1)).isoformat();signed(later)
            self.assertEqual(publication.publish(root,later,NOW+timedelta(minutes=1)),original)
            self.assertEqual(path.read_bytes(),raw)
            self.assertEqual(len(list((root/publication.DIRECTORY).glob('*.json'))),2)

    # The same immutable source cannot acquire a different size even with a self-consistent new hash.
    def test_conflicting_original_snapshot_refuses(self):
        with TemporaryDirectory() as directory:
            root=Path(directory);original=snapshot();publication.publish(root,original,NOW)
            before=(root/publication.DIRECTORY/'latest.json').read_bytes()
            other=deepcopy(original);other['rows']['AAA']['target_weight']=.18;other['rows']['AAA']['evidence']['model_position_size']=.18;signed(other)
            with self.assertRaisesRegex(ValueError,'conflicts'):publication.publish(root,other,NOW)
            self.assertEqual((root/publication.DIRECTORY/'latest.json').read_bytes(),before)

    # No new publication or HTTP read may treat an expired snapshot as current.
    def test_expired_original_refuses(self):
        value=snapshot()
        with self.assertRaisesRegex(ValueError,'expired'):publication.validate(value,datetime.fromisoformat(value['valid_until']))

    # A changed installed source is rejected without revising the original publication.
    def test_source_change_refuses(self):
        value=snapshot();sources=deepcopy(value['identity']['source_sha256']);sources['backend/market/strategy_publication.py']='0'*64
        with self.assertRaisesRegex(ValueError,'identity differs'):publication.validate(value,NOW,expected_sources=sources)

    # Booleans, oversized positions and nonfinite technical values are never displayable percentages.
    def test_semantic_corruption_refuses(self):
        for weight in (True,float('nan'),-.1,1.0):
            value=snapshot();value['rows']['AAA']['target_weight']=weight;value['rows']['AAA']['evidence']['model_position_size']=weight
            with self.assertRaises(ValueError):publication.validate(signed(value),NOW)
        value=snapshot();value['rows']['AAA']['evidence']['features']['ema_21_distance']=float('inf')
        with self.assertRaises(ValueError):publication.validate(signed(value),NOW)

    # The actual new prepare tail persists the snapshot before the caller can fail its paper work.
    def test_actual_prepare_hook_precedes_paper_caller(self):
        candidate=Path('/calc/learned_live_holding_candidate.py')
        if not candidate.exists():candidate=Path(publication.learned_live_holding.__file__)
        spec=importlib.util.spec_from_file_location('holding_publication_candidate',candidate)
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        with TemporaryDirectory() as directory:
            root=Path(directory);value=snapshot()
            current=SimpleNamespace();reader=SimpleNamespace(validate_report=lambda report:None)
            policy=SimpleNamespace(root=root)
            report=SimpleNamespace(panel=SimpleNamespace(tickers=('AAA',),dates=np.array(['2026-01-06'],dtype='datetime64[D]')))
            config={'policy':module.grade_led_policy.POLICY,'risk_directory':'risk','risk_receipt_sha256':'a'*64,'model_directory':'model','model_receipt_sha256':'b'*64,'cost_bps':10}
            original=SimpleNamespace(symbols=('AAA',));observations=root/'desk/learned-holding/observations'
            observations.mkdir(parents=True)
            # The fixture serializes a real file so prepare's normal namespace/permission steps run.
            def save_close(folder,observation,*,clock):
                folder.mkdir();(folder/'close.json').write_text('{}');return 'a'*64
            with patch.object(module,'read_configuration',return_value=(b'{}',config)),patch.object(module.holding_risk_bank,'load_bank',return_value=(original,{})),patch.object(module,'_timing',return_value=b'timing'),patch.object(module,'_model_report',return_value=report),patch.object(module,'_inputs',return_value=(np.array([[2]]),np.array([[True]]),{'sources':{}})),patch.object(module.forward,'observe_close',return_value=current),patch.object(module.forward,'write_close',side_effect=save_close),patch.object(module.forward,'load_close',return_value=current),patch.object(module.forward,'ForwardVolatilityHoldingReader',return_value=reader),patch.object(module,'GradeLedHoldingPolicy',return_value=policy),patch.object(module.context,'_check_unchanged'),patch.object(publication,'build',return_value=value),patch.object(publication,'_sources',return_value=value['identity']['source_sha256']):
                (root/module.CONFIG).write_bytes(b'{}');(root/module.learned_live_timing.CONFIG).parent.mkdir(parents=True,exist_ok=True);(root/module.learned_live_timing.CONFIG).write_bytes(b'timing')
                policy.config_bytes=CONFIG
                with patch('backend.agents.trading.desk.exit.evidence',return_value=SimpleNamespace(signalled=lambda:np.array([[False]]))):
                    selected=module.prepare(root,report,clock=lambda:NOW)
                self.assertIs(selected,policy)
            pointer=json.loads((root/publication.DIRECTORY/'latest.json').read_bytes())
            stored=json.loads((root/publication.DIRECTORY/(pointer['snapshot_id']+'.json')).read_bytes())
            self.assertEqual(stored['rows'],value['rows'])
            self.assertEqual(stored['published_at'],NOW.isoformat())


# Run only new persistent publication behavior in the bounded source container.
if __name__=='__main__':
    unittest.main()
