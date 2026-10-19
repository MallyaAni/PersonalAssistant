"""Finite PRIVATE marker/latch namespace; SQLite/native rename capacity is separate.

All extents and names exist before birth. Dynamic operation paths are logical
identities, never new filesystem names. PENDING bodies are unreadable forever;
metadata recovery may publish only an EMPTY original result slot after commit.
"""
from contextlib import contextmanager
from copy import deepcopy
from datetime import date
import fcntl
from hashlib import sha256
import os
from pathlib import Path
import stat

from backend.market import historical_physical_checkpoint as physical
from backend.market import historical_timing_packet as packet

SCHEMA = 'synthetic-reserved-protocol-metadata/1'
ROLES = ('reserved-native-save.json', 'reservation.json', 'prepared.json', 'result.json')
PHASES = ('BIRTH', 'NIGHTLY_CLOSE', 'PREPARE', 'DECISION_FROZEN', 'SUBMISSION_CAPTURED', 'OUTCOME_COMMITTED')
SOURCES = ('historical_reserved_protocol.py', 'historical_packet_store.py',
    'historical_reserved_native_io.py', 'historical_raw_nightly.py',
    'historical_reserved_cycle_stages.py', 'historical_reserved_cycle_final.py',
    'historical_conditional_cycle.py', 'historical_raw_cycle.py', 'historical_conditional_nightly.py')


# Authenticate finite regular source text through one held descriptor before using its hash.
def source_sha(path):
    physical._require(path.is_absolute() and path.resolve() == path and path.suffix == '.py',
                      'Canonical metadata source required')
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        before = os.fstat(descriptor)
        physical._require(stat.S_ISREG(before.st_mode) and before.st_size <= physical.META,
                          'Bounded regular metadata source required')
        raw = os.read(descriptor, physical.META + 1)
        physical._require(len(raw) == before.st_size
            and all(getattr(before, key) == getattr(os.fstat(descriptor), key)
                == getattr(path.lstat(), key) for key in
                ('st_dev', 'st_ino', 'st_size', 'st_mtime_ns', 'st_ctime_ns')),
            'Metadata source changed while reading')
        return sha256(raw).hexdigest()
    finally:
        os.close(descriptor)


# Preserve the exact original allocation and namespace identity, excluding mutable times.
def inode(path):
    info = path.lstat()
    physical._require(not path.is_symlink() and info.st_uid == os.getuid()
        and (stat.S_ISDIR(info.st_mode) if path.is_dir() else stat.S_ISREG(info.st_mode))
        and (path.is_dir() or info.st_nlink == 1)
        and stat.S_IMODE(info.st_mode) == (0o700 if path.is_dir() else 0o600),
        'Original private metadata inode required')
    return [str(getattr(info, name)) for name in ('st_dev', 'st_ino', 'st_size', 'st_blocks')]


# Fully initialize extents before arm, avoiding unwritten allocation conversions later.
def allocate(path, size):
    physical._allocate(path, size)
    descriptor = os.open(path, os.O_RDWR | os.O_NOFOLLOW)
    try:
        before = inode(path)
        physical._require(before == [str(getattr(os.fstat(descriptor), key)) for key in
            ('st_dev', 'st_ino', 'st_size', 'st_blocks')], 'Original held metadata allocation required')
        for offset in range(0, size, 4096):
            physical._require(os.pwrite(descriptor, bytes(min(4096, size - offset)), offset)
                              == min(4096, size - offset), 'Short metadata initialization')
        os.fsync(descriptor)
        os.lseek(descriptor, 0, os.SEEK_SET)
        for offset in range(0, size, 4096):
            physical._require(os.read(descriptor, min(4096, size - offset)) == bytes(min(4096, size - offset)),
                              'Complete initialized metadata readback required')
        after = inode(path)
        physical._require(after[:3] == before[:3] and int(after[3]) * 512 >= size
            and after == [str(getattr(os.fstat(descriptor), key)) for key in
                ('st_dev', 'st_ino', 'st_size', 'st_blocks')],
            'Metadata inode/size changed during initialization')
    finally:
        os.close(descriptor)


# Allocate one source-bound finite namespace before any account state or Store stage exists.
def reserve(store, account, *, source_paths, latch_sessions, slots=8):
    account = Path(account)
    physical._require(store.blob_reservation is not None
        and store.snapshot()['head'] is None and store.snapshot()['sequence'] == 0
        and account.resolve().is_relative_to(store.root.resolve())
        and not os.path.lexists(account / 'paper/state.json') and type(slots) is int and 1 <= slots <= 8
        and type(latch_sessions) is list and 1 <= len(latch_sessions) <= 8
        and len(set(latch_sessions)) == len(latch_sessions)
        and all(date.fromisoformat(day).isoformat() == day for day in latch_sessions),
        'Finite original metadata plan must precede birth')
    root = store.root / 'reserved-protocol'
    root.mkdir(mode=0o700)
    physical._require(type(source_paths) is list and 1 <= len(source_paths) <= 4
        and len(set(map(str, source_paths))) == len(source_paths), 'Finite distinct synthetic executor sources required')
    executors = list(map(str, source_paths))
    physical._require(all(Path(path).is_relative_to(Path(__file__).parents[1] / 'tests') for path in executors),
                      'Only explicitly synthetic fixture executor sources admitted')
    sources = {str(path): source_sha(path) for path in
        [*(Path(__file__).parent / name for name in SOURCES), *map(Path, executors)]}
    names = ['header', 'control', 'lock'] + [str(i) + '-' + str(j) for i in range(slots) for j in range(4)]
    names += ['latch-' + str(i) for i in range(len(latch_sessions))]
    for name in names:
        allocate(root / name, 4096 if name == 'lock' else physical.META)
    original = {name: inode(root / name) for name in names}
    original['.'] = inode(root)
    header = {'schema': SCHEMA, 'identity': store.identity, 'account': str(account),
        'source_sha256': sources, 'executor_sources': executors, 'slots': slots, 'latch_sessions': latch_sessions,
        'inodes': original, 'payload_cap': physical.META}
    physical._fixed_write(root / 'header', header)
    physical._fixed_write(root / 'control', {'operations': [], 'latches': {}, 'pending': None, 'failed': False})
    physical._sync(root)
    physical._sync(root.parent)
    return MetadataSlots(root, identity=store.identity)


# Keep exact original operation claims and initialized bodies without adopting interrupted writes.
class MetadataSlots:
    # Reopen only the original fixed header and source/allocation plan.
    def __init__(self, root, *, identity):
        self.root, self.identity = Path(root), physical._digest(identity)
        self.header = physical._fixed_read(self.root / 'header')
        self.header_sha256 = sha256(physical._encoded(self.header)).hexdigest()
        self.fault = None
        self._guard()

    # Bind the Store mode to the immutable original pool, account and source header.
    @property
    def binding(self):
        return {'schema': SCHEMA, 'identity': self.identity, 'root': str(self.root),
                'account': self.header['account'], 'header_sha256': self.header_sha256}

    # Reject removed/replaced/resized/reallocated files, names or participating source bytes.
    def _guard(self):
        header = self.header
        physical._require(type(header) is dict and set(header) == {'schema', 'identity', 'account',
            'source_sha256', 'executor_sources', 'slots', 'latch_sessions', 'inodes', 'payload_cap'}
            and header['schema'] == SCHEMA and header['identity'] == self.identity
            and physical._fixed_read(self.root / 'header') == header
            and type(header['slots']) is int and 1 <= header['slots'] <= 8
            and type(header['latch_sessions']) is list and 1 <= len(header['latch_sessions']) <= 8
            and len(set(header['latch_sessions'])) == len(header['latch_sessions'])
            and all(date.fromisoformat(day).isoformat() == day for day in header['latch_sessions'])
            and type(header['executor_sources']) is list and 1 <= len(header['executor_sources']) <= 4
            and len(set(header['executor_sources'])) == len(header['executor_sources'])
            and all(Path(path).is_relative_to(Path(__file__).parents[1] / 'tests')
                    for path in header['executor_sources'])
            and header['payload_cap'] == physical.META and self.root.name == 'reserved-protocol'
            and self.root.resolve() == self.root
            and Path(header['account']).resolve() == Path(header['account'])
            and Path(header['account']).is_relative_to(self.root.parent), 'Original metadata header required')
        expected = {'header', 'control', 'lock'} | {str(i) + '-' + str(j)
            for i in range(header['slots']) for j in range(4)}
        expected |= {'latch-' + str(i) for i in range(len(header['latch_sessions']))}
        physical._require(set(header['inodes']) == expected | {'.'} and set(header['source_sha256'])
            == {str(Path(__file__).parent / name) for name in SOURCES} | set(header['executor_sources']),
            'Complete original metadata/source plan required')
        with os.scandir(self.root) as entries:
            actual = set()
            for item in entries:
                physical._require(len(actual) < 67, 'Metadata namespace bound')
                actual.add(item.name)
        physical._require(actual == expected, 'Original fixed metadata namespace required')
        for name, expected_inode in header['inodes'].items():
            physical._require(type(expected_inode) is list and len(expected_inode) == 4
                and all(type(item) is str and item.isdecimal() for item in expected_inode)
                and (name == '.' or int(expected_inode[2]) == (4096 if name == 'lock' else physical.META)
                     and int(expected_inode[3]) * 512 >= int(expected_inode[2]))
                and inode(self.root if name == '.' else self.root / name) == expected_inode,
                              'Original initialized metadata allocation changed')
        physical._require(sum(int(row[3]) * 512 for row in header['inodes'].values()) <= 16 * 1024**2,
                          'Finite initialized metadata physical budget exceeded before arm')
        for name, expected_sha in header['source_sha256'].items():
            physical._require(source_sha(Path(name)) == physical._digest(expected_sha), 'Metadata source changed')

    # Serialize claims and writes while allowing authenticated original reads after uncertainty.
    @contextmanager
    def _locked(self, *, write=False):
        descriptor = os.open(self.root / 'lock', os.O_RDWR | os.O_NOFOLLOW)
        try:
            fcntl.flock(descriptor, (fcntl.LOCK_EX if write else fcntl.LOCK_SH) | fcntl.LOCK_NB)
            self._guard()
            physical._require(inode(self.root / 'lock') == [str(getattr(os.fstat(descriptor), key))
                for key in ('st_dev', 'st_ino', 'st_size', 'st_blocks')], 'Original held metadata lock required')
            yield
            self._guard()
            physical._require(inode(self.root / 'lock') == [str(getattr(os.fstat(descriptor), key))
                for key in ('st_dev', 'st_ino', 'st_size', 'st_blocks')], 'Held metadata lock changed')
        finally:
            os.close(descriptor)

    # Read only the finite persistent control graph with no pending-body adoption.
    def _control(self):
        value = physical._fixed_read(self.root / 'control')
        physical._require(set(value) == {'operations', 'latches', 'pending', 'failed'}
            and type(value['operations']) is list and len(value['operations']) <= self.header['slots']
            and type(value['latches']) is dict and type(value['failed']) is bool, 'Exact metadata control required')
        physical._require(all(type(slot) is int for slot in value['latches'].values())
            and (value['pending'] is None or type(value['pending']) is dict
                 and set(value['pending']) == {'slot', 'role'}
                 and type(value['pending']['slot']) is int and type(value['pending']['role']) is str),
            'Exact metadata pending/latch field types required')
        tokens, latches, pending = set(), {}, []
        for slot, row in enumerate(value['operations']):
            physical._require(type(row) is dict and set(row) == {'operation', 'phase', 'head', 'inputs',
                'latch_session', 'records', 'status', 'result'} and row['phase'] in PHASES
                and physical._digest(row['operation']) not in tokens and type(row['records']) is dict,
                'Original finite metadata operation required')
            tokens.add(row['operation'])
            physical._digest(row['inputs'])
            if row['head'] is not None:
                physical._digest(row['head'])
            if row['latch_session'] is not None:
                physical._require(row['phase'] == 'SUBMISSION_CAPTURED'
                    and row['latch_session'] in self.header['latch_sessions']
                    and row['latch_session'] not in latches, 'Original unique latch ownership required')
                latches[row['latch_session']] = slot
            physical._require(set(row['records']) <= set(ROLES) | ({'latch'} if row['latch_session'] else set()),
                              'Original finite metadata roles required')
            for role, record in row['records'].items():
                physical._require(type(record) is dict and set(record) == {'status', 'bytes', 'sha256'}
                    and record['status'] in ('COMPLETE', 'PENDING') and type(record['bytes']) is int
                    and 0 <= record['bytes'] <= physical.META, 'Original metadata record required')
                physical._digest(record['sha256'])
                if record['status'] == 'PENDING':
                    pending.append({'slot': slot, 'role': role})
            physical._require(row['status'] in ('OPEN', 'COMPLETE')
                and (row['result'] is None if row['status'] == 'OPEN' else
                     physical._digest(row['result']) == row['result'])
                and (row['status'] == 'COMPLETE') ==
                    (row['records'].get('result.json', {}).get('status') == 'COMPLETE'),
                'Original metadata operation completion required')
        physical._require(value['latches'] == latches and pending == ([] if value['pending'] is None
            else [value['pending']]), 'Original metadata pending/latch crosslinks required')
        return value

    # Refuse uncertain effects and any effect-bearing reuse of a completed original operation.
    def check_effects(self, directory=None):
        with self._locked(write=True):
            control = self._control()
            try:
                physical._require(not control['failed'] and control['pending'] is None,
                                  'Uncertain metadata namespace; no later effects')
                if directory is not None:
                    found = self._find(control, directory)
                    physical._require(found is not None and found[1]['status'] == 'OPEN',
                                      'Completed metadata operation has no later effects or evidence')
                for slot, row in enumerate(control['operations']):
                    for role in row['records']:
                        self._read(control, slot, row, role)
            except BaseException:
                control['failed'] = True
                physical._fixed_write(self.root / 'control', control)
                raise

    # Retain an explicit protocol-boundary interruption point without a native callback.
    def _point(self, point):
        if self.fault is not None:
            self.fault(point)

    # Hash an original logical path without creating its directory or file.
    def _token(self, directory):
        directory = Path(directory)
        account = Path(self.header['account'])
        physical._require(directory.is_absolute() and '..' not in directory.parts
            and directory.is_relative_to(account / 'operations'), 'Bound logical metadata operation required')
        return sha256(str(directory).encode()).hexdigest()

    # Locate an existing original operation, never implicitly claiming an absent one.
    def _find(self, control, directory):
        token = self._token(directory)
        found = [(index, row) for index, row in enumerate(control['operations']) if row['operation'] == token]
        physical._require(len(found) <= 1, 'Duplicate metadata operation')
        return found[0] if found else None

    # Distinguish an explicit attempted operation from precreated empty filesystem slots.
    def claimed(self, directory):
        with self._locked():
            return self._find(self._control(), directory) is not None

    # Retain caught claim uncertainty before any later native work can use this namespace.
    def claim(self, directory, *, phase, head, inputs, latch_session=None):
        try:
            return self._claim(directory, phase=phase, head=head, inputs=inputs, latch_session=latch_session)
        except BaseException:
            with self._locked(write=True):
                control = self._control()
                control['failed'] = True
                physical._fixed_write(self.root / 'control', control)
            raise

    # Persist exact phase/head/input/latch ownership in an original preallocated control cell.
    def _claim(self, directory, *, phase, head, inputs, latch_session=None):
        physical._require(phase in PHASES, 'Declared metadata phase required')
        if head is not None:
            physical._digest(head)
        physical._digest(inputs)
        with self._locked(write=True):
            control = self._control()
            physical._require(not control['failed'] and control['pending'] is None, 'Metadata claim uncertain')
            wanted = {'operation': self._token(directory), 'phase': phase, 'head': head,
                      'inputs': inputs, 'latch_session': latch_session, 'records': {},
                      'status': 'OPEN', 'result': None}
            found = self._find(control, directory)
            if found is not None:
                physical._require(found[1] == {**wanted, **{key: found[1][key]
                    for key in ('records', 'status', 'result')}}, 'Conflicting metadata claim')
                return self._reference(found[0], found[1])
            physical._require(len(control['operations']) < self.header['slots'], 'Metadata operation slots exhausted')
            if latch_session is not None:
                physical._require(phase == 'SUBMISSION_CAPTURED'
                    and latch_session in self.header['latch_sessions']
                    and latch_session not in control['latches'], 'Original pre-effect latch slot required')
                control['latches'][latch_session] = len(control['operations'])
            control['operations'].append(wanted)
            physical._fixed_write(self.root / 'control', control)
            self._point('metadata_claimed')
            return self._reference(len(control['operations']) - 1, wanted)

    # Return the typed immutable claim carried by original native/CAS evidence.
    def _reference(self, slot, row):
        return {'schema': SCHEMA, 'pool': self.binding, 'slot': slot,
                **{key: row[key] for key in ('operation', 'phase', 'head', 'inputs', 'latch_session')}}

    # Authenticate the original claim without changing control, even after a later refused write.
    def reference(self, directory):
        with self._locked():
            found = self._find(self._control(), directory)
            physical._require(found is not None, 'Original metadata claim missing')
            return self._reference(*found)

    # Map only the four fixed roles or the preclaimed session latch to original body inodes.
    def _body(self, slot, row, role):
        if role in ROLES:
            return self.root / (str(slot) + '-' + str(ROLES.index(role)))
        physical._require(role == 'latch' and row['latch_session'] in self.header['latch_sessions'],
                          'Original metadata role required')
        return self.root / ('latch-' + str(self.header['latch_sessions'].index(row['latch_session'])))

    # Seal an operation only with its exact phase-specific original result marker.
    def _result(self, row, raw):
        value = packet._decode(raw)
        nightly = row['phase'] in ('BIRTH', 'NIGHTLY_CLOSE')
        schema = ('standalone-current-raw-nightly-lifecycle/1' if nightly else
                  'synthetic-reserved-cycle-final/1' if row['phase'] == 'OUTCOME_COMMITTED' else
                  'synthetic-reserved-cycle-stages/1')
        physical._require(type(value) is dict and set(value) ==
            ({'schema', 'receipt'} if nightly else {'schema', 'receipt', 'head', 'reservation_sha256'})
            and value['schema'] == schema, 'Original phase-specific metadata result required')
        if not nightly:
            physical._digest(value['head'])
            physical._digest(value['reservation_sha256'])
        return physical._digest(value['receipt'])

    # Read exact unpadded original bytes; an EMPTY slot is absent and PENDING never readable.
    def _read(self, control, slot, row, role):
        record = row['records'].get(role)
        if record is None:
            raise FileNotFoundError(role)
        physical._require(record['status'] == 'COMPLETE'
            and not (control['pending'] is not None and control['pending']['slot'] == slot
                     and control['pending']['role'] == role), 'PENDING metadata body; never adopt')
        path = self._body(slot, row, role)
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        try:
            physical._require(inode(path) == [str(getattr(os.fstat(descriptor), key)) for key in
                ('st_dev', 'st_ino', 'st_size', 'st_blocks')], 'Metadata body replaced before read')
            raw = os.read(descriptor, physical.META + 1)
            physical._require(len(raw) == physical.META and 0 <= record['bytes'] <= physical.META
                and raw[record['bytes']:] == bytes(physical.META - record['bytes'])
                and sha256(raw[:record['bytes']]).hexdigest() == record['sha256'], 'Original metadata body differs')
            result = raw[:record['bytes']]
            if role == 'result.json':
                physical._require(row['status'] == 'COMPLETE' and self._result(row, result) == row['result'],
                                  'Original metadata result seal differs')
            return result
        finally:
            os.close(descriptor)

    # Read only a previously completed role from its original operation claim.
    def read(self, directory, role):
        with self._locked():
            control = self._control()
            found = self._find(control, directory)
            if found is None:
                raise FileNotFoundError(str(directory))
            return self._read(control, *found, role)

    # Charge PENDING before touching a body; uncertainty cannot grant retry or later effects.
    def write_once(self, directory, role, raw):
        with self._locked(write=True):
            control = self._control()
            try:
                physical._require(not control['failed'] and control['pending'] is None,
                                  'Metadata write uncertain')
                physical._require(type(raw) is bytes and len(raw) <= physical.META, 'Original metadata payload cap')
                found = self._find(control, directory)
                physical._require(found is not None, 'Metadata write requires original claim')
                slot, row = found
                path = self._body(slot, row, role)
                if role in row['records']:
                    physical._require(self._read(control, slot, row, role) == raw, 'Original metadata bytes conflict')
                    return
                physical._require(row['status'] == 'OPEN', 'Completed metadata operation cannot extend')
                result = self._result(row, raw) if role == 'result.json' else None
                control['pending'] = {'slot': slot, 'role': role}
                row['records'][role] = {'status': 'PENDING', 'bytes': len(raw), 'sha256': sha256(raw).hexdigest()}
                physical._fixed_write(self.root / 'control', control)
                self._point('metadata_pending_' + role)
                descriptor = os.open(path, os.O_RDWR | os.O_NOFOLLOW)
                try:
                    physical._require(inode(path) == [str(getattr(os.fstat(descriptor), key)) for key in
                        ('st_dev', 'st_ino', 'st_size', 'st_blocks')], 'Metadata body replaced before write')
                    body = raw + bytes(physical.META - len(raw))
                    physical._require(os.pwrite(descriptor, body, 0) == len(body), 'Short metadata body write')
                    os.fsync(descriptor)
                finally:
                    os.close(descriptor)
                self._point('metadata_body_written_' + role)
                self._guard()
                row['records'][role]['status'] = 'COMPLETE'
                if role == 'result.json':
                    row['status'], row['result'] = 'COMPLETE', result
                control['pending'] = None
                physical._fixed_write(self.root / 'control', control)
                self._point('metadata_completed_' + role)
            except BaseException:
                control['failed'] = True
                physical._fixed_write(self.root / 'control', control)
                raise

    # Read semantic latch absence or exact original published bytes from a fixed session slot.
    def read_latch(self, session):
        with self._locked():
            control = self._control()
            physical._require(session in self.header['latch_sessions'], 'Latch outside finite metadata plan')
            slot = control['latches'].get(session)
            if slot is None or 'latch' not in control['operations'][slot]['records']:
                return None
            return self._read(control, slot, control['operations'][slot], 'latch')


# Require the persisted original Store namespace rather than inferring mode from existing paths.
def pool(nightly):
    value = nightly.store.metadata_reservation
    if value is not None:
        physical._require(type(value) is MetadataSlots and value.header['account'] == str(nightly.root),
                          'Exact original metadata workspace required')
    return value


# Preserve ordinary directory-attempt semantics while bound mode uses explicit immutable claims.
def exists(nightly, directory):
    value = pool(nightly)
    return Path(directory).exists() if value is None else value.claimed(directory)


# Preserve exact file absence checks separately from attempted-operation claim state.
def marker_exists(nightly, path):
    value = pool(nightly)
    if value is None:
        return Path(path).exists()
    try:
        value.read(path.parent, path.name)
    except FileNotFoundError:
        return False
    return True


# Claim fixed slots instead of allocating hash-derived operation directories after birth.
def create(nightly, directory, *, phase, inputs, latch_session=None):
    value = pool(nightly)
    if value is None:
        directory.mkdir(mode=0o700)
        physical._sync(directory.parent)
        return None
    return value.claim(directory, phase=phase, head=nightly.expected_head,
                       inputs=inputs, latch_session=latch_session)


# Return exact marker bytes under the original path contract or the separate typed namespace.
def read(nightly, path, legacy):
    value = pool(nightly)
    return legacy.physical(path) if value is None else value.read(path.parent, path.name)


# Publish only one original role using initialized inodes when explicit metadata mode is bound.
def write(nightly, path, raw, legacy):
    value = pool(nightly)
    if value is None:
        return legacy.write_once(path, raw)
    return value.write_once(path.parent, path.name, raw)


# Bind the finite marker claim into original native evidence and CAS operation identity.
def reference(nightly, directory):
    value = pool(nightly)
    return None if value is None else value.reference(directory)


# Match a published reservation to its exact pre-effect metadata claim and original source header.
def verify(nightly, directory, *, phase, head, inputs):
    value = reference(nightly, directory)
    if value is not None:
        physical._require(value['phase'] == phase and value['head'] == head and value['inputs'] == inputs,
                          'Original metadata phase/head/input claim differs')
