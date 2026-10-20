"""Hypothetical original-quote accounting and interrupted original-result recovery."""

from copy import deepcopy
from dataclasses import asdict, replace
from datetime import timedelta
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import numpy as np

from backend.market import strategy_reference_book as ledger, strategy_reference_transition as transition
from backend.market import strategy_entry_context, strategy_model_history as native, strategy_publication as publication
from backend.market import strategy_model_extension
from backend.tests.test_strategy_entries import NOW
from backend.tests.test_strategy_reference_transition import snapshot_for,book_for,distribution


# Prepare a new explicit synthetic original model day without any account, provider or fitted head.
def prepared(root, targets=None, units=None, cash=.7, grades=None):
    snapshot=snapshot_for(root,targets or {'AAA':.17},grades)
    plan=transition.prepare(snapshot,book_for(snapshot,units or {'AAA':.003},cash),NOW)
    return snapshot,ledger.initial(plan,NOW.date().isoformat())


# Form a first published intent from native-equivalent proposed units, retaining its exact original deadline.
def intent_for(book, name, *, proposed=None, until=None):
    _,value=ledger.project(book,{row[0]:100.0 for row in book.plan.rows},
        {row[0]:distribution(-.02 if row[2]>row[1] else .02) for row in book.plan.rows},evidence_sha256='a'*64)
    row=value['rows'][name]
    intent={'intent_id':publication._digest({'day_id':book.day_id(),'ticker':name}),
        'snapshot_id':book.plan.snapshot_id,'strategy_identity':book.plan.reference.strategy_identity,
        'state':'execute','action':row['action'],'proposed_units':row['proposed_units'] if proposed is None else proposed,
        'at':NOW.isoformat(),'valid_until':(until or NOW+timedelta(seconds=29)).isoformat(),'price_anchor':100.0}
    intent['receipt_sha256']=publication._digest(intent)
    return intent


# Obtain an actual native quote-page receipt from explicitly synthetic JSON and the declared test observation.
def page_for(book, at, quotes=None):
    names=tuple(sorted(set(dict(book.positions))|{'SPY','QQQ'}))
    supplied={name:{'bp':99.99,'ap':100.01,'bs':10,'as':10,'t':at.isoformat()} for name in names}
    supplied.update(quotes or {})
    # Serve only the configured native IEX quote endpoint, without making a network request.
    def transport(url, headers):
        assert url.startswith(ledger.market.QUOTE_ENDPOINT)
        return 200,json.dumps({'quotes':supplied}).encode()
    return ledger.market.capture_quotes(names,transport=transport,headers={},clock=lambda:at)


# Keep the test seed explicitly synthetic while exercising the actual immutable metadata writer.
def seed(root, book):
    return ledger.commit(root,None,book,{'schema':'explicit-synthetic-unit-reference-seed','reference_sha256':book.plan.reference.evidence_sha256})


# Exercise numerical state transitions, original evidence clocks, durable results and rollover accounting.
class ReferenceBookTests(unittest.TestCase):
    # Publishing or observing the original quote cannot imply an execution, and an unchanged second read cannot fill twice.
    def test_later_quote_only_and_once(self):
        with TemporaryDirectory() as folder:
            _,book=prepared(Path(folder));intent=intent_for(book,'AAA')
            same,evidence=ledger.observe(book,{'AAA':intent},page_for(book,NOW),{'AAA':100.0},NOW)
            self.assertEqual(same,book);self.assertIsNone(evidence)
            later=NOW+timedelta(seconds=10)
            after,evidence=ledger.observe(book,{'AAA':intent},page_for(book,later),{'AAA':100.0},later)
            self.assertLess(dict(after.positions)['AAA'],dict(book.positions)['AAA'])
            self.assertGreater(after.cash,book.cash);self.assertEqual(after.buy_budget,book.buy_budget)
            self.assertEqual(evidence['results']['AAA']['state'],'observed_hypothetical_quote_proxy')
            again,repeated=ledger.observe(after,{'AAA':intent},page_for(book,later+timedelta(seconds=2)),{'AAA':100.0},later+timedelta(seconds=2))
            self.assertEqual(again,after);self.assertIsNone(repeated)
            self.assertEqual(book.generation,0);self.assertEqual(after.generation,1)

    # An old intent is resolved without a fill after its own original quote deadline, never executed at a later price.
    def test_expired_intent_preserves_units_cash_and_fees(self):
        with TemporaryDirectory() as folder:
            _,book=prepared(Path(folder));intent=intent_for(book,'AAA');later=NOW+timedelta(seconds=40)
            after,evidence=ledger.observe(book,{'AAA':intent},page_for(book,later),{'AAA':100.0},later)
            self.assertEqual((after.positions,after.cash,after.buy_budget,after.fees),(book.positions,book.cash,book.buy_budget,book.fees))
            self.assertEqual(evidence['results']['AAA']['quantity'],0)
            self.assertEqual(evidence['results']['AAA']['state'],'original_quote_expired_without_hypothetical_execution')
            _,view=ledger.project(after,{'AAA':100.0},{'AAA':distribution(.02)},evidence_sha256='a'*64)
            self.assertEqual(view['rows']['AAA']['state'],'no_trade')

    # A provider response received after the original deadline cannot backdate a fill using an earlier quote timestamp.
    def test_late_received_quote_does_not_backdate_execution(self):
        with TemporaryDirectory() as folder:
            _,book=prepared(Path(folder));intent=intent_for(book,'AAA');later=NOW+timedelta(seconds=35)
            quote={'AAA':{'bp':99.99,'ap':100.01,'bs':10,'as':10,'t':(NOW+timedelta(seconds=25)).isoformat()}}
            after,evidence=ledger.observe(book,{'AAA':intent},page_for(book,later,quote),{'AAA':100.0},later)
            self.assertEqual((after.positions,after.cash,after.buy_budget,after.fees),(book.positions,book.cash,book.buy_budget,book.fees))
            self.assertEqual(evidence['results']['AAA']['quantity'],0.0)
            self.assertEqual(evidence['results']['AAA']['state'],'original_quote_expired_without_hypothetical_execution')

    # Changed anchors, unsupported amounts, foreign books and altered provider bodies refuse before state mutation.
    def test_foreign_or_changed_evidence_refuses(self):
        with TemporaryDirectory() as folder:
            _,book=prepared(Path(folder));intent=intent_for(book,'AAA');later=NOW+timedelta(seconds=10)
            page=page_for(book,later)
            with self.assertRaisesRegex(ValueError,'anchor changed'):
                ledger.observe(book,{'AAA':intent},page,{'AAA':101.0},later)
            foreign=deepcopy(intent);foreign['intent_id']='f'*64;foreign['receipt_sha256']=publication._digest({k:v for k,v in foreign.items() if k!='receipt_sha256'})
            with self.assertRaises(ValueError):ledger.observe(book,{'AAA':foreign},page,{'AAA':100.0},later)
            with self.assertRaisesRegex(ValueError,'pending owned-unit objective'):
                ledger.observe(book,{'AAA':intent_for(book,'AAA',proposed=1.0)},page,{'AAA':100.0},later)
            changed={**page,'body':page['body']+b' '}
            with self.assertRaises(ValueError):ledger.observe(book,{'AAA':intent},changed,{'AAA':100.0},later)
            self.assertEqual(book.positions,(('AAA',.003),))

    # An expired mandatory exit remains unfilled without reissuing it from the same daily attempt.
    def test_expired_grade_exit_is_not_reissued(self):
        with TemporaryDirectory() as folder:
            _,book=prepared(Path(folder),{'AAA':0.0},{'AAA':.003},.7,{'AAA':'B'})
            intent=intent_for(book,'AAA');later=NOW+timedelta(seconds=40)
            after,_=ledger.observe(book,{'AAA':intent},page_for(book,later),{'AAA':100.0},later)
            _,value=ledger.project(after,{'AAA':100.0},{},evidence_sha256='a'*64)
            self.assertEqual(after.positions,book.positions)
            self.assertIsNone(value['rows']['AAA']['action'])
            self.assertEqual((value['rows']['AAA']['state'],value['rows']['AAA']['trade_weight']),('no_trade',0.0))

    # Later sale proceeds remain excluded from the original cash-spending budget even when execution prices rise.
    def test_native_replay_cash_budget_and_execution_accounting_match(self):
        with TemporaryDirectory() as folder:
            snapshot,book=prepared(Path(folder),{'AAA':0.0,'BBB':.25},{'AAA':.007},.3,{'AAA':'B','BBB':'A'})
            intents={name:intent_for(book,name) for name in ('AAA','BBB')};later=NOW+timedelta(seconds=10)
            quote={'BBB':{'bp':159.99,'ap':160.01,'bs':10,'as':10,'t':later.isoformat()}}
            after,evidence=ledger.observe(book,intents,page_for(book,later,quote),{'AAA':100.0,'BBB':100.0},later)
            names=('AAA','BBB','QQQ','SPY');dates=np.array(['2026-01-06','2026-01-07'],dtype='datetime64[D]')
            marks=np.full((2,4),100.0);opens=marks.copy();opens[1,0]=99.99
            observations=np.full((2,25,4),100.0);execution=observations.copy();execution[1,0,1]=160.01
            grades=np.full((2,4),2,dtype=int);grades[0,0]=1
            allocations=np.zeros((2,4));allocations[0,1]=.25
            initial=strategy_model_extension.InitialBook('2026-01-06',names,(.007,0.,0.,0.),.3,0.0,0,'a'*64)
            # Run the actual unchanged native replay on a fresh independent book with the same explicit execution prices.
            def provider(day,clock,stock):
                return distribution(-.02)
            result=native.replay(SimpleNamespace(cost_bps=10.0,timing_policy=transition.timing.POLICY),
                SimpleNamespace(tickers=names,dates=dates,adj_close=marks,open=opens),grades,np.zeros_like(grades,dtype=bool),
                observations,execution,provider,first=1,provenance={'explicit_synthetic_accounting_comparison':True},
                generated_at=NOW,allocations=allocations,initial_book=initial)
            self.assertEqual(dict(after.positions)['AAA'],result['stocks']['AAA']['latest_holding'])
            self.assertEqual(dict(after.positions)['BBB'],result['stocks']['BBB']['latest_holding'])
            self.assertEqual(after.cash,result['curve'][-1]['cash'])
            self.assertEqual(after.fees,result['fees']);self.assertEqual(after.buy_budget,0.0)
            self.assertLess(evidence['results']['BBB']['quantity'],intents['BBB']['proposed_units'])
            self.assertGreater(after.cash,.69)

    # A completed sale changes total cash but cannot enlarge the native Buy timing weight later in that same day.
    def test_later_projection_uses_daily_budget_not_sale_cash(self):
        with TemporaryDirectory() as folder:
            _,book=prepared(Path(folder),{'AAA':0.0,'BBB':.25},{'AAA':.007},.3,{'AAA':'B','BBB':'A'})
            later=NOW+timedelta(seconds=10)
            after,_=ledger.observe(book,{'AAA':intent_for(book,'AAA')},page_for(book,later),{'AAA':100.0},later)
            _,view=ledger.project(after,{'AAA':100.0,'BBB':160.0},{'BBB':distribution(-.02)},evidence_sha256='a'*64)
            self.assertEqual(view['rows']['AAA']['state'],'no_trade')
            self.assertLess(view['rows']['BBB']['proposed_units'],.0025)
            self.assertEqual(view['buy_funding_factor'],.3/(.0025*160.0*1.001))
            expected=transition.timing.decision(distribution(-.02),'buy',view['rows']['BBB']['trade_weight'],10,horizon=transition.timing.HORIZON)
            self.assertEqual(view['rows']['BBB']['waiting_log_utility'],expected.expected_log_utility)

    # A failed state-pointer update restores only the already durable original result and never re-observes prices.
    def test_interrupted_result_recovers_original_once(self):
        with TemporaryDirectory() as folder:
            snapshot,book=prepared(Path(folder));seed(folder,book);later=NOW+timedelta(seconds=10)
            after,evidence=ledger.observe(book,{'AAA':intent_for(book,'AAA')},page_for(book,later),{'AAA':100.0},later)
            with patch.object(ledger,'_point',side_effect=OSError('explicit pointer interruption')):
                with self.assertRaises(OSError):ledger.commit(folder,book,after,evidence)
            self.assertEqual(ledger.load(folder),book)
            with patch.object(ledger,'observe',side_effect=AssertionError('no market re-observation during recovery')):
                restored=ledger.load(folder,recover=True,snapshot=snapshot)
                self.assertEqual(restored,after);self.assertEqual(ledger.load(folder,recover=True,snapshot=snapshot),after)
            self.assertEqual(len(list((Path(folder)/ledger.DIRECTORY/book.day_id()).glob('[0-9]*.json'))),2)

    # A failed result fsync leaves no final generation that could later be adopted as a completed result.
    def test_failed_fsync_leaves_no_selectable_result(self):
        with TemporaryDirectory() as folder:
            snapshot,book=prepared(Path(folder));seed(folder,book);later=NOW+timedelta(seconds=10)
            after,evidence=ledger.observe(book,{'AAA':intent_for(book,'AAA')},page_for(book,later),{'AAA':100.0},later)
            with patch.object(ledger.os,'fsync',side_effect=OSError('explicit result fsync failure')):
                with self.assertRaises(OSError):ledger.commit(folder,book,after,evidence)
            self.assertFalse((Path(folder)/ledger.DIRECTORY/book.day_id()/'1.json').exists())
            self.assertEqual(ledger.load(folder,recover=True,snapshot=snapshot),book)

    # A stale writer cannot rewind a selected book or execute a second conflicting result from the same parent.
    def test_stale_writer_and_corrupt_successor_refuse(self):
        with TemporaryDirectory() as folder:
            _,book=prepared(Path(folder));seed(folder,book);later=NOW+timedelta(seconds=10)
            after,evidence=ledger.observe(book,{'AAA':intent_for(book,'AAA')},page_for(book,later),{'AAA':100.0},later)
            ledger.commit(folder,book,after,evidence)
            with self.assertRaisesRegex(ValueError,'stale writer'):
                ledger.commit(folder,book,after,evidence)
            (Path(folder)/ledger.DIRECTORY/book.day_id()/'2.json').write_bytes(b'{')
            with self.assertRaises(ValueError):ledger.load(folder,recover=True)
            self.assertEqual(ledger.load(folder),after)

    # An interrupted first seed restores its own original state using the exact expected snapshot identity.
    def test_interrupted_seed_recovers_without_new_seed(self):
        with TemporaryDirectory() as folder:
            snapshot,book=prepared(Path(folder))
            with patch.object(ledger,'_point',side_effect=OSError('explicit seed pointer interruption')):
                with self.assertRaises(OSError):seed(folder,book)
            restored=ledger.load(folder,recover=True,snapshot=snapshot)
            self.assertEqual(restored,book)
            with self.assertRaisesRegex(ValueError,'reseeding'):
                seed(folder,book)

    # Rollover changes basis mechanically, retains actual subsequent returns and resets spending only on the next day.
    def test_original_close_rollover_preserves_wealth_and_next_day_budget(self):
        with TemporaryDirectory() as folder:
            snapshot,book=prepared(Path(folder));later=NOW+timedelta(seconds=10)
            after,execution_evidence=ledger.observe(book,{'AAA':intent_for(book,'AAA')},page_for(book,later),{'AAA':100.0},later)
            updated=deepcopy(snapshot);tomorrow=NOW+timedelta(days=1)
            updated['session']='2026-01-07';updated['identity']['session']=updated['session']
            updated['observed_at']='2026-01-07T23:49:42+00:00'
            updated['as_of']=updated['published_at']=tomorrow.isoformat()
            updated['valid_until']=publication.live_model_decision._valid_until(updated['session']).isoformat()
            for row in updated['rows'].values():row['evidence']['inputs_as_of']=updated['session']
            for row in updated['grade_signals'].values():row['session']=updated['session']
            updated['snapshot_id']=publication._digest(updated['identity'])
            updated['receipt_sha256']=publication._digest({k:v for k,v in updated.items() if k!='receipt_sha256'})
            prices=np.array([[50.0],[55.0]]);prices.flags.writeable=False
            context=strategy_entry_context.EntryContext(SimpleNamespace(tickers=('AAA',),dates=np.array(['2026-01-06','2026-01-07'],dtype='datetime64[D]'),adj_close=prices),
                np.array([[2],[2]]),np.array([[True],[True]]),tomorrow,
                {'snapshot_id':updated['snapshot_id'],'publication_receipt_sha256':updated['receipt_sha256'],
                 'prior_session':updated['session'],'trade_session':'2026-01-08'})
            rolled,evidence=ledger.rollover(after,updated,context,tomorrow)
            converted=strategy_model_extension.rebase_units(np.array([dict(after.positions)['AAA']]),np.array([100.]),np.array([50.]))
            self.assertEqual(rolled.positions,(('AAA',converted[0]),))
            self.assertEqual(rolled.cash,after.cash);self.assertEqual(rolled.fees,after.fees)
            self.assertEqual(rolled.buy_budget,after.cash);self.assertGreater(rolled.buy_budget,after.buy_budget)
            self.assertAlmostEqual(rolled.cash+rolled.positions[0][1]*55,after.cash+dict(after.positions)['AAA']*110,places=15)
            seed(folder,book);ledger.commit(folder,book,after,execution_evidence)
            with patch.object(ledger,'_point',side_effect=OSError('explicit rollover pointer interruption')):
                with self.assertRaises(OSError):ledger.commit(folder,after,rolled,evidence)
            self.assertEqual(ledger.load(folder,recover=True,snapshot=updated),rolled)
            wrong=deepcopy(updated);wrong['session']='2026-01-09'
            with self.assertRaises(ValueError):ledger.rollover(after,wrong,context,tomorrow)
