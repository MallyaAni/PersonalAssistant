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

VERSION = 'strategy-numerical-entries/2'
BASIS = 'standing_counterfactual_reference_transition_not_viewer_order'
BRIDGE = 'original_adjusted_reference_close_times_current_IEX_return_from_attested_prior_IEX_close'


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
    value = transition.project(plan, marks, shifted, evidence_sha256=publication._digest(packet_identity),
        price_basis=transition.PRICE_BASIS, terminal=count == 25)
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
                      'intent_id': publication._digest({'snapshot_id': plan.snapshot_id, 'reference': plan.reference.evidence_sha256, 'ticker': name}),
                      'evidence': evidence}
    result = {'version': VERSION, 'status': 'available', 'snapshot_id': snapshot['snapshot_id'],
              'publication_receipt_sha256': snapshot['receipt_sha256'], 'strategy_identity': snapshot['strategy_identity'],
              'session': completed.date().isoformat(), 'completed_at': completed.isoformat(), 'generated_at': now.isoformat(),
              'valid_until': (completed+timedelta(minutes=15)).isoformat(), 'rows': rows, 'sources': cache['sources'],
              'forecast_receipt_sha256': forecast.receipt_sha256, 'forecast_evidence': cache.get('stored_forecast'),
              'context': cache['context'], 'feed': 'iex', 'historical_training_feed_matches': False, 'account_inputs': False,
              'sizing_basis': BASIS, 'reference_plan': asdict(plan), 'reference_evidence': cache['reference_evidence'],
              'reference_calculation': value, 'recommendation_not_fill': True, 'reference_progression': 'standing_no_fills_assumed'}
    result['timing_binding'] = {'config_sha256': sha256(cache['config_bytes']).hexdigest(),
        'model_receipt': cache['config']['model_receipt_sha256'], 'residual_receipt': cache['config']['residual_receipt_sha256'],
        'cost_bps': cache['config']['cost_bps']}
    result['receipt_sha256'] = publication._digest(result)
    return result


# Validate restored reference advice as finite owned-unit changes rather than fresh-portfolio purchase sizes.
def validate(value, snapshot, forecast=None):
    plan = restore(value['reference_plan'])
    calculation = value['reference_calculation']
    if (value['version'] != VERSION or value['sizing_basis'] != BASIS
            or value['reference_progression'] != 'standing_no_fills_assumed' or value['recommendation_not_fill'] is not True
            or plan.snapshot_id != snapshot['snapshot_id'] or plan.publication_receipt_sha256 != snapshot['receipt_sha256']
            or plan.reference.evidence_sha256 != publication._digest(value['reference_evidence'])
            or dict(plan.source_sha256) != transition.sources()
            or value['timing_binding']['config_sha256'] != snapshot['identity']['timing_config_sha256']
            or value['timing_binding']['cost_bps'] != plan.reference.cost_bps
            or calculation['plan_sha256'] != plan.receipt_sha256()
            or calculation['receipt_sha256'] != publication._digest({k:v for k,v in calculation.items() if k != 'receipt_sha256'})):
        raise ValueError('Original standing reference advice differs')
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


# Preserve one standing intent across quote refreshes and later candles without implying repeated trades.
def original_intent(root, value, name):
    row = value['rows'][name]
    folder = Path(root)/'desk/strategy-entries/standing-intents'/value['session']
    path = folder/(publication._sha(row['intent_id'])+'.json')
    if path.exists():
        raw = history._read(path, 131072)
        original = json.loads(raw)
        if (original.get('entry_version') != VERSION or original['ticker'] != name
                or original['snapshot_id'] != value['snapshot_id'] or original['intent_id'] != row['intent_id']
                or original['reference_proof']['reference_calculation']['plan_sha256'] != value['reference_calculation']['plan_sha256']
                or original['receipt_sha256'] != publication._digest({k:v for k,v in original.items() if k != 'receipt_sha256'})):
            raise ValueError('Original standing reference intent differs')
        return original
    if row['state'] != 'execute':
        return None
    original = {'ticker': name, **row, 'entry_version': VERSION, 'at': value['generated_at'], 'completed_at': value['completed_at'],
                **{key:value[key] for key in ('snapshot_id', 'publication_receipt_sha256', 'forecast_receipt_sha256',
                    'strategy_identity', 'forecast_evidence', 'quote_receipt')}, 'recommendation_not_fill': True,
                'reference_proof': {key:value[key] for key in ('version', 'sizing_basis', 'reference_progression', 'recommendation_not_fill',
                    'reference_plan', 'reference_evidence', 'reference_calculation', 'timing_binding', 'rows', 'quote_receipt')}}
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
