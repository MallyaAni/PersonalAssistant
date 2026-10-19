"""Finite PRIVATE in-memory SQLite with initialized durable banks.

This storage strategy creates no native SQLite database/journal/FILE-temp path.
It is NOT reservation of SQLite FILE temporaries or full model/RAM admission.
Only a published bank is authoritative; a RAM COMMIT never grants native work.
"""
from copy import deepcopy
from hashlib import sha256
import os
from pathlib import Path
import sqlite3

from backend.market import historical_physical_checkpoint as physical
from backend.market import historical_reserved_protocol as protocol
from backend.market.historical_timing_packet import _decode

SCHEMA = 'synthetic-reserved-sqlite-banks/1'
CAPACITY = 512 * 1024
TICKETS = 128
ALLOWANCES = {'BIRTH': 0, 'NIGHTLY_CLOSE': 0, 'PREPARE': 32,
              'DECISION_FROZEN': 2, 'SUBMISSION_CAPTURED': 2, 'OUTCOME_COMMITTED': 1}


# Observe public SQLite capabilities before selecting this separate private storage policy.
def runtime():
    connection = sqlite3.connect(':memory:', isolation_level=None)
    try:
        options = [row[0] for row in connection.execute('PRAGMA compile_options')]
        physical._require(len(options) <= 128 and all(len(item) <= 512 for item in options)
            and any(item in options for item in ('TEMP_STORE=1', 'TEMP_STORE=2', 'TEMP_STORE=3'))
            and hasattr(connection, 'serialize') and hasattr(connection, 'deserialize'),
            'SQLite memory/serialize capabilities unavailable before native work')
        return {'version': sqlite3.sqlite_version,
                'source_id': connection.execute('SELECT sqlite_source_id()').fetchone()[0],
                'compile_options': options}
    finally:
        connection.close()


# Precreate every bank/control/mode extent before a fresh Store or account exists.
def reserve(root, identity, *, source_paths):
    root = Path(root)
    physical._digest(identity)
    physical._require(not os.path.lexists(root) and root.is_absolute()
        and type(source_paths) is list and 1 <= len(source_paths) <= 4,
        'Fresh finite SQLite plan required')
    root.mkdir(mode=0o700)
    directory = root / 'reserved-sqlite'
    directory.mkdir(mode=0o700)
    for name in ('header', 'control', '0', '1'):
        protocol.allocate(directory / name, CAPACITY if name in ('0', '1') else physical.META)
    protocol.allocate(root / 'sqlite-mode', physical.META)
    protocol.allocate(root / 'lock', 4096)
    paths = [*(Path(__file__).parent / name for name in protocol.SOURCES), *map(Path, source_paths)]
    physical._require(len(set(paths)) == len(paths)
        and all(Path(path).is_relative_to(Path(__file__).parents[1] / 'tests') for path in source_paths),
        'Distinct explicitly synthetic SQLite executors required')
    header = {'schema': SCHEMA, 'identity': identity, 'root': str(root),
        'capacity': CAPACITY, 'tickets': TICKETS, 'runtime': runtime(),
        'sources': {str(path): protocol.source_sha(path) for path in paths},
        'executors': list(map(str, source_paths)),
        'inodes': {name: protocol.inode(directory / name) for name in ('header', 'control', '0', '1')}}
    header['inodes']['.'] = protocol.inode(directory)
    header['mode_inode'] = protocol.inode(root / 'sqlite-mode')
    header['owner_inode'] = protocol.inode(root / 'lock')
    physical._fixed_write(directory / 'header', header)
    binding = {'schema': SCHEMA, 'identity': identity, 'root': str(root),
               'header_sha256': sha256(physical._encoded(header)).hexdigest()}
    physical._fixed_write(root / 'sqlite-mode', binding)
    physical._fixed_write(directory / 'control', {'current': None, 'pending': None, 'failed': False,
        'used': 0, 'bootstrap_used': 0, 'phases': [], 'active': None})
    physical._sync(directory)
    physical._sync(root)
    physical._sync(root.parent)
    return SQLiteBanks(root, identity=identity)


# Guard held cursors as well as shortcuts after caught publication uncertainty.
class MemoryCursor(sqlite3.Cursor):
    # Refuse preparation or cached execution on a poisoned live connection.
    def execute(self, *args, **kwargs):
        physical._require(not self.connection.poisoned, 'Uncertain SQLite RAM cursor')
        return super().execute(*args, **kwargs)

    # Keep batched mutations under the same uncached authorizer and poison guard.
    def executemany(self, *args, **kwargs):
        physical._require(not self.connection.poisoned, 'Uncertain SQLite RAM cursor')
        return super().executemany(*args, **kwargs)

    # Admit schema scripts only during original pre-effect initialization.
    def executescript(self, *args, **kwargs):
        physical._require(not self.connection.poisoned and not self.connection.sealed,
                          'SQLite scripts forbidden after admission')
        return super().executescript(*args, **kwargs)

    # Refuse a held result row after the live transaction lost certainty.
    def fetchone(self):
        physical._require(not self.connection.poisoned, 'Uncertain SQLite RAM cursor')
        return super().fetchone()

    # Refuse a held result batch after the live transaction lost certainty.
    def fetchmany(self, *args):
        physical._require(not self.connection.poisoned, 'Uncertain SQLite RAM cursor')
        return super().fetchmany(*args)

    # Refuse all remaining held rows after the live transaction lost certainty.
    def fetchall(self):
        physical._require(not self.connection.poisoned, 'Uncertain SQLite RAM cursor')
        return super().fetchall()

    # Preserve iterator identity while checking live publication certainty.
    def __iter__(self):
        physical._require(not self.connection.poisoned, 'Uncertain SQLite RAM cursor')
        return self

    # Refuse iterator advancement after a caught uncertain publication.
    def __next__(self):
        physical._require(not self.connection.poisoned, 'Uncertain SQLite RAM cursor')
        return super().__next__()


# Keep real SQLite semantics while refusing unsupported disk routes and caught uncertainty.
class MemoryConnection(sqlite3.Connection):
    # Return only guarded native SQLite cursors rather than another supplied cursor type.
    def cursor(self, factory=None):
        physical._require(not getattr(self, 'poisoned', False) and factory is None,
                          'Original certain SQLite cursor factory required')
        return super().cursor(factory=MemoryCursor)

    # Refuse every ordinary query once the live RAM state lost publication certainty.
    def execute(self, *args, **kwargs):
        physical._require(not getattr(self, 'poisoned', False), 'Uncertain SQLite RAM connection')
        return self.cursor().execute(*args, **kwargs)

    # Route batch shortcuts through the same guarded native cursor and uncached authorizer.
    def executemany(self, *args, **kwargs):
        return self.cursor().executemany(*args, **kwargs)

    # Keep schema setup available only before the admitted query policy is installed.
    def executescript(self, *args, **kwargs):
        physical._require(not getattr(self, 'sealed', False), 'SQLite scripts forbidden after admission')
        return self.cursor().executescript(*args, **kwargs)

    # Refuse raw transient RAM export after publication uncertainty.
    def serialize(self, *args, **kwargs):
        physical._require(not getattr(self, 'poisoned', False), 'Uncertain SQLite RAM image')
        return super().serialize(*args, **kwargs)

    # Prevent the exposed connection from disabling its admitted SQL policy.
    def set_authorizer(self, callback):
        raise ValueError('SQLite authorizer replacement forbidden')

    # Keep native extension loading outside this private memory-only SQL route.
    def enable_load_extension(self, value):
        raise ValueError('SQLite extension route not admitted')

    # Exclude incremental BLOB writes that bypass the admitted SQL statement path.
    def blobopen(self, *args, **kwargs):
        raise ValueError('SQLite incremental BLOB route not admitted')

    # Retain the original native functions instead of accepting executor callbacks.
    def create_function(self, *args, **kwargs):
        raise ValueError('SQLite function registration not admitted')

    # Retain original aggregate semantics instead of accepting executor callbacks.
    def create_aggregate(self, *args, **kwargs):
        raise ValueError('SQLite aggregate registration not admitted')

    # Keep window-function callbacks outside this private SQL policy.
    def create_window_function(self, *args, **kwargs):
        raise ValueError('SQLite window registration not admitted')

    # Keep collation callbacks outside this private SQL policy.
    def create_collation(self, *args, **kwargs):
        raise ValueError('SQLite collation registration not admitted')

    # Permit deserialization only while reopening the authenticated original bank.
    def deserialize(self, *args, **kwargs):
        physical._require(getattr(self, 'loading', False), 'SQLite image substitution forbidden')
        return super().deserialize(*args, **kwargs)

    # Forbid another connection or filesystem target through this private API.
    def backup(self, *args, **kwargs):
        raise ValueError('SQLite backup route not admitted')


# Publish bounded complete SQLite images through the original fixed initialized bank inodes.
class SQLiteBanks:
    # Reopen only the original source/runtime/mode/physical binding without adopting pending work.
    def __init__(self, root, *, identity):
        self.root, self.identity = Path(root), physical._digest(identity)
        self.directory = self.root / 'reserved-sqlite'
        self.header = physical._fixed_read(self.directory / 'header')
        self.fault = None
        self.connection = None
        self.in_transaction, self.live_failed = False, False
        self._guard()

    # Bind this separate storage mode into the original Store metadata and native phase evidence.
    @property
    def binding(self):
        return {'schema': SCHEMA, 'identity': self.identity, 'root': str(self.root),
                'header_sha256': sha256(physical._encoded(self.header)).hexdigest()}

    # Require initialized fixed extents, immutable sources and the same public SQLite runtime.
    def _guard(self):
        h = self.header
        physical._require(set(h) == {'schema', 'identity', 'root', 'capacity', 'tickets', 'runtime',
            'sources', 'executors', 'inodes', 'mode_inode', 'owner_inode'} and h['schema'] == SCHEMA
            and h['identity'] == self.identity and h['root'] == str(self.root)
            and self.root.resolve() == self.root and h['capacity'] == CAPACITY and h['tickets'] == TICKETS
            and physical._fixed_read(self.directory / 'header') == h
            and physical._fixed_read(self.root / 'sqlite-mode') == self.binding
            and protocol.inode(self.root / 'sqlite-mode') == h['mode_inode']
            and protocol.inode(self.root / 'lock') == h['owner_inode']
            and set(h['inodes']) == {'.', 'header', 'control', '0', '1'}
            and set(h['sources']) == {str(Path(__file__).parent / n) for n in protocol.SOURCES}
                | set(h['executors']), 'Original SQLite mode/header required')
        with os.scandir(self.directory) as entries:
            names = []
            for entry in entries:
                physical._require(len(names) < 6, 'SQLite fixed namespace bound')
                names.append(entry.name)
        physical._require(set(names) == set(h['inodes']) - {'.'}, 'Original SQLite namespace required')
        for name, expected in h['inodes'].items():
            physical._require(type(expected) is list and len(expected) == 4
                and all(type(item) is str and item.isdecimal() for item in expected)
                and (name == '.' or int(expected[2]) == (CAPACITY if name in ('0', '1') else physical.META)
                     and int(expected[3]) * 512 >= int(expected[2]))
                and protocol.inode(self.directory if name == '.' else self.directory / name) == expected,
                              'Original initialized SQLite allocation changed')
        physical._require(int(h['mode_inode'][2]) == physical.META and int(h['owner_inode'][2]) == 4096
            and sum(int(row[3]) * 512 for row in [*h['inodes'].values(), h['mode_inode'], h['owner_inode']])
                <= 2 * 1024**2, 'Finite original SQLite allocation budget required')
        physical._require(all(protocol.source_sha(Path(name)) == expected for name, expected in h['sources'].items()),
                          'SQLite source changed')
        physical._require(h['runtime']['version'] == sqlite3.sqlite_version, 'Original SQLite runtime version required')

    # Require the original descriptor continuously held by the live exclusive Store owner.
    def _owner(self):
        physical._require(hasattr(self, 'owner_fd') and [str(getattr(os.fstat(self.owner_fd), key))
            for key in ('st_dev', 'st_ino', 'st_size', 'st_blocks')] == self.header['owner_inode']
            == protocol.inode(self.root / 'lock'), 'Original held SQLite Store ownership required')

    # Read the bounded original generation and precharged transaction/phase declarations.
    def _control(self):
        value = physical._fixed_read(self.directory / 'control')
        physical._require(set(value) == {'current', 'pending', 'failed', 'used', 'bootstrap_used', 'phases', 'active'}
            and type(value['failed']) is bool and type(value['used']) is int and 0 <= value['used'] <= TICKETS
            and type(value['bootstrap_used']) is int and 0 <= value['bootstrap_used'] <= 8
            and type(value['phases']) is list and len(value['phases']) <= 8
            and (value['active'] is None or type(value['active']) is int
                 and 0 <= value['active'] < len(value['phases'])), 'Exact finite SQLite control required')
        for row in value['phases']:
            physical._require(set(row) == {'claim', 'allowance', 'used', 'status', 'result'}
                and row['claim']['phase'] in ALLOWANCES
                and row['allowance'] == ALLOWANCES[row['claim']['phase']]
                and type(row['used']) is int and 0 <= row['used'] <= row['allowance']
                and row['status'] in ('OPEN', 'COMPLETE')
                and (row['result'] is None if row['status'] == 'OPEN' else
                     physical._digest(row['result']) == row['result']), 'Original SQLite phase allowance required')
        for key in ('current', 'pending'):
            row = value[key]
            if row is not None:
                physical._require(type(row) is dict and set(row) == ({'generation', 'bank', 'bytes', 'sha256', 'head'}
                    if key == 'current' else {'generation', 'bank', 'head'})
                    and type(row['generation']) is int and 0 <= row['generation'] < TICKETS
                    and row['bank'] == row['generation'] % 2, 'Original SQLite bank generation required')
                if row['head'] is not None:
                    physical._digest(row['head'])
                if key == 'current':
                    physical._require(type(row['bytes']) is int and 0 < row['bytes'] <= CAPACITY,
                                      'Bounded published SQLite image required')
                    physical._digest(row['sha256'])
        physical._require(value['used'] == value['bootstrap_used'] + sum(row['used'] for row in value['phases'])
            and len({physical._sha(physical._encoded(row['claim'])) for row in value['phases']}) == len(value['phases'])
            and all((row['status'] == 'OPEN') == (index == value['active'])
                    for index, row in enumerate(value['phases'])), 'Original SQLite phase/counter crosslinks required')
        current, pending = value['current'], value['pending']
        physical._require((current is None and value['used'] == (1 if pending is not None else 0))
            or (current is not None and current['generation'] == value['used'] - (2 if pending is not None else 1)),
            'Original published SQLite generation crosslink required')
        if pending is not None:
            physical._require(pending['generation'] == value['used'] - 1
                and (current is None or pending['bank'] != current['bank'] and pending['head'] == current['head']),
                'Pending SQLite bank must preserve the prior authoritative generation')
        return value

    # Retain explicit protocol cuts without representing a RAM commit as durable publication.
    def _point(self, point):
        if self.fault is not None:
            self.fault(point)

    # Read only the exact original published bank, never a pending inactive bank.
    def _image(self, control):
        current = control['current']
        physical._require(current is not None, 'Original published SQLite image missing')
        path = self.directory / str(current['bank'])
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        try:
            original = self.header['inodes'][str(current['bank'])]
            physical._require(original == protocol.inode(path) == [str(getattr(os.fstat(descriptor), key))
                for key in ('st_dev', 'st_ino', 'st_size', 'st_blocks')], 'Original held SQLite bank required')
            raw = os.read(descriptor, CAPACITY + 1)
            physical._require(len(raw) == CAPACITY
                and raw[current['bytes']:] == bytes(CAPACITY - current['bytes'])
                and sha256(raw[:current['bytes']]).hexdigest() == current['sha256'],
                'Original published SQLite bank differs')
            physical._require(original == protocol.inode(path) == [str(getattr(os.fstat(descriptor), key))
                for key in ('st_dev', 'st_ino', 'st_size', 'st_blocks')], 'Held SQLite bank changed')
            return raw[:current['bytes']]
        finally:
            os.close(descriptor)

    # Open a real memory database with no native database/journal/temp file path.
    def connect(self, *, create):
        self._guard()
        self._owner()
        physical._require(runtime() == self.header['runtime'], 'Original SQLite capability profile differs')
        value = self._control()
        physical._require((value['current'] is None and value['used'] == 0 and not value['failed']
            and value['pending'] is None) if create else value['current'] is not None,
            'Fresh or original published SQLite mode required')
        connection = sqlite3.connect(':memory:', isolation_level=None, timeout=0,
                                     factory=MemoryConnection, cached_statements=0)
        connection.poisoned, connection.sealed = False, False
        connection.reserved_bank_mode = True
        if not create:
            connection.loading = True
            try:
                connection.deserialize(self._image(value))
            finally:
                connection.loading = False
        self.connection = connection
        if not create:
            row = connection.execute("SELECT raw FROM meta WHERE key='state'").fetchone()
            physical._require(row is not None and _decode(row[0])['head'] == value['current']['head'],
                              'Published SQLite head differs from its original image')
        connection.execute('PRAGMA page_size=4096')
        connection.execute('PRAGMA max_page_count=128')
        connection.execute('PRAGMA journal_mode=MEMORY')
        connection.execute('PRAGMA temp_store=MEMORY')
        connection.execute('PRAGMA mmap_size=0')
        return connection

    # Restrict later SQL to the existing Store data operations and read-only policy checks.
    def seal_connection(self):
        connection = self.connection
        connection.sealed = True
        sqlite3.Connection.set_authorizer(connection, self._authorize)
        self._policy()

    # Reject attached/disk databases, DDL, changed PRAGMAs and writes outside a reserved transaction.
    def _authorize(self, action, first, second, database, trigger):
        allowed = {sqlite3.SQLITE_READ, sqlite3.SQLITE_SELECT}
        if trigger is not None:
            return sqlite3.SQLITE_DENY
        if action == sqlite3.SQLITE_FUNCTION:
            return sqlite3.SQLITE_OK if second in ('count', 'sum', 'coalesce', 'length', 'substr') else sqlite3.SQLITE_DENY
        if action == sqlite3.SQLITE_PRAGMA:
            return sqlite3.SQLITE_OK if second is None and first in (
                'database_list', 'journal_mode', 'temp_store', 'page_size', 'max_page_count',
                'page_count', 'freelist_count', 'integrity_check', 'compile_options') else sqlite3.SQLITE_DENY
        if action in (sqlite3.SQLITE_INSERT, sqlite3.SQLITE_UPDATE, sqlite3.SQLITE_DELETE, sqlite3.SQLITE_TRANSACTION):
            return sqlite3.SQLITE_OK if self.in_transaction and (action == sqlite3.SQLITE_TRANSACTION
                or database == 'main' and first in ('meta', 'entries', 'cycles', 'operations',
                    'demands', 'attempts', 'reads')) else sqlite3.SQLITE_DENY
        return sqlite3.SQLITE_OK if action in allowed and database in (None, 'main') else sqlite3.SQLITE_DENY

    # Assert the actual main-only memory policy and bounded serialized page domain before effects.
    def _policy(self):
        connection = self.connection
        physical._require(not self.live_failed and not getattr(connection, 'poisoned', False)
            and [tuple(row) for row in connection.execute('PRAGMA database_list')] == [(0, 'main', '')]
            and connection.execute('PRAGMA journal_mode').fetchone()[0] == 'memory'
            and connection.execute('PRAGMA temp_store').fetchone()[0] == 2
            and connection.execute('PRAGMA page_size').fetchone()[0] == 4096
            and connection.execute('PRAGMA max_page_count').fetchone()[0] == 128
            and connection.execute('PRAGMA page_count').fetchone()[0] <= 128,
            'Original finite main-only memory SQLite policy required')

    # Arm exact source/head/input-bound SQL commit allowances before the selected native phase.
    def arm(self, claim):
        self.check()
        value = self._control()
        physical._require(value['active'] is None and value['current'] is not None and claim['phase'] in ALLOWANCES
            and claim['head'] == value['current']['head']
            and len(value['phases']) < 8
            and all(row['claim'] != claim for row in value['phases']), 'Fresh original SQLite phase required')
        value['phases'].append({'claim': deepcopy(claim), 'allowance': ALLOWANCES[claim['phase']],
                                'used': 0, 'status': 'OPEN', 'result': None})
        value['active'] = len(value['phases']) - 1
        physical._fixed_write(self.directory / 'control', value)
        return {'schema': SCHEMA, 'pool': self.binding, 'slot': value['active'], 'claim': deepcopy(claim)}

    # Authenticate an old immutable SQL phase without rearming it or requiring current live authority.
    def verify(self, lease):
        self._guard()
        value = self._control()
        physical._require(type(lease) is dict and set(lease) == {'schema', 'pool', 'slot', 'claim'}
            and lease['schema'] == SCHEMA and lease['pool'] == self.binding
            and type(lease['slot']) is int and 0 <= lease['slot'] < len(value['phases'])
            and value['phases'][lease['slot']]['claim'] == lease['claim'],
            'Original immutable SQLite phase required')
        return value['phases'][lease['slot']]

    # Persist caught admission uncertainty before another IO object can attempt native effects.
    def check(self, lease=None):
        try:
            return self._check(lease)
        except BaseException:
            self.poison()
            raise

    # Validate the current connection against its last published bank before any new native use.
    def _check(self, lease):
        self._guard()
        self._owner()
        self._policy()
        value = self._control()
        physical._require(not value['failed'] and value['pending'] is None, 'Uncertain SQLite publication; no effects')
        if value['current'] is not None:
            physical._require(sha256(self.connection.serialize()).hexdigest() == value['current']['sha256'],
                              'SQLite RAM state differs from authoritative published bank')
        if lease is not None:
            physical._require(lease['schema'] == SCHEMA and lease['pool'] == self.binding
                and value['active'] == lease['slot']
                and value['phases'][lease['slot']]['claim'] == lease['claim']
                and value['phases'][lease['slot']]['status'] == 'OPEN', 'Original OPEN SQLite phase required')
        return value

    # Charge an original immutable transaction ticket before SQLite can change RAM or native authority.
    def begin(self, head):
        value = self.check()
        physical._require(value['used'] < TICKETS, 'Finite SQLite transaction tickets exhausted')
        if value['active'] is None:
            physical._require(not value['phases'] and value['bootstrap_used'] < 8,
                              'SQLite transaction outside original phase')
            value['bootstrap_used'] += 1
        else:
            phase = value['phases'][value['active']]
            physical._require(phase['status'] == 'OPEN' and phase['used'] < phase['allowance'],
                              'SQLite phase transaction allowance exhausted')
            phase['used'] += 1
        generation = value['used']
        value['used'] += 1
        value['pending'] = {'generation': generation, 'bank': generation % 2, 'head': head}
        physical._fixed_write(self.directory / 'control', value)
        self.in_transaction = True
        self._point('sqlite_transaction_reserved')

    # Publish a complete bounded RAM image before Store commit completion can escape to a caller.
    def publish(self, head):
        self._guard()
        self._owner()
        self._policy()
        value = self._control()
        pending = value['pending']
        physical._require(not value['failed'] and pending is not None and self.in_transaction,
                          'Original charged SQLite transaction required')
        raw = self.connection.serialize()
        physical._require(0 < len(raw) <= CAPACITY and len(raw) % 4096 == 0, 'SQLite serialized image cap')
        path = self.directory / str(pending['bank'])
        descriptor = os.open(path, os.O_RDWR | os.O_NOFOLLOW)
        try:
            physical._require(self.header['inodes'][str(pending['bank'])] == protocol.inode(path)
                == [str(getattr(os.fstat(descriptor), key)) for key in
                    ('st_dev', 'st_ino', 'st_size', 'st_blocks')], 'Original held SQLite write bank required')
            body = raw + bytes(CAPACITY - len(raw))
            physical._require(os.pwrite(descriptor, body, 0) == CAPACITY, 'Short SQLite bank write')
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        self._point('sqlite_bank_written')
        self._guard()
        current = {**pending, 'bytes': len(raw), 'sha256': sha256(raw).hexdigest(), 'head': head}
        physical._require(self._image({'current': current}) == raw, 'SQLite bank readback differs')
        value['current'], value['pending'] = current, None
        physical._fixed_write(self.directory / 'control', value)
        self.in_transaction = False
        self._point('sqlite_published')

    # Preserve caught uncertainty persistently and deny all subsequent live SQL access or native effects.
    def poison(self):
        self.live_failed, self.in_transaction = True, False
        if self.connection is not None:
            self.connection.poisoned = True
        self._owner()
        value = self._control()
        value['failed'] = True
        physical._fixed_write(self.directory / 'control', value)

    # Seal only the original published result without another SQLite commit or phase extension.
    def complete(self, lease, result):
        self._guard()
        self._owner()
        self.verify(lease)
        value = self._control()
        physical._require(value['pending'] is None and not value['failed']
            and lease['pool'] == self.binding and 0 <= lease['slot'] < len(value['phases']),
            'Original certain SQLite completion required')
        phase = value['phases'][lease['slot']]
        physical._require(phase['claim'] == lease['claim']
            and (phase['result'] is None or phase['result'] == result), 'Original SQLite result differs')
        if phase['status'] == 'COMPLETE':
            return
        physical._require(value['active'] == lease['slot'], 'Original active SQLite completion required')
        phase['status'], phase['result'] = 'COMPLETE', physical._digest(result)
        value['active'] = None
        physical._fixed_write(self.directory / 'control', value)
