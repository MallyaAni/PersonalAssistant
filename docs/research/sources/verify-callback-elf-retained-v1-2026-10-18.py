"""Independently reconstruct the exact retained callback ELF DATA and every complete output record."""
import hashlib
import json
import os
from pathlib import Path
import resource
import signal
import stat
import sys
import types

ROOT = Path('/home/animallya96/scratch/capacity-callback-elf-data-analysis-20261018-v1')
SOURCE = Path('/home/animallya96/scratch/capacity-callback-binary-copy-20261018-v1/callback.bin')
PRIOR = Path('/home/animallya96/scratch/capacity-callback-binary-independent-20261018-v1/proof.json')
PRIOR_SHA = '779a1f86987f55065061ca81d6891a61072d06a2f1514ec5bb64bbeb74dd4d9e'
PRIMARY_TOOLS = Path('/home/animallya96/scratch/capacity-callback-elf-primary-tools-20261018-v1')
PRIMARY_DRIVER_SHA = 'dd28a751b8f8219239b014978406430b2a5a2cfa2b0a4625cded6bd8074f6cdf'
SUMMARY_SHA = 'd0c98e420b2fc5787d4eb0aa8331d340fe44ba2a1a09c1ad10c56538eeaa155f'
SUMMARY_BYTES = 3704
DECODER = 'fold-callback-elf-data-v1-2026-10-18.py'
DECODER_SHA = 'f302196006bc47e3dd7c1a31aa9477d5119e6c18ac0cad015aa5efb302a34dc1'
OUT = Path('/home/animallya96/scratch/capacity-callback-elf-data-independent-20261018-v1')
CAP = 262144
KINDS = ('programs', 'sections', 'dynamic_slots', 'dynamic_string_declarations')


# Preserve held and named physical identity fields as exact decimal strings.
def physical(value):
    return {key: str(getattr(value, key)) for key in ('st_dev', 'st_ino', 'st_mode',
        'st_uid', 'st_nlink', 'st_size', 'st_blocks', 'st_mtime_ns', 'st_ctime_ns')}


# Authenticate a bounded fixed file twice through a held descriptor and named physical bookends.
def read(path, expected=None):
    assert path.resolve(strict=True) == path
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        before = os.fstat(descriptor)
        assert stat.S_ISREG(before.st_mode) and before.st_uid == 1000 and before.st_nlink == 1
        assert 0 <= before.st_size <= CAP
        raw = os.read(descriptor, CAP + 1); os.lseek(descriptor, 0, os.SEEK_SET)
        assert os.read(descriptor, CAP + 1) == raw and len(raw) == before.st_size
        assert physical(before) == physical(os.fstat(descriptor)) == physical(path.stat(follow_symlinks=False))
        row = {'sha256': hashlib.sha256(raw).hexdigest(), 'bytes': len(raw), 'physical': physical(before)}
        if expected is not None:
            for key, value in expected.items():
                assert row[key] == value
        return raw, row
    finally:
        os.close(descriptor)


# Encode every independently reconstructed field with exactly the declared complete-document JSON settings.
def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True,
        allow_nan=False).encode('ascii') + b'\n'


# Interrupt the independent DATA fold without any package, Docker or native-loader operation.
def alarm(signum, frame):
    raise TimeoutError('CALLBACK_ELF_DATA_INDEPENDENT_BOUND')


# Check complete ordered coverage and every decoded field against a separate reconstruction of authenticated bytes.
def main():
    assert __debug__ and os.getuid() == 1000 and sys.platform == 'linux'
    assert len(SUMMARY_SHA) == len(PRIMARY_DRIVER_SHA) == 64 and 0 < SUMMARY_BYTES <= CAP
    os.umask(0o077); os.nice(10)
    resource.setrlimit(resource.RLIMIT_AS, (536870912, 536870912))
    resource.setrlimit(resource.RLIMIT_CPU, (20, 20))
    resource.setrlimit(resource.RLIMIT_FSIZE, (CAP, CAP))
    for sig in (signal.SIGALRM, signal.SIGHUP, signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, alarm)
    signal.alarm(30)
    observed = {}
    summary_raw, observed[ROOT / 'summary.json'] = read(ROOT / 'summary.json',
        {'sha256': SUMMARY_SHA, 'bytes': SUMMARY_BYTES})
    summary = json.loads(summary_raw)
    assert summary_raw == encoded(summary)
    assert set(summary) == {'schema', 'status', 'prior', 'binary', 'decoder', 'driver',
        'base', 'counts', 'pages', 'complete_canonical_result_sha256',
        'complete_canonical_result_bytes', 'native_execution_or_runtime_model_RAM_admission',
        'Python', 'reported_Linux_ru_maxrss_KiB'}
    assert summary['Python'] == sys.version
    assert type(summary['reported_Linux_ru_maxrss_KiB']) is int and summary['reported_Linux_ru_maxrss_KiB'] > 0
    prior_raw, observed[PRIOR] = read(PRIOR, {'sha256': PRIOR_SHA, 'bytes': 11338})
    prior = json.loads(prior_raw)
    assert prior['schema'] == 'stopped-n2-callback-binary-independent/1'
    binary, observed[SOURCE] = read(SOURCE, prior['source_inventory']['callback.bin'])
    assert observed[SOURCE]['bytes'] == 216280 and observed[SOURCE]['sha256'] == '9edf4136653a328edcc88dc97f6d828440ad96550c436cbe087951845c89903b'
    assert summary['schema'] == 'retained-callback-ELF-DATA-analysis/1'
    assert summary['status'] == 'ACTUAL_ELF_DATA_REQUIRES_INDEPENDENT_FULL_FOLD'
    assert summary['prior'] == observed[PRIOR] and summary['binary'] == observed[SOURCE]
    primary_driver = PRIMARY_TOOLS / 'analyze-callback-elf-retained-v1-2026-10-18.py'
    primary_decoder = PRIMARY_TOOLS / 'parse-callback-elf-data-v1-2026-10-18.py'
    _, observed[primary_driver] = read(primary_driver, {'sha256': PRIMARY_DRIVER_SHA})
    _, observed[primary_decoder] = read(primary_decoder,
        {'sha256': 'e5c8040315f3b471a4d35d2c90a82778a78954659d4b66e494d5b18abdf9edaf', 'bytes': 9013})
    assert summary['driver'] == observed[primary_driver] and summary['decoder'] == observed[primary_decoder]
    decoder_path = Path(__file__).parent / DECODER
    decoder_raw, observed[decoder_path] = read(decoder_path, {'sha256': DECODER_SHA, 'bytes': 9855})
    own_path = Path(__file__)
    _, observed[own_path] = read(own_path)
    module = types.ModuleType('reviewed_independent_ELF_DATA_control')
    exec(compile(decoder_raw, str(decoder_path), 'exec', dont_inherit=True), module.__dict__)
    expected = module.reconstruct(binary)
    expected_bytes = encoded(expected)
    assert len(expected_bytes) <= 16777216
    assert hashlib.sha256(expected_bytes).hexdigest() == summary['complete_canonical_result_sha256']
    assert len(expected_bytes) == summary['complete_canonical_result_bytes']
    assert summary['base'] == {key: value for key, value in expected.items() if key not in KINDS}
    assert summary['counts'] == {kind: len(expected[kind]) for kind in KINDS}
    assert summary['native_execution_or_runtime_model_RAM_admission'] is None
    pointers = summary['pages']
    assert 0 < len(pointers) <= 256
    names = [row['file'] for row in pointers]
    assert names == ['page-%04d.json' % i for i in range(len(pointers))]
    assert set(names) | {'summary.json'} == {path.name for path in ROOT.iterdir()}
    reconstructed = {key: value for key, value in summary['base'].items()}
    reconstructed.update({kind: [] for kind in KINDS})
    output_bytes = len(summary_raw)
    prior_kind = -1
    for pointer in pointers:
        kind = pointer['kind']
        assert kind in KINDS and KINDS.index(kind) >= prior_kind
        prior_kind = KINDS.index(kind)
        raw, row = read(ROOT / pointer['file'], {key: pointer[key] for key in ('sha256', 'bytes')})
        observed[ROOT / pointer['file']] = row
        assert len(raw) <= 65536
        output_bytes += len(raw)
        assert output_bytes <= 16777216
        page = json.loads(raw)
        assert raw == encoded(page)
        start = len(reconstructed[kind])
        records = page['records']
        assert type(pointer['start']) is type(pointer['count']) is type(page['start']) is int
        assert 1 <= len(records) <= 64 and pointer['start'] == start and pointer['count'] == len(records)
        assert page == {'schema': 'callback-elf-record-page/1', 'binary_sha256': observed[SOURCE]['sha256'],
            'kind': kind, 'start': start, 'records': expected[kind][start:start + len(records)]}
        reconstructed[kind].extend(records)
    assert reconstructed == expected and encoded(reconstructed) == expected_bytes
    for path, row in observed.items():
        read(path, row)
    proof = {'schema': 'retained-callback-ELF-DATA-independent/1',
        'status': 'VERIFIED_EXACT_RETAINED_ELF_DATA_ONLY_NOT_NATIVE_RUNTIME',
        'input_inventory': {str(path): row for path, row in observed.items()},
        'counts': summary['counts'], 'base': summary['base'],
        'dynamic_string_declarations': expected['dynamic_string_declarations'],
        'complete_canonical_result_sha256': summary['complete_canonical_result_sha256'],
        'complete_canonical_result_bytes': len(expected_bytes), 'page_count': len(pointers),
        'all_fields_records_raw_spans_order_coverage_equal': True,
        'output_bytes_including_summary': output_bytes,
        'native_loading_or_runtime_model_RAM_admission': None, 'Python': sys.version,
        'reported_Linux_ru_maxrss_KiB': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss}
    raw = encoded(proof)
    assert len(raw) <= CAP and OUT.parent.resolve(strict=True) == OUT.parent
    OUT.mkdir(mode=0o700, exist_ok=False)
    with (OUT / 'proof.json').open('xb') as stream:
        stream.write(raw); stream.flush(); os.fsync(stream.fileno())
    assert read(OUT / 'proof.json')[0] == raw
    for directory in (OUT, OUT.parent):
        fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    signal.alarm(0)
    print(raw.decode('ascii'), end='')


if __name__ == '__main__':
    main()
