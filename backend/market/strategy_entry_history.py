"""Read one original recorded numerical recommendation without regenerating it.

Historical advice may remain readable after its quote expires. Its original
validity, price, source and model position remain explicit; this is not a new
entry assessment, a fill or a claim of hostile-filesystem isolation.
"""

import base64
from datetime import UTC, date, datetime, timedelta
from hashlib import sha256
from itertools import islice
import json
import math
import os
from pathlib import Path
from uuid import uuid4

from backend.market import calendar, execution_quotes, learned_live_holding
from backend.market import strategy_entries as entries, strategy_publication as publication

MAX_RECORD_BYTES = 131072
INDEX_SCHEMA = 'strategy-recorded-entry-index/1'
CHECKPOINT_SCHEMA = 'strategy-recorded-index-coverage/1'
PAGE_SCHEMA = 'strategy-recorded-entries/1'
INDEX_DIRECTORY = 'recorded-index'
MAX_INDEX_BYTES = 4096
MAX_CHECKPOINT_BYTES = 131072
MAX_INDEX_DAYS = 10000
MAX_DAY_RECORDS = 4096
MAX_SCAN_BYTES = 32 * 1024 * 1024
MAX_PAGE = 64


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
    reference = original.get('entry_version') in entries.reference_entries.VERSIONS
    at=_instant(original['at'])
    if (original['ticker']!=ticker or original['completed_at']!=completed.isoformat()
            or original['snapshot_id']!=snapshot_id or original['recommendation_not_fill'] is not True
            or original['state']!='execute' or original['action'] not in (('Buy','Sell') if reference else ('Buy',))
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
            or not reference and original['size_weight']!=allocation['target_weight']
            or any(evidence[key]!=allocation['evidence'][key] for key in (('grade','inputs_as_of','features') if reference else ('grade','inputs_as_of','model_position_size','features')))
            or evidence['completed_candle_at']!=completed.isoformat()
            or evidence['sizing_basis']!=(entries.reference_entries.PROGRESSING_BASIS if original.get('entry_version')==entries.reference_entries.PROGRESSING_VERSION
                else entries.reference_entries.BASIS if reference else 'fresh_unit_capital_allocation_not_account_trade_quantity')):
        raise ValueError('Original recommendation economics or position differs')
    forecast_raw=entries.read_forecast(root,original['forecast_evidence'])
    if sha256(forecast_raw).hexdigest()!=original['forecast_receipt_sha256']:
        raise ValueError('Original recommendation forecast differs')
    forecast=json.loads(forecast_raw)
    if reference:
        proof = (entries.reference_entries.read_proof(root,original['reference_proof_ref'])
            if original.get('entry_version')==entries.reference_entries.PROGRESSING_VERSION else original['reference_proof'])
        entries.reference_entries.validate(proof,snapshot,forecast)
        saved = proof['rows'][ticker]
        if any(original[field] != saved[field] for field in ('action','state','size_weight','model_position_weight','reference_units','proposed_units','quote_at','valid_until','evidence','intent_id')):
            raise ValueError('Original standing reference record differs')
        if original.get('entry_version')==entries.reference_entries.PROGRESSING_VERSION and (
                original['day_id']!=proof['day_id'] or any(original[field]!=saved[field]
                    for field in ('price_anchor','attempt_resolved','objective_pending'))):
            raise ValueError('Original hypothetical attempt differs')
    untimed_reference = reference and (original['evidence']['timing_reason']=='mandatory_grade_exit'
        or proof['reference_calculation']['terminal'] is True and entries.market._window(completed)[1]==25)
    if ticker not in forecast['symbols'] or forecast['distributions'].get(ticker) is None and not untimed_reference:
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
        'basis':'original_recorded_counterfactual_reference_recommendation_not_execution' if reference else 'original_recorded_model_recommendation_not_counterfactual_or_execution'}


# Enumerate a finite dedicated namespace without following substituted directories or files.
def _children(folder, maximum):
    if folder.is_symlink() or not folder.is_dir():
        raise ValueError('Original recorded-index directory required')
    children=list(islice(folder.iterdir(),maximum+1))
    if len(children)>maximum or any(path.is_symlink() for path in children):
        raise ValueError('Finite original recorded-index namespace required')
    return children


# Validate a small discovery reference without treating its metadata as a replacement for the original record.
def _index(raw, ticker, day, key):
    value=json.loads(raw)
    fields={'schema','id','ticker','at','completed_at','snapshot_id','strategy_identity','action','size_weight',
        'valid_until','original_bytes_sha256','original_receipt_sha256','indexed_view_at','indexed_view_sha256','receipt_sha256'}
    reference = value.get('schema') == 'strategy-recorded-entry-index/2'
    if (set(value)!=fields or value['schema'] not in (INDEX_SCHEMA,'strategy-recorded-entry-index/2') or value['ticker']!=ticker or value['id']!=key
            or value['action'] not in (('Buy','Sell') if reference else ('Buy',)) or type(value['size_weight']) not in (int,float)
            or not math.isfinite(value['size_weight']) or not 0<value['size_weight']<=1
            or publication._digest({name:item for name,item in value.items() if name!='receipt_sha256'})!=value['receipt_sha256']
            or _instant(value['completed_at']).astimezone(calendar.NEW_YORK).date().isoformat()!=day
            or publication._digest({'ticker':ticker,'completed_at':value['completed_at'],'snapshot_id':value['snapshot_id']})!=key):
        raise ValueError('Original recorded-index identity differs')
    for name in ('id','snapshot_id','strategy_identity','original_bytes_sha256','original_receipt_sha256','indexed_view_sha256','receipt_sha256'):
        publication._sha(value[name])
    if (not _instant(value['completed_at'])<=_instant(value['at'])<_instant(value['valid_until'])
            or not _instant(value['at'])<=_instant(value['indexed_view_at'])
            or not reference and _instant(value['indexed_view_at'])>=_instant(value['completed_at'])+timedelta(minutes=15)):
        raise ValueError('Original recorded-index clocks differ')
    return value


# Save only a fully validated original reference; partial or conflicting references are never overwritten.
def _write_index(root, restored, view):
    original=restored['original']
    value={'schema':'strategy-recorded-entry-index/2' if original.get('entry_version') in entries.reference_entries.VERSIONS else INDEX_SCHEMA,'id':restored['id'],'ticker':restored['ticker'],
        **{key:original[key] for key in ('at','completed_at','snapshot_id','strategy_identity','action','size_weight','valid_until')},
        'original_bytes_sha256':restored['original_bytes_sha256'],'original_receipt_sha256':original['receipt_sha256'],
        'indexed_view_at':view['generated_at'],'indexed_view_sha256':view['receipt_sha256']}
    value['receipt_sha256']=publication._digest(value)
    raw=json.dumps(value,sort_keys=True,allow_nan=False).encode()
    if len(raw)>MAX_INDEX_BYTES:
        raise ValueError('Finite recorded reference required')
    folder=Path(root)/entries.DIRECTORY/INDEX_DIRECTORY/value['strategy_identity']/value['ticker']/_instant(value['completed_at']).astimezone(calendar.NEW_YORK).date().isoformat()
    folder.mkdir(mode=0o700,parents=True,exist_ok=True)
    path=folder/(value['id']+'.json')
    try:
        with path.open('xb') as stream:
            stream.write(raw);stream.flush();os.fsync(stream.fileno())
    except FileExistsError:
        if _read(path,MAX_INDEX_BYTES)!=raw:
            raise ValueError('Original recorded reference conflicts')
    descriptor=os.open(folder,os.O_RDONLY)
    try:os.fsync(descriptor)
    finally:os.close(descriptor)
    if _read(path,MAX_INDEX_BYTES)!=raw:
        raise ValueError('Original recorded reference readback differs')


# Trust only a completed index pass and retain its explicit coverage independently of later current-pointer damage.
def _checkpoint(folder, now):
    path=folder/'coverage.json'
    if not path.exists():
        return None
    value=json.loads(_read(path,MAX_CHECKPOINT_BYTES))
    if (set(value)!={'schema','strategy_identity','sources','coverage_from','through','view_sha256','counts','receipt_sha256'}
            or value['schema']!=CHECKPOINT_SCHEMA or value['sources']!=entries.sources()
            or publication._digest({key:item for key,item in value.items() if key!='receipt_sha256'})!=value['receipt_sha256']
            or value['strategy_identity']!=folder.name or not isinstance(value['counts'],dict) or len(value['counts'])>4096
            or any(not isinstance(name,str) or not name or not name.isalnum() or name.upper()!=name or len(name)>12
                or type(count) is not int or not 0<=count<=MAX_INDEX_DAYS*MAX_DAY_RECORDS for name,count in value['counts'].items())
            or not _instant(value['coverage_from'])<=_instant(value['through'])<=now):
        raise ValueError('Original recording-index coverage differs')
    publication._sha(value['strategy_identity']);publication._sha(value['view_sha256'])
    return value


# Publish coverage only after every original reference for this exact view has been read back.
def _publish_checkpoint(folder, value, previous, counts):
    checkpoint={'schema':CHECKPOINT_SCHEMA,'strategy_identity':value['strategy_identity'],'sources':value['sources'],
        'coverage_from':previous['coverage_from'] if previous else value['completed_at'],
        'through':value['generated_at'],'view_sha256':value['receipt_sha256'],'counts':counts}
    checkpoint['receipt_sha256']=publication._digest(checkpoint)
    raw=json.dumps(checkpoint,sort_keys=True,allow_nan=False).encode()
    if len(raw)>MAX_CHECKPOINT_BYTES:
        raise ValueError('Finite index-coverage metadata required')
    temporary=folder/('coverage-'+uuid4().hex+'.tmp')
    try:
        with temporary.open('xb') as stream:
            stream.write(raw);stream.flush();os.fsync(stream.fileno())
        temporary.replace(folder/'coverage.json')
        descriptor=os.open(folder,os.O_RDONLY)
        try:os.fsync(descriptor)
        finally:os.close(descriptor)
    finally:
        temporary.unlink(missing_ok=True)
    if _read(folder/'coverage.json',MAX_CHECKPOINT_BYTES)!=raw:
        raise ValueError('Original index coverage readback differs')


# Discover first decisions only through a successfully published numerical view, never by adopting loose record files.
def remember_latest(root, now):
    if not isinstance(now,datetime) or now.utcoffset() is None:
        raise ValueError('Aware recording-index clock required')
    folder=Path(root)/entries.DIRECTORY
    path=folder/'latest.json'
    if not path.exists():
        return 0
    raw=_read(path,entries.MAX_BYTES)
    value=json.loads(raw)
    completed,generated=(_instant(value[key]) for key in ('completed_at','generated_at'))
    if (value['version'] not in (entries.VERSION,*entries.reference_entries.VERSIONS) or value['sources']!=entries.sources()
            or publication._digest({key:item for key,item in value.items() if key!='receipt_sha256'})!=value['receipt_sha256']
            or not completed<=generated<completed+timedelta(minutes=15) or generated>now
            or value['session']!=completed.astimezone(calendar.NEW_YORK).date().isoformat()
            or not isinstance(value['rows'],dict) or not 0<len(value['rows'])<=512):
        raise ValueError('Original published numerical view required for indexing')
    import fcntl
    index_folder=folder/INDEX_DIRECTORY/publication._sha(value['strategy_identity'])
    if index_folder.is_symlink():
        raise ValueError('Original recording-index namespace required')
    index_folder.mkdir(mode=0o700,parents=True,exist_ok=True)
    with (index_folder/'index.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        if _read(path,entries.MAX_BYTES)!=raw:
            raise ValueError('Published view changed before index ownership')
        previous=_checkpoint(index_folder,now)
        if previous:
            if generated<_instant(previous['through']) or generated==_instant(previous['through']) and value['receipt_sha256']!=previous['view_sha256']:
                raise ValueError('Original index coverage cannot move backward or replace a same-clock view')
            if value['receipt_sha256']==previous['view_sha256']:
                return 0
        count=0
        counts=dict(previous['counts']) if previous else {}
        for ticker,row in value['rows'].items():
            reference = value['version'] in entries.reference_entries.VERSIONS
            first = row.get('original_intent') if reference else None
            if (reference and first is None) or (not reference and row['state']!='execute'):
                continue
            recorded_completed = first['completed_at'] if reference else value['completed_at']
            recorded_size = first['size_weight'] if reference else row['size_weight']
            key=publication._digest({'ticker':ticker,'completed_at':recorded_completed,'snapshot_id':value['snapshot_id']})
            target=index_folder/ticker/value['session']/(key+'.json')
            if target.exists():
                indexed=_index(_read(target,MAX_INDEX_BYTES),ticker,value['session'],key)
                if (indexed['snapshot_id']!=value['snapshot_id'] or indexed['strategy_identity']!=value['strategy_identity']
                        or indexed['size_weight']!=recorded_size):
                    raise ValueError('Published observation and original recorded reference differ')
                if previous is None or _instant(indexed['indexed_view_at'])>_instant(previous['through']):
                    restored=read(root,ticker,recorded_completed,value['snapshot_id'],now)
                    if (indexed['indexed_view_sha256']!=value['receipt_sha256'] or indexed['indexed_view_at']!=value['generated_at']
                            or indexed['original_bytes_sha256']!=restored['original_bytes_sha256']):
                        raise ValueError('Only original interrupted index metadata can complete')
                    counts[ticker]=counts.get(ticker,0)+1
                continue
            restored=read(root,ticker,recorded_completed,value['snapshot_id'],now)
            original=restored['original']
            if (original['publication_receipt_sha256']!=value['publication_receipt_sha256']
                    or original['strategy_identity']!=value['strategy_identity'] or original['size_weight']!=recorded_size
                    or reference and original['receipt_sha256'] != first['receipt_sha256']):
                raise ValueError('Original first decision differs from published observation')
            _write_index(root,restored,value);count+=1
            counts[ticker]=counts.get(ticker,0)+1
        _publish_checkpoint(index_folder,value,previous,counts)
        return count


# Decode an opaque chronological page boundary without allowing a caller to select a filesystem path.
def _cursor(value, now):
    if value is None:
        return None
    if not isinstance(value,str) or not 0<len(value)<=256:
        raise ValueError('Finite original-record cursor required')
    decoded=json.loads(base64.b64decode(value,altchars=b'-_',validate=True))
    if not isinstance(decoded,list) or len(decoded)!=2:
        raise ValueError('Original-record cursor shape differs')
    instant=_instant(decoded[0]);key=publication._sha(decoded[1])
    if instant>now:
        raise ValueError('Original-record cursor cannot select the future')
    return instant,key


# Page original source-matched advice independently of current quote expiry or mutable latest pointers.
def recent(root, ticker, now, *, before=None, limit=MAX_PAGE):
    if (not isinstance(ticker,str) or not ticker or not ticker.isalnum() or ticker.upper()!=ticker or len(ticker)>12
            or not isinstance(now,datetime) or now.utcoffset() is None or type(limit) is not int or not 1<=limit<=MAX_PAGE):
        raise ValueError('Bounded original recommendation page required')
    boundary=_cursor(before,now)
    base=Path(root)/entries.DIRECTORY
    result={'schema':PAGE_SCHEMA,'ticker':ticker,'current_instruction':False,'account_inputs':False,
        'recommendation_not_fill':True,'items':[],'next_cursor':None,'strategy_identity':None,
        'coverage_from':None,'indexed_through':None}
    if not (base/INDEX_DIRECTORY).exists():
        return result
    _,config=learned_live_holding.read_configuration(root,now)
    installed=publication._strategy_identity(publication._sources(),config['cost_bps'])
    result['strategy_identity']=installed
    strategy_folder=base/INDEX_DIRECTORY/installed
    if not strategy_folder.exists():
        return result
    checkpoint=_checkpoint(strategy_folder,now)
    if checkpoint is None:
        raise ValueError('Original recording-index pass is incomplete')
    result.update(coverage_from=checkpoint['coverage_from'],indexed_through=checkpoint['through'])
    folder=strategy_folder/ticker
    if not folder.exists():
        if checkpoint['counts'].get(ticker,0):
            raise ValueError('Original recording-index coverage count differs')
        return result
    days=sorted(_children(folder,MAX_INDEX_DAYS),key=lambda path:path.name,reverse=True)
    candidates=[];scanned=0;covered=0
    for day in days:
        if date.fromisoformat(day.name).isoformat()!=day.name or day.name>now.astimezone(calendar.NEW_YORK).date().isoformat():
            raise ValueError('Original recorded session directory required')
        for path in _children(day,MAX_DAY_RECORDS):
            if path.suffix!='.json':
                raise ValueError('Original recorded reference filename required')
            raw=_read(path,MAX_INDEX_BYTES);scanned+=len(raw)
            if scanned>MAX_SCAN_BYTES:
                raise ValueError('Original recorded page exceeds finite scan bound')
            value=_index(raw,ticker,day.name,path.stem)
            order=(_instant(value['at']),value['id'])
            if order[0]>now:
                raise ValueError('Original recorded reference is in the future')
            if value['strategy_identity']!=installed:
                raise ValueError('Original index and installed economics differ')
            if _instant(value['indexed_view_at'])>_instant(checkpoint['through']):
                continue
            covered+=1
            if boundary and order>=boundary:
                continue
            candidates.append((order,value))
    if covered!=checkpoint['counts'].get(ticker,0):
        raise ValueError('Original recording-index coverage count differs')
    candidates.sort(key=lambda pair:pair[0],reverse=True)
    for _,value in candidates[:limit]:
        restored=read(root,ticker,value['completed_at'],value['snapshot_id'],now)
        original=restored['original']
        if (restored['id']!=value['id'] or restored['original_bytes_sha256']!=value['original_bytes_sha256']
                or original['receipt_sha256']!=value['original_receipt_sha256']
                or any(original[key]!=value[key] for key in ('at','valid_until','action','size_weight','strategy_identity'))):
            raise ValueError('Original recorded reference and decision bytes differ')
        result['items'].append({key:value[key] for key in ('id','ticker','at','completed_at','snapshot_id',
            'strategy_identity','action','size_weight','valid_until','original_bytes_sha256')})
    if len(candidates)>limit and result['items']:
        last=candidates[limit-1][0]
        result['next_cursor']=base64.urlsafe_b64encode(json.dumps([last[0].astimezone(UTC).isoformat(),last[1]]).encode()).decode()
    return result
