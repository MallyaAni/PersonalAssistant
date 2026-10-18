"""Build source-only archive-context contract/review without importing its payload."""
import ast
import base64
import copy
import hashlib
import json
import pathlib
import subprocess

ROOT = pathlib.Path(__file__).resolve().parents[3]
RESEARCH = ROOT / 'docs/research'
CONTEXT = 'sources/original-loader-capacity-archive-context-v1-2026-10-18.py'
INPUTS = {
    'stream': ('backend/market/live_model_history_stream_audit.py', 'f404e15be6e97caf856a4ba6db22eedef51ff5a4e3304dcbed90cf8e0abac2ff'),
    'cli': ('backend/cli/audit_original_live_model_history.py', '22d374f166b77d4b0346120aa55b3f9e652496503b88d3fae0681be04b9ab5d5'),
    'byte_auth': ('backend/market/live_model_history_input_auth.py', '35ad5f5f96fa7951b6163512ab733a9168869eef17038e030b7dad4dcbb1b111'),
    'parser': ('backend/market/original_history_json.py', 'de29c1017f4c9eadd874b2fbe0d85b4c80ced8e7a43fb6bd4f779c3d726cb2eb'),
    'metadata': ('docs/research/sources/original-loader-capacity-metadata-boundary-2026-10-18.py', 'd413e748bf2b1eb63f4d267371f22cf6431f6ae650368676c815b07779723135'),
    'evidence': ('docs/research/sources/original-loader-capacity-evidence-v1-2026-10-18.py', '400de9e73e2debb06c7267c925ca0914dc75a98c77f3044a49b88d26db26be25'),
    'adaptations': ('docs/research/sources/original-loader-capacity-archive-adaptations-v1-2026-10-18.py', '39f2884741036bbe3a33f451909a59b46924c43ea699e39670c1c13fbcde5134'),
    'pending': ('backend/market/live_model_history_pending_audit.py', '74e7d9800bf1bdeb51655f09ae2846bfb0dbbcc67afdcad705405a849eb0cf02'),
    'loader': ('backend/market/live_model_history_audit_inputs.py', 'fae5bfc7d7438071094f31f42e884cb48e3709c55f364954e51c28302d3c3e30'),
}


# Identify source bytes without executing any source declaration or application import.
def identity(raw):
    return {'sha256': hashlib.sha256(raw).hexdigest(), 'bytes': len(raw)}


# Select one exact declaration for a static comparison or dependency inventory.
def declaration(tree, name):
    nodes = tree.body
    for part in name.split('.'):
        selected = [node for node in nodes if isinstance(node, (ast.FunctionDef, ast.ClassDef)) and node.name == part]
        assert len(selected) == 1, name
        result = selected[0]
        nodes = result.body
    return result


# Read only literal constants, never evaluate a payload expression.
def literal(tree, name):
    values = [node.value for node in tree.body if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == name for target in node.targets)]
    assert len(values) == 1
    return ast.literal_eval(values[0])


# Normalize only explicitly declared primitive and constant namespace rebindings.
class Rebindings(ast.NodeTransformer):
    # Compare new evidence-qualified calls with their original unqualified declarations.
    def visit_Attribute(self, node):
        node = self.generic_visit(node)
        if isinstance(node.value, ast.Name) and node.value.id == 'evidence':
            return ast.Name(id=node.attr, ctx=node.ctx)
        if isinstance(node.value, ast.Name) and node.value.id == 'pending' and node.attr in ('MAX_COMPRESSED_BYTES', 'ORIGINAL_SOURCES'):
            return ast.Name(id=node.attr, ctx=node.ctx)
        return node


# Fingerprint a declaration while excluding positions and optional declared namespace changes.
def fingerprint(node, normalized=False):
    node = copy.deepcopy(node)
    if normalized:
        node = Rebindings().visit(node)
    return hashlib.sha256(ast.dump(node, include_attributes=False).encode()).hexdigest()


# Write a new or byte-identical source artifact without replacing a different checkpoint.
def save(path, value):
    raw = json.dumps(value, sort_keys=True, indent=2, allow_nan=False).encode() + b'\n'
    if path.exists():
        assert path.read_bytes() == raw, str(path)
    else:
        with path.open('xb') as output:
            output.write(raw)
    assert path.read_bytes() == raw
    return identity(raw)


# Inventory source dependencies, declared parity changes and all still-mandatory admission seams.
def main():
    sources = {}
    trees = {}
    for role, (name, expected) in INPUTS.items():
        raw = (ROOT / name).read_bytes()
        assert identity(raw)['sha256'] == expected
        sources[name] = identity(raw)
        trees[role] = ast.parse(raw, filename=name)
    raw = (RESEARCH / CONTEXT).read_bytes()
    context = ast.parse(raw, filename=CONTEXT)
    sources['docs/research/' + CONTEXT] = identity(raw)
    assert literal(context, 'SOURCE_PATHS') == literal(trees['stream'], 'SOURCE_PATHS')
    assert literal(context, 'ORIGINAL_SOURCES') == literal(trees['pending'], 'ORIGINAL_SOURCES')
    comparisons = {}
    for name in ('consumed_inputs', 'authenticate_inputs', 'initial', 'unchanged'):
        old = declaration(trees['stream'], 'OriginalArchives.' + name)
        new = declaration(context, 'CapacityOriginalArchivesV1.' + name)
        assert fingerprint(old, True) == fingerprint(new, True), name
        comparisons[name] = {'original_AST': fingerprint(old), 'candidate_AST': fingerprint(new), 'equal_after_declared_primitive_rebindings': True}
    declarations = {}
    for node in ast.walk(context):
        if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
            declarations[str(node.lineno) + ':' + node.name] = fingerprint(node)
    admission_declarations = {name: fingerprint(declaration(trees['cli'], name)) for name in ('invocation', 'runtime_admission', 'source_admission', 'producer_admission', 'calendar_admission', 'preserved_archives')}
    loader_attributes = sorted({node.attr for node in ast.walk(declaration(trees['loader'], 'load')) if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id == 'archives'})
    assert loader_attributes == ['authenticate_inputs', 'authenticate_sources', 'completion', 'source_root', 'sources']
    packet_raw = pathlib.Path('/tmp/capacity-evidence-parity-packet-20261018-v1/packet.json').read_bytes()
    assert identity(packet_raw) == {'sha256': 'edac83ca50254771cec2d79bb7e2d562b43bc1578e8fbeaa81730b2b21ad3fd2', 'bytes': 356825}
    packet = json.loads(packet_raw)
    module_map = {}
    for name in ('backend/__init__.py', 'backend/market/__init__.py'):
        record = packet['files']['audit/app/' + name]
        body = base64.b64decode(record['base64'], validate=True)
        assert identity(body) == {key: record[key] for key in ('sha256', 'bytes')}
        module_map['/app/' + name] = identity(body)['sha256']
    for target, role in (
        ('original_history_json.py', 'parser'), ('live_model_history_input_auth.py', 'byte_auth'),
        ('capacity_original_metadata_v1.py', 'metadata'), ('capacity_original_evidence_v1.py', 'evidence'),
        ('capacity_original_archive_adaptations_v1.py', 'adaptations'),
    ):
        module_map['/app/backend/market/' + target] = INPUTS[role][1]
    module_map['/app/backend/market/capacity_original_archives_v1.py'] = identity(raw)['sha256']
    map_digest = hashlib.sha256(json.dumps(module_map, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    seams = {
        'invocation': 'Retain exact externally pinned original schema2/profile/Pins/canonical paths/physical+completion SHA and size; add a distinct capacity schema/map wrapper, never reinterpret old invocation/audit_source_sha256 as this executed map.',
        'runtime': 'Fresh exact image/native packages/source/import/finite-call-phase manifests/mount inventory/UID/resources/absent root/exact invocation review before admission. Existing v3 genuine bootstrap remains incompatible; no guard/G08/cap relaxation.',
        'source': 'Retain full2431 original manifest+Git revision27471 equality and full byte authentication through original execution aliases, separately from real N2native31 reads and this new8-module declaration. Six SOURCE_PATHS and five ORIGINAL_SOURCES remain manifest-bound, not31-reader membership assumptions. External admission must bind root authority/full physical source bookends; identical31-file copies are not distinguished by content hashing alone.',
        'producer': 'Retain exact completed producer CID/image/exit/noOOM/command/entrypoint/mount receipt equality/sole output host mapping. No synthetic receipt substitutes.',
        'calendar': 'Retain original profile first/through/full reviewed exchange sequence/coverage and three source-bound calendar files BEFORE any session archive path is read. New context alone does not validate calendar or authorize arbitrary session paths.',
        'configuration_and_loader': 'Retain original config1a149/capture/overlay/observations/economic-review/action/passive paths and all loader DEPENDENCIES. Loader/reader/numerical import strategy unimplemented; unchanged pure forward/calibration files stay at real paths.',
        'preservation': 'Externally admit original profile/full completion373782589B+SHA b9ad and physical832110254B+SHA f334, initial+manifest+all session SHA; use only source-bound paper descriptor and original physical=True logical comparison. Every before/after byte receipt, archives.unchanged and complete source authentication must pass before serialization.',
        'lifetime': 'Fresh explicit owned scratch retained through loaded context, before+after complete detached receipt graphs, final JSON and optional UTF8. Ending Rows released after digest in finally; completion ShaMap object/index/spool retained unchanged until all consumers finish; no cleanup by deepcopy or freeze. Outer owner must then release owned scratch, preserving failed roots. No lifecycle owner implemented here.',
    }
    review = {
        'schema': 'capacity-original-archive-context-static-review/1',
        'status': 'SOURCE_ONLY_ALL_CONTEXT_BODIES_UNRUN',
        'source_files': sources, 'context_declaration_AST_sha256': declarations,
        'comparisons': comparisons,
        'original_admission_declaration_AST_sha256': admission_declarations,
        'loader_archive_attributes': loader_attributes,
        'exact_literal_checks': ['SOURCE_PATHS6', 'ORIGINAL_SOURCES5'],
        'new_identity': ['CapacitySourceReaderV1', 'CapacityOriginalArchivesV1', 'preserved_archives in capacity_original_archives_v1'],
        'declared_changes': [
            'Explicit fresh scratch/source_reader/external_inputs parameters; no implicit mkdtemp path. Source root comes from concrete new reader, not an imported original module __file__.',
            'New frozen dataclass and concrete bound real-file31 reader; byte checks follow existing stat/open semantics, not hostile-code/fd-root isolation. Outer source/import/mount admission still required.',
            'Constructor logical_digest/freeze rebindings; finally releases ending Rows on digest failure. Full genuine completion/schema/ShaMap provenance and large allocation behavior remain UNRUN.',
            'Parse/status/missing-field failures before ending extraction retain scratch; only entered digest/preservation paths have explicit Rows release. Outer failure-root/lifecycle ownership is still required.',
            'Source chain uses actual31 bytes plus all three pinned catalog bytes/two selected transitions and actual holding source. Adaptation receipt still says source_reader_authenticatedFalse; it is not relabelled as old genuine admission.',
            'Preservation uses authenticated inert paper AST metadata for exact17fields/path instead of importing account module; new exact archive type check/finally release. Schema/path metadata parity alone is not preservation parity.',
            'sessions/InitialReceipts/StreamAudit interface intentionally absent. Existing StreamAudit exact OriginalArchives type guard rejects this new class. No account/model entry point or original module spoofing.',
        ],
        'mandatory_unimplemented_composition': seams,
        'behavioral_parity': 'UNVERIFIED; AST equality is not value/type/missingness/alias/deepcopy/readonly/lifetime/RAM proof.',
        'operations': 'Only this local stdlib AST/JSON/source builder ran. No payload import/CodeType/body/test/SSH/hostprobe/Docker/job/data read.',
    }
    review_pin = save(RESEARCH / 'original-loader-archive-context-static-review-v1-2026-10-18.json', review)
    contract = {
        'schema': 'capacity-original-archive-context-contract/1',
        'status': 'SOURCE_PREPARED_CONTEXT_UNEXECUTED_NOT_GENUINE_BINDING',
        'starting_revision': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
        'context_source': {'path': CONTEXT, **identity(raw)},
        'static_review': {'path': 'original-loader-archive-context-static-review-v1-2026-10-18.json', **review_pin},
        'proposed_module_map': module_map, 'proposed_module_map_compact_sha256': map_digest,
        'map_scope': 'Immutable declaration for eight explicit files only; not a full2446/executor/import closure, not an assembled tree, runtime finder, phase/call manifest or genuine source admission. Original2431/N2native31/producer27471 maps stay distinct.',
        'complete_executor_source_map': None, 'generated_call_manifest': None,
        'entrypoint': None, 'launch': None, 'admission': None,
        'execution_authorized': False, 'model_import_strategy': None,
        'mandatory_unimplemented_composition': seams,
        'required_new_acceptance': [
            'Prepare distinct bounded synthetic proposal/caller/packet and source/native/runtime/resource/invocation review before any body execution. No old80/23/65+4/tiny/diagnostic/v2 replay or admission/root reuse.',
            'Actual new concrete reader must bind all31 exact real N2 sources, reject changed maps/bytes/types/path traversal and show whole-source physical bookends. Root authority is a separate external-admission requirement; identical31-file copies are content-equivalent, not inherently wrong roots. Native31 is not full original2431 admission.',
            'Compare complete original strict-reader completion/ending Rows/schema/hash/order/ShaMap provenance+count+spool/index identities and deepcopy/no-alias/lifetime through construction/input auth/unchanged/release, including failure cleanup/retention.',
            'Separate explicit synthetic originals from genuine provenance; test exact field/path/schema/full session+physical bytes preservation and missing/extra/wrong/nonfinite/corrupt/spool/changed-source refusals without general normalization.',
            'Review every admission seam in the new capacity composition, separate original source root aliases/new import source map/receipt paths and actual whole-memory coexistence before a genuine capacity proposal. Full parser/default-cap/model/RAM/history acceptance remains unverified.',
        ],
        'genuine_archive_context_ready': False, 'all_context_bodies': 'UNRUN',
        'unchanged': {'guard_caps_source_checks': True, 'original_timing': 'FAILED', 'publication': 'CLOSED', 'historical_weekday_intraday_fill_UI_RAM_horizon': 'UNVERIFIED', 'genuine_v6': 'OPEN_PAUSED_NO_REPLAY_ADOPTION_NEW_RUN', 'heartbeat': 'ACTIVE'},
    }
    contract_pin = save(RESEARCH / 'original-loader-archive-context-contract-v1-2026-10-18.json', contract)
    print(json.dumps({'contract': contract_pin, 'review': review_pin, 'module_map': map_digest, 'declarations': len(declarations), 'normalized_comparisons': len(comparisons)}, sort_keys=True))


if __name__ == '__main__':
    main()
