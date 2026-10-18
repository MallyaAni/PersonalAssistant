"""Prepare distinct bounded prerequisite or retained-receipt observations without decoder execution."""
import ast
import hashlib
import json
import os
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
TEMPLATE_SHA = '78253bcf66db3e449b4247749b1912c640ea809e941fb820d975e739bed19617'


# Construct a read-only Linux observation with fixed new roots and exact proposed control source pins.
def bootstrap(phase, mode, pins):
    return r'''import base64,hashlib,json,os,pathlib,resource,signal,socket,stat,sys,time
assert __debug__ and sys.platform=='linux' and os.getuid()==1000 and socket.gethostname()=='animallya-spark1'
resource.setrlimit(resource.RLIMIT_AS,(536870912,536870912))
resource.setrlimit(resource.RLIMIT_CPU,(20,20))
resource.setrlimit(resource.RLIMIT_FSIZE,(262144,262144))
signal.alarm(30)
raw=sys.stdin.buffer.read(65537)
assert len(raw)<=65536
packet=json.loads(raw)
expected=EXPECTED_PINS
assert type(packet)is dict and set(packet)==set(expected)
for name,sha in expected.items():
 body=base64.b64decode(packet[name],validate=True)
 assert len(body)<=262144 and hashlib.sha256(body).hexdigest()==sha
phase=PHASE_VALUE
mode=MODE_VALUE
tools=pathlib.Path('/home/animallya96/scratch/capacity-callback-symbol-'+phase+'-tools-20261018-v1')
output=pathlib.Path('/home/animallya96/scratch/capacity-callback-symbol-data-'+('analysis' if phase=='primary' else 'independent')+'-20261018-v1')
assert tools.parent.resolve(strict=True)==tools.parent and output.parent==tools.parent

# Keep original physical fields exact in the retained observation.
def physical(value):
 return {key:str(getattr(value,key))for key in ('st_dev','st_ino','st_mode','st_uid','st_nlink','st_size','st_blocks','st_mtime_ns','st_ctime_ns')}

# Read a complete bounded regular file twice and bind held and named physical bookends.
def read(path):
 assert path.resolve(strict=True)==path
 fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW)
 try:
  before=os.fstat(fd)
  assert stat.S_ISREG(before.st_mode)and before.st_uid==1000 and before.st_nlink==1 and 0<=before.st_size<=262144
  body=os.read(fd,262145);os.lseek(fd,0,os.SEEK_SET)
  assert os.read(fd,262145)==body and len(body)==before.st_size
  assert physical(before)==physical(os.fstat(fd))==physical(path.stat(follow_symlinks=False))
  return body,{'bytes':len(body),'sha256':hashlib.sha256(body).hexdigest(),'physical':physical(before)}
 finally:
  os.close(fd)

proof={'schema':'callback-symbol-DATA-observation/1','phase':phase,'mode':mode,'hostname':socket.gethostname(),'uid':os.getuid(),'python':sys.version,'observed_time_ns':str(time.time_ns()),'proposed_sources':expected,'wire_bytes':len(raw),'wire_sha256':hashlib.sha256(raw).hexdigest(),'reservation':False,'native_runtime_admission':None}
if mode=='prerequisite':
 assert not os.path.lexists(tools)and not os.path.lexists(output)
 available=None
 for line in pathlib.Path('/proc/meminfo').read_text().splitlines():
  fields=line.split()
  if fields and fields[0]=='MemAvailable:':
   assert len(fields)==3 and fields[2]=='kB'
   available=int(fields[1])*1024
 assert available is not None and available>=2147483648
 stats=os.statvfs(tools.parent)
 assert stats.f_bavail*stats.f_frsize>=33554432 and stats.f_favail>=512
 proof.update(MemAvailable_bytes=str(available),scratch_available_bytes=str(stats.f_bavail*stats.f_frsize),scratch_available_inodes=str(stats.f_favail),tools_root_absent=True,output_root_absent=True,remote_files_written=0)
else:
 assert mode=='receipts'and tools.resolve(strict=True)==tools and output.resolve(strict=True)==output
 observed={};retained={}
 targets=[(tools/'stage.json',True),(output/('summary.json'if phase=='primary'else'proof.json'),True)]+[(tools/name,False)for name in expected]
 for path,include in targets:
  body,row=read(path)
  if path.name in expected:
   assert row['sha256']==expected[path.name]
  observed[str(path)]=row
  if include:
   retained[str(path)]=dict(row,base64=base64.b64encode(body).decode('ascii'))
 for path,row in observed.items():
  assert read(pathlib.Path(path))[1]==row
 proof.update(input_inventory=observed,retained=retained,all_file_bookends_equal=True)
body=json.dumps(proof,sort_keys=True).encode()+b'\n'
assert len(body)<=262144
print(body.decode(),end='',flush=True)
signal.alarm(0)
'''.replace('EXPECTED_PINS', repr(pins)).replace('PHASE_VALUE', repr(phase)).replace('MODE_VALUE', repr(mode))


# Replace only three top-level constants while preserving the complete finite SSH owner functions.
def replace_constants(source, values):
    lines = source.splitlines(keepends=True)
    changes = []
    for name, value in values.items():
        nodes = [node for node in ast.parse(source).body if isinstance(node, ast.Assign)
            and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name) and node.targets[0].id == name]
        assert len(nodes) == 1
        node = nodes[0]
        literal = 'Path(' + repr(str(value)) + ')' if isinstance(value, Path) else repr(value)
        changes.append((node.lineno - 1, node.end_lineno, name + ' = ' + literal + '\n'))
    for start, end, body in sorted(changes, reverse=True):
        lines[start:end] = [body]
    return ''.join(lines)


# Compare complete outer function ASTs without evaluating either transport source.
def functions(value):
    return [ast.dump(n) for n in ast.parse(value).body if isinstance(n, ast.FunctionDef)]


# Build one exclusive proposed observation transport from exact existing source without invoking it.
def main():
    assert __debug__ and len(sys.argv) == 4
    phase, mode, destination = sys.argv[1], sys.argv[2], Path(sys.argv[3])
    assert phase in ('primary', 'independent') and mode in ('prerequisite', 'receipts')
    template = (HERE / 'callback-symbol-data-primary-transport-v1-2026-10-18.py').read_bytes()
    assert hashlib.sha256(template).hexdigest() == TEMPLATE_SHA
    target = (HERE / ('callback-symbol-data-' + phase + '-transport-v1-2026-10-18.py')).read_bytes()
    tree = ast.parse(target)
    pins = ast.literal_eval(next(n.value for n in tree.body if isinstance(n, ast.Assign)
        and any(isinstance(t, ast.Name) and t.id == 'PINS' for t in n.targets)))
    assert len(pins) == 2
    for name, sha in pins.items():
        body = (HERE / name).read_bytes()
        assert len(body) <= 262144 and hashlib.sha256(body).hexdigest() == sha
    boot = bootstrap(phase, mode, pins)
    ast.parse(boot)
    source = replace_constants(template.decode(), {'PINS': pins, 'BOOTSTRAP': boot,
        'LOCAL': Path('/tmp/callback-symbol-' + phase + '-' + mode + '-transport-20261018-v1')})
    source = source.replace('# Authenticate two reviewed operational sources and dispatch one retained-binary DATA operation.',
        '# Observe only fixed prerequisites or retained receipts through a bounded read-only SSH.')
    source = source.replace("'One reviewed retained-callback symbol/version DATA invocation; no native loading or old gates.'",
        "'One fixed read-only prerequisite or retained-receipt observation; no decoder execution.'")
    assert functions(template) == functions(source)
    destination.mkdir(mode=0o700, exist_ok=False)
    path = destination / ('callback-symbol-' + phase + '-' + mode + '-transport-v1-2026-10-18.py')
    with path.open('x') as output:
        output.write(source)
        output.flush()
        os.fsync(output.fileno())
    assert path.read_text() == source
    for directory in (destination, destination.resolve().parent):
        descriptor = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    print(json.dumps({'path': str(path), 'bytes': len(source.encode()),
        'sha256': hashlib.sha256(source.encode()).hexdigest(), 'source_sha256': pins}, sort_keys=True))


if __name__ == '__main__':
    main()
