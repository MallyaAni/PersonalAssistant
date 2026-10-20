"""Install exact audited history as release data, never rerunning its simulation."""
import base64
from datetime import UTC,datetime
import gzip
from hashlib import sha256
import io
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4

from backend.market import strategy_history_publication as history

SCHEMA='strategy-history-installation/1'


# Validate every bounded original asset before a release changes the selected history.
def prepare(source,review,cost_bps):
    source=Path(source)
    if (review['schema']!='strategy-history-install-review/1' or review['counterfactual'] is not True
            or review['real_orders'] is not False or type(review['stocks']) is not int
            or not 0<review['stocks']<=512 or len(review['compressed_files'])!=review['stocks']):
        raise ValueError('Explicit finite audited history review required')
    raw=history._read(source/'result.json');audit_raw=history._read(source/'audit.json');binding_raw=history._read(source/'binding.json')
    if any(sha256(body).hexdigest()!=review[key] for body,key in ((raw,'history_sha256'),(audit_raw,'audit_sha256'),(binding_raw,'binding_sha256'))):
        raise ValueError('Original reviewed history metadata differs')
    manifest,audit,binding=map(json.loads,(raw,audit_raw,binding_raw))
    if (set(manifest['files'])!=set(review['compressed_files']) or binding['history_sha256']!=review['history_sha256']
            or binding['audit_sha256']!=review['audit_sha256'] or manifest['counters']['decisions']!=review['recommendations']):
        raise ValueError('Original history review and accounting coverage differ')
    history.validate_binding(binding,manifest,audit,current_sources=history.publication._sources(),cost_bps=cost_bps)
    files={};total=len(raw)+len(audit_raw)+len(binding_raw)
    for ticker,expected in manifest['files'].items():
        if not isinstance(ticker,str) or not ticker.isalnum() or ticker.upper()!=ticker:
            raise ValueError('Explicit original history stock required')
        compressed=history._read(source/(ticker+'.json.gz'))
        pin=review['compressed_files'][ticker]
        if len(compressed)!=pin['bytes'] or sha256(compressed).hexdigest()!=pin['sha256']:
            raise ValueError('Reviewed compressed history asset differs')
        with gzip.GzipFile(fileobj=io.BytesIO(compressed)) as stream:
            body=stream.read(history.MAX_FILE+1)
        total+=len(body)
        if (type(expected['bytes']) is not int or not 0<expected['bytes']<=history.MAX_FILE
                or len(body)!=expected['bytes'] or sha256(body).hexdigest()!=expected['sha256'] or total>history.MAX_TOTAL):
            raise ValueError('Original decompressed history exceeds its identity or finite bound')
        files[ticker]=body
    if sum(map(len,files.values()))!=review['raw_stock_bytes']:
        raise ValueError('Original raw history extent differs')
    return {'manifest':raw,'audit':audit_raw,'binding':binding,'files':files,'review':review}


# Replace only the selected metadata pointer with durable exact bytes, preserving every immutable history body.
def _select(path,raw):
    temporary=path.with_name('selection-'+uuid4().hex+'.tmp')
    try:
        if raw is None:
            path.unlink(missing_ok=True)
        else:
            with temporary.open('xb') as stream:
                stream.write(raw);stream.flush();os.fsync(stream.fileno())
            temporary.replace(path)
        descriptor=os.open(path.parent,os.O_RDONLY)
        try:os.fsync(descriptor)
        finally:os.close(descriptor)
    finally:
        temporary.unlink(missing_ok=True)


# Admit a completed original installation idempotently, but never adopt an incomplete namespace.
def _already_installed(root,prepared,selected):
    review=prepared['review'];folder=Path(root)/history.DIRECTORY/review['history_sha256']
    if not folder.exists():return False
    binding=json.dumps(prepared['binding'],sort_keys=True,allow_nan=False).encode()
    expected={'history_sha256':review['history_sha256'],'audit_sha256':review['audit_sha256'],'binding_sha256':sha256(binding).hexdigest()}
    if selected is None or json.loads(selected)!=expected:
        raise ValueError('Incomplete or unselected original history cannot be adopted')
    bodies={'manifest.json':prepared['manifest'],'audit.json':prepared['audit'],'binding.json':binding,
        **{ticker+'.json':body for ticker,body in prepared['files'].items()}}
    if folder.is_symlink() or set(path.name for path in folder.iterdir())!=set(bodies):
        raise ValueError('Completed original history namespace differs')
    for name,body in bodies.items():
        if history._read(folder/name)!=body:raise ValueError('Completed original history bytes differ')
    return True


# Install audited originals after approval, retaining a rollback receipt before changing any history selector.
def install(root,prepared,archive_dir):
    root=Path(root);now=datetime.now(UTC)
    _,config=history.learned_live_holding.read_configuration(root,now)
    if config['cost_bps']!=prepared['binding']['economic_parameters']['cost_bps']:
        raise ValueError('Installed history and approved costs differ')
    parent=root/history.DIRECTORY;parent.mkdir(mode=0o700,parents=True,exist_ok=True)
    pointer=parent/'latest.json';before=history._read(pointer) if pointer.exists() else None
    if _already_installed(root,prepared,before):
        return {'status':'ORIGINAL_HISTORY_ALREADY_INSTALLED','archive':None,'history_sha256':prepared['review']['history_sha256']}
    if before is not None:history.read(root,None,now)
    archive=Path(archive_dir)/(now.strftime('%Y%m%dT%H%M%S')+'-'+uuid4().hex);archive.mkdir(mode=0o700,parents=True)
    binding_raw=json.dumps(prepared['binding'],sort_keys=True,allow_nan=False).encode()
    after=json.dumps({'history_sha256':prepared['review']['history_sha256'],'audit_sha256':prepared['review']['audit_sha256'],
        'binding_sha256':sha256(binding_raw).hexdigest()},sort_keys=True).encode()
    receipt={'schema':SCHEMA,'root':str(root.resolve()),'before':base64.b64encode(before).decode() if before is not None else None,
        'after_sha256':sha256(after).hexdigest(),'history_sha256':prepared['review']['history_sha256']}
    with (archive/'receipt.json').open('x') as stream:
        json.dump(receipt,stream,sort_keys=True);stream.flush();os.fsync(stream.fileno())
    try:
        with TemporaryDirectory(prefix='original-strategy-history-') as temporary:
            source=Path(temporary)
            for name,body in {'result.json':prepared['manifest'],'audit.json':prepared['audit'],**{ticker+'.json':body for ticker,body in prepared['files'].items()}}.items():
                (source/name).write_bytes(body)
            history.import_original(root,source,prepared['binding'],manifest_sha256=prepared['review']['history_sha256'],
                audit_path=source/'audit.json',audit_sha256=prepared['review']['audit_sha256'])
        if history._read(pointer)!=after:raise ValueError('Installed original history selection differs')
        for ticker in prepared['files']:
            history.read(root,ticker,now)
    except Exception:
        current=history._read(pointer) if pointer.exists() else None
        if current==after:_select(pointer,before)
        elif current!=before:raise ValueError('Unknown history selection retained for inspection')
        raise
    return {'status':'ORIGINAL_AUDITED_HISTORY_INSTALLED','archive':str(archive.resolve()),'history_sha256':receipt['history_sha256'],
        'stocks':len(prepared['files']),'recommendations':prepared['review']['recommendations']}


# Restore the exact original selector on release rollback while retaining all original and failed history bodies.
def rollback(root,archive):
    root=Path(root);receipt=json.loads(history._read(Path(archive)/'receipt.json'))
    if receipt['schema']!=SCHEMA or receipt['root']!=str(root.resolve()):
        raise ValueError('Original history rollback identity differs')
    pointer=root/history.DIRECTORY/'latest.json'
    if sha256(history._read(pointer)).hexdigest()!=receipt['after_sha256']:
        raise ValueError('Original history rollback selector differs')
    before=base64.b64decode(receipt['before'],validate=True) if receipt['before'] is not None else None
    _select(pointer,before)
    return {'status':'ORIGINAL_HISTORY_SELECTION_RESTORED','history_sha256':receipt['history_sha256']}
