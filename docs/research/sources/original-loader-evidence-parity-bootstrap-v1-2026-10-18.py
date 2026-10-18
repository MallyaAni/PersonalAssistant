"""UNRUN synthetic parity: real new modules, explicitly isolated original references."""
import ast
import builtins
import copy
import gzip
import hashlib
import io
import json
import math
import os
import resource
import signal
import stat
import subprocess
import sys
import types
from collections.abc import Mapping
from pathlib import Path

AUDIT=Path('/audit')
OUT=Path('/out')
CHILDREN=[]
CASES={
 'primitives':[
  'json-values','json-duplicate','json-nested-duplicate','json-NaN','json-Infinity','json-negative-Infinity','json-overflow','json-malformed','json-trailing','json-bytearray',
  'file-empty','file-custom-exact-bound','file-hash','file-wrong-hash','file-over-bound','file-bool-bound','file-negative-bound','file-directory','digest-bool','digest-upper','digest-short','digest-nonhex','stable-growth','stable-replace',
  'freeze-values-alias-copy','freeze-dict-set','freeze-dict-delete','freeze-dict-update','freeze-dict-clear','freeze-dict-pop','freeze-dict-setdefault','freeze-dict-ior','freeze-list-set','freeze-list-delete','freeze-list-append','freeze-list-extend','freeze-list-insert','freeze-list-pop','freeze-list-remove','freeze-list-clear','freeze-list-reverse','freeze-list-sort','freeze-list-iadd','freeze-list-imul','freeze-reinitialization-noop','freeze-custom-unchanged','freeze-base-mutator-limit',
  'gzip-small','gzip-concatenated','gzip-malformed','gzip-truncated','gzip-unit-compressed-bound','gzip-unit-expanded-bound'],
 'adaptations':[
  'digest-finite-values','digest-readonly','digest-authenticated-synthetic-Rows','digest-refuse-nonfinite','digest-refuse-nonstr-key','digest-refuse-tuple','digest-refuse-custom-map','digest-refuse-numpy-float','digest-refuse-numpy-int','digest-refuse-numpy-bool','digest-refuse-nested-Rows',
  'chain-original-to-N2','chain-map-wrong','chain-map-type','chain-digest-wrong','chain-profile-wrong','catalog-wrong-count','catalog-wrong-container','catalog-wrong-first','catalog-wrong-second','catalog-wrong-third','catalog-reordered','catalog-duplicate','holding-byte','holding-type','chain-predecessor','chain-CURRENT-renewal']
}

# Identify complete source and exact observation bytes.
def sha(raw):
    return hashlib.sha256(raw).hexdigest()

# Persist one bounded new observation with fsync and exact readback.
def save(path,value):
    raw=json.dumps(value,sort_keys=True,indent=2,allow_nan=False).encode()+b'\n'
    assert len(raw)<=262144
    with path.open('xb') as output:output.write(raw);output.flush();os.fsync(output.fileno())
    assert path.read_bytes()==raw

# Authenticate the complete small application tree before real Python file imports.
def load():
    pins=json.loads((AUDIT/'pins.json').read_bytes())
    for name,item in pins.items():
        path=AUDIT/name;raw=path.read_bytes()
        assert len(raw)==item['bytes']<=262144 and sha(raw)==item['sha256']
    app=AUDIT/'app'
    assert {str(path.relative_to(app)) for path in app.rglob('*') if path.is_file()}=={name[4:] for name in pins if name.startswith('app/')}
    sys.path.insert(0,str(app))
    from backend.market import capacity_original_evidence_v1 as evidence
    from backend.market import capacity_original_archive_adaptations_v1 as adaptations
    from backend.market import original_history_json as streamed
    allowed={'backend','backend.market','backend.market.capacity_original_evidence_v1','backend.market.capacity_original_archive_adaptations_v1','backend.market.original_history_json'}
    assert {name for name in sys.modules if name=='backend' or name.startswith('backend.')}==allowed
    assert not any(name.startswith(('numpy','scipy','sklearn')) for name in sys.modules)
    origins={name:str(Path(sys.modules[name].__file__).resolve()) for name in sorted(allowed)}
    for name,path in origins.items():assert Path(path).is_relative_to(app)
    return evidence,adaptations,streamed,origins

# Construct function/class references from full original compilation in synthetic globals only.
def reference(streamed,*,numerical=False):
    paths={name:AUDIT/'reference'/name for name in (
      'backend/market/live_model_history_stream_audit.py','backend/market/live_model_history_pending_audit.py','backend/market/live_model_history_receipts.py','backend/market/live_policy_replay.py','backend/market/live_model_history_nightly_model.py','backend/market/live_model_history_binding.py')}
    compiled={name:compile(path.read_bytes(),str(path),'exec',dont_inherit=True) for name,path in paths.items()}
    ns={'__name__':'ISOLATED_SYNTHETIC_ORIGINAL_REFERENCE','__builtins__':builtins.__dict__,'ast':ast,'gzip':gzip,'io':io,'json':json,'math':math,'os':os,'stat':stat,'sha256':hashlib.sha256,'Path':Path,'streamed':streamed,'Mapping':Mapping,'MAX_METADATA_BYTES':16*1024**2,'HASH_CHUNK_BYTES':1024**2}
    # Bind only one exact function CodeType, never execute an original module body.
    def bind(name,origin):
        code=next(item for item in compiled[origin].co_consts if isinstance(item,types.CodeType) and item.co_name==name)
        fn=types.FunctionType(code,ns,name)
        if name=='pinned':fn.__kwdefaults__={'max_bytes':None}
        ns[name]=fn
        return fn
    receipts='backend/market/live_model_history_receipts.py'
    pending='backend/market/live_model_history_pending_audit.py'
    stream='backend/market/live_model_history_stream_audit.py'
    bind('require',receipts)
    for name in ('unique','reject_constant','finite_float'):bind(name,pending)
    ns['pending']=types.SimpleNamespace(**{name:ns[name] for name in ('unique','reject_constant','finite_float')},MAX_COMPRESSED_BYTES=64*1024**2,MAX_JSON_BYTES=256*1024**2)
    for name in ('expected_digest','file_identity','stable_file','pinned','authenticate_file','strict_json','_immutable','_freeze','archive_value'):bind(name,stream)
    for name,base in (('_ReadOnlyDict',dict),('_ReadOnlyList',list)):
        code=next(item for item in compiled[stream].co_consts if isinstance(item,types.CodeType) and item.co_name==name)
        ns[name]=builtins.__build_class__(types.FunctionType(code,ns),name,base)
    if numerical:
        native=Path('/usr/local/lib/python3.12/site-packages')
        assert native.is_dir() and native.resolve(strict=True)==native
        sys.path.append(str(native))
        import numpy as np
        assert Path(np.__file__).resolve().is_relative_to(native)
        ns['np']=np
        plain=bind('plain','backend/market/live_policy_replay.py')
        ns['live_policy_replay']=types.SimpleNamespace(plain=plain)
        serialized=bind('serialized','backend/market/live_model_history_nightly_model.py')
        ns['numerical']=types.SimpleNamespace(serialized=serialized)
        bind('digest',stream)
        binding='backend/market/live_model_history_binding.py'
        configuration=json.loads((AUDIT/'reference-config.json').read_bytes())
        ns.update(REVIEWS=tuple(configuration['review_paths']),REVIEW_SHA256=configuration['review_pins'],N2_SOURCE_SHA256=configuration['native31_compact_sha256'],__file__=str(paths[binding]),learned_live_holding=types.SimpleNamespace(__file__=str(AUDIT/'reference/backend/market/learned_live_holding.py')))
        for name in ('require_hash','guard_extension','review_catalog','original_profile','source_digests','metadata_renewal','reviewed_sources'):bind(name,binding)
    return types.SimpleNamespace(**ns)

# Record a required positive equality or an explicitly named first-boundary refusal.
def check(rows,name,left,right,*,error=None,new_error=None):
    observed=[]
    for action,expected in ((left,error),(right,error if new_error is None else new_error)):
        try:value=action()
        except Exception as caught:
            assert expected is not None and type(caught).__name__==expected[0] and str(caught)==expected[1],(name,type(caught).__name__,str(caught),expected)
            observed.append({'exception':type(caught).__name__,'reason':str(caught)})
        else:
            assert expected is None,(name,'EXPECTED_REFUSAL_ABSENT')
            raw=json.dumps(value,sort_keys=True,allow_nan=False).encode()
            observed.append({'value_sha256':sha(raw)})
    if error is None and new_error is None:assert observed[0]==observed[1],name
    rows.append({'case':name,'status':'PASS' if error is None and new_error is None else 'EXPECTED_REFUSAL','comparison_scope':'CANDIDATE_DOMAIN_REFUSAL_ONLY_REFERENCE_NOT_EXECUTED' if error is None and new_error is not None else 'ISOLATED_REFERENCE_PARITY','reference':observed[0],'candidate':observed[1]})

# Exercise only synthetic file/JSON/container primitives with explicit inherited limitations.
def primitives(target):
    new,adapt,streamed,origins=load();old=reference(streamed);rows=[]
    values=br'{"unicode":"\u00e9\ud83d\ude00","zero":-0.0,"tiny":1e-999,"big":123456789012345678901234567890,"list":[true,null,0.25]}'
    check(rows,'json-values',lambda:old.strict_json(values),lambda:new.strict_json(values))
    invalid=[('json-duplicate',b'{"a":1,"a":2}',('ValueError','Duplicate original pending evidence field')),('json-nested-duplicate',b'{"a":{"b":0,"b":1}}',('ValueError','Duplicate original pending evidence field')),('json-NaN',b'NaN',('ValueError','Nonfinite original pending JSON constant: NaN')),('json-Infinity',b'Infinity',('ValueError','Nonfinite original pending JSON constant: Infinity')),('json-negative-Infinity',b'-Infinity',('ValueError','Nonfinite original pending JSON constant: -Infinity')),('json-overflow',b'1e999',('ValueError','Nonfinite original pending JSON number'))]
    for name,raw,error in invalid:check(rows,name,lambda raw=raw:old.strict_json(raw),lambda raw=raw:new.strict_json(raw),error=error)
    for name,raw in (('json-malformed',b'{'),('json-trailing',b'0 1')):
        try:json.loads(raw)
        except json.JSONDecodeError as caught:error=('JSONDecodeError',str(caught))
        check(rows,name,lambda raw=raw:old.strict_json(raw),lambda raw=raw:new.strict_json(raw),error=error)
    check(rows,'json-bytearray',lambda:old.strict_json(bytearray(b'0')),lambda:new.strict_json(bytearray(b'0')),error=('ValueError','Immutable original JSON bytes required'))
    empty=target/'empty';empty.write_bytes(b'');path=target/'bytes';path.write_bytes(bytes(range(256)))
    check(rows,'file-empty',lambda:old.pinned(empty,sha(b'')).hex(),lambda:new.pinned(empty,sha(b'')).hex())
    check(rows,'file-custom-exact-bound',lambda:old.pinned(path,sha(path.read_bytes()),max_bytes=256).hex(),lambda:new.pinned(path,sha(path.read_bytes()),max_bytes=256).hex())
    check(rows,'file-hash',lambda:old.authenticate_file(path,sha(path.read_bytes())),lambda:new.authenticate_file(path,sha(path.read_bytes())))
    check(rows,'file-wrong-hash',lambda:old.authenticate_file(path,'0'*64),lambda:new.authenticate_file(path,'0'*64),error=('ValueError','Pinned stream input bytes differ'))
    for name,bound,reason in (('file-over-bound',255,'Original metadata size exceeds bound'),('file-bool-bound',True,'Exact evidence size bound required'),('file-negative-bound',-1,'Exact evidence size bound required')):
        check(rows,name,lambda bound=bound:old.pinned(path,sha(path.read_bytes()),max_bytes=bound),lambda bound=bound:new.pinned(path,sha(path.read_bytes()),max_bytes=bound),error=('ValueError',reason))
    check(rows,'file-directory',lambda:old.authenticate_file(target,'0'*64),lambda:new.authenticate_file(target,'0'*64),error=('ValueError','Regular original evidence file required'))
    for name,value in (('digest-bool',True),('digest-upper','A'*64),('digest-short','a'*63),('digest-nonhex','z'*64)):
        check(rows,name,lambda value=value:old.expected_digest(value),lambda value=value:new.expected_digest(value),error=('ValueError','External original evidence digest required'))
    # Make actual file changes under synthetic output, not a patched filesystem observation.
    def changed(module,kind):
        sample=target/(kind+'-'+module.__name__);sample.write_bytes(b'x')
        with sample.open('rb') as held:
            before=module.file_identity(os.fstat(held.fileno()))
            if kind=='growth':
                with sample.open('ab') as writer:writer.write(b'y');writer.flush();os.fsync(writer.fileno())
            else:
                other=sample.with_suffix('.replacement');other.write_bytes(b'y');os.replace(other,sample)
            module.stable_file(held,sample,before)
    for kind in ('growth','replace'):check(rows,'stable-'+kind,lambda kind=kind:changed(old,kind),lambda kind=kind:changed(new,kind),error=('ValueError','Original evidence changed during authentication'))
    # Check parsed JSON alias separation and ordinary deepcopy identity without claiming hostile-code isolation.
    def freezing(module):
        original={'a':[{'b':1}],'z':-0.0};frozen=module._freeze(original);original['a'][0]['b']=2
        assert frozen['a'][0]['b']==1 and copy.deepcopy(frozen) is frozen
        return frozen
    check(rows,'freeze-values-alias-copy',lambda:freezing(old),lambda:freezing(new))
    dict_actions={'set':lambda x:x.__setitem__('x',2),'delete':lambda x:x.__delitem__('a'),'update':lambda x:x.update(x=2),'clear':lambda x:x.clear(),'pop':lambda x:x.pop('a'),'setdefault':lambda x:x.setdefault('x',2),'ior':lambda x:x.__ior__({'x':2})}
    for name,action in dict_actions.items():check(rows,'freeze-dict-'+name,lambda action=action:action(old._freeze({'a':1})),lambda action=action:action(new._freeze({'a':1})),error=('TypeError','Admitted original metadata is readonly'))
    list_actions={'set':lambda x:x.__setitem__(0,2),'delete':lambda x:x.__delitem__(0),'append':lambda x:x.append(2),'extend':lambda x:x.extend([2]),'insert':lambda x:x.insert(0,2),'pop':lambda x:x.pop(),'remove':lambda x:x.remove(1),'clear':lambda x:x.clear(),'reverse':lambda x:x.reverse(),'sort':lambda x:x.sort(),'iadd':lambda x:x.__iadd__([2]),'imul':lambda x:x.__imul__(2)}
    for name,action in list_actions.items():check(rows,'freeze-list-'+name,lambda action=action:action(old._freeze([1])),lambda action=action:action(new._freeze([1])),error=('TypeError','Admitted original metadata is readonly'))
    # Reinitialization is intentionally a no-op and base mutators remain an inherited limitation.
    def reinitialize(module):
        value=module._freeze({'a':[1]});identity=id(value);value.__init__({'x':2});value['a'].__init__([3]);assert id(value)==identity
        return value
    check(rows,'freeze-reinitialization-noop',lambda:reinitialize(old),lambda:reinitialize(new))
    custom=types.SimpleNamespace(value=[])
    check(rows,'freeze-custom-unchanged',lambda:old._freeze(custom) is custom,lambda:new._freeze(custom) is custom)
    # Demonstrate rather than conceal the unchanged low-level base-mutator bypass.
    def bypass(module):
        value=module._freeze({'a':1});dict.__setitem__(value,'a',2);return value
    check(rows,'freeze-base-mutator-limit',lambda:bypass(old),lambda:bypass(new))
    for name,raw in (('gzip-small',gzip.compress(b'{"a":1}',mtime=0)),('gzip-concatenated',gzip.compress(b'{"a":',mtime=0)+gzip.compress(b'1}',mtime=0))):check(rows,name,lambda raw=raw:old.archive_value(raw),lambda raw=raw:new.archive_value(raw))
    for name,raw,error in (('gzip-malformed',b'xx',('BadGzipFile',"Not a gzipped file (b'xx')")),('gzip-truncated',gzip.compress(b'{}',mtime=0)[:-3],('EOFError','Compressed file ended before the end-of-stream marker was reached'))):check(rows,name,lambda raw=raw:old.archive_value(raw),lambda raw=raw:new.archive_value(raw),error=error)
    # Explicitly injected smaller UNIT bounds cover refusal paths, never default-cap or RAM acceptance.
    def unit_bound(module,expanded):
        namespace=module.pending if module is old else module
        name='MAX_JSON_BYTES' if expanded else 'MAX_COMPRESSED_BYTES';before=getattr(namespace,name);setattr(namespace,name,1)
        try:return module.archive_value(gzip.compress(b'{}',mtime=0))
        finally:setattr(namespace,name,before)
    for name,expanded,reason in (('gzip-unit-compressed-bound',False,'Original stream archive too large'),('gzip-unit-expanded-bound',True,'Original stream expansion too large')):check(rows,name,lambda expanded=expanded:unit_bound(old,expanded),lambda expanded=expanded:unit_bound(new,expanded),error=('ValueError',reason))
    assert [row['case'] for row in rows]==CASES['primitives']
    save(target/'result.json',{'scope':'SYNTHETIC_PRIMITIVE_PARITY_ONLY','cases':rows,'module_origins':origins,'reference':'FULL_COMPILATION_ISOLATED_SYNTHETIC_GLOBALS_NO_ORIGINAL_MODULE_EXEC','injected_unit_gzip_bounds':True,'genuine_acceptance':False})

# Compare finite-control digest and original catalog transitions without original module imports.
def adaptations(target):
    evidence,new,streamed,origins=load();old=reference(streamed,numerical=True);rows=[]
    values={'z':-0.0,'unicode':'é😀','tiny':0.0,'big':123456789012345678901234567890,'history':[],'list':[True,None,0.25]}
    check(rows,'digest-finite-values',lambda:old.digest(values),lambda:new.logical_digest(values))
    check(rows,'digest-readonly',lambda:old.digest(old._freeze(values)),lambda:new.logical_digest(evidence._freeze(values)))
    source=target/'synthetic.json';raw=json.dumps({'history':[{'n':0,'x':-0.0},{'n':1,'x':'é'},{'n':2,'x':None}],'control':True},sort_keys=True).encode();source.write_bytes(raw)
    scratch=target/'spool';scratch.mkdir()
    parsed=streamed.read(source,sha(raw),directory=scratch)
    assert type(parsed['history']) is streamed.Rows and len(parsed['history'])==3
    try:
        check(rows,'digest-authenticated-synthetic-Rows',lambda:old.digest(parsed),lambda:new.logical_digest(parsed))
        np=old.np
        controls=[('digest-refuse-nonfinite',{'x':float('nan')},'FINITE_DECODED_CONTROLS_REQUIRED'),('digest-refuse-nonstr-key',{1:0},'FINITE_STRING_KEY_CONTROLS_REQUIRED'),('digest-refuse-tuple',(1,),'FINITE_DECODED_CONTROLS_REQUIRED'),('digest-refuse-custom-map',types.MappingProxyType({'x':1}),'FINITE_DECODED_CONTROLS_REQUIRED'),('digest-refuse-numpy-float',np.float64(1),'FINITE_DECODED_CONTROLS_REQUIRED'),('digest-refuse-numpy-int',np.int64(1),'FINITE_DECODED_CONTROLS_REQUIRED'),('digest-refuse-numpy-bool',np.bool_(True),'FINITE_DECODED_CONTROLS_REQUIRED'),('digest-refuse-nested-Rows',{'x':parsed['history']},'FINITE_DECODED_CONTROLS_REQUIRED')]
        for name,value,reason in controls:
            # Narrow-domain refusals are not parity over the original more permissive domain.
            check(rows,name,lambda:None,lambda value=value:new.logical_digest(value),new_error=('ValueError',reason))
    finally:streamed.release(parsed)
    assert not any(scratch.iterdir()),'SYNTHETIC_SPOOL_NOT_RELEASED'
    n2=json.loads((AUDIT/'native31.json').read_bytes());configuration=json.loads((AUDIT/'reference-config.json').read_bytes())
    review_bytes=tuple((AUDIT/'reference'/name).read_bytes() for name in configuration['review_paths'])
    original=dict(n2);original.pop('backend/market/live_model_decision.py');first=json.loads(review_bytes[0]);second=json.loads(review_bytes[1])
    original['backend/api/v1/market.py']=first['previous_approved_sha256'];original['backend/market/learned_live_holding.py']=second['source_changes']['backend/market/learned_live_holding.py']['before_sha256']
    holding=(AUDIT/'reference/backend/market/learned_live_holding.py').read_bytes()
    # Compare the exact selected transitions on an explicitly reconstructed SYNTHETIC predecessor.
    def reference_chain():
        old.reviewed_sources(original,n2,list(new.REVIEWS));return {'schema':new.SCHEMA,'reviews':list(new.REVIEWS),'source_count':31,'native31_compact_sha256':new.N2,'source_reader_authenticated':False}
    check(rows,'chain-original-to-N2',reference_chain,lambda:new.reviewed_n2_sources(original,n2,review_bytes,holding))
    wrong=dict(n2);wrong[next(iter(wrong))]='0'*64
    bad_digest=dict(original);bad_digest[next(iter(bad_digest))]='bad'
    invalid=[('chain-map-wrong',lambda:new.reviewed_n2_sources(original,wrong,review_bytes,holding),'EXACT_N2_NATIVE31_MAP_REQUIRED'),('chain-map-type',lambda:new.reviewed_n2_sources(original,[],review_bytes,holding),'EXACT_SOURCE_MAP_REQUIRED'),('chain-digest-wrong',lambda:new.reviewed_n2_sources(bad_digest,n2,review_bytes,holding),'External original evidence digest required'),('chain-profile-wrong',lambda:new.reviewed_n2_sources({},n2,review_bytes,holding),'EXACT_ORIGINAL_SOURCE_PROFILE_REQUIRED'),('catalog-wrong-count',lambda:new.review_catalog(review_bytes[:2]),'EXACT_ORIGINAL_THREE_ENTRY_CATALOG_REQUIRED'),('catalog-wrong-container',lambda:new.review_catalog(list(review_bytes)),'EXACT_ORIGINAL_THREE_ENTRY_CATALOG_REQUIRED')]
    for name,action,reason in invalid:check(rows,name,lambda:None,action,new_error=('ValueError',reason))
    for index,name in enumerate(('catalog-wrong-first','catalog-wrong-second','catalog-wrong-third')):
        changed=list(review_bytes);changed[index]+=b' '
        check(rows,name,lambda:None,lambda changed=changed:new.review_catalog(tuple(changed)),new_error=('ValueError','EXACT_ORIGINAL_REVIEW_BYTES_REQUIRED'))
    for name,value in (('catalog-reordered',tuple(reversed(review_bytes))),('catalog-duplicate',(review_bytes[0],review_bytes[0],review_bytes[2]))):check(rows,name,lambda:None,lambda value=value:new.review_catalog(value),new_error=('ValueError','EXACT_ORIGINAL_REVIEW_BYTES_REQUIRED'))
    for name,value in (('holding-byte',holding+b' '),('holding-type',bytearray(holding))):check(rows,name,lambda:None,lambda value=value:new.reviewed_n2_sources(original,n2,review_bytes,value),new_error=('ValueError','EXACT_N2_HOLDING_SOURCE_BYTES_REQUIRED'))
    changed=dict(original);changed['backend/api/v1/market.py']='0'*64
    check(rows,'chain-predecessor',lambda:old.reviewed_sources(changed,n2,list(new.REVIEWS)),lambda:new.reviewed_n2_sources(changed,n2,review_bytes,holding),error=('ValueError','Unreviewed historical-to-serving trading source change'))
    renewal=json.loads(review_bytes[2])['source_changes']['backend/agents/trading/desk/paper.py']
    assert renewal['before_sha256']==n2['backend/agents/trading/desk/paper.py']
    current=dict(n2);current['backend/agents/trading/desk/paper.py']=renewal['after_sha256']
    check(rows,'chain-CURRENT-renewal',lambda:None,lambda:new.reviewed_n2_sources(original,current,review_bytes,holding),new_error=('ValueError','EXACT_N2_NATIVE31_MAP_REQUIRED'))
    assert [row['case'] for row in rows]==CASES['adaptations']
    save(target/'result.json',{'scope':'SYNTHETIC_FINITE_DIGEST_AND_THREE_CATALOG_TWO_TRANSITION_ONLY','cases':rows,'module_origins':origins,'reference':'FULL_COMPILATION_ISOLATED_SYNTHETIC_GLOBALS_REAL_NUMPY_FOR_ORIGINAL_PLAIN_ONLY','reconstructed_original30_is_synthetic':True,'Rows_source':'THREE_SYNTHETIC_ROWS_ACTUAL_STRICT_READER','spool_released':True,'genuine_acceptance':False})

# Bound each child CPU and each output file independently of model or daemon memory.
def limits():
    resource.setrlimit(resource.RLIMIT_CPU,(15,15));resource.setrlimit(resource.RLIMIT_FSIZE,(262144,262144))

# Raise a real finite parent deadline while preserving owned-child cleanup.
def alarm(signum,frame):
    raise KeyboardInterrupt('EVIDENCE_PARITY_PARENT_DEADLINE')

# Run precisely two fresh parity children, retaining every exit and complete case inventory.
def diagnose():
    assert os.getuid()==1000 and list(OUT.iterdir())==[]
    signal.signal(signal.SIGALRM,alarm);signal.setitimer(signal.ITIMER_REAL,55)
    try:
        for mode in ('primitives','adaptations'):
            target=OUT/mode;target.mkdir(mode=0o700)
            stdout=(target/'stdout.log').open('xb');stderr=(target/'stderr.log').open('xb');process=None;stopped=None
            try:
                prior=signal.pthread_sigmask(signal.SIG_BLOCK,{signal.SIGALRM})
                try:
                    environment={**os.environ,**{name:'1' for name in ('OPENBLAS_NUM_THREADS','OMP_NUM_THREADS','MKL_NUM_THREADS','NUMEXPR_NUM_THREADS','VECLIB_MAXIMUM_THREADS','BLIS_NUM_THREADS')}}
                    process=subprocess.Popen([sys.executable,'-I','-S','-B',str(Path(__file__)),mode,str(target)],stdin=subprocess.DEVNULL,stdout=stdout,stderr=stderr,preexec_fn=limits,env=environment);CHILDREN.append(process)
                finally:signal.pthread_sigmask(signal.SIG_SETMASK,prior)
                process.wait(timeout=20)
            finally:
                if process is not None and process.poll() is None:
                    stopped='TERM';process.terminate()
                    try:process.wait(timeout=1)
                    except subprocess.TimeoutExpired:stopped='KILL';process.kill();process.wait(timeout=1)
                for output in (stdout,stderr):output.flush();os.fsync(output.fileno());output.close()
                save(target/'exit.json',{'pid':None if process is None else str(process.pid),'exit':None if process is None else process.returncode,'owned_stop':stopped})
            assert process.returncode==0 and stopped is None and (target/'stdout.log').read_bytes()==(target/'stderr.log').read_bytes()==b''
            value=json.loads((target/'result.json').read_bytes());assert [row['case'] for row in value['cases']]==CASES[mode]
        save(OUT/'comparison.json',{'status':'EVIDENCE_PARITY_REQUIRES_INDEPENDENT_REVIEW','children':2,'cases':sum(map(len,CASES.values())),'genuine_acceptance':False})
    finally:
        signal.setitimer(signal.ITIMER_REAL,0)
        for process in CHILDREN:
            if process.poll() is None:
                process.terminate()
                try:process.wait(timeout=1)
                except subprocess.TimeoutExpired:process.kill();process.wait(timeout=1)

if __name__=='__main__':
    if sys.argv[1:]==['diagnose']:diagnose()
    elif len(sys.argv)==3 and sys.argv[1] in CASES:{'primitives':primitives,'adaptations':adaptations}[sys.argv[1]](Path(sys.argv[2]))
    else:raise SystemExit('SOURCE_ONLY_NO_EVIDENCE_PARITY_INVOCATION')
