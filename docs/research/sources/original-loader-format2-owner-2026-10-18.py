"""SOURCE ONLY: one bounded tiny diagnostic through the previously pinned Owner.

Default invocation refuses. External source staging, actual host evidence and a
fresh scoped admission are prerequisites; this file creates none of those.
"""

import hashlib
import json
import os
import signal
import socket
import sys
import time
import types
from pathlib import Path

SOURCE = Path('/home/animallya96/scratch/n2-format2-hypothesis-source-20261018-v1')
RUN = Path('/home/animallya96/scratch/n2-format2-hypothesis-20261018-v1')
IMAGE = 'sha256:e0a54c1f3b293c241ea0eae767d8ba017d0e1a05679965935b336910faa63237'
CONTROLLER = '2e505205cc8a3793d7b3313a5b5c3b670b00134575982d26c725787b6530df5a'
FILES = {'audit/bootstrap.py', 'audit/harness-source.txt', 'owner/controller.py'}


# Keep immutable source physical counters exact without comparing mutable atime.
def physical(value):
    return {key: str(getattr(value, key)) for key in ('st_dev', 'st_ino', 'st_mode', 'st_uid', 'st_nlink', 'st_size', 'st_blocks', 'st_mtime_ns', 'st_ctime_ns')}


# Read one bounded held file with no-follow source and path identity bookends.
def read(path):
    assert path.resolve(strict=True) == path and path.stat().st_uid == 1000
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        before = os.fstat(descriptor)
        assert 0 <= before.st_size <= 262144
        chunks, size = [], 0
        while block := os.read(descriptor, 65536):
            size += len(block)
            assert size <= 262144
            chunks.append(block)
        assert physical(before) == physical(os.fstat(descriptor)) == physical(path.stat(follow_symlinks=False))
    finally:
        os.close(descriptor)
    raw = b''.join(chunks)
    return raw, {'sha256': hashlib.sha256(raw).hexdigest(), 'bytes': len(raw), 'physical': physical(before)}


# Authenticate every fixed staged diagnostic input without importing its backend names.
def sources(book):
    assert set(book) == {'schema', 'files'} and book['schema'] == 'tiny-format2-source/1' and set(book['files']) == FILES
    result = {}
    for name in sorted(FILES):
        raw, identity = read(SOURCE / name)
        assert book['files'][name] == {'sha256': identity['sha256'], 'bytes': len(raw)}
        result[name] = identity
    assert result['owner/controller.py']['sha256'] == CONTROLLER
    assert result['audit/harness-source.txt']['sha256'] == '737d4236345ebfbc90a0ecf33e3e9ce733e5f06afb2e53c3125e465e9b1a2eea'
    assert {path.name for path in (SOURCE / 'audit').iterdir()} == {'bootstrap.py', 'harness-source.txt'}
    return result


# Require one externally reviewed fresh synthetic-only admission before any create.
def execute(admission_sha, self_sha, book_sha):
    assert read(Path(__file__))[1]['sha256'] == self_sha
    assert os.getuid() == 1000 and socket.gethostname() == 'animallya-spark1' and not os.path.lexists(RUN)
    book_raw, book_identity = read(SOURCE / 'source-book.json')
    assert book_identity['sha256'] == book_sha
    book = json.loads(book_raw)
    before = sources(book)
    raw, identity = read(SOURCE / 'admission/admission.json')
    assert identity['sha256'] == admission_sha
    admission = json.loads(raw)
    assert set(admission) == {'schema', 'scope', 'observed_at_ns', 'host', 'uid', 'source_book_sha256', 'owner_sha256', 'run_root', 'image', 'host_evidence', 'genuine_execution_authorized'}
    assert admission['schema'] == 'tiny-format2-admission/1' and admission['scope'] == 'TINY_SYNTHETIC_FORMAT2_HYPOTHESIS_ONLY'
    assert admission['source_book_sha256'] == book_sha and admission['owner_sha256'] == self_sha
    assert admission['host'] == socket.gethostname() and admission['uid'] == 1000 and admission['run_root'] == str(RUN)
    assert admission['image'] == IMAGE and admission['genuine_execution_authorized'] is False
    assert 0 <= time.time_ns() - int(admission['observed_at_ns']) <= 120 * 10 ** 9
    assert len(admission['host_evidence']) == 2
    evidence = {}
    for item in admission['host_evidence']:
        path = Path(item['path'])
        assert path.parent == SOURCE / 'admission' and path.name in ('host-resources.json', 'runtime-image.json')
        body, observed = read(path)
        assert observed['sha256'] == item['sha256'] and path.name not in evidence
        evidence[path.name] = json.loads(body)
    host = evidence['host-resources.json']
    assert host['host'] == socket.gethostname() and host['uid'] == 1000 and host['observed_at_ns'] == admission['observed_at_ns']
    assert int(host['MemAvailable_bytes']) >= 5 * 1024 ** 3 and int(host['scratch_available_bytes']) >= 4 * 1024 ** 3 and int(host['scratch_inodes_available']) >= 8192
    assert host['run_target_lexists'] is False and host['reservation'] is False
    image = evidence['runtime-image.json']
    assert len(image) == 1 and image[0]['Id'] == IMAGE and image[0]['Os'] == 'linux' and image[0]['Architecture'] == 'arm64'
    controller_raw, identity = read(SOURCE / 'owner/controller.py')
    module = types.ModuleType('pinned_tiny_diagnostic_owner')
    exec(compile(controller_raw, str(SOURCE / 'owner/controller.py'), 'exec', dont_inherit=True), module.__dict__)
    signal.signal(signal.SIGALRM, module.alarm)
    for signum in (signal.SIGHUP, signal.SIGINT, signal.SIGTERM):
        signal.signal(signum, module.alarm)
    signal.setitimer(signal.ITIMER_REAL, 60)
    owner = None
    try:
        owner = module.Owner(RUN, SOURCE / 'audit', book_sha)
        module.save(RUN / 'source-before.json', module.encode(before))
        code, jobs, error = owner.command(['ps', '--filter', 'label=' + module.LABEL, '--format', '{{json .}}'])
        assert jobs == b'' and error == b''
        output = RUN / 'output'
        output.mkdir(mode=0o700)
        binds = [(str(SOURCE / 'audit'), '/audit', False), (str(output), '/out', True)]
        cid = owner.phase('prepare', binds, ['diagnose'], timeout=25)
        after = sources(book)
        assert before == after
        module.save(RUN / 'source-after.json', module.encode(after))
        comparison, observed = read(output / 'comparison.json')
        module.save(RUN / 'terminal.json', module.encode({'status': 'FORMAT2_TERMINAL_NOT_GUARD_ACCEPTANCE', 'cid': cid, 'comparison_sha256': observed['sha256'], 'source_book_sha256': book_sha, 'admission_sha256': admission_sha, 'genuine_or_guard_suite_acceptance': False}))
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        if owner is not None:
            owner.cleanup()


# Expose only the pinned scoped route; an ordinary invocation is inert.
def main(arguments):
    if len(arguments) != 4 or arguments[0] != '--admitted-format2-hypothesis':
        raise SystemExit('SOURCE_ONLY_NO_FORMAT2_ADMISSION')
    execute(arguments[1], arguments[2], arguments[3])


if __name__ == '__main__':
    main(sys.argv[1:])
