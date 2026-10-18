"""Prepare distinct fixed native-path HEAD controls without dispatch or content reads."""
import ast
import hashlib
import json
from pathlib import Path
import sys

SOURCES = Path(__file__).resolve().parent
RESEARCH = SOURCES.parent
SEAM_SHA = '15f8249875d0aef99b9f48d0e3eb9c1971cf85d23fefc09d27d9ed7538325128'


# Apply one exact declared textual change and refuse drift.
def once(text, old, new):
    assert text.count(old) == 1, old[:100]
    return text.replace(old, new, 1)


# Recover a pinned operational source without importing it.
def source(name, sha):
    raw = (SOURCES / name).read_bytes()
    assert hashlib.sha256(raw).hexdigest() == sha
    return raw.decode()


# Extract a top-level operational function and its purpose comment.
def function(text, name):
    item, = [n for n in ast.parse(text).body if isinstance(n, ast.FunctionDef) and n.name == name]
    return '\n'.join(text.splitlines()[item.lineno - 2:item.end_lineno])


# Preserve a new parseable source with an exclusive write and exact readback.
def write(name, text):
    raw = text.encode()
    ast.parse(raw)
    with (SOURCES / name).open('xb') as stream:
        stream.write(raw)
    assert (SOURCES / name).read_bytes() == raw
    return hashlib.sha256(raw).hexdigest(), len(raw)


# Derive the exact fixed declaration literal from the authenticated requirements-only seam.
def declarations():
    raw = (RESEARCH / 'original-loader-package-metadata-record-seams-v1-2026-10-18.json').read_bytes()
    assert hashlib.sha256(raw).hexdigest() == SEAM_SHA and len(raw) == 18911
    rows = json.loads(raw)['native_filename_declarations']['selected_candidates']
    assert len(rows) == 20 and len({r['lexical_absolute_path'] for r in rows}) == 20
    for row in rows:
        assert row['actual_path_file_hash_ELF_or_load_observed'] is False
        assert row['declared_size_decimal'].isdecimal() and int(row['declared_size_decimal']) > 0
        assert row['declared_hash']['algorithm'] == 'sha256' and len(row['declared_hash']['digest_hex']) == 64
        assert row['lexical_absolute_path'] == '/usr/local/lib/python3.12/site-packages/' + row['relative_path']
    return "SEAM_SHA = " + repr(SEAM_SHA) + "\nDECLARATIONS = " + repr(rows) + "\nPATHS = tuple(row['lexical_absolute_path'] for row in DECLARATIONS)"


# Prepare one source-pinned outer transport without starting any process.
def transport(role, name, sha, size):
    text = source('capacity-native-package-text-transport-v1-2026-10-18.py',
        '518ded7394ae1b04db85f32b89e15693086f8e184c231ac2b891391d2f749b08')
    changes = {
        'capacity-native-package-text-census-v1-2026-10-18.py': name,
        '296d0e8dd4d58883388a5c8f5b2d5c0b6d09ccfdbf82cb44c060333637bb1428': sha,
        '13080': str(size),
        'capacity-native-package-text-transport-20261018-v1': 'capacity-native-path-head-' + role + '-transport-20261018-v1',
        'capacity-native-package-text-census-tools-20261018-v1': 'capacity-native-path-head-' + role + '-tools-20261018-v1',
        'collect-new-native-package-texts': 'observe-twenty-native-paths' if role == 'primary' else 'verify-native-path-head',
    }
    if role == 'independent':
        changes['timeout=120'] = 'timeout=70'
    for old, new in changes.items():
        assert old in text
        text = text.replace(old, new)
    return write('native-path-head-' + role + '-transport-v1-2026-10-18.py', text)


# Generate the observer or a separately pinned retained-output checker for one new candidate.
def main(arguments):
    assert arguments == ['primary'] or (len(arguments) == 2 and arguments[0] == 'independent'
        and len(arguments[1]) == 64 and all(c in '0123456789abcdef' for c in arguments[1]))
    old = source('capacity-package-metadata-head-v1-2026-10-18.py',
        '17617e37bb685c7fb40767c750ceb79c0ff2745a8adf9095fade5ac5f850d0bb')
    verifier = source('verify-package-metadata-head-v1-2026-10-18.py',
        '6c17116d9bb1334b7a1e33ebc0ed64867916b56428c24941f077427567ea04ee')
    copy = source('capacity-package-metadata-text-census-v2-2026-10-18.py',
        'd9cadb938ca5d78d722c4b1974a778130962f4d84d69fcfac43d5f7eaa32960c')
    declaration = declarations()
    role = arguments[0]
    text = old if role == 'primary' else verifier
    text = text.replace('capacity-package-metadata-head-20261018-v1', 'capacity-native-path-head-20261018-v1')
    text = text.replace('capacity-package-metadata-head-independent-20261018-v1', 'capacity-native-path-head-independent-20261018-v1')
    begin = text.index("PATHS = tuple(")
    path_node, = [n for n in ast.parse(text).body if isinstance(n, ast.Assign)
        and any(isinstance(t, ast.Name) and t.id == 'PATHS' for t in n.targets)]
    end = sum(len(line) for line in text.splitlines(keepends=True)[:path_node.end_lineno]) - 1
    text = text[:begin] + declaration + text[end:]
    baseline = "BASELINE_INSPECT = Path('/home/animallya96/scratch/capacity-package-metadata-head-20261018-v1/inspect-before.stdout')\n"
    text = once(text, 'CAP = 262144\n', 'CAP = 262144\n' + baseline)
    inspection = function(copy, 'inspection')
    if role == 'primary':
        text = once(text,
            "            connection.settimeout(max(0.001, limit - time.monotonic()))\n            connection.connect('/var/run/docker.sock')\n            connection.settimeout(max(0.001, limit - time.monotonic()))\n            connection.sendall(request)",
            "            remaining = limit - time.monotonic()\n            if remaining <= 0:\n                raise TimeoutError('HEAD_BEFORE_CONNECT_DEADLINE')\n            connection.settimeout(remaining)\n            connection.connect('/var/run/docker.sock')\n            remaining = limit - time.monotonic()\n            if remaining <= 0:\n                raise TimeoutError('HEAD_BEFORE_SEND_DEADLINE')\n            connection.settimeout(remaining)\n            connection.sendall(request)")
        text = once(text, 'import signal\n', 'import signal\nimport stat\n')
        text = once(text, '# Observe paired path headers between exact stopped-container bookends without reading package content.',
            function(verifier, 'physical') + '\n\n\n' + function(verifier, 'read') + '\n\n\n' + inspection
            + '\n\n\n# Observe paired native path headers under a cumulative deadline without requesting their bodies.')
        text = once(text, "['observe-six-metadata-paths']", "['observe-twenty-native-paths']")
        text = once(text, "        before_raw = command", "        baseline_raw, baseline_row = read(BASELINE_INSPECT)\n        assert digest(baseline_raw) == BASELINE and len(baseline_raw) == 9755\n        saved_baseline = save('baseline-inspect.json', baseline_raw)\n        before_raw = command")
        text = once(text, '        before = inspect_source(before_raw)\n        assert digest(before_raw) == BASELINE',
            '        before = inspection(before_raw, baseline_raw)')
        text = once(text, "            paths.append({'container_path': path, 'reads': reads})",
            "            assert reads[0]['path_metadata']['http_status'] == 200\n            assert reads[0]['path_metadata']['stat']['size'] == int(DECLARATIONS[index]['declared_size_decimal'])\n            paths.append({'container_path': path, 'declaration': DECLARATIONS[index], 'reads': reads})")
        text = once(text, '        assert inspect_source(after_raw) == before and digest(after_raw) == BASELINE',
            "        after = inspection(after_raw, baseline_raw)\n        assert read(BASELINE_INSPECT) == (baseline_raw, baseline_row)")
        text = once(text, "'stopped-n2-package-metadata-head/1'", "'stopped-n2-native-path-head/1'")
        text = once(text, "'full_inspect_baseline_sha256': BASELINE,", "'full_inspect_baseline_sha256': BASELINE,\n            'declaration_seam_sha256': SEAM_SHA,\n            'inspection_binding': {'baseline': saved_baseline, 'baseline_physical': baseline_row,\n                'before': before, 'after': after, 'raw_before_after_equal': before_raw == after_raw},")
        text = once(text, '"""Observe only six fixed stopped-N2 metadata paths through bounded HEAD requests."""',
            '"""Observe twenty RECORD-declared stopped-N2 native paths through bounded HEAD only."""')
        name = 'capacity-native-path-head-v1-2026-10-18.py'
    else:
        text = once(text, '    signal.alarm(10)\n    try:',
            '    # Preserve the existing run() alarm across the fresh inspection and final readback.\n    try:')
        text = once(text, "CANDIDATE_SHA = '42d6171789b08b0b2b9c305a6fe564829982befd752b1779813de4edc4ac64af'",
            'CANDIDATE_SHA = ' + repr(arguments[1]))
        text = once(text, '# Authenticate every retained request, wire, receipt and exact stopped-container bookend independently.',
            function(old, 'inspect_source') + '\n\n\n' + inspection
            + '\n\n\n# Authenticate all retained fixed native-path HEAD observations without requesting native bodies.')
        text = once(text, "['verify-package-metadata-head']", "['verify-native-path-head']")
        text = once(text, "'stopped-n2-package-metadata-head/1'", "'stopped-n2-native-path-head/1'")
        text = once(text, "    names = {'candidate.json', 'prerequisites.json'}",
            "    assert candidate['declaration_seam_sha256'] == SEAM_SHA\n    names = {'candidate.json', 'prerequisites.json', 'baseline-inspect.json'}")
        text = once(text, '    for index in range(6):', '    for index in range(20):')
        text = once(text, 'len(names) == 44', 'len(names) == 129')
        text = once(text, "    for label in ('inspect-before', 'inspect-after'):\n        receipt =",
            "    baseline_raw = bodies['baseline-inspect.json']\n    assert digest(baseline_raw) == BASELINE and len(baseline_raw) == 9755\n    binding = candidate['inspection_binding']\n    assert binding['baseline'] == {'file': 'baseline-inspect.json', 'bytes': 9755, 'sha256': BASELINE}\n    assert binding['raw_before_after_equal'] == (bodies['inspect-before.stdout'] == bodies['inspect-after.stdout'])\n    for label in ('inspect-before', 'inspect-after'):\n        receipt =")
        text = once(text, "        assert digest(bodies[label + '.stdout']) == BASELINE",
            "        assert binding[label.removeprefix('inspect-')] == inspection(bodies[label + '.stdout'], baseline_raw)")
        text = once(text, "        assert len(candidate['paths'][index]['reads']) == 2",
            "        assert candidate['paths'][index]['declaration'] == DECLARATIONS[index]\n        assert len(candidate['paths'][index]['reads']) == 2")
        text = once(text, "        observations.append({'container_path': path, 'path_metadata': decoded[0]})",
            "        assert decoded[0]['http_status'] == 200\n        assert decoded[0]['stat']['size'] == int(DECLARATIONS[index]['declared_size_decimal'])\n        observations.append({'container_path': path, 'declaration': DECLARATIONS[index], 'path_metadata': decoded[0]})")
        text = once(text, "        assert digest(fresh) == BASELINE and fresh == bodies['inspect-before.stdout'] == bodies['inspect-after.stdout']",
            "        fresh_binding = inspection(fresh, baseline_raw)\n        baseline_now, baseline_observed = read(BASELINE_INSPECT)\n        assert baseline_now == baseline_raw and baseline_observed == binding['baseline_physical']")
        text = once(text, "'stopped-n2-package-metadata-head-independent/1'", "'stopped-n2-native-path-head-independent/1'")
        text = once(text, "'candidate_sha256': CANDIDATE_SHA, 'inventory': inventory, 'files': 44,",
            "'candidate_sha256': CANDIDATE_SHA, 'declaration_seam_sha256': SEAM_SHA,\n            'inventory': inventory, 'files': 129, 'original_baseline_physical': baseline_observed,")
        text = once(text, "'path_observations': observations, 'fresh_stopped_inspect_sha256': digest(fresh),",
            "'path_observations': observations, 'fresh_stopped_inspect_sha256': digest(fresh),\n            'inspection_binding': {'before': binding['before'], 'after': binding['after'], 'fresh': fresh_binding},")
        name = 'verify-native-path-head-v1-2026-10-18.py'
    sha, size = write(name, text)
    transport_sha, transport_size = transport(role, name, sha, size)
    print(json.dumps({'role': role, 'helper': name, 'sha256': sha, 'bytes': size,
        'transport_sha256': transport_sha, 'transport_bytes': transport_size}, sort_keys=True))


if __name__ == '__main__':
    main(sys.argv[1:])
