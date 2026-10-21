"""Current IEX timing for an explicitly standing model-reference transition.

The original reference remains unchanged by advice, polling or publication.
This is not a fill simulator or viewer account. A later reference close needs
its own original progression evidence; this adapter cannot reseed an older
history endpoint. IEX relative-return marks are distinct from historical SIP
and from an assertion of raw/adjusted price equivalence.
"""

from copy import deepcopy
import base64
from dataclasses import asdict
from datetime import datetime, timedelta
from hashlib import sha256
import json
import math
import os
from pathlib import Path

from backend.market import execution_quotes, forward_market_evidence as market
from backend.market import learned_live_timing
from backend.market import forward_probability_timing as inference
from backend.market import probabilistic_execution as probability
from backend.market import strategy_publication as publication
from backend.market import strategy_reference_transition as transition
from backend.market import strategy_history_publication as history
from backend.market import strategy_reference_book as reference_book

VERSION = 'strategy-numerical-entries/2'
BASIS = 'standing_counterfactual_reference_transition_not_viewer_order'
BRIDGE = 'original_adjusted_reference_close_times_current_IEX_return_from_attested_prior_IEX_close'
PROGRESSING_VERSION = 'strategy-numerical-entries/3'
PROGRESSING_BASIS = 'observed_hypothetical_reference_not_viewer_order'
VERSIONS = (VERSION,PROGRESSING_VERSION)


# Select the independent reference only when audited model history was explicitly installed.
def configured(root):
    return (Path(root)/history.DIRECTORY).exists()


# Prepare the reviewed reference once per candle without reading a paper or personal portfolio.
def prepare(root, snapshot, now):
    source = Path(__file__).with_name('data')/'strategy_history_oct19'
    review = json.loads((Path(__file__).resolve().parents[2]/'docs/research/strategy-history-install-review-2026-10-20.json').read_bytes())
    selected = history.read(root, None, now)
    if selected['provenance']['source_record_sha256'] != json.loads((source/'binding.json').read_bytes())['source_record_sha256']:
        raise ValueError('Installed and reviewed original reference differ')
    reference, evidence = transition.from_reviewed_history(root, snapshot, source, review, now)
    return transition.prepare(snapshot, reference, now), evidence


# Reopen or roll the original model book before acquiring advice, without ever reseeding a missing or damaged state.
def prepare_book(root, snapshot, now):
    folder=Path(root)/reference_book.DIRECTORY
    if not folder.exists():
        plan,evidence=prepare(root,snapshot,now)
        trade=datetime.fromisoformat(snapshot['valid_until']).astimezone(reference_book.calendar.NEW_YORK).date().isoformat()
        book=reference_book.initial(plan,trade)
        return reference_book.commit(root,None,book,evidence)
    book=reference_book.load(root,recover=True,snapshot=snapshot)
    if book.plan.snapshot_id==snapshot['snapshot_id']:
        book.plan.reference.validate(snapshot)
        return book
    context=transition.strategy_entry_context.load(root,snapshot,now)
    after,evidence=reference_book.rollover(book,snapshot,context,now)
    return reference_book.commit(root,book,after,evidence)


# Consume only published first recommendations using a subsequent original quote, never loose files or a GET request.
def observe_book(root, snapshot, cache, quote_page, now):
    from backend.market import strategy_entries, strategy_entry_history
    book=reference_book.load(root,recover=True,snapshot=snapshot)
    if book.plan.snapshot_id!=snapshot['snapshot_id']:
        raise ValueError('Original model book must precede current advice')
    path=Path(root)/strategy_entries.DIRECTORY/'latest.json'
    intents={}
    if path.exists():
        previous=json.loads(history._read(path,strategy_entries.MAX_BYTES))
        if (previous['receipt_sha256']!=publication._digest({k:v for k,v in previous.items() if k!='receipt_sha256'})
                or previous['sources']!=strategy_entries.sources()):
            raise ValueError('Original published model view differs before hypothetical execution')
        if previous['version']==PROGRESSING_VERSION and previous['day_id']==book.day_id():
            for name,row in previous['rows'].items():
                original=row.get('original_intent')
                if original is None or name in dict(book.resolved):
                    continue
                restored=strategy_entry_history.read(root,name,original['completed_at'],snapshot['snapshot_id'],now)['original']
                if restored.get('day_id')!=book.day_id() or restored.get('entry_version')!=PROGRESSING_VERSION:
                    raise ValueError('Original published model attempt belongs to another day')
                intents[name]=restored
    anchors={name:float(cache['packet'].prefixes[name]['prior_close']) for name in intents}
    after,evidence=reference_book.observe(book,intents,quote_page,anchors,now)
    if evidence is not None:
        after=reference_book.commit(root,book,after,evidence)
    cache['reference_book']=after
    cache['reference_plan']=reference_book.current_plan(after)
    cache['reference_evidence']=asdict(after)
    return after


# Restore immutable scalar plan data without prediction, account access or filesystem adoption.
def restore(value):
    reference = value['reference']
    book = transition.ReferenceBook(**{**reference, 'positions': tuple(tuple(row) for row in reference['positions'])})
    return transition.TransitionPlan(value['snapshot_id'], value['publication_receipt_sha256'], book,
        tuple(tuple(row) for row in value['rows']), tuple(tuple(row) for row in value['source_sha256']))


# Authenticate one native packet and current quotes before applying the declared relative-return mark bridge.
def project(snapshot, cache, quotes, now):
    publication.validate(snapshot, now, expected_sources=publication._sources())
    plan, packet, forecast = cache['reference_plan'], cache['packet'], cache['forecast']
    completed = cache['completed']
    market._same_window(completed, now, cache['available'])
    if (type(plan) is not transition.TransitionPlan or type(packet) is not market.MarketPacket
            or plan.snapshot_id != snapshot['snapshot_id'] or plan.publication_receipt_sha256 != snapshot['receipt_sha256']
            or cache['context']['snapshot_id'] != snapshot['snapshot_id']
            or plan.reference.evidence_sha256 != publication._digest(cache['reference_evidence'])
            or packet.receipt_sha256 != inference._digest(packet.receipt)
            or packet.receipt['arrays_sha256'] != market._inputs_hash(packet.prefixes, packet.snapshot)
            or packet.receipt['source_sha256'] != sha256(Path(market.__file__).read_bytes()).hexdigest()
            or forecast.receipt.get('market_source_evidence') != packet.receipt
            or forecast.receipt.get('contract') != inference.CONTRACT
            or forecast.receipt.get('sources') != inference._inference_sources()
            or forecast.receipt.get('model_receipt') != cache['config']['model_receipt_sha256']
            or forecast.receipt.get('residual_receipt') != cache['config']['residual_receipt_sha256']
            or forecast.receipt['observation']['completed_at'] != completed.isoformat()
            or cache['context']['publication_receipt_sha256'] != snapshot['receipt_sha256']
            or cache['context']['close_receipt_sha256'] != snapshot['identity']['close_receipt_sha256']
            or inference._digest(forecast.receipt) != forecast.receipt_sha256
            or inference._forecast_identity(forecast.distributions) != forecast.receipt['distributions']
            or sha256(cache['config_bytes']).hexdigest() != snapshot['identity']['timing_config_sha256']
            or json.loads(cache['config_bytes']) != cache['config']
            or cache['config']['policy'] != learned_live_timing.POLICY
            or set(cache['config']) != {'policy','model_directory','model_receipt_sha256','residual_directory','residual_receipt_sha256','cost_bps'}
            or cache['config']['cost_bps'] != plan.reference.cost_bps):
        raise ValueError('Original reference, native packet and timing inputs differ')
    marks, shifted, pairs, used = {}, {}, {}, {}
    closing_marks = {name: mark for name, _, mark in plan.reference.positions}
    for name in snapshot['rows']:
        prefix = packet.prefixes.get(name)
        if prefix is None:
            continue
        anchor = float(prefix['prior_close'])
        if not math.isfinite(anchor) or anchor <= 0:
            continue
        original = packet.snapshot['quotes'].get(name)
        current = quotes.get(name)
        pair = None
        if isinstance(original, dict) and isinstance(current, dict):
            if original.get('open') != forecast.receipt['raw_session_openings'].get(name):
                raise ValueError('Original reference prefix opening differs')
            described = execution_quotes.describe(current, 'iex', True, now)
            if described.get('eligible') and described.get('spread_verified') is True:
                merged = {**original, **{key: described[key] for key in ('bid', 'ask', 'bid_size', 'ask_size')},
                          'last': described['bid']/2 + described['ask']/2, 'as_of': current['t'], 'received_at': now.isoformat()}
                pair = inference._quote(merged, completed-timedelta(minutes=15), completed, now)
                if pair is not None:
                    used[name] = merged
        # A completed-candle mark values the model reference; it never supplies execution permission.
        close = float(prefix['close'][-1])
        raw_mark = pair[0] if pair else close
        if math.isfinite(raw_mark) and raw_mark > 0:
            marks[name] = closing_marks[name] * raw_mark / anchor
        pairs[name] = pair
        distribution = forecast.distributions.get(name)
        if pair is not None and distribution is not None:
            shifted[name] = probability.Distribution(distribution.mean+math.log(pair[0]/pair[1]), distribution.scale,
                distribution.residuals, distribution.weights, distribution.horizon)
    _, count, actual_completed = market._window(now)
    if actual_completed != completed:
        raise ValueError('Original reference candle changed')
    packet_identity = {'packet_receipt_sha256': packet.receipt_sha256, 'forecast_receipt_sha256': forecast.receipt_sha256,
                       'quotes': quotes, 'completed_at': completed.isoformat(), 'at': now.isoformat(), 'bridge': BRIDGE}
    progressing=type(cache.get('reference_book')) is reference_book.DayBook
    if progressing:
        book=cache['reference_book']
        prepared,value=reference_book.project(book,marks,shifted,evidence_sha256=publication._digest(packet_identity),terminal=count==25)
        if prepared!=plan:
            raise ValueError('Current hypothetical book and prepared advice differ')
    else:
        value = transition.project(plan, marks, shifted, evidence_sha256=publication._digest(packet_identity),
            price_basis=transition.PRICE_BASIS, terminal=count == 25)
    basis=PROGRESSING_BASIS if progressing else BASIS
    rows = {}
    for name, row in value['rows'].items():
        pair = pairs.get(name)
        state = row['state'] if pair is not None or row['action'] is None else 'unavailable'
        evidence = deepcopy(snapshot['rows'][name]['evidence'])
        evidence['grade_permission_reason'] = evidence.get('reason')
        evidence['reason'] = ('Grade below A; exit the model reference position' if row['reason']=='mandatory_grade_exit'
            else 'Model position reduction' if row['action']=='Sell'
            else 'Model position increase' if row['action']=='Buy' else 'No additional model reference trade')
        evidence.update(model_position_size=row['model_position_weight'], trade_size=row['trade_weight'],
            reference_position_size=row['reference_position_weight'], timing_reason=row['reason'] if pair else 'Fresh compatible IEX quote required',
            waiting_log_utility=row['waiting_log_utility'], completed_candle_at=completed.isoformat(),
            observed_price=pair[0] if pair else None, timing_engine=probability.POLICY, sizing_basis=BASIS,
            reference_basis=transition.BASIS, price_bridge=BRIDGE)
        evidence['sizing_basis']=basis
        if name in shifted:
            distribution = shifted[name]
            evidence.update(waiting_advantage_mean=distribution.mean,
                waiting_advantage_quantiles=probability.weighted_quantiles(
                    distribution.mean+distribution.scale*distribution.residuals, distribution.weights).tolist())
        quoted = used[name]['as_of'] if pair else None
        until = min(completed+timedelta(minutes=15), datetime.fromisoformat(quoted)+timedelta(seconds=execution_quotes.MAX_AGE_SECONDS)) if pair else now
        rows[name] = {'action': row['action'], 'state': state, 'size_weight': row['trade_weight'],
                      'model_position_weight': row['model_position_weight'], 'reference_units': row['reference_units'],
                      'proposed_units': row['proposed_units'], 'quote_at': quoted, 'valid_until': until.isoformat(),
                      'intent_id': publication._digest({'day_id':book.day_id(),'ticker':name}) if progressing else publication._digest({'snapshot_id': plan.snapshot_id, 'reference': plan.reference.evidence_sha256, 'ticker': name}),
                      **({'attempt_resolved':name in dict(book.resolved),
                          'objective_pending':abs(next(item[2] for item in plan.rows if item[0]==name)-row['reference_units'])>1e-12,
                          'price_anchor':float(packet.prefixes[name]['prior_close']) if name in packet.prefixes and math.isfinite(float(packet.prefixes[name]['prior_close'])) else None} if progressing else {}),
                      'evidence': evidence}
    result = {'version': PROGRESSING_VERSION if progressing else VERSION, 'status': 'available', 'snapshot_id': snapshot['snapshot_id'],
              'publication_receipt_sha256': snapshot['receipt_sha256'], 'strategy_identity': snapshot['strategy_identity'],
              'session': completed.date().isoformat(), 'completed_at': completed.isoformat(), 'generated_at': now.isoformat(),
              'valid_until': (completed+timedelta(minutes=15)).isoformat(), 'rows': rows, 'sources': cache['sources'],
              'forecast_receipt_sha256': forecast.receipt_sha256, 'forecast_evidence': cache.get('stored_forecast'),
              'context': cache['context'], 'feed': 'iex', 'historical_training_feed_matches': False, 'account_inputs': False,
              'sizing_basis': basis, 'reference_plan': asdict(plan), 'reference_evidence': cache['reference_evidence'],
              'reference_calculation': value, 'recommendation_not_fill': True,
              'reference_progression':'later_observed_hypothetical_quote_proxy' if progressing else 'standing_no_fills_assumed',
              **({'day_id':book.day_id(),'book_sha256':book.receipt_sha256(),'execution_basis':reference_book.EXECUTION_BASIS} if progressing else {})}
    result['timing_binding'] = {'config_sha256': sha256(cache['config_bytes']).hexdigest(),
        'model_receipt': cache['config']['model_receipt_sha256'], 'residual_receipt': cache['config']['residual_receipt_sha256'],
        'cost_bps': cache['config']['cost_bps']}
    result['receipt_sha256'] = publication._digest(result)
    return result


# Validate restored reference advice as finite owned-unit changes rather than fresh-portfolio purchase sizes.
def validate(value, snapshot, forecast=None):
    plan = restore(value['reference_plan'])
    calculation = value['reference_calculation']
    progressing=value['version']==PROGRESSING_VERSION
    basis=PROGRESSING_BASIS if progressing else BASIS
    if (value['version'] not in VERSIONS or value['sizing_basis'] != basis
            or value['reference_progression'] != ('later_observed_hypothetical_quote_proxy' if progressing else 'standing_no_fills_assumed') or value['recommendation_not_fill'] is not True
            or plan.snapshot_id != snapshot['snapshot_id'] or plan.publication_receipt_sha256 != snapshot['receipt_sha256']
            or plan.reference.evidence_sha256 != publication._digest(value['reference_evidence'])
            or dict(plan.source_sha256) != transition.sources()
            or value['timing_binding']['config_sha256'] != snapshot['identity']['timing_config_sha256']
            or value['timing_binding']['cost_bps'] != plan.reference.cost_bps
            or calculation['plan_sha256'] != plan.receipt_sha256()
            or calculation['receipt_sha256'] != publication._digest({k:v for k,v in calculation.items() if k != 'receipt_sha256'})):
        raise ValueError('Original standing reference advice differs')
    if progressing:
        book=reference_book.restore(value['reference_evidence'])
        if (reference_book.current_plan(book)!=plan or value['day_id']!=book.day_id()
                or value['book_sha256']!=book.receipt_sha256() or value['execution_basis']!=reference_book.EXECUTION_BASIS
                or calculation['version']!=reference_book.VERSION or calculation['day_id']!=book.day_id()
                or calculation['book_sha256']!=book.receipt_sha256() or calculation['book_source_sha256']!=reference_book.sources()
                or calculation['original_daily_buy_budget']!=book.buy_budget):
            raise ValueError('Original observed hypothetical book differs')
    if forecast is not None and (forecast['model_receipt'] != value['timing_binding']['model_receipt']
            or forecast['residual_receipt'] != value['timing_binding']['residual_receipt']
            or forecast['sources'] != inference._inference_sources()
            or forecast['contract'] != inference.CONTRACT):
        raise ValueError('Original reference forecast head differs')
    plan.reference.validate(snapshot)
    original = {row[0]: row for row in plan.rows}
    if set(value['rows']) != set(snapshot['rows']) or set(calculation['rows']) != set(value['rows']) or set(original) != set(value['rows']):
        raise ValueError('Complete original reference stock universe required')
    quoted = None
    if forecast is not None:
        page = value['quote_receipt']
        body = base64.b64decode(page['body_base64'],validate=True)
        at = datetime.fromisoformat(value['rows'][next(iter(value['rows']))]['evidence']['completed_candle_at'])
        observed = datetime.fromisoformat(page['received_at'])
        query,_,_ = market._page({**page,'body':body},market.QUOTE_ENDPOINT,observed)
        if query!={'symbols':','.join(forecast['symbols']),'feed':'iex'}:
            raise ValueError('Original reference quote cohort differs')
        if calculation['terminal'] != (market._window(at)[1] == 25):
            raise ValueError('Original native reference deadline differs')
        quoted = json.loads(body)['quotes']
    for name, row in value['rows'].items():
        saved = calculation['rows'][name]
        if (row['action'] not in ('Buy', 'Sell', None) or row['state'] not in ('execute', 'wait', 'unavailable', 'no_trade')
                or type(row['size_weight']) not in (int, float) or not math.isfinite(row['size_weight']) or not 0 <= row['size_weight'] <= 1
                or row['size_weight'] != saved['trade_weight'] or row['action'] != saved['action']
                or row['model_position_weight'] != original[name][3] or row['model_position_weight'] != saved['model_position_weight']
                or row['proposed_units'] != saved['proposed_units'] or row['reference_units'] != saved['reference_units']
                or (row['action'] == 'Sell' and not 0 < row['proposed_units'] <= row['reference_units'])
                or (row['state'] == 'execute' and not row['size_weight'] > 0)
                or row['evidence']['model_position_size'] != row['model_position_weight']
                or row['evidence']['trade_size'] != row['size_weight']
                or row['state'] != (saved['state'] if row['quote_at'] is not None or row['action'] is None else 'unavailable')
                or any(row['evidence'][key] != snapshot['rows'][name]['evidence'][key] for key in ('grade','inputs_as_of','features'))):
            raise ValueError('Original reference action amount or position differs')
        if progressing and (row['attempt_resolved']!=(name in dict(book.resolved))
                or row['objective_pending']!=(abs(original[name][2]-row['reference_units'])>1e-12)
                or row['intent_id']!=publication._digest({'day_id':book.day_id(),'ticker':name})):
            raise ValueError('Original hypothetical pending objective differs')
        if quoted is not None and row['quote_at'] is not None:
            if not isinstance(quoted.get(name),dict):
                raise ValueError('Original reference quote missing')
            described = execution_quotes.describe(quoted[name],'iex',True,observed)
            stamp = datetime.fromisoformat(row['quote_at'])
            until = min(at+timedelta(minutes=15),stamp+timedelta(seconds=execution_quotes.MAX_AGE_SECONDS))
            if (not described.get('eligible') or described.get('spread_verified') is not True
                    or row['quote_at'] != quoted[name]['t'] or row['evidence']['observed_price'] != described['bid']/2+described['ask']/2
                    or datetime.fromisoformat(row['valid_until']) != until or not at<=stamp<=observed<until
                    or datetime.fromisoformat(row['evidence']['completed_candle_at']) != at):
                raise ValueError('Original reference quote or expiry differs')
        elif quoted is not None and row['state'] in ('execute','wait'):
            raise ValueError('Fresh original quote required for reference action')
    return plan


# Persist one shared original calculation so each stock's first record remains below its unchanged size cap.
def store_proof(root, value):
    proof=deepcopy({key:value[key] for key in ('version','sizing_basis','reference_progression','recommendation_not_fill',
        'reference_plan','reference_evidence','reference_calculation','timing_binding','rows','quote_receipt','day_id','book_sha256','execution_basis')})
    for row in proof['rows'].values():
        row.pop('original_intent',None)
    raw=json.dumps(proof,sort_keys=True,allow_nan=False).encode()
    if len(raw)>524288:
        raise ValueError('Finite shared original reference calculation required')
    identity=sha256(raw).hexdigest();folder=Path(root)/'desk/strategy-entries/reference-proofs';folder.mkdir(mode=0o700,parents=True,exist_ok=True)
    path=folder/(identity+'.json')
    try:
        with path.open('xb') as stream:
            stream.write(raw);stream.flush();os.fsync(stream.fileno())
    except FileExistsError:
        if history._read(path,524288)!=raw:
            raise ValueError('Original shared reference calculation differs')
    descriptor=os.open(folder,os.O_RDONLY)
    try:os.fsync(descriptor)
    finally:os.close(descriptor)
    return {'sha256':identity,'bytes':len(raw)}


# Reopen the exact first calculation independently of current views, quote refreshes or account state.
def read_proof(root, descriptor):
    if set(descriptor)!={'sha256','bytes'} or type(descriptor['bytes']) is not int or not 0<descriptor['bytes']<=524288:
        raise ValueError('Finite original reference proof descriptor required')
    identity=publication._sha(descriptor['sha256'])
    folder=Path(root)/'desk/strategy-entries/reference-proofs'
    if folder.is_symlink():
        raise ValueError('Original reference proof namespace required')
    raw=history._read(folder/(identity+'.json'),524288)
    if len(raw)!=descriptor['bytes'] or sha256(raw).hexdigest()!=identity:
        raise ValueError('Original shared reference proof bytes differ')
    return json.loads(raw)


# Preserve one standing intent across quote refreshes and later candles without implying repeated trades.
def original_intent(root, value, name):
    row = value['rows'][name]
    folder = Path(root)/'desk/strategy-entries/standing-intents'/value['session']
    path = folder/(publication._sha(row['intent_id'])+'.json')
    if path.exists():
        raw = history._read(path, 131072)
        original = json.loads(raw)
        if (original.get('entry_version') != value['version'] or original['ticker'] != name
                or original['snapshot_id'] != value['snapshot_id'] or original['intent_id'] != row['intent_id']
                or (original.get('day_id')!=value.get('day_id') if value['version']==PROGRESSING_VERSION else original['reference_proof']['reference_calculation']['plan_sha256'] != value['reference_calculation']['plan_sha256'])
                or original['receipt_sha256'] != publication._digest({k:v for k,v in original.items() if k != 'receipt_sha256'})):
            raise ValueError('Original standing reference intent differs')
        return original
    if row['state'] != 'execute':
        return None
    original = {'ticker': name, **row, 'entry_version': value['version'], 'at': value['generated_at'], 'completed_at': value['completed_at'],
                **{key:value[key] for key in ('snapshot_id', 'publication_receipt_sha256', 'forecast_receipt_sha256',
                    'strategy_identity', 'forecast_evidence', 'quote_receipt')}, 'recommendation_not_fill': True,
                'reference_proof': {key:value[key] for key in ('version', 'sizing_basis', 'reference_progression', 'recommendation_not_fill',
                    'reference_plan', 'reference_evidence', 'reference_calculation', 'timing_binding', 'rows', 'quote_receipt')}}
    if value['version']==PROGRESSING_VERSION:
        original['day_id']=value['day_id']
        original.pop('reference_proof')
        original['reference_proof_ref']=store_proof(root,value)
    original['receipt_sha256'] = publication._digest(original)
    raw = json.dumps(original, sort_keys=True, allow_nan=False).encode()
    if len(raw) > 131072:
        raise ValueError('Finite original standing reference intent required')
    folder.mkdir(mode=0o700, parents=True, exist_ok=True)
    with path.open('xb') as stream:
        stream.write(raw); stream.flush(); os.fsync(stream.fileno())
    descriptor = os.open(folder, os.O_RDONLY)
    try: os.fsync(descriptor)
    finally: os.close(descriptor)
    return original
