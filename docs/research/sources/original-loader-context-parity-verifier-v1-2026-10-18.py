"""UNRUN independent terminal review; no payload imports or synthetic body replay."""
import hashlib
import json
import os
import resource
import stat
import subprocess
import sys
from pathlib import Path

SOURCE = Path('/home/animallya96/scratch/capacity-context-parity-source-20261018-v1')
RUN = Path('/home/animallya96/scratch/capacity-context-parity-20261018-v1')
REVIEW = Path('/home/animallya96/scratch/capacity-context-parity-independent-review-20261018-v1')
IMAGE = 'sha256:e0a54c1f3b293c241ea0eae767d8ba017d0e1a05679965935b336910faa63237'
POSITIVE = {
    'reader-exact31-and-paper-descriptor', 'reader-identical-copy-content-equivalent',
    'constructor-external-ShaMap-retained', 'constructor-plain-input-map-mode',
    'constructor-ending-Rows-digest-and-release', 'constructor-readonly-and-deepcopy', 'constructor-explicit-root-scratch-identity',
    'inputs-capture-selection-and-unused-count', 'source-chain-three-catalog-two-transition',
    'preservation-all-session-and-physical-hashes', 'preservation-source-bound17fields-and-path',
    'preservation-original-physical-nonfinite-logical-domain', 'calendar-source-and-parent-data-origins',
    'calendar-reviewed-years-and-closures-parity', 'calendar-boundary-session-sequence-parity',
    'phase-attach-before-after-order', 'phase-complete-JSON-UTF8-retains-both-graphs',
    'phase-real-file-directory-parent-sync-order', 'phase-release-only-own-RAM-refs-files-retained'}
REFUSALS = {
    'reader-map-type-refusal': ('ValueError', 'EXACT_NATIVE_SOURCE_DICT_REQUIRED'),
    'reader-map-count-refusal': ('RuntimeError', 'EXACT_N2_SOURCE_READER_REQUIRED'),
    'reader-map-hash-refusal': ('RuntimeError', 'EXACT_N2_NATIVE31_MAP_REQUIRED'),
    'reader-missing-source-refusal': ('FileNotFoundError', None),
    'reader-changed-source-refusal': ('ValueError', 'Pinned stream input bytes differ'),
    'reader-absolute-path-refusal': ('ValueError', 'CANONICAL_RELATIVE_NATIVE_SOURCE_REQUIRED'),
    'reader-traversal-path-refusal': ('ValueError', 'CANONICAL_RELATIVE_NATIVE_SOURCE_REQUIRED'),
    'reader-noncanonical-path-refusal': ('ValueError', 'CANONICAL_RELATIVE_NATIVE_SOURCE_REQUIRED'),
    'reader-nonmember-refusal': ('ValueError', 'NATIVE_SOURCE_MEMBER_REQUIRED'),
    'reader-subclass-refusal': ('ValueError', 'EXACT_CAPACITY_SOURCE_READER_REQUIRED'),
    'reader-recheck-changed-bytes-refusal': ('ValueError', 'Pinned stream input bytes differ'),
    'constructor-scratch-collision-refusal': ('FileExistsError', None),
    'constructor-reader-type-refusal': ('ValueError', 'EXACT_CAPACITY_SOURCE_READER_REQUIRED'),
    'constructor-bool-mode-refusal': ('ValueError', 'EXACT_EXTERNAL_INPUT_MODE_REQUIRED'),
    'constructor-status-refusal-retains-scratch': ('ValueError', 'Genuine completed original account required'),
    'constructor-missing-ending-retains-scratch': ('KeyError', "'paper_state'"),
    'constructor-malformed-completion-refusal': ('ValueError', 'Truncated original JSON value'),
    'inputs-relative-capture-path-refusal': ('ValueError', 'Relative original capture path required'),
    'inputs-changed-consumed-file-refusal': ('ValueError', 'Pinned stream input bytes differ'),
    'unchanged-ShaMap-index-tamper-refusal': ('ValueError', 'SHA map index changed'),
    'unchanged-ShaMap-spool-tamper-refusal': ('ValueError', 'SHA map spool changed'),
    'unchanged-original-selector-tamper-refusal': ('ValueError', 'Pinned stream input bytes differ'),
    'source-chain-changed-third-catalog-refusal': ('ValueError', 'Pinned stream input bytes differ'),
    'source-chain-legacy6-and-producer5-refusal': ('ValueError', 'Exact original legacy producer profile required'),
    'preservation-physical-size-refusal': ('ValueError', 'EXTERNAL_PHYSICAL_SIZE_DIFFERS'),
    'preservation-physical-SHA-refusal': ('ValueError', 'ORIGINAL_INPUT_DIGEST_MISMATCH'),
    'preservation-session-SHA-refusal': ('ValueError', 'Pinned stream input bytes differ'),
    'preservation-missing-field-refusal': ('ValueError', 'EXACT_ORIGINAL_PHYSICAL_STATE_SCHEMA_REQUIRED'),
    'preservation-extra-field-refusal': ('ValueError', 'EXACT_ORIGINAL_PHYSICAL_STATE_SCHEMA_REQUIRED'),
    'preservation-logical-ending-mismatch-refusal': ('ValueError', 'FINAL_PHYSICAL_STATE_DIFFERS_FROM_COMPLETION'),
    'preservation-CURRENT-paper-source-refusal': ('RuntimeError', 'EXACT_N2_PAPER_SOURCE_REQUIRED'),
    'preservation-archive-type-refusal': ('ValueError', 'EXACT_CAPACITY_ARCHIVES_REQUIRED'),
    'calendar-root-mismatch-refusal': ('ValueError', 'CAPACITY_CALENDAR_IMPORT_ROOT_REQUIRED'),
    'calendar-data-hash-refusal': ('ValueError', 'Pinned stream input bytes differ'),
    'binding-unit-schema-refusal': ('ValueError', 'EXACT_CAPACITY_BINDING_REQUIRED'),
    'binding-unit-profile-refusal': ('ValueError', 'ORIGINAL_FULL_CAPACITY_PROFILE_REQUIRED'),
    'binding-unit-import-root-refusal': ('ValueError', 'ACTUAL_CAPACITY_IMPORT_ROOT_REQUIRED'),
    'binding-unit-base2446-hash-refusal': ('ValueError', 'UNCHANGED_LEGACY2446_MAP_REQUIRED'),
    'binding-unit-module-set-refusal': ('ValueError', 'EXACT_CAPACITY_MODULE_SET_REQUIRED'),
    'binding-unit-legacy-override-refusal': ('ValueError', 'LEGACY_SOURCE_OVERRIDE_FORBIDDEN'),
    'binding-unit-map-union-refusal': ('ValueError', 'EXACT_CAPACITY_MAP_UNION_REQUIRED'),
    'binding-unit-duplicate-mount-destination-refusal': ('ValueError', 'UNIQUE_RUNTIME_MOUNT_DESTINATIONS_REQUIRED'),
    'binding-unit-writable-root-refusal': ('ValueError', 'EXACT_READONLY_CAPACITY_HOST_ROOT_REQUIRED'),
    'binding-unit-host-root-mapping-refusal': ('ValueError', 'EXACT_READONLY_CAPACITY_HOST_ROOT_REQUIRED'),
    'phase-duplicate-attach-refusal': ('ValueError', 'EXACT_LOADED_RETENTION_PHASE_REQUIRED'),
    'phase-after-before-attach-refusal': ('ValueError', 'AFTER_PHASE_ORDER_REQUIRED'),
    'phase-serialize-before-after-refusal': ('ValueError', 'COEXISTENCE_ROOTS_REQUIRED'),
    'phase-small-injected-result-bound-refusal': ('ValueError', 'CAPACITY_RESULT_BOUND_EXCEEDED'),
    'phase-persist-before-encode-refusal': ('ValueError', 'DURABLE_CANDIDATE_PHASE_REQUIRED'),
    'phase-exclusive-result-collision-refusal': ('FileExistsError', None),
    'phase-parent-path-FD-mismatch-refusal': ('ValueError', 'OWNED_DURABILITY_DIRECTORY_CHANGED'),
    'phase-directory-sync-failure-no-durable-phase': ('OSError', 'INJECTED_UNIT_DIRECTORY_FSYNC_FAILURE'),
    'phase-release-before-durability-refusal': ('ValueError', 'RELEASE_BEFORE_DURABILITY_FORBIDDEN'),
    'phase-public-execute-unconditional-refusal': ('RuntimeError', 'SOURCE_ONLY_NO_GENUINE_EXECUTOR_OR_MODEL_STRATEGY')}


# Require each declared candidate/reference/unit scope independently of the child status report.
def expected_scope(case):
    phase = 'INJECTED_PHASE_HOLDER_UNIT_CTOR_GENUINE_ADMISSIONS_LOADER_UNRUN'
    if case.startswith('phase-'):
        return phase + ({'phase-small-injected-result-bound-refusal': '_INJECTED_SMALL_BOUND_RESTORED',
                         'phase-real-file-directory-parent-sync-order': '_REAL_IO_NO_CRASH_DURABILITY_CLAIM'}.get(case, ''))
    if case.startswith('binding-unit-'):
        return ('INJECTED_MOUNT_RECORD_NEGATIVE_UNIT_NOT_ACTUAL_RUNTIME' if case in {
            'binding-unit-duplicate-mount-destination-refusal', 'binding-unit-writable-root-refusal', 'binding-unit-host-root-mapping-refusal'}
            else 'INJECTED_PINNED_METADATA_NEGATIVE_UNIT_NO_FULLMAP_OR_GENUINE_ADMISSION')
    return {
        'constructor-external-ShaMap-retained': 'ISOLATED_SYNTHETIC_CONSTRUCTOR_PARITY_DECLARED_CLASS_AND_ROOT_DIFFERENCES',
        'constructor-plain-input-map-mode': 'ISOLATED_SYNTHETIC_CONSTRUCTOR_PARITY_DECLARED_CLASS_AND_ROOT_DIFFERENCES',
        'preservation-all-session-and-physical-hashes': 'SYNTHETIC_RAW_HASH_PRESERVATION_NOT_GENUINE_ORIGINAL_ARCHIVES',
        'preservation-original-physical-nonfinite-logical-domain': 'EXISTING_EXPLICIT_PHYSICAL_TRUE_LOGICAL_COMPARISON_ONLY',
        'preservation-CURRENT-paper-source-refusal': 'SOURCE_DESCRIPTOR_BOUNDARY_ONLY_CONTEXT_NATIVE31_WOULD_REFUSE_EARLIER',
        'calendar-reviewed-years-and-closures-parity': 'ISOLATED_REVIEWED_SESSIONS_REFERENCE_REAL_PUBLIC_DATA',
        'calendar-boundary-session-sequence-parity': 'BOUNDED_DATE_REFERENCE_PARITY_NOT_FULL_ORIGINAL_PROFILE',
        'calendar-root-mismatch-refusal': 'SYNTHETIC_CALENDAR_METADATA_ONLY',
        'calendar-data-hash-refusal': 'SYNTHETIC_CALENDAR_METADATA_ONLY'}.get(case, 'ACTUAL_SYNTHETIC_CANDIDATE')


# Retain exact physical identity with decimal nanoseconds throughout independent reads.
def physical(value):
    return {k: str(getattr(value, k)) for k in ('st_dev', 'st_ino', 'st_mode', 'st_uid', 'st_nlink', 'st_size', 'st_blocks', 'st_mtime_ns', 'st_ctime_ns')}


# Independently read one bounded regular file with full named and held bookends.
def read(path):
    assert path.resolve(strict=True) == path
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        before = os.fstat(descriptor)
        assert stat.S_ISREG(before.st_mode) and before.st_uid == 1000 and before.st_nlink == 1 and 0 <= before.st_size <= 262144
        raw = os.read(descriptor, 262145)
        assert len(raw) == before.st_size and physical(before) == physical(os.fstat(descriptor)) == physical(path.stat(follow_symlinks=False))
        return raw, {'sha256': hashlib.sha256(raw).hexdigest(), 'bytes': len(raw), 'physical': physical(before)}
    finally:
        os.close(descriptor)


# Persist a new bounded independent proof or manifest page without replacing failed evidence.
def save(path, value):
    raw = json.dumps(value, sort_keys=True, indent=2, allow_nan=False).encode() + b'\n'
    assert len(raw) <= 262144
    with path.open('xb') as output:
        output.write(raw)
        output.flush()
        os.fsync(output.fileno())
    assert read(path)[0] == raw
    return hashlib.sha256(raw).hexdigest()


# Read JSON only after its exact external identity has been checked when supplied.
def value(path, expected=None):
    raw, item = read(path)
    if expected is not None:
        assert item['sha256'] == expected
    return json.loads(raw)


# Retain complete unique-destination mount records while allowing only their list representation order to differ.
def mounts(row):
    items = row['Mounts']
    assert len(items) == len({i['Destination'] for i in items}) == 2
    return {i['Destination']: i for i in items}


# Validate the exact stopped tiny runtime and independently refreshed full inspect identity.
def runtime(cid):
    stdout, stderr = REVIEW / 'fresh-inspect.json', REVIEW / 'fresh-inspect.stderr'
    environment = dict(os.environ)
    for key in ('DOCKER_HOST', 'DOCKER_CONTEXT', 'DOCKER_TLS_VERIFY', 'DOCKER_CERT_PATH'):
        environment.pop(key, None)
    with stdout.open('xb') as out, stderr.open('xb') as error:
        process = subprocess.Popen(['/usr/bin/docker', '--host', 'unix:///var/run/docker.sock', 'inspect', '--type=container', cid],
            stdin=subprocess.DEVNULL, stdout=out, stderr=error, env=environment)
        try:
            code = process.wait(timeout=15)
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=1)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=1)
        out.flush()
        error.flush()
        os.fsync(out.fileno())
        os.fsync(error.fileno())
    assert code == 0 and read(stderr)[0] == b''
    created = value(RUN / 'prepare-before.json')
    stopped = value(RUN / 'prepare-after.json')
    fresh = value(stdout)
    assert len(fresh) == 1
    fresh = fresh[0]
    assert created['Id'] == stopped['Id'] == fresh['Id'] == cid and fresh['Image'] == IMAGE
    assert created['State']['Status'] == 'created'
    for row in (created, stopped, fresh):
        host, config = row['HostConfig'], row['Config']
        assert config['User'] == '1000:1000' and host['NetworkMode'] == 'none' and host['ReadonlyRootfs'] is True
        assert host['Memory'] == host['MemorySwap'] == 2147483648 and host['NanoCpus'] == 1000000000
        assert host['PidsLimit'] == 32 and host['Tmpfs'] == {'/tmp': 'rw,size=64m'}
        assert host['LogConfig']['Type'] == 'none' and config['Healthcheck']['Test'] == ['NONE']
        assert host['CapDrop'] == ['ALL'] and not host['CapAdd'] and not host['Devices'] and not host['Privileged']
        assert 'no-new-privileges:true' in host['SecurityOpt']
        by_destination = mounts(row)
        assert set(by_destination) == {'/audit', '/out'}
        for destination, source, writable in (('/audit', SOURCE / 'audit', False), ('/out', RUN / 'output', True)):
            mount = by_destination[destination]
            assert mount['Type'] == 'bind' and mount['Source'] == str(source) and mount['RW'] is writable
    assert mounts(created) == mounts(stopped) == mounts(fresh)
    for row in (stopped, fresh):
        assert row['State']['Running'] is False and row['State']['ExitCode'] == 0 and row['State']['OOMKilled'] is False
    for key in ('Config', 'Path', 'Args', 'Image', 'Name'):
        assert created[key] == stopped[key] == fresh[key]
    before_host, after_host = dict(created['HostConfig']), dict(stopped['HostConfig'])
    if before_host.get('OomKillDisable') is False and after_host.get('OomKillDisable') is None:
        before_host['OomKillDisable'] = None
    assert before_host == after_host == fresh['HostConfig']
    assert {k: v for k, v in stopped.items() if k != 'Mounts'} == {k: v for k, v in fresh.items() if k != 'Mounts'}
    return {'cid': cid, 'fresh_inspect_sha256': read(stdout)[1]['sha256'],
        'created_stopped_raw_mount_order_equal': created['Mounts'] == stopped['Mounts'],
        'stopped_fresh_raw_mount_order_equal': stopped['Mounts'] == fresh['Mounts']}


# Record each complete run file twice and page its physical manifest below the ordinary file cap.
def inventory():
    names = sorted(p.relative_to(RUN).as_posix() for p in RUN.rglob('*') if not p.is_dir())
    assert 1 <= len(names) <= 4096
    records, inodes = {}, set()
    for name in names:
        path = RUN / name
        raw, first = read(path)
        assert read(path)[1] == first
        inode = (first['physical']['st_dev'], first['physical']['st_ino'])
        assert inode not in inodes
        inodes.add(inode)
        records[name] = first
    assert names == sorted(p.relative_to(RUN).as_posix() for p in RUN.rglob('*') if not p.is_dir())
    pages = []
    items = list(records.items())
    for start in range(0, len(items), 64):
        name = 'run-manifest-' + str(start // 64).zfill(3) + '.json'
        pages.append({'path': name, 'sha256': save(REVIEW / name, dict(items[start:start + 64]))})
    return {'files': len(names), 'bytes': sum(r['bytes'] for r in records.values()), 'pages': pages, 'two_full_reads': True}


# Independently check all new outcomes, actual children, immutable sources/caller/admission and stopped runtime.
def main(arguments):
    if len(arguments) != 4 or arguments[0] != '--review-context-parity':
        raise SystemExit('SOURCE_ONLY_NO_CONTEXT_REVIEW_ROUTE')
    self_sha, book_sha, admission_sha = arguments[1:]
    assert os.getuid() == 1000 and read(Path(__file__))[1]['sha256'] == self_sha and not os.path.lexists(REVIEW)
    resource.setrlimit(resource.RLIMIT_FSIZE, (262144, 262144))
    REVIEW.mkdir(mode=0o700)
    book = value(SOURCE / 'source-book.json', book_sha)
    admission = value(SOURCE / 'admission/admission.json', admission_sha)
    terminal = value(RUN / 'terminal.json')
    assert terminal['source_book_sha256'] == book_sha and terminal['admission_sha256'] == admission_sha and terminal['genuine_acceptance'] is False
    assert admission['source_book_sha256'] == book_sha and admission['genuine_execution_authorized'] is False
    before, after = value(RUN / 'source-before.json'), value(RUN / 'source-after.json')
    assert before == after and set(before) == set(book['files'])
    for name, item in book['files'].items():
        current = read(SOURCE / name)[1]
        assert current == before[name] and item == {k: current[k] for k in ('sha256', 'bytes')}
    caller = value(SOURCE / 'owner/caller-invocation.json')
    assert caller['owner_sha256'] == book['files']['owner/context-owner.py']['sha256'] == admission['owner_sha256']
    assert caller['caller_sha256'] == book['files']['owner/caller.py']['sha256']
    assert caller['argv'] == ['--admitted-context-parity', admission_sha, admission['owner_sha256'], book_sha]
    expected = value(SOURCE / 'audit/cases.json')
    assert len(REFUSALS) == 54 and POSITIVE.isdisjoint(REFUSALS)
    assert POSITIVE | set(REFUSALS) == {n for group in expected.values() for n in group}
    native_items = [item for item in admission['host_evidence'] if Path(item['path']).name == 'native-observation.json']
    assert len(native_items) == 1 and Path(native_items[0]['path']).parent == SOURCE / 'admission'
    native = value(Path(native_items[0]['path']), native_items[0]['sha256'])
    origins = {}
    for name in book['files']:
        if name.startswith('audit/app/') and name.endswith('.py'):
            relative = name.removeprefix('audit/app/').removesuffix('.py')
            module_name = relative.removesuffix('/__init__').replace('/', '.')
            origins[module_name] = '/audit/app/' + name.removeprefix('audit/app/')
    assert len(origins) == 11
    modes = {'context': ('reader', 'context'), 'preservation': ('preservation',), 'calendar': ('calendar',), 'units': ('binding_units', 'lifecycle_units')}
    outcomes, pids = [], set()
    for mode, groups in modes.items():
        root = RUN / 'output' / mode
        exit_value, result = value(root / 'exit.json'), value(root / 'result.json')
        assert exit_value['exit'] == 0 and exit_value['owned_stop'] is None and exit_value['pid'] not in pids
        assert type(exit_value['pid']) is str and exit_value['pid'].isdecimal()
        pids.add(exit_value['pid'])
        assert read(root / 'stdout.log')[0] == read(root / 'stderr.log')[0] == b''
        assert result['mode'] == mode and result['genuine_acceptance'] is False and result['lifecycle_constructor'] == 'UNRUN'
        assert result['module_origins'] == origins
        assert result['native'] == {'version': '2.5.3', 'path': '/usr/local/lib/python3.12/site-packages/numpy/__init__.py',
            'init_sha256': native['numpy']['init_sha256'], 'threads': {n: '1' for n in (
                'OPENBLAS_NUM_THREADS', 'OMP_NUM_THREADS', 'MKL_NUM_THREADS', 'NUMEXPR_NUM_THREADS', 'VECLIB_MAXIMUM_THREADS', 'BLIS_NUM_THREADS')}}
        assert [r['case'] for r in result['cases']] == [n for g in groups for n in expected[g]]
        for row in result['cases']:
            assert row['status'] == ('PASS' if row['case'] in POSITIVE else 'EXPECTED_REFUSAL')
            assert row['scope'] == expected_scope(row['case'])
            if row['case'] in REFUSALS:
                kind, reason = REFUSALS[row['case']]
                assert row['exception'] == kind and type(row['reason']) is str and row['reason']
                if reason is not None:
                    assert row['reason'] == reason
        outcomes.extend(result['cases'])
    assert len(outcomes) == len({r['case'] for r in outcomes}) == 73 and len(POSITIVE) == 19
    assert len(pids) == 4 and value(RUN / 'output/comparison.json')['cases'] == 73
    inspection = runtime(terminal['cid'])
    manifest = inventory()
    # The independent inventory is at-rest preservation evidence, not provenance of each injected fixture.
    proof = {'schema': 'capacity-context-parity-independent/1', 'scope': 'SYNTHETIC73_ONLY_NOT_GENUINE_OR_GENERAL_ORIGINAL_PARITY',
        'source_book_sha256': book_sha, 'admission_sha256': admission_sha, 'verifier_sha256': self_sha,
        'source_files': len(before), 'source_physical_bookends_equal': True, 'runtime': inspection,
        'actual_children': sorted(pids), 'cases': outcomes, 'positive': 19, 'expected_refusals': 54,
        'run_manifest': manifest, 'genuine_acceptance': False, 'publication': 'CLOSED',
        'refusal_reason_scope': '51_EXACT_REASONS_AND_3_OS_PATH_DEPENDENT_EXCEPTION_CLASSES',
        'crash_timeout_force_stop_transport_loss': 'UNEXERCISED_UNLESS_SEPARATE_ACTUAL_EVIDENCE'}
    proof_sha = save(REVIEW / 'proof.json', proof)
    print(json.dumps({'proof_sha256': proof_sha, 'files': manifest['files'], 'cases': 73, 'genuine_acceptance': False}, sort_keys=True))


if __name__ == '__main__':
    main(sys.argv[1:])
