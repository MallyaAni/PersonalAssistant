"""UNRUN independent historical metadata selector; unobserved summary pins refuse use."""
import base64
import hashlib
import json
import math
import os
from pathlib import Path
import resource
import signal
import socket
import stat
import sys

BASE = Path('/home/animallya96/scratch')
TOOLS = BASE / 'capacity-native-origin-independent-tools-20261018-v1'
PRIMARY_TOOLS = BASE / 'capacity-native-origin-observer-tools-20261018-v1'
PRIMARY = PRIMARY_TOOLS / 'observe-retained-native-json-v1-2026-10-18.py'
PRIMARY_SHA = 'b7f6ffb0b968c08caa0b6133c0d2aa20d75c54f87b0abc80326c28c9096a6e5b'
OBSERVATION = BASE / 'capacity-native-origin-observation-20261018-v1'
SUMMARY_SHA = '8402d4238508755502005d8290141e10827494083a6384b46be611b5e962986d'
SUMMARY_BYTES = 13430
EVIDENCE = BASE / 'capacity-context-parity-evidence-20261018-v1'
ORIGINAL = BASE / 'capacity-context-native-probe-20261018-v1/output/native.json'
COPY = EVIDENCE / 'native/output/native.json'
DESTINATION = BASE / 'capacity-native-origin-independent-20261018-v1'
CONTRACT_SHA = '4a6ef7b722e4b4eb5e77df8de1be7b3fd2ca604d555985d8048409b5748180f5'
PRIOR_SHA = '1355771ff667f81e02dbe07885914dd5be8bf5cf395a3e74ef3bfdfd4988c6f7'
INSPECT_SHA = 'd5265be87b979e83e396e18d1d9d4571cc6e1db5aa09239200004a2809bd90d2'
TOP_SHA = 'd2378ddf7f0e5cf9eac724ff1f7c8f3f5d3cff70c0ba39f45cd2ca18546fd9f9'
FIELDS = ('st_dev', 'st_ino', 'st_mode', 'st_uid', 'st_nlink', 'st_size', 'st_blocks', 'st_mtime_ns', 'st_ctime_ns')
WORK = 0
OPENS = 0
INPUTS = {}


# Convert every physical field without loss through floating point or JavaScript.
def identity(info):
    return dict(zip(FIELDS, (str(getattr(info, name)) for name in FIELDS)))


# Account for every hash before creating a digest under one invocation-wide budget.
def charged_sha(body):
    global WORK
    assert len(body) <= 4194304 - WORK, 'INDEPENDENT_NATIVE_HASH_WORK_BOUND'
    WORK += len(body)
    hasher = hashlib.sha256()
    hasher.update(body)
    return hasher.hexdigest()


# Authenticate complete bytes twice using bounded chunked reads and held/named identities.
def acquire(filename, pin=None):
    global OPENS
    assert OPENS < 1024 and filename.resolve(strict=True) == filename
    OPENS += 1
    fd = os.open(filename, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        first = os.fstat(fd)
        assert stat.S_ISREG(first.st_mode) and first.st_uid == 1000 and first.st_nlink == 1
        assert 0 <= first.st_size <= 262144
        passes = []
        for iteration in range(2):
            os.lseek(fd, 0, os.SEEK_SET)
            body = bytearray()
            while True:
                chunk = os.read(fd, min(16384, 262145 - len(body)))
                if not chunk:
                    break
                body.extend(chunk)
                assert len(body) <= 262144
            passes.append(bytes(body))
        assert passes[0] == passes[1] and len(passes[0]) == first.st_size
        assert identity(first) == identity(os.fstat(fd)) == identity(os.lstat(filename))
        row = {'physical': identity(first), 'bytes': len(passes[0]), 'sha256': charged_sha(passes[0])}
        if pin is not None:
            for name in pin:
                assert row[name] == pin[name]
        if filename in INPUTS:
            assert INPUTS[filename] == row
        INPUTS[filename] = row
        return passes[0], row
    finally:
        os.close(fd)


# Reject duplicate bounded object members before constructing a JSON dictionary.
def unique_members(entries):
    assert len(entries) <= 2048
    names = [entry[0] for entry in entries]
    assert len(names) == len(set(names))
    assert all(type(name) is str and len(name.encode('utf-8')) <= 4096 for name in names)
    return dict(entries)


# Reject both literal nonfinite constants and overflowed decimal exponents.
def finite_decimal(text):
    number = float(text)
    assert math.isfinite(number)
    return number


# Refuse nonstandard JSON constants rather than accepting or normalizing them.
def invalid_constant(text):
    raise ValueError('INDEPENDENT_NATIVE_NONFINITE_' + text)


# Parse bounded JSON independently with duplicate and numeric checks.
def parse(body):
    assert len(body) <= 262144
    return json.loads(body.decode('utf-8'), object_pairs_hook=unique_members,
        parse_constant=invalid_constant, parse_float=finite_decimal)


# Check all declared physical metadata without opening the record's payload.
def check_row(row):
    assert isinstance(row, dict) and set(row) == {'bytes', 'sha256', 'physical'}
    assert type(row['bytes']) is int and row['bytes'] in range(262145)
    value = row['sha256']
    assert type(value) is str and len(value) == 64 and set(value) <= set('0123456789abcdef')
    physical = row['physical']
    assert type(physical) is dict and set(physical) == set(FIELDS)
    for text in physical.values():
        assert type(text) is str and 0 < len(text) <= 32 and text.isascii() and text.isdecimal()
        assert str(int(text)) == text
    assert physical['st_size'] == str(row['bytes']) and physical['st_uid'] == '1000' and physical['st_nlink'] == '1'
    assert stat.S_IFMT(int(physical['st_mode'])) == stat.S_IFREG


# Enumerate only bounded direct names for exact before-and-after inventory checks.
def names(directory, prefix=None):
    assert directory.resolve(strict=True) == directory
    found = set()
    with os.scandir(directory) as entries:
        count = 0
        for entry in entries:
            count += 1
            assert count <= 2048 and len(entry.name.encode('utf-8')) <= 4096
            if prefix is None or entry.name[:len(prefix)] == prefix:
                found.add(entry.name)
    return found


# Reconstruct the primary's complete canonical output bytes without calling its encoder.
def canonical(value):
    result = (json.dumps(value, ensure_ascii=True, allow_nan=False, separators=(',', ':'), sort_keys=True) + '\n').encode('ascii')
    assert len(result) <= 65536
    return result


# Raise outside ordinary exception retention when interrupted or out of wall time.
def stop(number, frame):
    raise KeyboardInterrupt('INDEPENDENT_NATIVE_SIGNAL_' + str(number))


# Independently select the complete catalog row and reconstruct every observed byte and field.
def main(arguments):
    assert arguments == ['--independent-retained-native-json-v1']
    assert SUMMARY_BYTES > 0 and len(SUMMARY_SHA) == 64, 'UNOBSERVED_PRIMARY_SUMMARY_REFUSES_USE'
    assert __debug__ and sys.platform == 'linux' and os.getuid() == 1000 and socket.gethostname() == 'animallya-spark1'
    os.umask(0o077)
    os.nice(10)
    for limit, value in ((resource.RLIMIT_AS, 536870912), (resource.RLIMIT_CPU, 20), (resource.RLIMIT_FSIZE, 262144)):
        resource.setrlimit(limit, (value, value))
    for number in (signal.SIGALRM, signal.SIGINT, signal.SIGHUP, signal.SIGTERM):
        signal.signal(number, stop)
    signal.alarm(30)
    assert Path(__file__) == TOOLS / 'verify-retained-native-json-v1-2026-10-18.py'
    assert DESTINATION.parent.resolve(strict=True) == DESTINATION.parent and not os.path.lexists(DESTINATION)
    acquire(Path(__file__))
    _, primary_row = acquire(PRIMARY, {'sha256': PRIMARY_SHA})
    contract = parse(acquire(PRIMARY_TOOLS / 'origin-contract.json', {'bytes': 24905, 'sha256': CONTRACT_SHA})[0])
    prior = parse(acquire(PRIMARY_TOOLS / 'native-proof.json', {'bytes': 46814, 'sha256': PRIOR_SHA})[0])
    inspections = parse(acquire(PRIMARY_TOOLS / 'native-inspect.json', {'bytes': 9755, 'sha256': INSPECT_SHA})[0])
    summary_raw, summary_row = acquire(OBSERVATION / 'summary.json', {'bytes': SUMMARY_BYTES, 'sha256': SUMMARY_SHA})
    summary = parse(summary_raw)
    assert canonical(summary) == summary_raw
    selection = contract['retained_metadata_selection']
    runtime = contract['existing_runtime']
    assert contract['schema'] == 'capacity-native-origin-requirements/1' and contract['genuine_execution_authorized'] is False
    assert selection['evidence_root'] == str(EVIDENCE) and selection['target_manifest_key'] == 'native/output/native.json'
    assert selection['target_original'] == str(ORIGINAL) and selection['target_copy'] == str(COPY)
    assert selection['target_SHA_bytes_physical'] is None and selection['top_manifest_sha256'] == TOP_SHA
    assert prior['schema'] == 'capacity-context-native-metadata/1' and prior['status'] == 'VERIFIED_NATIVE_METADATA_ONLY'
    assert prior['stopped'] is True and prior['genuine_or_parity_acceptance'] is False and prior['exit'] == 0
    assert type(inspections) is list and len(inspections) == 1
    inspection = inspections[0]
    assert runtime['cid'] == inspection['Id'] == prior['cid'] and runtime['image'] == inspection['Image'] == prior['image']
    assert prior['inspect_sha256'] == INSPECT_SHA and prior['python'] == '3.12.14'
    assert prior['native_source']['sha256'] == '6a9e82a33291466c7ef7abc57554c90b26f56c9253bbc1ff4969c49515f0105f'
    assert inspection['State']['Status'] == 'exited' and inspection['State']['Running'] is False and inspection['State']['Pid'] == 0
    assert inspection['State']['ExitCode'] == 0 and inspection['State']['OOMKilled'] is False
    assert all(inspection[key] == runtime[key] for key in ('Path', 'Args'))
    assert all(inspection['Config'][key] == runtime[key] for key in ('Entrypoint', 'Cmd', 'WorkingDir'))
    top = parse(acquire(EVIDENCE / 'manifest.json', {'sha256': TOP_SHA, 'bytes': 10845})[0])
    assert set(top) == {'schema', 'scope', 'bytes', 'files', 'pages', 'external_packet', 'proof_sha256', 'preserver_sha256', 'genuine_acceptance'}
    assert top['schema'] == 'capacity-context-parity-evidence/1' and top['genuine_acceptance'] is False
    assert type(top['files']) is int and top['files'] == 1339 and top['bytes'] == 24575979
    assert top['pages'] == selection['page_inventory'] and len(top['pages']) == 21
    expected_names = {'manifest-page-%03d.json' % index for index in range(21)}
    assert names(EVIDENCE, 'manifest-page-') == expected_names
    catalog_names, sizes, matches, counts = set(), [], [], []
    for index in range(21):
        pointer = top['pages'][index]
        assert set(pointer) == {'path', 'bytes', 'sha256', 'physical'} and pointer['path'] == 'manifest-page-%03d.json' % index
        pin = dict(pointer)
        del pin['path']
        check_row(pin)
        records = parse(acquire(EVIDENCE / pointer['path'], pin)[0])
        assert type(records) is dict and len(records) == (59 if index == 20 else 64)
        counts.append(len(records))
        for label in records:
            assert label and not label.startswith('/') and '\x00' not in label
            parts = label.split('/')
            assert all(part not in {'', '.', '..'} for part in parts) and '/'.join(parts) == label
            assert label not in catalog_names and len(catalog_names) < 1339
            catalog_names.add(label)
            item = records[label]
            assert type(item) is dict and set(item) == {'original', 'copy'}
            for kind in ('original', 'copy'):
                check_row(item[kind])
            assert item['original']['sha256'] == item['copy']['sha256'] and item['original']['bytes'] == item['copy']['bytes']
            sizes.append(item['original']['bytes'])
            if label == 'native/output/native.json':
                matches.append({'page': pointer['path'], 'row': item})
    assert len(catalog_names) == 1339 and sum(sizes) == top['bytes'] and len(matches) == 1
    selected = matches[0]
    raw, original_row = acquire(ORIGINAL, selected['row']['original'])
    assert raw and acquire(COPY, selected['row']['copy'])[0] == raw
    fields = parse(raw)
    assert type(fields) is dict and set(fields) == set(contract['source_omission']['probe_result_fields'])
    assert fields['schema'] == 'capacity-context-native-probe/1' and type(fields['uid']) is int and fields['uid'] == prior['uid'] == 1000
    assert all(fields[key] == prior[key] for key in ('python', 'numpy', 'threads'))
    assert type(fields['backend_modules']) is list and fields['backend_modules'] == [] and fields['parity_or_genuine_acceptance'] is False
    timestamp = fields['observed_at_ns']
    assert type(timestamp) is str and timestamp.isascii() and timestamp.isdecimal() and timestamp == prior['probe_observed_at_ns']
    executable = fields['python_executable']
    assert type(executable) is str and executable[:1] == '/' and '\x00' not in executable and 0 < len(executable.encode('utf-8')) <= 4096
    primary_paths = {PRIMARY, PRIMARY_TOOLS / 'origin-contract.json', PRIMARY_TOOLS / 'native-proof.json', PRIMARY_TOOLS / 'native-inspect.json', EVIDENCE / 'manifest.json', ORIGINAL, COPY}
    primary_paths.update(EVIDENCE / ('manifest-page-%03d.json' % index) for index in range(21))
    expected_inventory = {str(path): INPUTS[path] for path in primary_paths}
    page_count = (len(raw) + 32767) // 32768
    assert 1 <= page_count <= 8 and names(OBSERVATION) == {'summary.json'} | {'body-%04d.json' % i for i in range(page_count)}
    page_rows, reconstructed, output_bytes = [], bytearray(), 0
    for index in range(page_count):
        part = raw[index * 32768:(index + 1) * 32768]
        page = {'schema': 'retained-native-json-raw-page/1', 'start': index, 'records': [{'offset': index * 32768,
            'bytes': len(part), 'base64': base64.b64encode(part).decode('ascii'), 'sha256': charged_sha(part)}]}
        body = canonical(page)
        filename = 'body-%04d.json' % index
        observed, row = acquire(OBSERVATION / filename)
        assert observed == body
        decoded_page = parse(observed)
        assert decoded_page == page and len(decoded_page['records']) == 1
        reconstructed.extend(base64.b64decode(decoded_page['records'][0]['base64'], validate=True))
        page_rows.append({'file': filename, 'start': index, 'count': 1, **row})
        output_bytes += len(body)
    assert bytes(reconstructed) == raw
    before_summary = 2 * sum(row['bytes'] for row in expected_inventory.values()) + len(raw) + 3 * output_bytes
    expected_summary = {'schema': 'retained-native-json-observation/1', 'status': 'HISTORICAL_ARTIFACT_REQUIRES_INDEPENDENT_FOLD',
        'input_inventory': expected_inventory, 'contract_sha256': CONTRACT_SHA, 'top_manifest_sha256': TOP_SHA,
        'catalog_records': 1339, 'catalog_payload_bytes_declared_only': sum(sizes), 'catalog_page_record_counts': counts,
        'selection': selected, 'native_fields': fields, 'native_raw_bytes': len(raw), 'native_raw_sha256': original_row['sha256'],
        'raw_pages': page_rows, 'hash_work_before_summary': before_summary, 'output_bytes_before_summary': output_bytes,
        'historical_string_only_not_executable_path_build_or_runtime_authority': True, 'native_runtime_admission': None,
        'genuine_execution_authorized': False}
    assert summary == expected_summary and canonical(expected_summary) == summary_raw
    assert before_summary + 2 * len(summary_raw) <= 4194304 and output_bytes + len(summary_raw) <= 16777216
    for filename, pin in list(INPUTS.items()):
        acquire(filename, pin)
    assert names(EVIDENCE, 'manifest-page-') == expected_names
    assert names(OBSERVATION) == {'summary.json'} | {'body-%04d.json' % i for i in range(page_count)}
    proof = {'schema': 'independent-retained-native-json/1', 'status': 'HISTORICAL_ARTIFACT_BYTES_ONLY',
        'input_inventory': {str(path): row for path, row in INPUTS.items()}, 'summary': summary_row,
        'primary_source': primary_row, 'selection': selected, 'catalog_records': 1339, 'raw_pages': page_rows,
        'native_fields': fields, 'complete_raw_equal': True, 'complete_canonical_summary_equal': True,
        'primary_hash_work_final': before_summary + 2 * len(summary_raw), 'hash_work_before_proof': WORK,
        'native_runtime_admission': None, 'genuine_execution_authorized': False}
    proof_raw = canonical(proof)
    expected_sha = charged_sha(proof_raw)
    DESTINATION.mkdir(mode=0o700, exist_ok=False)
    with (DESTINATION / 'proof.json').open('xb') as output:
        output.write(proof_raw)
        output.flush()
        os.fsync(output.fileno())
    assert acquire(DESTINATION / 'proof.json', {'sha256': expected_sha, 'bytes': len(proof_raw)})[0] == proof_raw
    assert names(DESTINATION) == {'proof.json'}
    for directory in (DESTINATION, DESTINATION.parent):
        descriptor = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    signal.alarm(0)
    print(json.dumps({'proof_sha256': expected_sha, 'proof_bytes': len(proof_raw), 'hash_work_final': WORK,
        'historical_artifact_only': True}, sort_keys=True))


if __name__ == '__main__':
    main(sys.argv[1:])
