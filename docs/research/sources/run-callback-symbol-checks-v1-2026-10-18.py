"""One finite Linux owner and child for new SYNTHETIC63 symbol DATA checks only."""
import hashlib
import json
import os
from pathlib import Path
import resource
import signal
import stat
import subprocess
import sys
import time
import types

ROOT = Path('/home/animallya96/scratch/callback-symbol-synthetic-run-20261018-v1')
PINS = {
    'parse-callback-symbol-data-v1-2026-10-18.py': '6fe24522e57910ed2f9136762ea4f910f46fd6a6a91afe4f55c80b5e8462bd11',
    'fold-callback-symbol-data-v1-2026-10-18.py': 'a526e85d63313fac8a4de11eb31dc34964ad9eaeed6d93a4a78d25cb5b469127',
    'check-callback-symbol-data-v1-2026-10-18.py': '847127b3a70b7522645e8901c881cb135ca2da5850400c9a282647096a9cd76d',
}
WATCHED = (signal.SIGINT, signal.SIGHUP, signal.SIGTERM, signal.SIGALRM)


# Keep physical source identity and nanosecond timestamps exact through JSON.
def physical(value):
    return {key: str(getattr(value, key)) for key in ('st_dev', 'st_ino', 'st_mode',
        'st_uid', 'st_nlink', 'st_size', 'st_blocks', 'st_mtime_ns', 'st_ctime_ns')}


# Authenticate bounded regular source bytes with two held reads and named physical bookends.
def read(path, expected=None):
    assert path.resolve(strict=True) == path
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        before = os.fstat(descriptor)
        assert stat.S_ISREG(before.st_mode) and before.st_uid == 1000 and before.st_nlink == 1
        assert 0 <= before.st_size <= 262144
        raw = os.read(descriptor, 262145)
        os.lseek(descriptor, 0, os.SEEK_SET)
        assert os.read(descriptor, 262145) == raw and len(raw) == before.st_size
        assert physical(before) == physical(os.fstat(descriptor)) == physical(path.stat(follow_symlinks=False))
        row = {'sha256': hashlib.sha256(raw).hexdigest(), 'bytes': len(raw), 'physical': physical(before)}
        if expected is not None:
            assert row == expected
        return raw, row
    finally:
        os.close(descriptor)


# Escape fixture Exception retention so hard deadlines and ordinary termination reach owner cleanup.
def interrupted(signum, frame):
    raise KeyboardInterrupt('SYMBOL_SYNTHETIC_SIGNAL_' + str(signum))


# Remove the short parent registration signal mask immediately before the sole child exec.
def unmask():
    signal.pthread_sigmask(signal.SIG_SETMASK, ())


# Persist one bounded exclusive result with complete readback on the owned run root.
def retain(name, body):
    assert Path(name).name == name and len(body) <= 262144
    with (ROOT / name).open('xb') as stream:
        stream.write(body)
        stream.flush()
        os.fsync(stream.fileno())
    assert read(ROOT / name)[0] == body


# Execute only three authenticated operational modules and all63 new synthetic fixtures in one child.
def child():
    assert __debug__ and sys.platform == 'linux' and os.getuid() == 1000
    resource.setrlimit(resource.RLIMIT_AS, (536870912, 536870912))
    resource.setrlimit(resource.RLIMIT_CPU, (10, 10))
    resource.setrlimit(resource.RLIMIT_FSIZE, (262144, 262144))
    for watched in WATCHED:
        signal.signal(watched, interrupted)
    signal.alarm(15)
    started = time.monotonic()
    directory = Path(__file__).parent
    own_raw, own_row = read(Path(__file__))
    modules, sources = [], {}
    for index, (name, digest) in enumerate(PINS.items()):
        raw, row = read(directory / name)
        assert row['sha256'] == digest
        sources[name] = row
        module = types.ModuleType('reviewed_symbol_DATA_control_' + str(index))
        exec(compile(raw, str(directory / name), 'exec', dont_inherit=True), module.__dict__)
        modules.append(module)
    result = modules[2].run(modules[0], modules[1])
    for name, row in sources.items():
        read(directory / name, row)
    read(Path(__file__), own_row)
    result.update({'source_inventory': sources, 'owner_source': own_row,
        'elapsed_seconds': time.monotonic() - started, 'Python': sys.version,
        'reported_Linux_ru_maxrss_KiB': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss})
    body = json.dumps(result, sort_keys=True, allow_nan=False).encode() + b'\n'
    assert len(body) <= 262144
    print(body.decode(), end='', flush=True)
    signal.alarm(0)
    raise SystemExit(0 if result['all_pass'] else 1)


# Own one child through finite wait and cleanup, retaining failure evidence without retries.
def main():
    assert __debug__ and sys.platform == 'linux' and os.getuid() == 1000
    os.umask(0o077)
    os.nice(10)
    resource.setrlimit(resource.RLIMIT_AS, (536870912, 536870912))
    resource.setrlimit(resource.RLIMIT_CPU, (20, 20))
    resource.setrlimit(resource.RLIMIT_FSIZE, (262144, 262144))
    for watched in WATCHED:
        signal.signal(watched, interrupted)
    signal.alarm(25)
    ROOT.mkdir(mode=0o700, exist_ok=False)
    directory = Path(__file__).parent
    inventory = {}
    for name, digest in PINS.items():
        body, row = read(directory / name)
        assert row['sha256'] == digest
        inventory[name] = row
        retain(name, body)
    own_name = Path(__file__).name
    own_body, own_row = read(Path(__file__))
    inventory[own_name] = own_row
    retain(own_name, own_body)
    command = [sys.executable, '-I', '-S', '-B', str(ROOT / own_name), '--child']
    retain('invocation.json', json.dumps({'command': command, 'wait_seconds': 20,
        'scope': 'NEW_SYNTHETIC63_DATA_ONLY', 'source_sha256': PINS,
        'actual_callback_or_package_open': False}, sort_keys=True).encode())
    receipt = {'schema': 'callback-symbol-synthetic-owner/1', 'command': command,
        'pid': None, 'exit_code': None, 'timeout': False, 'owned_child_reaped': False,
        'exception': None, 'cleanup_failure': None, 'owned_child_stop': None}
    process = None
    with (ROOT / 'stdout.json').open('xb') as stdout, (ROOT / 'stderr.bin').open('xb') as stderr:
        try:
            blocked = signal.pthread_sigmask(signal.SIG_BLOCK, WATCHED)
            try:
                process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=stdout,
                    stderr=stderr, preexec_fn=unmask, start_new_session=True)
                receipt['pid'] = str(process.pid)
            finally:
                signal.pthread_sigmask(signal.SIG_SETMASK, blocked)
            receipt['exit_code'] = process.wait(timeout=20)
            receipt['owned_child_reaped'] = True
        except subprocess.TimeoutExpired:
            receipt['timeout'] = True
        except BaseException as error:
            receipt['exception'] = type(error).__name__
        finally:
            blocked = signal.pthread_sigmask(signal.SIG_BLOCK, WATCHED)
            try:
                if process is not None:
                    try:
                        if process.poll() is None:
                            receipt['owned_child_stop'] = 'TERM'
                            try:
                                os.killpg(process.pid, signal.SIGTERM)
                            except ProcessLookupError:
                                pass
                            try:
                                process.wait(timeout=1)
                            except subprocess.TimeoutExpired:
                                receipt['owned_child_stop'] = 'KILL'
                                try:
                                    os.killpg(process.pid, signal.SIGKILL)
                                except ProcessLookupError:
                                    pass
                                process.wait(timeout=1)
                        receipt['exit_code'] = process.returncode
                        receipt['owned_child_reaped'] = True
                    except BaseException as error:
                        receipt['cleanup_failure'] = type(error).__name__
                for stream in (stdout, stderr):
                    stream.flush()
                    os.fsync(stream.fileno())
                receipt['source_bookend_failure'] = None
                try:
                    for name, row in inventory.items():
                        read(directory / name, row)
                except BaseException as error:
                    receipt['source_bookend_failure'] = type(error).__name__
                receipt['stage_source_inventory'] = inventory
                retain('exit.json', json.dumps(receipt, sort_keys=True).encode() + b'\n')
                for directory_to_sync in (ROOT, ROOT.parent):
                    descriptor = os.open(directory_to_sync, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
                    try:
                        os.fsync(descriptor)
                    finally:
                        os.close(descriptor)
            finally:
                signal.alarm(0)
                signal.pthread_sigmask(signal.SIG_SETMASK, blocked)
    assert receipt['exit_code'] == 0 and not receipt['timeout'] and receipt['owned_child_reaped']
    assert all(receipt[k] is None for k in ('exception', 'cleanup_failure', 'owned_child_stop', 'source_bookend_failure'))
    assert read(ROOT / 'stderr.bin')[0] == b''
    print(json.dumps({'run_root': str(ROOT), 'receipt': receipt}, sort_keys=True))


if __name__ == '__main__':
    if sys.argv[1:] == ['--child']:
        child()
    else:
        assert sys.argv[1:] == []
        main()
