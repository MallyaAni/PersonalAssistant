"""Authenticate one retained binary and decode its ELF metadata as DATA only."""
import hashlib
import json
import os
from pathlib import Path
import resource
import signal
import stat
import sys
import types

SOURCE = Path('/home/animallya96/scratch/capacity-callback-binary-copy-20261018-v1/callback.bin')
PRIOR = Path('/home/animallya96/scratch/capacity-callback-binary-independent-20261018-v1/proof.json')
PRIOR_SHA = '779a1f86987f55065061ca81d6891a61072d06a2f1514ec5bb64bbeb74dd4d9e'
DECODER = 'parse-callback-elf-data-v1-2026-10-18.py'
DECODER_SHA = 'e5c8040315f3b471a4d35d2c90a82778a78954659d4b66e494d5b18abdf9edaf'
OUT = Path('/home/animallya96/scratch/capacity-callback-elf-data-analysis-20261018-v1')
CAP = 262144
KINDS = ('programs', 'sections', 'dynamic_slots', 'dynamic_string_declarations')
WRITTEN = 0


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


# Encode complete finite JSON using the exact canonical settings shared with the independent driver.
def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True,
        allow_nan=False).encode('ascii') + b'\n'


# Persist one complete bounded output while charging the finite total output budget.
def save(name, value, bound=CAP):
    global WRITTEN
    raw = encoded(value)
    assert Path(name).name == name and len(raw) <= bound
    WRITTEN += len(raw)
    assert WRITTEN <= 16777216
    with (OUT / name).open('xb') as stream:
        stream.write(raw); stream.flush(); os.fsync(stream.fileno())
    assert read(OUT / name)[0] == raw
    return {'file': name, 'sha256': hashlib.sha256(raw).hexdigest(), 'bytes': len(raw)}


# Stop this data-only helper within its finite CPU, memory, file and wall allowances.
def alarm(signum, frame):
    raise TimeoutError('CALLBACK_ELF_DATA_ANALYSIS_BOUND')


# Decode only the authenticated callback and preserve every resulting field in complete bounded pages.
def main():
    assert __debug__ and os.getuid() == 1000 and sys.platform == 'linux'
    os.umask(0o077); os.nice(10)
    resource.setrlimit(resource.RLIMIT_AS, (536870912, 536870912))
    resource.setrlimit(resource.RLIMIT_CPU, (20, 20))
    resource.setrlimit(resource.RLIMIT_FSIZE, (CAP, CAP))
    for sig in (signal.SIGALRM, signal.SIGHUP, signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, alarm)
    signal.alarm(30)
    prior_raw, prior_row = read(PRIOR, {'sha256': PRIOR_SHA, 'bytes': 11338})
    prior = json.loads(prior_raw)
    assert prior['schema'] == 'stopped-n2-callback-binary-independent/1'
    binary_pin = prior['source_inventory']['callback.bin']
    assert binary_pin['bytes'] == 216280 and binary_pin['sha256'] == '9edf4136653a328edcc88dc97f6d828440ad96550c436cbe087951845c89903b'
    binary, binary_row = read(SOURCE, binary_pin)
    decoder_path = Path(__file__).parent / DECODER
    decoder_raw, decoder_row = read(decoder_path, {'sha256': DECODER_SHA, 'bytes': 9013})
    own_path = Path(__file__)
    own_raw, own_row = read(own_path)
    module = types.ModuleType('reviewed_primary_ELF_DATA_control')
    exec(compile(decoder_raw, str(decoder_path), 'exec', dont_inherit=True), module.__dict__)
    result = module.parse(binary)
    complete = encoded(result)
    assert len(complete) <= 16777216
    complete_sha = hashlib.sha256(complete).hexdigest()
    assert OUT.parent.resolve(strict=True) == OUT.parent
    OUT.mkdir(mode=0o700, exist_ok=False)
    pointers = []
    for kind in KINDS:
        records = result[kind]
        start = 0
        while start < len(records):
            batch = []
            while start + len(batch) < len(records) and len(batch) < 64:
                candidate = batch + [records[start + len(batch)]]
                page = {'schema': 'callback-elf-record-page/1', 'binary_sha256': binary_row['sha256'],
                    'kind': kind, 'start': start, 'records': candidate}
                if len(encoded(page)) > 65536:
                    assert batch, 'CALLBACK_ELF_SINGLE_RECORD_PAGE_BOUND'
                    break
                batch = candidate
            assert batch and len(pointers) < 256
            name = 'page-%04d.json' % len(pointers)
            page = {'schema': 'callback-elf-record-page/1', 'binary_sha256': binary_row['sha256'],
                'kind': kind, 'start': start, 'records': batch}
            pointer = save(name, page, 65536)
            pointer.update({'kind': kind, 'start': start, 'count': len(batch)})
            pointers.append(pointer)
            start += len(batch)
    for path, expected in ((PRIOR, prior_row), (SOURCE, binary_row),
            (decoder_path, decoder_row), (own_path, own_row)):
        read(path, expected)
    summary = {'schema': 'retained-callback-ELF-DATA-analysis/1',
        'status': 'ACTUAL_ELF_DATA_REQUIRES_INDEPENDENT_FULL_FOLD',
        'prior': prior_row, 'binary': binary_row, 'decoder': decoder_row, 'driver': own_row,
        'base': {key: value for key, value in result.items() if key not in KINDS},
        'counts': {kind: len(result[kind]) for kind in KINDS}, 'pages': pointers,
        'complete_canonical_result_sha256': complete_sha, 'complete_canonical_result_bytes': len(complete),
        'native_execution_or_runtime_model_RAM_admission': None,
        'Python': sys.version, 'reported_Linux_ru_maxrss_KiB': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss}
    saved = save('summary.json', summary)
    for directory in (OUT, OUT.parent):
        fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    signal.alarm(0)
    print(json.dumps({'output': str(OUT), 'summary': saved, 'counts': summary['counts'],
        'base': summary['base'], 'pages': len(pointers), 'total_output_bytes': WRITTEN}, sort_keys=True))


if __name__ == '__main__':
    main()
