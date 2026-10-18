"""Fresh synthetic-only admission and one exact metadata caller invocation."""
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
PROBE=Path('/home/animallya96/scratch/n2-loader-guard-transfer-20261018-v2/prerequisites.py')
IMAGE='sha256:e0a54c1f3b293c241ea0eae767d8ba017d0e1a05679965935b336910faa63237'
OWNER='d1a73446f79c26e627ac74c5face0ad480e5f62fd9a360bfccf37442a4b5c434'
CALLER='5b2151c4ea45512f1a4bf08ad7299c03f5647d43dba5bddfbfde34c59821f272'
BOOK='dc785f33272b61c4bb79c5c456cce8728aede1ac8ee69880e47817766221ef0f'
PREREQUISITES='3b3e2248a10aae9592f4a14fa69bc7be4e3933555edf67cccaf8ef78d5fcc6d9'

# Bind exact small source or proof bytes without importing any application module.
def read(path,expected):
    assert path.resolve(strict=True)==path and path.stat().st_size<=262144
    raw=path.read_bytes()
    assert len(raw)<=262144 and hashlib.sha256(raw).hexdigest()==expected
    return raw

# Persist an exclusive bounded admission record and fsync its directory.
def save(path,value):
    raw=json.dumps(value,sort_keys=True,indent=2,allow_nan=False).encode()+b'\n'
    assert len(raw)<=262144
    with path.open('xb') as output:
        output.write(raw);output.flush();os.fsync(output.fileno())
    assert path.read_bytes()==raw
    descriptor=os.open(path.parent,os.O_RDONLY|os.O_DIRECTORY)
    try:os.fsync(descriptor)
    finally:os.close(descriptor)
    return hashlib.sha256(raw).hexdigest()

# Stop the outer launch on its real wall deadline while preserving the owner cleanup.
def alarm(signum,frame):
    raise TimeoutError('METADATA_LAUNCH_DEADLINE')

# Admit exactly one fresh metadata attempt after independently reviewed prerequisites.
def main(arguments):
    assert len(arguments)==1 and hashlib.sha256(Path(__file__).read_bytes()).hexdigest()==arguments[0]
    assert os.getuid()==1000 and socket.gethostname()=='animallya-spark1' and not os.path.lexists(RUN)
    prior=json.loads(read(PRE/'proof.json',PREREQUISITES))
    assert prior['runtime_created'] is False and prior['status']=='VERIFIED_SOURCE_PREREQUISITES_NOT_EXECUTION_ADMISSION'
    read(SOURCE/'source-book.json',BOOK);read(SOURCE/'owner/metadata-owner.py',OWNER)
    caller=read(SOURCE/'owner/caller.py',CALLER)
    for name,item in prior['source_physical'].items():
        path=SOURCE/name
        read(path,item['sha256'])
        actual={key:str(getattr(path.stat(follow_symlinks=False),key)) for key in item['physical']}
        assert actual==item['physical']
    root=SOURCE/'admission'
    root.mkdir(mode=0o700,exist_ok=False)
    probe=types.ModuleType('metadata_fresh_prerequisites')
    probe.__file__=str(PROBE)
    exec(compile(read(PROBE,'9576b475e00ff34ba89e2a2bf2036e8a4e939ad7b540cebf0b60ef0741d168a4'),str(PROBE),'exec',dont_inherit=True),probe.__dict__)
    signal.signal(signal.SIGALRM,alarm);signal.setitimer(signal.ITIMER_REAL,150)
    try:
        code,jobs,error=probe.query(root,'jobs',['ps','--filter','label=anios.synthetic.guard-owner','--format','{{json .}}'])
        assert code==0 and jobs==error==b''
        code,raw,error=probe.query(root,'image',['image','inspect',IMAGE])
        image=json.loads(raw)
        assert code==0 and not error and len(image)==1 and image[0]['Id']==IMAGE and image[0]['Os']=='linux' and image[0]['Architecture']=='arm64'
        memory=dict(line.split(':',1) for line in Path('/proc/meminfo').read_text().splitlines())
        disk=os.statvfs(SOURCE)
        observed=str(time.time_ns())
        host={'host':socket.gethostname(),'uid':os.getuid(),'observed_at_ns':observed,'MemAvailable_bytes':str(int(memory['MemAvailable'].split()[0])*1024),'scratch_available_bytes':str(disk.f_bavail*disk.f_frsize),'scratch_inodes_available':str(disk.f_favail),'run_target_lexists':os.path.lexists(RUN),'reservation':False}
        assert int(host['MemAvailable_bytes'])>=5*1024**3 and int(host['scratch_available_bytes'])>=4*1024**3 and int(host['scratch_inodes_available'])>=8192 and host['run_target_lexists'] is False
        evidence=[{'path':str(root/'runtime-image.json'),'sha256':save(root/'runtime-image.json',image)},{'path':str(root/'host-resources.json'),'sha256':save(root/'host-resources.json',host)}]
        admission={'schema':'metadata-tiny-admission/1','scope':'N2_METADATA_HELPER_PARTIAL31_ONLY','observed_at_ns':observed,'host':host['host'],'uid':1000,'source_book_sha256':BOOK,'owner_sha256':OWNER,'run_root':str(RUN),'image':IMAGE,'host_evidence':evidence,'genuine_execution_authorized':False}
        admission_sha=save(root/'admission.json',admission)
        save(root/'launch-binding.json',{'launch_sha256':arguments[0],'prerequisite_sha256':PREREQUISITES,'caller_sha256':CALLER,'caller_arguments':['--call-admitted-metadata-tiny',OWNER,BOOK,admission_sha],'synthetic_only':True})
        module=types.ModuleType('exact_metadata_caller')
        module.__file__=str(SOURCE/'owner/caller.py')
        exec(compile(caller,module.__file__,'exec',dont_inherit=True),module.__dict__)
        module.main(['--call-admitted-metadata-tiny',OWNER,BOOK,admission_sha])
        print(json.dumps({'admission_sha256':admission_sha,'host':host,'runtime_attempted_once':True,'genuine_execution':False},sort_keys=True),flush=True)
    finally:signal.setitimer(signal.ITIMER_REAL,0)

if __name__=='__main__':main(sys.argv[1:])
