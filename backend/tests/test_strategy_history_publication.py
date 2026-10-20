"""Original history import, stable economics and reviewed next-open chart clocks."""
from copy import deepcopy
from datetime import datetime
from hashlib import sha256
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from backend.market import strategy_history_publication as history, strategy_publication as publication


# Create a clearly synthetic audited file fixture to exercise the actual durable reader contract.
def original(root):
    source=root/'original';source.mkdir()
    provenance={'cost_bps':10,'basis':'account_independent_unit_capital_targets','config_sha256':'a'*64,'source_record_sha256':'b'*64}
    stock={'schema':'latest-strategy-simulation/1','policy':'grade-led-learned-sizing/1','ticker':'AAA','start':'2026-09-01','through':'2026-10-19',
        'counterfactual':True,'real_orders':False,'provenance':provenance,'splits':[],
        'latest_holding':.002,'latest_target':.027,
        'decisions':[{'id':'original-in-sample','ticker':'AAA','date':'2026-07-01','at':'2026-07-01T09:45:00-04:00','action':'BUY','weight':.02,
            'evidence':{'grade':'A','inputs_as_of':'2026-06-30','model_position_size':.02,'features':{'ema_21_distance':.01}}},
            {'id':'original-buy','ticker':'AAA','date':'2026-10-16','at':'2026-10-16T09:45:00-04:00','action':'BUY','weight':.027,
            'evidence':{'grade':'A','inputs_as_of':'2026-10-15','model_position_size':.143,'features':{'ema_21_distance':-.03}}}],
        'trades':[{'id':'original-trade','ticker':'AAA','date':'2026-10-16','at':'2026-10-16T09:30:00-04:00','action':'BUY','weight':.027}],
        'targets':[{'date':'2026-07-01','weight':.02},{'date':'2026-10-16','weight':.027}],
        'grade_rows':[{'date':'2026-09-08','grade':'A','said':False},{'date':'2026-10-19','grade':'B','said':False}]}
    raw=json.dumps(stock,sort_keys=True).encode();(source/'AAA.json').write_bytes(raw)
    manifest={key:stock[key] for key in ('schema','policy','start','through','counterfactual','real_orders','provenance')}
    manifest.update(files={'AAA':{'sha256':sha256(raw).hexdigest(),'bytes':len(raw)}},curve=[{'date':'2026-10-19','equity':1.0,'cash':1.0}],counters={'decisions':2})
    encoded=json.dumps(manifest,sort_keys=True).encode();(source/'result.json').write_bytes(encoded)
    audit={'status':'VERIFIED_LOCKED_RECOMMENDATION_ACCOUNTING','original_result_sha256':sha256(encoded).hexdigest()}
    audit_raw=json.dumps(audit,sort_keys=True).encode();(root/'audit.json').write_bytes(audit_raw)
    sources=publication._sources()
    binding={'schema':'strategy-history-economics-binding/1','history_sha256':sha256(encoded).hexdigest(),'audit_sha256':sha256(audit_raw).hexdigest(),
        'source_record_sha256':provenance['source_record_sha256'],'config_sha256':provenance['config_sha256'],
        'economic_sources':{name:sources['backend/market/'+name] for name in history.ECONOMIC_NAMES},
        'economic_parameters':{'cost_bps':10},'strategy_identity':publication._strategy_identity(sources,10)}
    return source,binding,stock,manifest,audit


# Validate actual imported bytes and source-bound historical projections rather than callbacks alone.
class HistoryPublicationTests(unittest.TestCase):
    # Current quote expiry does not hide correctly bound historical advice or overwrite its original evidence.
    def test_import_and_read_preserve_original_advice(self):
        with TemporaryDirectory() as directory:
            root=Path(directory);source,binding,stock,_,_=original(root)
            history.import_original(root,source,binding,manifest_sha256=binding['history_sha256'],audit_path=root/'audit.json',audit_sha256=binding['audit_sha256'])
            before=(source/'AAA.json').read_bytes()
            with patch.object(history.learned_live_holding,'read_configuration',return_value=(b'current reviewed config',{'cost_bps':10})):
                value=history.read(root,'AAA',datetime.fromisoformat('2026-10-21T19:00:00-04:00'))
            self.assertEqual([{k:v for k,v in row.items() if k!='sample'} for row in value['decisions']],stock['decisions'])
            self.assertEqual([row['sample'] for row in value['decisions']],['in_sample','out_of_sample'])
            self.assertEqual(value['trades'][0]['sample'],'out_of_sample')
            self.assertEqual([row['sample'] for row in value['targets']],['in_sample','out_of_sample'])
            self.assertEqual(value['provenance']['model_fit_through'],history.MODEL_FIT_THROUGH)
            self.assertTrue(value['provenance']['verified_against_installed_strategy'])
            self.assertEqual(value['grade_rows'][-1]['at'],'2026-10-20T09:30:00-04:00')
            self.assertEqual((source/'AAA.json').read_bytes(),before)

    # The overview names the same fit boundary and counts decisions on each side of it.
    def test_overview_reports_fit_boundary_and_decision_samples(self):
        with TemporaryDirectory() as directory:
            root=Path(directory);source,binding,_,_,_=original(root)
            history.import_original(root,source,binding,manifest_sha256=binding['history_sha256'],audit_path=root/'audit.json',audit_sha256=binding['audit_sha256'])
            with patch.object(history.learned_live_holding,'read_configuration',return_value=(b'current reviewed config',{'cost_bps':10})):
                value=history.read(root,None,datetime.fromisoformat('2026-10-21T19:00:00-04:00'))
            self.assertEqual(value['provenance']['model_fit_through'],history.MODEL_FIT_THROUGH)
            self.assertEqual((value['in_sample_decisions'],value['out_of_sample_decisions']),(1,1))
            self.assertEqual([row['sample'] for row in value['latest_decisions']],['in_sample','out_of_sample'])
            self.assertEqual(value['stock_overview']['AAA']['last_trade']['sample'],'out_of_sample')

    # A changed fee model or missing original economic sources cannot silently relabel another strategy's history.
    def test_foreign_cost_or_source_refuses(self):
        with TemporaryDirectory() as directory:
            _,binding,_,manifest,audit=original(Path(directory))
            with self.assertRaisesRegex(ValueError,'economics differ'):
                history.validate_binding(binding,manifest,audit,current_sources=publication._sources(),cost_bps=20)
            changed=deepcopy(binding);changed['economic_sources']={}
            with self.assertRaisesRegex(ValueError,'economics differ'):
                history.validate_binding(changed,manifest,audit,current_sources=publication._sources(),cost_bps=10)

    # An altered original stock cannot be selected by an otherwise valid manifest and accounting proof.
    def test_corrupt_original_stock_refuses(self):
        with TemporaryDirectory() as directory:
            root=Path(directory);source,binding,_,_,_=original(root)
            (source/'AAA.json').write_bytes(b'changed original')
            with self.assertRaisesRegex(ValueError,'stock history bytes differ'):
                history.import_original(root,source,binding,manifest_sha256=binding['history_sha256'],audit_path=root/'audit.json',audit_sha256=binding['audit_sha256'])
            self.assertFalse((root/history.DIRECTORY/'latest.json').exists())

    # Grade clocks use reviewed following openings, including weekends and holidays, rather than model expiry.
    def test_reviewed_grade_opening_clocks(self):
        self.assertEqual(history.next_open('2026-10-19'),'2026-10-20T09:30:00-04:00')
        self.assertEqual(history.next_open('2026-09-04'),'2026-09-08T09:30:00-04:00')
        self.assertEqual(history.next_open('2026-10-16'),'2026-10-19T09:30:00-04:00')
        with self.assertRaises(ValueError):history.next_open('2026-09-07')


# Execute only these new historical publication assertions in an isolated component run.
if __name__=='__main__':
    unittest.main()
