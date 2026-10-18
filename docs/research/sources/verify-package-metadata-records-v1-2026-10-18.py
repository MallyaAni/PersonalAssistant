"""Independently fold complete retained metadata/RECORD declarations without package execution."""
import base64
import csv
from email import policy
from email.parser import BytesHeaderParser
import hashlib
import io
import json
import os
from pathlib import Path
import posixpath
import resource
import signal
import stat

ROOT = Path('/home/animallya96/scratch/capacity-package-metadata-record-analysis-20261018-v1')
SOURCE = Path('/home/animallya96/scratch/capacity-package-metadata-text-census-20261018-v2')
PRIOR = Path('/home/animallya96/scratch/capacity-package-metadata-text-independent-20261018-v2/proof.json')
OUT = Path('/home/animallya96/scratch/capacity-package-metadata-record-independent-20261018-v1')
SUMMARY_SHA = '180359449b7d1a3085ad2a50a63f027da28b199f6ecb0559861f098920c7f976'
SUMMARY_BYTES = 228692
PRIOR_SHA = '2b2ca95aaefdf78103e93b2393faa497419270ad0cc4d009f89684314cd046ba'
PREFIX = '/usr/local/lib/python3.12/site-packages'
CAP = 262144


# Preserve local evidence physical identity fields as exact integer strings.
def physical(value):
    return {key: str(getattr(value, key)) for key in ('st_dev', 'st_ino', 'st_mode',
        'st_uid', 'st_nlink', 'st_size', 'st_blocks', 'st_mtime_ns', 'st_ctime_ns')}


# Authenticate one bounded file twice using held no-follow descriptor and named physical bookends.
def read(path, expected=None):
    assert path.resolve(strict=True) == path
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        before = os.fstat(descriptor)
        assert stat.S_ISREG(before.st_mode) and before.st_uid == 1000 and before.st_nlink == 1
        assert 0 <= before.st_size <= CAP
        raw = os.read(descriptor, CAP + 1); os.lseek(descriptor, 0, os.SEEK_SET)
        assert os.read(descriptor, CAP + 1) == raw and len(raw) == before.st_size
        assert physical(before) == physical(os.fstat(descriptor)) == physical(path.stat(follow_symlinks=False))
        row = {'sha256': hashlib.sha256(raw).hexdigest(), 'bytes': len(raw), 'physical': physical(before)}
        if expected is not None:
            for key, value in expected.items():
                assert row[key] == value
        return raw, row
    finally:
        os.close(descriptor)


# Reconstruct a complete RECORD row independently while treating paths and hashes solely as declarations.
def row_value(fields, position, line):
    assert len(fields) == 3 and all(isinstance(value, str) for value in fields)
    path, hash_value, size = fields
    assert path and '\x00' not in path and '\\' not in path and path[-1] != '/'
    absolute = posixpath.normpath(posixpath.join(PREFIX, path))
    declared = None
    if hash_value:
        algorithm, encoded = hash_value.split('=', 1)
        assert algorithm in hashlib.algorithms_guaranteed and encoded and '=' not in encoded
        assert set(encoded) <= set('ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_-')
        binary = base64.urlsafe_b64decode(encoded + '=' * ((4 - len(encoded) % 4) % 4))
        assert 1 <= len(binary) <= 128 and base64.urlsafe_b64encode(binary).decode().rstrip('=') == encoded
        width = hashlib.new(algorithm).digest_size
        assert width == 0 or width == len(binary)
        declared = {'algorithm': algorithm, 'digest_hex': binary.hex()}
    assert size == '' or all(character in '0123456789' for character in size)
    basename = path.split('/')[-1]
    native = any(basename.endswith(suffix) for suffix in ('.so', '.dylib', '.dll', '.pyd')) or '.so.' in basename
    return {'record_index': position, 'CSV_end_line': line, 'fields': fields,
        'lexical_absolute_path': absolute, 'lexical_within_site_packages': absolute.startswith(PREFIX + '/'),
        'declared_hash': declared, 'declared_size_decimal': None if size == '' else str(int(size)),
        'native_filename_shape_only': native}


# Interrupt the finite independent fold without any Docker or package operation.
def alarm(signum, frame):
    raise TimeoutError('PACKAGE_METADATA_INDEPENDENT_BOUND')


# Recompute every source/header/ordered CSV row, derived field and page association independently.
def main():
    assert __debug__ and os.getuid() == 1000 and len(SUMMARY_SHA) == 64 and 0 < SUMMARY_BYTES <= CAP
    os.umask(0o077); os.nice(10)
    resource.setrlimit(resource.RLIMIT_AS, (536870912, 536870912))
    resource.setrlimit(resource.RLIMIT_CPU, (20, 20))
    resource.setrlimit(resource.RLIMIT_FSIZE, (CAP, CAP))
    previous = {sig: signal.signal(sig, alarm) for sig in (signal.SIGALRM, signal.SIGHUP, signal.SIGINT, signal.SIGTERM)}
    signal.alarm(30)
    try:
        summary_raw, summary_row = read(ROOT / 'summary.json', {'sha256': SUMMARY_SHA, 'bytes': SUMMARY_BYTES})
        summary = json.loads(summary_raw)
        prior_raw, prior_row = read(PRIOR, {'sha256': PRIOR_SHA, 'bytes': 27692})
        prior = json.loads(prior_raw)
        assert summary['schema'] == 'copied-package-metadata-RECORD-analysis/1'
        assert summary['status'] == 'METADATA_FIELDS_AND_COMPLETE_RECORD_DECLARATIONS_ONLY_REQUIRES_INDEPENDENT_REVIEW'
        assert summary['prior'] == prior_row and summary['package_AST_CodeType_import_body_Docker_or_declared_file_reads'] is False
        assert summary['installed_runtime_native_thread_model_RAM_admission'] is None
        assert [(p['package'], p['literal_source_version_reference']) for p in summary['packages']] == [('pyarrow', '25.0.1'), ('numpy', '2.5.3'), ('scipy', '1.18.1')]
        pointers = summary['pages']
        assert 0 < len(pointers) <= 1536
        names = [p['file'] for p in pointers]
        assert len(names) == len(set(names)) and set(names) | {'summary.json'} == {p.name for p in ROOT.iterdir()}
        pages, inventory = {}, {}
        for pointer in pointers:
            name = pointer['file']
            assert Path(name).name == name
            raw, observed = read(ROOT / name, {key: pointer[key] for key in ('sha256', 'bytes')})
            page = json.loads(raw)
            assert page['schema'] == 'copied-package-RECORD-rows/1' and 1 <= len(page['records']) <= 64
            pages[name], inventory[name] = page, observed
        sources, results, flattened = {}, [], []
        total, native_total = 0, 0
        csv.field_size_limit(CAP)
        for index, package in enumerate(summary['packages']):
            metadata_name = 'source-%02d.metadata.txt' % (index * 2)
            record_name = 'source-%02d.metadata.txt' % (index * 2 + 1)
            metadata_raw, meta_row = read(SOURCE / metadata_name, prior['source_inventory'][metadata_name])
            record_raw, record_source = read(SOURCE / record_name, prior['source_inventory'][record_name])
            assert summary['sources'][metadata_name] == meta_row and package['metadata_source'] == meta_row
            assert summary['sources'][record_name] == record_source and package['record_source'] == record_source
            sources[metadata_name], sources[record_name] = meta_row, record_source
            message = BytesHeaderParser(policy=policy.compat32).parsebytes(metadata_raw)
            assert not message.defects
            header_pairs = [[key, value] for key, value in message.raw_items()]
            assert package['metadata']['all_header_pairs'] == header_pairs
            selected = {}
            for name in ('Metadata-Version', 'Name', 'Version'):
                values = message.get_all(name, [])
                assert len(values) == 1 and type(values[0]) is str and values[0] and '\r' not in values[0] and '\n' not in values[0]
                selected[name] = values[0]
            assert package['metadata'] == {'fields': selected, 'all_header_pairs': header_pairs,
                'meaning': 'COPIED_DISTRIBUTION_METADATA_DECLARATIONS_NOT_RUNTIME_OR_BINARY_ATTESTATION'}
            assert package['metadata_identity_matches_source_literals'] == (selected['Name'] == package['package'] and selected['Version'] == package['literal_source_version_reference'])
            reader = csv.reader(io.StringIO(record_raw.decode('utf-8'), newline=''), strict=True)
            records = []
            for position, fields in enumerate(reader):
                assert position < 32768
                records.append(row_value(fields, position, reader.line_num))
            assert records and len({r['fields'][0] for r in records}) == len(records)
            actual, position = [], 0
            for pointer in package['pages']:
                assert pointer in pointers
                page = pages[pointer['file']]
                assert page['package'] == package['package'] and page['record_source_sha256'] == record_source['sha256']
                assert page['start_record_index'] == position
                assert pointer['file'] == 'record-%02d-page-%04d.json' % (index, position // 64)
                assert len(page['records']) == min(64, len(records) - position)
                actual.extend(page['records']); position += len(page['records']); flattened.append(pointer)
            assert actual == records and package['record_count'] == len(records)
            native = [r for r in records if r['native_filename_shape_only']]
            assert package['native_filename_declarations'] == native
            assert package['outside_site_packages_declarations'] == [r for r in records if not r['lexical_within_site_packages']]
            directory = package['package'] + '-' + package['literal_source_version_reference'] + '.dist-info/'
            own, = [r for r in records if r['fields'][0] == directory + 'METADATA']
            own_record, = [r for r in records if r['fields'][0] == directory + 'RECORD']
            assert package['METADATA_RECORD_self_consistency_only'] == own and package['RECORD_self_declaration'] == own_record
            if own['declared_hash'] is not None:
                algorithm = own['declared_hash']['algorithm']
                assert algorithm not in ('shake_128', 'shake_256')
                assert hashlib.new(algorithm, metadata_raw).hexdigest() == own['declared_hash']['digest_hex']
            assert own['declared_size_decimal'] is None or own['declared_size_decimal'] == str(len(metadata_raw))
            assert package['declared_files_opened_or_authenticated'] is False
            results.append({'package': package['package'], 'metadata_fields': selected,
                'rows': len(records), 'native_filename_declarations': native,
                'ordered_fields_SHA256': hashlib.sha256(json.dumps([r['fields'] for r in records], separators=(',', ':')).encode()).hexdigest(),
                'outside_site_packages_count': len(package['outside_site_packages_declarations'])})
            total += len(records); native_total += len(native)
        assert set(summary['sources']) == set(sources) and flattened == pointers
        assert summary['total_record_rows'] == total and summary['native_filename_declaration_count'] == native_total
        for name, observed in inventory.items():
            read(ROOT / name, observed)
        for name, observed in sources.items():
            read(SOURCE / name, observed)
        read(ROOT / 'summary.json', summary_row); read(PRIOR, prior_row)
        proof = {'schema': 'copied-package-metadata-RECORD-independent/1',
            'status': 'VERIFIED_METADATA_HEADERS_AND_FULL_ORDERED_RECORD_DECLARATIONS_ONLY',
            'summary': summary_row, 'prior': prior_row, 'sources': sources, 'pages': inventory,
            'packages': results, 'total_record_rows': total, 'native_filename_declaration_count': native_total,
            'declared_native_files_opened_or_authenticated': False,
            'package_AST_CodeType_import_body_Docker_hostprobe_or_old_gate_replay': False,
            'installed_runtime_native_thread_model_RAM_admission': None}
        raw = json.dumps(proof, sort_keys=True, indent=2, allow_nan=False).encode() + b'\n'
        assert len(raw) <= CAP and OUT.parent.resolve(strict=True) == OUT.parent
        OUT.mkdir(mode=0o700, exist_ok=False)
        with (OUT / 'proof.json').open('xb') as stream:
            stream.write(raw); stream.flush(); os.fsync(stream.fileno())
        assert read(OUT / 'proof.json')[0] == raw
        descriptor = os.open(OUT, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        os.fsync(descriptor); os.close(descriptor)
        print(raw.decode(), end='')
    finally:
        signal.alarm(0)
        for sig, handler in previous.items():
            signal.signal(sig, handler)


if __name__ == '__main__':
    main()
