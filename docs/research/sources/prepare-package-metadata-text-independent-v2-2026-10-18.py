"""Prepare an independently pinned v2 fold without rerunning any collection."""
import ast
import hashlib
from pathlib import Path
import runpy
import sys

SOURCES = Path(__file__).resolve().parent


# Refuse any absent or repeated declared source change.
def once(text, old, new):
    assert text.count(old) == 1, old[:100]
    return text.replace(old, new, 1)


# Derive one independent checker from pinned operational controls and the actual candidate SHA.
def main(candidate_sha):
    assert len(candidate_sha) == 64 and all(c in '0123456789abcdef' for c in candidate_sha)
    builder = SOURCES / 'prepare-package-metadata-text-v1-2026-10-18.py'
    assert hashlib.sha256(builder.read_bytes()).hexdigest() == 'e9353d70679a000b8956f23aa43dede3b59c240044b85ce79d9585b99db1f58b'
    draft = Path('/tmp/capacity-package-metadata-text-independent-preparation-20261018-v2')
    draft.mkdir(mode=0o700, exist_ok=False)
    for name in ('verify-native-package-text-census-v1-2026-10-18.py', 'capacity-native-package-text-transport-v1-2026-10-18.py'):
        with (draft / name).open('xb') as stream:
            stream.write((SOURCES / name).read_bytes())
    control = runpy.run_path(str(builder))
    control['independent'].__globals__['SOURCES'] = draft
    control['independent'](candidate_sha)
    text = (draft / 'verify-package-metadata-text-census-v1-2026-10-18.py').read_text()
    text = text.replace('capacity-package-metadata-text-census-20261018-v1', 'capacity-package-metadata-text-census-20261018-v2')
    text = text.replace('capacity-package-metadata-text-independent-20261018-v1', 'capacity-package-metadata-text-independent-20261018-v2')
    text = once(text, "'stopped-n2-package-metadata-text-census/1'", "'stopped-n2-package-metadata-text-census/2'")
    text = once(text, "    names = {'candidate.json', 'prerequisites.json', 'prior-head-proof.json'}",
        "    names = {'candidate.json', 'prerequisites.json', 'prior-head-proof.json', 'baseline-inspect.json', 'prior-failure-diagnostic.json'}")
    text = once(text, 'len(names) == 51', 'len(names) == 53')
    text = once(text, "'full_readback_files': 51", "'full_readback_files': 53")
    text = once(text, "BASELINE = 'd5265be87b979e83e396e18d1d9d4571cc6e1db5aa09239200004a2809bd90d2'", """BASELINE = 'd5265be87b979e83e396e18d1d9d4571cc6e1db5aa09239200004a2809bd90d2'
BASELINE_INSPECT = Path('/home/animallya96/scratch/capacity-package-metadata-head-20261018-v1/inspect-before.stdout')
DIAGNOSTIC = Path('/home/animallya96/scratch/capacity-package-metadata-text-inspect-diagnostic-20261018-v1/proof.json')
DIAGNOSTIC_SHA = '7ec16ed395d9b1d75f542a7001e43aede48462accb066e9ae3005561a91cd85f'""")
    marker = '# Check copied source bytes, full terminal receipts and a separately observed stopped inspect.'
    text = once(text, marker, '''# Independently compare complete inspection fields and full mount records, retaining list order observations.
def inspection(raw, baseline_raw):
    records, originals = json.loads(raw), json.loads(baseline_raw)
    assert len(records) == len(originals) == 1 and digest(baseline_raw) == BASELINE
    item, baseline = records[0], originals[0]
    assert set(item) == set(baseline)
    for key in baseline:
        if key != 'Mounts':
            assert item[key] == baseline[key]
    current, original = item['Mounts'], baseline['Mounts']
    destinations = [mount['Destination'] for mount in current]
    original_destinations = [mount['Destination'] for mount in original]
    assert len(destinations) == len(set(destinations)) == len(original_destinations) == len(set(original_destinations)) == 2
    assert set(destinations) == set(original_destinations)
    assert all(next(mount for mount in current if mount['Destination'] == destination)
        == next(mount for mount in original if mount['Destination'] == destination) for destination in destinations)
    return {'sha256': digest(raw), 'bytes': len(raw), 'raw_bytes_equal': raw == baseline_raw,
        'full_decoded_equal': item == baseline, 'raw_Mounts_list_order_equal': current == original,
        'all_nonMounts_and_complete_uniqueDestination_mount_records_equal': True}


''' + marker)
    text = once(text, "    assert hashlib.sha256(bodies['inspect-before.stdout']).hexdigest() == 'd5265be87b979e83e396e18d1d9d4571cc6e1db5aa09239200004a2809bd90d2'",
        """    baseline_raw, baseline_row = read(BASELINE_INSPECT)
    diagnostic_raw, diagnostic_row = read(DIAGNOSTIC)
    assert digest(baseline_raw) == BASELINE and len(baseline_raw) == 9755
    assert digest(diagnostic_raw) == DIAGNOSTIC_SHA and len(diagnostic_raw) == 4767
    assert bodies['baseline-inspect.json'] == baseline_raw and bodies['prior-failure-diagnostic.json'] == diagnostic_raw
    binding = candidate['inspection_binding']
    assert candidate['full_container_inspect_bookends_equal'] is None
    assert binding['baseline'] == {'file': 'baseline-inspect.json', 'bytes': len(baseline_raw), 'sha256': BASELINE}
    assert binding['diagnostic'] == {'file': 'prior-failure-diagnostic.json', 'bytes': len(diagnostic_raw), 'sha256': DIAGNOSTIC_SHA}
    assert binding['baseline_physical'] == baseline_row and binding['diagnostic_physical'] == diagnostic_row
    assert binding['before'] == inspection(bodies['inspect-before.stdout'], baseline_raw)
    assert binding['after'] == inspection(bodies['inspect-after.stdout'], baseline_raw)
    assert binding['raw_before_after_equal'] == (bodies['inspect-before.stdout'] == bodies['inspect-after.stdout'])
    assert binding['full_nonMounts_and_uniqueDestination_mount_bookends_equal'] is True
    diagnostic = json.loads(diagnostic_raw)
    assert diagnostic['all_nonMounts_fields_equal'] is True and diagnostic['complete_uniqueDestination_mount_records_equal'] is True
    assert diagnostic['raw_Mounts_list_order_equal'] is False""")
    text = once(text, "    assert before == json.loads(bodies['inspect-after.stdout']) and len(before) == 1", '    assert len(before) == 1')
    text = once(text, '    assert json.loads(fresh) == before and digest(fresh) == BASELINE',
        '    fresh_binding = inspection(fresh, baseline_raw)')
    text = once(text, '    assert read(PRIOR) == (prior_raw, prior_row)',
        '    assert read(PRIOR) == (prior_raw, prior_row)\n    assert read(BASELINE_INSPECT) == (baseline_raw, baseline_row)\n    assert read(DIAGNOSTIC) == (diagnostic_raw, diagnostic_row)')
    text = once(text, "'stopped-n2-package-metadata-text-census-independent/1'", "'stopped-n2-package-metadata-text-census-independent/2'")
    text = once(text, "        'prior_head_proof': prior_row}",
        "        'prior_head_proof': prior_row, 'inspection_binding': binding, 'fresh_inspection_binding': fresh_binding}")
    ast.parse(text)
    name = 'verify-package-metadata-text-census-v2-2026-10-18.py'
    with (SOURCES / name).open('xb') as stream:
        stream.write(text.encode())
    sha, size = hashlib.sha256(text.encode()).hexdigest(), len(text.encode())
    transport = (draft / 'package-metadata-text-independent-transport-v1-2026-10-18.py').read_text()
    draft_helper = (draft / 'verify-package-metadata-text-census-v1-2026-10-18.py').read_bytes()
    changes = {'verify-package-metadata-text-census-v1-2026-10-18.py': name,
        hashlib.sha256(draft_helper).hexdigest(): sha, str(len(draft_helper)): str(size),
        'capacity-package-metadata-text-independent-transport-20261018-v1': 'capacity-package-metadata-text-independent-transport-20261018-v2',
        'capacity-package-metadata-text-independent-tools-20261018-v1': 'capacity-package-metadata-text-independent-tools-20261018-v2'}
    for old, new in changes.items():
        assert old in transport
        transport = transport.replace(old, new)
    ast.parse(transport)
    output = SOURCES / 'package-metadata-text-independent-transport-v2-2026-10-18.py'
    with output.open('xb') as stream:
        stream.write(transport.encode())
    print(sha, size, hashlib.sha256(output.read_bytes()).hexdigest(), output.stat().st_size)


if __name__ == '__main__':
    assert len(sys.argv) == 2
    main(sys.argv[1])
