"""Read one original recorded numerical recommendation without regenerating it.

Historical advice may remain readable after its quote expires. Its original
validity, price, source and model position remain explicit; this is not a new
entry assessment, a fill or a claim of hostile-filesystem isolation.
"""

import base64
from datetime import datetime, timedelta
from hashlib import sha256
import json
from pathlib import Path

from backend.market import calendar, execution_quotes, learned_live_holding
from backend.market import strategy_entries as entries, strategy_publication as publication

MAX_RECORD_BYTES = 131072


# Read a finite original record while rejecting symlinks and in-place changes during the read.
def _read(path, maximum):
    from backend.market.strategy_entry_context import _read as original_read
    return original_read(path, maximum)


# Require an aware original timestamp before comparing its market session or publication clock.
def _instant(value):
    instant = datetime.fromisoformat(value)
    if instant.utcoffset() is None:
        raise ValueError('Original aware recommendation clock required')
    return instant


# Restore an exact first recommendation using its original candle and snapshot, independently of latest pointers.
def read(root, ticker, completed_at, snapshot_id, now):
    if not isinstance(ticker,str) or not ticker or not ticker.isalnum() or ticker.upper()!=ticker or len(ticker)>12:
        raise ValueError('Original recommendation ticker required')
    if not isinstance(now,datetime) or now.utcoffset() is None:
        raise ValueError('Aware historical read clock required')
    snapshot_id=publication._sha(snapshot_id)
    completed=_instant(completed_at).astimezone(calendar.NEW_YORK)
    _,_,original_window=entries.market._window(completed+timedelta(seconds=1))
    if completed!=original_window:
        raise ValueError('Original completed regular candle required')
    key=publication._digest({'ticker':ticker,'completed_at':completed.isoformat(),'snapshot_id':snapshot_id})
    base=Path(root)/entries.DIRECTORY/'recommendations'
    folder=base/completed.date().isoformat()
    if folder.is_symlink() or folder.resolve().parent!=base.resolve():
        raise ValueError('Original recommendation namespace required')
    raw=_read(folder/(key+'.json'),MAX_RECORD_BYTES)
    original=json.loads(raw)
    at=_instant(original['at'])
    if (original['ticker']!=ticker or original['completed_at']!=completed.isoformat()
            or original['snapshot_id']!=snapshot_id or original['recommendation_not_fill'] is not True
            or original['state']!='execute' or original['action']!='Buy'
            or publication._digest({k:v for k,v in original.items() if k!='receipt_sha256'})!=original['receipt_sha256']
            or not completed<=at<=now or at>=completed+timedelta(minutes=15)):
        raise ValueError('Original first recommendation identity differs')
    snapshot=json.loads(_read(Path(root)/publication.DIRECTORY/(snapshot_id+'.json'),publication.MAX_BYTES))
    publication.validate(snapshot,at)
    _,config=learned_live_holding.read_configuration(root,now)
    installed=publication._strategy_identity(publication._sources(),config['cost_bps'])
    allocation=snapshot['rows'][ticker]
    evidence=original['evidence']
    if (snapshot['snapshot_id']!=snapshot_id or snapshot['receipt_sha256']!=original['publication_receipt_sha256']
            or installed!=snapshot['strategy_identity'] or installed!=original['strategy_identity']
            or type(original['size_weight']) not in (int,float) or not 0<original['size_weight']<=1
            or original['size_weight']!=allocation['target_weight']
            or any(evidence[key]!=allocation['evidence'][key] for key in ('grade','inputs_as_of','model_position_size','features'))
            or evidence['completed_candle_at']!=completed.isoformat()
            or evidence['sizing_basis']!='fresh_unit_capital_allocation_not_account_trade_quantity'):
        raise ValueError('Original recommendation economics or position differs')
    forecast_raw=entries.read_forecast(root,original['forecast_evidence'])
    if sha256(forecast_raw).hexdigest()!=original['forecast_receipt_sha256']:
        raise ValueError('Original recommendation forecast differs')
    forecast=json.loads(forecast_raw)
    if ticker not in forecast['symbols'] or forecast['distributions'].get(ticker) is None:
        raise ValueError('Original stock timing distribution required')
    quote=original['quote_receipt']
    body=base64.b64decode(quote['body_base64'],validate=True)
    page={**{k:quote[k] for k in ('url','requested_at','received_at','status','sha256')},'body':body}
    query,_,_=entries.market._page(page,entries.market.QUOTE_ENDPOINT,at)
    if query!={'symbols':','.join(forecast['symbols']),'feed':'iex'}:
        raise ValueError('Original quote cohort differs')
    current=json.loads(body)['quotes'][ticker]
    described=execution_quotes.describe(current,'iex',True,at)
    quote_at=_instant(current['t'])
    until=min(completed+timedelta(minutes=15),quote_at+timedelta(seconds=execution_quotes.MAX_AGE_SECONDS))
    if (not described.get('eligible') or described.get('spread_verified') is not True
            or evidence['observed_price']!=described['bid']/2+described['ask']/2
            or _instant(original['quote_at'])!=quote_at or _instant(original['valid_until'])!=until
            or not at<until):
        raise ValueError('Original observed recommendation quote differs')
    return {'schema':'strategy-recorded-entry/1','id':key,'ticker':ticker,'original':original,
        'original_bytes_sha256':sha256(raw).hexdigest(),'snapshot_identity':snapshot['identity'],
        'recorded_at':original['at'],'original_valid_until':original['valid_until'],
        'current_instruction':False,'recommendation_not_fill':True,'account_inputs':False,
        'verified_against_installed_economics':True,'historical_training_feed_matches':False,
        'basis':'original_recorded_model_recommendation_not_counterfactual_or_execution'}
