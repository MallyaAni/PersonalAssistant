"""Independent readonly source/prerequisite and terminal folds; never execute probes."""
import base64
import hashlib
import json
import os
import signal
import socket
import sys
import time
import types
from pathlib import Path

SOURCE=Path('/home/animallya96/scratch/n2-metadata-tiny-source-20261018-v1')
RUN=Path('/home/animallya96/scratch/n2-metadata-tiny-20261018-v1')
PRE=Path('/home/animallya96/scratch/n2-metadata-tiny-prerequisites-20261018-v1')
FINAL=Path('/home/animallya96/scratch/n2-metadata-tiny-independent-review-20261018-v1')
HELPER=Path('/home/animallya96/scratch/n2-loader-guard-source-20261018-v2/owner/verifier.py')
PROBE=Path('/home/animallya96/scratch/n2-loader-guard-transfer-20261018-v2/prerequisites.py')
BOOK='dc785f33272b61c4bb79c5c456cce8728aede1ac8ee69880e47817766221ef0f'
PACKET='881af8743066e336c4abf021b9c7a5ded1e8b0bb55d3f1df03aac7f0112d0a3e'
IMAGE='sha256:e0a54c1f3b293c241ea0eae767d8ba017d0e1a05679965935b336910faa63237'
FIELDS=('sessions_seen','last_rebalance','sessions_since_rebalance','policy_version','opened','start_equity','history','pending','journal','unconfirmed_rebalance','previous_rebalance','order_seq','event_cycle','event_outcomes','deferred_buys','rebalance_targets','allocation_state')
CASES=[
('real-partial31-reader-twice',None),
('paper-byte','EXACT_N2_PAPER_SOURCE_REQUIRED'),('CURRENT-paper','EXACT_N2_PAPER_SOURCE_REQUIRED'),
('paper-type','EXACT_BOUNDED_PAPER_BYTES_REQUIRED'),('paper-bound','EXACT_BOUNDED_PAPER_BYTES_REQUIRED'),
*[( 'descriptor-'+name,'EXACT_SOURCE_BOUND_LAYOUT_REQUIRED') for name in ('schema','source_sha256','PaperState_ast_sha256','state_path_ast_sha256','physical_state_fields','relative_state_components')],
('descriptor-type','EXACT_SOURCE_BOUND_LAYOUT_REQUIRED'),('wrong31-pin','EXACT_N2_NATIVE31_MAP_REQUIRED'),
('missing31','EXACT_N2_SOURCE_READER_REQUIRED'),('reader-type','EXACT_N2_SOURCE_READER_REQUIRED'),
*[(name,'ACTUAL_PARTIAL_SOURCEBOOK_BINDING_REQUIRED') for name in ('adapter-fake-book','adapter-lambda','adapter-wrong-root','adapter-wrong-pins','adapter-wrong-root-fd','adapter-instance-read')],
('unit-wrong-bytes','N2_SOURCE_BYTES_DIFFER'),('unit-wrong-byte-type','BOUNDED_AUTHENTICATED_SOURCE_BYTES_REQUIRED')]

# Authenticate the old read-only utility source, without invoking its test entry point.
def library(path,expected):
    raw=path.read_bytes()
    assert len(raw)<=262144 and hashlib.sha256(raw).hexdigest()==expected
    value=types.ModuleType('metadata_independent_'+path.stem)
    value.__file__=str(path)
    exec(compile(raw,str(path),'exec',dont_inherit=True),value.__dict__)
    return value

# Persist a finite new independent proof with durable exact-byte readback.
def save(path,value):
    raw=json.dumps(value,sort_keys=True,indent=2,allow_nan=False).encode()+b'\n'
    assert len(raw)<=262144
    with path.open('xb') as output:
        output.write(raw);output.flush();os.fsync(output.fileno())
    assert path.read_bytes()==raw
    descriptor=os.open(path.parent,os.O_RDONLY|os.O_DIRECTORY)
    try:os.fsync(descriptor)
    finally:os.close(descriptor)
    return {'sha256':hashlib.sha256(raw).hexdigest(),'bytes':len(raw)}

# Verify the fixed40 source payloads and38 source-book records against original staging.
def source_fold(reader):
    physical,bodies=reader.capture(SOURCE)
    stage=reader.metadata(bodies['stage-proof.json'])
    assert stage['packet_sha256']==PACKET and stage['source_book_sha256']==BOOK and len(stage['files'])==41
    for name,item in stage['files'].items():assert physical[name]==item
    book=reader.metadata(bodies['source-book.json'])
    assert reader.sha(bodies['source-book.json'])==BOOK and book['schema']=='metadata-tiny-source/1' and len(book['files'])==38
    assert set(stage['files'])==set(book['files'])|{'owner/metadata-owner.py','owner/caller.py','source-book.json'}
    for name,item in book['files'].items():assert item=={key:physical[name][key] for key in ('sha256','bytes')}
    native=reader.metadata(bodies['audit/native31.json'])
    assert len(native)==31 and reader.sha(json.dumps(native,sort_keys=True,separators=(',',':')).encode())=='99e62ab9f8b02bc315ce59b81f8b461ae5c988e275cdf09cacf2d36b1025f8ab'
    for name,expected in native.items():assert physical['audit/fixture/'+name]['sha256']==expected
    return physical,bodies,stage,book,native

# Read fresh actual image/jobs/resources before any new metadata runtime is admitted.
def prerequisites(reader):
    PRE.mkdir(mode=0o700,exist_ok=False)
    before,bodies,stage,book,native=source_fold(reader)
    assert set(before)==set(stage['files'])|{'stage-proof.json'}
    probe=library(PROBE,'9576b475e00ff34ba89e2a2bf2036e8a4e939ad7b540cebf0b60ef0741d168a4')
    code,jobs,error=probe.query(PRE,'jobs',['ps','--filter','label=anios.synthetic.guard-owner','--format','{{json .}}'])
    assert code==0 and jobs==error==b''
    code,raw,error=probe.query(PRE,'image',['image','inspect',IMAGE])
    image=reader.metadata(raw)
    assert code==0 and error==b'' and len(image)==1 and image[0]['Id']==IMAGE and image[0]['Os']=='linux' and image[0]['Architecture']=='arm64'
    save(PRE/'runtime-image.json',image)
    memory=dict(line.split(':',1) for line in Path('/proc/meminfo').read_text().splitlines())
    disk=os.statvfs(SOURCE)
    resources={'scope':'FRESH_METADATA_SYNTHETIC_HEADROOM_NOT_RESERVATION','host':socket.gethostname(),'uid':os.getuid(),'observed_at_ns':str(time.time_ns()),'MemAvailable_bytes':str(int(memory['MemAvailable'].split()[0])*1024),'scratch_available_bytes':str(disk.f_bavail*disk.f_frsize),'scratch_inodes_available':str(disk.f_favail),'targets':{str(path):os.path.lexists(path) for path in (RUN,FINAL)},'reservation':False}
    assert resources['host']=='animallya-spark1' and resources['uid']==1000 and not any(resources['targets'].values())
    assert int(resources['MemAvailable_bytes'])>=5*1024**3 and int(resources['scratch_available_bytes'])>=4*1024**3 and int(resources['scratch_inodes_available'])>=8192
    assert source_fold(reader)[0]==before
    result={'schema':'metadata-tiny-prerequisite-proof/1','status':'VERIFIED_SOURCE_PREREQUISITES_NOT_EXECUTION_ADMISSION','source_physical':before,'packet_sha256':PACKET,'source_book_sha256':BOOK,'resources':resources,'image_raw_sha256':reader.sha(raw),'active_labelled_jobs':[],'runtime_created':False}
    pin=save(PRE/'proof.json',result)
    print(json.dumps({'proof':pin,'resources':resources},sort_keys=True))

# Independently fold all23 retained outcomes and one fresh exact-CID inspection.
def terminal(reader):
    FINAL.mkdir(mode=0o700,exist_ok=False)
    sources,source,stage,book,native=source_fold(reader)
    files,bodies=reader.capture(RUN)
    term=reader.metadata(bodies['terminal.json'])
    assert term['status']=='METADATA_TINY_TERMINAL_PARTIAL31_NOT_GENUINE_ACCEPTANCE' and term['genuine_or_guard_suite_acceptance'] is False and term['source_book_sha256']==BOOK
    before=reader.metadata(bodies['source-before.json'])
    assert before==reader.metadata(bodies['source-after.json']) and set(before)==set(book['files'])
    for name,item in before.items():assert item==sources[name]
    assert term['comparison_sha256']==reader.sha(bodies['output/comparison.json'])
    adm=reader.metadata(source['admission/admission.json'])
    assert reader.sha(source['admission/admission.json'])==term['admission_sha256'] and adm['scope']=='N2_METADATA_HELPER_PARTIAL31_ONLY' and adm['genuine_execution_authorized'] is False
    created=reader.metadata(bodies['prepare-before.json'])
    stopped=reader.metadata(bodies['prepare-after.json'])
    row,inspect_sha=reader.inspect_owned(term['cid'],FINAL,0)
    label=reader.sha((str(RUN)+':'+BOOK).encode())
    name='n2-guard-'+label[:20]+'-prepare'
    binds=[(str(SOURCE/'audit'),'/audit',False),(str(RUN/'output'),'/out',True)]
    reader.runtime(created,name,label,binds,['diagnose'],stopped=False)
    reader.runtime(row,name,label,binds,['diagnose'],stopped=True)
    assert row['Id']==created['Id']==stopped['Id'] and row['State']==stopped['State'] and row['Config']==created['Config']==stopped['Config']
    assert {key:value for key,value in row.items() if key!='Mounts'}=={key:value for key,value in stopped.items() if key!='Mounts'}
    mount_maps=[]
    for observation in (created,stopped,row):
        assert len(observation['Mounts'])==2 and len({item['Destination'] for item in observation['Mounts']})==2
        mount_maps.append({item['Destination']:item for item in observation['Mounts']})
    assert mount_maps[0]==mount_maps[1]==mount_maps[2]
    assert set(created['HostConfig'])==set(stopped['HostConfig'])
    differences={key:[created['HostConfig'][key],stopped['HostConfig'][key]] for key in created['HostConfig'] if created['HostConfig'][key]!=stopped['HostConfig'][key]}
    assert differences in ({},{'OomKillDisable':[False,None]})
    candidate=reader.metadata(bodies['output/candidate/result.json'])
    reference=reader.metadata(bodies['output/reference/result.json'])
    assert candidate['scope']=='SYNTHETIC_METADATA_ACTUAL_HELPER_PARTIAL_SOURCEBOOK_NOT_GENUINE_ADMISSION'
    assert reference['scope']=='ISOLATED_SYNTHETIC_DECLARATION_REFERENCE' and reference['paper_instance_created'] is reference['full_original_module_imported'] is False
    assert candidate['fields']==reference['fields']==list(FIELDS) and len(FIELDS)==17
    assert candidate['paths']==reference['paths']==['/synthetic/no-account/paper/state.json','relative-reference/paper/state.json']
    assert candidate['native31']==native and candidate['complete2446_source_admission'] is False and candidate['callback_refusal_cases_explicitly_injected'] is True
    assert candidate['helper_sha256']=='d413e748bf2b1eb63f4d267371f22cf6431f6ae650368676c815b07779723135' and candidate['harness_sha256']=='030cb5bb25f89c2785e6acbd55aceff5c99b632a5eb538079ee027362ae6178a'
    assert len(CASES)==23 and [item['case'] for item in candidate['cases']]==[item[0] for item in CASES]
    for (case,reason),outcome in zip(CASES,candidate['cases'],strict=True):
        if reason is None:assert outcome=={'case':case,'status':'PASS','read_sources':31,'full2446_authenticated':False}
        else:assert outcome=={'case':case,'status':'EXPECTED_REFUSAL','reason':reason}
    bookends=candidate['source_bookends_before']
    assert len(bookends)==31 and bookends==candidate['source_bookends_after'] and set(bookends)==set(native)
    for name,identity in bookends.items():
        actual=sources['audit/fixture/'+name]['physical']
        assert identity=={key:actual[key] for key in identity} and len(identity)==8
    children=[]
    for mode in ('reference','candidate'):
        value=reader.metadata(bodies['output/'+mode+'/exit.json'])
        assert value['exit']==0 and value['owned_stop'] is None and int(value['pid'])>1
        assert bodies['output/'+mode+'/stdout.log']==bodies['output/'+mode+'/stderr.log']==b''
        children.append(value)
    assert children[0]['pid']!=children[1]['pid']
    comparison=reader.metadata(bodies['output/comparison.json'])
    assert comparison=={'status':'METADATA_TINY_CANDIDATE_REQUIRES_INDEPENDENT_REVIEW','children':2,'cases':23,'fields':17,'paths_equal':True,'native_sources':31,'genuine_source_admission':False,'model_or_account':False}
    assert reader.capture(RUN)[0]==files and source_fold(reader)[0]==sources
    result={'schema':'metadata-tiny-independent-proof/1','status':'VERIFIED_METADATA_HELPER_PARTIAL31_ONLY','cases':23,'children':children,'cid':row['Id'],'finished':row['State']['FinishedAt'],'independent_inspect_sha256':inspect_sha,'raw_mount_order_equal':row['Mounts']==stopped['Mounts'],'created_stopped_HostConfig_representation_differences':differences,'source_physical':sources,'run_physical':files,'source_book_sha256':BOOK,'packet_sha256':PACKET,'complete2446_source_admission':False,'model_or_account_RAM_acceptance':False,'publication':'CLOSED'}
    pin=save(FINAL/'proof.json',result)
    print(json.dumps({'proof':pin,'cid':row['Id'],'cases':23,'children':children},sort_keys=True))

# Expose only readonly review routes with a real finite wall deadline.
def main(arguments):
    assert len(arguments)==2 and arguments[0] in ('prerequisites','terminal') and hashlib.sha256(Path(__file__).read_bytes()).hexdigest()==arguments[1]
    assert os.getuid()==1000 and socket.gethostname()=='animallya-spark1'
    reader=library(HELPER,'e0fa867a793c78b8260d935ed0c1518f60caa10ba3ab11e084a51ae249ec92f5')
    signal.signal(signal.SIGALRM,reader.alarm)
    signal.setitimer(signal.ITIMER_REAL,45)
    try:{'prerequisites':prerequisites,'terminal':terminal}[arguments[0]](reader)
    finally:signal.setitimer(signal.ITIMER_REAL,0)

if __name__=='__main__':
    main(sys.argv[1:])
