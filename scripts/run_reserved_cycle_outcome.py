"""Run one NEW reserved final/Nightly cohort; source references are explicitly separate."""
import hashlib
import base64
import gzip
import importlib
import json
import os
from pathlib import Path
import resource
import sys
import stat
import time
import unittest

OUT = Path('/out')
PINS = json.loads(Path('/audit/pins.json').read_bytes())
MAP = json.loads(Path('/fixture/native-source-map.json').read_bytes())


# Preserve exact nanosecond identity fields without a JSON floating-point projection.
def identity(path):
    value = path.stat()
    return {name: str(getattr(value, name)) for name in
            ('st_dev', 'st_ino', 'st_size', 'st_mtime_ns', 'st_ctime_ns')}


# Authenticate all staged sources before and after the actual tests.
def sources():
    result = {}
    for name, expected in PINS.items():
        path = Path(name)
        before = identity(path)
        assert int(before['st_size']) <= 262144
        body = path.read_bytes()
        assert hashlib.sha256(body).hexdigest() == expected
        assert identity(path) == before
        result[name] = {'sha256': expected, 'physical': before}
    return result


# Bind the actual imported native modules to the previously authenticated source map.
def native_sources():
    result = {}
    for name, module in list(sys.modules.items()):
        filename = getattr(module, '__file__', None)
        if filename and filename.startswith('/native/'):
            path = Path(filename)
            before = identity(path)
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            assert digest == MAP[str(path.relative_to('/native'))]
            assert identity(path) == before
            result[name] = {'sha256': digest, 'physical': before}
    return result


# Authenticate the two actual owned child cut/exit witnesses without replaying a child.
def child_receipts(module):
    paths = module.ACTUAL_KILL_FILES
    assert len(paths) <= 4
    result = []
    for pair in paths:
        assert type(pair) is tuple and len(pair) == 2
        records = []
        for name, expected in zip(pair, ('actual-child-cut.json', 'actual-child-exit.json')):
            path = Path(name)
            assert path.name == expected and path.resolve() == path and path.is_relative_to(OUT / 'cases')
            descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
            try:
                before = identity(path)
                assert stat.S_ISREG(os.fstat(descriptor).st_mode) and int(before['st_size']) <= 16384
                body = os.read(descriptor, 16385)
                os.lseek(descriptor, 0, os.SEEK_SET)
                assert os.read(descriptor, 16385) == body and len(body) == int(before['st_size'])
                assert identity(path) == before
                assert all(str(getattr(os.fstat(descriptor), key)) == value for key, value in before.items())
                records.append({'path': name, 'sha256': hashlib.sha256(body).hexdigest(),
                                'physical': before, 'value': json.loads(body)})
            finally:
                os.close(descriptor)
        cut, ended = records[0]['value'], records[1]['value']
        assert cut['pid'] == ended['pid'] and type(cut['pid']) is int
        assert cut['point'] == ended['point'] and cut['head'] == ended['head']
        assert ended['exitcode'] == -9 and ended['scope'] == 'ACTUAL_OWNED_SIGKILL_NOT_POWER_LOSS'
        result.append({'cut': records[0], 'exit': records[1]})
    assert len({row['cut']['value']['pid'] for row in result}) == len(result)
    for row in result:
        cut = row['cut']['value']
        assert hashlib.sha256(cut['broker_raw'].encode()).hexdigest() == cut['broker_sha256']
    return result


# Run the new tests once and retain outcomes, source bindings and actual writer guards.
def main():
    assert os.getuid() == os.getgid() == 1000
    os.nice(19)
    before = sources()
    from backend.agents.trading.desk import paper
    module = importlib.import_module('backend.tests.test_historical_reserved_cycle_outcome')
    from backend.market import historical_packet_spool
    from backend.agents.trading.desk import intraday_orders
    native_before = native_sources()
    bindings = dict(vars(paper))
    group = os.environ['RESERVED_OUTCOME_GROUP']
    assert group in ('A', 'B')
    names = sorted(name for name in vars(module.ReservedCycleOutcomeTests) if name.startswith('test_'))
    selected = names[:5] if group == 'A' else names[5:]
    suite = unittest.TestSuite(module.ReservedCycleOutcomeTests(name) for name in selected)
    assert len(names) == 10 and suite.countTestCases() == 5
    started = time.monotonic()
    result = unittest.TextTestRunner(verbosity=2, stream=sys.stdout).run(suite)
    children = child_receipts(module)
    if result.wasSuccessful():
        assert len(children) == (2 if group == 'A' else 4)
    assert children == child_receipts(module)
    assert before == sources() and native_before == native_sources()
    assert set(vars(paper)) == set(bindings)
    assert all(vars(paper)[key] is value for key, value in bindings.items())
    forbidden = [name for name in sys.modules if name.startswith((
        'sklearn', 'backend.cli', 'backend.market.live_model',
        'backend.market.learned_',
        'backend.market.historical_conditional_nightly', 'backend.market.historical_raw_nightly',
        'backend.market.historical_conditional_cycle', 'backend.market.historical_raw_cycle',
        'backend.market.historical_raw_cycle_final',
        'backend.tests.test_historical_paper_component_integration',
        'backend.tests.test_historical_raw_nightly_metadata',
        'backend.tests.test_historical_raw_nightly_lifecycle',
        'backend.cli.market_daily', 'backend.market.historical_conditional_settlement'))]
    assert forbidden == []
    physical_raw = json.dumps(module.PHYSICAL_OBSERVATIONS, sort_keys=True, separators=(',', ':')).encode()
    assert len(module.PHYSICAL_OBSERVATIONS) <= 5 and len(physical_raw) < 1024 * 1024
    if result.wasSuccessful():
        assert len(module.PHYSICAL_OBSERVATIONS) == 5
    physical_gzip = gzip.compress(physical_raw, mtime=0)
    assert len(physical_gzip) < 131072
    proof = {
        'status': 'VERIFIED_SYNTHETIC_RESERVED_CYCLE_OUTCOME_COHORT' if result.wasSuccessful() and not result.skipped else 'FAILED',
        'actual_owned_sigkill_children': children,
        'physical_inventories': {'encoding': 'gzip-base64-complete-json/1',
            'raw_bytes': len(physical_raw), 'raw_sha256': hashlib.sha256(physical_raw).hexdigest(),
            'gzip_bytes': len(physical_gzip), 'gzip_sha256': hashlib.sha256(physical_gzip).hexdigest(),
            'base64': base64.b64encode(physical_gzip).decode()},
        'cohort': group, 'selected': selected,
        'source_scope': 'NEW copied payload <524288B; separate TWO whole unchanged RO reference sources plus native tree; combined executed closure exceeds copied-payload cap; source-isolated globals remain synthetic',
        'tests': result.testsRun, 'failures': len(result.failures),
        'errors': len(result.errors), 'skips': len(result.skipped),
        'elapsed_seconds': time.monotonic() - started,
        'peak_kib': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        'source_before': before, 'source_after': sources(),
        'native_before': native_before, 'native_after': native_sources(),
        'native_writer_globals_unchanged': True,
        'forbidden_imports': forbidden,
        'scope': 'NEW actual private reserved Stage graph/native flush desired8/submitted5/filled5 final save/OUTCOME/reopen/original recovery/same-session Nightly; declared synthetic resolution proxies NOT native market Resolver; owned protocol-boundary SIGKILLs NOT powerloss/inside syscall/SQLite commit; no native sender/model/SQLite-journal/directory/latch/twohost/fullhorizon/RAM/genuine admission',
    }
    assert len(json.dumps(proof, sort_keys=True, indent=2, allow_nan=False).encode()) < 262144
    with (OUT / 'proof.json').open('x') as handle:
        json.dump(proof, handle, sort_keys=True, indent=2, allow_nan=False)
        handle.flush()
        os.fsync(handle.fileno())
    return 0 if proof['status'] == 'VERIFIED_SYNTHETIC_RESERVED_CYCLE_OUTCOME_COHORT' else 1


if __name__ == '__main__':
    raise SystemExit(main())
