"""Native IEX packet, both-side standing advice and original history acceptance."""

from copy import deepcopy
from datetime import timedelta
from hashlib import sha256
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

import numpy as np

from backend.market import forward_market_evidence as market, forward_probability_timing as inference
from backend.market import probabilistic_execution as probability
from backend.market import strategy_entries as entries, strategy_entry_history as history
from backend.market import strategy_publication as publication, strategy_reference_entries as reference
from backend.market import strategy_reference_transition as transition
from backend.tests.test_strategy_entries import NOW
from backend.tests.test_strategy_reference_transition import snapshot_for, book_for, distribution


# Build actual native market evidence from explicit synthetic provider JSON, without making network requests.
def packet_for(now=NOW):
    opening = now.replace(hour=9, minute=30, second=0, microsecond=0)
    count = int((now-opening)//timedelta(minutes=15))
    names = ('AAA', 'QQQ', 'SPY')
    bars = [{'t': (opening+timedelta(minutes=15*i)).isoformat(), 'o': 100., 'h': 101., 'l': 99., 'c': 100., 'v': 1000.}
            for i in range(count+1)]
    prior = {**bars[0], 't': (opening-timedelta(days=1)).replace(hour=15,minute=45).isoformat()}
    quotes = {name: {'bp': 99.99, 'ap': 100.01, 'bs': 10, 'as': 10, 't': now.isoformat()} for name in names}
    # Supply only the native bounded bars and quotes endpoints used by the collector.
    def transport(url, headers):
        query = parse_qs(urlsplit(url).query)
        if '/quotes/' in url:
            return 200, json.dumps({'quotes': quotes}).encode()
        assert query['feed'] == ['iex']
        selected = [prior, *bars] if query['adjustment'] == ['split'] else bars
        return 200, json.dumps({'bars': {name: selected for name in names}, 'next_page_token': None}).encode()
    packet = market.capture(names, transport=transport, headers={}, clock=lambda: now)
    page = market.capture_quotes(names, transport=transport, headers={}, clock=lambda: now)
    return packet, quotes, page


# Bind a synthetic original snapshot and native forecast to the same actual packet contract and typed reference.
def fixture(root, *, units=.003, cash=.7, target=.17, grade='A', mean=.02, now=NOW, close_mark=100.):
    snapshot = snapshot_for(root, {'AAA': target}, {'AAA': grade})
    config = {'policy': entries.learned_live_timing.POLICY, 'model_receipt_sha256': '1'*64,
              'residual_receipt_sha256': '2'*64, 'cost_bps': 10,
              'model_directory': 'explicit-synthetic-head', 'residual_directory': 'explicit-synthetic-residual'}
    raw = json.dumps(config, sort_keys=True).encode()
    snapshot['identity']['timing_config_sha256'] = sha256(raw).hexdigest()
    snapshot['identity']['config_sha256'] = sha256(b'synthetic').hexdigest()
    snapshot['calculation_receipt'] = {'explicit_synthetic_reference_entry_fixture': True}
    snapshot['snapshot_id'] = publication._digest(snapshot['identity'])
    snapshot['receipt_sha256'] = publication._digest({k:v for k,v in snapshot.items() if k!='receipt_sha256'})
    reference_book = book_for(snapshot, {'AAA': units}, cash, {'AAA': close_mark})
    evidence = {'explicit_synthetic_reference': True}
    # Use the preparation evidence's exact hash rather than pretending it is an actual historical-book receipt.
    reference_book = transition.ReferenceBook(reference_book.strategy_identity, reference_book.through,
        reference_book.cost_bps, reference_book.positions, reference_book.cash, publication._digest(evidence))
    plan = transition.prepare(snapshot, reference_book, now)
    packet, quotes, page = packet_for(now)
    values = {'AAA': distribution(mean) if mean is not None else None, 'QQQ': None, 'SPY': None}
    completed = market._window(now)[2]
    receipt = {'contract': inference.CONTRACT, 'sources': inference._inference_sources(),
        'model_receipt': config['model_receipt_sha256'], 'residual_receipt': config['residual_receipt_sha256'],
        'symbols': list(values), 'distributions': inference._forecast_identity(values),
        'market_source_evidence': packet.receipt, 'observation': {'completed_at': completed.isoformat()},
        'raw_session_openings': {name: 100. for name in values}}
    forecast = inference.ObservedForecast(values, receipt, inference._digest(receipt))
    context = {'snapshot_id': snapshot['snapshot_id'], 'publication_receipt_sha256': snapshot['receipt_sha256'],
               'close_receipt_sha256': snapshot['identity']['close_receipt_sha256']}
    cache = {'reference_plan': plan, 'reference_evidence': evidence, 'packet': packet, 'forecast': forecast,
        'snapshot_id': snapshot['snapshot_id'], 'completed': completed, 'available': now, 'sources': entries.sources(),
        'config_bytes': raw, 'config': config, 'context': context}
    return snapshot, cache, quotes, page


# Add the actual original quote page before testing durable first-intent and HTTP reader behavior.
def publish(root, snapshot, cache, quotes, page, now):
    publication.publish(root, snapshot, now)
    cache['stored_forecast'] = entries.store_forecast(root, cache['forecast'])
    value = entries.project(snapshot, cache, quotes, now)
    value['quote_receipt'] = {key: page[key] for key in ('url','requested_at','received_at','status','sha256')}
    value['quote_receipt']['body_base64'] = __import__('base64').b64encode(page['body']).decode()
    value['receipt_sha256'] = publication._digest({k:v for k,v in value.items() if k!='receipt_sha256'})
    entries.publish(root, value)
    return value


# Exercise real parsers and native numerical choices while keeping provider data explicitly synthetic.
class ReferenceEntryTests(unittest.TestCase):
    # The existing normal display collector publishes both-side reference advice and completes its original-history index.
    def test_normal_collector_uses_existing_forecast_without_account_or_new_capture(self):
        from backend.services.current_opportunity_collector import CurrentOpportunityCollector
        with TemporaryDirectory() as directory:
            root = Path(directory)
            snapshot, cache, quotes, _ = fixture(root)
            publication.publish(root, snapshot, NOW)
            path = root/entries.learned_live_timing.CONFIG
            path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(cache['config_bytes'])
            collector = CurrentOpportunityCollector(root, enabled=False)
            collector._entry_cache = cache
            # Only the existing quote refresh endpoint is requested; native bars and timing are already in cache.
            def transport(url, headers):
                self.assertIn('/quotes/', url)
                return 200, json.dumps({'quotes': quotes}).encode()
            original_collect = entries.collect
            # Exercise the real normal collector with an explicitly synthetic test clock and provider body.
            def collect(root, cache):
                return original_collect(root, cache, clock=lambda: NOW, transport=transport)
            with patch.object(publication,'read',return_value=snapshot), \
                    patch.object(history.learned_live_holding,'read_configuration',return_value=(b'synthetic',{'cost_bps':10})), \
                    patch.object(entries.alpaca,'credentials',return_value={}), \
                    patch.object(entries,'acquire',side_effect=AssertionError('no repeated native capture')), \
                    patch.object(entries,'collect',side_effect=collect):
                result = collector._collect_once()
                self.assertEqual(result['status'],'collected')
                self.assertEqual(result['recorded_history'],'available')
                current = entries.read(root,snapshot,NOW)
                self.assertEqual(current['rows']['AAA']['action'],'Sell')
                self.assertEqual(len(history.recent(root,'AAA',NOW+timedelta(hours=1))['items']),1)

    # The normal numerical entry function now selects the reference adapter and evaluates a still-A Sell.
    def test_normal_project_native_sell_and_buy_match(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            snapshot, cache, quotes, _ = fixture(root)
            value = entries.project(snapshot, cache, quotes, NOW)
            row = value['rows']['AAA']
            self.assertEqual((value['version'], row['action'], row['state']), (reference.VERSION, 'Sell', 'execute'))
            expected = probability.decision(distribution(.02), 'sell', abs(.17/100-.003)*100, 10, horizon=probability.HORIZON)
            self.assertEqual(row['evidence']['waiting_log_utility'], expected.expected_log_utility)
            self.assertAlmostEqual(row['size_weight'], .13, places=14)
            self.assertEqual(row['model_position_weight'], .17)
            changed = deepcopy(cache)
            book = transition.ReferenceBook(cache['reference_plan'].reference.strategy_identity, snapshot['session'], 10,
                (('AAA', .001, 100.),), .9, publication._digest(cache['reference_evidence']))
            changed['reference_plan'] = transition.prepare(snapshot, book, NOW)
            bought_value = entries.project(snapshot, changed, quotes, NOW)
            bought = bought_value['rows']['AAA']
            self.assertEqual(bought['action'], 'Buy')
            self.assertEqual(bought['verdict'],
                'buy' if bought['state'] == 'execute' else 'nothing')
            self.assertAlmostEqual(bought['size_weight'],
                .07 if bought['state'] == 'execute' else 0, places=14)
            self.assertAlmostEqual(
                bought_value['reference_calculation']['rows']['AAA']['trade_weight'],
                .07, places=14)

    # Equivalent percentage moves use the explicit IEX-return bridge, never an unlabelled raw/adjusted equality.
    def test_price_bridge_and_no_additional_requests(self):
        with TemporaryDirectory() as directory:
            snapshot, cache, quotes, _ = fixture(Path(directory), units=.0015, close_mark=200.)
            packet_before = deepcopy(cache['packet'].receipt)
            value = entries.project(snapshot, cache, quotes, NOW)
            self.assertEqual(value['reference_calculation']['marked_prices']['AAA'], 200.)
            self.assertEqual(value['rows']['AAA']['evidence']['observed_price'], 100.)
            self.assertEqual(value['rows']['AAA']['evidence']['price_bridge'], reference.BRIDGE)
            self.assertAlmostEqual(value['rows']['AAA']['size_weight'], .13, places=14)
            self.assertFalse(value['historical_training_feed_matches'])
            self.assertEqual(cache['packet'].receipt, packet_before)

    # Stale quotes may not execute a grade exit even when the completed bar still values the model reference.
    def test_stale_quote_never_executes_grade_exit(self):
        with TemporaryDirectory() as directory:
            snapshot, cache, quotes, _ = fixture(Path(directory), target=0., grade='B')
            quotes['AAA']['t'] = (NOW-timedelta(seconds=31)).isoformat()
            row = entries.project(snapshot, cache, quotes, NOW)['rows']['AAA']
            self.assertEqual((row['action'], row['state']), ('Sell', 'unavailable'))
            self.assertEqual((row['verdict'], row['reason_code']),
                ('nothing', 'quote_stale'))
            self.assertEqual(row['size_weight'], 0)
            self.assertIsNone(row['quote_at'])

    # Original packet mutation, resealed foreign heads and a changed source window all fail before advice.
    def test_packet_head_and_clock_mutation_refuse(self):
        with TemporaryDirectory() as directory:
            snapshot, cache, quotes, _ = fixture(Path(directory))
            changed = deepcopy(cache); changed['packet'].prefixes['AAA']['prior_close'] = 50.
            with self.assertRaises(ValueError): entries.project(snapshot, changed, quotes, NOW)
            changed = deepcopy(cache)
            receipt = deepcopy(changed['forecast'].receipt); receipt['model_receipt'] = '9'*64
            changed['forecast'] = inference.ObservedForecast(changed['forecast'].distributions, receipt, inference._digest(receipt))
            with self.assertRaises(ValueError): entries.project(snapshot, changed, quotes, NOW)
            with self.assertRaises(ValueError): entries.project(snapshot, cache, quotes, NOW+timedelta(minutes=15))

    # Only the actual final native candle may use the native terminal deadline; no caller terminal flag exists.
    def test_terminal_permission_comes_from_native_window(self):
        with TemporaryDirectory() as directory:
            snapshot, cache, quotes, _ = fixture(Path(directory), mean=None)
            self.assertEqual(entries.project(snapshot, cache, quotes, NOW)['rows']['AAA']['state'], 'unavailable')
        final = NOW.replace(hour=15, minute=45)
        with TemporaryDirectory() as directory:
            snapshot, cache, quotes, _ = fixture(Path(directory), mean=None, now=final)
            row = entries.project(snapshot, cache, quotes, final)['rows']['AAA']
            self.assertEqual(row['state'], 'execute')
            self.assertEqual(row['evidence']['timing_reason'], 'shared_terminal_deadline')

    # Quote refreshes and later candles preserve one original standing Sell record without advancing reference holdings.
    def test_first_standing_sell_persists_across_candles_and_indexes_once(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            snapshot, cache, quotes, page = fixture(root)
            value = publish(root, snapshot, cache, quotes, page, NOW)
            first = value['rows']['AAA']['original_intent']
            record = root/entries.DIRECTORY/'recommendations'/'2026-01-07'/(first['id']+'.json')
            original = record.read_bytes()
            config = {'cost_bps':10}
            with patch.object(history.learned_live_holding, 'read_configuration', return_value=(b'synthetic', config)):
                self.assertEqual(history.remember_latest(root, NOW), 1)
                later = NOW+timedelta(minutes=15)
                packet, quotes2, page2 = packet_for(later)
                receipt = deepcopy(cache['forecast'].receipt)
                receipt['market_source_evidence'] = packet.receipt
                receipt['observation']['completed_at'] = market._window(later)[2].isoformat()
                cache2 = {**cache, 'packet':packet, 'completed':market._window(later)[2], 'available':later,
                    'forecast': inference.ObservedForecast(cache['forecast'].distributions, receipt, inference._digest(receipt))}
                cache2.pop('stored_forecast', None)
                again = publish(root, snapshot, cache2, quotes2, page2, later)
                self.assertEqual(again['rows']['AAA']['original_intent'], first)
                self.assertEqual(record.read_bytes(), original)
                self.assertEqual(history.remember_latest(root, later), 0)
                items = history.recent(root, 'AAA', later+timedelta(hours=1))['items']
                self.assertEqual(len(items), 1)
                self.assertEqual(items[0]['action'], 'Sell')
                restored = history.read(root, 'AAA', first['completed_at'], snapshot['snapshot_id'], later)
                self.assertEqual(restored['original']['size_weight'], value['rows']['AAA']['size_weight'])
                self.assertFalse(restored['current_instruction'])
            self.assertEqual(cache['reference_plan'].reference.positions, (('AAA', .003, 100.),))
            self.assertEqual(entries.read(root, snapshot, later)['rows']['AAA']['action'], 'Sell')

    # Rehashed amount, technical facts and quote changes cannot become current reference advice.
    def test_current_view_tampering_is_unavailable(self):
        with TemporaryDirectory() as directory:
            root=Path(directory);snapshot,cache,quotes,page=fixture(root)
            value=publish(root,snapshot,cache,quotes,page,NOW)
            path=root/entries.DIRECTORY/'latest.json'
            for kind in ('size','position','features','quote'):
                changed=deepcopy(value)
                if kind=='size':changed['rows']['AAA']['size_weight']=.2
                elif kind=='position':changed['rows']['AAA']['model_position_weight']=0
                elif kind=='features':changed['rows']['AAA']['evidence']['features']['ema_21_distance']=9
                else:changed['rows']['AAA']['evidence']['observed_price']=200
                changed['receipt_sha256']=publication._digest({k:v for k,v in changed.items() if k!='receipt_sha256'})
                path.write_text(json.dumps(changed))
                self.assertEqual(entries.read(root,snapshot,NOW)['status'],'unavailable')


# Exercise the real authenticated API with model-reference sells and immutable original technical reasons.
class ReferenceEntryHTTPTests(unittest.IsolatedAsyncioTestCase):
    # Owner content, nonowner denial and corrupt-current refusal all run through ASGI without account fallback.
    async def test_owner_current_and_original_sell_over_http(self):
        from types import SimpleNamespace
        from fastapi import FastAPI
        from httpx import ASGITransport, AsyncClient
        from backend.api.v1 import market_allocation, market_simulation
        from backend.config.settings import settings
        from backend.core.auth import issue_user_token
        from backend.agents.trading.desk import paper
        from backend.market import alpaca_trading
        app=FastAPI();app.include_router(market_allocation.router,prefix='/api/v1');app.include_router(market_simulation.router,prefix='/api/v1')
        with TemporaryDirectory() as directory:
            root=Path(directory);snapshot,cache,quotes,page=fixture(root)
            value=publish(root,snapshot,cache,quotes,page,NOW)
            first=value['rows']['AAA']['original_intent']
            with patch.object(settings,'AUTH_REQUIRED',True),patch.object(settings,'MARKET_DESK_USER','desk_user'), \
                    patch.object(settings,'MARKET_DATA_ROOT',str(root)), \
                    patch.object(market_allocation,'datetime',SimpleNamespace(now=lambda tz:NOW)), \
                    patch.object(market_simulation,'datetime',SimpleNamespace(now=lambda tz:NOW+timedelta(hours=1))), \
                    patch.object(history.learned_live_holding,'read_configuration',return_value=(b'synthetic',{'cost_bps':10})), \
                    patch.object(paper,'load_state',side_effect=AssertionError('must not access paper')), \
                    patch.object(alpaca_trading,'client_from_env',side_effect=AssertionError('must not access broker')), \
                    patch.object(entries,'acquire',side_effect=AssertionError('GET must not acquire')):
                history.remember_latest(root,NOW)
                owner={'Authorization':'Bearer '+issue_user_token('desk_user',scopes=['memory:read'])}
                foreign={'Authorization':'Bearer '+issue_user_token('other_user',scopes=['memory:read'])}
                async with AsyncClient(transport=ASGITransport(app=app),base_url='http://test') as client:
                    url='/api/v1/market/desk_user/desk/model-allocation'
                    response=await client.get(url,headers=owner)
                    self.assertEqual(response.status_code,200)
                    self.assertEqual(response.json()['entry_assessment']['rows']['AAA']['action'],'Sell')
                    self.assertEqual(response.headers['cache-control'],'private, no-store')
                    self.assertEqual((await client.get(url,headers=foreign)).status_code,403)
                    self.assertEqual((await client.get(url)).status_code,401)
                    url2='/api/v1/market/desk_user/desk/strategy-simulation/AAA/recommendation'
                    params={'completed_at':first['completed_at'],'snapshot_id':snapshot['snapshot_id']}
                    original=await client.get(url2,params=params,headers=owner)
                    self.assertEqual(original.status_code,200)
                    self.assertEqual(original.json()['original']['action'],'Sell')
                    self.assertEqual(original.json()['original']['evidence']['features'],snapshot['rows']['AAA']['evidence']['features'])
                    (root/entries.DIRECTORY/'latest.json').write_text('damaged current view')
                    self.assertEqual((await client.get(url,headers=owner)).json()['entry_assessment']['status'],'unavailable')
                    self.assertEqual((await client.get(url2,params=params,headers=owner)).json(),original.json())


# Run the new normal-entry/reference journeys in the bounded component process.
if __name__ == '__main__':
    unittest.main()
