"""Read only the exact small original execution receipt over the retained pinned key."""
import base64
import hashlib
import json
import os
from pathlib import Path
import resource
import shlex
import subprocess

OUT = Path('/tmp/original-loader-genuine-composition-20261018-v1')
EXPECTED = 'eaa07107c2f88e31f6c3eaf1f5eee1bf579bc86fed60db7f578a502859960e96'
REMOTE = """import base64,hashlib,json,os,stat
# Preserve exact physical identity counters for the held original metadata.
def physical(value):
    return {name:str(getattr(value,name)) for name in ('st_dev','st_ino','st_mode','st_uid','st_nlink','st_size','st_mtime_ns','st_ctime_ns')}
parts='/home/animallya96/scratch/live-model-history-full-20261013-v1/execution.json'.split('/')[1:]
parent=os.open('/',os.O_RDONLY|os.O_DIRECTORY)
try:
    for part in parts[:-1]:
        following=os.open(part,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=parent)
        os.close(parent)
        parent=following
    fd=os.open(parts[-1],os.O_RDONLY|os.O_NOFOLLOW,dir_fd=parent)
    try:
        before=os.fstat(fd)
        assert stat.S_ISREG(before.st_mode) and before.st_size<=262144
        raw=os.read(fd,262145)
        assert len(raw)==before.st_size and os.read(fd,1)==b''
        after=os.fstat(fd)
        named=os.stat(parts[-1],dir_fd=parent,follow_symlinks=False)
        assert physical(before)==physical(after)==physical(named)
        checksum=hashlib.sha256(raw).hexdigest()
        assert checksum=='eaa07107c2f88e31f6c3eaf1f5eee1bf579bc86fed60db7f578a502859960e96'
        print(json.dumps({'sha256':checksum,'bytes':len(raw),'physical_before':physical(before),'physical_after':physical(after),'body_base64':base64.b64encode(raw).decode()},sort_keys=True))
    finally:
        os.close(fd)
finally:
    os.close(parent)
"""

# Bound local transport logs without claiming a daemon or model memory limit.
def limits():
    resource.setrlimit(resource.RLIMIT_FSIZE,(512*1024,512*1024))

# Preserve each new small observation with fsync and byte-identical readback.
def save(path,raw):
    assert len(raw)<=512*1024
    with path.open('xb') as output:
        output.write(raw)
        output.flush()
        os.fsync(output.fileno())
    assert path.read_bytes()==raw

# Fetch one authenticated metadata file; never run a container or application import.
def main():
    OUT.mkdir(mode=0o700,exist_ok=False)
    trusted=Path('/tmp/checkpoint-image-hostkeys-20261017-v1')
    assert b'172.16.8.3 ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAINHTL/KivuZJ4KwrNAPy+2RnonvooU7mqwOvqA8anY8s' in trusted.read_bytes().splitlines()
    argv=['ssh','-o','BatchMode=yes','-o','StrictHostKeyChecking=yes','-o','HostKeyAlgorithms=ssh-ed25519','-o','ConnectTimeout=10','-o','GlobalKnownHostsFile=/dev/null','-o','UserKnownHostsFile='+str(trusted),'animallya96@172.16.8.3',shlex.join(['python3','-I','-S','-B','-c',REMOTE])]
    process=None
    with (OUT/'metadata.stdout').open('xb') as stdout,(OUT/'metadata.stderr').open('xb') as stderr:
        try:
            process=subprocess.Popen(argv,stdin=subprocess.DEVNULL,stdout=stdout,stderr=stderr,preexec_fn=limits)
            process.wait(timeout=30)
        finally:
            if process is not None and process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=1)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=1)
            stdout.flush();os.fsync(stdout.fileno())
            stderr.flush();os.fsync(stderr.fileno())
    save(OUT/'exit.json',json.dumps({'exit':process.returncode,'pid':str(process.pid)},sort_keys=True).encode())
    assert process.returncode==0 and (OUT/'metadata.stderr').read_bytes()==b''
    report=json.loads((OUT/'metadata.stdout').read_bytes())
    raw=base64.b64decode(report['body_base64'],validate=True)
    assert hashlib.sha256(raw).hexdigest()==EXPECTED and len(raw)==report['bytes']
    save(OUT/'original-execution.json',raw)
    print(json.dumps({'status':'AUTHENTICATED_SMALL_METADATA_ONLY','sha256':EXPECTED,'bytes':len(raw),'root':str(OUT)}))

if __name__=='__main__':
    main()
