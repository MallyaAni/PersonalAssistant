"""UNRUN: four fresh bounded SYNTHETIC context/calendar/unit children, no genuine route."""
import hashlib
import json
import os
import resource
import signal
import subprocess
import sys
from pathlib import Path

AUDIT = Path('/audit')
OUT = Path('/out')
CHILDREN = []
THREADS = ('OPENBLAS_NUM_THREADS', 'OMP_NUM_THREADS', 'MKL_NUM_THREADS',
           'NUMEXPR_NUM_THREADS', 'VECLIB_MAXIMUM_THREADS', 'BLIS_NUM_THREADS')
MODES = {'context': ('reader', 'context'), 'preservation': ('preservation',),
         'calendar': ('calendar',), 'units': ('binding_units', 'lifecycle_units')}


# Preserve one new bounded observation with exact bytes and durable local readback.
def save(path, value):
    raw = json.dumps(value, sort_keys=True, indent=2, allow_nan=False).encode() + b'\n'
    assert len(raw) <= 262144
    with path.open('xb') as output:
        output.write(raw)
        output.flush()
        os.fsync(output.fileno())
    assert path.read_bytes() == raw


# Authenticate the complete bounded audit inventory before importing any candidate payload.
def inventory():
    pins = json.loads((AUDIT / 'pins.json').read_bytes())
    assert 1 <= len(pins) <= 128
    for name, identity in pins.items():
        path = AUDIT / name
        assert path.resolve(strict=True) == path and not path.is_symlink()
        raw = path.read_bytes()
        assert len(raw) == identity['bytes'] <= 262144 and hashlib.sha256(raw).hexdigest() == identity['sha256']
    assert {str(p.relative_to(AUDIT)) for p in AUDIT.rglob('*') if p.is_file()} == set(pins) | {'pins.json'}
    return pins


# Return the exact reviewed order of all planned new observations without old suite dispatch.
def cases(mode):
    groups = json.loads((AUDIT / 'cases.json').read_bytes())
    assert {n: len(v) for n, v in groups.items()} == {'reader': 13, 'context': 20, 'preservation': 11, 'calendar': 5, 'binding_units': 10, 'lifecycle_units': 14}
    names = [n for group in groups.values() for n in group]
    assert len(names) == len(set(names)) == 73
    return [n for group in MODES[mode] for n in groups[group]]


# Run only the named new child group on real candidate origins and explicitly labelled synthetic references/units.
def child(mode, target):
    inventory()
    assert os.getuid() == 1000 and all(os.environ.get(n) == '1' for n in THREADS)
    assert not any(n == 'backend' or n.startswith(('backend.', 'numpy', 'sklearn')) for n in sys.modules)
    native = Path('/usr/local/lib/python3.12/site-packages')
    assert native.resolve(strict=True) == native
    sys.path.append(str(native))
    sys.path.insert(0, str(AUDIT))
    import fixtures
    import cases as context_cases
    import units
    env = fixtures.load()
    if mode == 'context':
        rows = context_cases.context_group(env, target)
    elif mode == 'preservation':
        rows = []
        context_cases.preservation(env, target, rows)
    elif mode == 'calendar':
        rows = units.calendars(env, target)
    elif mode == 'units':
        rows = units.bindings(env) + units.phases(env, target)
    else:
        raise AssertionError('UNREVIEWED_CHILD_MODE')
    assert [r['case'] for r in rows] == cases(mode)
    save(target / 'result.json', {'schema': 'capacity-context-synthetic-child/1', 'mode': mode,
        'cases': rows, 'module_origins': env.origins,
        'native': {'version': env.np.__version__, 'path': env.np.__file__, 'init_sha256': fixtures.sha(Path(env.np.__file__).read_bytes()),
                   'threads': {n: os.environ[n] for n in THREADS}},
        'reference': 'EXPLICIT_ISOLATED_SYNTHETIC_GLOBALS_NO_ORIGINAL_MODULE_IMPORT_EXEC',
        'lifecycle_constructor': 'UNRUN', 'genuine_acceptance': False, 'publication': 'CLOSED'})


# Bound each fresh child CPU and each individual file without changing model, parser or result caps.
def limits():
    resource.setrlimit(resource.RLIMIT_CPU, (15, 15))
    resource.setrlimit(resource.RLIMIT_FSIZE, (262144, 262144))


# Interrupt a real parent deadline so the registered owned children still get reaped.
def alarm(signum, frame):
    raise KeyboardInterrupt('CONTEXT_PARITY_PARENT_DEADLINE')


# Run four new children once and retain exact exits, full named outcomes and owned cleanup.
def diagnose():
    inventory()
    assert os.getuid() == 1000 and list(OUT.iterdir()) == []
    signal.signal(signal.SIGALRM, alarm)
    signal.setitimer(signal.ITIMER_REAL, 100)
    completed = []
    try:
        for mode in MODES:
            target = OUT / mode
            target.mkdir(mode=0o700)
            stdout, stderr = (target / 'stdout.log').open('xb'), (target / 'stderr.log').open('xb')
            process, stopped = None, None
            try:
                prior = signal.pthread_sigmask(signal.SIG_BLOCK, {signal.SIGALRM})
                try:
                    environment = {**os.environ, **{n: '1' for n in THREADS}}
                    process = subprocess.Popen([sys.executable, '-I', '-S', '-B', str(Path(__file__)), mode, str(target)],
                        stdin=subprocess.DEVNULL, stdout=stdout, stderr=stderr, preexec_fn=limits, env=environment)
                    CHILDREN.append(process)
                finally:
                    signal.pthread_sigmask(signal.SIG_SETMASK, prior)
                process.wait(timeout=20)
            finally:
                if process is not None and process.poll() is None:
                    stopped = 'TERM'
                    process.terminate()
                    try:
                        process.wait(timeout=1)
                    except subprocess.TimeoutExpired:
                        stopped = 'KILL'
                        process.kill()
                        process.wait(timeout=1)
                for output in (stdout, stderr):
                    output.flush()
                    os.fsync(output.fileno())
                    output.close()
                save(target / 'exit.json', {'pid': None if process is None else str(process.pid),
                    'exit': None if process is None else process.returncode, 'owned_stop': stopped})
            assert process.returncode == 0 and stopped is None
            assert (target / 'stdout.log').read_bytes() == (target / 'stderr.log').read_bytes() == b''
            result = json.loads((target / 'result.json').read_bytes())
            assert [r['case'] for r in result['cases']] == cases(mode) and result['genuine_acceptance'] is False
            completed.extend(result['cases'])
        assert len(completed) == 73 and len({r['case'] for r in completed}) == 73
        save(OUT / 'comparison.json', {'schema': 'capacity-context-synthetic-comparison/1',
            'status': 'SYNTHETIC73_REQUIRES_INDEPENDENT_REVIEW', 'children': 4, 'cases': 73,
            'genuine_acceptance': False, 'publication': 'CLOSED'})
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        for process in CHILDREN:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=1)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=1)


if __name__ == '__main__':
    if sys.argv[1:] == ['diagnose']:
        diagnose()
    elif len(sys.argv) == 3 and sys.argv[1] in MODES:
        child(sys.argv[1], Path(sys.argv[2]))
    else:
        raise SystemExit('SOURCE_ONLY_NO_CONTEXT_PARITY_INVOCATION')
