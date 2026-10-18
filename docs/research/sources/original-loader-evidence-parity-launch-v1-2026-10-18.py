"""Fresh admission for one native metadata probe, then one separately admitted parity run."""
import hashlib
import json
import os
import signal
import socket
import stat
import sys
import time
import types
from pathlib import Path

BASE=Path('/home/animallya96/scratch')
SOURCE=BASE/'capacity-evidence-parity-source-20261018-v1'
RUN=BASE/'capacity-evidence-parity-20261018-v1'
PRE=BASE/'capacity-evidence-parity-prerequisites-20261018-v1'
TRANSFER=BASE/'capacity-evidence-parity-transfer-20261018-v1'
NATIVE=BASE/'capacity-evidence-native-probe-20261018-v1'
NATIVE_REVIEW=BASE/'capacity-evidence-native-probe-review-20261018-v1'
PROBE=BASE/'n2-loader-guard-transfer-20261018-v2/prerequisites.py'
BOOK='9cffe5361488307afd63123a4a79ef8b92ec2da53f629c1521734c2d3217b502'
OWNER='3514a6f4d9bfd6be699d0eab6d1b33f6c4e6974b59b94f3734f9f47fa16e36ff'
CALLER='024a4e1e12891c902206e5597d8bcb8a1bb03ba56e7f395fd68b0b90151bc354'
CONTROLLER='2e505205cc8a3793d7b3313a5b5c3b670b00134575982d26c725787b6530df5a'
NATIVE_SOURCE='ac6d0696a658f5da3b219b8eac548831450a9021ec81d4241ee4e01912e4440a'
IMAGE='sha256:e0a54c1f3b293c241ea0eae767d8ba017d0e1a05679965935b336910faa63237'

# Authenticate a bounded regular source across held and named physical identities.
def read(path,expected):
    assert path.resolve(strict=True)==path
    descriptor=os.open(path,os.O_RDONLY|os.O_NOFOLLOW)
    try:
        before=os.fstat(descriptor);assert stat.S_ISREG(before.st_mode) and before.st_uid==1000 and before.st_nlink==1 and 0<=before.st_size<=262144
        raw=os.read(descriptor,262145);keys=('st_dev','st_ino','st_mode','st_uid','st_nlink','st_size','st_blocks','st_mtime_ns','st_ctime_ns')
        identity={key:str(getattr(before,key)) for key in keys}
        assert len(raw)==before.st_size and all(getattr(before,key)==getattr(os.fstat(descriptor),key)==getattr(path.stat(follow_symlinks=False),key) for key in keys) and hashlib.sha256(raw).hexdigest()==expected
        return raw,identity
    finally:os.close(descriptor)

# Persist only new finite admission and invocation metadata with exact readback.
def save(path,value):
    raw=json.dumps(value,sort_keys=True,indent=2,allow_nan=False).encode()+b'\n';assert len(raw)<=262144
    with path.open('xb') as output:output.write(raw);output.flush();os.fsync(output.fileno())
    assert path.read_bytes()==raw
    descriptor=os.open(path.parent,os.O_RDONLY|os.O_DIRECTORY)
    try:os.fsync(descriptor)
    finally:os.close(descriptor)
    return hashlib.sha256(raw).hexdigest()

# Bind a source utility without invoking any old main route.
def library(path,pin):
    raw,_=read(path,pin);value=types.ModuleType('fresh_parity_'+path.stem);value.__file__=str(path)
    exec(compile(raw,str(path),'exec',dont_inherit=True),value.__dict__)
    return value

# Read new jobs/image/resources immediately before consuming a separate admission.
def fresh(root,target):
    root.mkdir(mode=0o700,exist_ok=False)
    probe=library(PROBE,'9576b475e00ff34ba89e2a2bf2036e8a4e939ad7b540cebf0b60ef0741d168a4')
    code,jobs,error=probe.query(root,'jobs',['ps','--filter','label=anios.synthetic.guard-owner','--format','{{json .}}']);assert code==0 and jobs==error==b''
    code,raw,error=probe.query(root,'image',['image','inspect',IMAGE]);image=json.loads(raw)
    assert code==0 and not error and len(image)==1 and image[0]['Id']==IMAGE and image[0]['Os']=='linux' and image[0]['Architecture']=='arm64'
    memory=dict(line.split(':',1) for line in Path('/proc/meminfo').read_text().splitlines());disk=os.statvfs(SOURCE)
    host={'host':socket.gethostname(),'uid':os.getuid(),'observed_at_ns':str(time.time_ns()),'MemAvailable_bytes':str(int(memory['MemAvailable'].split()[0])*1024),'scratch_available_bytes':str(disk.f_bavail*disk.f_frsize),'scratch_inodes_available':str(disk.f_favail),'run_target_lexists':os.path.lexists(target),'reservation':False}
    assert host['run_target_lexists'] is False and int(host['MemAvailable_bytes'])>=5*1024**3 and int(host['scratch_available_bytes'])>=4*1024**3 and int(host['scratch_inodes_available'])>=8192
    evidence=[{'path':str(root/'host-resources.json'),'sha256':save(root/'host-resources.json',host)},{'path':str(root/'runtime-image.json'),'sha256':save(root/'runtime-image.json',image)}]
    return host,evidence

# Own one isolated NumPy-only probe after fresh metadata admission; never invoke parity here.
def native(prerequisite_sha,self_sha):
    prior=json.loads(read(PRE/'proof.json',prerequisite_sha)[0]);assert prior['status']=='VERIFIED_SOURCE_IMAGE_HOST_ONLY_NATIVE_AND_PARITY_UNRUN'
    for name,item in prior['source_physical'].items():assert read(SOURCE/name,item['sha256'])[1]==item['physical']
    audit=TRANSFER/'native-audit';raw,identity=read(audit/'bootstrap.py',NATIVE_SOURCE)
    assert [path.name for path in audit.iterdir()]==['bootstrap.py']
    host,evidence=fresh(TRANSFER/'native-admission',NATIVE)
    review_sha=hashlib.sha256(b'NUMPY_METADATA_ONLY\0'+raw).hexdigest()
    admission_sha=save(TRANSFER/'native-admission/admission.json',{'scope':'NUMPY_IMPORT_METADATA_ONLY','launch_sha256':self_sha,'prerequisite_sha256':prerequisite_sha,'review_sha256':review_sha,'observed_at_ns':host['observed_at_ns'],'host':host,'host_evidence':evidence,'genuine_or_parity_execution':False})
    controller=library(SOURCE/'owner/controller.py',CONTROLLER);owner=None
    signal.signal(signal.SIGALRM,controller.alarm)
    for signum in (signal.SIGHUP,signal.SIGINT,signal.SIGTERM):signal.signal(signum,controller.alarm)
    signal.setitimer(signal.ITIMER_REAL,120)
    try:
        owner=controller.Owner(NATIVE,audit,review_sha);controller.save(NATIVE/'source-before.json',controller.encode(identity))
        output=NATIVE/'output';output.mkdir(mode=0o700)
        cid=owner.phase('prepare',[(str(audit),'/audit',False),(str(output),'/out',True)],['diagnose'],timeout=60)
        assert read(audit/'bootstrap.py',NATIVE_SOURCE)[1]==identity
        controller.save(NATIVE/'source-after.json',controller.encode(identity));controller.save(NATIVE/'terminal.json',controller.encode({'status':'NATIVE_NUMPY_METADATA_ONLY_NOT_PARITY_ACCEPTANCE','cid':cid,'review_sha256':review_sha,'admission_sha256':admission_sha}))
        print(json.dumps({'admission_sha256':admission_sha,'host':host,'cid':cid,'parity_executed':False},sort_keys=True),flush=True)
    finally:
        signal.setitimer(signal.ITIMER_REAL,0)
        if owner is not None:owner.cleanup()

# Require independent native proof plus a new fresh scoped admission for one exact parity caller.
def parity(prerequisite_sha,native_sha,self_sha):
    prior=json.loads(read(PRE/'proof.json',prerequisite_sha)[0]);assert prior['status']=='VERIFIED_SOURCE_IMAGE_HOST_ONLY_NATIVE_AND_PARITY_UNRUN'
    native_proof=json.loads(read(NATIVE_REVIEW/'proof.json',native_sha)[0]);assert native_proof['status']=='VERIFIED_NATIVE_IMPORT_METADATA_ONLY'
    assert native_proof['facts']['numpy_file']=='/usr/local/lib/python3.12/site-packages/numpy/__init__.py' and native_proof['facts']['python'].startswith('3.12.')
    for name,item in prior['source_physical'].items():assert read(SOURCE/name,item['sha256'])[1]==item['physical']
    read(SOURCE/'source-book.json',BOOK);read(SOURCE/'owner/parity-owner.py',OWNER);raw,_=read(SOURCE/'owner/caller.py',CALLER)
    root=SOURCE/'admission';host,evidence=fresh(root,RUN)
    value={'schema':'capacity-evidence-parity-admission/1','scope':'SYNTHETIC_EVIDENCE_AND_ARCHIVE_PARITY_ONLY','observed_at_ns':host['observed_at_ns'],'host':host['host'],'uid':1000,'source_book_sha256':BOOK,'owner_sha256':OWNER,'run_root':str(RUN),'image':IMAGE,'host_evidence':evidence,'genuine_execution_authorized':False}
    admission_sha=save(root/'admission.json',value)
    arguments=['--call-admitted-evidence-parity',OWNER,BOOK,admission_sha]
    save(root/'launch-binding.json',{'launch_sha256':self_sha,'prerequisite_sha256':prerequisite_sha,'native_proof_sha256':native_sha,'caller_sha256':CALLER,'caller_arguments':arguments,'synthetic_only':True})
    module=types.ModuleType('exact_admitted_parity_caller');module.__file__=str(SOURCE/'owner/caller.py')
    exec(compile(raw,module.__file__,'exec',dont_inherit=True),module.__dict__);module.main(arguments)
    print(json.dumps({'admission_sha256':admission_sha,'host':host,'native_proof_sha256':native_sha,'genuine_execution':False},sort_keys=True),flush=True)

# Expose only exact self-pinned explicit native or parity routes, both initially inert.
def main(arguments):
    assert len(arguments) in (3,4) and arguments[0] in ('native','parity')
    assert all(len(value)==64 and all(char in '0123456789abcdef' for char in value) for value in arguments[1:])
    assert read(Path(__file__),arguments[-1])[0] and os.getuid()==1000 and socket.gethostname()=='animallya-spark1'
    if arguments[0]=='native':assert len(arguments)==3;native(arguments[1],arguments[2])
    else:assert len(arguments)==4;parity(arguments[1],arguments[2],arguments[3])

if __name__=='__main__':main(sys.argv[1:])
