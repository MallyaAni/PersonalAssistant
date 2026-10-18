"""Parse exact copied METADATA/RECORD data without importing installed packages or reading declared files."""
import base64
import csv
from email import policy
from email.parser import BytesParser
import hashlib
import io
import json
import os
from pathlib import Path
import posixpath
import resource
import signal
import stat

SOURCE = Path('/home/animallya96/scratch/capacity-package-metadata-text-census-20261018-v2')
PRIOR = Path('/home/animallya96/scratch/capacity-package-metadata-text-independent-20261018-v2/proof.json')
OUT = Path('/home/animallya96/scratch/capacity-package-metadata-record-analysis-20261018-v1')
PRIOR_SHA = '2b2ca95aaefdf78103e93b2393faa497419270ad0cc4d009f89684314cd046ba'
PREFIX = '/usr/local/lib/python3.12/site-packages'
CAP = 262144
PACKAGES = (('pyarrow', '25.0.1'), ('numpy', '2.5.3'), ('scipy', '1.18.1'))


# Represent held and named physical fields as exact decimal strings.
def physical(value):
    return {key: str(getattr(value, key)) for key in ('st_dev', 'st_ino', 'st_mode',
        'st_uid', 'st_nlink', 'st_size', 'st_blocks', 'st_mtime_ns', 'st_ctime_ns')}


# Authenticate a bounded retained data file through two complete held-descriptor reads and named bookends.
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


# Persist one finite bounded data page or summary with readback and directory sync.
def save(name, value):
    assert Path(name).name == name
    raw = json.dumps(value, sort_keys=True, indent=2, allow_nan=False).encode() + b'\n'
    assert len(raw) <= CAP
    with (OUT / name).open('xb') as stream:
        stream.write(raw); stream.flush(); os.fsync(stream.fileno())
    assert read(OUT / name)[0] == raw
    descriptor = os.open(OUT, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    os.fsync(descriptor); os.close(descriptor)
    return {'file': name, 'sha256': hashlib.sha256(raw).hexdigest(), 'bytes': len(raw)}


# Stop the operational parser within its finite wall-clock allowance.
def alarm(signum, frame):
    raise TimeoutError('PACKAGE_METADATA_DATA_ANALYSIS_BOUND')


# Decode a declared RECORD hash as data without hashing or opening its referenced file.
def declared_hash(value):
    if value == '':
        return None
    algorithm, separator, encoded = value.partition('=')
    assert separator and algorithm in hashlib.algorithms_guaranteed and encoded and '=' not in encoded
    assert all(character in 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_' for character in encoded)
    decoded = base64.b64decode(encoded + '=' * (-len(encoded) % 4), altchars=b'-_', validate=True)
    assert base64.urlsafe_b64encode(decoded).decode().rstrip('=') == encoded and 0 < len(decoded) <= 128
    width = hashlib.new(algorithm).digest_size
    assert width == 0 or len(decoded) == width
    return {'algorithm': algorithm, 'digest_hex': decoded.hex()}


# Classify filename spelling only, never infer binary format, loadability or runtime dependencies.
def native_name(path):
    name = path.rsplit('/', 1)[-1]
    return name.endswith(('.so', '.dylib', '.dll', '.pyd')) or '.so.' in name


# Preserve one complete CSV row and its lexical path/hash/size interpretation without filesystem resolution.
def record_row(fields, index, end_line):
    assert len(fields) == 3 and all(type(value) is str for value in fields)
    path, hash_text, size_text = fields
    assert path and '\x00' not in path and '\\' not in path and not path.endswith('/')
    assert size_text == '' or all('0' <= c <= '9' for c in size_text)
    canonical = posixpath.normpath(path if path.startswith('/') else posixpath.join(PREFIX, path))
    return {'record_index': index, 'CSV_end_line': end_line, 'fields': fields,
        'lexical_absolute_path': canonical,
        'lexical_within_site_packages': canonical.startswith(PREFIX + '/'),
        'declared_hash': declared_hash(hash_text),
        'declared_size_decimal': None if size_text == '' else str(int(size_text)),
        'native_filename_shape_only': native_name(path)}


# Retain all parsed header pairs and mandatory identity fields without evaluating package code.
def metadata(raw):
    message = BytesParser(policy=policy.compat32).parsebytes(raw, headersonly=True)
    assert not message.defects
    selected = {}
    for name in ('Metadata-Version', 'Name', 'Version'):
        values = message.get_all(name, [])
        assert len(values) == 1 and type(values[0]) is str and values[0] and '\n' not in values[0] and '\r' not in values[0]
        selected[name] = values[0]
    return {'fields': selected, 'all_header_pairs': [[name, value] for name, value in message.raw_items()],
        'meaning': 'COPIED_DISTRIBUTION_METADATA_DECLARATIONS_NOT_RUNTIME_OR_BINARY_ATTESTATION'}


# Parse all six authenticated retained data files and preserve complete RECORD rows in bounded ordered pages.
def main():
    assert __debug__ and os.getuid() == 1000
    os.umask(0o077); os.nice(10)
    resource.setrlimit(resource.RLIMIT_AS, (536870912, 536870912))
    resource.setrlimit(resource.RLIMIT_CPU, (20, 20))
    resource.setrlimit(resource.RLIMIT_FSIZE, (CAP, CAP))
    previous = {sig: signal.signal(sig, alarm) for sig in (signal.SIGALRM, signal.SIGHUP, signal.SIGINT, signal.SIGTERM)}
    signal.alarm(30)
    try:
        prior_raw, prior_row = read(PRIOR, {'sha256': PRIOR_SHA, 'bytes': 27692})
        prior = json.loads(prior_raw)
        assert prior['source_files'] == 6 and prior['source_bytes'] == 462945 and prior['full_readback_files'] == 53
        assert OUT.parent.resolve(strict=True) == OUT.parent
        OUT.mkdir(mode=0o700, exist_ok=False)
        csv.field_size_limit(CAP)
        sources, packages, pages = {}, [], []
        for package_index, (package, literal_version) in enumerate(PACKAGES):
            metadata_name, record_name = ('source-%02d.metadata.txt' % (package_index * 2 + offset) for offset in (0, 1))
            metadata_raw, metadata_row = read(SOURCE / metadata_name, prior['source_inventory'][metadata_name])
            record_raw, source_row = read(SOURCE / record_name, prior['source_inventory'][record_name])
            sources[metadata_name], sources[record_name] = metadata_row, source_row
            headers = metadata(metadata_raw)
            reader = csv.reader(io.StringIO(record_raw.decode('utf-8'), newline=''), strict=True)
            records, seen = [], set()
            for index, fields in enumerate(reader):
                assert index < 32768
                row = record_row(fields, index, reader.line_num)
                assert fields[0] not in seen
                seen.add(fields[0]); records.append(row)
            assert records
            package_pages = []
            for start in range(0, len(records), 64):
                name = 'record-%02d-page-%04d.json' % (package_index, start // 64)
                page = save(name, {'schema': 'copied-package-RECORD-rows/1', 'package': package,
                    'record_source_sha256': source_row['sha256'], 'start_record_index': start,
                    'records': records[start:start + 64]})
                package_pages.append(page); pages.append(page)
            relative_metadata = package + '-' + literal_version + '.dist-info/METADATA'
            own = [row for row in records if row['fields'][0] == relative_metadata]
            self_record = [row for row in records if row['fields'][0] == package + '-' + literal_version + '.dist-info/RECORD']
            assert len(own) == len(self_record) == 1
            if own[0]['declared_hash'] is not None:
                algorithm = own[0]['declared_hash']['algorithm']
                assert algorithm not in ('shake_128', 'shake_256')
                assert hashlib.new(algorithm, metadata_raw).hexdigest() == own[0]['declared_hash']['digest_hex']
            if own[0]['declared_size_decimal'] is not None:
                assert own[0]['declared_size_decimal'] == str(len(metadata_raw))
            packages.append({'package': package, 'literal_source_version_reference': literal_version,
                'metadata': headers, 'metadata_identity_matches_source_literals': headers['fields']['Name'] == package and headers['fields']['Version'] == literal_version,
                'record_source': source_row, 'metadata_source': metadata_row,
                'record_count': len(records), 'pages': package_pages,
                'METADATA_RECORD_self_consistency_only': own[0], 'RECORD_self_declaration': self_record[0],
                'native_filename_declarations': [row for row in records if row['native_filename_shape_only']],
                'outside_site_packages_declarations': [row for row in records if not row['lexical_within_site_packages']],
                'declared_files_opened_or_authenticated': False})
        for name, row in sources.items():
            read(SOURCE / name, row)
        read(PRIOR, prior_row)
        summary = {'schema': 'copied-package-metadata-RECORD-analysis/1',
            'status': 'METADATA_FIELDS_AND_COMPLETE_RECORD_DECLARATIONS_ONLY_REQUIRES_INDEPENDENT_REVIEW',
            'prior': prior_row, 'sources': sources, 'packages': packages, 'pages': pages,
            'total_record_rows': sum(row['record_count'] for row in packages),
            'native_filename_declaration_count': sum(len(row['native_filename_declarations']) for row in packages),
            'package_AST_CodeType_import_body_Docker_or_declared_file_reads': False,
            'installed_runtime_native_thread_model_RAM_admission': None}
        saved = save('summary.json', summary)
        print((OUT / saved['file']).read_text(), end='')
    finally:
        signal.alarm(0)
        for sig, handler in previous.items():
            signal.signal(sig, handler)


if __name__ == '__main__':
    main()
