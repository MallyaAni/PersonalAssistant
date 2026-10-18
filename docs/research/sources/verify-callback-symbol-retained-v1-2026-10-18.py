"""Independently reconstruct every retained symbol/version DATA field without invoking the primary."""
import hashlib
import json
import os
from pathlib import Path
import resource
import signal
import stat
import sys
import types

ROOT = Path('/home/animallya96/scratch/capacity-callback-symbol-data-analysis-20261018-v1')
OUT = Path('/home/animallya96/scratch/capacity-callback-symbol-data-independent-20261018-v1')
PRIOR = Path('/home/animallya96/scratch/capacity-callback-elf-data-independent-20261018-v1/proof.json')
PRIOR_SHA = '20c33344ece0c69c550f23771dbea6d9ab8d1eb6c2344a6fac2366224d817889'
BINARY = Path('/home/animallya96/scratch/capacity-callback-binary-copy-20261018-v1/callback.bin')
PAGE = Path('/home/animallya96/scratch/capacity-callback-elf-data-analysis-20261018-v1/page-0001.json')
PRIMARY_TOOLS = Path('/home/animallya96/scratch/capacity-callback-symbol-primary-tools-20261018-v1')
PRIMARY_SHA = 'b7eadb0166ed9aa21749c5230f19ce466b2430ca95fca0cc6f61948bac5d65c4'
SUMMARY_SHA = '3e70063876485948154d9d4118140a0a94aa5695ef80be1b1bc8dc886cd1bb39'
SUMMARY_BYTES = 5712
DECODER = 'fold-callback-symbol-data-v1-2026-10-18.py'
DECODER_SHA = 'a526e85d63313fac8a4de11eb31dc34964ad9eaeed6d93a4a78d25cb5b469127'
CAP = 262144
KINDS = ('selected_sections', 'symbols', 'versions', 'needs', 'gaps', 'associations')
DATA_USED = None
AUTH_USED = 0
READS = 0


# Keep every physical field exact without converting nanosecond integers to floating point.
def physical(value):
    return {key: str(getattr(value, key)) for key in ('st_dev', 'st_ino', 'st_mode',
        'st_uid', 'st_nlink', 'st_size', 'st_blocks', 'st_mtime_ns', 'st_ctime_ns')}


# Charge every digest before hashing against its explicitly separate bounded accounting category.
def digest(raw, data=False):
    global DATA_USED, AUTH_USED
    if data:
        assert type(DATA_USED) is int
        DATA_USED += len(raw)
        assert DATA_USED <= 16777216, 'SYMBOL_DRIVER_DATA_HASH_WORK_BOUND'
    else:
        AUTH_USED += len(raw)
        assert AUTH_USED <= 4194304, 'SYMBOL_DRIVER_AUTH_HASH_WORK_BOUND'
    return hashlib.sha256(raw).hexdigest()


# Independently authenticate complete held and named file reads with exact original identities when supplied.
def read(path, expected=None, data=False):
    global READS
    READS += 1
    assert READS <= 1024 and path.resolve(strict=True) == path
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        before = os.fstat(descriptor)
        assert stat.S_ISREG(before.st_mode) and before.st_uid == 1000 and before.st_nlink == 1
        assert 0 <= before.st_size <= CAP
        raw = os.read(descriptor, CAP + 1)
        os.lseek(descriptor, 0, os.SEEK_SET)
        assert os.read(descriptor, CAP + 1) == raw and len(raw) == before.st_size
        assert physical(before) == physical(os.fstat(descriptor)) == physical(path.stat(follow_symlinks=False))
        row = {'bytes': len(raw), 'sha256': digest(raw, data), 'physical': physical(before)}
        if expected is not None:
            assert all(row[key] == value for key, value in expected.items())
        return raw, row
    finally:
        os.close(descriptor)


# Encode the entire independently reconstructed result under the original finite JSON rules.
def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True,
        allow_nan=False).encode('ascii') + b'\n'


# Stop this finite read-only fold on deadline or ordinary termination without swallowing a refusal.
def interrupted(signum, frame):
    raise KeyboardInterrupt('CALLBACK_SYMBOL_INDEPENDENT_SIGNAL_' + str(signum))


# Reconstruct all fields, greedy pages and canonical bytes from original authenticated inputs before acceptance.
def main():
    global DATA_USED
    assert __debug__ and sys.platform == 'linux' and os.getuid() == 1000
    assert all(len(value) == 64 and all(c in '0123456789abcdef' for c in value)
        for value in (PRIMARY_SHA, SUMMARY_SHA)) and 0 < SUMMARY_BYTES <= CAP
    os.umask(0o077)
    os.nice(10)
    resource.setrlimit(resource.RLIMIT_AS, (536870912, 536870912))
    resource.setrlimit(resource.RLIMIT_CPU, (20, 20))
    resource.setrlimit(resource.RLIMIT_FSIZE, (CAP, CAP))
    for watched in (signal.SIGALRM, signal.SIGINT, signal.SIGHUP, signal.SIGTERM):
        signal.signal(watched, interrupted)
    signal.alarm(30)
    assert OUT.parent.resolve(strict=True) == OUT.parent and not os.path.lexists(OUT)
    observed, categories = {}, {}
    prior_raw, observed[PRIOR] = read(PRIOR, {'bytes': 6569, 'sha256': PRIOR_SHA})
    prior = json.loads(prior_raw)
    assert prior['schema'] == 'retained-callback-ELF-DATA-independent/1' and prior['all_fields_records_raw_spans_order_coverage_equal'] is True
    binary_pin, page_pin = (prior['input_inventory'][str(path)] for path in (BINARY, PAGE))
    assert binary_pin['bytes'] == 216280 and binary_pin['sha256'] == '9edf4136653a328edcc88dc97f6d828440ad96550c436cbe087951845c89903b'
    assert page_pin['bytes'] == 15279 and page_pin['sha256'] == '43ce64015bf67ad315821caa994123c7134d55e4dabb89c7bea9414607a5daa3'
    binary, observed[BINARY] = read(BINARY, binary_pin)
    page_raw, observed[PAGE] = read(PAGE, page_pin)
    primary_driver = PRIMARY_TOOLS / 'analyze-callback-symbol-retained-v1-2026-10-18.py'
    primary_decoder = PRIMARY_TOOLS / 'parse-callback-symbol-data-v1-2026-10-18.py'
    _, observed[primary_driver] = read(primary_driver, {'sha256': PRIMARY_SHA})
    _, observed[primary_decoder] = read(primary_decoder,
        {'sha256': '6fe24522e57910ed2f9136762ea4f910f46fd6a6a91afe4f55c80b5e8462bd11', 'bytes': 13496})
    own_path, decoder_path = Path(__file__), Path(__file__).parent / DECODER
    _, observed[own_path] = read(own_path)
    decoder_raw, observed[decoder_path] = read(decoder_path, {'bytes': 14287, 'sha256': DECODER_SHA})
    categories.update({path: False for path in observed})
    module = types.ModuleType('reviewed_retained_symbol_DATA_independent')
    exec(compile(decoder_raw, str(decoder_path), 'exec', dont_inherit=True), module.__dict__)
    expected = module.fold(binary, page_raw)
    DATA_USED = expected['hash_work_bytes_before_output_hashes']
    assert type(DATA_USED) is int and 0 < DATA_USED <= 16777216
    canonical = module.canonical(expected)
    canonical_sha = digest(canonical, True)
    expected_pages = module.fold_pages(expected)
    summary_path = ROOT / 'summary.json'
    summary_raw, observed[summary_path] = read(summary_path, {'bytes': SUMMARY_BYTES, 'sha256': SUMMARY_SHA}, True)
    categories[summary_path] = True
    summary = json.loads(summary_raw)
    assert summary_raw == encoded(summary) and summary['schema'] == 'retained-callback-symbol-DATA-analysis/1'
    assert summary['status'] == 'ACTUAL_SYMBOL_DATA_REQUIRES_INDEPENDENT_COMPLETE_FOLD'
    assert set(summary) == {'schema', 'status', 'input_inventory', 'base', 'counts', 'pages',
        'complete_canonical_result_bytes', 'complete_canonical_result_sha256', 'DATA_hash_work_before_summary',
        'operational_auth_hash_work_bytes', 'operational_auth_includes_binary_page_hashes_separate_from_decoder',
        'native_loading_or_runtime_model_RAM_admission', 'Python', 'reported_Linux_ru_maxrss_KiB'}
    primary_inputs = (PRIOR, BINARY, PAGE, primary_driver, primary_decoder)
    assert summary['input_inventory'] == {str(path): observed[path] for path in primary_inputs}
    assert summary['base'] == {key: value for key, value in expected.items() if key not in KINDS}
    assert summary['counts'] == {kind: len(expected[kind]) for kind in KINDS}
    assert summary['complete_canonical_result_sha256'] == canonical_sha
    assert summary['complete_canonical_result_bytes'] == len(canonical) <= 16777216
    assert summary['operational_auth_hash_work_bytes'] == 2 * sum(observed[path]['bytes'] for path in primary_inputs)
    assert summary['operational_auth_includes_binary_page_hashes_separate_from_decoder'] is True
    assert summary['native_loading_or_runtime_model_RAM_admission'] is None and summary['Python'] == sys.version
    assert type(summary['reported_Linux_ru_maxrss_KiB']) is int and summary['reported_Linux_ru_maxrss_KiB'] > 0
    pointers = summary['pages']
    assert 0 < len(pointers) == len(expected_pages) <= 256
    names = ['page-%04d.json' % index for index in range(len(pointers))]
    assert [row['file'] for row in pointers] == names
    assert sorted(path.name for path in ROOT.iterdir()) == sorted(names + ['summary.json'])
    reconstructed = dict(summary['base'], **{kind: [] for kind in KINDS})
    output_bytes = len(summary_raw)
    for index, (pointer, expected_body) in enumerate(zip(pointers, expected_pages, strict=True)):
        assert set(pointer) == {'file', 'bytes', 'sha256', 'kind', 'start', 'count'}
        path = ROOT / names[index]
        raw, observed[path] = read(path, {key: pointer[key] for key in ('bytes', 'sha256')}, True)
        categories[path] = True
        assert raw == expected_body and len(raw) <= 65536
        page = json.loads(raw)
        assert raw == encoded(page)
        kind, records = page['kind'], page['records']
        assert kind in KINDS and type(pointer['start']) is type(pointer['count']) is int
        assert pointer['kind'] == kind and pointer['start'] == page['start'] == len(reconstructed[kind])
        assert pointer['count'] == len(records) and 1 <= len(records) <= 64
        reconstructed[kind].extend(records)
        output_bytes += len(raw)
        assert output_bytes <= 16777216
    assert reconstructed == expected and encoded(reconstructed) == canonical
    primary_before_summary = expected['hash_work_bytes_before_output_hashes'] + len(canonical) + 2 * sum(map(len, expected_pages))
    assert summary['DATA_hash_work_before_summary'] == primary_before_summary
    assert primary_before_summary + 2 * len(summary_raw) <= 16777216
    for path, row in observed.items():
        read(path, row, categories[path])
    assert sorted(path.name for path in ROOT.iterdir()) == sorted(names + ['summary.json'])
    proof = {'schema': 'retained-callback-symbol-DATA-independent/1',
        'status': 'VERIFIED_COMPLETE_SYMBOL_VERSION_DATA_ONLY_NOT_NATIVE_RUNTIME',
        'input_inventory': {str(path): row for path, row in observed.items()},
        'counts': summary['counts'], 'base': summary['base'], 'needs': expected['needs'], 'gaps': expected['gaps'],
        'complete_canonical_result_sha256': canonical_sha, 'complete_canonical_result_bytes': len(canonical),
        'all_fields_raw_spans_names_order_multiplicity_pages_canonical_equal': True,
        'page_count': len(expected_pages), 'output_bytes_including_summary': output_bytes,
        'primary_DATA_hash_work_final': primary_before_summary + 2 * len(summary_raw),
        'independent_DATA_hash_work_before_proof': DATA_USED, 'operational_auth_hash_work_bytes': AUTH_USED,
        'operational_auth_includes_binary_page_hashes_separate_from_decoder': True,
        'native_loading_or_runtime_model_RAM_admission': None, 'Python': sys.version,
        'reported_Linux_ru_maxrss_KiB': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss}
    raw = encoded(proof)
    assert len(raw) <= CAP
    proof_sha = digest(raw, True)
    OUT.mkdir(mode=0o700, exist_ok=False)
    with (OUT / 'proof.json').open('xb') as output:
        output.write(raw)
        output.flush()
        os.fsync(output.fileno())
    assert read(OUT / 'proof.json', data=True)[0] == raw
    for directory in (OUT, OUT.parent):
        descriptor = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    signal.alarm(0)
    print(json.dumps({'proof_bytes': len(raw), 'proof_sha256': proof_sha, 'counts': proof['counts'],
        'DATA_hash_work_final': DATA_USED, 'operational_auth_hash_work_final': AUTH_USED}, sort_keys=True))


if __name__ == '__main__':
    main()
