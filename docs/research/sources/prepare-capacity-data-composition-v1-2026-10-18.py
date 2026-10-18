"""Prepare inert upstream data-type composition; no payload imports or executable compilation."""
import ast
from hashlib import sha256
import io
import json
import os
from pathlib import Path
import tokenize

REPO = Path('/Users/animallya/.codex/worktrees/learned-live-release-20261006/PersonalAssistant')
DOCS = REPO / 'docs/research'
ROOT = Path('/tmp/capacity-data-composition-source-20261018-v1')
DATA_SHA = 'd78058068ee9fb03722971917a32dcb6589dcf43fa2320fa51d4c998e8c695f0'
COMPOSITION_SHA = '5a605c1018f3274ad6ccd6e6363e20587e7769b5d46b0cfa2ece3ebcdb85e248'
ORIGINALS = {
    'admissions': ('original-loader-capacity-admissions-v1-2026-10-18.py', 'f7a226b3d90472ac3ebe161e4c46beb2c49245d489ac1de4a78f90ee2af6d0a9'),
    'inputs': ('original-loader-capacity-inputs-v1-2026-10-18.py', '8470e2b579cc39b32113e2fcb88e8e918eac283e900f7d62341059761c524661'),
    'binding': ('original-loader-capacity-loader-binding-v1-2026-10-18.py', 'd41e2bf0f408fa77dc2d69160ce2452abde3803998e760b5d6113f9bd0d4bc6b'),
    'lifecycle': ('original-loader-capacity-loader-lifecycle-v1-2026-10-18.py', 'ba888e95f5925d7ffb084ce3d15688299f9987284e8a9e38fd1d54a1c772ebc4'),
    'durability': ('original-loader-capacity-admission-lifecycle-v1-2026-10-18.py', '3acd8b296b3d14234d7c769e2ce4c5a63c8e381d87d7677476964ea1a5f84b1b'),
}
UPSTREAM_PATHS = {
    'backend/market/capacity_original_admissions_v2.py',
    'backend/market/capacity_original_inputs_v2.py',
    'backend/market/capacity_original_loader_binding_v2.py',
    'backend/market/capacity_original_loader_lifecycle_v2.py',
    'backend/market/capacity_original_durability_v1.py',
}


# Hash exact bytes without loading any declared application module.
def digest(raw):
    return sha256(raw).hexdigest()


# Read one independently pinned source or metadata declaration.
def pinned(path, expected):
    raw = path.read_bytes()
    assert digest(raw) == expected, str(path)
    return raw


# Keep only new bounded files and verify complete bytes after file fsync.
def save(path, raw, metadata=False):
    assert len(raw) <= (16777216 if metadata else 262144), str(path)
    with path.open('xb') as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    assert path.read_bytes() == raw
    return {'path': str(path), 'sha256': digest(raw), 'bytes': len(raw)}


# Encode finite declarations, not model or account objects.
def encoded(value):
    return json.dumps(value, sort_keys=True, indent=2, allow_nan=False).encode() + b'\n'


# Refuse a source edit unless exactly one reviewed anchor is present.
def changed(text, before, after):
    assert text.count(before) == 1, before
    return text.replace(before, after)


# Change explicit Python identifiers while leaving receipt and error strings alone.
def identifiers(text, replacements):
    seen, result = set(), []
    for token in tokenize.generate_tokens(io.StringIO(text).readline):
        if token.type == tokenize.NAME and token.string in replacements:
            seen.add(token.string)
            token = token._replace(string=replacements[token.string])
        result.append(token)
    assert seen == set(replacements)
    return tokenize.untokenize(result)


# Preserve a distinct inert module and its declared future executor origin.
def module(kind, text):
    origin = 'backend/market/capacity_original_' + {'admissions': 'admissions_v2', 'inputs': 'inputs_v2', 'binding': 'loader_binding_v2', 'lifecycle': 'loader_lifecycle_v2', 'durability': 'durability_v1'}[kind] + '.py'
    name = 'capacity-data-' + kind + '-composition-v1-2026-10-18.py'
    raw = ('# SOURCE ONLY: new upstream identity; no runtime or model admission.\n' + text).encode()
    tree = ast.parse(raw)
    lines = raw.decode().splitlines()
    functions = [node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)]
    for node in functions:
        first = min([node.lineno] + [item.lineno for item in node.decorator_list])
        assert lines[first - 2].lstrip().startswith('#'), (kind, node.name)
    row = save(DOCS / 'sources' / name, raw)
    save(ROOT / name, raw)
    return {**row, 'path': 'sources/' + name, 'proposed_origin': origin, 'functions': len(functions), 'payload_bodies_run': False}


# Compose exact new data identities without weakening any old source or guard.
def main():
    ROOT.mkdir(exist_ok=False)
    old = {key: pinned(DOCS / 'sources' / row[0], row[1]).decode() for key, row in ORIGINALS.items()}
    data_raw = pinned(DOCS / 'original-loader-map-auth-interface-source-map-v1-2026-10-18.json', DATA_SHA)
    data = json.loads(data_raw)
    data_modules = data['additions']
    assert len(data['files']) == 2463 and len(data_modules) == 4
    imports = {
        'live_model_history_input_auth': 'capacity_original_input_auth_v1',
        'capacity_original_admissions_v1': 'capacity_original_admissions_v2',
        'capacity_original_archives_v1': 'capacity_original_archives_v2',
        'capacity_original_archive_adaptations_v1': 'capacity_original_archive_adaptations_v2',
        'capacity_original_loader_binding_v1': 'capacity_original_loader_binding_v2',
        'capacity_original_admission_lifecycle_v1': 'capacity_original_durability_v1',
        'capacity_original_inputs_v1': 'capacity_original_inputs_v2',
    }
    texts = {}
    for key in ('admissions', 'inputs', 'binding', 'lifecycle'):
        used = {before: after for before, after in imports.items() if any(token.type == tokenize.NAME and token.string == before for token in tokenize.generate_tokens(io.StringIO(old[key]).readline))}
        texts[key] = identifiers(old[key], used)
    texts['inputs'] = identifiers(texts['inputs'], {'CapacityOriginalArchivesV1': 'CapacityOriginalArchivesV2', 'CapacityAuditInputsV1': 'CapacityAuditInputsV2'})
    texts['inputs'] = changed(texts['inputs'], "SCHEMA = 'capacity-original-inputs/1'", "SCHEMA = 'capacity-original-inputs/2'")
    texts['lifecycle'] = identifiers(texts['lifecycle'], {'CapacityLoaderLeaseV1': 'CapacityLoaderLeaseV2'})
    texts['lifecycle'] = changed(texts['lifecycle'], 'archives_module.CapacitySourceReaderV1', 'archives_module.CapacitySourceReaderV2')
    texts['lifecycle'] = changed(texts['lifecycle'], 'archives_module.CapacityOriginalArchivesV1', 'archives_module.CapacityOriginalArchivesV2')
    texts['lifecycle'] = changed(texts['lifecycle'], 'inputs_module.CapacityAuditInputsV1', 'inputs_module.CapacityAuditInputsV2')
    texts['lifecycle'] = changed(texts['lifecycle'], "'capacity_original_inputs_v1.CapacityAuditInputsV1'", "'capacity_original_inputs_v2.CapacityAuditInputsV2'")
    texts['lifecycle'] = changed(texts['lifecycle'], "'capacity_original_inputs_v1',", "'capacity_original_inputs_v2',")
    texts['lifecycle'] = changed(texts['lifecycle'], "'calendar', 'live_execution_inputs'):", "'calendar', 'live_execution_inputs', 'capacity_original_history_json_v1', 'capacity_original_input_auth_v1', 'capacity_original_archive_adaptations_v2', 'capacity_original_archives_v2'):")
    texts['lifecycle'] = changed(texts['lifecycle'], "SCHEMA = 'capacity-original-loader-lease/1'", "SCHEMA = 'capacity-original-loader-lease/2'")
    texts['lifecycle'] = changed(texts['lifecycle'], '        self.modules = module_admission(self.binding, self.source_map)', "        self.modules = module_admission(self.binding, self.source_map)\n        self.interfaces = {'data_modules': dict(self.source_map['data_interfaces']), 'upstream_modules': dict(self.source_map['compositions']), 'original_byte_receipt_adopted': False}")
    texts['lifecycle'] = changed(texts['lifecycle'], "result = {'status':", "result = {'schema': 'capacity-loader-data-candidate/1', 'implementation_binding': self.interfaces, 'status':")
    tree = ast.parse(old['durability'])
    sync = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == 'sync_directory')
    sync_text = '\n'.join(old['durability'].splitlines()[sync.lineno - 2:sync.end_lineno])
    bound = next(node for node in tree.body if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == 'MAX_RESULT_BYTES' for target in node.targets))
    texts['durability'] = '"""Unexecuted directory durability primitive under a new module identity."""\nimport os\nimport stat\nfrom backend.market import capacity_original_evidence_v1 as evidence\n\n' + ast.get_source_segment(old['durability'], bound) + '\n\n' + sync_text + '\n'
    binding = texts['binding']
    binding = changed(binding, "SCHEMA = 'capacity-original-loader-binding/1'", "SCHEMA = 'capacity-original-loader-binding/2'")
    binding = changed(binding, "ROOT_KEYS =", 'COMPOSITION_MAP_SHA256 = ' + repr(COMPOSITION_SHA) + '\nDATA_MAP_SHA256 = ' + repr(DATA_SHA) + '\nDATA_INTERFACES = ' + repr(data_modules) + '\nUPSTREAM_PATHS = {' + ', '.join(repr(name) for name in sorted(UPSTREAM_PATHS)) + '}\nROOT_KEYS =')
    binding = changed(binding, "'entry_map', 'source_map',", "'entry_map', 'composition_map', 'data_map', 'source_map',")
    binding = changed(binding, "'entry_map_sha256', 'source_map_sha256',", "'entry_map_sha256', 'composition_map_sha256', 'data_map_sha256', 'source_map_sha256',")
    binding = changed(binding, "    value = admissions.invocation", "    evidence.require(binding['composition_map_sha256'] == COMPOSITION_MAP_SHA256 and binding['data_map_sha256'] == DATA_MAP_SHA256, 'EXACT_DATA_COMPOSITION_CHAIN_REQUIRED')\n    value = admissions.invocation")
    before = "    source_map = evidence.strict_json(evidence.pinned(binding['source_map'], binding['source_map_sha256']))"
    end = "    native = file_map(evidence.strict_json(evidence.pinned(binding['native31'], binding['native31_sha256'])), 31)"
    start_index, end_index = binding.index(before), binding.index(end)
    prefix = binding[start_index:end_index].replace("binding['source_map'], binding['source_map_sha256']", "binding['composition_map'], COMPOSITION_MAP_SHA256")
    prefix = prefix.replace('source_map', 'composition_map')
    suffix = """    data_map = evidence.strict_json(evidence.pinned(binding['data_map'], DATA_MAP_SHA256))
    evidence.require(type(data_map) is dict and set(data_map) == {'schema', 'base2459_sha256', 'additions', 'files'} and data_map['schema'] == 'capacity-data-interface-source-declaration/1' and data_map['base2459_sha256'] == COMPOSITION_MAP_SHA256, 'EXACT_DATA_INTERFACE_SCHEMA_REQUIRED')
    evidence.require(data_map['additions'] == DATA_INTERFACES and not set(DATA_INTERFACES) & set(files), 'EXACT_FOUR_NEW_DATA_INTERFACES_REQUIRED')
    data_files = file_map(data_map['files'], 2463)
    evidence.require(data_files == {**files, **DATA_INTERFACES}, 'EXACT2463_DATA_UNION_REQUIRED')
    source_map = evidence.strict_json(evidence.pinned(binding['source_map'], binding['source_map_sha256']))
    evidence.require(type(source_map) is dict and set(source_map) == {'schema', 'data2463_sha256', 'upstreams', 'files'} and source_map['schema'] == 'capacity-original-loader-data-source-declaration/1' and source_map['data2463_sha256'] == DATA_MAP_SHA256, 'EXACT_UPSTREAM_COMPOSITION_SCHEMA_REQUIRED')
    upstreams = file_map(source_map['upstreams'], 5)
    evidence.require(set(upstreams) == UPSTREAM_PATHS and not set(upstreams) & set(data_files), 'EXACT_FIVE_UPSTREAM_ADDITIONS_REQUIRED')
    files = file_map(source_map['files'], 2468)
    evidence.require(files == {**data_files, **upstreams}, 'EXACT2468_UPSTREAM_UNION_REQUIRED')
"""
    binding = binding[:start_index] + prefix + suffix + binding[end_index:]
    binding = changed(binding, "{'files': files, 'reference': reference, 'compositions': compositions}", "{'files': files, 'reference': reference, 'compositions': upstreams, 'data_interfaces': DATA_INTERFACES}")
    binding = changed(binding, "'executor_files': 2459", "'executor_files': 2468")
    texts['binding'] = binding
    modules = {key: module(key, value) for key, value in texts.items()}
    additions = {row['proposed_origin']: row['sha256'] for row in modules.values()}
    assert set(additions) == UPSTREAM_PATHS and not set(additions) & set(data['files'])
    declaration = {'schema': 'capacity-original-loader-data-source-declaration/1', 'data2463_sha256': DATA_SHA, 'upstreams': additions, 'files': {**data['files'], **additions}}
    assert len(declaration['files']) == 2468
    map_record = save(DOCS / 'original-loader-data-composition-source-map-v1-2026-10-18.json', encoded(declaration), True)
    map_record['path'] = Path(map_record['path']).name
    contract = {'schema': 'capacity-data-upstream-source-contract/1', 'status': 'SOURCE_ONLY_ALL_NEW_BODIES_UNRUN', 'modules': modules, 'original_sources': {key: {'path': 'sources/' + row[0], 'sha256': row[1]} for key, row in ORIGINALS.items()}, 'data_map_sha256': DATA_SHA, 'composition_map_sha256': COMPOSITION_SHA, 'source_map_declaration': map_record,
        'deltas': {'admissions': 'Only new byte-auth/adaptations imports; original schema2 invocation/runtime/source/producer/calendar/package body checks intact.', 'inputs': 'New archiveV2 exact guard/import, resultV2 class and schema2; all factory/numerical/economic/readonly bodies otherwise unchanged.', 'durability': 'Exact original sync_directory body and256MiB expression only; standalone new module avoids importing old lifecycle/byte-auth.', 'binding': 'Only declared new dependency imports/schema; exact old map chain retained, then exact2463 data additions and2468 upstream union. Root/source/calendar/native/module-origin checks unchanged except executor count metadata. No old path override.', 'lifecycle': 'Explicit V2 dependencies/archive/source-reader/input result/Pins/authenticate; real clock/private factory/type lineage/fullgraphs/serialization/fsync order retained. New implementation metadata and result schema prevent old byte receipt adoption.'},
        'identity_and_receipts': 'New class/module globals/CodeTypes are distinct. Metadata source correspondence is not runtime/type/alias/readonly/deepcopy/numeric/factory/lifetime/RAM parity. Original2431 producer/reference2446/newexecutor2468 receipts remain separate; original795d4c6b receipt not adopted.',
        'guard': 'Unchanged030cb5bb guard; no verify whitelist or call/generated manifest. Full import and selected-call closure NOT yet established. Existing V1 modules/binding/maps remain unchanged and refuse these new identities/map.',
        'limits': '16MiB typed map outside ordinary262KiB source/log/packet roots;256MiB result bound unchanged. No cap increase. New declarations are unassembled, not executed-map/finder/runtime admission.',
        'unadmitted': {key: None for key in ('entrypoint', 'executed_map', 'finder', 'call_manifest', 'generated_manifest', 'phase_manifest', 'native_package_closure', 'model_import_strategy', 'wrapper', 'owner', 'caller', 'bootstrap', 'stager', 'packet', 'runtime', 'launch', 'admission')}, 'execution_authorized': False,
        'next': 'Independently review exact new import/type/schema/map/lifetime deltas, then SOURCE ONLY inspect full selected import/call/guard closure and bind distinct source-book/finder/phase/generated/native contracts before any synthetic or genuine runtime proposal. No old gate/body/packet replay.'}
    record = save(DOCS / 'original-loader-data-composition-source-contract-v1-2026-10-18.json', encoded(contract))
    save(ROOT / 'contract-pointer.json', encoded(record))
    print(json.dumps({'contract': record, 'modules': modules, 'map': map_record, 'payload_bodies_run': False}, sort_keys=True))


if __name__ == '__main__':
    main()
