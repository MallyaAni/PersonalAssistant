"""Finite PRIVATE native namespace lineage; directory/journal capacity is NOT reserved.

Held directory descriptors and original names prevent accidental parent recreation.
Absolute native Path.replace is unchanged; this is not hostile-race isolation,
filesystem capacity reservation, native adoption, or power-loss admission.
"""
from copy import deepcopy
from hashlib import sha256
import os
from pathlib import Path
import stat

from backend.market import historical_physical_checkpoint as physical
from backend.market import historical_reserved_protocol as protocol
from backend.market import historical_synthetic_native_write as native

SCHEMA = 'synthetic-native-directory-binding/1'
DIRECTORIES = ('.', 'anchors', 'receipts', 'work', 'work/paper', 'work/operations')


# Refuse loosely typed or oversized physical fields before treating them as original identity.
def numbers(value, count):
    physical._require(type(value) is list and len(value) == count
        and all(type(item) is str and 1 <= len(item) <= 32 and item.isdecimal() for item in value),
        'Exact finite original native namespace fields required')
    return list(map(int, value))


# Observe exact private directory identity without interpreting its allocated blocks as capacity.
def directory(path):
    value = path.lstat()
    physical._require(stat.S_ISDIR(value.st_mode) and not path.is_symlink()
        and stat.S_IMODE(value.st_mode) == 0o700 and value.st_uid == os.getuid(),
        'Original private native directory required')
    return [str(getattr(value, name)) for name in
            ('st_dev', 'st_ino', 'st_mode', 'st_size', 'st_blocks', 'st_nlink')]


# Observe a native anchor that legitimately has two links before replacement.
def anchor(path):
    value = physical._regular(path, private=True)
    return [str(getattr(value, name)) for name in
            ('st_dev', 'st_ino', 'st_size', 'st_blocks', 'st_nlink')]


# Create only fixed initialized lease metadata before birth, never an account placeholder.
def reserve(store, writer, *, source_paths):
    physical._require(store.sqlite_reservation is not None and store.metadata_reservation is not None
        and store.snapshot()['sequence'] == 0 and type(writer) is native.ReservedWriter
        and writer._control() == {'operation': None, 'next_slot': 0, 'current': None, 'last': None}
        and not os.path.lexists(writer.root / 'work/paper/state.json')
        and type(source_paths) is list and 1 <= len(source_paths) <= 4,
        'Fresh explicit synthetic native-directory binding required')
    root = store.root / 'reserved-native-directory'
    physical._require(not os.path.lexists(root)
        and not os.path.lexists(store.root / 'native-directory-mode'), 'Original fresh native-directory mode required')
    root.mkdir(mode=0o700)
    for path in (root / 'header', root / 'control', store.root / 'native-directory-mode'):
        protocol.allocate(path, physical.META)
    paths = [*(Path(__file__).parent / name for name in protocol.SOURCES),
             Path(native.__file__), *map(Path, source_paths)]
    physical._require(len(set(paths)) == len(paths)
        and all(Path(path).is_relative_to(Path(__file__).parents[1] / 'tests') for path in source_paths),
        'Distinct synthetic directory executors required')
    header = {'schema': SCHEMA, 'identity': store.identity, 'store': str(store.root),
        'writer': str(writer.root), 'writer_header': sha256((writer.root / 'header').read_bytes()).hexdigest(),
        'sources': {str(path): protocol.source_sha(path) for path in paths},
        'executors': list(map(str, source_paths)), 'slots': writer.header['slots'],
        'metadata': store.metadata_reservation.binding,
        'directories': {name: directory(writer.root if name == '.' else writer.root / name) for name in DIRECTORIES},
        'anchors': {str(i): anchor(writer.root / 'anchors' / str(i)) for i in range(writer.header['slots'])},
        'inodes': {'.': protocol.inode(root), 'header': protocol.inode(root / 'header'),
                   'control': protocol.inode(root / 'control'),
                   'mode': protocol.inode(store.root / 'native-directory-mode')},
        'owner_inode': protocol.inode(store.root / 'lock'), 'capacity_reserved': False,
        'native_operation_adopted': False}
    physical._fixed_write(root / 'header', header)
    binding = {'schema': SCHEMA, 'identity': store.identity, 'store': str(store.root),
        'writer': str(writer.root), 'header_sha256': sha256(physical._encoded(header)).hexdigest(),
        'capacity_reserved': False}
    physical._fixed_write(store.root / 'native-directory-mode', binding)
    physical._fixed_write(root / 'control', {'cursor': writer._control(), 'pending': None,
        'failed': False, 'phases': [], 'active': None, 'records': []})
    physical._sync(root)
    physical._sync(store.root)
    value = DirectoryBindings(store.root, writer, identity=store.identity, metadata_pool=store.metadata_reservation)
    value.owner_fd = store.lock
    value.check()
    store.bind_native_directory(value)
    return value


# Bind finite original namespace transitions without claiming a filesystem allocation guarantee.
class DirectoryBindings:
    # Hold the original directories for this Store lifetime, including on metadata-only reopen.
    def __init__(self, store, writer, *, identity, metadata_pool):
        self.store, self.writer, self.identity = Path(store), writer, physical._digest(identity)
        self.metadata_pool = metadata_pool
        self.root = self.store / 'reserved-native-directory'
        self.header = physical._fixed_read(self.root / 'header')
        self.fault, self.live_failed, self.descriptors = None, False, {}
        self.original_save = writer._save_locked.__func__
        try:
            self._guard()
            for name in DIRECTORIES:
                path = writer.root if name == '.' else writer.root / name
                self.descriptors[name] = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            self._directories()
        except BaseException:
            self.close()
            raise

    # Preserve the exact source/account/writer/identity declaration in Store and phase evidence.
    @property
    def binding(self):
        return {'schema': SCHEMA, 'identity': self.identity, 'store': str(self.store),
            'writer': str(self.writer.root), 'header_sha256': sha256(physical._encoded(self.header)).hexdigest(),
            'capacity_reserved': False}

    # Close only held descriptors, retaining every failed/completed byte and pathname.
    def close(self):
        for descriptor in self.descriptors.values():
            os.close(descriptor)
        self.descriptors.clear()

    # Require original fixed source/header/mode metadata, never a renamed or omitted substitute.
    def _guard(self):
        h = self.header
        physical._require(type(h) is dict and set(h) == {'schema', 'identity', 'store', 'writer',
            'writer_header', 'sources', 'executors', 'slots', 'metadata', 'directories', 'anchors',
            'inodes', 'owner_inode', 'capacity_reserved', 'native_operation_adopted'}
            and type(self.writer) is native.ReservedWriter and self.store.resolve() == self.store
            and self.writer.root.is_relative_to(self.store)
            and type(self.metadata_pool) is protocol.MetadataSlots
            and self.metadata_pool.header['identity'] == self.identity
            and h['metadata'] == self.metadata_pool.binding
            and self.writer.header['identity_sha256'] == self.identity
            and h['schema'] == SCHEMA and h['identity'] == self.identity
            and h['store'] == str(self.store) and h['writer'] == str(self.writer.root)
            and h['capacity_reserved'] is h['native_operation_adopted'] is False
            and type(h['slots']) is int and 1 <= h['slots'] <= native.MAX_SLOTS
            and h['slots'] == self.writer.header['slots'] and type(h['directories']) is dict
            and set(h['directories']) == set(DIRECTORIES) and type(h['anchors']) is dict
            and type(h['executors']) is list and 1 <= len(h['executors']) <= 4
            and len(set(h['executors'])) == len(h['executors'])
            and all(type(name) is str and Path(name).is_relative_to(Path(__file__).parents[1] / 'tests')
                    for name in h['executors']) and type(h['sources']) is dict
            and set(h['anchors']) == {str(i) for i in range(h['slots'])}
            and set(h['inodes']) == {'.', 'header', 'control', 'mode'}
            and set(h['sources']) == {str(Path(__file__).parent / n) for n in protocol.SOURCES}
                | {str(Path(native.__file__))} | set(h['executors'])
            and physical._fixed_read(self.root / 'header') == h
            and physical._fixed_read(self.store / 'native-directory-mode') == self.binding
            and sha256((self.writer.root / 'header').read_bytes()).hexdigest() == h['writer_header']
            and all(protocol.source_sha(Path(name)) == value for name, value in h['sources'].items()),
            'Original source-bound native-directory mode required')
        physical._digest(h['writer_header'])
        for row in h['directories'].values():
            fields = numbers(row, 6)
            physical._require(fields[0] > 0 and fields[1] > 0 and stat.S_ISDIR(fields[2])
                and stat.S_IMODE(fields[2]) == 0o700 and 0 < fields[3] <= 65536
                and fields[4] * 512 >= fields[3] and fields[5] >= 2,
                'Original bounded native directory observation required')
        physical._require(len({tuple(row[:2]) for row in h['directories'].values()}) == len(DIRECTORIES),
                          'Distinct original native directories required')
        for row in h['anchors'].values():
            fields = numbers(row, 5)
            physical._require(fields[0] > 0 and fields[1] > 0 and fields[2] == native.SLOT_BYTES
                and fields[3] * 512 >= native.SLOT_BYTES and fields[4] == 2,
                'Original unused native anchor allocation required')
        physical._require(len({tuple(row[:2]) for row in h['anchors'].values()}) == h['slots'],
                          'Distinct original native anchors required')
        physical._require(set(self._names(self.root)) == {'header', 'control'},
                          'Original finite directory-lease metadata names required')
        for name, original in h['inodes'].items():
            fields = numbers(original, 4)
            path = self.store / 'native-directory-mode' if name == 'mode' else self.root if name == '.' else self.root / name
            physical._require(protocol.inode(path) == original and (name == '.' or fields[2] == physical.META)
                and fields[3] * 512 >= fields[2], 'Original initialized directory-lease metadata changed')
        physical._require(sum(int(row[3]) * 512 for row in h['inodes'].values()) <= 1024**2
            and numbers(h['owner_inode'], 4)[2] == 4096, 'Finite initialized directory-lease metadata bound')
        physical._require(self.writer._save_locked.__func__ is self.original_save,
                          'Original native locked-save method required')
        self.writer._guard()

    # Bound each directory enumeration instead of recursively inspecting unrelated state.
    def _names(self, path):
        result = []
        with os.scandir(path) as entries:
            for item in entries:
                physical._require(len(result) < 32 and len(item.name.encode()) <= 128,
                                  'Finite native directory name bound')
                result.append(item.name)
        return sorted(result)

    # Compare named and continuously held directory inodes without claiming race-free absolute rename.
    def _directories(self):
        physical._require(set(self.descriptors) == set(DIRECTORIES), 'Original held native directories required')
        for name, descriptor in self.descriptors.items():
            path = self.writer.root if name == '.' else self.writer.root / name
            held = os.fstat(descriptor)
            physical._require(directory(path) == self.header['directories'][name]
                == [str(getattr(held, key)) for key in
                    ('st_dev', 'st_ino', 'st_mode', 'st_size', 'st_blocks', 'st_nlink')],
                'Original held native directory changed; no capacity claim')

    # Require the continuously held original Store owner before metadata mutation or native effects.
    def _owner(self):
        physical._require(hasattr(self, 'owner_fd') and self.header['owner_inode']
            == protocol.inode(self.store / 'lock') == [str(getattr(os.fstat(self.owner_fd), key))
                for key in ('st_dev', 'st_ino', 'st_size', 'st_blocks')],
            'Original native-directory Store owner required')

    # Read only original finite phase/save records; pending work never supplies a completed cursor.
    def _control(self):
        value = physical._fixed_read(self.root / 'control')
        physical._require(set(value) == {'cursor', 'pending', 'failed', 'phases', 'active', 'records'}
            and type(value['failed']) is bool and type(value['phases']) is list and len(value['phases']) <= 8
            and type(value['records']) is list and len(value['records']) <= self.header['slots']
            and type(value['cursor']) is dict
            and set(value['cursor']) == {'operation', 'next_slot', 'current', 'last'}
            and value['cursor']['operation'] is None and type(value['cursor']['next_slot']) is int
            and value['cursor']['next_slot'] == len(value['records'])
            and (value['active'] is None or type(value['active']) is int
                 and 0 <= value['active'] < len(value['phases'])),
            'Exact native-directory phase/cursor control required')
        for index, phase in enumerate(value['phases']):
            physical._require(type(phase) is dict and set(phase) == {'claim', 'status', 'result'}
                and phase['status'] in ('OPEN', 'COMPLETE')
                and (phase['status'] == 'OPEN') == (index == value['active'])
                and (phase['result'] is None if phase['status'] == 'OPEN' else
                     physical._digest(phase['result']) == phase['result']), 'Original directory phase required')
            self._claim(phase['claim'])
        physical._require(len({physical._sha(physical._encoded(p['claim'])) for p in value['phases']})
            == len(value['phases']), 'Distinct original native-directory phase claims required')
        prior, previous_phase = None, -1
        for index, record in enumerate(value['records']):
            physical._require(type(record) is dict and set(record) == {'slot', 'phase', 'receipt', 'anchor'}
                and type(record['slot']) is int and record['slot'] == index and type(record['phase']) is int
                and 0 <= record['phase'] < len(value['phases'])
                and record['phase'] >= previous_phase, 'Original directory save record required')
            self.writer._receipt(record['receipt'], {'last': {'slot': index}})
            row = numbers(record['anchor'], 5)
            state = record['receipt']['state']
            physical._require(record['receipt']['prior'] == prior and record['anchor'][:2]
                == self.header['anchors'][str(index)][:2]
                and row[:3] == [state['device'], state['inode'], state['length']]
                and row[3] * 512 >= row[2] and row[4] == 2,
                'Original native anchor/receipt chain differs')
            prior, previous_phase = state, record['phase']
        expected_cursor = {'operation': None, 'next_slot': len(value['records']), 'current': prior,
            'last': None if not value['records'] else {'slot': len(value['records']) - 1,
                'receipt_sha256': physical._sha(physical._encoded(value['records'][-1]['receipt']))}}
        physical._require(value['cursor'] == expected_cursor, 'Original native directory cursor/receipt chain required')
        if value['pending'] is not None:
            p = value['pending']
            physical._require(type(p) is dict and set(p) == {'slot', 'phase', 'before'}
                and type(p['slot']) is int and p['slot'] == len(value['records'])
                and p['slot'] < self.header['slots'] and p['phase'] == value['active']
                and type(p['phase']) is int and 0 <= p['phase'] < len(value['phases'])
                and value['phases'][p['phase']]['status'] == 'OPEN'
                and p['before'] == value['cursor'], 'Original pending native directory save required')
        return value

    # Authenticate a typed original metadata claim independently of the caller supplying it.
    def _claim(self, claim):
        physical._require(type(claim) is dict and set(claim) == {'schema', 'pool', 'slot', 'operation',
            'phase', 'head', 'inputs', 'latch_session'} and claim['schema'] == protocol.SCHEMA
            and claim['pool'] == self.metadata_pool.binding and type(claim['slot']) is int,
            'Exact original metadata claim required for native-directory phase')
        with self.metadata_pool._locked():
            value = self.metadata_pool._control()
            physical._require(0 <= claim['slot'] < len(value['operations'])
                and self.metadata_pool._reference(claim['slot'], value['operations'][claim['slot']]) == claim,
                'Original persisted metadata claim differs')

    # Validate the one declared native transition and every unaffected original name/link.
    def _namespace(self, cursor, records):
        self._directories()
        physical._require(self._names(self.writer.root) == sorted(('anchors', 'receipts', 'work', 'header', 'control', 'lock'))
            and self._names(self.writer.root / 'work') == ['operations', 'paper']
            and self._names(self.writer.root / 'work/operations') == [],
            'Original finite native parent namespace required')
        slots, used = self.header['slots'], cursor['next_slot']
        physical._require(self._names(self.writer.root / 'anchors') == sorted(str(i) for i in range(slots))
            and self._names(self.writer.root / 'receipts') == sorted(str(i) for i in range(slots)),
            'Original native anchor/receipt namespace required')
        expected = [f'.reserved-{i}.tmp' for i in range(used, slots)]
        if used:
            expected.append('state.json')
        physical._require(self._names(self.writer.root / 'work/paper') == sorted(expected),
                          'Original native temporary/state namespace required')
        for i in range(slots):
            path = self.writer.root / 'anchors' / str(i)
            current = anchor(path)
            if i >= used:
                work = self.writer.root / 'work/paper' / f'.reserved-{i}.tmp'
                physical._require(current == self.header['anchors'][str(i)] == anchor(work),
                                  'Original unused native temporary/anchor changed')
            else:
                record = records[i]
                physical._require(current[:4] == record['anchor'][:4]
                    and int(current[4]) == (2 if i == used - 1 else 1),
                    'Original consumed native anchor/link lineage changed')
        if used:
            physical._require(native._image(self.writer.root / 'work/paper/state.json') == cursor['current']
                == records[-1]['receipt']['state'], 'Original native state cursor differs')

    # Permanently stop new effects on caught namespace uncertainty while preserving original completed records.
    def poison(self):
        self.live_failed = True
        self._owner()
        value = self._control()
        value['failed'] = True
        physical._fixed_write(self.root / 'control', value)

    # Check before each capability, retaining original completed-read access after later uncertainty.
    def check(self, lease=None):
        try:
            self._guard()
            self._owner()
            value = self._control()
            physical._require(not self.live_failed and not value['failed'] and value['pending'] is None,
                              'Uncertain native directory lease; never replay')
            physical._require(self.writer._control() == value['cursor'], 'Native directory cursor drift')
            if lease is not None:
                physical._require(self.verify(lease)['status'] == 'OPEN'
                    and value['active'] == lease['slot'], 'Original OPEN native directory phase required')
            self._namespace(value['cursor'], value['records'])
            return value
        except BaseException:
            self.poison()
            raise

    # Persist exact metadata source/head/input phase ownership before any selected native effect.
    def arm(self, claim):
        value = self.check()
        self._claim(claim)
        physical._require(hasattr(self, 'store_owner') and self.store_owner._directory_binding is self
            and self.store_owner.snapshot()['head'] == claim['head'], 'Original pre-effect directory head required')
        physical._require(value['active'] is None and len(value['phases']) < 8
            and all(row['claim'] != claim for row in value['phases']), 'Fresh native directory phase required')
        value['phases'].append({'claim': deepcopy(claim), 'status': 'OPEN', 'result': None})
        value['active'] = len(value['phases']) - 1
        physical._fixed_write(self.root / 'control', value)
        return {'schema': SCHEMA, 'pool': self.binding, 'slot': value['active'], 'claim': deepcopy(claim)}

    # Authenticate original historical phase identity without adopting pending saves or requiring a latest cursor.
    def verify(self, lease):
        self._guard()
        value = self._control()
        physical._require(type(lease) is dict and set(lease) == {'schema', 'pool', 'slot', 'claim'}
            and lease['schema'] == SCHEMA and lease['pool'] == self.binding
            and type(lease['slot']) is int and 0 <= lease['slot'] < len(value['phases'])
            and value['phases'][lease['slot']]['claim'] == lease['claim'], 'Original directory phase binding required')
        return value['phases'][lease['slot']]

    # Read an original completed native save even when a later independent save remains pending.
    def verify_save(self, lease, receipt):
        self.verify(lease)
        value = self._control()
        slot = receipt['slot']
        physical._require(type(slot) is int and 0 <= slot < len(value['records'])
            and value['records'][slot]['phase'] == lease['slot']
            and value['records'][slot]['receipt'] == receipt
            and physical._fixed_read(self.writer.root / 'receipts' / str(slot)) == receipt
            and native._image(self.writer.root / 'anchors' / str(slot)) == receipt['state'],
            'Original completed directory/native receipt required')
        return receipt

    # Preserve named protocol cut points without claiming a cut inside the kernel rename.
    def _point(self, name):
        if self.fault is not None:
            self.fault(name)

    # Charge a native namespace transition under the original writer lock before invoking unchanged native code.
    def save(self, lease, state, *, expected_preimage):
        try:
            self.writer._guard()
            physical._identity(self.writer.header['identity'], self.identity, self.writer.source)
            physical._require(type(state) is self.writer._state_type, 'Original native PaperState required')
            with self.writer._locked():
                value = self.check(lease)
                physical._require(expected_preimage == value['cursor']['current'], 'Original directory preimage required')
                slot = value['cursor']['next_slot']
                physical._require(slot < self.header['slots'], 'Finite native directory slots exhausted')
                value['pending'] = {'slot': slot, 'phase': lease['slot'], 'before': deepcopy(value['cursor'])}
                physical._fixed_write(self.root / 'control', value)
                self._point('native_directory_pending')
                receipt = self.writer._save_locked(state, expected_preimage)
                cursor = self.writer._control()
                records = [*value['records'], {'slot': slot, 'phase': lease['slot'],
                    'receipt': receipt, 'anchor': anchor(self.writer.root / 'anchors' / str(slot))}]
                physical._require(cursor == {'operation': None, 'next_slot': slot + 1,
                    'current': receipt['state'], 'last': {'slot': slot,
                        'receipt_sha256': physical._sha(physical._encoded(receipt))}},
                    'Original native result cursor required before directory publication')
                self._namespace(cursor, records)
                self._point('native_directory_returned')
                value.update(cursor=cursor, records=records, pending=None)
                physical._fixed_write(self.root / 'control', value)
                self._point('native_directory_result_written')
                return receipt
        except BaseException:
            self.poison()
            raise

    # Complete only the original lifecycle result without saving, appending, replaying or extending slots.
    def complete(self, lease, result):
        phase = self.verify(lease)
        result = physical._digest(result)
        if phase['status'] == 'COMPLETE':
            physical._require(phase['result'] == result, 'Original directory result differs')
            return
        self.check(lease)
        value = self._control()
        value['phases'][lease['slot']].update(status='COMPLETE', result=result)
        value['active'] = None
        physical._fixed_write(self.root / 'control', value)
