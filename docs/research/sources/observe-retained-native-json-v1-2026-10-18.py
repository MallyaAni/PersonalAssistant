"""UNRUN retained historical JSON observer; no executable-path or native-runtime admission."""
import base64
import hashlib
import json
import math
import os
from pathlib import Path, PurePosixPath
import resource
import signal
import socket
import stat
import sys

TOOLS = Path('/home/animallya96/scratch/capacity-native-origin-observer-tools-20261018-v1')
EVIDENCE = Path('/home/animallya96/scratch/capacity-context-parity-evidence-20261018-v1')
ORIGINAL = Path('/home/animallya96/scratch/capacity-context-native-probe-20261018-v1/output/native.json')
COPY = EVIDENCE / 'native/output/native.json'
OUT = Path('/home/animallya96/scratch/capacity-native-origin-observation-20261018-v1')
KEY = 'native/output/native.json'
CONTRACT_SHA = '4a6ef7b722e4b4eb5e77df8de1be7b3fd2ca604d555985d8048409b5748180f5'
PRIOR_SHA = '1355771ff667f81e02dbe07885914dd5be8bf5cf395a3e74ef3bfdfd4988c6f7'
INSPECT_SHA = 'd5265be87b979e83e396e18d1d9d4571cc6e1db5aa09239200004a2809bd90d2'
TOP_SHA = 'd2378ddf7f0e5cf9eac724ff1f7c8f3f5d3cff70c0ba39f45cd2ca18546fd9f9'
CAP = 262144
PHYSICAL = ('st_dev', 'st_ino', 'st_mode', 'st_uid', 'st_nlink', 'st_size', 'st_blocks', 'st_mtime_ns', 'st_ctime_ns')
HASH_USED = 0
READS = 0


# Preserve exact held and named file identities as decimal strings.
def physical(value):
    return {key: str(getattr(value, key)) for key in PHYSICAL}


# Charge every digest before work against one cumulative invocation-wide counter.
def digest(raw):
    global HASH_USED
    assert HASH_USED + len(raw) <= 4194304, 'NATIVE_METADATA_HASH_WORK_BOUND'
    HASH_USED += len(raw)
    return hashlib.sha256(raw).hexdigest()


# Refuse duplicate or oversized JSON objects instead of collapsing catalog records.
def pairs(items):
    assert len(items) <= 2048
    result = {}
    for key, value in items:
        assert type(key) is str and len(key.encode('utf-8')) <= 4096 and key not in result
        result[key] = value
    return result


# Refuse nonfinite JSON constants without changing any original byte representation.
def nonfinite(value):
    raise ValueError('NATIVE_METADATA_NONFINITE_' + value)


# Reject exponent overflow as well as explicit nonfinite JSON constants.
def finite_number(value):
    result = float(value)
    assert math.isfinite(result)
    return result


# Parse only complete bounded JSON with exact object keys and no nonfinite constants.
def decoded(raw):
    assert len(raw) <= CAP
    return json.loads(raw, object_pairs_hook=pairs, parse_constant=nonfinite, parse_float=finite_number)


# Validate a complete ordinary-file metadata row without opening the declared file.
def metadata(row):
    assert type(row) is dict and set(row) == {'bytes', 'sha256', 'physical'}
    assert type(row['bytes']) is int and 0 <= row['bytes'] <= CAP
    assert type(row['sha256']) is str and len(row['sha256']) == 64 and all(c in '0123456789abcdef' for c in row['sha256'])
    fields = row['physical']
    assert type(fields) is dict and set(fields) == set(PHYSICAL)
    assert all(type(v) is str and 1 <= len(v) <= 32 and v.isascii() and v.isdecimal() and str(int(v)) == v for v in fields.values())
    assert int(fields['st_size']) == row['bytes'] and fields['st_uid'] == '1000' and fields['st_nlink'] == '1'
    assert stat.S_ISREG(int(fields['st_mode']))


# Authenticate two complete held reads with original physical pins when supplied and charge their digest.
def read(path, expected=None):
    global READS
    assert READS < 1024 and path.resolve(strict=True) == path
    READS += 1
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        before = os.fstat(descriptor)
        assert stat.S_ISREG(before.st_mode) and before.st_uid == 1000 and before.st_nlink == 1 and 0 <= before.st_size <= CAP
        raw = os.read(descriptor, CAP + 1)
        os.lseek(descriptor, 0, os.SEEK_SET)
        assert os.read(descriptor, CAP + 1) == raw and len(raw) == before.st_size
        assert physical(before) == physical(os.fstat(descriptor)) == physical(path.stat(follow_symlinks=False))
        row = {'bytes': len(raw), 'sha256': digest(raw), 'physical': physical(before)}
        if expected is not None:
            assert all(row[key] == value for key, value in expected.items())
        return raw, row
    finally:
        os.close(descriptor)


# Inspect only bounded top-level manifest-page names, never recursively inventory payload bodies.
def page_names():
    assert EVIDENCE.resolve(strict=True) == EVIDENCE
    result, count = set(), 0
    with os.scandir(EVIDENCE) as entries:
        for entry in entries:
            count += 1
            assert count <= 2048 and len(entry.name.encode('utf-8')) <= 4096
            if entry.name.startswith('manifest-page-'):
                result.add(entry.name)
    return result


# Encode complete finite output pages under the existing byte bound.
def encoded(value):
    raw = json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True, allow_nan=False).encode('ascii') + b'\n'
    assert len(raw) <= 65536
    return raw


# Persist one exclusive bounded output with a charged digest and full charged readback.
def save(name, raw):
    assert len(raw) <= 65536
    sha = digest(raw)
    path = OUT / name
    with path.open('xb') as output:
        output.write(raw)
        output.flush()
        os.fsync(output.fileno())
    observed, row = read(path, {'sha256': sha, 'bytes': len(raw)})
    assert observed == raw
    return row


# Escape ordinary termination and deadlines without retaining an incomplete attempt as acceptance.
def interrupted(signum, frame):
    raise KeyboardInterrupt('NATIVE_METADATA_SIGNAL_' + str(signum))


# Select one authenticated historical artifact after the complete catalog and retain all raw bytes in pages.
def main(arguments):
    assert arguments == ['--observe-retained-native-json-v1']
    assert __debug__ and sys.platform == 'linux' and os.getuid() == 1000 and socket.gethostname() == 'animallya-spark1'
    os.umask(0o077)
    os.nice(10)
    resource.setrlimit(resource.RLIMIT_AS, (536870912, 536870912))
    resource.setrlimit(resource.RLIMIT_CPU, (20, 20))
    resource.setrlimit(resource.RLIMIT_FSIZE, (CAP, CAP))
    for watched in (signal.SIGALRM, signal.SIGINT, signal.SIGHUP, signal.SIGTERM):
        signal.signal(watched, interrupted)
    signal.alarm(30)
    assert Path(__file__) == TOOLS / 'observe-retained-native-json-v1-2026-10-18.py'
    assert OUT.parent.resolve(strict=True) == OUT.parent and not os.path.lexists(OUT)
    inputs = {}
    _, inputs[Path(__file__)] = read(Path(__file__))
    contract_raw, inputs[TOOLS / 'origin-contract.json'] = read(TOOLS / 'origin-contract.json', {'bytes': 24905, 'sha256': CONTRACT_SHA})
    prior_raw, inputs[TOOLS / 'native-proof.json'] = read(TOOLS / 'native-proof.json', {'bytes': 46814, 'sha256': PRIOR_SHA})
    inspect_raw, inputs[TOOLS / 'native-inspect.json'] = read(TOOLS / 'native-inspect.json', {'bytes': 9755, 'sha256': INSPECT_SHA})
    contract, prior, inspections = decoded(contract_raw), decoded(prior_raw), decoded(inspect_raw)
    assert contract['schema'] == 'capacity-native-origin-requirements/1' and contract['genuine_execution_authorized'] is False
    selection = contract['retained_metadata_selection']
    assert selection['evidence_root'] == str(EVIDENCE) and selection['target_manifest_key'] == KEY
    assert selection['target_original'] == str(ORIGINAL) and selection['target_copy'] == str(COPY)
    assert selection['target_SHA_bytes_physical'] is None and selection['top_manifest_sha256'] == TOP_SHA
    assert prior['schema'] == 'capacity-context-native-metadata/1' and prior['status'] == 'VERIFIED_NATIVE_METADATA_ONLY'
    assert prior['genuine_or_parity_acceptance'] is False and prior['stopped'] is True and prior['exit'] == 0
    assert type(inspections) is list and len(inspections) == 1
    inspection = inspections[0]
    assert prior['cid'] == inspection['Id'] == contract['existing_runtime']['cid']
    assert prior['image'] == inspection['Image'] == contract['existing_runtime']['image']
    assert prior['inspect_sha256'] == INSPECT_SHA and prior['python'] == '3.12.14'
    assert prior['native_source']['sha256'] == '6a9e82a33291466c7ef7abc57554c90b26f56c9253bbc1ff4969c49515f0105f'
    assert inspection['State']['Status'] == 'exited' and inspection['State']['Running'] is False and inspection['State']['Pid'] == 0
    assert inspection['State']['ExitCode'] == 0 and inspection['State']['OOMKilled'] is False
    for name in ('Path', 'Args'):
        assert inspection[name] == contract['existing_runtime'][name]
    for name in ('Entrypoint', 'Cmd', 'WorkingDir'):
        assert inspection['Config'][name] == contract['existing_runtime'][name]
    top_raw, inputs[EVIDENCE / 'manifest.json'] = read(EVIDENCE / 'manifest.json', {'bytes': 10845, 'sha256': TOP_SHA})
    top = decoded(top_raw)
    assert set(top) == {'schema', 'scope', 'bytes', 'files', 'pages', 'external_packet', 'proof_sha256', 'preserver_sha256', 'genuine_acceptance'}
    assert top['schema'] == 'capacity-context-parity-evidence/1' and top['genuine_acceptance'] is False
    assert type(top['files']) is int and top['files'] == 1339 and top['bytes'] == 24575979
    assert top['pages'] == selection['page_inventory'] and len(top['pages']) == 21
    names = {'manifest-page-%03d.json' % index for index in range(21)}
    assert page_names() == names
    seen, totals, page_counts, selected = set(), 0, [], []
    for index, pointer in enumerate(top['pages']):
        assert set(pointer) == {'path', 'bytes', 'sha256', 'physical'} and pointer['path'] == 'manifest-page-%03d.json' % index
        pin = {key: value for key, value in pointer.items() if key != 'path'}
        metadata(pin)
        path = EVIDENCE / pointer['path']
        body, inputs[path] = read(path, pin)
        records = decoded(body)
        assert type(records) is dict and len(records) == (64 if index < 20 else 59)
        page_counts.append(len(records))
        for name, row in records.items():
            assert name and '\x00' not in name and PurePosixPath(name).as_posix() == name
            assert not name.startswith('/') and not any(part in ('', '.', '..') for part in name.split('/'))
            assert name not in seen and len(seen) < 1339
            seen.add(name)
            assert type(row) is dict and set(row) == {'original', 'copy'}
            metadata(row['original'])
            metadata(row['copy'])
            assert row['original']['bytes'] == row['copy']['bytes'] and row['original']['sha256'] == row['copy']['sha256']
            totals += row['original']['bytes']
            if name == KEY:
                selected.append({'page': pointer['path'], 'row': row})
    assert len(seen) == 1339 and totals == top['bytes'] and len(selected) == 1
    chosen = selected[0]
    native_raw, inputs[ORIGINAL] = read(ORIGINAL, chosen['row']['original'])
    copied, inputs[COPY] = read(COPY, chosen['row']['copy'])
    assert native_raw == copied and native_raw
    native = decoded(native_raw)
    assert type(native) is dict and set(native) == set(contract['source_omission']['probe_result_fields'])
    assert native['schema'] == 'capacity-context-native-probe/1' and type(native['uid']) is int and native['uid'] == prior['uid'] == 1000
    assert native['python'] == prior['python'] and native['numpy'] == prior['numpy'] and native['threads'] == prior['threads']
    assert type(native['backend_modules']) is list and native['backend_modules'] == [] and native['parity_or_genuine_acceptance'] is False
    assert type(native['observed_at_ns']) is str and native['observed_at_ns'] == prior['probe_observed_at_ns'] and native['observed_at_ns'].isascii() and native['observed_at_ns'].isdecimal()
    executable = native['python_executable']
    assert type(executable) is str and executable.startswith('/') and '\x00' not in executable and 0 < len(executable.encode('utf-8')) <= 4096
    OUT.mkdir(mode=0o700, exist_ok=False)
    pages, output_rows, output_bytes = [], {}, 0
    for offset in range(0, len(native_raw), 32768):
        part = native_raw[offset:offset + 32768]
        record = {'offset': offset, 'bytes': len(part), 'base64': base64.b64encode(part).decode('ascii'), 'sha256': digest(part)}
        index = len(pages)
        assert index < 256
        body = encoded({'schema': 'retained-native-json-raw-page/1', 'start': index, 'records': [record]})
        name = 'body-%04d.json' % index
        row = save(name, body)
        output_rows[OUT / name] = row
        pages.append({'file': name, 'start': index, 'count': 1, **row})
        output_bytes += len(body)
        assert output_bytes <= 16777216
    for path, row in inputs.items():
        read(path, row)
    for path, row in output_rows.items():
        read(path, row)
    assert page_names() == names
    summary = {'schema': 'retained-native-json-observation/1', 'status': 'HISTORICAL_ARTIFACT_REQUIRES_INDEPENDENT_FOLD',
        'input_inventory': {str(path): row for path, row in inputs.items()}, 'contract_sha256': CONTRACT_SHA,
        'top_manifest_sha256': TOP_SHA, 'catalog_records': len(seen), 'catalog_payload_bytes_declared_only': totals,
        'catalog_page_record_counts': page_counts, 'selection': chosen, 'native_fields': native,
        'native_raw_bytes': len(native_raw), 'native_raw_sha256': inputs[ORIGINAL]['sha256'], 'raw_pages': pages,
        'hash_work_before_summary': HASH_USED, 'output_bytes_before_summary': output_bytes,
        'historical_string_only_not_executable_path_build_or_runtime_authority': True,
        'native_runtime_admission': None, 'genuine_execution_authorized': False}
    summary_raw = encoded(summary)
    assert output_bytes + len(summary_raw) <= 16777216
    summary_row = save('summary.json', summary_raw)
    assert sorted(path.name for path in OUT.iterdir()) == sorted([row['file'] for row in pages] + ['summary.json'])
    for directory in (OUT, OUT.parent):
        descriptor = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    signal.alarm(0)
    print(json.dumps({'summary': summary_row, 'pages': len(pages), 'hash_work_final': HASH_USED,
        'output_bytes': output_bytes + len(summary_raw), 'historical_artifact_only': True}, sort_keys=True))


if __name__ == '__main__':
    main(sys.argv[1:])
