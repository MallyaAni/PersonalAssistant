"""Finite local owner for one new synthetic-only ELF decoder check root."""
import hashlib
import json
import os
from pathlib import Path
import resource
import signal
import subprocess
import sys

ROOT = Path('/tmp/callback-elf-synthetic-20261018-v1')
NAMES = ('parse-callback-elf-data-v1-2026-10-18.py',
    'fold-callback-elf-data-v1-2026-10-18.py', 'check-callback-elf-data-v1-2026-10-18.py')
PINS = {
    NAMES[0]: 'e5c8040315f3b471a4d35d2c90a82778a78954659d4b66e494d5b18abdf9edaf',
    NAMES[1]: 'f302196006bc47e3dd7c1a31aa9477d5119e6c18ac0cad015aa5efb302a34dc1',
    NAMES[2]: 'e4b2ace819e5a09f26bad354b69f9faa5d474601fd78f69af417a00b514fcb22',
}
WATCHED = (signal.SIGINT, signal.SIGHUP, signal.SIGTERM, signal.SIGALRM)


# Convert ordinary parent termination signals into exceptions that enter owned-child cleanup.
def interrupted(signum, frame):
    raise KeyboardInterrupt('LOCAL_OWNER_SIGNAL_' + str(signum))


# Remove the parent's short registration mask in the sole child immediately before exec.
def child_unmask():
    signal.pthread_sigmask(signal.SIG_SETMASK, ())


# Write and sync a new bounded owned evidence file without replacing an existing path.
def retain(name, body):
    if len(body) > 262144:
        raise ValueError('LOCAL_CONTROL_FILE_BOUND')
    path = ROOT / name
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'wb') as output:
        output.write(body)
        output.flush()
        os.fsync(output.fileno())
    if path.read_bytes() != body:
        raise ValueError('LOCAL_RETAINED_READBACK')


# Freeze the three operational sources and run their synthetic checks once with finite ownership.
def main():
    if not __debug__:
        raise ValueError('OPTIMIZED_OWNER_REFUSED')
    resource.setrlimit(resource.RLIMIT_AS, (512 * 1024 * 1024, 512 * 1024 * 1024))
    resource.setrlimit(resource.RLIMIT_CPU, (20, 20))
    resource.setrlimit(resource.RLIMIT_FSIZE, (262144, 262144))
    for watched in WATCHED:
        signal.signal(watched, interrupted)
    ROOT.mkdir(mode=0o700)
    for name in NAMES:
        source = (Path(__file__).resolve().parent / name).read_bytes()
        if len(source) > 262144 or hashlib.sha256(source).hexdigest() != PINS.get(name):
            raise ValueError('LOCAL_REVIEWED_SOURCE_PIN')
        retain(name, source)
    command = [sys.executable, '-I', '-S', '-B', str(ROOT / NAMES[2])]
    retain('invocation.json', json.dumps({'command': command, 'timeout_seconds': 20,
        'source_sha256': PINS, 'scope': 'NEW_SYNTHETIC_DATA_ONLY',
        'actual_callback_or_package_open': False}, sort_keys=True).encode())
    receipt = {'schema': 'local-synthetic-elf-owner/1', 'command': command,
        'exit_code': None, 'timeout': False, 'owned_child_reaped': False,
        'exception': None, 'cleanup_failure': None}
    child = None
    signal.alarm(25)
    with open(ROOT / 'stdout.json', 'xb') as stdout, open(ROOT / 'stderr.bin', 'xb') as stderr:
        try:
            previous = signal.pthread_sigmask(signal.SIG_BLOCK, WATCHED)
            try:
                child = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=stdout,
                    stderr=stderr, preexec_fn=child_unmask)
                receipt['pid'] = child.pid
            finally:
                signal.pthread_sigmask(signal.SIG_SETMASK, previous)
            receipt['exit_code'] = child.wait(timeout=20)
            receipt['owned_child_reaped'] = True
        except subprocess.TimeoutExpired:
            receipt['timeout'] = True
        except BaseException as error:
            receipt['exception'] = type(error).__name__
        finally:
            previous = signal.pthread_sigmask(signal.SIG_BLOCK, WATCHED)
            try:
                if child is not None:
                    try:
                        if child.poll() is None:
                            child.terminate()
                            try:
                                child.wait(timeout=1)
                            except subprocess.TimeoutExpired:
                                child.kill()
                                child.wait(timeout=1)
                        receipt['exit_code'] = child.returncode
                        receipt['owned_child_reaped'] = True
                    except BaseException as error:
                        receipt['cleanup_failure'] = type(error).__name__
                stdout.flush()
                stderr.flush()
                os.fsync(stdout.fileno())
                os.fsync(stderr.fileno())
                retain('exit.json', json.dumps(receipt, sort_keys=True).encode())
                for directory in (ROOT, ROOT.resolve().parent):
                    fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
                    try:
                        os.fsync(fd)
                    finally:
                        os.close(fd)
            finally:
                signal.alarm(0)
                signal.pthread_sigmask(signal.SIG_SETMASK, previous)
    if receipt['exit_code'] != 0 or receipt['timeout'] or receipt['exception'] or receipt['cleanup_failure'] \
            or not receipt['owned_child_reaped'] or (ROOT / 'stderr.bin').stat().st_size:
        raise ValueError('SYNTHETIC_CONTROL_FAILED_PRESERVED')
    print(json.dumps({'root': str(ROOT), 'receipt': receipt,
        'stdout_sha256': hashlib.sha256((ROOT / 'stdout.json').read_bytes()).hexdigest()}, sort_keys=True))


if __name__ == '__main__':
    main()
