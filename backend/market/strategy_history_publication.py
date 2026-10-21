"""Serve immutable audited model history without accounts or a dated funded record.

An explicit import binds original numerical output and accounting proof to the
same economic code and costs. Reads retain original model/configuration clocks.
They never run a simulation, recreate advice or convert proxies into real fills.
"""

from datetime import date, datetime, timedelta
from hashlib import sha256
import json
import os
from pathlib import Path
from uuid import uuid4

from backend.market import calendar, learned_live_holding, strategy_publication as publication

DIRECTORY = 'desk/strategy-model-history'
MAX_FILE = 1048576
MAX_TOTAL = 32 * 1024 * 1024
ECONOMIC_NAMES=('adaptive_growth_policy.py','grade_led_policy.py','joint_funded_policy.py','market_conditioned_holding.py',
    'forward_arithmetic.py','forward_execution.py','live_probability_timing.py','entry_timing.py',
    'direct_daily_arithmetic.py','learned_entry_data.py','market_conditioned_calibration.py','probabilistic_execution.py')


# Read one exact finite artifact without accepting a symlink or a partial oversized payload.
def _read(path, maximum=MAX_FILE):
    path=Path(path)
    if path.is_symlink() or not 0 < path.stat().st_size <= maximum:
        raise ValueError('Original finite history artifact required')
    raw=path.read_bytes()
    if len(raw)>maximum:
        raise ValueError('History artifact exceeds its bound')
    return raw


# Derive the next reviewed opening separately from a position publication's closing deadline.
def next_open(day):
    historical=json.loads(calendar.HISTORICAL_SESSIONS_PATH.read_bytes())['years']
    current=json.loads(calendar.HOLIDAYS_PATH.read_bytes())['years']
    years={int(year) for year in historical}|{int(year) for year in current}
    closures={value for row in historical.values() for value in row['full_closures']}
    closures.update(value for rows in current.values() for value in rows)
    original=date.fromisoformat(day)
    if original.year not in years or original.weekday()>=5 or day in closures:
        raise ValueError('Original reviewed grade session required')
    following=original+timedelta(days=1)
    while following.year in years and (following.weekday()>=5 or following.isoformat() in closures):
        following+=timedelta(days=1)
    if following.year not in years:
        raise ValueError('Following reviewed grade session unavailable')
    return datetime.combine(following,calendar.REGULAR_OPEN,calendar.NEW_YORK).isoformat()


# Validate the same economic method and costs while keeping all original dated provenance.
def validate_binding(binding, manifest, audit, *, current_sources, cost_bps):
    original=manifest['provenance']
    required=set(ECONOMIC_NAMES)
    selected={name:current_sources['backend/market/'+name] for name in binding['economic_sources']}
    if (binding['schema']!='strategy-history-economics-binding/1' or set(binding['economic_sources'])!=required
            or binding['economic_sources']!=selected
            or binding['strategy_identity']!=publication._strategy_identity(current_sources,cost_bps)
            or binding['config_sha256']!=original['config_sha256']
            or binding['source_record_sha256']!=original['source_record_sha256']
            or original['cost_bps']!=cost_bps or binding['economic_parameters']!={'cost_bps':cost_bps}
            or manifest['policy']!='grade-led-learned-sizing/1' or manifest['counterfactual'] is not True
            or manifest['real_orders'] is not False
            or audit['status']!='VERIFIED_LOCKED_RECOMMENDATION_ACCOUNTING'
            or audit['original_result_sha256']!=binding['history_sha256']):
        raise ValueError('Original audited history economics differ from installed strategy')


# Import only exact audited data files into a separate namespace, without opening any account or native pool.
def import_original(root, source, binding, *, manifest_sha256, audit_path, audit_sha256):
    source=Path(source)
    raw=_read(source/'result.json');audit_raw=_read(audit_path)
    if sha256(raw).hexdigest()!=manifest_sha256 or sha256(audit_raw).hexdigest()!=audit_sha256:
        raise ValueError('Original numerical history or accounting bytes differ')
    manifest,audit=json.loads(raw),json.loads(audit_raw)
    if binding['history_sha256']!=manifest_sha256 or binding['audit_sha256']!=audit_sha256:
        raise ValueError('Original history binding identity differs')
    validate_binding(binding,manifest,audit,current_sources=publication._sources(),cost_bps=manifest['provenance']['cost_bps'])
    folder=Path(root)/DIRECTORY/manifest_sha256
    folder.mkdir(mode=0o700,parents=True,exist_ok=False)
    total=len(raw)+len(audit_raw)
    for ticker,expected in manifest['files'].items():
        if not isinstance(ticker,str) or not ticker.isalnum() or ticker.upper()!=ticker:
            raise ValueError('Explicit original stock filename required')
        content=_read(source/(ticker+'.json'))
        total+=len(content)
        if total>MAX_TOTAL or len(content)!=expected['bytes'] or sha256(content).hexdigest()!=expected['sha256']:
            raise ValueError('Original stock history bytes differ or exceed the finite import bound')
        with (folder/(ticker+'.json')).open('xb') as stream:
            stream.write(content);stream.flush();os.fsync(stream.fileno())
    for name,content in (('manifest.json',raw),('audit.json',audit_raw),('binding.json',json.dumps(binding,sort_keys=True,allow_nan=False).encode())):
        with (folder/name).open('xb') as stream:
            stream.write(content);stream.flush();os.fsync(stream.fileno())
    pointer={'history_sha256':manifest_sha256,'audit_sha256':audit_sha256,
             'binding_sha256':sha256((folder/'binding.json').read_bytes()).hexdigest()}
    temporary=folder.parent/('latest-'+uuid4().hex+'.tmp')
    with temporary.open('xb') as stream:
        stream.write(json.dumps(pointer,sort_keys=True).encode());stream.flush();os.fsync(stream.fileno())
    temporary.replace(folder.parent/'latest.json')
    descriptor=os.open(folder.parent,os.O_RDONLY)
    try:os.fsync(descriptor)
    finally:os.close(descriptor)
    return pointer


# Project only original stock data after source/configuration admission, even if today's position quote has expired.
def read(root,ticker,now):
    config_raw,config=learned_live_holding.read_configuration(root,now)
    pointer=json.loads(_read(Path(root)/DIRECTORY/'latest.json'))
    identity=publication._sha(pointer['history_sha256'])
    folder=Path(root)/DIRECTORY/identity
    if folder.is_symlink() or folder.resolve().parent != (Path(root)/DIRECTORY).resolve():
        raise ValueError('Original history namespace required')
    manifest_raw=_read(folder/'manifest.json');audit_raw=_read(folder/'audit.json');binding_raw=_read(folder/'binding.json')
    if (sha256(manifest_raw).hexdigest()!=identity or sha256(audit_raw).hexdigest()!=pointer['audit_sha256']
            or sha256(binding_raw).hexdigest()!=pointer['binding_sha256']):
        raise ValueError('Original selected history publication differs')
    manifest,audit,binding=json.loads(manifest_raw),json.loads(audit_raw),json.loads(binding_raw)
    validate_binding(binding,manifest,audit,current_sources=publication._sources(),cost_bps=config['cost_bps'])
    if ticker is None:
        overview,held,targets,latest={},{},{},[]
        for name,expected in manifest['files'].items():
            stock_raw=_read(folder/(name+'.json'))
            if sha256(stock_raw).hexdigest()!=expected['sha256']:
                raise ValueError('Original summary stock bytes differ')
            stock=json.loads(stock_raw)
            held[name]=stock['latest_holding'];targets[name]=stock['latest_target']
            overview[name]={'holding':held[name],'target':targets[name],
                'last_trade':stock['trades'][-1] if stock['trades'] else None,'trades':len(stock['trades'])}
            latest.extend(stock['decisions'][-20:])
        final=manifest['curve'][-1]
        return {'schema':manifest['schema'],'policy':manifest['policy'],'start':manifest['start'],'through':manifest['through'],
            'counterfactual':True,'real_orders':False,'provenance':manifest['provenance'],'tickers':sorted(manifest['files']),
            'curve':manifest['curve'],'decisions':manifest['counters']['decisions'],
            'initial_cash':1.0,'starting_equity':1.0,'starting_holdings':{},'starting_basis':'original_fresh_fractional_unit_capital_simulation',
            'ending_equity':final['equity'],'ending_cash':final['cash'],'ending_holdings':held,'latest_targets':targets,
            'latest_decisions':sorted(latest,key=lambda row:row['at'])[-20:],'stock_overview':overview,
            'latest_positions':[],'positions_basis':'original_fractional_units_in_ending_holdings_no_current_price_marks'}
    if ticker not in manifest['files'] or not ticker.isalnum():
        raise ValueError('Original covered history ticker required')
    raw=_read(folder/(ticker+'.json'));expected=manifest['files'][ticker]
    if len(raw)!=expected['bytes'] or sha256(raw).hexdigest()!=expected['sha256']:
        raise ValueError('Original stock history bytes differ')
    value=json.loads(raw)
    if (value['ticker']!=ticker or value['policy']!=manifest['policy']
            or value['provenance']['config_sha256']!=binding['config_sha256']
            or value['provenance']['source_record_sha256']!=binding['source_record_sha256']):
        raise ValueError('Original stock provenance differs')
    value['provenance']={**value['provenance'],'strategy_identity':binding['strategy_identity'],
        'strategy_contract':binding,'verified_against_installed_strategy':True,
        'grade_clock_basis':'original_simulated_close_grade_available_at_next_reviewed_open'}
    value['grade_rows']=[{**row,'at':next_open(row['date'])} for row in value.get('grade_rows',[])]
    return value
