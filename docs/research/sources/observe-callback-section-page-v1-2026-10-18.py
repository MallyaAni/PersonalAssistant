"""Read one prior-authenticated section-record page as DATA, without binary parsing."""
import base64
import hashlib
import json
import os
from pathlib import Path
import resource
import signal
import stat
import sys

PRIOR = Path('/home/animallya96/scratch/capacity-callback-elf-data-independent-20261018-v1/proof.json')
PRIOR_SHA = '20c33344ece0c69c550f23771dbea6d9ab8d1eb6c2344a6fac2366224d817889'
PAGE = Path('/home/animallya96/scratch/capacity-callback-elf-data-analysis-20261018-v1/page-0001.json')
PAGE_SHA = '43ce64015bf67ad315821caa994123c7134d55e4dabb89c7bea9414607a5daa3'
CAP = 262144


# Keep every physical identity field exact through JSON and local transport.
def physical(value):
    return {key: str(getattr(value, key)) for key in ('st_dev', 'st_ino', 'st_mode',
        'st_uid', 'st_nlink', 'st_size', 'st_blocks', 'st_mtime_ns', 'st_ctime_ns')}


# Read one fixed regular file twice and compare held and named identity before returning it.
def read(path, expected=None):
    assert path.resolve(strict=True) == path
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        before = os.fstat(descriptor)
        assert stat.S_ISREG(before.st_mode) and before.st_uid == 1000 and before.st_nlink == 1
        assert 0 <= before.st_size <= CAP
        raw = os.read(descriptor, CAP + 1)
        os.lseek(descriptor, 0, os.SEEK_SET)
        assert os.read(descriptor, CAP + 1) == raw and len(raw) == before.st_size
        assert physical(before) == physical(os.fstat(descriptor)) == physical(path.stat(follow_symlinks=False))
        row = {'sha256': hashlib.sha256(raw).hexdigest(), 'bytes': len(raw), 'physical': physical(before)}
        if expected is not None:
            for key, value in expected.items():
                assert row[key] == value
        return raw, row
    finally:
        os.close(descriptor)


# Interrupt only this finite read-only observation when its wall allowance expires.
def alarm(signum, frame):
    raise TimeoutError('SECTION_PAGE_OBSERVATION_BOUND')


# Return the complete authenticated prior page and receipt without reading any native binary.
def main():
    assert __debug__ and os.getuid() == 1000 and sys.platform == 'linux'
    os.umask(0o077)
    os.nice(10)
    resource.setrlimit(resource.RLIMIT_AS, (536870912, 536870912))
    resource.setrlimit(resource.RLIMIT_CPU, (20, 20))
    resource.setrlimit(resource.RLIMIT_FSIZE, (CAP, CAP))
    for sig in (signal.SIGALRM, signal.SIGHUP, signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, alarm)
    signal.alarm(30)
    own = Path(__file__)
    own_raw, own_row = read(own)
    prior_raw, prior_row = read(PRIOR, {'sha256': PRIOR_SHA, 'bytes': 6569})
    prior = json.loads(prior_raw)
    assert prior['schema'] == 'retained-callback-ELF-DATA-independent/1'
    expected = prior['input_inventory'][str(PAGE)]
    assert expected['sha256'] == PAGE_SHA and expected['bytes'] == 15279
    raw, row = read(PAGE, expected)
    for path, pin in ((own, own_row), (PRIOR, prior_row), (PAGE, row)):
        read(path, pin)
    result = {'schema': 'callback-section-page-observation/1',
        'scope': 'EXACT_RETAINED_PAGE_DATA_ONLY_NO_BINARY_OR_PARSER_EXECUTION',
        'inputs': {str(PRIOR): prior_row, str(PAGE): row, str(own): own_row},
        'page_base64': base64.b64encode(raw).decode('ascii'),
        'native_execution_or_runtime_model_RAM_admission': None,
        'python': sys.version, 'reported_Linux_ru_maxrss_KiB': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss}
    body = json.dumps(result, sort_keys=True, allow_nan=False).encode('ascii') + b'\n'
    assert len(body) <= CAP
    output = own.parent / 'observation.json'
    with output.open('xb') as stream:
        stream.write(body)
        stream.flush()
        os.fsync(stream.fileno())
    assert read(output)[0] == body
    for directory in (own.parent, own.parent.parent):
        descriptor = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    signal.alarm(0)
    print(body.decode('ascii'), end='')


if __name__ == '__main__':
    main()
