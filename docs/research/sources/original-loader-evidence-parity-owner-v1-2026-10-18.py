"""UNRUN owner: one fresh externally admitted synthetic parity phase only."""
import hashlib
import json
import os
import signal
import socket
import stat
import sys
import time
import types
from pathlib import Path, PurePosixPath

SOURCE=Path('/home/animallya96/scratch/capacity-evidence-parity-source-20261018-v1')
RUN=Path('/home/animallya96/scratch/capacity-evidence-parity-20261018-v1')
IMAGE='sha256:e0a54c1f3b293c241ea0eae767d8ba017d0e1a05679965935b336910faa63237'
CONTROLLER='2e505205cc8a3793d7b3313a5b5c3b670b00134575982d26c725787b6530df5a'

# Preserve source physical identities as exact decimal strings.
def physical(value):
    return {key:str(getattr(value,key)) for key in ('st_dev','st_ino','st_mode','st_uid','st_nlink','st_size','st_blocks','st_mtime_ns','st_ctime_ns')}

# Read only bounded regular source or metadata bytes with held/named physical bookends.
def read(path):
    assert path.resolve(strict=True)==path
    descriptor=os.open(path,os.O_RDONLY|os.O_NOFOLLOW)
    try:
        before=os.fstat(descriptor)
        assert stat.S_ISREG(before.st_mode) and before.st_uid==1000 and before.st_nlink==1 and 0<=before.st_size<=262144
        raw=os.read(descriptor,262145)
        assert len(raw)==before.st_size and physical(before)==physical(os.fstat(descriptor))==physical(path.stat(follow_symlinks=False))
        return raw,{'sha256':hashlib.sha256(raw).hexdigest(),'bytes':len(raw),'physical':physical(before)}
    finally:os.close(descriptor)

# Authenticate the complete new small source book and exact audit-file inventory.
def sources(book):
    assert set(book)=={'schema','files'} and book['schema']=='capacity-evidence-parity-source/1' and 1<=len(book['files'])<=64
    observed={}
    for name,item in sorted(book['files'].items()):
        path=PurePosixPath(name)
        assert not path.is_absolute() and '..' not in path.parts and str(path)==name and path.parts[0] in ('audit','owner')
        raw,identity=read(SOURCE/name)
        assert item=={key:identity[key] for key in ('sha256','bytes')}
        observed[name]=identity
    assert observed['owner/controller.py']['sha256']==CONTROLLER
    actual={str(path.relative_to(SOURCE)) for path in (SOURCE/'audit').rglob('*') if path.is_file()}
    assert actual=={name for name in book['files'] if name.startswith('audit/')}
    return observed

# Require a fresh one-use synthetic source/runtime/resource admission before any create.
def execute(admission_sha,self_sha,book_sha):
    assert os.getuid()==1000 and socket.gethostname()=='animallya-spark1' and not os.path.lexists(RUN)
    assert read(Path(__file__))[1]['sha256']==self_sha
    raw,identity=read(SOURCE/'source-book.json');assert identity['sha256']==book_sha
    book=json.loads(raw);before=sources(book)
    raw,identity=read(SOURCE/'admission/admission.json');assert identity['sha256']==admission_sha
    admission=json.loads(raw)
    assert set(admission)=={'schema','scope','observed_at_ns','host','uid','source_book_sha256','owner_sha256','run_root','image','host_evidence','genuine_execution_authorized'}
    assert admission['schema']=='capacity-evidence-parity-admission/1' and admission['scope']=='SYNTHETIC_EVIDENCE_AND_ARCHIVE_PARITY_ONLY'
    assert admission['source_book_sha256']==book_sha and admission['owner_sha256']==self_sha and admission['run_root']==str(RUN)
    assert admission['host']==socket.gethostname() and admission['uid']==1000 and admission['image']==IMAGE and admission['genuine_execution_authorized'] is False
    assert 0<=time.time_ns()-int(admission['observed_at_ns'])<=120*10**9 and len(admission['host_evidence'])==2
    evidence={}
    for item in admission['host_evidence']:
        path=Path(item['path']);assert path.parent==SOURCE/'admission' and path.name in ('host-resources.json','runtime-image.json') and path.name not in evidence
        raw,identity=read(path);assert identity['sha256']==item['sha256'];evidence[path.name]=json.loads(raw)
    host=evidence['host-resources.json'];image=evidence['runtime-image.json']
    assert host['host']==socket.gethostname() and host['uid']==1000 and host['observed_at_ns']==admission['observed_at_ns'] and host['run_target_lexists'] is False and host['reservation'] is False
    assert int(host['MemAvailable_bytes'])>=5*1024**3 and int(host['scratch_available_bytes'])>=4*1024**3 and int(host['scratch_inodes_available'])>=8192
    assert len(image)==1 and image[0]['Id']==IMAGE and image[0]['Os']=='linux' and image[0]['Architecture']=='arm64'
    controller=types.ModuleType('parity_owner_library');controller.__file__=str(SOURCE/'owner/controller.py')
    raw=read(Path(controller.__file__))[0];exec(compile(raw,controller.__file__,'exec',dont_inherit=True),controller.__dict__)
    signal.signal(signal.SIGALRM,controller.alarm)
    for signum in (signal.SIGHUP,signal.SIGINT,signal.SIGTERM):signal.signal(signum,controller.alarm)
    signal.setitimer(signal.ITIMER_REAL,130);owner=None
    try:
        owner=controller.Owner(RUN,SOURCE/'audit',book_sha)
        controller.save(RUN/'source-before.json',controller.encode(before))
        code,jobs,error=owner.command(['ps','--filter','label='+controller.LABEL,'--format','{{json .}}']);assert code==0 and jobs==error==b''
        output=RUN/'output';output.mkdir(mode=0o700)
        cid=owner.phase('prepare',[(str(SOURCE/'audit'),'/audit',False),(str(output),'/out',True)],['diagnose'],timeout=85)
        assert sources(book)==before
        controller.save(RUN/'source-after.json',controller.encode(before))
        raw,identity=read(output/'comparison.json')
        controller.save(RUN/'terminal.json',controller.encode({'status':'CAPACITY_EVIDENCE_PARITY_REQUIRES_INDEPENDENT_REVIEW','cid':cid,'source_book_sha256':book_sha,'admission_sha256':admission_sha,'comparison_sha256':identity['sha256'],'genuine_acceptance':False}))
    finally:
        signal.setitimer(signal.ITIMER_REAL,0)
        if owner is not None:owner.cleanup()

# Refuse ordinary invocation and expose only the exact scoped route.
def main(arguments):
    if len(arguments)!=4 or arguments[0]!='--admitted-evidence-parity':raise SystemExit('SOURCE_ONLY_NO_EVIDENCE_PARITY_ADMISSION')
    execute(arguments[1],arguments[2],arguments[3])

if __name__=='__main__':main(sys.argv[1:])
