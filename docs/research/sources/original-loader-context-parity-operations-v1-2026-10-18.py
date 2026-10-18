"""One pinned-key transport/staging and explicit reviewed native/synthetic/read-only operations."""
import hashlib
import json
import os
import resource
import shlex
import subprocess
import sys
import types
from pathlib import Path

REPO = Path('/Users/animallya/.codex/worktrees/learned-live-release-20261006/PersonalAssistant')
LOCAL = Path('/tmp/capacity-context-parity-operations-20261018-v1')
BASE = '/home/animallya96/scratch/'
TOOLS = BASE + 'capacity-context-parity-tools-source-20261018-v1'
TRANSFER = BASE + 'capacity-context-parity-transfer-20261018-v1'
SOURCE = BASE + 'capacity-context-parity-source-20261018-v1'
BOOK = '371af1dfa4fb82fea78888044cb7165c266bf50f16fc17752c52ebf363224f33'
PACKET = 'dfd903f31677b5945ae8fceafb25990b237d8780a5060f9469acc064d133f772'
MAPPING = {
    'preflight.py': 'original-loader-context-parity-preflight-v1-2026-10-18.py',
    'launch.py': 'original-loader-context-parity-launch-v1-2026-10-18.py',
    'native-audit/bootstrap.py': 'original-loader-context-native-probe-v1-2026-10-18.py',
    'verifier.py': 'original-loader-context-parity-verifier-v2-2026-10-18.py',
    'preserver.py': 'original-loader-context-parity-preserver-v2-2026-10-18.py',
    'stager.py': 'original-loader-context-parity-stager-v1-2026-10-18.py'}


# Identify complete source bytes for every transport, runtime and independent-review binding.
def sha(raw):
    return hashlib.sha256(raw).hexdigest()


# Load only the pinned transport constants without calling any earlier operation or test main.
def transport():
    path = Path('/tmp/n2_guard_packet_owner_20261018_v3.py')
    raw = path.read_bytes()
    assert sha(raw) == 'f8e6fcb47bff6c2f190295ddd2bd63308b7384a10734b422daed5e07c300c4db'
    module = types.ModuleType('context_pinned_transport_constants')
    exec(compile(raw, str(path), 'exec', dont_inherit=True), module.__dict__)
    assert module.TRUSTED.read_bytes() == module.KEYS
    return module


# Bound each local transport log without changing any remote model or daemon limit.
def limits():
    resource.setrlimit(resource.RLIMIT_FSIZE, (262144, 262144))


# Own one finite SSH operation with exact pinned host keys and durable actual child exit.
def remote(name, arguments, body=b'', timeout=55):
    module = transport()
    assert len(body) <= 2097152 and name and '/' not in name
    command = ['ssh', '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=yes', '-o', 'HostKeyAlgorithms=ssh-ed25519',
        '-o', 'ConnectTimeout=10', '-o', 'ServerAliveInterval=15', '-o', 'ServerAliveCountMax=2',
        '-o', 'GlobalKnownHostsFile=/dev/null', '-o', 'UserKnownHostsFile=' + str(module.TRUSTED),
        'animallya96@172.16.8.3', shlex.join(arguments)]
    stdout, stderr = (LOCAL / (name + '.stdout')).open('xb'), (LOCAL / (name + '.stderr')).open('xb')
    process, stopped = None, None
    try:
        process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=stdout, stderr=stderr, preexec_fn=limits)
        process.communicate(input=body, timeout=timeout)
    finally:
        if process is not None and process.poll() is None:
            stopped = 'TERM'
            process.terminate()
            try:
                process.wait(timeout=1)
            except subprocess.TimeoutExpired:
                stopped = 'KILL'
                process.kill()
                process.wait(timeout=1)
        for output in (stdout, stderr):
            output.flush()
            os.fsync(output.fileno())
            output.close()
        receipt = json.dumps({'pid': None if process is None else str(process.pid), 'exit': None if process is None else process.returncode,
            'owned_stop': stopped, 'arguments': arguments, 'timeout_seconds': timeout}, sort_keys=True).encode()
        with (LOCAL / (name + '.exit.json')).open('xb') as output:
            output.write(receipt)
            output.flush()
            os.fsync(output.fileno())
    raw, error = (LOCAL / (name + '.stdout')).read_bytes(), (LOCAL / (name + '.stderr')).read_bytes()
    assert len(raw) <= 262144 and len(error) <= 262144
    print(json.dumps({'operation': name, 'exit': process.returncode, 'owned_stop': stopped,
        'stdout': {'sha256': sha(raw), 'bytes': len(raw)} if name.startswith('fetch-') else raw.decode(),
        'stderr': error.decode()}, sort_keys=True), flush=True)
    assert stopped is None and process.returncode == 0 and not error
    return raw


# Invoke only one exact staged helper source under isolated Python with explicit arguments.
def invocation(name, pin, arguments):
    path = TOOLS + '/' + name
    return "import hashlib,pathlib,sys; p=pathlib.Path(" + repr(path) + "); raw=p.read_bytes(); assert len(raw)<=262144 and hashlib.sha256(raw).hexdigest()==" + repr(pin) + "; sys.argv=[str(p)]+" + repr(arguments) + "; exec(compile(raw,str(p),'exec',dont_inherit=True),{'__name__':'__main__','__file__':str(p)})"


# Stage tools and the existing immutable compressed-source packet once without application execution.
def stage():
    LOCAL.mkdir(mode=0o700, exist_ok=False)
    files = {name: (REPO / 'docs/research/sources' / original).read_bytes() for name, original in MAPPING.items()}
    files['operations.py'] = Path(__file__).read_bytes()
    files['query-library.py'] = Path('/tmp/n2_guard_prerequisites_20261018_v3.py').read_bytes()
    assert sha(files['query-library.py']) == '8d3f17d41e5b13b98e697138facadb3f00fe68e5822130fc9d4ad2b5929acc38'
    assert sha(files['verifier.py']) == 'c2abab9db6b347d0a7e34bed0b85df05b4c7487539c89ebe07e1797633f2f48e'
    assert sha(files['preserver.py']) == 'cf772f8dc17b4f7e325f50d463e2ea79abeb1e25561e8929aae8f5b992f56329'
    assert sha(files['stager.py']) == '7cfef0ebd7b2b53cf7032b9e063c2d03d5d866385577539ac66e942700aad4b5'
    assert all(len(raw) <= 262144 for raw in files.values())
    book = {'schema': 'capacity-context-parity-tools/1', 'files': {name: {'sha256': sha(raw), 'bytes': len(raw)} for name, raw in sorted(files.items())}}
    book_raw = json.dumps(book, sort_keys=True, indent=2).encode() + b'\n'
    with (LOCAL / 'tools-book.json').open('xb') as output:
        output.write(book_raw)
        output.flush()
        os.fsync(output.fileno())
    payload = json.dumps({**{name: raw.hex() for name, raw in files.items()}, 'source-book.json': book_raw.hex()}, sort_keys=True).encode()
    assert len(payload) <= 2097152
    code = "import hashlib,json,os,pathlib,socket,sys; raw=sys.stdin.buffer.read(2097153); assert len(raw)<=2097152 and hashlib.sha256(raw).hexdigest()==" + repr(sha(payload)) + "; root=pathlib.Path(" + repr(TOOLS) + "); transfer=pathlib.Path(" + repr(TRANSFER) + "); assert os.getuid()==1000 and socket.gethostname()=='animallya-spark1' and root.parent.resolve(strict=True)==root.parent; transfer.mkdir(mode=0o700,exist_ok=False); root.mkdir(mode=0o700,exist_ok=False); files=json.loads(raw)\nfor name,text in files.items():\n p=root/name; assert not pathlib.PurePosixPath(name).is_absolute() and '..' not in pathlib.PurePosixPath(name).parts; body=bytes.fromhex(text); assert len(body)<=262144; p.parent.mkdir(mode=0o700,parents=True,exist_ok=True); f=p.open('xb'); f.write(body); f.flush(); os.fsync(f.fileno()); f.close(); assert p.read_bytes()==body\nfor p in (root/'native-audit',root,transfer,root.parent):\n fd=os.open(p,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW); os.fsync(fd); os.close(fd)\nprint(json.dumps({name:hashlib.sha256(bytes.fromhex(text)).hexdigest() for name,text in files.items()},sort_keys=True))"
    uploaded = json.loads(remote('tools-stage', ['python3', '-I', '-S', '-B', '-c', code], payload))
    assert uploaded == {**{name: sha(raw) for name, raw in files.items()}, 'source-book.json': sha(book_raw)}
    packet = Path('/tmp/capacity-context-parity-packet-20261018-v1/packet.json').read_bytes()
    assert sha(packet) == PACKET and len(packet) == 903267
    receiver = "import hashlib,os,pathlib,sys; raw=sys.stdin.buffer.read(2097153); assert len(raw)==903267 and hashlib.sha256(raw).hexdigest()==" + repr(PACKET) + "; p=pathlib.Path(" + repr(TRANSFER + '/packet.json') + "); f=p.open('xb'); f.write(raw); f.flush(); os.fsync(f.fileno()); f.close(); assert p.read_bytes()==raw; fd=os.open(p.parent,os.O_RDONLY|os.O_DIRECTORY); os.fsync(fd); os.close(fd); print(hashlib.sha256(raw).hexdigest())"
    assert remote('packet-transfer', ['python3', '-I', '-S', '-B', '-c', receiver], packet).decode().strip() == PACKET
    remote('source-stage', ['python3', '-I', '-S', '-B', '-c', invocation('stager.py', book['files']['stager.py']['sha256'],
        ['--stage-context-source', TRANSFER + '/packet.json', PACKET])])
    print(json.dumps({'tools_book_sha256': sha(book_raw), 'source_book_sha256': BOOK, 'packet_sha256': PACKET, 'payload_execution': False}, sort_keys=True))


# Dispatch one exact admitted or read-only helper route using the immutable local tools book.
def run(route, arguments):
    book_raw = (LOCAL / 'tools-book.json').read_bytes()
    book = json.loads(book_raw)
    tool_sha = sha(book_raw)
    if route in ('prerequisites', 'native-fold'):
        name = 'preflight.py'
        pin = book['files'][name]['sha256']
        args = [route, pin, tool_sha]
    elif route in ('native', 'parity'):
        name = 'launch.py'
        pin = book['files'][name]['sha256']
        args = [route, pin, tool_sha] + arguments
    elif route == 'terminal':
        name = 'verifier.py'
        pin = book['files'][name]['sha256']
        args = ['--review-context-parity', pin, BOOK] + arguments
    else:
        assert route in ('preserve', 'copy-review')
        name = 'preserver.py'
        pin = book['files'][name]['sha256']
        args = ['--preserve-context-parity' if route == 'preserve' else '--review-context-preservation', pin] + arguments
    remote(route, ['python3', '-I', '-S', '-B', '-c', invocation(name, pin, args)], timeout=240)


# Fetch one bounded raw receipt by exact physical path without replaying the work it describes.
def fetch(name, path):
    code = "import pathlib,sys; p=pathlib.Path(" + repr(path) + "); assert p.resolve(strict=True)==p and p.stat().st_size<=262144; raw=p.read_bytes(); assert len(raw)<=262144; sys.stdout.buffer.write(raw)"
    raw = remote('fetch-' + name, ['python3', '-I', '-S', '-B', '-c', code])
    print(json.dumps({'local': str(LOCAL / ('fetch-' + name + '.stdout')), 'sha256': sha(raw), 'bytes': len(raw)}, sort_keys=True))


# Refuse unspecified operations and keep every admitted launch separate from staging and prerequisite review.
def main(arguments):
    if arguments == ['stage']:
        stage()
    elif len(arguments) == 3 and arguments[0] == 'fetch':
        fetch(arguments[1], arguments[2])
    elif arguments and ((arguments[0] in ('prerequisites', 'native-fold') and len(arguments) == 1) or
        (arguments[0] in ('native', 'terminal', 'preserve', 'copy-review') and len(arguments) == 2) or
        (arguments[0] == 'parity' and len(arguments) == 3)):
        run(arguments[0], arguments[1:])
    else:
        raise SystemExit('NO_CONTEXT_PARITY_OPERATION_ROUTE')


if __name__ == '__main__':
    main(sys.argv[1:])
