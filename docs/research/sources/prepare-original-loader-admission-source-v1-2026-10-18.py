"""Prepare separately named admission source and static parity/lifetime contracts only."""
import ast
import copy
import hashlib
import json
import pathlib
import subprocess

ROOT = pathlib.Path(__file__).resolve().parents[3]
RESEARCH = ROOT / 'docs/research'
SOURCES = RESEARCH / 'sources'
CLI = ROOT / 'backend/cli/audit_original_live_model_history.py'
ADMISSIONS = SOURCES / 'original-loader-capacity-admissions-v1-2026-10-18.py'
LIFECYCLE = SOURCES / 'original-loader-capacity-admission-lifecycle-v1-2026-10-18.py'
CALENDAR = SOURCES / 'original-loader-capacity-calendar-v1-2026-10-18.py'


# Identify source bytes without executing or importing the declared payload.
def pin(raw):
    return {'sha256': hashlib.sha256(raw).hexdigest(), 'bytes': len(raw)}


# Fingerprint exact declaration content independently of source positions.
def fingerprint(node):
    return hashlib.sha256(ast.dump(node, include_attributes=False).encode()).hexdigest()


# Identify exact sorted compact file-map content without treating it as an execution receipt.
def compact(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


# Select a unique top-level source declaration for explicit new-file copying.
def select(tree, name):
    nodes = [node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.Assign)) and (getattr(node, 'name', None) == name or any(isinstance(target, ast.Name) and target.id == name for target in getattr(node, 'targets', [])))]
    assert len(nodes) == 1, name
    return nodes[0]


# Write only a new or exactly identical artifact, never replace a different checkpoint.
def save(path, raw):
    if path.exists():
        assert path.read_bytes() == raw, str(path)
    else:
        with path.open('xb') as output:
            output.write(raw)
    assert path.read_bytes() == raw
    return pin(raw)


# Serialize finite source artifacts without loss of integer precision or intentional bytes.
def save_json(path, value):
    return save(path, json.dumps(value, sort_keys=True, indent=2, allow_nan=False).encode() + b'\n')


# Copy admission bodies as a new real module, then inventory explicit changes and limits.
def main():
    original_raw = CLI.read_bytes()
    assert pin(original_raw)['sha256'] == '22d374f166b77d4b0346120aa55b3f9e652496503b88d3fae0681be04b9ab5d5'
    original_text = original_raw.decode()
    tree = ast.parse(original_text)
    header = '''"""UNEXECUTED new admission module; copied source is not the original CLI identity.

No old effect module import, runtime projection, model loading or executor exists.
Calendar/package imports are deferred and still need separately admitted closure.
"""
import os
import socket
from pathlib import Path

from backend.market import live_model_history_input_auth as byte_auth
from backend.market.capacity_original_evidence_v1 import authenticate_file, pinned, require, strict_json
from backend.market.capacity_original_archive_adaptations_v1 import logical_digest as digest
'''
    names = ('IMAGE', 'FULL_REVISION', 'FULL_CONTAINER', 'PRODUCER_IMAGE', 'FULL_ACCOUNT', 'SCHEMA', 'FULL_PHYSICAL_SHA256', 'FULL_PHYSICAL_BYTES', 'FULL_COMPLETION_BYTES', 'FULL_COMPLETION_SHA256')
    parts = [header] + [ast.get_source_segment(original_text, select(tree, name)) for name in names]
    purposes = {
        'invocation': 'Decode only the unchanged original externally pinned schema2 invocation.',
        'runtime_admission': 'Retain exact original runtime and read-only input/proof mount checks.',
        'source_admission': 'Authenticate the legacy audit-source/Git map separately from new executor bytes.',
        'producer_admission': 'Retain exact completed producer image, command, mounts and original output mapping.',
        'calendar_admission': 'Apply original calendar checks through an explicit new reviewed-session module.',
    }
    for name, purpose in purposes.items():
        source = ast.get_source_segment(original_text, select(tree, name))
        if name == 'calendar_admission':
            first, rest = source.split('\n', 1)
            source = first + '\n    import numpy as np\n    from backend.market import capacity_original_calendar_v1 as calendar\n    require(Path(calendar.__file__).resolve().parents[2] == archives.source_root, "CAPACITY_CALENDAR_IMPORT_ROOT_REQUIRED")\n' + rest
        parts.append('# ' + purpose + '\n' + source)
    parts.append('''# Check the unchanged exact native package versions without fitting or loading a model.
def native_packages():
    import numpy as np
    import sklearn
    require(np.__version__ == '2.5.3' and sklearn.__version__ == '1.9.1', 'EXACT_NATIVE_NUMERIC_PACKAGES_REQUIRED')
    return {'numpy': np.__version__, 'sklearn': sklearn.__version__, 'model_or_fit': False}
''')
    raw = ('\n\n'.join(parts) + '\n').encode()
    admissions_pin = save(ADMISSIONS, raw)
    candidate = ast.parse(raw)
    comparisons = {}
    for name in purposes:
        old = select(tree, name)
        new = select(candidate, name)
        normalized = copy.deepcopy(new)
        if name == 'calendar_admission':
            assert isinstance(normalized.body[0], ast.Import) and isinstance(normalized.body[1], ast.ImportFrom) and isinstance(normalized.body[2], ast.Expr)
            normalized.body = normalized.body[3:]
        assert fingerprint(old) == fingerprint(normalized), name
        comparisons[name] = {'original_AST': fingerprint(old), 'new_AST': fingerprint(new), 'exact_after_declared_calendar_prefix_only': True}
    calendar_raw = CALENDAR.read_bytes()
    real_calendar = (ROOT / 'backend/market/calendar.py').read_bytes()
    assert pin(real_calendar)['sha256'] == 'f5ceca3cd12484f66a13f75026c4466970c8810496bf7b7871f5973d749f05f4'
    assert fingerprint(select(ast.parse(calendar_raw), 'reviewed_sessions')) == fingerprint(select(ast.parse(real_calendar), 'reviewed_sessions'))
    context_contract = json.loads((RESEARCH / 'original-loader-archive-context-contract-v1-2026-10-18.json').read_bytes())
    assert context_contract['proposed_module_map_compact_sha256'] == '841f99e58b429223c8422b60fea003273fdfaa57193c4a624ba1a5ab718efd17'
    modules = {name.removeprefix('/app/'): digest for name, digest in context_contract['proposed_module_map'].items()}
    modules['backend/market/capacity_original_admissions_v1.py'] = admissions_pin['sha256']
    modules['backend/market/capacity_original_calendar_v1.py'] = pin(calendar_raw)['sha256']
    modules['backend/market/capacity_original_admission_lifecycle_v1.py'] = pin(LIFECYCLE.read_bytes())['sha256']
    base_raw = (RESEARCH / 'original-loader-genuine-source-map-2026-10-18.json').read_bytes()
    assert pin(base_raw)['sha256'] == '9a0bfbeb59e0a63072453a6ac0e930e65a89684efd90bc705febf9b1bdbe6224'
    base = json.loads(base_raw)
    assert len(base) == 2446 and compact(base) == '503e8d508ebe5fdc82a17c11974ccce5366c60ce8e78fc549c129fc6c6d81e03'
    assert all(name not in base or base[name] == digest for name, digest in modules.items())
    source_map = {'schema': 'capacity-original-source-map/1', 'base': base, 'modules': modules, 'files': {**base, **modules}}
    assert len(modules) == 11 and len(source_map['files']) == 2453
    # Keep this large metadata declaration local; it is not an application tree or staging packet.
    local = pathlib.Path('/tmp/capacity-admission-source-map-20261018-v2')
    local.mkdir(mode=0o700, exist_ok=False)
    source_map_pin = save_json(local / 'source-map.json', source_map)
    review = {
        'schema': 'capacity-original-admission-static-review/1', 'status': 'SOURCE_ONLY_ALL_BODIES_UNRUN',
        'original_CLI': pin(original_raw), 'new_admissions': admissions_pin,
        'copied_admissions': comparisons,
        'calendar': {'original': pin(real_calendar), 'new': pin(calendar_raw), 'reviewed_sessions_AST_exact': True, 'new_identity': True, 'imports': 'json/lru_cache/Path/NumPy only; no original calendar/Panel/MarketStore/Yahoo import. New calendar source/package/native/data parity UNRUN.'},
        'lifecycle': pin(LIFECYCLE.read_bytes()),
        'source_map': {**source_map_pin, 'local_path': str(local / 'source-map.json'), 'base_files': 2446, 'module_files': 11, 'union_files': 2453, 'compact_union_sha256': compact(source_map['files']), 'tree_assembled_or_runtime_admitted': False},
        'lifecycle_order': ['distinct wrapper + unchanged original schema2', 'actual original runtime', 'new root host mapping', 'new2453 byte map separately from old audit_source map', 'exact native versions', 'fresh proof root/owned reserved failure FD', 'full completion size/native31/new archives', 'legacy source/Git', 'producer', 'new calendar and original data hashes', 'full session/raw physical preservation', 'complete BEFORE byte receipt', 'retain separately admitted loader result; no loader call', 'complete AFTER byte receipt/equality/preservation/unchanged/new source', 'complete JSON+UTF8 with all graphs retained', '256MiB result bound unchanged', 'exclusive file fsync/hash readback plus held/path-identity directory and proof-parent fsync', 'drop only own RAM refs; retain files'],
        'unimplemented': ['actual pre-import fence/finder/generated+phase call manifests/native extension closure/exact host/runtime/resource admission', 'genuine loader/type/model strategy', 'timing/RAM/aliasing/deepcopy/readonly/lifetime/preservation behavioral acceptance', 'completion/failed root archival cleanup and bounded cumulative disk metadata reservation'],
        'scope': 'Public execute unconditionally refuses. Direct call bodies are UNRUN source proposals, not independently admitted operations. A guard slot is not proof a fence is installed, and map union is not an import/call closure. Loaded arbitrary non-None object is retained only, never model/type acceptance. Root mapping is not held-root-FD isolation. Failures retain newly created evidence/scratch; no retry, root adoption or native account change.',
    }
    review_pin = save_json(RESEARCH / 'original-loader-admission-static-review-v1-2026-10-18.json', review)
    contract = {
        'schema': 'capacity-original-admission-contract/1', 'status': 'SOURCE_PREPARED_UNEXECUTED_WRAPPER_LIFECYCLE',
        'starting_revision': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
        'sources': {ADMISSIONS.name: admissions_pin, CALENDAR.name: pin(calendar_raw), LIFECYCLE.name: pin(LIFECYCLE.read_bytes()), pathlib.Path(__file__).name: pin(pathlib.Path(__file__).read_bytes())},
        'static_review': {'path': 'original-loader-admission-static-review-v1-2026-10-18.json', **review_pin},
        'new_module_map': modules, 'full_source_map': review['source_map'],
        'old_invocation_and_source_map': 'Original schema2/value.audit_source_sha256 receipt retained unchanged; new external capacity binding/map/root receipt separate. No old map reinterpretation or legacy file override.',
        'calendar': 'Actual new real file identity with unchanged reviewed_sessions AST/same real parent data paths. New import root explicitly equals archive root; three original calendar data hashes and original calendar bytes remain authenticated. Function/body equality is not calendar/native/parity acceptance.',
        'lifetime': review['lifecycle_order'], 'unimplemented': review['unimplemented'],
        'entrypoint': None, 'launch': None, 'admission': None, 'execution_authorized': False, 'model_import_strategy': None,
        'next': 'Prepare distinct bounded SYNTHETIC context/admission/lifecycle parity proposal/bootstrap/caller/packet; original references isolated explicitly SYNTHETIC. Include map/root/calendar/source/lifetime/serialization/failure-phase controls and actual module origins. No genuine loader/context/source/runtime admission. Fresh independent source/native/runtime/resources/exact invocation review before ONE new scoped test; no old80/23/65+4/tiny/diagnostic/v2 body replay/root-admission reuse.',
        'unchanged': {'historical_weekday_intraday_fill_UI_RAM_horizon': 'UNVERIFIED', 'original_timing': 'FAILED', 'publication': 'CLOSED', 'genuine_v6': 'OPEN_PAUSED_NO_REPLAY_ADOPTION_NEW_RUN', 'heartbeat': 'ACTIVE'},
    }
    contract_pin = save_json(RESEARCH / 'original-loader-admission-contract-v1-2026-10-18.json', contract)
    print(json.dumps({'admissions': admissions_pin, 'calendar': pin(calendar_raw), 'lifecycle': pin(LIFECYCLE.read_bytes()), 'contract': contract_pin, 'review': review_pin, 'source_map': review['source_map']}, sort_keys=True))


if __name__ == '__main__':
    main()
