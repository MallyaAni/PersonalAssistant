"""Build requirements from retained source and metadata; never observe or execute a runtime."""
import ast
import hashlib
import json
import os
from pathlib import Path
import signal
import stat

REPO = Path('/Users/animallya/.codex/worktrees/learned-live-release-20261006/PersonalAssistant')
DOCS = REPO / 'docs/research'
ROOT = Path('/tmp/capacity-native-origin-contract-20261018-v1')
PINS = {
    'original-loader-callback-symbol-data-proof-v1-2026-10-18.json': ('b449bed28bc6bc339269f097f6b2dbacbd447a9b1ef93044846e78b87e7a2476', 18006),
    'original-loader-callback-symbol-data-independent-v1-2026-10-18.json': ('bca4d7f616050feddb3aabfa5427e3c67434efbd93141c63ef600b1bee02ca0c', 12826),
    'original-loader-context-parity-proof-v1-2026-10-18.json': ('b6327bcfd28c6c5448683a4beddbbc20897f18a1dcc7c251e609c4b1810e57e9', 38967),
    'original-loader-callback-symbol-requirements-v1-2026-10-18.json': ('ca3503c0c58352297104f286ca8784422dc66612aa46ad27eb20f9bbfd51b40f', 12746),
    'sources/original-loader-context-native-probe-v1-2026-10-18.py': ('6a9e82a33291466c7ef7abc57554c90b26f56c9253bbc1ff4969c49515f0105f', 1878),
    'sources/original-loader-context-parity-preflight-v1-2026-10-18.py': ('e064dc5e1739a1e7e8e20b8af178a3420a6d58476233a2bbaad2943446ead243', 13589),
    'sources/original-loader-context-parity-preserver-v2-2026-10-18.py': ('cf772f8dc17b4f7e325f50d463e2ea79abeb1e25561e8929aae8f5b992f56329', 9562),
    '/tmp/capacity-context-parity-operations-20261018-v1/fetch-native-proof.stdout': ('1355771ff667f81e02dbe07885914dd5be8bf5cf395a3e74ef3bfdfd4988c6f7', 46814),
    '/tmp/capacity-context-parity-operations-20261018-v1/fetch-native-inspect.stdout': ('d5265be87b979e83e396e18d1d9d4571cc6e1db5aa09239200004a2809bd90d2', 9755),
    '/tmp/capacity-context-parity-operations-20261018-v1/fetch-evidence-manifest.stdout': ('d2378ddf7f0e5cf9eac724ff1f7c8f3f5d3cff70c0ba39f45cd2ca18546fd9f9', 10845),
}


# Keep exact file identities, including nanoseconds, as decimal strings.
def physical(value):
    return {key: str(getattr(value, key)) for key in ('st_dev', 'st_ino', 'st_mode',
        'st_uid', 'st_nlink', 'st_size', 'st_blocks', 'st_mtime_ns', 'st_ctime_ns')}


# Authenticate complete bounded local bytes with two held reads and named bookends.
def read(path):
    path = path.resolve(strict=True)
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        before = os.fstat(descriptor)
        assert stat.S_ISREG(before.st_mode) and before.st_nlink == 1 and 0 <= before.st_size <= 262144
        raw = os.read(descriptor, 262145)
        os.lseek(descriptor, 0, os.SEEK_SET)
        assert raw == os.read(descriptor, 262145) and len(raw) == before.st_size
        assert physical(before) == physical(os.fstat(descriptor)) == physical(path.stat(follow_symlinks=False))
        return raw, {'sha256': hashlib.sha256(raw).hexdigest(), 'bytes': len(raw), 'physical': physical(before)}
    finally:
        os.close(descriptor)


# Persist one exclusive finite JSON artifact and verify its full readback.
def save(path, value):
    raw = json.dumps(value, sort_keys=True, indent=2, allow_nan=False).encode() + b'\n'
    assert len(raw) <= 262144
    with path.open('xb') as output:
        output.write(raw)
        output.flush()
        os.fsync(output.fileno())
    assert read(path)[0] == raw
    return read(path)[1]


# Locate one literal dictionary assignment in authenticated source without compiling it.
def dictionary(raw, function, variable):
    tree = ast.parse(raw)
    functions = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == function]
    assert len(functions) == 1
    assignments = [node for node in ast.walk(functions[0]) if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == variable for target in node.targets)]
    assert len(assignments) == 1 and isinstance(assignments[0].value, ast.Dict)
    node = assignments[0].value
    keys = [ast.literal_eval(key) for key in node.keys]
    assert all(type(key) is str for key in keys) and len(keys) == len(set(keys))
    return functions[0], dict(zip(keys, node.values, strict=True))


# Derive the missing-field boundary and an inert staged provenance contract from exact evidence.
def main():
    assert __debug__
    signal.alarm(30)
    inputs, bodies = {}, {}
    for name, (sha, size) in PINS.items():
        path = DOCS / name
        raw, row = read(path)
        assert row['sha256'] == sha and row['bytes'] == size
        inputs[str(path)] = row
        bodies[name] = raw
    assert sum(row['bytes'] for row in inputs.values()) <= 1048576
    symbols = json.loads(bodies['original-loader-callback-symbol-data-independent-v1-2026-10-18.json'])
    prior = json.loads(bodies['original-loader-context-parity-proof-v1-2026-10-18.json'])
    native = json.loads(bodies['/tmp/capacity-context-parity-operations-20261018-v1/fetch-native-proof.stdout'])
    inspect = json.loads(bodies['/tmp/capacity-context-parity-operations-20261018-v1/fetch-native-inspect.stdout'])
    manifest = json.loads(bodies['/tmp/capacity-context-parity-operations-20261018-v1/fetch-evidence-manifest.stdout'])
    assert symbols['all_fields_raw_spans_names_order_multiplicity_pages_canonical_equal'] is True
    assert native['cid'] == prior['native']['cid'] == inspect[0]['Id']
    assert native['image'] == inspect[0]['Image'] == prior['prerequisites']['image_id']
    assert native['inspect_sha256'] == PINS['/tmp/capacity-context-parity-operations-20261018-v1/fetch-native-inspect.stdout'][0]
    assert native['python'] == '3.12.14' and native['stopped'] is True and native['exit'] == 0
    assert 'python_executable' not in native and len(inspect) == 1
    assert manifest['schema'] == 'capacity-context-parity-evidence/1' and manifest['genuine_acceptance'] is False
    assert manifest['files'] == 1339 and len(manifest['pages']) == 21
    probe_fn, probe_fields = dictionary(bodies['sources/original-loader-context-native-probe-v1-2026-10-18.py'], 'main', 'result')
    fold_fn, fold_fields = dictionary(bodies['sources/original-loader-context-parity-preflight-v1-2026-10-18.py'], 'native_fold', 'proof')
    assert ast.dump(probe_fields['python_executable'], include_attributes=False) == "Attribute(value=Name(id='sys', ctx=Load()), attr='executable', ctx=Load())"
    assert 'python_executable' not in fold_fields
    declarations = []
    for need in symbols['needs']:
        declarations.append({'file_hex': need['file']['hex'], 'requirements': [
            {'name_hex': item['name']['hex'], 'vna_other_decimal': item['fields']['other'],
                'auxiliary_array_index': item['index']} for item in need['auxiliaries']]})
    contract = {
        'schema': 'capacity-native-origin-requirements/1',
        'status': 'SOURCE_REVIEW_REQUIRED_NO_OBSERVER_OR_RUNTIME_ADMISSION',
        'input_inventory': inputs,
        'existing_runtime': {'cid': native['cid'], 'image': native['image'], 'python_version_metadata': native['python'],
            'Path': inspect[0]['Path'], 'Args': inspect[0]['Args'], 'WorkingDir': inspect[0]['Config']['WorkingDir'],
            'Entrypoint': inspect[0]['Config']['Entrypoint'], 'Cmd': inspect[0]['Config']['Cmd'],
            'scope': 'HISTORICAL_STOPPED_NUMPY_METADATA_ONLY_NOT_FUTURE_GENUINE_PROCESS'},
        'source_omission': {'probe_function_AST_sha256': hashlib.sha256(ast.dump(probe_fn, include_attributes=False).encode()).hexdigest(),
            'fold_function_AST_sha256': hashlib.sha256(ast.dump(fold_fn, include_attributes=False).encode()).hexdigest(),
            'probe_result_fields': list(probe_fields), 'fold_proof_fields': list(fold_fields),
            'emitted_field': 'python_executable', 'emitted_expression': 'sys.executable',
            'summary_field_absent': True, 'raw_native_json_observed_here': False,
            'interpretation': 'Prior NumPy-only summary intentionally omits this field; its version string and Entrypoint python cannot establish executable path or build authority.'},
        'callback_required_version_declarations': declarations,
        'retained_metadata_selection': {
            'evidence_root': prior['preservation']['root'],
            'top_manifest_sha256': PINS['/tmp/capacity-context-parity-operations-20261018-v1/fetch-evidence-manifest.stdout'][0],
            'top_manifest_bytes': 10845, 'page_inventory': manifest['pages'],
            'target_manifest_key': 'native/output/native.json',
            'target_original': '/home/animallya96/scratch/capacity-context-native-probe-20261018-v1/output/native.json',
            'target_copy': prior['preservation']['root'] + '/native/output/native.json',
            'target_SHA_bytes_physical': None,
            'selection_authority': 'Exact ROOTS native and NATIVE/output/native.json declarations in authenticated preserver/preflight source; target row not yet read.',
            'future_requirements': [
                'Prepare distinct readonly observer and independent selector; no old preserver/fold/probe invocation, recursive inventory, Docker or runtime execution.',
                'Authenticate full top manifest SHA/size and all21 fixed page SHA/size/original decimal physical rows before selecting. Reject duplicate JSON keys, malformed page paths, extra/missing pages, duplicate record names, wrong complete1339-record count or any changed bookend.',
                'Require exactly ONE target_manifest_key over complete page metadata, retaining complete selected row plus page identity and top identity. No last-match, substring, guessed page or basename fallback.',
                'Read ONLY exact target_original and target_copy bodies after row authentication, each two full held/named reads and later fullSHA/physical bookends against respective original/copy rows; require equal complete bodies/SHA/size across original and copy. No other1338 payload body reads and no old full preservation acceptance claim.',
                'Retain complete raw native.json, exact schema/field types, historical Python/NumPy/UID/time/source/terminal relations, and unmodified python_executable string. Reject embedded NUL/nonabsolute/over4096-byte path values; shape validity is NOT executable path/build authority.',
                'Report a string recovered from the preserved historical artifact, without retroactively extending proof1355771f. A historical sys.executable string is not current path resolution, symlink/hardlink authority, ELF/PT_INTERP, actual loader or future process state. Do NOT open that declared path in this stage.',
                'Keep a single cumulative4MiB hash-work counter including source/prior/top/page/target/output/readback/later bookend hashes, charge BEFORE each digest;1024reads/262KiBfile, complete output pages<=65536encodedB AND64records/max256/16MiBtotal. Refuse before exceeding any bound; no completion guarantee from caps.',
                'New exact source/invocation/actual fresh host resources/absent roots reviewed independently BEFORE any observation.512MiBLinuxASsoft=hard/20CPU/30alarm/70SSH/TERM1KILL1 are proposed controls only;2GiBmem/32MiBscratch512inode headroom is not reservation/native/model/daemon RAM admission.',
            ]},
        'later_gates_NOT_implemented': [
            {'gate': 'INTERPRETER_FILE_ORIGIN', 'requirements': 'Bind complete namespace/image/container/mount and command/PATH resolution to actual declared executable; retain each link/alias and canonical target from exact observed metadata. Distinguish path string, copied file identity and original container-source authority. No guessed path or host substitute.', 'observer': None},
            {'gate': 'ELF_AND_BUILD', 'requirements': 'Authenticate complete interpreter/provider bytes and exact build evidence before claims. Parse executable ELF/PT_INTERP and needed libraries as DATA under a separately reviewed domain. Version strings/upstream source tags/build IDs alone are not binary-to-build certificates. Missing or oversized artifact refuses current whole-file route; prepare distinct bounded authentication before any read, never reuse text-copy tools or increase their caps.', 'observer': None},
            {'gate': 'LOADER_SEARCH_STATE', 'requirements': 'Bind actual matching loader implementation/build with exact invocation, namespace, security mode, already-loaded/global symbols, environment, cache/config/preloads, token/hardware search rules and dependency request origin/order. Minimize to required named state; never broad-export credentials or bypass denied reads. Historical stopped metadata alone cannot certify future process state.', 'observer': None},
            {'gate': 'PROVIDER_ALIAS_VERSION_TRANSITIVE', 'requirements': 'Bind each resolved provider bytes/namespace/physical aliases, full needed/definition/version/symbol/multiplicity/order chain and transitive closure to the actual matching loader state. libm.so.6/libc.so.6 and GLIBC_2.17 are declarations only; static candidate search is not observed runtime resolution or compatibility.', 'observer': None},
            {'gate': 'PYTHON_EXTENSION_BINDING', 'requirements': 'Bind actual matching interpreter import flags, spec name/origin/loader and init symbol, generated/native callable/global/type/class/phase provenance and the complete import/native/thread/pool lifetimes. No dlopen/dlsym/ldd/readelf/package execution or all-functions allowance is granted.', 'observer': None},
            {'gate': 'GENUINE_MODEL_RAM', 'requirements': 'Keep producer2431/reference2446/executor2468 separate and unchanged guard3b8be00b/old030c/G08/caps. Full context/spools/both receipt graphs/JSON+UTF8/model/Arrow pools and actual horizon allocation remain mandatory and unverified.', 'observer': None},
        ],
        'reference_scope': 'Existing ca3503c0 CPython3.12.14/glibc2.42/ELF4.3 DRAFT references remain reference only, NOT installed interpreter/loader/build attestation. No new external source or binary read here.',
        'observation_executor': None, 'observer_invocation': None, 'native_runtime_admission': None,
        'genuine_execution_authorized': False,
        'closed_jobs': 'Actual symbols/ELFfold/copies/HEAD/metadata/censuses/synthetic63/37/73/80/23/65+4/tiny/diagnostic/v2 and all old packets stay CLOSED, no replay for docs.',
    }
    ROOT.mkdir(mode=0o700, exist_ok=False)
    contract_row = save(ROOT / 'contract.json', contract)
    for path, row in inputs.items():
        assert read(Path(path))[1] == row
    static = {'schema': 'capacity-native-origin-source-derivation/1', 'contract': contract_row,
        'source_omission': contract['source_omission'], 'input_files': len(inputs),
        'all_input_full_SHA_physical_bookends_equal': True,
        'remote_observations_or_payload_execution': 0, 'proposed_target_row_observed': False}
    save(ROOT / 'static.json', static)
    for directory in (ROOT, ROOT.resolve(strict=True).parent):
        descriptor = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    signal.alarm(0)
    print(json.dumps({'root': str(ROOT), 'contract': contract_row, 'inputs': len(inputs)}, sort_keys=True))


if __name__ == '__main__':
    main()
