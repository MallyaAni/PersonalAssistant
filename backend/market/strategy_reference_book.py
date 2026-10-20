"""Observed hypothetical execution of a model reference, never an account fill.

A later eligible IEX bid/ask can supply an explicitly named execution proxy
inside the original recommendation's validity. Merely publishing or reading
advice cannot advance this book. Original daily cash budget excludes sale
proceeds, and original results precede their mutable discovery pointer.
"""

import base64
from dataclasses import asdict, dataclass
from datetime import datetime
from hashlib import sha256
import json
import math
import os
from pathlib import Path
from uuid import uuid4

from backend.market import calendar, execution_quotes, forward_market_evidence as market
from backend.market import strategy_publication as publication
from backend.market import strategy_reference_transition as transition
from backend.market import strategy_verdict as verdicts

VERSION = 'strategy-observed-hypothetical-book/1'
EXECUTION_BASIS = 'later_observed_IEX_bid_ask_proxy_not_actual_fill'
DIRECTORY = 'desk/strategy-reference-book'
MAX_BYTES = 262144


# Bind the derived ledger to its actual numerical and original-market readers.
def sources():
    return transition.sources() | {Path(module.__file__).name: sha256(Path(module.__file__).read_bytes()).hexdigest()
        for module in (market, execution_quotes)} | {Path(__file__).name: sha256(Path(__file__).read_bytes()).hexdigest()}


# Restore an immutable prepared objective without running prediction or reading an account.
def restore_plan(value):
    original = value['reference']
    reference = transition.ReferenceBook(**{**original,'positions':tuple(tuple(row) for row in original['positions'])})
    return transition.TransitionPlan(value['snapshot_id'],value['publication_receipt_sha256'],reference,
        tuple(tuple(row) for row in value['rows']),tuple(tuple(row) for row in value['source_sha256']))


# Own current fractional units, original daily budget and resolved attempts separately from advice.
@dataclass(frozen=True)
class DayBook:
    plan: transition.TransitionPlan
    trade_session: str
    positions: tuple[tuple[str,float], ...]
    cash: float
    buy_budget: float
    fees: float
    resolved: tuple[tuple[str,str], ...]
    generation: int
    evidence_sha256: str
    source_sha256: tuple[tuple[str,str], ...]

    # Identify a day by its fixed objective, independently of quote refreshes or later executions.
    def day_id(self):
        return publication._digest({'snapshot_id':self.plan.snapshot_id,
            'publication_receipt_sha256':self.plan.publication_receipt_sha256,'trade_session':self.trade_session})

    # Authenticate one exact state without treating its digest as proof of actual owned positions.
    def receipt_sha256(self):
        return publication._digest(asdict(self))

    # Reject debt, overspending, partial universes or an unreviewed execution implementation.
    def validate(self):
        names=tuple(row[0] for row in self.plan.rows)
        if (type(self.plan) is not transition.TransitionPlan or self.plan.source_sha256!=tuple(sorted(transition.sources().items()))
                or self.source_sha256!=tuple(sorted(sources().items()))
                or tuple(name for name,_ in self.positions)!=names or len(set(names))!=len(names)
                or any(not transition._number(units) for _,units in self.positions)
                or any(not transition._number(value) for value in (self.cash,self.buy_budget,self.fees))
                or self.buy_budget>self.cash or type(self.generation) is not int or self.generation<0
                or tuple(sorted(self.resolved))!=self.resolved or len(dict(self.resolved))!=len(self.resolved)
                or not set(dict(self.resolved))<=set(names)
                or datetime.fromisoformat(self.trade_session).date().isoformat()!=self.trade_session
                or self.trade_session<=self.plan.reference.through):
            raise ValueError('Complete non-borrowing original hypothetical book required')
        publication._sha(self.evidence_sha256)
        for _,receipt in self.resolved:
            publication._sha(receipt)
        return self


# Start a separate model day with its original available cash and fixed desired units.
def initial(plan, trade_session, *, fees=0.0):
    book=DayBook(plan,trade_session,tuple((name,units) for name,units,*_ in plan.rows),plan.reference.cash,
        plan.reference.cash,fees,(),0,plan.reference.evidence_sha256,tuple(sorted(sources().items())))
    return book.validate()


# Prepare current owned model units without changing the original day objective or treating a resolved attempt as another trade.
def current_plan(book):
    book.validate()
    units=dict(book.positions);resolved=dict(book.resolved)
    reference=transition.ReferenceBook(book.plan.reference.strategy_identity,book.plan.reference.through,
        book.plan.reference.cost_bps,tuple((name,units[name],mark) for name,_,mark in book.plan.reference.positions),
        book.cash,book.receipt_sha256())
    rows=tuple((name,units[name],units[name] if name in resolved else wanted,target,grade)
        for name,_,wanted,target,grade in book.plan.rows)
    return transition.TransitionPlan(book.plan.snapshot_id,book.plan.publication_receipt_sha256,reference,rows,book.plan.source_sha256)


# Derive native timing against current hypothetical units while retaining the original daily objective and budget.
def project(book, marks, distributions, *, evidence_sha256, terminal=False):
    current=current_plan(book);reference=current.reference;rows=current.rows;resolved=dict(book.resolved)
    value=transition.project(current,marks,distributions,evidence_sha256=evidence_sha256,
        price_basis=reference.price_basis,terminal=terminal)
    native_receipt=value['receipt_sha256']
    spend=sum((wanted-held)*marks.get(name,0.0) for name,held,wanted,_,_ in rows if wanted>held)
    spend*=1+reference.cost_bps/10000
    funded=min(1.0,book.buy_budget/spend) if spend>0 else 1.0
    for name,row in value['rows'].items():
        if name in resolved:
            row.update(action=None,state='no_trade',proposed_units=0.0,trade_weight=0.0,waiting_log_utility=None,
                reason='Original hypothetical attempt already resolved; no repeated trade')
        elif row['action']=='Buy':
            original=next(item for item in rows if item[0]==name)
            amount=(original[2]-original[1])*funded
            weight=amount*marks[name]/value['reference_equity'] if amount>0 else 0.0
            choice=(transition.timing.Decision('no_trade',reason='No original daily buy cash remaining') if amount<=0
                else transition.timing.Decision('execute',reason='shared_terminal_deadline') if terminal
                else transition.timing.decision(distributions.get(name),'buy',weight,reference.cost_bps,horizon=transition.timing.HORIZON))
            row.update(action='Buy' if amount>0 else None,proposed_units=amount,trade_weight=weight,state=choice.state,
                reason=choice.reason,waiting_log_utility=choice.expected_log_utility)
        row.update(verdicts.annotate(row,reason_key='verdict_reason',
            target_weight=row['model_position_weight'],
            held_weight=row['reference_position_weight'],
            distribution_available=distributions.get(name) is not None,
            resolved=name in resolved))
        row['size_weight']=(row['trade_weight'] if row['verdict'] in ('buy','sell')
            else 0.0)
    value.update(version=VERSION,calculation_basis='derived_daily_cash_budget_over_native_reference_projection',
        native_projection_sha256=native_receipt,buy_funding_factor=funded,original_daily_buy_budget=book.buy_budget,
        day_id=book.day_id(),book_sha256=book.receipt_sha256(),book_source_sha256=dict(book.source_sha256))
    value['receipt_sha256']=publication._digest({key:item for key,item in value.items() if key!='receipt_sha256'})
    return current,value


# Settle only original published attempts from a genuinely later eligible quote inside their original deadline.
def observe(book, intents, quote_page, anchors, observed_at):
    book.validate()
    body=quote_page['body']
    query,_,_=market._page(quote_page,market.QUOTE_ENDPOINT,observed_at)
    if (query!={'feed':'iex','symbols':','.join(sorted(set(dict(book.positions))|{'SPY','QQQ'}))}
            or not set(intents)<=set(dict(book.positions))
            or observed_at.astimezone(calendar.NEW_YORK).date().isoformat()!=book.trade_session):
        raise ValueError('Original current-day IEX execution observation required')
    quotes=json.loads(body)['quotes'];units=dict(book.positions);resolved=dict(book.resolved)
    try:
        market._window(observed_at)
        regular=True
    except ValueError:
        regular=False
    cash,budget,fees=book.cash,book.buy_budget,book.fees;results={}
    reference_marks={name:mark for name,_,mark in book.plan.reference.positions}
    order=sorted(intents,key=lambda name:(intents[name]['action']=='Buy',name))
    for name in order:
        if name in resolved:
            continue
        intent=intents[name];at=datetime.fromisoformat(intent['at']);until=datetime.fromisoformat(intent['valid_until'])
        expected=publication._digest({'day_id':book.day_id(),'ticker':name})
        if (intent['intent_id']!=expected or intent['snapshot_id']!=book.plan.snapshot_id
                or intent['strategy_identity']!=book.plan.reference.strategy_identity or intent['state']!='execute'
                or intent['action'] not in ('Buy','Sell') or not transition._number(intent['proposed_units'],positive=True)
                or intent['receipt_sha256']!=publication._digest({key:item for key,item in intent.items() if key!='receipt_sha256'})
                or at.utcoffset() is None or until.utcoffset() is None
                or not at<until or at>observed_at):
            raise ValueError('Original published hypothetical intent required')
        wanted=next(row[2] for row in book.plan.rows if row[0]==name)
        if ((intent['action']=='Buy')!=(wanted>units[name])
                or intent['proposed_units']>abs(wanted-units[name])):
            raise ValueError('Original hypothetical amount exceeds the pending owned-unit objective')
        quote=quotes.get(name);described=execution_quotes.describe(quote,'iex',True,observed_at) if isinstance(quote,dict) else {}
        stamp=datetime.fromisoformat(quote['t']) if isinstance(quote,dict) and quote.get('t') else None
        valid=(regular and observed_at<until and described.get('eligible') and described.get('spread_verified') is True and stamp is not None
            and at<stamp<until and at<datetime.fromisoformat(quote_page['requested_at']))
        if not valid and observed_at<until:
            continue
        result={'intent_sha256':intent['receipt_sha256'],'action':intent['action'],'quantity':0.0,'price':None,
            'state':'original_quote_expired_without_hypothetical_execution','execution_at':None,'fee':0.0}
        if valid:
            anchor=anchors[name]
            if not transition._number(anchor,positive=True) or anchor!=intent['price_anchor']:
                raise ValueError('Original split-attested IEX anchor changed')
            price=reference_marks[name]*(described['ask'] if intent['action']=='Buy' else described['bid'])/anchor
            buying=intent['action']=='Buy';cost=book.plan.reference.cost_bps/10000
            quantity=(min(intent['proposed_units'],max(0.0,min(cash,budget))/(price*(1+cost))) if buying
                else min(intent['proposed_units'],units[name]))
            amount=quantity*price;fee=amount*cost
            cash+=-amount-fee if buying else amount-fee
            units[name]+=quantity if buying else -quantity
            if buying:
                budget=max(0.0,budget-amount-fee)
            fees+=fee
            result.update(quantity=quantity,price=price,state='observed_hypothetical_quote_proxy' if quantity>0 else 'cash_limited',
                execution_at=stamp.isoformat(),fee=fee)
        resolved[name]=publication._digest(result);results[name]=result
    if not results:
        return book,None
    evidence={'basis':EXECUTION_BASIS,'parent_book_sha256':book.receipt_sha256(),'results':results,'execution_order':list(results),
        'quote_receipt':{key:quote_page[key] for key in ('url','requested_at','received_at','status','sha256')},
        'quote_body_base64':base64.b64encode(body).decode(),'price_anchors':{name:anchors.get(name) for name in results},
        'observed_at':observed_at.isoformat(),'actual_fill_claim':False}
    after=DayBook(book.plan,book.trade_session,tuple((name,units[name]) for name,_ in book.positions),cash,budget,fees,
        tuple(sorted(resolved.items())),book.generation+1,publication._digest(evidence),book.source_sha256).validate()
    return after,evidence


# Check cash, fees and units from the already selected original result, without another market observation or model choice.
def _result_matches(before, after, evidence):
    if (evidence['basis']!=EXECUTION_BASIS or evidence['parent_book_sha256']!=before.receipt_sha256()
            or evidence['actual_fill_claim'] is not False or evidence['execution_order']!=list(dict.fromkeys(evidence['execution_order']))
            or set(evidence['execution_order'])!=set(evidence['results']) or after.plan!=before.plan
            or after.trade_session!=before.trade_session or after.source_sha256!=before.source_sha256):
        raise ValueError('Original hypothetical result binding differs')
    units=dict(before.positions);resolved=dict(before.resolved);cash,budget,fees=before.cash,before.buy_budget,before.fees
    for name in evidence['execution_order']:
        result=evidence['results'][name];quantity=result['quantity'];price=result['price'];fee=result['fee']
        if (name not in units or name in resolved or result['action'] not in ('Buy','Sell')
                or not transition._number(quantity) or not transition._number(fee)
                or price is not None and not transition._number(price,positive=True)
                or quantity>0 and price is None):
            raise ValueError('Original hypothetical execution amount differs')
        amount=quantity*price if price is not None else 0.0
        if fee!=amount*(before.plan.reference.cost_bps/10000):
            raise ValueError('Original hypothetical fee differs')
        buying=result['action']=='Buy'
        if (not buying and quantity>units[name]) or (buying and amount+fee>min(cash,budget)):
            raise ValueError('Original hypothetical result borrows or sells unowned units')
        cash+=-amount-fee if buying else amount-fee
        units[name]+=quantity if buying else -quantity
        if buying:budget=max(0.0,budget-amount-fee)
        fees+=fee;resolved[name]=publication._digest(result)
    expected=DayBook(before.plan,before.trade_session,tuple((name,units[name]) for name,_ in before.positions),
        cash,budget,fees,tuple(sorted(resolved.items())),before.generation+1,publication._digest(evidence),before.source_sha256)
    if after!=expected:
        raise ValueError('Original hypothetical result accounting differs')


# Rebase the same owned model units with original daily input evidence before selecting the next day's objective.
def rollover(book, snapshot, context, now):
    book.validate();publication.validate(snapshot,now,expected_sources=publication._sources())
    if (snapshot['session']!=book.trade_session or snapshot['strategy_identity']!=book.plan.reference.strategy_identity
            or context.receipt['snapshot_id']!=snapshot['snapshot_id']
            or context.receipt['publication_receipt_sha256']!=snapshot['receipt_sha256']
            or context.receipt['prior_session']!=snapshot['session']):
        raise ValueError('Immediately subsequent original close required; no reseeding or skipped model day')
    panel=context.panel;dates=[str(day) for day in panel.dates];names=tuple(panel.tickers)
    old=dates.index(book.plan.reference.through);new=dates.index(snapshot['session'])
    if new!=len(dates)-1 or old>=new or set(snapshot['rows'])!=set(dict(book.positions)):
        raise ValueError('Complete original reference universe and dated close prefix required')
    units=dict(book.positions);positions=[];anchors={}
    for name,_,mark in book.plan.reference.positions:
        old_mark=float(panel.adj_close[old,names.index(name)]);new_mark=float(panel.adj_close[new,names.index(name)])
        if not transition._number(old_mark,positive=True) or not transition._number(new_mark,positive=True):
            raise ValueError('Original adjusted anchor and later close marks required')
        positions.append((name,units[name]*mark/old_mark,new_mark));anchors[name]=[mark,old_mark,new_mark]
    evidence={'schema':'strategy-reference-observed-rollover/1','parent_book_sha256':book.receipt_sha256(),
        'context':context.receipt,'anchors':anchors,'original_cash':book.cash,'fees':book.fees,
        'unfilled_old_attempts_are_not_fills':True}
    reference=transition.ReferenceBook(snapshot['strategy_identity'],snapshot['session'],book.plan.reference.cost_bps,
        tuple(positions),book.cash,publication._digest(evidence))
    plan=transition.prepare(snapshot,reference,now)
    return initial(plan,context.receipt['trade_session'],fees=book.fees),evidence


# Encode finite canonical metadata without admitting NaN, unbounded files or mutable caller references.
def _bytes(value):
    raw=json.dumps(value,sort_keys=True,allow_nan=False).encode()
    if len(raw)>MAX_BYTES:
        raise ValueError('Finite hypothetical state metadata required')
    return raw


# Restore a source-bound state from a retained original result rather than recalculating executions.
def restore(value):
    return DayBook(restore_plan(value['plan']),value['trade_session'],tuple(tuple(row) for row in value['positions']),
        value['cash'],value['buy_budget'],value['fees'],tuple(tuple(row) for row in value['resolved']),value['generation'],
        value['evidence_sha256'],tuple(tuple(row) for row in value['source_sha256'])).validate()


# Read exact finite metadata from the dedicated ledger, without following a substituted file.
def _read(path):
    from backend.market.strategy_entry_context import _read as finite_read
    return json.loads(finite_read(path,MAX_BYTES))


# Keep every state generation under its exact original model-day namespace.
def _day(folder, identity):
    day=folder/publication._sha(identity)
    if day.is_symlink() or day.resolve().parent!=folder.resolve():
        raise ValueError('Original hypothetical day namespace required')
    return day


# Publish only a discovery pointer after its original state result has been durably recorded.
def _point(folder, book):
    value={'version':VERSION,'day_id':book.day_id(),'generation':book.generation,'state_sha256':book.receipt_sha256()}
    temporary=folder/('latest-'+uuid4().hex+'.tmp')
    try:
        with temporary.open('xb') as stream:
            stream.write(_bytes(value));stream.flush();os.fsync(stream.fileno())
        temporary.replace(folder/'latest.json')
        descriptor=os.open(folder,os.O_RDONLY)
        try:os.fsync(descriptor)
        finally:os.close(descriptor)
    finally:
        temporary.unlink(missing_ok=True)


# Persist one original result before selecting it, refusing a conflicting or partially written generation.
def commit(root, before, after, evidence):
    after.validate()
    folder=Path(root)/DIRECTORY;day=_day(folder,after.day_id())
    day.mkdir(mode=0o700,parents=True,exist_ok=True)
    if (folder/'latest.json').exists():
        current=load(root)
        if before is None or current.receipt_sha256()!=before.receipt_sha256():
            raise ValueError('Original hypothetical parent changed; no stale writer or reseeding')
    elif before is not None:
        raise ValueError('Original hypothetical parent pointer missing')
    if before is None:
        if after.generation!=0:
            raise ValueError('Original zero-generation seed required')
    elif before.day_id()==after.day_id():
        if after.generation!=before.generation+1:
            raise ValueError('Next original hypothetical result generation required')
        _result_matches(before,after,evidence)
    elif (after.generation!=0 or after.plan.reference.through!=before.trade_session
            or evidence.get('schema')!='strategy-reference-observed-rollover/1'
            or evidence.get('parent_book_sha256')!=before.receipt_sha256()):
        raise ValueError('Exact subsequent model-day rollover required')
    value={'version':VERSION,'before_sha256':before.receipt_sha256() if before else None,'after':asdict(after),'evidence':evidence}
    value['receipt_sha256']=publication._digest(value);path=day/(str(after.generation)+'.json');raw=_bytes(value)
    temporary=day/('result-'+uuid4().hex+'.tmp')
    try:
        with temporary.open('xb') as stream:
            stream.write(raw);stream.flush();os.fsync(stream.fileno())
        try:os.link(temporary,path)
        except FileExistsError:
            if _bytes(_read(path))!=raw:
                raise ValueError('Original hypothetical result conflicts; never recompute or adopt another result')
    finally:
        temporary.unlink(missing_ok=True)
    descriptor=os.open(day,os.O_RDONLY)
    try:os.fsync(descriptor)
    finally:os.close(descriptor)
    if _bytes(_read(path))!=raw:
        raise ValueError('Original hypothetical result readback differs')
    _point(folder,after)
    return after


# Recover only the original next result after an interrupted pointer update, without reading new market data.
def load(root, *, recover=False, snapshot=None):
    folder=Path(root)/DIRECTORY
    expected=None
    if snapshot is not None:
        trade=datetime.fromisoformat(snapshot['valid_until']).astimezone(calendar.NEW_YORK).date().isoformat()
        expected=publication._digest({'snapshot_id':snapshot['snapshot_id'],
            'publication_receipt_sha256':snapshot['receipt_sha256'],'trade_session':trade})
    if not (folder/'latest.json').exists():
        if not recover or expected is None:
            raise FileNotFoundError('Original hypothetical pointer unavailable')
        saved=_read(_day(folder,expected)/'0.json')
        if (saved['version']!=VERSION or saved['before_sha256'] is not None
                or saved['receipt_sha256']!=publication._digest({k:v for k,v in saved.items() if k!='receipt_sha256'})):
            raise ValueError('Original interrupted seed differs')
        original=restore(saved['after'])
        if original.day_id()!=expected or original.generation!=0:
            raise ValueError('Original interrupted seed identity differs')
        original.plan.reference.validate(snapshot)
        _point(folder,original)
        return original
    pointer=_read(folder/'latest.json')
    day=_day(folder,pointer['day_id'])
    if pointer['version']!=VERSION or type(pointer['generation']) is not int or pointer['generation']<0:
        raise ValueError('Original hypothetical state namespace required')
    record=_read(day/(str(pointer['generation'])+'.json'))
    if (record['version']!=VERSION or record['receipt_sha256']!=publication._digest({k:v for k,v in record.items() if k!='receipt_sha256'})):
        raise ValueError('Original hypothetical state result differs')
    book=restore(record['after'])
    if book.day_id()!=pointer['day_id'] or book.receipt_sha256()!=pointer['state_sha256'] or book.generation!=pointer['generation']:
        raise ValueError('Original hypothetical discovery pointer differs')
    successor=day/(str(book.generation+1)+'.json')
    if recover and successor.exists():
        saved=_read(successor)
        if (saved['version']!=VERSION or saved['receipt_sha256']!=publication._digest({k:v for k,v in saved.items() if k!='receipt_sha256'})
                or saved['before_sha256']!=book.receipt_sha256()):
            raise ValueError('Interrupted original hypothetical result differs')
        original=restore(saved['after'])
        if original.day_id()!=book.day_id() or original.generation!=book.generation+1:
            raise ValueError('Interrupted hypothetical result identity differs')
        _result_matches(book,original,saved['evidence'])
        _point(folder,original)
        return original
    if recover and expected is not None and expected!=book.day_id() and (_day(folder,expected)/'0.json').exists():
        saved=_read(_day(folder,expected)/'0.json')
        if (saved['version']!=VERSION or saved['before_sha256']!=book.receipt_sha256()
                or saved['receipt_sha256']!=publication._digest({k:v for k,v in saved.items() if k!='receipt_sha256'})):
            raise ValueError('Original interrupted rollover differs')
        original=restore(saved['after'])
        if (original.day_id()!=expected or original.generation!=0
                or original.plan.reference.through!=book.trade_session):
            raise ValueError('Original interrupted rollover identity differs')
        original.plan.reference.validate(snapshot)
        _point(folder,original)
        return original
    return book
