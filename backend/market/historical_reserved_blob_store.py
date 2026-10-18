"""Finite SYNTHETIC Store/CAS extents; not SQLite/native/replica admission.

All body, catalog and control files exist before a phase is armed. Used prefixes
remain in their original inodes; publication creates no names or truncated files.
The bounded hash catalog avoids rebuilding a growing whole-history manifest.
"""
from contextlib import contextmanager
from hashlib import sha256
import fcntl
import os
from pathlib import Path
import struct

from backend.market import historical_physical_checkpoint as physical
from backend.market.historical_packet_demand import BUDGET

SCHEMA = 'synthetic-reserved-store-cas/1'
LEASE = 'synthetic-reserved-store-phase/1'
CHUNK = 65536
CELLS = 2048
CELL = 128
GROUPS = 8
SLOTS = 512
PHASE_SLOTS = 64
CALLS = 64
METADATA_BYTES = 2 * 1024**2
METADATA_ITEMS = 4
PREFIX = struct.Struct('>4s32sQIIII')


# Bind this backend, ordinary Store API, metadata adapters and frozen IO primitives.
def sources():
    directory = Path(__file__).parent
    names = ('historical_reserved_blob_store.py', 'historical_packet_store.py',
             'historical_native_metadata.py', 'historical_reserved_native_metadata.py',
             'historical_physical_checkpoint.py')
    return {name: sha256((directory / name).read_bytes()).hexdigest() for name in names}


# Preallocate an empty synthetic Store's complete finite blob namespace before birth.
def reserve(store):
    from backend.market.historical_packet_store import Store

    physical._require(type(store) is Store and store.blob_reservation is None,
                      'Original unbound Store required')
    for name in ('blobs', 'incoming'):
        with os.scandir(store.root / name) as entries:
            physical._require(next(entries, None) is None, 'Existing Store blobs cannot be adopted')
    root = store.root / 'reserved-blobs'
    root.mkdir(mode=0o700)
    (root / 'body').mkdir(mode=0o700)
    for name in ('header', 'control', 'catalog'):
        physical._allocate(root / name, physical.META)
    physical._allocate(root / 'lock', 4096)
    for index in range(SLOTS):
        physical._allocate(root / 'body' / str(index), CHUNK)
    inodes = {name: [str((info := (root / name).stat()).st_dev), str(info.st_ino)]
        for name in ('header', 'control', 'catalog', 'lock', *('body/' + str(i) for i in range(SLOTS)))}
    physical._require((root / 'catalog').read_bytes() == bytes(physical.META), 'New empty catalog required')
    header = {'schema': SCHEMA, 'identity': store.identity, 'store_root': str(store.root),
        'sources': sources(), 'slots': SLOTS, 'slot_bytes': CHUNK,
        'catalog_cells': CELLS, 'cell_bytes': CELL, 'groups': GROUPS,
        'phase_slots': PHASE_SLOTS, 'phase_calls': CALLS,
        'metadata_bytes': METADATA_BYTES, 'metadata_items': METADATA_ITEMS, 'inodes': inodes,
        'directory_metadata_reserved': False, 'sqlite_reserved': False,
        'two_host_reserved': False, 'native_operation_adopted': False}
    physical._fixed_write(root / 'header', header)
    physical._fixed_write(root / 'control', {'groups': [], 'pending': None})
    for path in (root / 'body', root, store.root):
        physical._sync(path)
    return ReservedCAS(root, identity=store.identity)


# Hold a separately versioned finite CAS; OPEN publications never authorize replay.
class ReservedCAS:
    # Authenticate exact source, namespace, inode allocation and the immutable header.
    def __init__(self, root, *, identity):
        self.root = physical._path(root)
        self.identity = physical._digest(identity)
        self.header = physical._fixed_read(self.root / 'header')
        inventory = self.header.get('inodes')
        expected = {'schema': SCHEMA, 'identity': identity, 'store_root': str(self.root.parent),
            'sources': sources(), 'slots': SLOTS, 'slot_bytes': CHUNK,
            'catalog_cells': CELLS, 'cell_bytes': CELL, 'groups': GROUPS,
            'phase_slots': PHASE_SLOTS, 'phase_calls': CALLS,
            'metadata_bytes': METADATA_BYTES, 'metadata_items': METADATA_ITEMS, 'inodes': inventory,
            'directory_metadata_reserved': False, 'sqlite_reserved': False,
            'two_host_reserved': False, 'native_operation_adopted': False}
        physical._require(self.root.name == 'reserved-blobs' and self.header == expected,
                          'Original synthetic reserved CAS header required')
        physical._require(all(self.header[name] is False for name in (
            'directory_metadata_reserved', 'sqlite_reserved', 'two_host_reserved',
            'native_operation_adopted')), 'Explicit unadmitted capacity flags required')
        physical._require(all(type(self.header[name]) is int for name in (
            'slots', 'slot_bytes', 'catalog_cells', 'cell_bytes', 'groups', 'phase_slots',
            'phase_calls', 'metadata_bytes', 'metadata_items')), 'Exact integer CAS bounds required')
        self.header_sha256 = sha256(physical._encoded(expected)).hexdigest()
        names = ('header', 'control', 'catalog', 'lock', *('body/' + str(i) for i in range(SLOTS)))
        physical._require(type(inventory) is dict and set(inventory) == set(names),
                          'Original reserved inode inventory required')
        self.inodes = {}
        for name in names:
            size = CHUNK if name.startswith('body/') else 4096 if name == 'lock' else physical.META
            info = physical._extent(self.root / name, size, 1)
            physical._require(inventory[name] == [str(info.st_dev), str(info.st_ino)],
                              'Original reserved inode differs on reopen')
            self.inodes[name] = info.st_dev, info.st_ino
        self._control()

    # Verify original held/named inodes without accepting sparse or replaced extents.
    def _open(self, name, *, write=False):
        size = CHUNK if name.startswith('body/') else 4096 if name == 'lock' else physical.META
        path = self.root / name
        before = physical._extent(path, size, 1)
        physical._require((before.st_dev, before.st_ino) == self.inodes[name], 'Reserved CAS inode changed')
        descriptor = os.open(path, (os.O_RDWR if write else os.O_RDONLY) | os.O_NOFOLLOW)
        try:
            physical._opened(path, descriptor, before)
        except BaseException:
            os.close(descriptor)
            raise
        return descriptor, before

    # Serialize each finite reservation/read/write through its original allocated lock.
    @contextmanager
    def _locked(self, *, shared=False):
        descriptor, before = self._open('lock', write=True)
        try:
            fcntl.flock(descriptor, (fcntl.LOCK_SH if shared else fcntl.LOCK_EX) | fcntl.LOCK_NB)
            header_fd, header_before = self._open('header')
            try:
                physical._require(physical._fixed_read(self.root / 'header') == self.header,
                                  'Original reserved CAS header changed')
                physical._opened(self.root / 'header', header_fd, header_before)
            finally:
                os.close(header_fd)
            yield
            physical._opened(self.root / 'lock', descriptor, before)
        finally:
            os.close(descriptor)

    # Reject malformed/torn phase counters before interpreting any catalog record.
    def _control(self):
        descriptor, before = self._open('control')
        try:
            frame = os.pread(descriptor, 40, 0)
            length = int.from_bytes(frame[:8], 'big')
            physical._require(len(frame) == 40 and 0 < length < physical.META - 40,
                              'Torn reserved CAS control length')
            raw = os.pread(descriptor, length, 40)
            physical._require(len(raw) == length and sha256(raw).digest() == frame[8:],
                              'Torn reserved CAS control contents')
            physical._opened(self.root / 'control', descriptor, before)
            value = physical._decoded(raw)
        finally:
            os.close(descriptor)
        physical._require(type(value) is dict and set(value) == {'groups', 'pending'}
            and type(value['groups']) is list and len(value['groups']) <= GROUPS,
            'Exact reserved CAS control required')
        for index, group in enumerate(value['groups']):
            physical._require(type(group) is dict and set(group) == {'declaration', 'calls', 'slots', 'bytes',
                'metadata', 'metadata_pending', 'metadata_bytes', 'status', 'result'}
                and type(group['declaration']) is dict
                and type(group['declaration'].get('index')) is int
                and type(group['declaration'].get('start')) is int
                and group['declaration']['index'] == index
                and group['declaration']['start'] == index * PHASE_SLOTS
                and group['declaration']['identity'] == self.identity
                and group['declaration']['header_sha256'] == self.header_sha256
                and group['status'] in ('ACTIVE', 'COMPLETE', 'PAUSED')
                and type(group['calls']) is int and 0 <= group['calls'] <= CALLS
                and type(group['slots']) is int and 0 <= group['slots'] <= PHASE_SLOTS
                and type(group['bytes']) is int and 0 <= group['bytes'] <= PHASE_SLOTS * CHUNK
                and type(group['metadata']) is list and len(group['metadata']) <= METADATA_ITEMS
                and type(group['metadata_bytes']) is int and 0 <= group['metadata_bytes'] <= METADATA_BYTES,
                'Reserved CAS phase counters differ')
            declaration = group['declaration']
            physical._require(set(declaration) == {'schema', 'identity', 'header_sha256', 'index',
                'start', 'slots', 'calls', 'metadata_bytes', 'metadata_items', 'operation', 'head'}
                and all(type(declaration[key]) is int for key in (
                    'slots', 'calls', 'metadata_bytes', 'metadata_items'))
                and declaration['schema'] == LEASE and declaration['slots'] == PHASE_SLOTS
                and declaration['calls'] == CALLS and declaration['metadata_bytes'] == METADATA_BYTES
                and declaration['metadata_items'] == METADATA_ITEMS,
                'Original reserved phase bounds required')
            physical._digest(declaration['operation'])
            for reference in group['metadata']:
                physical._digest(reference)
            if group['metadata_pending'] is not None:
                pending_metadata = group['metadata_pending']
                physical._require(type(pending_metadata) is dict
                    and set(pending_metadata) == {'kind', 'producer'}
                    and pending_metadata['kind'] in ('nightly-entry', 'holding-decision')
                    and group['status'] != 'COMPLETE', 'Original pending metadata required')
                physical._digest(pending_metadata['producer'])
            if declaration['head'] is not None:
                physical._digest(declaration['head'])
            if group['status'] == 'COMPLETE':
                physical._digest(group['result'])
            else:
                physical._require(group['result'] is None, 'Incomplete phase has no result')
            physical._require(index == len(value['groups']) - 1 or group['status'] == 'COMPLETE',
                              'Only the last reserved phase may be active')
        if value['pending'] is not None:
            pending = value['pending']
            physical._require(type(pending) is dict and set(pending) == {'group', 'ordinal'}
                and value['groups'] and type(pending['group']) is int
                and pending['group'] == len(value['groups']) - 1
                and type(pending['ordinal']) is int
                and pending['ordinal'] == value['groups'][-1]['calls'] + 1
                and 0 < pending['ordinal'] <= CALLS
                and value['groups'][-1]['status'] != 'COMPLETE',
                'Original pending blob control required')
        return value

    # Persist a small fixed control update without growing or replacing its inode.
    def _write(self, value):
        raw = physical._encoded(value)
        physical._require(len(raw) + 40 < physical.META, 'Reserved CAS control bound')
        frame = len(raw).to_bytes(8, 'big') + sha256(raw).digest() + raw
        descriptor, before = self._open('control', write=True)
        try:
            physical._require(os.pwrite(descriptor, frame, 0) == len(frame), 'Short reserved control write')
            os.fsync(descriptor)
            physical._written(self.root / 'control', descriptor, before, physical.META)
            physical._require(os.pread(descriptor, len(frame), 0) == frame, 'Control readback differs')
        finally:
            os.close(descriptor)

    # Provide finite fault-injection boundaries without replacing native persistence.
    def _point(self, name):
        pass

    # Reserve a complete finite phase range before any selected native effect occurs.
    def arm(self, *, operation, head):
        physical._digest(operation)
        if head is not None:
            physical._digest(head)
        with self._locked():
            value = self._control()
            physical._require(value['pending'] is None
                and (not value['groups'] or value['groups'][-1]['status'] == 'COMPLETE'),
                'Unfinished reserved CAS phase; never rearm')
            index = len(value['groups'])
            physical._require(index < GROUPS, 'Reserved CAS phase capacity exhausted before native work')
            declaration = {'schema': LEASE, 'identity': self.identity, 'header_sha256': self.header_sha256,
                'index': index, 'start': index * PHASE_SLOTS, 'slots': PHASE_SLOTS,
                'calls': CALLS, 'metadata_bytes': METADATA_BYTES, 'metadata_items': METADATA_ITEMS,
                'operation': operation, 'head': head}
            value['groups'].append({'declaration': declaration, 'calls': 0, 'slots': 0, 'bytes': 0,
                'metadata': [], 'metadata_pending': None, 'metadata_bytes': 0,
                'status': 'ACTIVE', 'result': None})
            self._write(value)
            self._point('reserved_cas_armed')
            return declaration

    # Require an exact original declaration, optionally restricting it to the active writer.
    def group(self, declaration, *, active=False):
        value = self._control()
        physical._require(type(declaration) is dict and type(declaration.get('index')) is int
            and 0 <= declaration['index'] < len(value['groups']), 'Original reserved phase required')
        group = value['groups'][declaration['index']]
        physical._require(group['declaration'] == declaration, 'Reserved phase declaration differs')
        if active:
            physical._require(declaration['index'] == len(value['groups']) - 1
                and group['status'] == 'ACTIVE' and value['pending'] is None,
                'Reserved CAS phase uncertain or not active')
        return value, group

    # Decode one checksummed fixed catalog cell, refusing torn or unsupported records.
    def _cell(self, raw):
        if raw == bytes(CELL):
            return None
        prefix, checksum = raw[:PREFIX.size], raw[PREFIX.size:PREFIX.size + 32]
        physical._require(checksum == sha256(prefix).digest()
            and raw[PREFIX.size + 32:] == bytes(CELL - PREFIX.size - 32), 'Torn reserved CAS catalog')
        magic, digest, length, first, count, group, ordinal = PREFIX.unpack(prefix)
        physical._require(magic == b'RC01' and length <= PHASE_SLOTS * CHUNK
            and count == (length + CHUNK - 1) // CHUNK
            and first + count <= SLOTS and group < GROUPS and 0 < ordinal <= CALLS,
            'Reserved CAS record fields differ')
        return {'sha256': digest.hex(), 'bytes': length, 'first': first,
                'count': count, 'group': group, 'ordinal': ordinal}

    # Probe a fixed bounded hash table instead of serializing all prior object receipts.
    def _lookup(self, digest):
        physical._digest(digest)
        descriptor, before = self._open('catalog')
        try:
            start = int(digest[:8], 16) % CELLS
            for offset in range(CELLS):
                position = (start + offset) % CELLS
                raw = os.pread(descriptor, CELL, position * CELL)
                physical._require(len(raw) == CELL, 'Reserved catalog truncated')
                record = self._cell(raw)
                if record is None or record['sha256'] == digest:
                    physical._opened(self.root / 'catalog', descriptor, before)
                    return position, record
            raise physical.PhysicalPause('Reserved catalog capacity exhausted')
        finally:
            os.close(descriptor)

    # Read only completed logical prefixes while retaining exact padding and old anchors.
    def _read(self, record, value, limit):
        physical._require(record['bytes'] <= limit and record['group'] < len(value['groups']),
                          'Reserved blob read cap or phase differs')
        group = value['groups'][record['group']]
        physical._require(record['ordinal'] <= group['calls']
            and group['declaration']['start'] <= record['first']
            and record['first'] + record['count'] <= group['declaration']['start'] + group['slots'],
            'Uncommitted reserved blob cannot be read')
        chunks, remaining = [], record['bytes']
        for slot in range(record['first'], record['first'] + record['count']):
            descriptor, before = self._open('body/' + str(slot))
            try:
                body = os.pread(descriptor, min(CHUNK, remaining), 0)
                physical._require(len(body) == min(CHUNK, remaining), 'Reserved body truncated')
                physical._opened(self.root / ('body/' + str(slot)), descriptor, before)
                chunks.append(body)
                remaining -= len(body)
            finally:
                os.close(descriptor)
        raw = b''.join(chunks)
        physical._require(not remaining and sha256(raw).hexdigest() == record['sha256'],
                          'Original reserved blob bytes differ')
        return raw

    # Expose ordinary whole-blob reads without adopting a pending publication.
    def read_blob(self, digest, *, limit):
        with self._locked(shared=True):
            value = self._control()
            _, record = self._lookup(digest)
            physical._require(record is not None, 'Reserved blob is absent')
            return self._read(record, value, limit)

    # Persist PENDING before reading/writing and commit only exact fsynced reserved bytes.
    def put_stream(self, stream, *, limit, expected_sha256=None):
        physical._require(type(limit) is int and 0 <= limit <= BUDGET['bytes_per_group'],
                          'Original bounded Store blob limit required')
        if expected_sha256 is not None:
            physical._digest(expected_sha256)
        with self._locked():
            value = self._control()
            physical._require(value['groups'] and value['pending'] is None,
                              'Unreserved or uncertain CAS; never replay')
            group = value['groups'][-1]
            physical._require(group['status'] == 'ACTIVE' and group['calls'] < CALLS,
                              'Reserved CAS write allowance exhausted')
            ordinal = group['calls'] + 1
            value['pending'] = {'group': len(value['groups']) - 1, 'ordinal': ordinal}
            self._write(value)
            self._point('reserved_cas_pending')
            available = min(limit, (PHASE_SLOTS - group['slots']) * CHUNK,
                            PHASE_SLOTS * CHUNK - group['bytes'])
            parts, total = [], 0
            while True:
                body = stream.read(min(CHUNK, available - total + 1))
                physical._require(type(body) is bytes and len(body) <= CHUNK,
                                  'Bounded reserved byte stream required')
                if not body:
                    break
                total += len(body)
                physical._require(total <= available, 'Reserved CAS byte capacity exhausted')
                parts.append(body)
            raw = b''.join(parts)
            digest = sha256(raw).hexdigest()
            physical._require(expected_sha256 is None or expected_sha256 == digest,
                              'Original reserved blob digest differs')
            position, existing = self._lookup(digest)
            if existing is not None:
                physical._require(self._read(existing, value, limit) == raw, 'Reserved immutable conflict')
            else:
                count = (total + CHUNK - 1) // CHUNK
                first = group['declaration']['start'] + group['slots']
                for offset in range(count):
                    name = 'body/' + str(first + offset)
                    descriptor, before = self._open(name, write=True)
                    try:
                        body = raw[offset * CHUNK:(offset + 1) * CHUNK]
                        physical._require(os.pwrite(descriptor, body, 0) == len(body), 'Short reserved CAS write')
                        os.fsync(descriptor)
                        physical._written(self.root / name, descriptor, before, CHUNK)
                        physical._require(os.pread(descriptor, len(body), 0) == body, 'Reserved CAS readback differs')
                    finally:
                        os.close(descriptor)
                self._point('reserved_cas_body_fsynced')
                prefix = PREFIX.pack(b'RC01', bytes.fromhex(digest), total, first, count,
                                     len(value['groups']) - 1, ordinal)
                cell = prefix + sha256(prefix).digest() + bytes(CELL - PREFIX.size - 32)
                descriptor, before = self._open('catalog', write=True)
                try:
                    physical._require(os.pwrite(descriptor, cell, position * CELL) == CELL, 'Short catalog write')
                    os.fsync(descriptor)
                    physical._written(self.root / 'catalog', descriptor, before, physical.META)
                    physical._require(os.pread(descriptor, CELL, position * CELL) == cell, 'Catalog readback differs')
                finally:
                    os.close(descriptor)
                group['slots'] += count
                self._point('reserved_cas_index_fsynced')
            group['calls'] = ordinal
            group['bytes'] += total
            value['pending'] = None
            self._write(value)
            self._point('reserved_cas_committed')
            return digest, total

    # Claim one metadata item before encoding, separately from ordinary CAS slot/call usage.
    def begin_metadata(self, *, kind, producer):
        physical._require(kind in ('nightly-entry', 'holding-decision'), 'Exact native metadata kind required')
        with self._locked():
            value = self._control()
            physical._require(value['groups'], 'Original reserved metadata phase required')
            declaration = value['groups'][-1]['declaration']
            value, group = self.group(declaration, active=True)
            physical._require(group['metadata_pending'] is None and len(group['metadata']) < METADATA_ITEMS,
                              'Uncertain or exhausted reserved metadata count')
            group['metadata_pending'] = {'kind': kind, 'producer': physical._digest(producer)}
            self._write(value)
            self._point('reserved_metadata_pending')
            return declaration, len(group['metadata']), METADATA_BYTES - group['metadata_bytes']

    # Commit one exact typed descriptor after all its reserved chunks are readable.
    def commit_metadata(self, reference):
        with self._locked():
            value, group = self.group(reference['reserved_cas'], active=True)
            physical._require(group['metadata_pending'] == {'kind': reference['kind'],
                'producer': reference['producer_sha256']}
                and reference['metadata_index'] == len(group['metadata'])
                and group['metadata_bytes'] + reference['raw_bytes'] <= METADATA_BYTES,
                'Original reserved metadata completion differs')
            group['metadata'].append(sha256(physical._encoded(reference)).hexdigest())
            group['metadata_bytes'] += reference['raw_bytes']
            group['metadata_pending'] = None
            self._write(value)

    # Pause only the active phase after uncertainty, retaining all completed original phases.
    def poison(self, declaration):
        with self._locked():
            value = self._control()
            physical._require(value['groups'], 'Reserved metadata phase required')
            if (value['groups'][-1]['status'] != 'ACTIVE'
                    or value['groups'][-1]['declaration'] != declaration):
                return
            value['groups'][-1]['status'] = 'PAUSED'
            self._write(value)

    # Authenticate older completed metadata independently of the pool's latest writer cursor.
    def metadata(self, reference):
        with self._locked(shared=True):
            _, group = self.group(reference['reserved_cas'])
            index = reference['metadata_index']
            physical._require(type(index) is int and 0 <= index < len(group['metadata'])
                and group['metadata'][index] == sha256(physical._encoded(reference)).hexdigest(),
                'Original reserved metadata descriptor differs')

    # Seal only a completed original result; idempotent recovery never retries blob/native work.
    def complete(self, declaration, result):
        physical._digest(result)
        with self._locked():
            value, group = self.group(declaration)
            if group['status'] == 'COMPLETE':
                physical._require(group['result'] == result, 'Conflicting reserved phase result')
                return
            physical._require(group['status'] == 'ACTIVE' and value['pending'] is None
                and group['metadata_pending'] is None and declaration['index'] == len(value['groups']) - 1,
                'Uncertain reserved phase cannot complete')
            _, record = self._lookup(result)
            physical._require(record is not None and record['group'] <= declaration['index'],
                              'Original stored phase result required')
            self._read(record, value, physical.META)
            group.update(status='COMPLETE', result=result)
            self._write(value)
            self._point('reserved_cas_phase_complete')
