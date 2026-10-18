"""Readonly source/native/terminal folds; never execute a parity or probe body."""
import ast
import hashlib
import json
import os
import signal
import socket
import sys
import time
import types
from pathlib import Path

BASE=Path('/home/animallya96/scratch')
SOURCE=BASE/'capacity-evidence-parity-source-20261018-v1'
RUN=BASE/'capacity-evidence-parity-20261018-v1'
PRE=BASE/'capacity-evidence-parity-prerequisites-20261018-v1'
FINAL=BASE/'capacity-evidence-parity-independent-review-20261018-v1'
TRANSFER=BASE/'capacity-evidence-parity-transfer-20261018-v1'
NATIVE=BASE/'capacity-evidence-native-probe-20261018-v1'
NATIVE_REVIEW=BASE/'capacity-evidence-native-probe-review-20261018-v1'
BOOK='9cffe5361488307afd63123a4a79ef8b92ec2da53f629c1521734c2d3217b502'
PACKET='edac83ca50254771cec2d79bb7e2d562b43bc1578e8fbeaa81730b2b21ad3fd2'
IMAGE='sha256:e0a54c1f3b293c241ea0eae767d8ba017d0e1a05679965935b336910faa63237'
HELPER=BASE/'n2-loader-guard-source-20261018-v2/owner/verifier.py'
PROBE=BASE/'n2-loader-guard-transfer-20261018-v2/prerequisites.py'
POSITIVES={'json-values','file-empty','file-custom-exact-bound','file-hash','freeze-values-alias-copy','freeze-reinitialization-noop','freeze-custom-unchanged','freeze-base-mutator-limit','gzip-small','gzip-concatenated','digest-finite-values','digest-readonly','digest-authenticated-synthetic-Rows','chain-original-to-N2'}
DOMAIN_REASONS={
 'digest-refuse-nonfinite':'FINITE_DECODED_CONTROLS_REQUIRED','digest-refuse-nonstr-key':'FINITE_STRING_KEY_CONTROLS_REQUIRED',
 **{name:'FINITE_DECODED_CONTROLS_REQUIRED' for name in ('digest-refuse-tuple','digest-refuse-custom-map','digest-refuse-numpy-float','digest-refuse-numpy-int','digest-refuse-numpy-bool','digest-refuse-nested-Rows')},
 'chain-map-wrong':'EXACT_N2_NATIVE31_MAP_REQUIRED','chain-map-type':'EXACT_SOURCE_MAP_REQUIRED','chain-digest-wrong':'External original evidence digest required','chain-profile-wrong':'EXACT_ORIGINAL_SOURCE_PROFILE_REQUIRED',
 'catalog-wrong-count':'EXACT_ORIGINAL_THREE_ENTRY_CATALOG_REQUIRED','catalog-wrong-container':'EXACT_ORIGINAL_THREE_ENTRY_CATALOG_REQUIRED',
 **{name:'EXACT_ORIGINAL_REVIEW_BYTES_REQUIRED' for name in ('catalog-wrong-first','catalog-wrong-second','catalog-wrong-third','catalog-reordered','catalog-duplicate')},
 'holding-byte':'EXACT_N2_HOLDING_SOURCE_BYTES_REQUIRED','holding-type':'EXACT_N2_HOLDING_SOURCE_BYTES_REQUIRED','chain-CURRENT-renewal':'EXACT_N2_NATIVE31_MAP_REQUIRED'}

# Authenticate a bounded utility source without invoking any old entry point.
def library(path,expected):
    raw=path.read_bytes();assert len(raw)<=262144 and hashlib.sha256(raw).hexdigest()==expected
    value=types.ModuleType('parity_readonly_'+path.stem);value.__file__=str(path)
    exec(compile(raw,str(path),'exec',dont_inherit=True),value.__dict__)
    return value

# Write one new bounded independent observation with durable exact readback.
def save(path,value):
    raw=json.dumps(value,sort_keys=True,indent=2,allow_nan=False).encode()+b'\n';assert len(raw)<=262144
    with path.open('xb') as output:output.write(raw);output.flush();os.fsync(output.fileno())
    assert path.read_bytes()==raw
    descriptor=os.open(path.parent,os.O_RDONLY|os.O_DIRECTORY)
    try:os.fsync(descriptor)
    finally:os.close(descriptor)
    return {'sha256':hashlib.sha256(raw).hexdigest(),'bytes':len(raw)}

# Verify all22 staged source records and their original full physical identities.
def source_fold(reader):
    physical,bodies=reader.capture(SOURCE)
    stage=reader.metadata(bodies['stage-proof.json']);book=reader.metadata(bodies['source-book.json'])
    assert stage['schema']=='capacity-evidence-parity-stage-proof/1' and stage['packet_sha256']==PACKET and stage['source_book_sha256']==BOOK and len(stage['files'])==23
    assert reader.sha(bodies['source-book.json'])==BOOK and book['schema']=='capacity-evidence-parity-source/1' and len(book['files'])==22
    assert set(stage['files'])==set(book['files'])|{'source-book.json'}
    for name,item in stage['files'].items():assert physical[name]==item
    for name,item in book['files'].items():assert item=={key:physical[name][key] for key in ('sha256','bytes')}
    tree=ast.parse(bodies['audit/bootstrap.py'])
    cases=ast.literal_eval(next(node.value for node in tree.body if isinstance(node,ast.Assign) and any(isinstance(target,ast.Name) and target.id=='CASES' for target in node.targets)))
    assert [len(cases[mode]) for mode in ('primitives','adaptations')]==[53,27] and len(set(sum(cases.values(),[])))==80
    return physical,bodies,stage,book,cases

# Read fresh actual image/jobs/headroom and prove exclusive future roots are absent.
def prerequisites(reader):
    PRE.mkdir(mode=0o700,exist_ok=False)
    before,bodies,stage,book,cases=source_fold(reader);assert set(before)==set(stage['files'])|{'stage-proof.json'}
    probe=library(PROBE,'9576b475e00ff34ba89e2a2bf2036e8a4e939ad7b540cebf0b60ef0741d168a4')
    code,jobs,error=probe.query(PRE,'jobs',['ps','--filter','label=anios.synthetic.guard-owner','--format','{{json .}}']);assert code==0 and jobs==error==b''
    code,raw,error=probe.query(PRE,'image',['image','inspect',IMAGE]);image=reader.metadata(raw)
    assert code==0 and not error and len(image)==1 and image[0]['Id']==IMAGE and image[0]['Os']=='linux' and image[0]['Architecture']=='arm64'
    save(PRE/'runtime-image.json',image)
    memory=dict(line.split(':',1) for line in Path('/proc/meminfo').read_text().splitlines());disk=os.statvfs(SOURCE)
    resources={'host':socket.gethostname(),'uid':os.getuid(),'observed_at_ns':str(time.time_ns()),'MemAvailable_bytes':str(int(memory['MemAvailable'].split()[0])*1024),'scratch_available_bytes':str(disk.f_bavail*disk.f_frsize),'scratch_inodes_available':str(disk.f_favail),'targets':{str(path):os.path.lexists(path) for path in (RUN,FINAL,NATIVE,NATIVE_REVIEW)},'reservation':False}
    assert resources['host']=='animallya-spark1' and resources['uid']==1000 and not any(resources['targets'].values())
    assert int(resources['MemAvailable_bytes'])>=5*1024**3 and int(resources['scratch_available_bytes'])>=4*1024**3 and int(resources['scratch_inodes_available'])>=8192
    assert source_fold(reader)[0]==before
    result={'schema':'capacity-evidence-parity-prerequisites/1','status':'VERIFIED_SOURCE_IMAGE_HOST_ONLY_NATIVE_AND_PARITY_UNRUN','source_physical':before,'resources':resources,'image_raw_sha256':reader.sha(raw),'source_book_sha256':BOOK,'packet_sha256':PACKET,'active_labelled_jobs':[],'native_or_parity_runtime_created':False}
    print(json.dumps({'proof':save(PRE/'proof.json',result),'resources':resources},sort_keys=True))

# Check created/stopped/fresh isolation and complete unique mount records for one owned CID.
def runtime(reader,root,review,cid,review_sha,audit):
    physical,bodies=reader.capture(root)
    created=reader.metadata(bodies['prepare-before.json']);stopped=reader.metadata(bodies['prepare-after.json'])
    row,inspect_sha=reader.inspect_owned(cid,review,0)
    label=reader.sha((str(root)+':'+review_sha).encode());name='n2-guard-'+label[:20]+'-prepare'
    binds=[(str(audit),'/audit',False),(str(root/'output'),'/out',True)]
    reader.runtime(created,name,label,binds,['diagnose'],stopped=False);reader.runtime(row,name,label,binds,['diagnose'],stopped=True)
    assert row['Id']==created['Id']==stopped['Id'] and row['State']==stopped['State'] and row['Config']==created['Config']==stopped['Config']
    assert {key:value for key,value in row.items() if key!='Mounts'}=={key:value for key,value in stopped.items() if key!='Mounts'}
    mount_maps=[]
    for observation in (created,stopped,row):
        assert len(observation['Mounts'])==len({item['Destination'] for item in observation['Mounts']})==2
        mount_maps.append({item['Destination']:item for item in observation['Mounts']})
    assert mount_maps[0]==mount_maps[1]==mount_maps[2]
    assert set(created['HostConfig'])==set(stopped['HostConfig'])
    differences={key:[created['HostConfig'][key],stopped['HostConfig'][key]] for key in created['HostConfig'] if created['HostConfig'][key]!=stopped['HostConfig'][key]}
    assert differences in ({},{'OomKillDisable':[False,None]})
    return physical,bodies,row,inspect_sha,differences

# Fold a separately admitted NumPy-only probe without executing it or any parity body.
def native(reader):
    NATIVE_REVIEW.mkdir(mode=0o700,exist_ok=False)
    _,raws=reader.capture(NATIVE);term=reader.metadata(raws['terminal.json'])
    assert term['status']=='NATIVE_NUMPY_METADATA_ONLY_NOT_PARITY_ACCEPTANCE'
    files,bodies,row,inspection,differences=runtime(reader,NATIVE,NATIVE_REVIEW,term['cid'],term['review_sha256'],TRANSFER/'native-audit')
    native_physical,native_bodies=reader.capture(TRANSFER/'native-audit')
    assert set(native_physical)=={'bootstrap.py'} and native_physical['bootstrap.py']['sha256']=='ac6d0696a658f5da3b219b8eac548831450a9021ec81d4241ee4e01912e4440a'
    assert term['review_sha256']==reader.sha(b'NUMPY_METADATA_ONLY\0'+native_bodies['bootstrap.py'])
    assert reader.metadata(bodies['source-before.json'])==reader.metadata(bodies['source-after.json'])==native_physical['bootstrap.py']['physical']
    admission_raw=(TRANSFER/'native-admission/admission.json').read_bytes()
    assert reader.sha(admission_raw)==term['admission_sha256'] and reader.metadata(admission_raw)['scope']=='NUMPY_IMPORT_METADATA_ONLY'
    facts=reader.metadata(bodies['output/native.json'])
    assert facts['scope']=='NUMPY_IMPORT_METADATA_ONLY_NO_MODEL_OR_APP' and facts['uid']==1000 and facts['python'].startswith('3.12.')
    assert facts['numpy_file']=='/usr/local/lib/python3.12/site-packages/numpy/__init__.py' and type(facts['numpy_version']) is str and facts['numpy_version']
    assert facts['backend_modules']==[] and len(facts['numpy_init_sha256'])==64 and facts['thread_limits']=={name:'1' for name in ('OPENBLAS_NUM_THREADS','OMP_NUM_THREADS','MKL_NUM_THREADS','NUMEXPR_NUM_THREADS','VECLIB_MAXIMUM_THREADS','BLIS_NUM_THREADS')}
    assert reader.capture(NATIVE)[0]==files and reader.capture(TRANSFER/'native-audit')[0]==native_physical
    result={'schema':'capacity-evidence-native-independent/1','status':'VERIFIED_NATIVE_IMPORT_METADATA_ONLY','cid':row['Id'],'finished':row['State']['FinishedAt'],'facts':facts,'inspect_sha256':inspection,'files':files,'native_source_physical':native_physical,'created_stopped_HostConfig_differences':differences,'parity_or_genuine_acceptance':False}
    print(json.dumps({'proof':save(NATIVE_REVIEW/'proof.json',result),'facts':facts},sort_keys=True))

# Derive the exact common-refusal reason from the separately reviewed finite case specification.
def common_reason(name):
    if name.startswith('freeze-'):return ('TypeError','Admitted original metadata is readonly')
    if name.startswith('digest-'):return ('ValueError','External original evidence digest required')
    mapping={
      'json-duplicate':('ValueError','Duplicate original pending evidence field'),'json-nested-duplicate':('ValueError','Duplicate original pending evidence field'),
      'json-overflow':('ValueError','Nonfinite original pending JSON number'),'json-bytearray':('ValueError','Immutable original JSON bytes required'),
      'file-wrong-hash':('ValueError','Pinned stream input bytes differ'),'file-over-bound':('ValueError','Original metadata size exceeds bound'),'file-bool-bound':('ValueError','Exact evidence size bound required'),'file-negative-bound':('ValueError','Exact evidence size bound required'),'file-directory':('ValueError','Regular original evidence file required'),
      'stable-growth':('ValueError','Original evidence changed during authentication'),'stable-replace':('ValueError','Original evidence changed during authentication'),
      'gzip-malformed':('BadGzipFile',"Not a gzipped file (b'xx')"),'gzip-truncated':('EOFError','Compressed file ended before the end-of-stream marker was reached'),'gzip-unit-compressed-bound':('ValueError','Original stream archive too large'),'gzip-unit-expanded-bound':('ValueError','Original stream expansion too large'),'chain-predecessor':('ValueError','Unreviewed historical-to-serving trading source change')}
    if name in ('json-NaN','json-Infinity','json-negative-Infinity'):return ('ValueError','Nonfinite original pending JSON constant: '+{'json-NaN':'NaN','json-Infinity':'Infinity','json-negative-Infinity':'-Infinity'}[name])
    if name in ('json-malformed','json-trailing'):
        try:json.loads(b'{' if name=='json-malformed' else b'0 1')
        except json.JSONDecodeError as error:return ('JSONDecodeError',str(error))
    return mapping[name]

# Independently require every exact named result, child exit and source/runtime bookend.
def terminal(reader):
    FINAL.mkdir(mode=0o700,exist_ok=False)
    sources,source,stage,book,cases=source_fold(reader)
    _,initial=reader.capture(RUN);term=reader.metadata(initial['terminal.json'])
    assert term['status']=='CAPACITY_EVIDENCE_PARITY_REQUIRES_INDEPENDENT_REVIEW' and term['source_book_sha256']==BOOK and term['genuine_acceptance'] is False
    files,bodies,row,inspection,differences=runtime(reader,RUN,FINAL,term['cid'],BOOK,SOURCE/'audit')
    assert reader.metadata(bodies['source-before.json'])==reader.metadata(bodies['source-after.json'])=={name:sources[name] for name in book['files']}
    assert term['comparison_sha256']==reader.sha(bodies['output/comparison.json'])
    admission=reader.metadata(source['admission/admission.json']);assert reader.sha(source['admission/admission.json'])==term['admission_sha256'] and admission['scope']=='SYNTHETIC_EVIDENCE_AND_ARCHIVE_PARITY_ONLY' and admission['genuine_execution_authorized'] is False
    binding=reader.metadata(source['admission/launch-binding.json'])
    native_raw=(NATIVE_REVIEW/'proof.json').read_bytes();assert reader.sha(native_raw)==binding['native_proof_sha256'] and reader.metadata(native_raw)['status']=='VERIFIED_NATIVE_IMPORT_METADATA_ONLY'
    invocation=reader.metadata(source['owner/caller-invocation.json'])
    assert invocation['argv']==['--admitted-evidence-parity',term['admission_sha256'],'3514a6f4d9bfd6be699d0eab6d1b33f6c4e6974b59b94f3734f9f47fa16e36ff',BOOK]
    assert binding['caller_arguments']==['--call-admitted-evidence-parity',invocation['owner_sha256'],BOOK,term['admission_sha256']] and invocation['caller_sha256']==binding['caller_sha256']=='024a4e1e12891c902206e5597d8bcb8a1bb03ba56e7f395fd68b0b90151bc354'
    children=[];counts={'positive':0,'reference_refusal':0,'candidate_domain_refusal':0}
    for mode in ('primitives','adaptations'):
        prefix='output/'+mode+'/'
        value=reader.metadata(bodies[prefix+'result.json']);child=reader.metadata(bodies[prefix+'exit.json'])
        assert child['exit']==0 and child['owned_stop'] is None and int(child['pid'])>1 and bodies[prefix+'stdout.log']==bodies[prefix+'stderr.log']==b''
        assert [item['case'] for item in value['cases']]==cases[mode] and value['genuine_acceptance'] is False
        expected_origins={name:'/audit/app/'+name.replace('.','/')+('/__init__.py' if name in ('backend','backend.market') else '.py') for name in ('backend','backend.market','backend.market.capacity_original_evidence_v1','backend.market.capacity_original_archive_adaptations_v1','backend.market.original_history_json')}
        assert value['module_origins']==expected_origins
        for outcome in value['cases']:
            assert set(outcome)=={'case','status','comparison_scope','reference','candidate'}
            name=outcome['case'];left=outcome['reference'];right=outcome['candidate']
            if name in POSITIVES:
                assert outcome['status']=='PASS' and outcome['comparison_scope']=='ISOLATED_REFERENCE_PARITY' and left==right and set(left)=={'value_sha256'} and len(left['value_sha256'])==64;counts['positive']+=1
            elif name in DOMAIN_REASONS:
                assert outcome['status']=='EXPECTED_REFUSAL' and outcome['comparison_scope']=='CANDIDATE_DOMAIN_REFUSAL_ONLY_REFERENCE_NOT_EXECUTED' and left=={'value_sha256':reader.sha(b'null')} and right=={'exception':'ValueError','reason':DOMAIN_REASONS[name]};counts['candidate_domain_refusal']+=1
            else:
                kind,reason=common_reason(name)
                assert outcome['status']=='EXPECTED_REFUSAL' and outcome['comparison_scope']=='ISOLATED_REFERENCE_PARITY' and left==right=={'exception':kind,'reason':reason};counts['reference_refusal']+=1
        children.append(child)
        if mode=='primitives':assert value['scope']=='SYNTHETIC_PRIMITIVE_PARITY_ONLY' and value['injected_unit_gzip_bounds'] is True
        else:assert value['scope']=='SYNTHETIC_FINITE_DIGEST_AND_THREE_CATALOG_TWO_TRANSITION_ONLY' and value['spool_released'] is value['reconstructed_original30_is_synthetic'] is True
    assert counts=={'positive':14,'reference_refusal':44,'candidate_domain_refusal':22} and children[0]['pid']!=children[1]['pid']
    assert reader.metadata(bodies['output/comparison.json'])=={'status':'EVIDENCE_PARITY_REQUIRES_INDEPENDENT_REVIEW','children':2,'cases':80,'genuine_acceptance':False}
    assert source_fold(reader)[0]==sources and reader.capture(RUN)[0]==files
    result={'schema':'capacity-evidence-parity-independent-proof/1','status':'VERIFIED_SYNTHETIC_EVIDENCE_PARITY_ONLY','cases':80,'counts':counts,'children':children,'cid':row['Id'],'finished':row['State']['FinishedAt'],'inspect_sha256':inspection,'created_stopped_HostConfig_differences':differences,'source_physical':sources,'run_physical':files,'source_book_sha256':BOOK,'packet_sha256':PACKET,'genuine_archive_model_RAM_acceptance':False,'publication':'CLOSED'}
    print(json.dumps({'proof':save(FINAL/'proof.json',result),'counts':counts,'cid':row['Id'],'children':children},sort_keys=True))

# Expose only bounded readonly routes with exact self authentication.
def main(arguments):
    assert len(arguments)==2 and arguments[0] in ('prerequisites','native','terminal') and hashlib.sha256(Path(__file__).read_bytes()).hexdigest()==arguments[1]
    assert os.getuid()==1000 and socket.gethostname()=='animallya-spark1'
    reader=library(HELPER,'e0fa867a793c78b8260d935ed0c1518f60caa10ba3ab11e084a51ae249ec92f5')
    signal.signal(signal.SIGALRM,reader.alarm);signal.setitimer(signal.ITIMER_REAL,45)
    try:{'prerequisites':prerequisites,'native':native,'terminal':terminal}[arguments[0]](reader)
    finally:signal.setitimer(signal.ITIMER_REAL,0)

if __name__=='__main__':main(sys.argv[1:])
