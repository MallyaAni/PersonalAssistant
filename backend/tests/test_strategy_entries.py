"""Original input reading, native numerical decisions and durable recommendation evidence."""

from copy import deepcopy
from datetime import datetime, timedelta
from hashlib import sha256
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import numpy as np

from backend.market import calendar, forward_arithmetic, forward_probability_timing as inference
from backend.market import probabilistic_execution as probability
from backend.market import strategy_entry_context as context, strategy_entries as entries, strategy_publication as publication, strategy_entry_history as history
from backend.market.daily_arithmetic_bridge import _hash
from backend.services.current_opportunity_collector import CurrentOpportunityCollector

NOW = datetime.fromisoformat('2026-01-07T09:45:01-05:00')
PUBLISHED = datetime.fromisoformat('2026-01-06T19:00:00-05:00')


# Construct explicit synthetic original input files rather than weakening a native publication guard.
def fixture(root):
    _, exchange = calendar.reviewed_sessions()
    dates = np.arange(np.datetime64('2024-10-01'), np.datetime64('2026-01-07'))
    dates = dates[np.is_busday(dates,busdaycal=exchange)]
    symbols = ('AAA','QQQ','SPY')
    prices = np.broadcast_to(100+np.arange(len(dates))[:,None]/100,(len(dates),3)).copy()
    grades = np.full(prices.shape,2.0);grades[:,1:] = -1
    eligible = grades >= 0
    arrays = {'dates':dates,'symbols':np.array(symbols),'features':np.zeros((3,13)),
        'prices':prices[-1].copy(),'forecasts':np.zeros(3),'support':np.ones(3,dtype=bool),
        'history_prices':prices,'history_grades':grades}
    prefix = {key:_hash(value) for key,value in (('dates',dates),('prices',prices),('grades',grades),('eligible',eligible))}
    native = {'policy':'forward-holding-close/1-shadow','symbols':list(symbols),'published_at':PUBLISHED.isoformat(),
        'observed_at':PUBLISHED.isoformat(),'model_publication_sha256':'a'*64,'prefix_sha256':prefix,
        'array_sha256':{key:_hash(value) for key,value in arrays.items()}}
    folder = root/'desk/learned-holding/observations'/('1'*32);folder.mkdir(parents=True)
    np.savez_compressed(folder/'close.npz',**arrays)
    receipt = {'identity':native,'identity_sha256':forward_arithmetic.base._json_hash(native),
        'arrays_sha256':sha256((folder/'close.npz').read_bytes()).hexdigest()}
    raw = json.dumps(receipt,sort_keys=True).encode();(folder/'close.json').write_bytes(raw)
    sources = publication._sources();strategy = publication._strategy_identity(sources,10)
    identity = {'schema':publication.SCHEMA,'session':'2026-01-06','policy':'grade-led-learned-sizing/1',
        'basis':'account_independent_unit_capital_targets','source_sha256':sources,'strategy_identity':strategy,
        'holding_model_receipt_sha256':'a'*64,'close_receipt_sha256':sha256(raw).hexdigest(),'prefix_sha256':prefix,'economic_parameters':{'cost_bps':10},
        'close_context':{'directory':folder.name,'receipt_sha256':sha256(raw).hexdigest(),'arrays_sha256':receipt['arrays_sha256']}}
    value = {'version':publication.VERSION,'status':'available','policy':identity['policy'],'basis':identity['basis'],
        'session':identity['session'],'identity':identity,'snapshot_id':publication._digest(identity),'strategy_identity':strategy,
        'observed_at':PUBLISHED.isoformat(),'as_of':PUBLISHED.isoformat(),'published_at':PUBLISHED.isoformat(),
        'valid_until':'2026-01-07T16:00:00-05:00','account_basis':'no_account_inputs',
        'timing_basis':'nightly_position_size_not_immediate_trade_size',
        'grade_signals':{'AAA':{'grade':'A','action':'buy','session':'2026-01-06','basis':'observed_close_grade'}},
        'rows':{'AAA':{'target_weight':.17,'evidence':{'grade':'A','inputs_as_of':'2026-01-06','model_position_size':.17,
            'features':{'ema_21_distance':-.03},'reason':'Synthetic published model size'}}}}
    value['receipt_sha256'] = publication._digest(value)
    return value,arrays,folder


# Build a small original native distribution and a compatible observed current quote.
def timing_cache(snapshot, mean=-.01):
    distribution = probability.Distribution(mean,.001,np.array([-1.,1.]),np.array([1.,1.]))
    distributions = {'AAA':distribution,'QQQ':None,'SPY':None}
    receipt = {'distributions':inference._forecast_identity(distributions),'symbols':list(distributions)}
    forecast = inference.ObservedForecast(distributions,receipt,inference._digest(receipt))
    completed = NOW-timedelta(seconds=1)
    quote = {'bid':99.99,'ask':100.01,'bid_size':5,'ask_size':5,'last':100,'next_open':100,'open':100,
        'basis':'raw_current_shares','feed':'iex','bar':(completed-timedelta(minutes=15)).isoformat(),
        'as_of':NOW.isoformat(),'received_at':NOW.isoformat(),'next_open_at':completed.isoformat(),'next_open_published_at':NOW.isoformat()}
    cache = {'completed':completed,'available':NOW,'snapshot_id':snapshot['snapshot_id'],'forecast':forecast,
        'quotes':{'AAA':quote},'config':{'cost_bps':10},'context':{'contract':'explicit_synthetic_context'},'sources':entries.sources()}
    quotes = {'AAA':{'bp':99.99,'ap':100.01,'bs':5,'as':5,'t':NOW.isoformat()}}
    return cache,quotes,distribution


# Verify account-independent context, native economic parity and first-result persistence.
class StrategyEntryTests(unittest.TestCase):
    # Historical economics identity must change when trading costs change even if all source bytes match.
    def test_economics_identity_includes_costs(self):
        sources=publication._sources()
        self.assertEqual(publication._strategy_identity(sources,10),publication._strategy_identity(sources,10.0))
        self.assertNotEqual(publication._strategy_identity(sources,10),publication._strategy_identity(sources,20))
        with TemporaryDirectory() as directory:
            snapshot,_,_=fixture(Path(directory))
            snapshot['identity']['economic_parameters']['cost_bps']=20
            snapshot['snapshot_id']=publication._digest(snapshot['identity'])
            snapshot['receipt_sha256']=publication._digest({k:v for k,v in snapshot.items() if k!='receipt_sha256'})
            with self.assertRaisesRegex(ValueError,'identity differs'):publication.validate(snapshot,NOW)

    # The display pass refreshes only quotes within a candle and indexes its unchanged first advice against a real saved snapshot.
    def test_collect_reuses_forecast_and_keeps_original_recommendation(self):
        with TemporaryDirectory() as directory:
            root=Path(directory);snapshot,_,_=fixture(root);cache,quotes,_=timing_cache(snapshot)
            cache['config_bytes']=b'{}'
            target=root/entries.learned_live_timing.CONFIG;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(b'{}')
            observed=[NOW]
            publication.publish(root,snapshot,NOW)
            collector=CurrentOpportunityCollector(root,enabled=False)
            collector._entry_cache=cache
            # Return original explicit IEX quote JSON through the actual native endpoint receipt parser.
            def transport(url,headers):
                self.assertIn('feed=iex',url)
                return 200,json.dumps({'quotes':quotes}).encode()
            original_collect=entries.collect
            # Drive the existing background service through the actual numerical collector and fixture source clock.
            def collect(root,cache):
                return original_collect(root,cache,clock=lambda:observed[0],transport=transport)
            with patch.object(publication,'read',return_value=snapshot),patch.object(history.learned_live_holding,'read_configuration',return_value=(b'fixture',{'cost_bps':10})),patch.object(entries.alpaca,'credentials',return_value={}),patch.object(entries,'acquire',side_effect=AssertionError('must reuse original forecast')),patch.object(entries,'collect',side_effect=collect):
                result=collector._collect_once()
                self.assertEqual(result['status'],'collected')
                original=list((root/entries.DIRECTORY/'recommendations'/'2026-01-07').glob('*.json'))[0].read_bytes()
                observed[0]+=timedelta(seconds=5);quotes['AAA']['t']=observed[0].isoformat()
                self.assertEqual(collector._collect_once()['status'],'collected')
                self.assertEqual(list((root/entries.DIRECTORY/'recommendations'/'2026-01-07').glob('*.json'))[0].read_bytes(),original)
            reopened=entries.read(root,snapshot,observed[0])
            self.assertEqual(reopened['rows']['AAA']['state'],'execute')
            self.assertEqual(reopened['rows']['AAA']['size_weight'],.17)
            self.assertEqual(sha256(__import__('base64').b64decode(reopened['quote_receipt']['body_base64'])).hexdigest(),reopened['quote_receipt']['sha256'])

    # Original container path prefixes may differ, but both original files must still match exactly.
    def test_context_descriptor_normalizes_original_container_prefix(self):
        with TemporaryDirectory() as directory:
            root=Path(directory);snapshot,_,folder=fixture(root)
            policy=SimpleNamespace(root=root,admission={'close_directory':'/original/container/prefix/'+folder.name,
                'close_receipt_sha256':snapshot['identity']['close_receipt_sha256']})
            current=SimpleNamespace(receipt={'arrays_sha256':snapshot['identity']['close_context']['arrays_sha256']})
            self.assertEqual(publication._close_context(policy,current),snapshot['identity']['close_context'])
            (folder/'close.json').write_bytes(b'foreign')
            with self.assertRaisesRegex(ValueError,'bytes required'):publication._close_context(policy,current)

    # Reading the original daily input after the open never reopens or predicts a holding model.
    def test_original_context_after_open_never_recomputes(self):
        with TemporaryDirectory() as directory:
            snapshot,arrays,_ = fixture(Path(directory))
            with patch.object(forward_arithmetic,'load_close',side_effect=AssertionError('must not re-open holding forecast')),patch.object(forward_arithmetic,'load_publication',side_effect=AssertionError('must not load holding head')):
                opened = context.load(directory,snapshot,NOW)
            np.testing.assert_array_equal(opened.panel.adj_close,arrays['history_prices'])
            np.testing.assert_array_equal(opened.grades,arrays['history_grades'])
            self.assertFalse(opened.eligible[:,1:].any())
            self.assertFalse(opened.panel.adj_close.flags.writeable)
            self.assertEqual(opened.receipt['trade_session'],'2026-01-07')

    # Changed archive bytes and a self-consistent but foreign published prefix both fail closed.
    def test_original_context_drift_refuses(self):
        with TemporaryDirectory() as directory:
            snapshot,_,folder = fixture(Path(directory))
            original = (folder/'close.npz').read_bytes();(folder/'close.npz').write_bytes(original+b'foreign')
            with self.assertRaisesRegex(ValueError,'archive differs'):context.load(directory,snapshot,NOW)
            (folder/'close.npz').write_bytes(original)
            other = deepcopy(snapshot);other['identity']['prefix_sha256']['eligible']='0'*64
            other['snapshot_id']=publication._digest(other['identity']);other['receipt_sha256']=publication._digest({k:v for k,v in other.items() if k!='receipt_sha256'})
            with self.assertRaisesRegex(ValueError,'identity differs'):context.load(directory,other,NOW)

    # Both execute and wait exactly match the unchanged native decision at the same original size.
    def test_native_execute_wait_and_current_price_transport_match(self):
        with TemporaryDirectory() as directory:
            snapshot,_,_ = fixture(Path(directory))
            for mean in (-.01,.01):
                cache,quotes,distribution = timing_cache(snapshot,mean)
                value = entries.project(snapshot,cache,quotes,NOW)
                actual = probability.decision(distribution,'buy',.17,10,horizon=probability.HORIZON)
                self.assertEqual(value['rows']['AAA']['state'],actual.state)
                self.assertEqual(value['rows']['AAA']['evidence']['waiting_log_utility'],actual.expected_log_utility)
                quotes['AAA'].update(bp=101.99,ap=102.01)
                moved = entries.project(snapshot,cache,quotes,NOW)
                shifted = probability.Distribution(distribution.mean+np.log(102/100),distribution.scale,distribution.residuals,distribution.weights)
                expected = probability.decision(shifted,'buy',.17,10,horizon=probability.HORIZON)
                row = moved['rows']['AAA']
                self.assertEqual(row['state'],expected.state)
                self.assertEqual(row['size_weight'],
                    .17 if expected.state=='execute' else 0)
                self.assertEqual(row['verdict'],
                    'buy' if expected.state=='execute' else 'nothing')
                self.assertEqual(distribution.mean,mean)

    # Quote expiry and candle rollover cannot keep an old execute recommendation active.
    def test_expired_quote_and_bar_refuse(self):
        with TemporaryDirectory() as directory:
            snapshot,_,_ = fixture(Path(directory));cache,quotes,_ = timing_cache(snapshot)
            quotes['AAA']['t']=(NOW-timedelta(seconds=31)).isoformat()
            self.assertEqual(entries.project(snapshot,cache,quotes,NOW)['rows']['AAA']['state'],'unavailable')
            with self.assertRaises(ValueError):entries.project(snapshot,cache,quotes,NOW+timedelta(minutes=15))

    # A later wait refresh preserves the first original recommendation and source-bound readable current state.
    def test_first_recommendation_survives_later_refresh(self):
        with TemporaryDirectory() as directory:
            root=Path(directory);snapshot,_,_=fixture(root);cache,quotes,_=timing_cache(snapshot)
            cache['stored_forecast']=entries.store_forecast(root,cache['forecast'])
            first=entries.project(snapshot,cache,quotes,NOW);entries.publish(root,first)
            paths=list((root/entries.DIRECTORY/'recommendations'/'2026-01-07').glob('*.json'))
            self.assertEqual(len(paths),1);original=paths[0].read_bytes()
            self.assertEqual(json.loads(original)['forecast_evidence'],cache['stored_forecast'])
            changed,quotes,_=timing_cache(snapshot,.01)
            changed['stored_forecast']=entries.store_forecast(root,changed['forecast'])
            entries.publish(root,entries.project(snapshot,changed,quotes,NOW))
            self.assertEqual(paths[0].read_bytes(),original)
            self.assertEqual(entries.read(root,snapshot,NOW)['rows']['AAA']['state'],'wait')
            other=deepcopy(snapshot);other['snapshot_id']='0'*64
            self.assertEqual(entries.read(root,other,NOW)['status'],'unavailable')

    # Large original receipts survive the unchanged one-MiB file limit through verified finite parts.
    def test_forecast_parts_roundtrip_and_tamper_refusal(self):
        with TemporaryDirectory() as directory:
            root=Path(directory);receipt={'original_packet':'x'*1200000}
            forecast=SimpleNamespace(receipt=receipt,receipt_sha256=inference._digest(receipt))
            reference=entries.store_forecast(root,forecast)
            expected=json.dumps(receipt,sort_keys=True,allow_nan=False).encode()
            self.assertEqual(entries.read_forecast(root,reference),expected)
            folder=root/entries.DIRECTORY/Path(reference['path']).parent
            self.assertEqual(len(list(folder.glob('*.part'))),5)
            self.assertTrue(all(path.stat().st_size<=262144 for path in folder.iterdir()))
            self.assertEqual(entries.store_forecast(root,forecast),reference)
            (folder/'001.part').write_bytes(b'changed')
            with self.assertRaisesRegex(ValueError,'size differs'):entries.read_forecast(root,reference)

    # An interrupted original part write cannot publish advice or be adopted as complete evidence.
    def test_incomplete_forecast_never_publishes_or_adopts(self):
        with TemporaryDirectory() as directory:
            root=Path(directory);snapshot,_,_=fixture(root);cache,quotes,_=timing_cache(snapshot)
            with patch.object(entries.os,'fsync',side_effect=OSError('injected durability failure')):
                with self.assertRaises(OSError):entries.store_forecast(root,cache['forecast'])
            folder=root/entries.DIRECTORY/'forecast-evidence'/cache['forecast'].receipt_sha256
            self.assertTrue((folder/'000.part').exists())
            self.assertFalse((folder/'manifest.json').exists())
            with self.assertRaises(OSError):entries.store_forecast(root,cache['forecast'])
            with self.assertRaises((TypeError,KeyError)):entries.publish(root,entries.project(snapshot,cache,quotes,NOW))
            self.assertFalse((root/entries.DIRECTORY/'latest.json').exists())
            self.assertFalse((root/entries.DIRECTORY/'recommendations').exists())

    # An overnight pass clears cached numerical data before any read, credential lookup or market request.
    def test_closed_session_never_reads_or_acquires(self):
        cache={'original':'old'}
        with patch.object(publication,'read',side_effect=AssertionError('must not read')),patch.object(entries.alpaca,'credentials',side_effect=AssertionError('must not acquire')):
            self.assertEqual(entries.collect('/unused',cache,clock=lambda:PUBLISHED)['status'],'closed')
        self.assertEqual(cache,{})


# Run only the new entry component assertions when invoked by the isolated harness.
if __name__ == '__main__':
    unittest.main()
