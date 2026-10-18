"""Authenticate retained callback bytes and preserve complete symbol/version DATA, never load native code."""
import hashlib
import json
import os
from pathlib import Path
import resource
import signal
import stat
import sys
import types

PRIOR = Path('/home/animallya96/scratch/capacity-callback-elf-data-independent-20261018-v1/proof.json')
PRIOR_SHA = '20c33344ece0c69c550f23771dbea6d9ab8d1eb6c2344a6fac2366224d817889'
BINARY = Path('/home/animallya96/scratch/capacity-callback-binary-copy-20261018-v1/callback.bin')
PAGE = Path('/home/animallya96/scratch/capacity-callback-elf-data-analysis-20261018-v1/page-0001.json')
DECODER = 'parse-callback-symbol-data-v1-2026-10-18.py'
DECODER_SHA = '6fe24522e57910ed2f9136762ea4f910f46fd6a6a91afe4f55c80b5e8462bd11'
OUT = Path('/home/animallya96/scratch/capacity-callback-symbol-data-analysis-20261018-v1')
CAP = 262144
KINDS = ('selected_sections', 'symbols', 'versions', 'needs', 'gaps', 'associations')
DATA_USED = None
AUTH_USED = 0
READS = 0
WRITTEN = 0


# Keep nanosecond times, allocation and physical identity exact as decimal strings.
def physical(value):
    return {key: str(getattr(value, key)) for key in ('st_dev', 'st_ino', 'st_mode',
        'st_uid', 'st_nlink', 'st_size', 'st_blocks', 'st_mtime_ns', 'st_ctime_ns')}


# Charge a complete digest before hashing to the residual DATA ledger or separate finite authentication ledger.
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


# Bind two complete held reads to the original named regular file and its optional exact prior identity.
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


# Encode one complete finite canonical document without truncation or altered numeric content.
def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True,
        allow_nan=False).encode('ascii') + b'\n'


# Persist a complete bounded output and charge its digest plus full readback to the same residual DATA ledger.
def save(name, raw, bound):
    global WRITTEN
    assert Path(name).name == name and len(raw) <= bound <= CAP
    WRITTEN += len(raw)
    assert WRITTEN <= 16777216
    proof = {'file': name, 'bytes': len(raw), 'sha256': digest(raw, True)}
    with (OUT / name).open('xb') as output:
        output.write(raw)
        output.flush()
        os.fsync(output.fileno())
    retained, row = read(OUT / name, data=True)
    assert retained == raw and row['sha256'] == proof['sha256']
    return proof


# Escape the finite helper on deadline or ordinary termination without catching a decoder refusal.
def interrupted(signum, frame):
    raise KeyboardInterrupt('CALLBACK_SYMBOL_DATA_SIGNAL_' + str(signum))


# Decode only authenticated retained DATA and preserve every record and canonical binding in new bounded pages.
def main():
    global DATA_USED
    assert __debug__ and sys.platform == 'linux' and os.getuid() == 1000
    os.umask(0o077)
    os.nice(10)
    resource.setrlimit(resource.RLIMIT_AS, (536870912, 536870912))
    resource.setrlimit(resource.RLIMIT_CPU, (20, 20))
    resource.setrlimit(resource.RLIMIT_FSIZE, (CAP, CAP))
    for watched in (signal.SIGALRM, signal.SIGINT, signal.SIGHUP, signal.SIGTERM):
        signal.signal(watched, interrupted)
    signal.alarm(30)
    assert OUT.parent.resolve(strict=True) == OUT.parent and not os.path.lexists(OUT)
    inventory = {}
    prior_raw, inventory[PRIOR] = read(PRIOR, {'bytes': 6569, 'sha256': PRIOR_SHA})
    prior = json.loads(prior_raw)
    assert prior['schema'] == 'retained-callback-ELF-DATA-independent/1'
    assert prior['all_fields_records_raw_spans_order_coverage_equal'] is True
    binary_pin, page_pin = (prior['input_inventory'][str(path)] for path in (BINARY, PAGE))
    assert binary_pin['bytes'] == 216280 and binary_pin['sha256'] == '9edf4136653a328edcc88dc97f6d828440ad96550c436cbe087951845c89903b'
    assert page_pin['bytes'] == 15279 and page_pin['sha256'] == '43ce64015bf67ad315821caa994123c7134d55e4dabb89c7bea9414607a5daa3'
    binary, inventory[BINARY] = read(BINARY, binary_pin)
    page, inventory[PAGE] = read(PAGE, page_pin)
    decoder_path, own_path = Path(__file__).parent / DECODER, Path(__file__)
    decoder_raw, inventory[decoder_path] = read(decoder_path, {'bytes': 13496, 'sha256': DECODER_SHA})
    _, inventory[own_path] = read(own_path)
    module = types.ModuleType('reviewed_retained_symbol_DATA_primary')
    exec(compile(decoder_raw, str(decoder_path), 'exec', dont_inherit=True), module.__dict__)
    result = module.decode(binary, page)
    DATA_USED = result['hash_work_bytes_before_output_hashes']
    assert type(DATA_USED) is int and 0 < DATA_USED <= 16777216
    canonical = module.encoded(result)
    assert len(canonical) <= 16777216
    canonical_sha = digest(canonical, True)
    pages = module.pages(result)
    assert 0 < len(pages) <= 256 and sum(map(len, pages)) <= 16777216
    OUT.mkdir(mode=0o700, exist_ok=False)
    pointers = []
    flattened = {kind: [] for kind in KINDS}
    prior_kind = -1
    for index, body in enumerate(pages):
        value = json.loads(body)
        kind, rows = value['kind'], value['records']
        assert kind in KINDS and KINDS.index(kind) >= prior_kind
        prior_kind = KINDS.index(kind)
        assert body == encoded(value) and len(body) <= 65536 and 1 <= len(rows) <= 64
        assert value == {'schema': 'callback-symbol-record-page/1', 'binary_sha256': binary_pin['sha256'],
            'kind': kind, 'start': len(flattened[kind]), 'records': result[kind][len(flattened[kind]):len(flattened[kind]) + len(rows)]}
        pointer = save('page-%04d.json' % index, body, 65536)
        pointer.update({'kind': kind, 'start': value['start'], 'count': len(rows)})
        pointers.append(pointer)
        flattened[kind].extend(rows)
    assert flattened == {kind: result[kind] for kind in KINDS}
    for path, row in inventory.items():
        read(path, row)
    summary = {'schema': 'retained-callback-symbol-DATA-analysis/1',
        'status': 'ACTUAL_SYMBOL_DATA_REQUIRES_INDEPENDENT_COMPLETE_FOLD',
        'input_inventory': {str(path): row for path, row in inventory.items()},
        'base': {key: value for key, value in result.items() if key not in KINDS},
        'counts': {kind: len(result[kind]) for kind in KINDS}, 'pages': pointers,
        'complete_canonical_result_bytes': len(canonical), 'complete_canonical_result_sha256': canonical_sha,
        'DATA_hash_work_before_summary': DATA_USED, 'operational_auth_hash_work_bytes': AUTH_USED,
        'operational_auth_includes_binary_page_hashes_separate_from_decoder': True,
        'native_loading_or_runtime_model_RAM_admission': None, 'Python': sys.version,
        'reported_Linux_ru_maxrss_KiB': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss}
    saved = save('summary.json', encoded(summary), CAP)
    for directory in (OUT, OUT.parent):
        descriptor = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    signal.alarm(0)
    print(json.dumps({'summary': saved, 'counts': summary['counts'], 'pages': len(pages),
        'DATA_hash_work_final': DATA_USED, 'operational_auth_hash_work_final': AUTH_USED,
        'total_output_bytes': WRITTEN}, sort_keys=True))


if __name__ == '__main__':
    main()
