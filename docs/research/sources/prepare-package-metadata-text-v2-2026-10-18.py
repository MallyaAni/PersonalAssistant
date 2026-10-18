"""Prepare a distinct content reader for the evidenced inspection list-order representation."""
import ast
import hashlib
from pathlib import Path

SOURCES = Path(__file__).resolve().parent


# Apply exactly one declared source change and refuse unexpected input drift.
def once(text, old, new):
    assert text.count(old) == 1, old[:100]
    return text.replace(old, new, 1)


# Generate new source and pinned transport without running the reader or changing old roots.
def main():
    raw = (SOURCES / 'capacity-package-metadata-text-census-v1-2026-10-18.py').read_bytes()
    assert hashlib.sha256(raw).hexdigest() == 'a9af8e55fb60b2b950aeada945b7e0ac354fe853a3efeeb6ba4809ba8c226a60'
    text = raw.decode().replace('capacity-package-metadata-text-census-20261018-v1', 'capacity-package-metadata-text-census-20261018-v2')
    text = once(text, "KNOWN = {}", """KNOWN = {}
BASELINE_INSPECT = Path('/home/animallya96/scratch/capacity-package-metadata-head-20261018-v1/inspect-before.stdout')
DIAGNOSTIC = Path('/home/animallya96/scratch/capacity-package-metadata-text-inspect-diagnostic-20261018-v1/proof.json')
DIAGNOSTIC_SHA = '7ec16ed395d9b1d75f542a7001e43aede48462accb066e9ae3005561a91cd85f'""")
    marker = '# Copy exactly six metadata files without importing packages or interpreting their contents.'
    replacement = '''# Compare every inspect field and complete unique mount records while retaining raw list order separately.
def inspection(raw, baseline_raw):
    item, baseline = inspect_source(raw), inspect_source(baseline_raw)
    assert digest(baseline_raw) == BASELINE
    assert {key: value for key, value in item.items() if key != 'Mounts'} == {key: value for key, value in baseline.items() if key != 'Mounts'}
    current_mounts, baseline_mounts = item['Mounts'], baseline['Mounts']
    assert len({mount['Destination'] for mount in current_mounts}) == len(current_mounts) == 2
    assert len({mount['Destination'] for mount in baseline_mounts}) == len(baseline_mounts) == 2
    assert {mount['Destination']: mount for mount in current_mounts} == {mount['Destination']: mount for mount in baseline_mounts}
    return {'sha256': digest(raw), 'bytes': len(raw), 'raw_bytes_equal': raw == baseline_raw,
        'full_decoded_equal': item == baseline, 'raw_Mounts_list_order_equal': current_mounts == baseline_mounts,
        'all_nonMounts_and_complete_uniqueDestination_mount_records_equal': True}


''' + marker
    text = once(text, marker, replacement)
    text = once(text, "        saved_prior = save('prior-head-proof.json', prior_raw)", """        saved_prior = save('prior-head-proof.json', prior_raw)
        baseline_raw, baseline_row = read(BASELINE_INSPECT)
        assert digest(baseline_raw) == BASELINE and len(baseline_raw) == 9755
        diagnostic_raw, diagnostic_row = read(DIAGNOSTIC)
        assert digest(diagnostic_raw) == DIAGNOSTIC_SHA and len(diagnostic_raw) == 4767
        diagnostic = json.loads(diagnostic_raw)
        assert diagnostic['all_nonMounts_fields_equal'] is True
        assert diagnostic['complete_uniqueDestination_mount_records_equal'] is True
        assert diagnostic['raw_Mounts_list_order_equal'] is False
        saved_baseline = save('baseline-inspect.json', baseline_raw)
        saved_diagnostic = save('prior-failure-diagnostic.json', diagnostic_raw)""")
    text = once(text, '        before = inspect_source(before_raw)\n        assert digest(before_raw) == BASELINE',
        '        before = inspection(before_raw, baseline_raw)')
    text = once(text, '        after = inspect_source(after_raw)\n        assert digest(after_raw) == BASELINE\n        assert read(PRIOR) == (prior_raw, prior_row)\n        assert before == after',
        '        after = inspection(after_raw, baseline_raw)\n        assert read(PRIOR) == (prior_raw, prior_row)\n        assert read(BASELINE_INSPECT) == (baseline_raw, baseline_row)\n        assert read(DIAGNOSTIC) == (diagnostic_raw, diagnostic_row)')
    text = once(text, "'stopped-n2-package-metadata-text-census/1'", "'stopped-n2-package-metadata-text-census/2'")
    text = once(text, "'full_container_inspect_bookends_equal': True,", """'full_container_inspect_bookends_equal': None,
            'inspection_binding': {'baseline': saved_baseline, 'diagnostic': saved_diagnostic,
                'baseline_physical': baseline_row, 'diagnostic_physical': diagnostic_row,
                'before': before, 'after': after,
                'raw_before_after_equal': before_raw == after_raw,
                'full_nonMounts_and_uniqueDestination_mount_bookends_equal': True},""")
    helper = SOURCES / 'capacity-package-metadata-text-census-v2-2026-10-18.py'
    ast.parse(text)
    with helper.open('xb') as stream:
        stream.write(text.encode())
    assert helper.read_bytes() == text.encode()
    sha, size = hashlib.sha256(helper.read_bytes()).hexdigest(), helper.stat().st_size
    raw_transport = (SOURCES / 'package-metadata-text-transport-v1-2026-10-18.py').read_bytes()
    assert hashlib.sha256(raw_transport).hexdigest() == '24c8a8f5e57fd0f40908b079ae49126f137218ef12f99387cf14f3eda491cbe5'
    transport = raw_transport.decode()
    changes = {'capacity-package-metadata-text-census-v1-2026-10-18.py': helper.name,
        'a9af8e55fb60b2b950aeada945b7e0ac354fe853a3efeeb6ba4809ba8c226a60': sha,
        '14943': str(size), 'capacity-package-metadata-text-transport-20261018-v1': 'capacity-package-metadata-text-transport-20261018-v2',
        'capacity-package-metadata-text-tools-20261018-v1': 'capacity-package-metadata-text-tools-20261018-v2'}
    for old, new in changes.items():
        assert old in transport
        transport = transport.replace(old, new)
    ast.parse(transport)
    output = SOURCES / 'package-metadata-text-transport-v2-2026-10-18.py'
    with output.open('xb') as stream:
        stream.write(transport.encode())
    print(sha, size, hashlib.sha256(output.read_bytes()).hexdigest(), output.stat().st_size)


if __name__ == '__main__':
    main()
