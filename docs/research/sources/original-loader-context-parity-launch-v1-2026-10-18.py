"""Fresh separate native metadata and synthetic73 admissions; no genuine launch route."""
import hashlib
import json
import os
import signal
import socket
import sys
import types
from pathlib import Path

BASE = Path('/home/animallya96/scratch')
SOURCE = BASE / 'capacity-context-parity-source-20261018-v1'
TOOLS = BASE / 'capacity-context-parity-tools-source-20261018-v1'
TRANSFER = BASE / 'capacity-context-parity-transfer-20261018-v1'
PRE = BASE / 'capacity-context-parity-prerequisites-20261018-v1'
NATIVE = BASE / 'capacity-context-native-probe-20261018-v1'
NATIVE_REVIEW = BASE / 'capacity-context-native-probe-review-20261018-v1'
RUN = BASE / 'capacity-context-parity-20261018-v1'
BOOK = '371af1dfa4fb82fea78888044cb7165c266bf50f16fc17752c52ebf363224f33'
OWNER = '3baa6ecd4a5ed0228bfc921b0089d9d65ab60be753588b2a1d548d5eb7a0bb69'
CALLER = 'd3e0d8eb4857a0ebbcff38c5b8c72cf087860f56bced8f14bc298f68a2293a5f'
CONTROLLER = '2e505205cc8a3793d7b3313a5b5c3b670b00134575982d26c725787b6530df5a'
IMAGE = 'sha256:e0a54c1f3b293c241ea0eae767d8ba017d0e1a05679965935b336910faa63237'


# Read the externally SHA-bound tool map and bind one exact utility without dispatching its main.
def helper(name, tools_sha):
    raw = (TOOLS / 'source-book.json').read_bytes()
    assert len(raw) <= 262144 and hashlib.sha256(raw).hexdigest() == tools_sha
    item = json.loads(raw)['files'][name]
    path = TOOLS / name
    body = path.read_bytes()
    assert len(body) == item['bytes'] <= 262144 and hashlib.sha256(body).hexdigest() == item['sha256']
    module = types.ModuleType('context_launch_' + path.stem)
    module.__file__ = str(path)
    exec(compile(body, str(path), 'exec', dont_inherit=True), module.__dict__)
    return module


# Require all source and tool bytes to match their independently observed physical prerequisites.
def prerequisite(metadata, tools_sha, expected):
    prior = json.loads(metadata.read(PRE / 'proof.json', expected)[0])
    assert prior['status'] == 'VERIFIED_SOURCE_IMAGE_HOST_ONLY_ALL73_AND_NATIVE_UNRUN'
    assert prior['source_book_sha256'] == BOOK and prior['tools_book_sha256'] == tools_sha
    assert metadata.source_fold(tools_sha) == prior['source_physical']
    return prior


# Admit exactly one isolated new NumPy metadata container after fresh actual prerequisite review.
def native(metadata, tools_sha, prerequisite_sha, self_sha):
    prerequisite(metadata, tools_sha, prerequisite_sha)
    raw, source_identity = metadata.read(TOOLS / 'native-audit/bootstrap.py')
    assert [p.name for p in (TOOLS / 'native-audit').iterdir()] == ['bootstrap.py']
    host, evidence = metadata.fresh(TRANSFER / 'native-admission', NATIVE)
    review_sha = hashlib.sha256(b'CONTEXT73_NATIVE_METADATA_ONLY\0' + raw).hexdigest()
    admission_sha = metadata.save(TRANSFER / 'native-admission/admission.json', {
        'scope': 'CONTEXT73_NUMPY_METADATA_ONLY', 'launch_sha256': self_sha, 'prerequisite_sha256': prerequisite_sha,
        'tools_book_sha256': tools_sha, 'review_sha256': review_sha, 'observed_at_ns': host['observed_at_ns'],
        'host': host, 'host_evidence': evidence, 'genuine_or_parity_execution': False})
    controller = metadata.library(SOURCE / 'owner/controller.py', CONTROLLER)
    signal.signal(signal.SIGALRM, controller.alarm)
    for signum in (signal.SIGHUP, signal.SIGINT, signal.SIGTERM):
        signal.signal(signum, controller.alarm)
    signal.setitimer(signal.ITIMER_REAL, 120)
    owner = None
    try:
        owner = controller.Owner(NATIVE, TOOLS / 'native-audit', review_sha)
        controller.save(NATIVE / 'source-before.json', controller.encode(source_identity))
        output = NATIVE / 'output'
        output.mkdir(mode=0o700)
        cid = owner.phase('prepare', [(str(TOOLS / 'native-audit'), '/audit', False), (str(output), '/out', True)], ['diagnose'], timeout=60)
        assert metadata.read(TOOLS / 'native-audit/bootstrap.py')[1] == source_identity
        controller.save(NATIVE / 'source-after.json', controller.encode(source_identity))
        controller.save(NATIVE / 'terminal.json', controller.encode({'status': 'CONTEXT_NUMPY_METADATA_ONLY_NOT_PARITY_ACCEPTANCE',
            'cid': cid, 'review_sha256': review_sha, 'admission_sha256': admission_sha, 'tools_book_sha256': tools_sha}))
        print(json.dumps({'admission_sha256': admission_sha, 'cid': cid, 'resources': host, 'parity_executed': False}, sort_keys=True), flush=True)
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        if owner is not None:
            owner.cleanup()


# Consume a separate fresh synthetic73 admission only after independent native metadata review.
def parity(metadata, tools_sha, prerequisite_sha, native_sha, self_sha):
    prerequisite(metadata, tools_sha, prerequisite_sha)
    native_raw = metadata.read(NATIVE_REVIEW / 'proof.json', native_sha)[0]
    native_proof = json.loads(native_raw)
    assert native_proof['status'] == 'VERIFIED_NATIVE_METADATA_ONLY' and native_proof['genuine_or_parity_acceptance'] is False
    assert native_proof['source_physical'] == metadata.source_fold(tools_sha)
    metadata.read(SOURCE / 'source-book.json', BOOK)
    metadata.read(SOURCE / 'owner/context-owner.py', OWNER)
    caller_raw = metadata.read(SOURCE / 'owner/caller.py', CALLER)[0]
    root = SOURCE / 'admission'
    host, evidence = metadata.fresh(root, RUN)
    native_observation_sha = metadata.save(root / 'native-observation.json', native_proof)
    evidence.append({'path': str(root / 'native-observation.json'), 'sha256': native_observation_sha})
    admission_sha = metadata.save(root / 'admission.json', {'schema': 'capacity-context-parity-admission/1',
        'scope': 'ONE_NEW_SYNTHETIC73_CONTEXT_CALENDAR_AND_EXPLICIT_UNITS_ONLY', 'observed_at_ns': host['observed_at_ns'],
        'host': host['host'], 'uid': 1000, 'source_book_sha256': BOOK, 'owner_sha256': OWNER,
        'run_root': str(RUN), 'image': IMAGE, 'host_evidence': evidence, 'genuine_execution_authorized': False})
    arguments = ['--call-admitted-context-parity', OWNER, BOOK, admission_sha]
    metadata.save(root / 'launch-binding.json', {'launch_sha256': self_sha, 'tools_book_sha256': tools_sha,
        'prerequisite_sha256': prerequisite_sha, 'native_proof_sha256': native_sha,
        'native_observation_sha256': native_observation_sha, 'caller_sha256': CALLER, 'caller_arguments': arguments, 'genuine_execution': False})
    caller = types.ModuleType('new_exact_context73_caller')
    caller.__file__ = str(SOURCE / 'owner/caller.py')
    exec(compile(caller_raw, caller.__file__, 'exec', dont_inherit=True), caller.__dict__)
    caller.main(arguments)
    print(json.dumps({'admission_sha256': admission_sha, 'resources': host, 'native_proof_sha256': native_sha,
        'genuine_execution': False}, sort_keys=True), flush=True)


# Expose only exact self/source-pinned native or synthetic routes after independent prerequisite review.
def main(arguments):
    assert len(arguments) in (4, 5) and arguments[0] in ('native', 'parity')
    route, self_sha, tools_sha, prerequisite_sha = arguments[:4]
    assert os.getuid() == 1000 and socket.gethostname() == 'animallya-spark1'
    metadata = helper('preflight.py', tools_sha)
    metadata.read(Path(__file__), self_sha)
    if route == 'native':
        assert len(arguments) == 4
        native(metadata, tools_sha, prerequisite_sha, self_sha)
    else:
        assert len(arguments) == 5
        parity(metadata, tools_sha, prerequisite_sha, arguments[4], self_sha)


if __name__ == '__main__':
    main(sys.argv[1:])
