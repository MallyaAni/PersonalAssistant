"""Numerical account-independent regular-session entry observations.

The nightly model chooses position percentages. This collector uses the native
published timing distribution and native current-price transport to decide
execute/wait for a fresh unit-capital allocation. It neither sizes against an
account nor sends orders. IEX is explicitly different from historical SIP.
"""

from copy import deepcopy
from dataclasses import asdict
import base64
from datetime import UTC, datetime, timedelta
from hashlib import sha256
import json
import math
import os
from pathlib import Path
from uuid import uuid4

import numpy as np

from backend.market import alpaca, calendar, execution_quotes, forward_execution
from backend.market import forward_market_evidence as market
from backend.market import forward_probability_timing as inference
from backend.market import learned_live_timing, probabilistic_execution as probability
from backend.market import strategy_entry_context, strategy_publication as publication
from backend.market import strategy_reference_entries as reference_entries
from backend.market.labels import Action, OrderSide, TimingState

VERSION = 'strategy-numerical-entries/1'
DIRECTORY = 'desk/strategy-entries'
MAX_BYTES = 524288
MAX_FORECAST_BYTES = 8 * 1024 * 1024
FORECAST_PART_BYTES = 262144


# Bind the adapter and unchanged numerical/market input mechanisms in each observation.
def sources():
    result = inference._inference_sources()
    for module in (market, learned_live_timing, strategy_entry_context, reference_entries, reference_entries.transition,reference_entries.reference_book):
        result['backend/market/' + Path(module.__file__).name] = sha256(Path(module.__file__).read_bytes()).hexdigest()
    result['backend/market/strategy_entries.py'] = sha256(Path(__file__).read_bytes()).hexdigest()
    return result


# Preserve a complete original forecast in finite files, publishing its manifest only after every part is durable.
def store_forecast(root, forecast):
    raw=json.dumps(forecast.receipt,sort_keys=True,allow_nan=False).encode()
    if len(raw)>MAX_FORECAST_BYTES or sha256(raw).hexdigest()!=forecast.receipt_sha256:
        raise ValueError('Finite original numerical forecast receipt required')
    folder=Path(root)/DIRECTORY/'forecast-evidence'/forecast.receipt_sha256
    folder.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
    try:folder.mkdir(mode=0o700)
    except FileExistsError:
        manifest_raw=(folder/'manifest.json').read_bytes()
        reference={'path':str((folder/'manifest.json').relative_to(Path(root)/DIRECTORY)),
            'sha256':sha256(manifest_raw).hexdigest()}
        if read_forecast(root,reference)!=raw:
            raise ValueError('Original independent forecast evidence conflicts')
        return reference
    parts=[]
    for index,start in enumerate(range(0,len(raw),FORECAST_PART_BYTES)):
        name=f'{index:03d}.part';part=raw[start:start+FORECAST_PART_BYTES]
        with (folder/name).open('xb') as stream:
            stream.write(part);stream.flush();os.fsync(stream.fileno())
        parts.append({'name':name,'bytes':len(part),'sha256':sha256(part).hexdigest()})
    manifest={'schema':'strategy-entry-forecast-parts/1','forecast_sha256':forecast.receipt_sha256,'bytes':len(raw),'parts':parts}
    encoded=json.dumps(manifest,sort_keys=True).encode()
    with (folder/'manifest.json').open('xb') as stream:
        stream.write(encoded);stream.flush();os.fsync(stream.fileno())
    descriptor=os.open(folder,os.O_RDONLY)
    try:os.fsync(descriptor)
    finally:os.close(descriptor)
    return {'path':str((folder/'manifest.json').relative_to(Path(root)/DIRECTORY)),'sha256':sha256(encoded).hexdigest()}


# Verify all original parts before trusting a forecast referenced by displayed advice.
def read_forecast(root, reference):
    base=Path(root)/DIRECTORY
    path=base/reference['path']
    if path.is_symlink() or path.resolve().parent.parent != (base/'forecast-evidence').resolve() or path.name!='manifest.json':
        raise ValueError('Original forecast evidence namespace required')
    encoded=path.read_bytes()
    if len(encoded)>16384 or sha256(encoded).hexdigest()!=reference['sha256']:
        raise ValueError('Original forecast evidence manifest differs')
    manifest=json.loads(encoded)
    if manifest['schema']!='strategy-entry-forecast-parts/1' or not 0<manifest['bytes']<=MAX_FORECAST_BYTES or not 1<=len(manifest['parts'])<=32:
        raise ValueError('Finite original forecast parts required')
    pieces=[]
    for index,part in enumerate(manifest['parts']):
        if part['name']!=f'{index:03d}.part' or not 0<part['bytes']<=FORECAST_PART_BYTES:
            raise ValueError('Original ordered forecast part required')
        source=path.parent/part['name']
        if source.is_symlink() or source.stat().st_size!=part['bytes']:
            raise ValueError('Original forecast part size differs')
        raw=source.read_bytes()
        if sha256(raw).hexdigest()!=part['sha256']:
            raise ValueError('Original forecast part bytes differ')
        pieces.append(raw)
    raw=b''.join(pieces)
    if len(raw)!=manifest['bytes'] or sha256(raw).hexdigest()!=manifest['forecast_sha256']:
        raise ValueError('Original complete forecast bytes differ')
    return raw


# Restore only the installed monthly timing head and residuals, without an account or holding forecast.
def acquire(root, snapshot, *, clock, transport):
    started = market._as_of(clock())
    session, _, completed = market._window(started)
    context = strategy_entry_context.load(root, snapshot, started)
    if context.receipt['trade_session'] != session.isoformat():
        raise ValueError('Current numerical entry session differs from original daily context')
    book=reference_entries.prepare_book(root,snapshot,started) if reference_entries.configured(root) else None
    raw = (Path(root) / learned_live_timing.CONFIG).read_bytes()
    config = json.loads(raw)
    if (sha256(raw).hexdigest() != snapshot['identity']['timing_config_sha256']
            or set(config) != {'policy','model_directory','model_receipt_sha256','residual_directory','residual_receipt_sha256','cost_bps'}
            or config['policy'] != learned_live_timing.POLICY
            or type(config['cost_bps']) not in (int, float) or not math.isfinite(config['cost_bps'])
            or not 0 <= config['cost_bps'] < 10000):
        raise ValueError('Original independent timing configuration differs')
    residual = inference.load_residual_month(learned_live_timing._folder(root, config['residual_directory']),
        receipt_sha256=config['residual_receipt_sha256'], observed_at=started)
    model_folder = learned_live_timing._folder(root, config['model_directory'])
    _, model = forward_execution.load_publication(model_folder, receipt_sha256=config['model_receipt_sha256'], observed_at=started)
    if (tuple(context.panel.tickers) != tuple(residual.receipt['identity']['symbols'])
            or model['identity']['input_identity'].get('cohort') != residual.receipt['identity']['archive_identity']['cohort']
            or model['training']['fit_date'] != residual.receipt['identity']['fit_date']):
        raise ValueError('Original timing model, residual and daily cohort differ')
    packet = market.capture(context.panel.tickers, transport=transport, headers=alpaca.credentials(), clock=clock)
    forecast = market.prepare_forecast(packet, context.panel, context.grades, context.eligible,
        daily_as_of=context.daily_as_of, model_folder=model_folder,
        model_receipt_sha256=config['model_receipt_sha256'], residual_month=residual, clock=clock)
    available = market._as_of(clock())
    market._same_window(completed, available, started)
    if (Path(root) / learned_live_timing.CONFIG).read_bytes() != raw:
        raise ValueError('Timing configuration changed during independent inference')
    result = {'completed':completed, 'snapshot_id':snapshot['snapshot_id'], 'forecast':forecast, 'packet': packet,
        'quotes':deepcopy(packet.snapshot['quotes']), 'config_bytes':raw, 'config':config,
        'context':context.receipt, 'sources':sources(), 'available':available}
    if book is not None:
        result['reference_book']=book
        result['reference_plan']=reference_entries.reference_book.current_plan(book)
        result['reference_evidence']=asdict(book)
    return result


# Reprice the native distribution using exactly the native midpoint-to-original-next-open transport.
def project(snapshot, cache, quotes, now):
    completed, forecast = cache['completed'], cache['forecast']
    market._same_window(completed, now, cache['available'])
    if (cache['snapshot_id'] != snapshot['snapshot_id'] or cache['sources'] != sources()
            or inference._digest(forecast.receipt) != forecast.receipt_sha256
            or inference._forecast_identity(forecast.distributions) != forecast.receipt['distributions']):
        raise ValueError('Original numerical observation changed')
    if 'reference_plan' in cache:
        return reference_entries.project(snapshot, cache, quotes, now)
    rows = {}
    for name, allocation in snapshot['rows'].items():
        weight = allocation['target_weight']
        original = cache['quotes'].get(name)
        current = quotes.get(name)
        quote = deepcopy(original) if isinstance(original, dict) else {}
        if isinstance(current, dict):
            described = execution_quotes.describe(current, 'iex', True, now)
            if described.get('eligible') and described.get('spread_verified') is True:
                quote.update(bid=described['bid'], ask=described['ask'], bid_size=described['bid_size'], ask_size=described['ask_size'],
                    last=described['bid']/2+described['ask']/2, as_of=current['t'], received_at=now.isoformat())
            else:
                quote = {}
        else:
            quote = {}
        pair = inference._quote(quote, completed-timedelta(minutes=15), completed, now)
        distribution = forecast.distributions.get(name)
        choice = probability.Decision(TimingState.NO_TRADE,
                                      reason='No new model allocation')
        shifted = None
        if weight > 0:
            if pair is None or distribution is None:
                choice = probability.Decision(TimingState.UNAVAILABLE, reason='Current compatible quote or calibrated timing distribution unavailable')
            else:
                midpoint, anchor = pair
                shifted = probability.Distribution(distribution.mean + math.log(midpoint/anchor), distribution.scale,
                    distribution.residuals, distribution.weights, distribution.horizon)
                choice = probability.decision(shifted, OrderSide.BUY, weight, cache['config']['cost_bps'], horizon=probability.HORIZON)
        evidence = deepcopy(allocation['evidence'])
        evidence.update(timing_reason=choice.reason, waiting_log_utility=choice.expected_log_utility,
            completed_candle_at=completed.isoformat(), observed_price=pair[0] if pair else None,
            timing_engine=probability.POLICY, sizing_basis='fresh_unit_capital_allocation_not_account_trade_quantity')
        if shifted is not None:
            evidence['waiting_advantage_mean'] = shifted.mean
            evidence['waiting_advantage_quantiles'] = probability.weighted_quantiles(shifted.mean+shifted.scale*shifted.residuals, shifted.weights).tolist()
        rows[name] = {'state':choice.state, 'action':Action.BUY if weight > 0 else None, 'size_weight':weight,
            'quote_at':quote.get('as_of') if pair else None,
            'valid_until':min(completed+timedelta(minutes=15), datetime.fromisoformat(quote['as_of'])+timedelta(seconds=execution_quotes.MAX_AGE_SECONDS)).isoformat() if pair else now.isoformat(),
            'evidence':evidence}
    value = {'version':VERSION, 'status':'available', 'snapshot_id':snapshot['snapshot_id'],
        'publication_receipt_sha256':snapshot['receipt_sha256'], 'strategy_identity':snapshot['strategy_identity'],
        'session':completed.date().isoformat(), 'completed_at':completed.isoformat(), 'generated_at':now.isoformat(),
        'valid_until':(completed+timedelta(minutes=15)).isoformat(), 'rows':rows, 'sources':cache['sources'],
        'forecast_receipt_sha256':forecast.receipt_sha256, 'context':cache['context'],
        'forecast_evidence':cache.get('stored_forecast'),
        'feed':'iex', 'historical_training_feed_matches':False, 'account_inputs':False,
        'sizing_basis':'fresh_unit_capital_allocation_not_account_trade_quantity'}
    value['receipt_sha256'] = publication._digest(value)
    return value


# Write a finite current view atomically and retain the original first recommendation for each stock and candle.
def publish(root, value):
    if sha256(read_forecast(root,value['forecast_evidence'])).hexdigest()!=value['forecast_receipt_sha256']:
        raise ValueError('Original forecast must precede numerical recommendation publication')
    raw = json.dumps(value, sort_keys=True, allow_nan=False).encode()
    if len(raw) > MAX_BYTES:
        raise ValueError('Finite numerical entry publication required')
    folder = Path(root) / DIRECTORY
    folder.mkdir(mode=0o700, parents=True, exist_ok=True)
    history = folder / 'recommendations' / value['session']
    history.mkdir(mode=0o700, parents=True, exist_ok=True)
    for name, row in value['rows'].items():
        if value['version'] in reference_entries.VERSIONS:
            original = reference_entries.original_intent(root, value, name)
            if original is None:
                continue
            key = publication._digest({'ticker':name,'completed_at':original['completed_at'],'snapshot_id':value['snapshot_id']})
            original_raw = json.dumps(original,sort_keys=True,allow_nan=False).encode()
            path = history/(key+'.json')
            try:
                with path.open('xb') as stream:
                    stream.write(original_raw);stream.flush();os.fsync(stream.fileno())
            except FileExistsError:
                if path.read_bytes() != original_raw:
                    raise ValueError('Original standing intent alias differs')
            row['original_intent'] = {'id':key, 'completed_at':original['completed_at'], 'at':original['at'],
                'size_weight':original['size_weight'], 'action':original['action'], 'receipt_sha256':original['receipt_sha256']}
            continue
        if TimingState(row['state']) is not TimingState.EXECUTE:
            continue
        original = {'ticker':name, **row, 'at':value['generated_at'], 'completed_at':value['completed_at'],
            'snapshot_id':value['snapshot_id'], 'publication_receipt_sha256':value['publication_receipt_sha256'],
            'forecast_receipt_sha256':value['forecast_receipt_sha256'], 'strategy_identity':value['strategy_identity'],
            'forecast_evidence':value['forecast_evidence'],
            'quote_receipt':value.get('quote_receipt'), 'recommendation_not_fill':True}
        original['receipt_sha256'] = publication._digest(original)
        key = publication._digest({'ticker':name,'completed_at':value['completed_at'],'snapshot_id':value['snapshot_id']})
        try:
            with (history/(key+'.json')).open('xb') as stream:
                stream.write(json.dumps(original,sort_keys=True,allow_nan=False).encode());stream.flush();os.fsync(stream.fileno())
        except FileExistsError:
            stored = json.loads((history/(key+'.json')).read_bytes())
            if (publication._digest({k:v for k,v in stored.items() if k!='receipt_sha256'}) != stored['receipt_sha256']
                    or any(stored[field] != original[field] for field in ('ticker','completed_at','snapshot_id','strategy_identity'))):
                raise ValueError('Original first recommendation evidence differs')
    if value['version'] in reference_entries.VERSIONS:
        value['receipt_sha256'] = publication._digest({k:v for k,v in value.items() if k!='receipt_sha256'})
        raw = json.dumps(value,sort_keys=True,allow_nan=False).encode()
        if len(raw) > MAX_BYTES:
            raise ValueError('Finite numerical reference publication required')
    temporary = folder/('latest-'+uuid4().hex+'.tmp')
    try:
        with temporary.open('xb') as stream:
            stream.write(raw);stream.flush();os.fsync(stream.fileno())
        temporary.replace(folder/'latest.json')
    finally:
        temporary.unlink(missing_ok=True)
    descriptor = os.open(folder,os.O_RDONLY)
    try:os.fsync(descriptor)
    finally:os.close(descriptor)


# Serve only an unchanged current numerical observation belonging to the exact independent publication.
def read(root, snapshot, now):
    try:
        path = Path(root)/DIRECTORY/'latest.json'
        if path.is_symlink() or path.stat().st_size > MAX_BYTES:
            raise ValueError('Finite original entry observation required')
        value = json.loads(path.read_bytes())
        if (value['version'] not in (VERSION,*reference_entries.VERSIONS) or value['sources'] != sources()
                or value['snapshot_id'] != snapshot['snapshot_id'] or value['strategy_identity'] != snapshot['strategy_identity']
                or value['publication_receipt_sha256'] != snapshot['receipt_sha256']
                or publication._digest({k:v for k,v in value.items() if k!='receipt_sha256'}) != value['receipt_sha256']
                or not datetime.fromisoformat(value['generated_at']) <= now < datetime.fromisoformat(value['valid_until'])
                or set(value['rows']) != set(snapshot['rows'])):
            raise ValueError('Original current numerical entry observation differs')
        forecast_raw = read_forecast(root,value['forecast_evidence'])
        if sha256(forecast_raw).hexdigest()!=value['forecast_receipt_sha256']:
            raise ValueError('Original numerical forecast evidence differs')
        market._window(market._as_of(now))
        if value['version'] in reference_entries.VERSIONS:
            reference_entries.validate(value, snapshot, json.loads(forecast_raw))
            return value
        for name, row in value['rows'].items():
            if (row['size_weight'] != snapshot['rows'][name]['target_weight']
                    or row['state'] not in TimingState
                    or row['state'] == TimingState.EXECUTE
                    and not row['size_weight'] > 0):
                raise ValueError('Numerical entry size differs from original model')
        return value
    except (OSError, ValueError, KeyError, TypeError):
        return {'version':VERSION,'status':'unavailable','rows':{},'reason':'Fresh numerical 15-minute observation required'}


# Collect on the existing display loop, sharing one forecast per candle and never touching orders or accounts.
def collect(root, cache, *, clock=None, transport=None):
    import fcntl
    clock = clock or (lambda:datetime.now(UTC))
    now = market._as_of(clock())
    try:
        _, _, completed = market._window(now)
    except ValueError:
        cache.clear()
        return {'status':'closed'}
    snapshot = publication.read(root, now)
    failure = cache.get('failure')
    if failure and failure['completed'] == completed and (failure['attempts'] >= 3 or now < failure['retry_at']):
        return {'status':'unavailable','reason':'Current numerical acquisition unavailable'}
    folder = Path(root)/DIRECTORY
    folder.mkdir(mode=0o700,parents=True,exist_ok=True)
    with (folder/'collect.lock').open('a') as lock:
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:return {'status':'busy'}
        transport = transport or learned_live_timing.market_transport
        if cache.get('completed') != completed or cache.get('snapshot_id') != snapshot['snapshot_id']:
            attempts = failure['attempts'] if failure and failure['completed'] == completed else 0
            cache.clear()
            try:
                cache.update(acquire(root,snapshot,clock=clock,transport=transport))
            except Exception:
                cache.clear()
                cache['failure']={'completed':completed,'attempts':attempts+1,'retry_at':now+timedelta(seconds=60)}
                raise
        if not cache.get('stored_forecast'):
            try:
                cache['stored_forecast']=store_forecast(root,cache['forecast'])
            except Exception:
                cache.clear()
                raise
        if (Path(root)/learned_live_timing.CONFIG).read_bytes() != cache['config_bytes']:
            cache.clear()
            raise ValueError('Installed timing configuration changed')
        quote_page = market.capture_quotes(cache['forecast'].receipt['symbols'],transport=transport,
            headers=alpaca.credentials(),clock=clock,expected_window=(completed,cache['available']))
        observed = market._as_of(clock())
        query, _, _ = market._page(quote_page,market.QUOTE_ENDPOINT,observed)
        if query != {'symbols':','.join(cache['forecast'].receipt['symbols']),'feed':'iex'}:
            raise ValueError('Original current quote cohort differs')
        quotes = json.loads(quote_page['body'])['quotes']
        if 'reference_book' in cache:
            reference_entries.observe_book(root,snapshot,cache,quote_page,observed)
        value = project(snapshot,cache,quotes,observed)
        value['quote_receipt'] = {key:quote_page[key] for key in ('url','requested_at','received_at','status','sha256')}
        value['quote_receipt']['body_base64'] = base64.b64encode(quote_page['body']).decode()
        value['receipt_sha256'] = publication._digest({k:v for k,v in value.items() if k!='receipt_sha256'})
        publish(root,value)
        return {'status':'collected','completed_at':completed.isoformat(),'rows':len(value['rows'])}
