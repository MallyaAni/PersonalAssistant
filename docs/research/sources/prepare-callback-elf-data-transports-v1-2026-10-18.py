"""Build new exact-source transports from a preserved operational transport SOURCE only."""
import ast
import hashlib
import json
import os
from pathlib import Path
import sys

BASE = Path(__file__).resolve().parent
TEMPLATE = BASE / 'callback-elf-synthetic-transport-v1-2026-10-18.py'
TEMPLATE_SHA = '777950f1bac4d9674518ce6a2e72d8398f6bdf9288c45e367e68c5867f325a19'
PHASES = {
    'primary': ('analyze-callback-elf-retained-v1-2026-10-18.py',
        'parse-callback-elf-data-v1-2026-10-18.py',
        'e5c8040315f3b471a4d35d2c90a82778a78954659d4b66e494d5b18abdf9edaf'),
    'independent': ('verify-callback-elf-retained-v1-2026-10-18.py',
        'fold-callback-elf-data-v1-2026-10-18.py',
        'f302196006bc47e3dd7c1a31aa9477d5119e6c18ac0cad015aa5efb302a34dc1'),
}


# Freeze a newly generated source with exact readback rather than replacing any previous path.
def retain(path, raw):
    with path.open('xb') as output:
        output.write(raw); output.flush(); os.fsync(output.fileno())
    assert path.read_bytes() == raw


# Build a fixed two-source Linux bootstrap with finite staging and new DATA-only invocation roots.
def bootstrap(phase, pins, driver):
    return f'''import base64,hashlib,json,os,pathlib,resource,signal,socket,sys
assert os.getuid()==1000 and socket.gethostname()=='animallya-spark1' and sys.platform=='linux' and not sys.flags.optimize
resource.setrlimit(resource.RLIMIT_AS,(536870912,536870912))
resource.setrlimit(resource.RLIMIT_CPU,(20,20))
resource.setrlimit(resource.RLIMIT_FSIZE,(262144,262144))
signal.alarm(30)
os.umask(0o077)
raw=sys.stdin.buffer.read(65537)
assert len(raw)<=65536
packet=json.loads(raw)
expected={pins!r}
assert type(packet)is dict and set(packet)==set(expected)
sources={{}}
for name,digest in expected.items():
 body=base64.b64decode(packet[name],validate=True)
 assert len(body)<=262144 and hashlib.sha256(body).hexdigest()==digest
 sources[name]=body
root=pathlib.Path('/home/animallya96/scratch/capacity-callback-elf-{phase}-tools-20261018-v1')
assert root.parent.resolve(strict=True)==root.parent and not os.path.lexists(root)
target=pathlib.Path('/home/animallya96/scratch/capacity-callback-elf-data-{'analysis' if phase == 'primary' else 'independent'}-20261018-v1')
assert not os.path.lexists(target)
available=None
for line in pathlib.Path('/proc/meminfo').read_text().splitlines():
 fields=line.split()
 if fields and fields[0]=='MemAvailable:':
  assert len(fields)==3 and fields[2]=='kB'
  available=int(fields[1])*1024
assert available is not None and available>=2147483648
stats=os.statvfs(root.parent)
assert stats.f_bavail*stats.f_frsize>=33554432 and stats.f_favail>=512
root.mkdir(mode=0o700,exist_ok=False)
for name,body in sources.items():
 with (root/name).open('xb')as output:
  output.write(body);output.flush();os.fsync(output.fileno())
 assert (root/name).read_bytes()==body
proof=json.dumps({{'scope':'RETAINED_CALLBACK_ELF_DATA_ONLY','phase':{phase!r},'source_sha256':expected,'MemAvailable_bytes':str(available),'scratch_available_bytes':str(stats.f_bavail*stats.f_frsize),'scratch_available_inodes':str(stats.f_favail),'headroom_is_reservation':False,'python':sys.version,'hostname':socket.gethostname(),'uid':os.getuid()}},sort_keys=True).encode()
with (root/'stage.json').open('xb')as output:
 output.write(proof);output.flush();os.fsync(output.fileno())
assert (root/'stage.json').read_bytes()==proof
for directory in (root,root.parent):
 fd=os.open(directory,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW);os.fsync(fd);os.close(fd)
print(proof.decode(),flush=True)
signal.alarm(0)
path=root/{driver!r}
exec(compile(sources[path.name],str(path),'exec',dont_inherit=True),{{'__name__':'__main__','__file__':str(path)}})
'''


# Replace only whole top-level constant statements while preserving all operational transport function ASTs.
def replace_constants(text, values):
    tree = ast.parse(text)
    lines = text.splitlines(keepends=True)
    changes = []
    for name, value in values.items():
        matches = [node for node in tree.body if isinstance(node, ast.Assign)
            and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name)
            and node.targets[0].id == name]
        assert len(matches) == 1
        node = matches[0]
        literal = 'Path(' + repr(str(value)) + ')' if isinstance(value, Path) else repr(value)
        changes.append((node.lineno - 1, node.end_lineno, name + ' = ' + literal + '\n'))
    first = tree.body[0]
    assert isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant)
    changes.append((first.lineno - 1, first.end_lineno,
        repr('One reviewed retained-callback ELF DATA invocation; no native loading or old gates.') + '\n'))
    for start, end, new in sorted(changes, reverse=True):
        lines[start:end] = [new]
    text = ''.join(lines)
    old = '# Authenticate four operational sources and dispatch one synthetic-only Linux attempt without retries.'
    assert text.count(old) == 1
    return text.replace(old, '# Authenticate two reviewed operational sources and dispatch one retained-binary DATA operation.')


# Prepare one new transport and prove unchanged transport functions without importing or running any decoder.
def main():
    assert __debug__ and len(sys.argv) == 3 and sys.argv[1] in PHASES
    phase, output_dir = sys.argv[1], Path(sys.argv[2])
    old_raw = TEMPLATE.read_bytes()
    assert hashlib.sha256(old_raw).hexdigest() == TEMPLATE_SHA and len(old_raw) == 9163
    driver, decoder, decoder_sha = PHASES[phase]
    controls = {name: (BASE / name).read_bytes() for name in (driver, decoder)}
    assert all(len(body) <= 262144 for body in controls.values())
    assert hashlib.sha256(controls[decoder]).hexdigest() == decoder_sha
    pins = {name: hashlib.sha256(body).hexdigest() for name, body in controls.items()}
    boot = bootstrap(phase, pins, driver)
    ast.parse(boot)
    text = replace_constants(old_raw.decode(), {
        'LOCAL': Path('/tmp/callback-elf-data-' + phase + '-transport-20261018-v1'),
        'PINS': pins, 'BOOTSTRAP': boot})
    old_tree, new_tree = ast.parse(old_raw), ast.parse(text)
    old_functions = [ast.dump(n, include_attributes=False) for n in old_tree.body if isinstance(n, ast.FunctionDef)]
    new_functions = [ast.dump(n, include_attributes=False) for n in new_tree.body if isinstance(n, ast.FunctionDef)]
    assert old_functions == new_functions and len(old_functions) == 3
    raw = text.encode()
    assert len(raw) <= 262144
    output_dir.mkdir(mode=0o700, exist_ok=False)
    name = 'callback-elf-data-' + phase + '-transport-v1-2026-10-18.py'
    retain(output_dir / name, raw)
    for filename, body in controls.items():
        retain(output_dir / filename, body)
    for directory in (output_dir, output_dir.resolve().parent):
        descriptor = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        os.fsync(descriptor); os.close(descriptor)
    print(json.dumps({'transport': str(output_dir / name), 'sha256': hashlib.sha256(raw).hexdigest(),
        'bytes': len(raw), 'source_sha256': pins, 'unchanged_function_ASTs': 3}))


if __name__ == '__main__':
    main()
