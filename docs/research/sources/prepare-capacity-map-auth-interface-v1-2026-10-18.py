"""Prepare a separately named data-only interface cut; never import payload code."""

import ast
from hashlib import sha256
import io
import json
import os
from pathlib import Path
import tokenize

REPO = Path('/Users/animallya/.codex/worktrees/learned-live-release-20261006/PersonalAssistant')
DOCS = REPO / 'docs/research'
ROOT = Path('/tmp/capacity-map-auth-interface-source-20261018-v1')
MAP_SHA = '5a605c1018f3274ad6ccd6e6363e20587e7769b5d46b0cfa2ece3ebcdb85e248'
GUARD_SHA = '030cb5bb25f89c2785e6acbd55aceff5c99b632a5eb538079ee027362ae6178a'
SOURCES = {
    'parser': ('backend/market/original_history_json.py', 'de29c1017f4c9eadd874b2fbe0d85b4c80ced8e7a43fb6bd4f779c3d726cb2eb'),
    'lifecycle': ('docs/research/sources/original-loader-capacity-loader-lifecycle-v1-2026-10-18.py', 'ba888e95f5925d7ffb084ce3d15688299f9987284e8a9e38fd1d54a1c772ebc4'),
    'input_auth': ('backend/market/live_model_history_input_auth.py', '35ad5f5f96fa7951b6163512ab733a9168869eef17038e030b7dad4dcbb1b111'),
    'adaptations': ('docs/research/sources/original-loader-capacity-archive-adaptations-v1-2026-10-18.py', '39f2884741036bbe3a33f451909a59b46924c43ea699e39670c1c13fbcde5134'),
    'archives': ('docs/research/sources/original-loader-capacity-archive-context-v1-2026-10-18.py', '0212bc8dedd0fb44502547fe974670ef84c21db608ab633e2a818c9e718e692b'),
}


# Hash exact source bytes without interpreting application or account objects.
def digest(raw):
    return sha256(raw).hexdigest()


# Read one externally pinned original source without importing its module.
def pinned(relative, expected):
    raw = (REPO / relative).read_bytes()
    assert digest(raw) == expected, relative
    return raw


# Persist new bounded source declarations exclusively and check the complete readback.
def save(path, raw, *, metadata=False):
    assert len(raw) <= (16777216 if metadata else 262144), str(path)
    with path.open('xb') as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    assert path.read_bytes() == raw
    return {'path': str(path), 'sha256': digest(raw), 'bytes': len(raw)}


# Encode finite source metadata while keeping every payload body unexecuted.
def encoded(value):
    return json.dumps(value, sort_keys=True, indent=2, allow_nan=False).encode() + b'\n'


# Apply one exact textual seam rather than silently accepting a missing source anchor.
def replace_once(text, before, after):
    assert text.count(before) == 1, before
    return text.replace(before, after)


# Rename only explicit Python identifiers, without changing message or receipt strings.
def identifiers(text, replacements):
    tokens = list(tokenize.generate_tokens(io.StringIO(text).readline))
    seen = set()
    result = []
    for token in tokens:
        if token.type == tokenize.NAME and token.string in replacements:
            seen.add(token.string)
            token = token._replace(string=replacements[token.string])
        result.append(token)
    assert seen == set(replacements)
    return tokenize.untokenize(result)


# Preserve a new module identity and all original function purpose comments as inert source.
def module(kind, filename, proposed, text):
    raw = ('# SOURCE ONLY: separately versioned capacity data interface; all bodies UNRUN.\n'
           '# This is a new module/type identity, not the original verified reader or receipt.\n' + text).encode()
    tree = ast.parse(raw)
    lines = raw.decode().splitlines()
    functions = [node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)]
    for node in functions:
        line = min([node.lineno] + [item.lineno for item in node.decorator_list])
        assert lines[line - 2].lstrip().startswith('#'), (kind, node.name)
    record = save(DOCS / 'sources' / filename, raw)
    save(ROOT / filename, raw)
    return {**record, 'path': 'sources/' + filename, 'proposed_origin': proposed, 'functions': len(functions), 'payload_bodies_run': False}


# Prepare an explicit pure-data method rename and all immediate typed data consumers.
def main():
    ROOT.mkdir(exist_ok=False)
    source = {key: pinned(*row) for key, row in SOURCES.items()}
    guard = pinned('docs/research/sources/original-loader-capacity-harness-v3-2026-10-18.py', GUARD_SHA)
    tree = ast.parse(guard)
    assignments = {target.id: item.value for item in tree.body if isinstance(item, ast.Assign) for target in item.targets if isinstance(target, ast.Name)}
    assert 'verify' in ast.literal_eval(assignments['FORBIDDEN_NAMES'].args[0])
    parser = replace_once(source['parser'].decode(), '    def verify(self):', '    def authenticate_contents(self):')
    parser = replace_once(parser, '            result.verify()', '            result.authenticate_contents()')
    input_auth = replace_once(source['input_auth'].decode(), 'from backend.market import original_history_json as streamed', 'from backend.market import capacity_original_history_json_v1 as streamed')
    input_auth = replace_once(input_auth, '        value.verify()', '        value.authenticate_contents()')
    adaptations = replace_once(source['adaptations'].decode(), 'from backend.market import original_history_json as streamed', 'from backend.market import capacity_original_history_json_v1 as streamed')
    adaptations = replace_once(adaptations, "SCHEMA = 'capacity-original-archive-adaptations/1'", "SCHEMA = 'capacity-original-archive-adaptations/2'")
    archives = replace_once(source['archives'].decode(), 'from backend.market import original_history_json as streamed', 'from backend.market import capacity_original_history_json_v1 as streamed')
    archives = replace_once(archives, 'from backend.market import live_model_history_input_auth as byte_auth', 'from backend.market import capacity_original_input_auth_v1 as byte_auth')
    archives = replace_once(archives, 'from backend.market import capacity_original_archive_adaptations_v1 as adaptations', 'from backend.market import capacity_original_archive_adaptations_v2 as adaptations')
    archives = replace_once(archives, "SCHEMA = 'capacity-original-archive-context/1'", "SCHEMA = 'capacity-original-archive-context/2'")
    archives = replace_once(archives, '            inputs.verify()', '            inputs.authenticate_contents()')
    archives = identifiers(archives, {'CapacityOriginalArchivesV1': 'CapacityOriginalArchivesV2', 'CapacitySourceReaderV1': 'CapacitySourceReaderV2'})
    modules = {}
    for key, text, proposed, filename in (
        ('parser', parser, 'backend/market/capacity_original_history_json_v1.py', 'capacity-original-history-json-v1-2026-10-18.py'),
        ('input_auth', input_auth, 'backend/market/capacity_original_input_auth_v1.py', 'capacity-original-input-auth-v1-2026-10-18.py'),
        ('adaptations', adaptations, 'backend/market/capacity_original_archive_adaptations_v2.py', 'capacity-original-archive-adaptations-v2-2026-10-18.py'),
        ('archives', archives, 'backend/market/capacity_original_archives_v2.py', 'capacity-original-archive-context-v2-2026-10-18.py'),
    ):
        modules[key] = module(key, filename, proposed, text)
    base = json.loads(pinned('docs/research/original-loader-composition-source-map-v1-2026-10-18.json', MAP_SHA))
    additions = {row['proposed_origin']: row['sha256'] for row in modules.values()}
    assert len(base['files']) == 2459 and not set(additions) & set(base['files'])
    declaration = {'schema': 'capacity-data-interface-source-declaration/1', 'base2459_sha256': MAP_SHA, 'additions': additions, 'files': {**base['files'], **additions}}
    assert len(declaration['files']) == 2463
    map_record = save(DOCS / 'original-loader-map-auth-interface-source-map-v1-2026-10-18.json', encoded(declaration), metadata=True)
    map_record['path'] = Path(map_record['path']).name
    contract = {
        'schema': 'capacity-map-auth-interface-source-contract/1', 'status': 'SOURCE_ONLY_NEW_DATA_IDENTITIES_ALL_PAYLOAD_BODIES_UNRUN',
        'guard': {'path': 'sources/original-loader-capacity-harness-v3-2026-10-18.py', 'sha256': GUARD_SHA, 'unchanged': True, 'profile_forbidden_before_manifest': 'backend co_name verify => FORBIDDEN_FUNCTION'},
        'original_sources': {key: {'path': row[0], 'sha256': row[1], 'bytes': len(source[key])} for key, row in SOURCES.items()},
        'modules': modules, 'source_map_declaration': map_record,
        'original_collision_chain': [
            'CapacityLoaderLeaseV1.__init__ -> CapacityOriginalArchivesV1.__init__ -> streamed.read external_inputs=True -> Cursor.sha_map -> ShaMap.verify during ADMISSION',
            'CapacityArchive/LoaderLeaseV1._bytes -> byte_auth.authenticate -> streamed.read external_inputs=True -> ShaMap.verify, then verify_sha_map(inputs) -> ShaMap.verify',
            'CapacityOriginalArchivesV1.unchanged -> completion input_sha256.verify during AFTER',
        ],
        'source_only_conditional_barrier': 'Given earlier imports/admissions/reads succeed, unchanged guard refuses the pure-data ShaMap.verify body before call-manifest lookup. This is source reachability, not an observed genuine failure or certified first runtime event.',
        'exact_deltas': {
            'parser': 'ShaMap.verify declaration becomes authenticate_contents; only Cursor.sha_map own call changes. All complete method bodies, checks, sealed spool/index/canonical hashes, bounds, return fields, release semantics and allocations retained as source.',
            'input_auth': 'Import new parser identity and call authenticate_contents only; verify_sha_map name is already permitted. All full original source/input two-read receipts and return fields unchanged in source; new Pins/ShaMap/module identities explicit.',
            'adaptations': 'Only new parser import and schema2; exact new Rows type check and digest use same parser identity as new archive context.',
            'archives': 'Only new parser/input_auth/adaptations imports, schema2, explicit class/source-reader namesV2 and input-map method call. Complete original admissions, source catalogs, physical=True logical comparison, archive sizes/source checks/scratch/lifetimes retained.',
        },
        'identity_receipt_limits': 'New Row/Rows/ShaMap/ArchiveRef/History/Cursor/Pins/context/source-reader identities. No alias, monkeypatch, sys.modules injection, original source overwrite or old receipt relabel. Equal source bodies/receipt shapes do not prove behavior/type/readonly/alias/digest/lifetime/RAM parity. Original byte-auth receipt795d4c6b and all old proofs stay separate.',
        'upstream_uncomposed': 'Old2459 binding deliberately refuses this new map. Old input factory requires exact V1 archives; old lifecycle/admissions still bind old byte_auth/parser. A DISTINCT source-bound upstream composition/map transition/finder/guard contract must select the new identities consistently before any execution proposal. No claim that new data modules repair the old composition at runtime.',
        'native_and_generated': 'Parser dataclasses/SQLite/tempfile/fsync and input-auth Pins are unexecuted new identities. Exact runtime/dataclass format2/native closure/call and phase manifests remain absent. No model/provider/account imports or source-body tests run.',
        'unadmitted': {key: None for key in ('entrypoint', 'upstream_composition', 'executed_map', 'finder', 'call_manifest', 'generated_manifest', 'phase_manifest', 'native_package_closure', 'model_import_strategy', 'wrapper', 'owner', 'caller', 'stager', 'bootstrap', 'packet', 'runtime', 'launch', 'admission')},
        'execution_authorized': False,
        'next': 'Independently compare every complete AST after only declared interface/import/type/schema changes. Then SOURCE ONLY compose all new upstream archive/result/input-auth/admission/lifecycle/type/map bindings and complete import/call/guard closure. Do not weaken original verify guard or execute old/new payloads.',
        'unchanged': {'old_sources_maps_proofs_roots_packets_admissions': True, 'guard_G08_caps': True, 'production_original_account_history': True, 'original_timing': 'FAILED', 'publication': 'CLOSED', 'v6': 'OPEN_PAUSED_NO_REPLAY_ADOPTION_NEW_RUN', 'model_RAM_history_ordinary_intraday_fill_UI': 'UNVERIFIED', 'heartbeat': 'ACTIVE'},
    }
    record = save(DOCS / 'original-loader-map-auth-interface-source-contract-v1-2026-10-18.json', encoded(contract))
    save(ROOT / 'contract-pointer.json', encoded(record))
    descriptor = os.open(ROOT, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    print(json.dumps({'contract': record, 'modules': modules, 'map': map_record, 'payload_bodies_run': False}, sort_keys=True))


if __name__ == '__main__':
    main()
