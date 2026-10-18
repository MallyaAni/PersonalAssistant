"""Local stdlib-only source packet builder; payload imports/compilation/bodies forbidden."""
import ast
import base64
import gzip
import hashlib
import json
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SOURCES = ROOT / 'docs/research/sources'
OUTPUT = Path('/tmp/capacity-context-parity-packet-20261018-v1')
OLD_METADATA = Path('/tmp/n2-metadata-tiny-packet-20261018-v1/packet.json')
OLD_PARITY = Path('/tmp/capacity-evidence-parity-packet-20261018-v1/packet.json')
FILES = {}


# Identify full exact immutable source bytes rather than parsed-source approximations.
def sha(raw):
    return hashlib.sha256(raw).hexdigest()


# Read a preserved packet only as authenticated inert source input, never dispatch its old bootstrap.
def previous(path, expected):
    raw = path.read_bytes()
    assert sha(raw) == expected
    value = json.loads(raw)
    result = {}
    for name, item in value['files'].items():
        data = base64.b64decode(item['base64'], validate=True)
        assert len(data) == item['bytes'] and sha(data) == item['sha256']
        result[name] = data
    return result


# Add one ordinary bounded source and reject ambiguous duplicate destinations.
def add(name, raw):
    assert name not in FILES and type(raw) is bytes and len(raw) <= 262144
    FILES[name] = raw


# Read exact original producer bytes from Git without executing any original Python body.
def original(name):
    result = subprocess.run(['git', 'show', '27471b9c:' + name], cwd=ROOT, check=True, capture_output=True)
    return result.stdout


# Persist one new local packet artifact with fsync and exact readback.
def save(path, raw):
    with path.open('xb') as output:
        output.write(raw)
        output.flush()
        os.fsync(output.fileno())
    assert path.read_bytes() == raw


# Build the distinct source-only synthetic73 envelope from real modules and preserved inert references.
def main():
    assert not OUTPUT.exists()
    # These complete packet SHAs authenticate old source inputs only, not a new admission or body replay.
    metadata_raw = OLD_METADATA.read_bytes()
    parity_raw = OLD_PARITY.read_bytes()
    # Full identities are fixed in the earlier exact-source proofs, independently checked before this builder runs.
    metadata_proof = json.loads((ROOT / 'docs/research/original-loader-metadata-tiny-source-proof-2026-10-18.json').read_bytes())
    parity_proof = json.loads((ROOT / 'docs/research/original-loader-evidence-parity-source-proof-v1-2026-10-18.json').read_bytes())
    assert sha(metadata_raw).startswith('881af874') and sha(parity_raw).startswith('edac83ca')
    # Require each complete hash to occur in its immutable earlier proof, not merely its displayed prefix.
    assert sha(metadata_raw) in json.dumps(metadata_proof) and sha(parity_raw) in json.dumps(parity_proof)
    old = previous(OLD_METADATA, sha(metadata_raw))
    prior = previous(OLD_PARITY, sha(parity_raw))
    for name, raw in prior.items():
        if name.startswith('audit/reference/') or name in ('audit/native31.json', 'audit/reference-config.json'):
            add(name, raw)
    add('audit/current-paper-source.txt', old['audit/current-paper-source.txt'])
    for name, raw in old.items():
        if name.startswith('audit/fixture/'):
            add('audit/inert-source/' + name.removeprefix('audit/fixture/'), raw)
    candidate = {
        'capacity_original_metadata_v1.py': 'original-loader-capacity-metadata-boundary-2026-10-18.py',
        'capacity_original_evidence_v1.py': 'original-loader-capacity-evidence-v1-2026-10-18.py',
        'capacity_original_archive_adaptations_v1.py': 'original-loader-capacity-archive-adaptations-v1-2026-10-18.py',
        'capacity_original_archives_v1.py': 'original-loader-capacity-archive-context-v1-2026-10-18.py',
        'capacity_original_calendar_v1.py': 'original-loader-capacity-calendar-v1-2026-10-18.py',
        'capacity_original_admissions_v1.py': 'original-loader-capacity-admissions-v1-2026-10-18.py',
        'capacity_original_admission_lifecycle_v1.py': 'original-loader-capacity-admission-lifecycle-v1-2026-10-18.py'}
    for name, source in candidate.items():
        add('audit/app/backend/market/' + name, (SOURCES / source).read_bytes())
    for name in ('backend/__init__.py', 'backend/market/__init__.py', 'backend/market/original_history_json.py'):
        add('audit/app/' + name, prior['audit/app/' + name])
    add('audit/app/backend/market/live_model_history_input_auth.py', (ROOT / 'backend/market/live_model_history_input_auth.py').read_bytes())
    tree = ast.parse((SOURCES / candidate['capacity_original_archives_v1.py']).read_bytes())
    constants = {n.targets[0].id: ast.literal_eval(n.value) for n in tree.body if isinstance(n, ast.Assign) and isinstance(n.targets[0], ast.Name) and n.targets[0].id in ('SOURCE_PATHS', 'ORIGINAL_SOURCES', 'CATALOG_PATHS')}
    for name in sorted(set(constants['SOURCE_PATHS']) | set(constants['ORIGINAL_SOURCES'])):
        destination = 'audit/inert-source/' + name
        raw = original(name)
        if destination in FILES:
            assert FILES[destination] == raw
        else:
            add(destination, raw)
        if name in constants['ORIGINAL_SOURCES']:
            assert sha(raw) == constants['ORIGINAL_SOURCES'][name]
    for name in constants['CATALOG_PATHS']:
        add('audit/inert-source/' + name, prior['audit/reference/' + name])
    for name in ('calendar.py', 'data/nyse_holidays.json', 'data/nyse_historical_sessions.json', 'data/nyse_early_closes.json'):
        raw = original('backend/market/' + name)
        add('audit/reference/backend/market/' + name, raw)
        if name != 'calendar.py':
            add('audit/app/backend/market/' + name, raw)
    for target, suffix in (('bootstrap.py', 'bootstrap'), ('fixtures.py', 'fixtures'), ('cases.py', 'cases'), ('units.py', 'units')):
        add('audit/' + target, (SOURCES / ('original-loader-context-parity-' + suffix + '-v1-2026-10-18.py')).read_bytes())
    for target, suffix in (('context-owner.py', 'owner'), ('caller.py', 'caller'), ('stager.py', 'stager')):
        add('owner/' + target, (SOURCES / ('original-loader-context-parity-' + suffix + '-v1-2026-10-18.py')).read_bytes())
    add('owner/controller.py', prior['owner/controller.py'])
    assert sha(FILES['owner/controller.py']) == '2e505205cc8a3793d7b3313a5b5c3b670b00134575982d26c725787b6530df5a'
    proposal = json.loads((ROOT / 'docs/research/original-loader-archive-context-parity-proposal-v1-2026-10-18.json').read_bytes())
    names = [name for group in proposal['groups'].values() for name in group['cases']]
    assert len(names) == len(set(names)) == 73
    add('audit/cases.json', json.dumps({n: g['cases'] for n, g in proposal['groups'].items()}, sort_keys=True).encode())
    raw_map = (ROOT / 'docs/research/original-loader-admission-source-map-v1-2026-10-18.json').read_bytes()
    assert len(raw_map) == 570874 and sha(raw_map) == 'a68ebbefb776a93dfdfb56fc6c4893ac35450a224fcf2fa50498cb911bfeda43'
    compressed_map = gzip.compress(raw_map, mtime=0)
    add('audit/source-map.json.gz', compressed_map)
    add('audit/map-binding.json', json.dumps({'raw_bytes': len(raw_map), 'raw_sha256': sha(raw_map), 'gzip_bytes': len(compressed_map), 'gzip_sha256': sha(compressed_map)}, sort_keys=True).encode())
    pins = {name.removeprefix('audit/'): {'sha256': sha(raw), 'bytes': len(raw)} for name, raw in sorted(FILES.items()) if name.startswith('audit/')}
    add('audit/pins.json', json.dumps(pins, sort_keys=True, indent=2).encode() + b'\n')
    book = json.dumps({'schema': 'capacity-context-parity-source/1', 'files': {name: {'sha256': sha(raw), 'bytes': len(raw)} for name, raw in sorted(FILES.items())}}, sort_keys=True, indent=2).encode() + b'\n'
    packet_files = {}
    for name, raw in sorted(FILES.items()):
        if name.endswith('.py'):
            ast.parse(raw, filename=name)
        compressed = gzip.compress(raw, mtime=0)
        packet_files[name] = {'gzip_base64': base64.b64encode(compressed).decode(), 'gzip_sha256': sha(compressed),
            'gzip_bytes': len(compressed), 'sha256': sha(raw), 'bytes': len(raw)}
    packet = json.dumps({'schema': 'capacity-context-parity-packet/1', 'files': packet_files,
        'source_book': base64.b64encode(book).decode(), 'source_book_sha256': sha(book)}, sort_keys=True, separators=(',', ':')).encode() + b'\n'
    assert len(packet) <= 2097152 and len(book) <= 262144 and len(FILES) <= 128 and sum(map(len, FILES.values())) <= 8 * 1024**2
    OUTPUT.mkdir(mode=0o700)
    save(OUTPUT / 'packet.json', packet)
    save(OUTPUT / 'source-book.json', book)
    report = {'schema': 'capacity-context-parity-packet-build/1', 'packet_sha256': sha(packet), 'packet_bytes': len(packet),
        'source_book_sha256': sha(book), 'source_book_bytes': len(book), 'records': len(FILES), 'decoded_bytes': sum(map(len, FILES.values())),
        'source_map_raw_bytes': len(raw_map), 'source_map_gzip_bytes': len(compressed_map), 'planned_cases': 73,
        'payload_import_or_compilation_or_body_execution': False, 'execution_authorized': False}
    save(OUTPUT / 'build.json', json.dumps(report, sort_keys=True, indent=2).encode() + b'\n')
    print(json.dumps(report, sort_keys=True))


if __name__ == '__main__':
    main()
