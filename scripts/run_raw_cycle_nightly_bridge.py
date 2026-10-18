"""Run only the source-isolated committed raw Cycle to Nightly bridge integration over synthetic accounts."""
import hashlib
import importlib
import json
import os
from pathlib import Path
import resource
import sys
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


# Run the new tests once and retain outcomes, source bindings and actual writer guards.
def main():
    assert os.getuid() == os.getgid() == 1000
    os.nice(19)
    before = sources()
    from backend.agents.trading.desk import paper
    module = importlib.import_module('backend.tests.test_historical_raw_cycle_nightly')
    from backend.agents.trading.desk import intraday_orders
    native_before = native_sources()
    bindings = dict(vars(paper))
    suite = unittest.defaultTestLoader.loadTestsFromModule(module)
    assert suite.countTestCases() == 8
    started = time.monotonic()
    result = unittest.TextTestRunner(verbosity=2, stream=sys.stdout).run(suite)
    assert before == sources() and native_before == native_sources()
    assert set(vars(paper)) == set(bindings)
    assert all(vars(paper)[key] is value for key, value in bindings.items())
    forbidden = [name for name in sys.modules if name.startswith((
        'sklearn', 'backend.cli', 'backend.market.live_model',
        'backend.market.learned_',
        'backend.market.historical_conditional_nightly', 'backend.market.historical_raw_nightly',
        'backend.market.historical_conditional_cycle', 'backend.market.historical_raw_cycle',
        'backend.cli.market_daily', 'backend.market.historical_conditional_settlement'))]
    assert forbidden == []
    proof = {
        'status': 'VERIFIED_SOURCE_ISOLATED_COMMITTED_RAW_CYCLE_NIGHTLY' if result.wasSuccessful() and not result.skipped else 'FAILED',
        'tests': result.testsRun, 'failures': len(result.failures),
        'errors': len(result.errors), 'skips': len(result.skipped),
        'elapsed_seconds': time.monotonic() - started,
        'peak_kib': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        'source_before': before, 'source_after': sources(),
        'native_before': native_before, 'native_after': native_sources(),
        'native_writer_globals_unchanged': True,
        'forbidden_imports': forbidden,
        'scope': 'Exact new raw Cycle final reader and complete RawNightly private close/read/recovery CodeTypes, actual Store reserved decision/submission and OUTCOME head commitments, native ReplayBroker partial fills/paper saves/raw reconciliation/checkpoint; explicit SYNTHETIC Cycle producer/context parser, policy/trade/calendar/source-manifest globals; no complete Cycle producer/constructor/model/market_daily planning/native-operation adoption/genuine admission',
    }
    with (OUT / 'proof.json').open('x') as handle:
        json.dump(proof, handle, sort_keys=True, indent=2, allow_nan=False)
        handle.flush()
        os.fsync(handle.fileno())
    return 0 if proof['status'] == 'VERIFIED_SOURCE_ISOLATED_COMMITTED_RAW_CYCLE_NIGHTLY' else 1


if __name__ == '__main__':
    raise SystemExit(main())
