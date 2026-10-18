"""Build only local source/packet metadata; never import or compile any payload CodeType."""
import ast
import base64
import gzip
import hashlib
import io
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SOURCES = ROOT / 'docs/research/sources'
PACKET = Path('/tmp/capacity-context-parity-packet-20261018-v1')


# Return the full identity and byte length of an exact retained artifact.
def identity(raw):
    return {'sha256': hashlib.sha256(raw).hexdigest(), 'bytes': len(raw)}


# Record only source and packet readback evidence, keeping every runtime acceptance unrun.
def main():
    commit = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=ROOT, check=True, capture_output=True, text=True).stdout.strip()
    subprocess.run(['git', 'show', '--check', '--format=', commit], cwd=ROOT, check=True, capture_output=True)
    source_files = sorted(SOURCES.glob('*context-parity*-2026-10-18.py'))
    sources, purpose = {}, 0
    for path in source_files:
        raw = path.read_bytes()
        name = str(path.relative_to(ROOT))
        assert subprocess.run(['git', 'show', commit + ':' + name], cwd=ROOT, check=True, capture_output=True).stdout == raw
        tree, lines = ast.parse(raw, filename=name), raw.decode().splitlines()
        assert raw.endswith(b'\n') and not raw.endswith(b'\n\n')
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                first = min([node.lineno] + [d.lineno for d in node.decorator_list])
                assert lines[first - 2].lstrip().startswith('#')
                purpose += 1
        sources[name] = identity(raw)
    proposal_path = ROOT / 'docs/research/original-loader-archive-context-parity-proposal-v1-2026-10-18.json'
    proposal = json.loads(proposal_path.read_bytes())
    names = {n for group in proposal['groups'].values() for n in group['cases']}
    assert len(names) == 73
    verifier = ast.parse((SOURCES / 'original-loader-context-parity-verifier-v1-2026-10-18.py').read_bytes())
    declarations = {node.targets[0].id: ast.literal_eval(node.value) for node in verifier.body if isinstance(node, ast.Assign)
        and isinstance(node.targets[0], ast.Name) and node.targets[0].id in ('POSITIVE', 'REFUSALS')}
    assert len(declarations['POSITIVE']) == 19 and len(declarations['REFUSALS']) == 54
    assert declarations['POSITIVE'].isdisjoint(declarations['REFUSALS']) and declarations['POSITIVE'] | set(declarations['REFUSALS']) == names
    assert sum(reason is None for _, reason in declarations['REFUSALS'].values()) == 3
    packet_raw = (PACKET / 'packet.json').read_bytes()
    packet = json.loads(packet_raw)
    assert identity(packet_raw) == {'sha256': 'dfd903f31677b5945ae8fceafb25990b237d8780a5060f9469acc064d133f772', 'bytes': 903267}
    book_raw = base64.b64decode(packet['source_book'], validate=True)
    assert book_raw == (PACKET / 'source-book.json').read_bytes()
    assert identity(book_raw)['sha256'] == packet['source_book_sha256']
    book = json.loads(book_raw)
    files = {}
    decoded = {}
    for name, item in packet['files'].items():
        compressed = base64.b64decode(item['gzip_base64'], validate=True)
        assert identity(compressed) == {'sha256': item['gzip_sha256'], 'bytes': item['gzip_bytes']}
        with gzip.GzipFile(fileobj=io.BytesIO(compressed)) as stream:
            raw = stream.read(item['bytes'] + 1)
            assert len(raw) == item['bytes'] <= 262144 and stream.read(1) == b''
        assert identity(raw) == book['files'][name] == {'sha256': item['sha256'], 'bytes': item['bytes']}
        if name.endswith('.py'):
            ast.parse(raw, filename=name)
        files[name] = identity(raw)
        decoded[name] = raw
    assert files == book['files'] and len(files) == 83 and sum(i['bytes'] for i in files.values()) == 1643772
    native = json.loads(decoded['audit/native31.json'])
    assert len(native) == 31
    for name, expected in native.items():
        assert identity(decoded['audit/inert-source/' + name])['sha256'] == expected
    unchanged = {}
    for name in ('original-loader-capacity-archive-context-v1-2026-10-18.py', 'original-loader-capacity-evidence-v1-2026-10-18.py',
        'original-loader-capacity-archive-adaptations-v1-2026-10-18.py', 'original-loader-capacity-metadata-boundary-2026-10-18.py',
        'original-loader-capacity-admissions-v1-2026-10-18.py', 'original-loader-capacity-calendar-v1-2026-10-18.py',
        'original-loader-capacity-admission-lifecycle-v1-2026-10-18.py'):
        path = SOURCES / name
        raw = path.read_bytes()
        assert subprocess.run(['git', 'show', '5cb62db3:' + str(path.relative_to(ROOT))], cwd=ROOT, check=True, capture_output=True).stdout == raw
        unchanged[str(path.relative_to(ROOT))] = identity(raw)
    proof = {
        'schema': 'capacity-context-parity-source-proof/1', 'source_commit': commit,
        'status': 'SOURCE_REVIEWED_PACKET_PREPARED_ALL73_BODIES_UNRUN', 'execution_authorized': False,
        'sources': sources, 'unchanged_candidate_sources': unchanged,
        'proposal': {'path': str(proposal_path.relative_to(ROOT)), **identity(proposal_path.read_bytes())},
        'packet': {'path': str(PACKET / 'packet.json'), **identity(packet_raw), 'records': 83, 'decoded_bytes': 1643772,
            'encoding': 'PER_RECORD_GZIP_WITH_FULL_COMPRESSED_AND_DECODED_SHA_SIZE', 'envelope_bound': 2097152,
            'decoded_file_bound': 262144, 'decoded_aggregate_source_bound': 8388608, 'source_book': identity(book_raw),
            'raw_source_map_bytes': 570874, 'source_map_gzip_bytes': len(decoded['audit/source-map.json.gz']),
            'native31_all_source_bytes_matched': True, 'readback': 'FULL_SHA_BASE64_BOUNDED_GZIP_JSON_AST_PASS_NO_PAYLOAD_EXECUTION'},
        'groups': {name: len(group['cases']) for name, group in proposal['groups'].items()},
        'expected_observations': {'total': 73, 'positive': 19, 'refusals': 54, 'fixed_refusal_reasons': 51,
            'OS_path_dependent_class_only': 3, 'all_status': 'UNRUN', 'original_reference_comparisons':
            'ONLY_TWO_CONSTRUCTOR_PROJECTIONS_AND_TWO_CALENDAR_COMPARISONS_NOT_73_ORIGINAL_PARITY_CASES'},
        'scope': [
            'Real separately named eleven-module candidate closure plus three actual public frozen calendar files proposed at real /audit/app paths; source packet only, no staged tree/import runtime acceptance.',
            'All31 inert N2 source bytes retained without account/provider/policy execution; distinct actual legacy6/producer5 source reads and three authenticated catalogs. Identical copies are content-equivalent, not original source-root authority.',
            'Tiny SYNTHETIC completion/state/session/input fixtures; actual strict Rows/ShaMap planned for provenance/order/hash/release/read-only/deepcopy checks. No genuine373MB/832MB/164833-input account fixture.',
            'Only isolated SYNTHETIC full-compilation constructor/primitive/digest/calendar references proposed; no original effect module execution/import or PaperState instance. Reference source paths remain actual inert reference paths.',
            'Ten binding refusals and fourteen phase-holder cases are explicitly injected UNIT scaffolding. Genuine lifecycle constructor/native_packages/full2453 module admission/model loader remain UNRUN.',
            'Default source/parser/history/result/guard/G08 caps unchanged. Full570874B source map remains240215B authenticated gzip on disk and expands only bounded RAM in negative metadata UNITs. No full-map positive admission.',
            'Separate source-reviewed independent verifier/preserver are outside immutable83-record packet and require a distinct exact tools-source staging closure. Their bodies/inspects/copies are UNRUN.',
            'Paged64-record manifests proposed for complete source/run/review/tool preservation without file-cap exceptions; exact nanoseconds are decimal strings. No crash/timeout/force-stop/transport-loss acceptance.'
        ],
        'review': {'worker': 'EXISTING_HEALTHY_trading_action_consistency_READONLY',
            'operations': 'SOURCE_READ_ONLY_NO_IMPORT_COMPILATION_TEST_EDIT_NETWORK_HOST_OPS',
            'finding_fixed_before_execution': 'Independent verifier initially checked status/nonempty scope only; now exact54 types/51reasons/3OSclasses/allscopes/11origins/native metadata. Initial draft was not packeted or run.',
            'new_agent_or_limited_worker_retry': False},
        'checks': {'AST': 'PASS', 'purpose_comments': purpose, 'JSON_fullSHA_hashlinks': 'PASS', 'packet_independent_readback': 'PASS',
            'Ruff': 'UNAVAILABLE_NOT_CLAIMED', 'diff': 'SOURCE_COMMIT_PASS_FINAL_DOCUMENT_STAGED_CHECK_STILL_REQUIRED',
            'payload_import_CodeType_compile_body_test': 'NONE', 'SSH_hostprobe_Docker_job': 'NONE'},
        'remaining_before_execution': [
            'Prepare and independently review exact source/tool staging and bounded outer transport/native metadata/prerequisite observation/launch contracts.',
            'Fresh actual e0/native package origins/Python/UID/jobs/absent new roots/resource headroom and exact invocation independent review BEFORE ONE new scoped synthetic admission/test.',
            'Do not regenerate this packet or reuse old80/23/65+4/tiny/diagnostic/v2 roots/bodies/admissions. Preserve all roots and failures.',
            'Genuine fullsource/fence/runtime/model strategy/loader entrypoint/admission remain absent; no genuine loader/model/account/history/twohost launch or cap/guard relaxation.'
        ],
        'actual_stage': None, 'native_prerequisite': None, 'actual_outer_transport': None, 'admission': None, 'runtime': None,
        'unchanged': {'original_timing': 'FAILED', 'publication': 'CLOSED', 'missing_original_receipts': 'STILL_MISSING',
            'genuine_v6': 'OPEN_PAUSED_NO_REPLAY_ADOPTION_NEW_RUN', 'fullsource_runtime_model_RAM_horizon_history_weekday_intraday_fill_UI': 'UNVERIFIED',
            'actual_twohost_Spark2_image_daemon_temp_incremental_RAM': 'UNVERIFIED', 'heartbeat': 'ACTIVE', 'diagram': 'NONE'}
    }
    path = ROOT / 'docs/research/original-loader-context-parity-source-proof-v1-2026-10-18.json'
    raw = json.dumps(proof, sort_keys=True, indent=2, allow_nan=False).encode() + b'\n'
    with path.open('xb') as output:
        output.write(raw)
    assert path.read_bytes() == raw
    print(json.dumps({'path': str(path), **identity(raw), 'source_commit': commit, 'all73': 'UNRUN'}, sort_keys=True))


if __name__ == '__main__':
    main()
