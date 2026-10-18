"""UNEXECUTED pinned caller proposal for the synthetic-only source package.

The default script entry point refuses. Its sole proposed activation route
requires an exact self SHA and fresh external synthetic admission. Packet SHA
alone authenticates source bytes; it is never runtime admission.
"""

import base64
import hashlib
import json
import os
import sys
import time
import types
from pathlib import Path

FINGERPRINT = {'algorithm': 'cpython-code-marshal-format-2-sha256/1', 'marshal_version': 2}
HARNESS_SHA = '030cb5bb25f89c2785e6acbd55aceff5c99b632a5eb538079ee027362ae6178a'
MANIFEST_SCHEMA = 'n2-capacity-call-manifest/2'



# Name full finite source or acceptance records without application imports.
def sha(raw):
    return hashlib.sha256(raw).hexdigest()


# Reject duplicate external declaration fields before loading any helper.
def unique(pairs):
    result = {}
    for key, value in pairs:
        assert key not in result
        result[key] = value
    return result


# Reject nonfinite declaration tokens rather than interpreting them as facts.
def nonfinite(value):
    raise ValueError('NONFINITE_CALLER_METADATA')


# Parse only bounded finite duplicate-free external source or admission metadata.
def metadata(raw, limit):
    assert len(raw) <= limit
    return json.loads(raw, object_pairs_hook=unique, parse_constant=nonfinite)


# Load only held bytes pinned by an external source packet into a private module.
def helper(name, raw, expected):
    assert len(raw) <= 262144 and sha(raw) == expected and not name.startswith('backend')
    module = types.ModuleType(name)
    sys.modules[name] = module
    exec(compile(raw, '<pinned-' + name + '>', 'exec', dont_inherit=True, optimize=0), module.__dict__)
    return module


# Require a narrow fresh synthetic admission declaration without creating one.
def admission(path, expected, packet_sha, stage_root, run_root):
    raw = path.read_bytes()
    assert len(raw) <= 262144 and sha(raw) == expected
    value = metadata(raw, 262144)
    assert value['schema'] == 'n2-guard-synthetic-admission/3'
    assert value['scope'] == 'SYNTHETIC_ONLY_NOT_GENUINE_LOADER'
    assert value['guard_manifest_schema'] == MANIFEST_SCHEMA and value['generated_fingerprint'] == FINGERPRINT
    assert value['packet_sha256'] == packet_sha and value['stage_root'] == str(stage_root) and value['run_root'] == str(run_root)
    assert value['host'] == os.uname().nodename and value['uid'] == os.getuid() == 1000
    assert type(value['observed_at_ns']) is str and value['observed_at_ns'].isdecimal()
    assert 0 <= time.time_ns() - int(value['observed_at_ns']) <= 120 * 1000000000
    assert value['image'] == 'sha256:e0a54c1f3b293c241ea0eae767d8ba017d0e1a05679965935b336910faa63237'
    assert value['source_review_complete'] is True and value['runtime_admitted'] is True
    assert value['genuine_loader_authorized'] is False and value['production_mutation_authorized'] is False
    # External host evidence must accompany the declaration. The future ROOT
    # must review its contents; these hashes cannot turn declarations into proof.
    assert type(value['host_evidence']) is list and len(value['host_evidence']) == 2
    assert {Path(item['path']).name for item in value['host_evidence']} == {'runtime-image.json', 'host-resources.json'}
    for item in value['host_evidence']:
        assert set(item) == {'path', 'sha256'}
        evidence = Path(item['path'])
        assert evidence.resolve(strict=True) == evidence and evidence.is_file()
        assert evidence.stat().st_size <= 262144
        descriptor = os.open(evidence, os.O_RDONLY | os.O_NOFOLLOW)
        try:
            before = os.fstat(descriptor)
            body = os.read(descriptor, 262145)
            assert os.read(descriptor, 1) == b'' and len(body) == before.st_size <= 262144
            after = os.fstat(descriptor)
            named = evidence.stat(follow_symlinks=False)
            assert (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns) == (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns) == (named.st_dev, named.st_ino, named.st_size, named.st_mtime_ns, named.st_ctime_ns)
            assert sha(body) == item['sha256']
        finally:
            os.close(descriptor)
    return value


# Stage exact small sources, run the separately admitted proposal once and verify.
def proposed_call(packet_path, packet_sha, stage_root, run_root, admission_path, admission_sha):
    assert sys.flags.isolated and sys.flags.no_site and sys.flags.dont_write_bytecode and not sys.flags.optimize
    assert not any(name == 'backend' or name.startswith('backend.') for name in sys.modules)
    assert stage_root.is_absolute() and run_root.is_absolute() and stage_root.parent == run_root.parent
    assert stage_root != run_root and not stage_root.is_relative_to(run_root) and not run_root.is_relative_to(stage_root)
    admission(admission_path, admission_sha, packet_sha, stage_root, run_root)
    packet_raw = packet_path.read_bytes()
    assert len(packet_raw) <= 2 * 1024 ** 2 and sha(packet_raw) == packet_sha
    packet = metadata(packet_raw, 2 * 1024 ** 2)
    stage_record = packet['files']['stage.py']
    stage_raw = base64.b64decode(stage_record['base64'], validate=True)
    stage = helper('guard_source_stage', stage_raw, stage_record['sha256'])
    receipt = stage.stage(stage_root, packet_raw, packet_sha)
    controller_record = packet['files']['owner/controller.py']
    controller_raw = (stage_root / 'owner/controller.py').read_bytes()
    controller = helper('guard_source_owner', controller_raw, controller_record['sha256'])
    verifier_record = packet['files']['owner/verifier.py']
    verifier_raw = (stage_root / 'owner/verifier.py').read_bytes()
    verifier = helper('guard_independent_verifier', verifier_raw, verifier_record['sha256'])
    controller.proposed_run(run_root, stage_root / 'audit', receipt['review_sha256'])
    review_root = run_root.parent / (run_root.name + '-independent-review-v3')
    result = verifier.verify(run_root, stage_root, packet_sha, review_root)
    raw = json.dumps(result, sort_keys=True, indent=2, allow_nan=False).encode() + b'\n'
    assert len(raw) <= 2 * 1024 ** 2
    stage.write(review_root / 'proof.json', raw)
    return {'scope': 'SYNTHETIC_ONLY', 'independent_proof_sha256': sha(raw), 'independent_proof_path': str(review_root / 'proof.json'), 'genuine_loader': False, 'combined_model_memory': False}


# Expose one explicit synthetic route only after self/source/admission pinning.
def main(arguments):
    if len(arguments) != 8 or arguments[0] != '--admitted-synthetic-v3':
        raise SystemExit('SOURCE_ONLY_NO_SOURCE_PACKET_OR_FRESH_SYNTHETIC_ADMISSION')
    flag, packet_path, packet_sha, stage_root, run_root, admission_path, admission_sha, self_sha = arguments
    source = Path(__file__)
    assert source.resolve(strict=True) == source and source.stat().st_size <= 262144
    assert sha(source.read_bytes()) == self_sha
    return proposed_call(Path(packet_path), packet_sha, Path(stage_root), Path(run_root), Path(admission_path), admission_sha)


if __name__ == '__main__':
    main(sys.argv[1:])
