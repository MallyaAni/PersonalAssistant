"""UNRUN calendar comparison and explicit injected binding/phase-holder UNIT controls."""
import copy
import gzip
import hashlib
import json
import os
import types
from contextlib import contextmanager
from pathlib import Path

from fixtures import AUDIT, encoded, outcome, sha, write


# Restore every declared unit injection even if its expected observation fails.
@contextmanager
def patch(owner, **values):
    before = {name: getattr(owner, name) for name in values}
    try:
        for name, value in values.items():
            setattr(owner, name, value)
        yield
    finally:
        for name, value in before.items():
            setattr(owner, name, value)


# Compare actual reviewed-session data and NumPy arithmetic without importing original calendar dependencies.
def calendars(env, target):
    rows = []
    calendar = env.calendar
    paths = (calendar.HOLIDAYS_PATH, calendar.HISTORICAL_SESSIONS_PATH, calendar.EARLY_CLOSES_PATH)
    pins = json.loads((AUDIT / 'pins.json').read_bytes())
    outcome(rows, 'calendar-source-and-parent-data-origins', lambda: all(p.parent == Path(calendar.__file__).parent / 'data' and
        sha(p.read_bytes()) == pins[str(p.relative_to(AUDIT))]['sha256'] for p in paths))
    reference_path = AUDIT / 'reference/backend/market/calendar.py'
    code = compile(reference_path.read_bytes(), str(reference_path), 'exec', dont_inherit=True)
    selected = next(c for c in code.co_consts if isinstance(c, types.CodeType) and c.co_name == 'reviewed_sessions')
    namespace = {'__name__': 'ISOLATED_SYNTHETIC_CALENDAR_REFERENCE', '__file__': str(reference_path),
        'np': env.np, 'json': json, 'HISTORICAL_SESSIONS_PATH': AUDIT / 'reference/backend/market/data/nyse_historical_sessions.json',
        'HOLIDAYS_PATH': AUDIT / 'reference/backend/market/data/nyse_holidays.json'}
    original = types.FunctionType(selected, namespace)
    years, days = calendar.reviewed_sessions()
    old_years, old_days = original()
    outcome(rows, 'calendar-reviewed-years-and-closures-parity', lambda: sorted(years) == sorted(old_years) and
        list(map(str, days.holidays)) == list(map(str, old_days.holidays)), scope='ISOLATED_REVIEWED_SESSIONS_REFERENCE_REAL_PUBLIC_DATA')
    dates = env.np.arange(env.np.datetime64('2019-02-25'), env.np.datetime64('2019-03-09'))
    outcome(rows, 'calendar-boundary-session-sequence-parity', lambda: list(map(str, dates[env.np.is_busday(dates, busdaycal=days)])),
        reference=lambda: list(map(str, dates[env.np.is_busday(dates, busdaycal=old_days)])), scope='BOUNDED_DATE_REFERENCE_PARITY_NOT_FULL_ORIGINAL_PROFILE')
    root = Path(calendar.__file__).resolve().parents[2]
    sources = {str(p.relative_to(root)): sha(p.read_bytes()) for p in paths}
    archives = types.SimpleNamespace(source_root=root, sources=sources, completion={'first': '2019-03-01', 'through': '2019-03-04',
        'sessions': [{'session': '2019-03-01'}, {'session': '2019-03-04'}]})
    # This tiny private-profile object is explicit synthetic metadata, never a full context admission.
    accepted = env.lifecycle.admissions.calendar_admission(archives, 'complete-private-v10')
    assert accepted['sessions'] == 2 and accepted['first'] == '2019-03-01' and accepted['through'] == '2019-03-04'
    archives.source_root = target
    outcome(rows, 'calendar-root-mismatch-refusal', lambda: env.lifecycle.admissions.calendar_admission(archives, 'complete-private-v10'),
        refusal=('ValueError', 'CAPACITY_CALENDAR_IMPORT_ROOT_REQUIRED'), scope='SYNTHETIC_CALENDAR_METADATA_ONLY')
    archives.source_root = root
    sources[next(iter(sources))] = '0' * 64
    outcome(rows, 'calendar-data-hash-refusal', lambda: env.lifecycle.admissions.calendar_admission(archives, 'complete-private-v10'),
        refusal=('ValueError', 'Pinned stream input bytes differ'), scope='SYNTHETIC_CALENDAR_METADATA_ONLY')
    return rows


# Decode authenticated full-map metadata in RAM under its existing exact expansion bound, never a large child file.
def source_map():
    manifest = json.loads((AUDIT / 'map-binding.json').read_bytes())
    raw = (AUDIT / 'source-map.json.gz').read_bytes()
    assert sha(raw) == manifest['gzip_sha256'] and len(raw) == manifest['gzip_bytes'] <= 262144
    import io
    with gzip.GzipFile(fileobj=io.BytesIO(raw)) as stream:
        expanded = stream.read(manifest['raw_bytes'] + 1)
        assert len(expanded) == manifest['raw_bytes'] == 570874 and stream.read(1) == b''
    assert sha(expanded) == manifest['raw_sha256']
    return json.loads(expanded)


# Exercise only negative wrapper/map/mount boundaries with labelled injected pinned metadata.
def bindings(env):
    rows = []
    module = env.lifecycle
    template = source_map()
    root = Path(module.__file__).resolve().parents[2]
    original = {'profile': 'original-full-27471', 'runtime': '/UNIT/runtime', 'runtime_sha256': 'b' * 64}
    wrapper = {'schema': module.SCHEMA, 'original_invocation': '/UNIT/original', 'original_invocation_sha256': 'a' * 64,
        'source_root': str(root), 'source_host_root': '/UNIT/host', 'source_map': '/UNIT/map', 'source_map_sha256': 'c' * 64,
        'native31': '/UNIT/native', 'native31_sha256': 'd' * 64}
    mutations = (
        ('binding-unit-schema-refusal', 'EXACT_CAPACITY_BINDING_REQUIRED'),
        ('binding-unit-profile-refusal', 'ORIGINAL_FULL_CAPACITY_PROFILE_REQUIRED'),
        ('binding-unit-import-root-refusal', 'ACTUAL_CAPACITY_IMPORT_ROOT_REQUIRED'),
        ('binding-unit-base2446-hash-refusal', 'UNCHANGED_LEGACY2446_MAP_REQUIRED'),
        ('binding-unit-module-set-refusal', 'EXACT_CAPACITY_MODULE_SET_REQUIRED'),
        ('binding-unit-legacy-override-refusal', 'LEGACY_SOURCE_OVERRIDE_FORBIDDEN'),
        ('binding-unit-map-union-refusal', 'EXACT_CAPACITY_MAP_UNION_REQUIRED'))
    for case, reason in mutations:
        binding, value, mapping = copy.deepcopy(wrapper), copy.deepcopy(original), copy.deepcopy(template)
        if case == 'binding-unit-schema-refusal':
            binding['schema'] = 'UNIT_WRONG_SCHEMA'
        elif case == 'binding-unit-profile-refusal':
            value['profile'] = 'UNIT_NON_GENUINE'
        elif case == 'binding-unit-import-root-refusal':
            binding['source_root'] = '/UNIT/not-import-root'
        elif case == 'binding-unit-base2446-hash-refusal':
            mapping['base'][next(iter(mapping['base']))] = '0' * 64
        elif case == 'binding-unit-module-set-refusal':
            mapping['modules'].pop(next(iter(mapping['modules'])))
        elif case == 'binding-unit-legacy-override-refusal':
            name = next(n for n in mapping['modules'] if n in mapping['base'])
            mapping['modules'][name] = '0' * 64
        else:
            mapping['files'].pop(next(iter(mapping['files'])))
        # Inject exact returned metadata only; no wrapper/root/profile positive admission is claimed.
        def pinned(path, expected):
            assert str(path) in ('/UNIT/wrapper', '/UNIT/map', '/UNIT/native')
            return encoded({'/UNIT/wrapper': binding, '/UNIT/map': mapping, '/UNIT/native': {}}[str(path)])
        with patch(module.evidence, pinned=pinned), patch(module.admissions, invocation=lambda *args: value):
            outcome(rows, case, lambda: module.capacity_binding('/UNIT/wrapper', '0' * 64), refusal=('ValueError', reason),
                scope='INJECTED_PINNED_METADATA_NEGATIVE_UNIT_NO_FULLMAP_OR_GENUINE_ADMISSION')
    for case in ('binding-unit-duplicate-mount-destination-refusal', 'binding-unit-writable-root-refusal', 'binding-unit-host-root-mapping-refusal'):
        mounts = [{'Destination': str(root), 'Source': '/UNIT/host', 'Type': 'bind', 'RW': False}]
        if 'duplicate' in case:
            mounts.append(dict(mounts[0]))
            reason = 'UNIQUE_RUNTIME_MOUNT_DESTINATIONS_REQUIRED'
        else:
            mounts[0]['RW' if 'writable' in case else 'Source'] = True if 'writable' in case else '/UNIT/wrong-host'
            reason = 'EXACT_READONLY_CAPACITY_HOST_ROOT_REQUIRED'
        with patch(module.evidence, pinned=lambda *args: encoded([{'Mounts': mounts}])):
            outcome(rows, case, lambda: module.root_admission(wrapper, original), refusal=('ValueError', reason), scope='INJECTED_MOUNT_RECORD_NEGATIVE_UNIT_NOT_ACTUAL_RUNTIME')
    return rows


# Build only an injected phase holder; the genuine constructor and loader never execute.
def holder(env, target):
    module = env.lifecycle
    target.mkdir()
    destination = target / 'candidate'
    destination.mkdir()
    lease = module.CapacityArchiveLeaseV1.__new__(module.CapacityArchiveLeaseV1)
    lease.phase = 'BEFORE'
    lease.proof_parent, lease.destination = target, destination
    keys = ('st_dev', 'st_ino', 'st_mode', 'st_uid')
    lease.parent_identity = tuple(getattr(target.stat(follow_symlinks=False), k) for k in keys)
    lease.destination_identity = tuple(getattr(destination.stat(follow_symlinks=False), k) for k in keys)
    lease.before = {'UNIT_ONLY': {'unicode': 'é😀', 'pairs': [['z', 'a' * 64], ['a', 'b' * 64]]}}
    lease.after = lease.serialized = lease.encoded = lease.loaded = None
    lease.archives = types.SimpleNamespace(unchanged=lambda: None)
    lease._bytes = lambda name: copy.deepcopy(lease.before)
    lease.value = {'physical_sha256': 'c' * 64, 'physical_bytes': 1}
    lease.preserved = {'UNIT_ONLY_NOT_AUTHENTICATED': 'd' * 64}
    lease.binding, lease.source_map = {}, {}
    for name in ('runtime', 'root', 'legacy_source', 'modules', 'packages', 'producer', 'calendar'):
        setattr(lease, name, {'UNIT_ONLY': name})
    return lease


# Advance only the unit holder with explicitly injected tiny byte/source/preservation functions.
def advance(env, lease):
    with patch(env.lifecycle.archives_module, preserved_archives=lambda *args: lease.preserved), patch(env.lifecycle, module_admission=lambda *args: None):
        lease.retain_loaded(object())
        lease.verify_after()
    assert lease.phase == 'AFTER' and lease.before == lease.after and lease.before is not lease.after


# Check actual phase methods and file/sync ordering without constructor, full receipts or crash acceptance.
def phases(env, target):
    rows = []
    module = env.lifecycle
    scope = 'INJECTED_PHASE_HOLDER_UNIT_CTOR_GENUINE_ADMISSIONS_LOADER_UNRUN'
    lease = holder(env, target / 'order')
    advance(env, lease)
    outcome(rows, 'phase-attach-before-after-order', lambda: lease.phase == 'AFTER', scope=scope)
    outcome(rows, 'phase-duplicate-attach-refusal', lambda: lease.retain_loaded(object()), refusal=('ValueError', 'EXACT_LOADED_RETENTION_PHASE_REQUIRED'), scope=scope)
    early = holder(env, target / 'early')
    outcome(rows, 'phase-after-before-attach-refusal', early.verify_after, refusal=('ValueError', 'AFTER_PHASE_ORDER_REQUIRED'), scope=scope)
    outcome(rows, 'phase-serialize-before-after-refusal', early.serialize, refusal=('ValueError', 'COEXISTENCE_ROOTS_REQUIRED'), scope=scope)
    before, after, loaded, archives = lease.before, lease.after, lease.loaded, lease.archives
    raw = lease.serialize()
    outcome(rows, 'phase-complete-JSON-UTF8-retains-both-graphs', lambda: raw == lease.serialized.encode('utf-8') and json.loads(raw)['input_bytes'] == before and
        lease.before is before and lease.after is after and lease.loaded is loaded and lease.archives is archives and before is not after, scope=scope)
    small = holder(env, target / 'small-bound')
    advance(env, small)
    with patch(module, MAX_RESULT_BYTES=1):
        outcome(rows, 'phase-small-injected-result-bound-refusal', small.serialize, refusal=('ValueError', 'CAPACITY_RESULT_BOUND_EXCEEDED'), scope=scope + '_INJECTED_SMALL_BOUND_RESTORED')
    assert small.phase == 'AFTER' and small.before is not None and small.encoded is not None
    outcome(rows, 'phase-persist-before-encode-refusal', early.persist, refusal=('ValueError', 'DURABLE_CANDIDATE_PHASE_REQUIRED'), scope=scope)
    collision = holder(env, target / 'collision')
    advance(env, collision)
    collision.serialize()
    write(collision.destination / 'candidate.json', b'RETAINED_UNIT_COLLISION')
    outcome(rows, 'phase-exclusive-result-collision-refusal', collision.persist, refusal=('FileExistsError', None), scope=scope)
    assert (collision.destination / 'candidate.json').read_bytes() == b'RETAINED_UNIT_COLLISION'
    events = []
    actual_fsync, actual_auth, actual_directory = os.fsync, module.evidence.authenticate_file, module.sync_directory
    # Observe real fsync calls while retaining the real operations and exact byte recheck.
    def syncing(descriptor):
        events.append(('fsync', descriptor))
        return actual_fsync(descriptor)
    # Observe the real file SHA verification between file fsync and directory syncing.
    def authenticating(path, expected):
        events.append(('authenticate', str(path)))
        return actual_auth(path, expected)
    # Retain real held-FD directory identity checks and fsync in destination-then-parent order.
    def directory(path, expected):
        events.append(('directory', str(path)))
        return actual_directory(path, expected)
    with patch(module.os, fsync=syncing), patch(module.evidence, authenticate_file=authenticating), patch(module, sync_directory=directory):
        receipt = lease.persist()
    expected_order = ['fsync', 'authenticate', 'directory', 'fsync', 'directory', 'fsync']
    outcome(rows, 'phase-real-file-directory-parent-sync-order', lambda: [n for n, _ in events] == expected_order and
        [p for n, p in events if n == 'directory'] == [str(lease.destination), str(lease.proof_parent)] and
        receipt['sha256'] == sha(raw) and (lease.destination / 'candidate.json').read_bytes() == raw, scope=scope + '_REAL_IO_NO_CRASH_DURABILITY_CLAIM')
    mismatch = holder(env, target / 'parent-mismatch')
    advance(env, mismatch)
    mismatch.serialize()
    mismatch.parent_identity = (0, 0, 0, 0)
    outcome(rows, 'phase-parent-path-FD-mismatch-refusal', mismatch.persist, refusal=('ValueError', 'OWNED_DURABILITY_DIRECTORY_CHANGED'), scope=scope)
    assert mismatch.phase == 'ENCODED' and (mismatch.destination / 'candidate.json').is_file()
    failed = holder(env, target / 'directory-fail')
    advance(env, failed)
    failed.serialize()
    # Inject a named unit IO failure; this is not a process crash or actual filesystem failure.
    def failure(path, expected):
        raise OSError('INJECTED_UNIT_DIRECTORY_FSYNC_FAILURE')
    with patch(module, sync_directory=failure):
        outcome(rows, 'phase-directory-sync-failure-no-durable-phase', failed.persist, refusal=('OSError', 'INJECTED_UNIT_DIRECTORY_FSYNC_FAILURE'), scope=scope)
    assert failed.phase == 'ENCODED' and failed.before is not None and failed.loaded is not None
    outcome(rows, 'phase-release-before-durability-refusal', failed.release, refusal=('ValueError', 'RELEASE_BEFORE_DURABILITY_FORBIDDEN'), scope=scope)
    retained = lease.destination / 'unit-spool-retained'
    write(retained, b'UNIT_NOT_REAL_SHA_MAP')
    lease.release()
    outcome(rows, 'phase-release-only-own-RAM-refs-files-retained', lambda: lease.phase == 'RELEASED_REFERENCES_ONLY_FILES_RETAINED' and
        all(getattr(lease, n) is None for n in ('loaded', 'before', 'after', 'serialized', 'encoded', 'archives')) and retained.read_bytes() == b'UNIT_NOT_REAL_SHA_MAP' and
        (lease.destination / 'candidate.json').read_bytes() == raw and before is not None and after is not None and archives is not None and loaded is not None, scope=scope)
    outcome(rows, 'phase-public-execute-unconditional-refusal', module.execute, refusal=('RuntimeError', 'SOURCE_ONLY_NO_GENUINE_EXECUTOR_OR_MODEL_STRATEGY'), scope=scope)
    return rows
