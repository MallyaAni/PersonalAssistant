"""UNEXECUTED distinct loader binding; map/root receipts are not runtime admission.

The reference2446 tree is data only and must not enter import search. The new
executor map explicitly changes one source path and adds four entry modules plus
these two composition modules. Original2431 producer/source/input receipts stay
separate. Old2453 binding and its legacy override refusal are unchanged.
"""
import hashlib
import json
import os
from pathlib import Path
import stat
import sys
from types import ModuleType

from backend.market import capacity_original_admissions_v1 as admissions
from backend.market import capacity_original_evidence_v1 as evidence
from backend.market import live_model_history_input_auth as byte_auth
from backend.market.capacity_original_admissions_v1 import FULL_REVISION
from backend.market.capacity_original_archive_adaptations_v1 import logical_digest as digest
from backend.market.capacity_original_evidence_v1 import authenticate_file, pinned, require, strict_json

SCHEMA = 'capacity-original-loader-binding/1'
REFERENCE_MAP_SHA256 = '9a0bfbeb59e0a63072453a6ac0e930e65a89684efd90bc705febf9b1bdbe6224'
REFERENCE_COMPACT_SHA256 = '503e8d508ebe5fdc82a17c11974ccce5366c60ce8e78fc549c129fc6c6d81e03'
PRIOR_MAP_SHA256 = 'a68ebbefb776a93dfdfb56fc6c4893ac35450a224fcf2fa50498cb911bfeda43'
ENTRY_MAP_SHA256 = 'aaa1ad0622f18f35e8f639d4a7a9e78e21d8681e19860c7a7284b0876b043f9c'
NATIVE_COMPACT_SHA256 = '99e62ab9f8b02bc315ce59b81f8b461ae5c988e275cdf09cacf2d36b1025f8ab'
TRANSITION_PATH = 'backend/market/learned_entry_data.py'
ORIGINAL_SHA256 = '4b0555a6fd929c8a73a9063ef933fde22ce581fa85f37badb37fe611a9123365'
VARIANT_SHA256 = '21adedb2a11ef8fe9802c4be6c2783b684bfd755db17032ae4bbaf0a2e2a693e'
ENTRY_MODULES = {
    'backend/market/capacity_original_daily_inputs_v1.py': 'a77634e8c54575f3295179c48b4d6577940deff44d1daa691553d826ecc3f9cc',
    'backend/market/capacity_original_economics_v1.py': 'b66cebc1f24f6938a2a4e9dd17cfd6efd233d0ab44091b293c980f9e5a6eadcc',
    'backend/market/capacity_original_frozen_readers_v1.py': '7a0352cb56ad74332c80f64c7b676d85d6e88fdf903f768c0b5f4a5de0536915',
    'backend/market/capacity_original_inputs_v1.py': '8470e2b579cc39b32113e2fcb88e8e918eac283e900f7d62341059761c524661',
}
COMPOSITION_PATHS = {
    'backend/market/capacity_original_loader_binding_v1.py',
    'backend/market/capacity_original_loader_lifecycle_v1.py',
}
ROOT_KEYS = ('st_dev', 'st_ino', 'st_mode', 'st_uid')


# Hash finite canonical source maps without treating them as executable call manifests.
def map_digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


# Require canonical source paths and complete lowercase digest declarations.
def file_map(value, count):
    evidence.require(type(value) is dict and len(value) == count, 'EXACT_SOURCE_MAP_COUNT_REQUIRED')
    for name, expected in value.items():
        byte_auth.canonical(name, absolute=False)
        byte_auth.digest_value(expected)
    return value


# Accept only the pinned original-to-variant transition and explicitly added modules.
def capacity_binding(path, expected):
    binding = evidence.strict_json(evidence.pinned(path, expected))
    path_fields = ('original_invocation', 'source_root', 'source_host_root', 'reference_root', 'reference_host_root', 'reference_map', 'prior_map', 'entry_map', 'source_map', 'native31')
    digest_fields = ('original_invocation_sha256', 'reference_map_sha256', 'prior_map_sha256', 'entry_map_sha256', 'source_map_sha256', 'native31_sha256')
    fields = {'schema', 'source_root_identity', 'reference_root_identity', *path_fields, *digest_fields}
    evidence.require(type(binding) is dict and set(binding) == fields and binding['schema'] == SCHEMA, 'EXACT_NEW_LOADER_BINDING_REQUIRED')
    for name in path_fields:
        byte_auth.canonical(binding[name], absolute=True)
    for name in digest_fields:
        byte_auth.digest_value(binding[name])
    evidence.require(binding['reference_map_sha256'] == REFERENCE_MAP_SHA256 and binding['prior_map_sha256'] == PRIOR_MAP_SHA256 and binding['entry_map_sha256'] == ENTRY_MAP_SHA256, 'EXACT_REVIEWED_MAP_CHAIN_REQUIRED')
    value = admissions.invocation(binding['original_invocation'], binding['original_invocation_sha256'])
    evidence.require(value['profile'] == 'original-full-27471', 'ORIGINAL_FULL_CAPACITY_PROFILE_REQUIRED')
    evidence.require(Path(binding['source_root']) == Path(__file__).resolve().parents[2], 'ACTUAL_EXECUTOR_IMPORT_ROOT_REQUIRED')
    reference = file_map(evidence.strict_json(evidence.pinned(binding['reference_map'], REFERENCE_MAP_SHA256)), 2446)
    evidence.require(map_digest(reference) == REFERENCE_COMPACT_SHA256, 'EXACT_REFERENCE2446_REQUIRED')
    prior = evidence.strict_json(evidence.pinned(binding['prior_map'], PRIOR_MAP_SHA256))
    entry = evidence.strict_json(evidence.pinned(binding['entry_map'], ENTRY_MAP_SHA256))
    original_files = file_map(prior['files'], 2453)
    entry_files = file_map(entry['files'], 2457)
    evidence.require(prior['base'] == reference, 'UNCHANGED_REFERENCE_BASE_REQUIRED')
    evidence.require(set(entry_files) - set(original_files) == set(ENTRY_MODULES) and entry['new_modules'] == ENTRY_MODULES, 'EXACT_FOUR_ENTRY_ADDITIONS_REQUIRED')
    evidence.require({name for name in original_files if original_files[name] != entry_files[name]} == {TRANSITION_PATH} and original_files[TRANSITION_PATH] == ORIGINAL_SHA256 and entry_files[TRANSITION_PATH] == VARIANT_SHA256, 'SOLE_EXACT_IMPORT_CUT_REQUIRED')
    evidence.require(all(entry_files[name] == expected for name, expected in ENTRY_MODULES.items()), 'EXACT_ENTRY_SOURCE_IDENTITIES_REQUIRED')
    source_map = evidence.strict_json(evidence.pinned(binding['source_map'], binding['source_map_sha256']))
    evidence.require(type(source_map) is dict and set(source_map) == {'schema', 'entry2457_sha256', 'compositions', 'files'} and source_map['schema'] == 'capacity-original-loader-source-declaration/1' and source_map['entry2457_sha256'] == ENTRY_MAP_SHA256, 'EXACT_COMPOSITION_SOURCE_SCHEMA_REQUIRED')
    compositions = file_map(source_map['compositions'], 2)
    evidence.require(set(compositions) == COMPOSITION_PATHS and not set(compositions) & set(entry_files), 'EXACT_NEW_COMPOSITION_ADDITIONS_REQUIRED')
    files = file_map(source_map['files'], 2459)
    evidence.require(files == {**entry_files, **compositions}, 'EXACT2459_UNION_REQUIRED')
    native = file_map(evidence.strict_json(evidence.pinned(binding['native31'], binding['native31_sha256'])), 31)
    evidence.require(map_digest(native) == NATIVE_COMPACT_SHA256 and all(reference[name] == expected for name, expected in native.items()), 'UNCHANGED_REFERENCE_NATIVE31_REQUIRED')
    return binding, value, {'files': files, 'reference': reference, 'compositions': compositions}, native


# Reject overlapping executor/reference/proof namespaces and unreviewed descendant mounts.
def root_admission(binding, value):
    row = evidence.strict_json(evidence.pinned(value['runtime'], value['runtime_sha256']))[0]
    mounts = row['Mounts']
    evidence.require(type(mounts) is list and len(mounts) == len({item['Destination'] for item in mounts}), 'UNIQUE_RUNTIME_DESTINATIONS_REQUIRED')
    roots = (Path(binding['source_root']), Path(binding['reference_root']))
    hosts = (Path(binding['source_host_root']), Path(binding['reference_host_root']))
    for left, right in (roots, hosts):
        evidence.require(not left.is_relative_to(right) and not right.is_relative_to(left), 'DISJOINT_EXECUTOR_REFERENCE_ROOTS_REQUIRED')
    proof = Path(value['proof_parent'])
    for root, host in zip(roots, hosts, strict=True):
        evidence.require(not root.is_relative_to(proof) and not proof.is_relative_to(root), 'PROOF_EXECUTOR_REFERENCE_OVERLAP')
        selected = [item for item in mounts if item['Destination'] == str(root)]
        evidence.require(len(selected) == 1 and selected[0]['Type'] == 'bind' and selected[0]['RW'] is False and selected[0]['Source'] == str(host), 'EXACT_DISTINCT_READONLY_ROOT_MOUNT_REQUIRED')
        evidence.require(not any(Path(item['Destination']) != root and Path(item['Destination']).is_relative_to(root) for item in mounts), 'DESCENDANT_SOURCE_MOUNT_OVERRIDE_FORBIDDEN')
    writable = [item for item in mounts if item['RW']]
    evidence.require(len(writable) == 1 and writable[0]['Destination'] == str(proof), 'SOLE_PROOF_BIND_REQUIRED')
    proof_host = Path(writable[0]['Source'])
    evidence.require(all(not host.is_relative_to(proof_host) and not proof_host.is_relative_to(host) for host in hosts), 'PROOF_HOST_SOURCE_OVERLAP')
    reference = roots[1]
    evidence.require(not any(Path(item or os.getcwd()).resolve().is_relative_to(reference) or reference.is_relative_to(Path(item or os.getcwd()).resolve()) for item in sys.path), 'REFERENCE_TREE_IN_IMPORT_SEARCH_FORBIDDEN')
    return {'executor': str(roots[0]), 'executor_host': str(hosts[0]), 'reference': str(roots[1]), 'reference_host': str(hosts[1]), 'runtime_sha256': value['runtime_sha256'], 'source_book_or_finder_acceptance': False}


# Compare held directory descriptors and named physical roots to external exact identities.
def check_root(descriptor, path, expected):
    info = os.fstat(descriptor)
    named = byte_auth.physical(path).stat(follow_symlinks=False)
    evidence.require(type(expected) is dict and set(expected) == set(ROOT_KEYS) and all(type(value) is str and value.isdecimal() and str(int(value)) == value for value in expected.values()), 'EXACT_DECIMAL_ROOT_IDENTITY_REQUIRED')
    evidence.require(stat.S_ISDIR(info.st_mode) and {key: str(getattr(info, key)) for key in ROOT_KEYS} == expected and all(getattr(info, key) == getattr(named, key) for key in ROOT_KEYS), 'BOUND_SOURCE_ROOT_IDENTITY_CHANGED')


# Hash both complete trees while holding and bookending their actual root descriptors.
def module_admission(binding, source_map):
    descriptors = []
    try:
        for name in ('source_root', 'reference_root'):
            path = byte_auth.physical(binding[name])
            descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            descriptors.append((descriptor, path, binding[name + '_identity']))
            check_root(descriptor, path, binding[name + '_identity'])
        for root, files in ((binding['source_root'], source_map['files']), (binding['reference_root'], source_map['reference'])):
            for name, expected in files.items():
                evidence.authenticate_file(Path(root) / name, expected)
        for descriptor, path, identity in descriptors:
            check_root(descriptor, path, identity)
    finally:
        for descriptor, _, _ in descriptors:
            os.close(descriptor)
    return {'executor_files': 2459, 'reference_files': 2446, 'source_map_sha256': binding['source_map_sha256'], 'reference_map_sha256': REFERENCE_MAP_SHA256, 'root_FDs_held_during_hash_only': True, 'per_file_open_is_root_FD_relative': False, 'finder_or_runtime_acceptance': False}


# Bind imported module origins to executor paths without claiming live CodeType or native closure.
def module_origin(binding, source_map, module):
    evidence.require(type(module) is ModuleType and type(module.__name__) is str, 'EXACT_MODULE_OBJECT_REQUIRED')
    name = module.__name__.replace('.', '/') + '.py'
    evidence.require(name in source_map['files'], 'DECLARED_MODULE_ORIGIN_REQUIRED')
    path = Path(binding['source_root']) / name
    evidence.require(Path(module.__file__).resolve() == path and module.__spec__ is not None and module.__spec__.origin == str(path), 'EXACT_EXECUTOR_MODULE_ORIGIN_REQUIRED')
    evidence.authenticate_file(path, source_map['files'][name])
    return {'module': module.__name__, 'path': str(path), 'sha256': source_map['files'][name], 'CodeType_globals_or_native_acceptance': False}


# Authenticate unchanged legacy audit/Git receipts against the separate exact reference tree.
def source_admission(value, archives, reference_root):
    root = Path(reference_root)
    require(root == archives.source_root, 'EXACT_REFERENCE_ARCHIVE_ROOT_REQUIRED')
    files = value["audit_source_sha256"]
    required = {
        "backend/cli/audit_original_live_model_history.py",
        "backend/cli/verify_actual_policy_timing.py",
        "backend/cli/verify_live_model_history.py",
        "backend/market/live_model_history_audit_inputs.py",
        "backend/market/live_model_history_stream_audit.py",
        "backend/market/live_model_history_pending_audit.py",
        "backend/market/live_model_history_observation_context.py",
        "backend/market/live_model_history_nightly_model.py",
        "backend/market/live_model_history_nightly_audit.py",
        "backend/market/live_model_history_receipts.py",
        "backend/market/live_model_history_input_auth.py",
        "backend/market/original_history_json.py",
        "backend/market/live_model_history_binding.py",
        "backend/market/live_policy_replay.py",
        "backend/agents/trading/desk/paper.py",
    }
    require(required <= set(files), "ALL_AUDIT_COMPONENT_SOURCE_PINS_REQUIRED")
    for name, expected in files.items():
        byte_auth.canonical(name, absolute=False)
        authenticate_file(root / name, expected)
    if value["profile"] == "complete-private-v10":
        require(value["git_map"] is None and value["git_map_sha256"] is None, "TEST_PROFILE_IS_NOT_FULL_GIT_AUTHENTICATION")
        return "UNVERIFIED_TEST_PROFILE_ONLY"
    require(value["git_map"] is not None, "EXTERNAL_COMPLETE_GIT_BLOB_MAP_REQUIRED")
    record = strict_json(pinned(value["git_map"], value["git_map_sha256"]))
    require(set(record) == {"revision", "files"} and record["revision"] == FULL_REVISION and len(record["files"]) == 2431 and record["files"] == archives.sources, "ORIGINAL_FULL_GIT_BLOB_PROFILE_DIFFERS")
    return {"revision": FULL_REVISION, "files": 2431, "external_git_blob_map_sha256": value["git_map_sha256"]}


# Retain full original calendar checks using real executor imports and matching reference bytes.
def calendar_admission(archives, profile, executor_root):
    import numpy as np
    from backend.market import calendar
    require(Path(calendar.__file__).resolve().parents[2] == Path(executor_root), "EXACT_ORIGINAL_CALENDAR_EXECUTOR_ROOT_REQUIRED")
    for path in (Path(calendar.__file__), archives.source_root / 'backend/market/calendar.py'):
        authenticate_file(path, archives.sources['backend/market/calendar.py'])
    completion = archives.completion
    first, through = completion["first"], completion["through"]
    require((first, through) == (("2019-03-01", "2026-10-12") if profile == "original-full-27471" else ("2019-03-01", "2019-03-04")), "EXACT_ORIGINAL_PROFILE_CALENDAR_REQUIRED")
    years, days = calendar.reviewed_sessions()
    dates = np.arange(np.datetime64(first), np.datetime64(through) + np.timedelta64(1, "D"))
    require(all(day.astype(object).year in years for day in dates), "REVIEWED_CALENDAR_COVERAGE_REQUIRED")
    expected = list(map(str, dates[np.is_busday(dates, busdaycal=days)]))
    require([row["session"] for row in completion["sessions"]] == expected, "COMPLETE_EXCHANGE_SESSION_SEQUENCE_REQUIRED")
    for path in (calendar.HOLIDAYS_PATH, calendar.HISTORICAL_SESSIONS_PATH, calendar.EARLY_CLOSES_PATH):
        relative = str(path.relative_to(executor_root))
        authenticate_file(path, archives.sources[relative])
        authenticate_file(archives.source_root / relative, archives.sources[relative])
    return {"sessions": len(expected), "first": first, "through": through, "sha256": digest(expected)}


# Refuse public execution because a distinct full source/fence/runtime contract is still absent.
def execute(*args, **kwargs):
    raise RuntimeError('SOURCE_ONLY_LOADER_BINDING_NOT_RUNTIME_ADMISSION')
