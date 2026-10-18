"""Independently verify retained HEAD observations without repeating path requests."""
import base64
import hashlib
import json
import os
from pathlib import Path
import resource
import selectors
import signal
import stat
import subprocess
import sys
import time
from urllib.parse import quote

ROOT = Path('/home/animallya96/scratch/capacity-native-path-head-20261018-v1')
REVIEW = Path('/home/animallya96/scratch/capacity-native-path-head-independent-20261018-v1')
CID = '803718a62e3cbd1f6070abab25a58e1fbc0ee5d04b5444f57c817d7e47b8bf57'
IMAGE = 'sha256:e0a54c1f3b293c241ea0eae767d8ba017d0e1a05679965935b336910faa63237'
BASELINE = 'd5265be87b979e83e396e18d1d9d4571cc6e1db5aa09239200004a2809bd90d2'
CAP = 262144
BASELINE_INSPECT = Path('/home/animallya96/scratch/capacity-package-metadata-head-20261018-v1/inspect-before.stdout')
DOCKER = ('docker', '--host', 'unix:///var/run/docker.sock')
SEAM_SHA = '15f8249875d0aef99b9f48d0e3eb9c1971cf85d23fefc09d27d9ed7538325128'
DECLARATIONS = [{'package': 'pyarrow', 'RECORD_source_sha256': 'c7c1a40dc1aa59406ecd791d6a7e03bf47d1aef5ce41b232e8ae02c0a994a6a5', 'record_index': 593, 'CSV_end_line': 594, 'relative_path': 'pyarrow/lib.cpython-312-aarch64-linux-gnu.so', 'lexical_absolute_path': '/usr/local/lib/python3.12/site-packages/pyarrow/lib.cpython-312-aarch64-linux-gnu.so', 'declared_hash': {'algorithm': 'sha256', 'digest_hex': '888582ab7169c6aaa2d5bfb02350697634800fa5d42d74231df160a1af8c917a'}, 'declared_size_decimal': '4107800', 'actual_path_file_hash_ELF_or_load_observed': False}, {'package': 'pyarrow', 'RECORD_source_sha256': 'c7c1a40dc1aa59406ecd791d6a7e03bf47d1aef5ce41b232e8ae02c0a994a6a5', 'record_index': 36, 'CSV_end_line': 37, 'relative_path': 'pyarrow/_compute.cpython-312-aarch64-linux-gnu.so', 'lexical_absolute_path': '/usr/local/lib/python3.12/site-packages/pyarrow/_compute.cpython-312-aarch64-linux-gnu.so', 'declared_hash': {'algorithm': 'sha256', 'digest_hex': 'c4d2164d6988ca68e97dc46603df00e97f3aec588de1a0d9ef4f7db96816e0ad'}, 'declared_size_decimal': '1307360', 'actual_path_file_hash_ELF_or_load_observed': False}, {'package': 'pyarrow', 'RECORD_source_sha256': 'c7c1a40dc1aa59406ecd791d6a7e03bf47d1aef5ce41b232e8ae02c0a994a6a5', 'record_index': 60, 'CSV_end_line': 61, 'relative_path': 'pyarrow/_fs.cpython-312-aarch64-linux-gnu.so', 'lexical_absolute_path': '/usr/local/lib/python3.12/site-packages/pyarrow/_fs.cpython-312-aarch64-linux-gnu.so', 'declared_hash': {'algorithm': 'sha256', 'digest_hex': '3a5d94385fc0a7eba0ab9b95966592f528a7557a1c1648b58fbbeabf70477779'}, 'declared_size_decimal': '537304', 'actual_path_file_hash_ELF_or_load_observed': False}, {'package': 'pyarrow', 'RECORD_source_sha256': 'c7c1a40dc1aa59406ecd791d6a7e03bf47d1aef5ce41b232e8ae02c0a994a6a5', 'record_index': 45, 'CSV_end_line': 46, 'relative_path': 'pyarrow/_dataset.cpython-312-aarch64-linux-gnu.so', 'lexical_absolute_path': '/usr/local/lib/python3.12/site-packages/pyarrow/_dataset.cpython-312-aarch64-linux-gnu.so', 'declared_hash': {'algorithm': 'sha256', 'digest_hex': 'c8780f8e30718537c6178b8fb448f7b978ee28140793fc9b8e013de2b842e769'}, 'declared_size_decimal': '1037800', 'actual_path_file_hash_ELF_or_load_observed': False}, {'package': 'pyarrow', 'RECORD_source_sha256': 'c7c1a40dc1aa59406ecd791d6a7e03bf47d1aef5ce41b232e8ae02c0a994a6a5', 'record_index': 50, 'CSV_end_line': 51, 'relative_path': 'pyarrow/_dataset_parquet.cpython-312-aarch64-linux-gnu.so', 'lexical_absolute_path': '/usr/local/lib/python3.12/site-packages/pyarrow/_dataset_parquet.cpython-312-aarch64-linux-gnu.so', 'declared_hash': {'algorithm': 'sha256', 'digest_hex': 'd34cf4e21af717d6eded08e43ee07c3e24a07b4bf1004258a3df0cf14402c9b3'}, 'declared_size_decimal': '401808', 'actual_path_file_hash_ELF_or_load_observed': False}, {'package': 'pyarrow', 'RECORD_source_sha256': 'c7c1a40dc1aa59406ecd791d6a7e03bf47d1aef5ce41b232e8ae02c0a994a6a5', 'record_index': 74, 'CSV_end_line': 75, 'relative_path': 'pyarrow/_parquet.cpython-312-aarch64-linux-gnu.so', 'lexical_absolute_path': '/usr/local/lib/python3.12/site-packages/pyarrow/_parquet.cpython-312-aarch64-linux-gnu.so', 'declared_hash': {'algorithm': 'sha256', 'digest_hex': 'c7ea494a2bf566e278bdd43233f4e2ea5e8279a5c8078b2615b414dcf49d5be7'}, 'declared_size_decimal': '705264', 'actual_path_file_hash_ELF_or_load_observed': False}, {'package': 'pyarrow', 'RECORD_source_sha256': 'c7c1a40dc1aa59406ecd791d6a7e03bf47d1aef5ce41b232e8ae02c0a994a6a5', 'record_index': 596, 'CSV_end_line': 597, 'relative_path': 'pyarrow/libarrow.so.2500', 'lexical_absolute_path': '/usr/local/lib/python3.12/site-packages/pyarrow/libarrow.so.2500', 'declared_hash': {'algorithm': 'sha256', 'digest_hex': '8a4877c1fb01a9bde90dff529bab77152bc968a1e07c0452897191c239f84076'}, 'declared_size_decimal': '48111992', 'actual_path_file_hash_ELF_or_load_observed': False}, {'package': 'pyarrow', 'RECORD_source_sha256': 'c7c1a40dc1aa59406ecd791d6a7e03bf47d1aef5ce41b232e8ae02c0a994a6a5', 'record_index': 598, 'CSV_end_line': 599, 'relative_path': 'pyarrow/libarrow_compute.so.2500', 'lexical_absolute_path': '/usr/local/lib/python3.12/site-packages/pyarrow/libarrow_compute.so.2500', 'declared_hash': {'algorithm': 'sha256', 'digest_hex': '34a0c34ee2f3f11b6b209f413b8f13b64c8360d64d5b7e742c7774c099684ddf'}, 'declared_size_decimal': '14905408', 'actual_path_file_hash_ELF_or_load_observed': False}, {'package': 'pyarrow', 'RECORD_source_sha256': 'c7c1a40dc1aa59406ecd791d6a7e03bf47d1aef5ce41b232e8ae02c0a994a6a5', 'record_index': 599, 'CSV_end_line': 600, 'relative_path': 'pyarrow/libarrow_dataset.so.2500', 'lexical_absolute_path': '/usr/local/lib/python3.12/site-packages/pyarrow/libarrow_dataset.so.2500', 'declared_hash': {'algorithm': 'sha256', 'digest_hex': '5c495174f6d8e58bea0a78a6b375e96e87bdeb25e3af0f00b36d93d9d079ad54'}, 'declared_size_decimal': '2268752', 'actual_path_file_hash_ELF_or_load_observed': False}, {'package': 'pyarrow', 'RECORD_source_sha256': 'c7c1a40dc1aa59406ecd791d6a7e03bf47d1aef5ce41b232e8ae02c0a994a6a5', 'record_index': 611, 'CSV_end_line': 612, 'relative_path': 'pyarrow/libparquet.so.2500', 'lexical_absolute_path': '/usr/local/lib/python3.12/site-packages/pyarrow/libparquet.so.2500', 'declared_hash': {'algorithm': 'sha256', 'digest_hex': 'ed1dd2bef16e399dab849d6f3f461f273b116379dfd786fefdde29322ec46db8'}, 'declared_size_decimal': '11764248', 'actual_path_file_hash_ELF_or_load_observed': False}, {'package': 'pyarrow', 'RECORD_source_sha256': 'c7c1a40dc1aa59406ecd791d6a7e03bf47d1aef5ce41b232e8ae02c0a994a6a5', 'record_index': 601, 'CSV_end_line': 602, 'relative_path': 'pyarrow/libarrow_python.so', 'lexical_absolute_path': '/usr/local/lib/python3.12/site-packages/pyarrow/libarrow_python.so', 'declared_hash': {'algorithm': 'sha256', 'digest_hex': 'e12090c0d2d4903a6003e763a051ca83255ba19101183ab48293f7afc4a7c85b'}, 'declared_size_decimal': '2185016', 'actual_path_file_hash_ELF_or_load_observed': False}, {'package': 'pyarrow', 'RECORD_source_sha256': 'c7c1a40dc1aa59406ecd791d6a7e03bf47d1aef5ce41b232e8ae02c0a994a6a5', 'record_index': 602, 'CSV_end_line': 603, 'relative_path': 'pyarrow/libarrow_python.so.2500', 'lexical_absolute_path': '/usr/local/lib/python3.12/site-packages/pyarrow/libarrow_python.so.2500', 'declared_hash': {'algorithm': 'sha256', 'digest_hex': 'e12090c0d2d4903a6003e763a051ca83255ba19101183ab48293f7afc4a7c85b'}, 'declared_size_decimal': '2185016', 'actual_path_file_hash_ELF_or_load_observed': False}, {'package': 'pyarrow', 'RECORD_source_sha256': 'c7c1a40dc1aa59406ecd791d6a7e03bf47d1aef5ce41b232e8ae02c0a994a6a5', 'record_index': 603, 'CSV_end_line': 604, 'relative_path': 'pyarrow/libarrow_python.so.2500.1.0', 'lexical_absolute_path': '/usr/local/lib/python3.12/site-packages/pyarrow/libarrow_python.so.2500.1.0', 'declared_hash': {'algorithm': 'sha256', 'digest_hex': 'e12090c0d2d4903a6003e763a051ca83255ba19101183ab48293f7afc4a7c85b'}, 'declared_size_decimal': '2185016', 'actual_path_file_hash_ELF_or_load_observed': False}, {'package': 'numpy', 'RECORD_source_sha256': 'a54bc643f7bb4873ccee79861127eb7992f9ec46951d37be73552a2efb3c177b', 'record_index': 98, 'CSV_end_line': 99, 'relative_path': 'numpy/_core/_multiarray_umath.cpython-312-aarch64-linux-gnu.so', 'lexical_absolute_path': '/usr/local/lib/python3.12/site-packages/numpy/_core/_multiarray_umath.cpython-312-aarch64-linux-gnu.so', 'declared_hash': {'algorithm': 'sha256', 'digest_hex': '73d0c6e928b027c9a3a99101dd0899492d91ccb2ba350dbb851e4b06c89039cb'}, 'declared_size_decimal': '6122041', 'actual_path_file_hash_ELF_or_load_observed': False}, {'package': 'numpy', 'RECORD_source_sha256': 'a54bc643f7bb4873ccee79861127eb7992f9ec46951d37be73552a2efb3c177b', 'record_index': 26, 'CSV_end_line': 27, 'relative_path': 'numpy.libs/libscipy_openblas64_-f552eb69.so', 'lexical_absolute_path': '/usr/local/lib/python3.12/site-packages/numpy.libs/libscipy_openblas64_-f552eb69.so', 'declared_hash': {'algorithm': 'sha256', 'digest_hex': 'e58b9ec0d373252b70f37d9dc891d7183a4f57f062db87f38e9a1bf7442d3037'}, 'declared_size_decimal': '27121113', 'actual_path_file_hash_ELF_or_load_observed': False}, {'package': 'numpy', 'RECORD_source_sha256': 'a54bc643f7bb4873ccee79861127eb7992f9ec46951d37be73552a2efb3c177b', 'record_index': 25, 'CSV_end_line': 26, 'relative_path': 'numpy.libs/libgfortran-e1b7dfc8-d8198c01.so.5.0.0', 'lexical_absolute_path': '/usr/local/lib/python3.12/site-packages/numpy.libs/libgfortran-e1b7dfc8-d8198c01.so.5.0.0', 'declared_hash': {'algorithm': 'sha256', 'digest_hex': '25899a29a06d3f2927021b4823d858558839fea0e7e759eedb8926fd0a339ea4'}, 'declared_size_decimal': '1605377', 'actual_path_file_hash_ELF_or_load_observed': False}, {'package': 'scipy', 'RECORD_source_sha256': 'b4b210e29143fee78ff3abd82e2d308554642129deacfcfec4e7e626c2d4fd68', 'record_index': 219, 'CSV_end_line': 220, 'relative_path': 'scipy/_lib/_ccallback_c.cpython-312-aarch64-linux-gnu.so', 'lexical_absolute_path': '/usr/local/lib/python3.12/site-packages/scipy/_lib/_ccallback_c.cpython-312-aarch64-linux-gnu.so', 'declared_hash': {'algorithm': 'sha256', 'digest_hex': '9edf4136653a328edcc88dc97f6d828440ad96550c436cbe087951845c89903b'}, 'declared_size_decimal': '216280', 'actual_path_file_hash_ELF_or_load_observed': False}, {'package': 'scipy', 'RECORD_source_sha256': 'b4b210e29143fee78ff3abd82e2d308554642129deacfcfec4e7e626c2d4fd68', 'record_index': 8, 'CSV_end_line': 9, 'relative_path': 'scipy.libs/libscipy_openblas-b7e2810b.so', 'lexical_absolute_path': '/usr/local/lib/python3.12/site-packages/scipy.libs/libscipy_openblas-b7e2810b.so', 'declared_hash': {'algorithm': 'sha256', 'digest_hex': '5d4ef10608de957609e27942c23e092ce27415dc8394a796d014633ae2995f82'}, 'declared_size_decimal': '28750121', 'actual_path_file_hash_ELF_or_load_observed': False}, {'package': 'scipy', 'RECORD_source_sha256': 'b4b210e29143fee78ff3abd82e2d308554642129deacfcfec4e7e626c2d4fd68', 'record_index': 6, 'CSV_end_line': 7, 'relative_path': 'scipy.libs/libgfortran-daac5196-038a5e3c.so.5.0.0', 'lexical_absolute_path': '/usr/local/lib/python3.12/site-packages/scipy.libs/libgfortran-daac5196-038a5e3c.so.5.0.0', 'declared_hash': {'algorithm': 'sha256', 'digest_hex': '23ee0d91d5786961b0dfbc201a82e6bc8c832b8bf450b56e918a574269a57400'}, 'declared_size_decimal': '1605393', 'actual_path_file_hash_ELF_or_load_observed': False}, {'package': 'scipy', 'RECORD_source_sha256': 'b4b210e29143fee78ff3abd82e2d308554642129deacfcfec4e7e626c2d4fd68', 'record_index': 7, 'CSV_end_line': 8, 'relative_path': 'scipy.libs/libgfortran-e1b7dfc8.so.5.0.0', 'lexical_absolute_path': '/usr/local/lib/python3.12/site-packages/scipy.libs/libgfortran-e1b7dfc8.so.5.0.0', 'declared_hash': {'algorithm': 'sha256', 'digest_hex': '296e40e3d92d0c4377e1f8b40a929045fee6bc5686226faf940fc824e469a7be'}, 'declared_size_decimal': '1484433', 'actual_path_file_hash_ELF_or_load_observed': False}]
PATHS = tuple(row['lexical_absolute_path'] for row in DECLARATIONS)
CANDIDATE_SHA = '52363e510d61b6d3c3964fef6ab099bb270aeee124c849e1f66ef01a649a7723'



# Bind named and held local copy metadata with lossless physical integer strings.
def physical(value):
    return {key: str(getattr(value, key)) for key in ('st_dev', 'st_ino', 'st_mode',
        'st_uid', 'st_nlink', 'st_size', 'st_blocks', 'st_mtime_ns', 'st_ctime_ns')}


# Independently read one regular copied observation twice without following path links.
def read(path):
    assert path.resolve(strict=True) == path
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        before = os.fstat(descriptor)
        assert stat.S_ISREG(before.st_mode) and before.st_uid == 1000 and before.st_nlink == 1
        assert 0 <= before.st_size <= CAP
        first = os.read(descriptor, CAP + 1)
        os.lseek(descriptor, 0, os.SEEK_SET)
        assert os.read(descriptor, CAP + 1) == first and len(first) == before.st_size
        assert physical(before) == physical(os.fstat(descriptor)) == physical(path.stat(follow_symlinks=False))
        return first, {'sha256': hashlib.sha256(first).hexdigest(), 'bytes': len(first), 'physical': physical(before)}
    finally:
        os.close(descriptor)


# Identify complete finite source or wire bytes without executing their contents.
def digest(raw):
    return hashlib.sha256(raw).hexdigest()


# Retain a new bounded observation, fsync its bytes and parent, and verify readback.
def save(name, raw):
    assert type(raw) is bytes and len(raw) <= CAP and Path(name).name == name
    path = REVIEW / name
    with path.open('xb') as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    assert path.read_bytes() == raw
    descriptor = os.open(REVIEW, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    return {'file': name, 'bytes': len(raw), 'sha256': digest(raw)}


# Encode only finite plain metadata within the unchanged ordinary file cap.
def save_json(name, value):
    return save(name, json.dumps(value, sort_keys=True, indent=2, allow_nan=False).encode() + b'\n')


# Interrupt the host helper while letting its owned CLI cleanup and receipts run.
def alarm(signum, frame):
    raise TimeoutError('SOURCE_CENSUS_WALL_BOUND')


# Give only the owned Go CLI its required virtual address ceiling without a daemon RAM claim.
def client_limits():
    resource.setrlimit(resource.RLIMIT_AS, (4294967296, 4294967296))
    signal.pthread_sigmask(signal.SIG_UNBLOCK,
        {signal.SIGALRM, signal.SIGHUP, signal.SIGINT, signal.SIGTERM})


# Bound a read-only Docker response and preserve evidence through bounded owned CLI cleanup.
def command(name, arguments, deadline):
    assert arguments == ('container', 'inspect', CID)
    assert time.monotonic() < deadline
    process, selector = None, selectors.DefaultSelector()
    buffers = {'stdout': bytearray(), 'stderr': bytearray()}
    overflow, stopped, failure, cleanup_failure = {}, None, None, None
    try:
        blocked = signal.pthread_sigmask(signal.SIG_BLOCK,
            {signal.SIGALRM, signal.SIGHUP, signal.SIGINT, signal.SIGTERM})
        try:
            process = subprocess.Popen(DOCKER + arguments, stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True,
                preexec_fn=client_limits)
        finally:
            signal.pthread_sigmask(signal.SIG_SETMASK, blocked)
        for channel in buffers:
            pipe = getattr(process, channel)
            os.set_blocking(pipe.fileno(), False)
            selector.register(pipe, selectors.EVENT_READ, channel)
        limit = min(deadline, time.monotonic() + 5)
        while selector.get_map():
            remaining = limit - time.monotonic()
            if remaining <= 0:
                raise TimeoutError('DOCKER_SOURCE_READ_DEADLINE')
            for key, events in selector.select(min(remaining, 0.1)):
                channel = key.data
                raw = os.read(key.fd, min(4096, CAP - len(buffers[channel]) + 1))
                if not raw:
                    selector.unregister(key.fileobj)
                    continue
                available = CAP - len(buffers[channel])
                buffers[channel].extend(raw[:available])
                if len(raw) > available:
                    overflow[channel] = raw[available:].hex()
                    raise RuntimeError('DOCKER_SOURCE_RESPONSE_BOUND')
        process.wait(timeout=max(0.001, limit - time.monotonic()))
    except BaseException as exc:
        failure = type(exc).__name__
        raise
    finally:
        blocked = signal.pthread_sigmask(signal.SIG_BLOCK,
            {signal.SIGALRM, signal.SIGHUP, signal.SIGINT, signal.SIGTERM})
        try:
            try:
                if process is not None and process.poll() is None:
                    stopped = 'TERM'
                    try:
                        os.killpg(process.pid, signal.SIGTERM)
                    except ProcessLookupError:
                        pass
                    try:
                        process.wait(timeout=1)
                    except subprocess.TimeoutExpired:
                        stopped = 'KILL'
                        try:
                            os.killpg(process.pid, signal.SIGKILL)
                        except ProcessLookupError:
                            pass
                        process.wait(timeout=1)
            except BaseException as exc:
                cleanup_failure = type(exc).__name__
                raise
            finally:
                selector.close()
                if process is not None:
                    process.stdout.close()
                    process.stderr.close()
                outputs = {channel: save(name + '.' + channel, bytes(raw)) for channel, raw in buffers.items()}
                save_json(name + '.exit.json', {'arguments': list(DOCKER + arguments),
                    'pid': None if process is None else str(process.pid),
                    'exit': None if process is None else process.returncode,
                    'owned_CLI_group_stop': stopped, 'failure_class': failure,
                    'cleanup_failure_class': cleanup_failure,
                    'outputs': outputs, 'overflow_first_extra_byte_hex': overflow,
                    'overflow_prefix_is_complete_response': False if overflow else None})
        finally:
            signal.pthread_sigmask(signal.SIG_SETMASK, blocked)
    assert process.returncode == 0 and not stopped and not buffers['stderr'] and not overflow
    return bytes(buffers['stdout'])


# Independently reconstruct strict path metadata from one stored header-only HTTP response.
def decode(raw, path):
    pieces = raw.split(b'\r\n\r\n')
    assert len(pieces) == 2 and pieces[1] == b'' and 4 <= len(raw) <= CAP
    lines = pieces[0].decode('ascii').split('\r\n')
    protocol, code, reason = lines[0].split(' ', 2)
    assert protocol == 'HTTP/1.1' and code in ('200', '404')
    pairs = [line.split(':', 1) for line in lines[1:]]
    assert all(len(pair) == 2 and pair[0] and pair[0] == pair[0].strip()
        and all(33 <= ord(c) <= 126 for c in pair[0]) for pair in pairs)
    lowered = [pair[0].lower() for pair in pairs]
    assert len(set(lowered)) == len(pairs) and 'transfer-encoding' not in lowered
    headers = dict((key.lower(), value.strip()) for key, value in pairs)
    if code == '404':
        assert 'x-docker-container-path-stat' not in headers
        return {'status': 'REFUSED_MISSING_PATH', 'http_status': 404,
            'content_read_authorized': False, 'stat': None}
    encoded = headers['x-docker-container-path-stat']
    value_raw = base64.b64decode(encoded, validate=True)
    assert base64.b64encode(value_raw).decode() == encoded
    value = json.loads(value_raw)
    assert set(value) == {'name', 'size', 'mode', 'mtime', 'linkTarget'}
    assert value['name'] == path.rsplit('/', 1)[1] and value['linkTarget'] == ''
    assert type(value['size']) is int and value['size'] > 0
    assert type(value['mode']) is int and 0 <= value['mode'] <= 4095
    assert isinstance(value['mtime'], str) and 1 <= len(value['mtime']) <= 128
    return {'status': 'DAEMON_REPORTED_REGULAR_PATH_ONLY', 'http_status': 200, 'stat': value,
        'content_bytes_within_ordinary_cap': value['size'] <= CAP,
        'content_read_authorized': False,
        'container_held_FD_identity_or_baked_image_attestation': False}


# Refuse any changed, running, restarted, mounted-over or non-N2 source container.
def inspect_source(raw):
    values = json.loads(raw)
    assert type(values) is list and len(values) == 1
    item = values[0]
    assert item['Id'] == CID and item['Image'] == IMAGE
    state = item['State']
    assert state['Status'] == 'exited' and state['Running'] is False
    assert state['Paused'] is False and state['Restarting'] is False
    assert state['ExitCode'] == 0 and state['OOMKilled'] is False and state['Pid'] == 0
    assert state['FinishedAt'] == '2026-10-18T09:53:55.975021651Z'
    assert item['HostConfig']['ReadonlyRootfs'] is True and item['Config']['User'] == '1000:1000'
    destinations = [mount['Destination'] for mount in item['Mounts']]
    assert len(destinations) == len(set(destinations)) == 2 and set(destinations) == {'/audit', '/out'}
    for path in PATHS:
        assert all(path != target and not path.startswith(target.rstrip('/') + '/') for target in destinations)
    return item


# Compare every inspect field and complete unique mount records while retaining raw list order separately.
def inspection(raw, baseline_raw):
    item, baseline = inspect_source(raw), inspect_source(baseline_raw)
    assert digest(baseline_raw) == BASELINE
    assert {key: value for key, value in item.items() if key != 'Mounts'} == {key: value for key, value in baseline.items() if key != 'Mounts'}
    current_mounts, baseline_mounts = item['Mounts'], baseline['Mounts']
    assert len({mount['Destination'] for mount in current_mounts}) == len(current_mounts) == 2
    assert len({mount['Destination'] for mount in baseline_mounts}) == len(baseline_mounts) == 2
    assert {mount['Destination']: mount for mount in current_mounts} == {mount['Destination']: mount for mount in baseline_mounts}
    return {'sha256': digest(raw), 'bytes': len(raw), 'raw_bytes_equal': raw == baseline_raw,
        'full_decoded_equal': item == baseline, 'raw_Mounts_list_order_equal': current_mounts == baseline_mounts,
        'all_nonMounts_and_complete_uniqueDestination_mount_records_equal': True}


# Authenticate all retained fixed native-path HEAD observations without requesting native bodies.
def main(arguments):
    assert arguments == ['verify-native-path-head'] and __debug__ and os.getuid() == 1000
    assert signal.pthread_sigmask(signal.SIG_BLOCK, set()) == set()
    os.umask(0o077); os.nice(10)
    resource.setrlimit(resource.RLIMIT_AS, (536870912, 4294967296))
    resource.setrlimit(resource.RLIMIT_CPU, (20, 20))
    resource.setrlimit(resource.RLIMIT_FSIZE, (CAP, CAP))
    assert ROOT.resolve(strict=True) == ROOT and REVIEW.parent.resolve(strict=True) == REVIEW.parent
    candidate_raw, first_candidate = read(ROOT / 'candidate.json')
    assert digest(candidate_raw) == CANDIDATE_SHA
    candidate = json.loads(candidate_raw)
    assert candidate['schema'] == 'stopped-n2-native-path-head/1'
    assert candidate['status'] == 'PAIRED_PATH_METADATA_ONLY_REQUIRES_INDEPENDENT_REVIEW'
    assert candidate['container'] == CID and candidate['image'] == IMAGE
    assert candidate['full_inspect_baseline_sha256'] == BASELINE
    assert candidate['package_content_read'] is False and candidate['installed_distribution_version_attested'] is False
    assert candidate['native_package_thread_model_RAM_closure'] is None
    assert candidate['container_start_create_exec_load'] is False and candidate['content_read_authorized'] is False
    assert [row['container_path'] for row in candidate['paths']] == list(PATHS)
    assert candidate['declaration_seam_sha256'] == SEAM_SHA
    names = {'candidate.json', 'prerequisites.json', 'baseline-inspect.json'}
    for label in ('inspect-before', 'inspect-after'):
        names.update(label + suffix for suffix in ('.stdout', '.stderr', '.exit.json'))
    for index in range(20):
        for turn in range(2):
            names.update('path-%02d-read-%d' % (index, turn) + suffix
                for suffix in ('.request', '.response', '.receipt.json'))
    assert len(names) == 129 and {p.name for p in ROOT.iterdir()} == names
    bodies, inventory = {}, {}
    for name in sorted(names):
        bodies[name], inventory[name] = read(ROOT / name)
    assert bodies['candidate.json'] == candidate_raw and inventory['candidate.json'] == first_candidate
    baseline_raw = bodies['baseline-inspect.json']
    assert digest(baseline_raw) == BASELINE and len(baseline_raw) == 9755
    binding = candidate['inspection_binding']
    assert binding['baseline'] == {'file': 'baseline-inspect.json', 'bytes': 9755, 'sha256': BASELINE}
    assert binding['raw_before_after_equal'] == (bodies['inspect-before.stdout'] == bodies['inspect-after.stdout'])
    for label in ('inspect-before', 'inspect-after'):
        receipt = json.loads(bodies[label + '.exit.json'])
        assert receipt['arguments'] == list(DOCKER) + ['container', 'inspect', CID]
        assert receipt['exit'] == 0 and receipt['owned_CLI_group_stop'] is None
        assert receipt['failure_class'] is None and receipt['cleanup_failure_class'] is None
        assert receipt['overflow_first_extra_byte_hex'] == {} and bodies[label + '.stderr'] == b''
        assert binding[label.removeprefix('inspect-')] == inspection(bodies[label + '.stdout'], baseline_raw)
        for channel in ('stdout', 'stderr'):
            expected = receipt['outputs'][channel]
            assert expected == {'file': label + '.' + channel,
                'bytes': len(bodies[label + '.' + channel]), 'sha256': digest(bodies[label + '.' + channel])}
    observations = []
    for index, path in enumerate(PATHS):
        expected_request = ('HEAD /containers/' + CID + '/archive?path=' + quote(path, safe='')
            + ' HTTP/1.1\r\nHost: docker\r\nConnection: close\r\n\r\n').encode('ascii')
        decoded = []
        assert candidate['paths'][index]['declaration'] == DECLARATIONS[index]
        assert len(candidate['paths'][index]['reads']) == 2
        for turn in range(2):
            label = 'path-%02d-read-%d' % (index, turn)
            assert bodies[label + '.request'] == expected_request
            receipt = json.loads(bodies[label + '.receipt.json'])
            assert receipt['failure_class'] is None and receipt['overflow_first_extra_byte_hex'] is None
            assert receipt['socket'] == '/var/run/docker.sock' and receipt['method'] == 'HEAD'
            assert receipt['container_path'] == path and receipt['response_body_requested'] is False
            assert type(receipt['observed_at_ns']) is str and receipt['observed_at_ns'].isdecimal()
            row = candidate['paths'][index]['reads'][turn]
            for key, suffix in (('request', '.request'), ('response', '.response')):
                actual = {'file': label + suffix, 'bytes': len(bodies[label + suffix]),
                    'sha256': digest(bodies[label + suffix])}
                assert receipt[key] == row[key] == actual
            result = decode(bodies[label + '.response'], path)
            assert row['path_metadata'] == result
            decoded.append(result)
        assert decoded[0] == decoded[1]
        assert decoded[0]['http_status'] == 200
        assert decoded[0]['stat']['size'] == int(DECLARATIONS[index]['declared_size_decimal'])
        observations.append({'container_path': path, 'declaration': DECLARATIONS[index], 'path_metadata': decoded[0]})
    prerequisites = json.loads(bodies['prerequisites.json'])
    assert prerequisites['hostname'] == 'animallya-spark1' and prerequisites['uid'] == 1000
    assert prerequisites['source_paths'] == list(PATHS) and prerequisites['reservation'] is False
    assert int(prerequisites['MemAvailable_bytes']) >= 2147483648
    assert int(prerequisites['scratch_available_bytes']) >= 1073741824
    assert int(prerequisites['scratch_available_inodes']) >= 512
    REVIEW.mkdir(mode=0o700, exist_ok=False)
    previous = {sig: signal.signal(sig, alarm) for sig in (signal.SIGALRM, signal.SIGHUP, signal.SIGINT, signal.SIGTERM)}
    # Preserve the existing run() alarm across the fresh inspection and final readback.
    try:
        fresh = command('inspect-fresh', ('container', 'inspect', CID), time.monotonic() + 5)
        fresh_binding = inspection(fresh, baseline_raw)
        baseline_now, baseline_observed = read(BASELINE_INSPECT)
        assert baseline_now == baseline_raw and baseline_observed == binding['baseline_physical']
        for name in sorted(names):
            raw, row = read(ROOT / name)
            assert raw == bodies[name] and row == inventory[name]
        proof = {'schema': 'stopped-n2-native-path-head-independent/1',
            'status': 'VERIFIED_RETAINED_PAIRED_DAEMON_PATH_METADATA_ONLY',
            'candidate_sha256': CANDIDATE_SHA, 'declaration_seam_sha256': SEAM_SHA,
            'inventory': inventory, 'files': 129, 'original_baseline_physical': baseline_observed,
            'path_observations': observations, 'fresh_stopped_inspect_sha256': digest(fresh),
            'inspection_binding': {'before': binding['before'], 'after': binding['after'], 'fresh': fresh_binding},
            'package_content_read_or_path_HEAD_replay': False,
            'installed_distribution_native_thread_model_RAM_admission': None,
            'container_source_held_FD_or_baked_image_attestation': False}
        saved = save_json('proof.json', proof)
        raw, row = read(REVIEW / 'proof.json')
        assert digest(raw) == saved['sha256'] and len(raw) == saved['bytes']
        print(raw.decode(), end='')
    finally:
        signal.alarm(0)
        for sig, handler in previous.items():
            signal.signal(sig, handler)


# Bound the complete independent readback, including all pre-inspection file reads.
def run(arguments):
    previous = {sig: signal.signal(sig, alarm) for sig in (signal.SIGALRM, signal.SIGHUP, signal.SIGINT, signal.SIGTERM)}
    signal.alarm(30)
    try:
        main(arguments)
    finally:
        signal.alarm(0)
        for sig, handler in previous.items():
            signal.signal(sig, handler)


if __name__ == '__main__':
    run(sys.argv[1:])
