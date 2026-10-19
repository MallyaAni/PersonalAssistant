"""Unused private durability primitive; no HTTP, model, sender or account operation.

The caller must reserve before external work. An interrupted reservation pauses;
this module cannot establish whether an external operation happened. Charged byte
allowances are conservative and never refunded. Parser-local usage is not global
acquisition usage. Page manifests retain bytes, not validated market packets.
"""

import fcntl
import hashlib
import io
import os
import sqlite3
import stat
import time
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

from backend.market import historical_packet_checkpoint as checkpoint
from backend.market import historical_packet_demand as demand
from backend.market import historical_packet_registry as registry
from backend.market.historical_timing_packet import _decode, _digest

CHUNK = 64 * 1024
MAX_META = 256 * 1024
MAX_ENTRY = 4096
OPERATIONS = {"DECISION_FROZEN", "SUBMISSION_CAPTURED"}
RATE_NS = 60 * 1_000_000_000
RATE_US = 60 * 1_000_000


# Sample actual acquisition clocks internally, never a historical caller timestamp.
def _clock():
    return datetime.now(UTC), time.monotonic_ns()


# Preserve exact UTC microseconds without floating-point timestamp rounding.
def _clock_values(value):
    utc, monotonic = value
    _require(
        type(utc) is datetime
        and utc.tzinfo is not None
        and utc.utcoffset() == timedelta(0)
        and type(monotonic) is int
        and 0 <= monotonic < 2**63,
        "Actual aware UTC and bounded monotonic clock required",
    )
    delta = utc - datetime(1970, 1, 1, tzinfo=UTC)
    microseconds = (delta.days * 86400 + delta.seconds) * 1_000_000 + delta.microseconds
    _require(0 <= microseconds < 2**63, "Bounded actual UTC required")
    return microseconds, monotonic


# Distinguish a private resource/uncertainty pause from missing market evidence.
class StorePause(ValueError):  # noqa: N818 -- Explicit resource/uncertainty pause.
    """The same identity must remain paused without implicit re-execution."""


# Reject unsafe metadata and conflicting descendants before any new commitment.
def _require(condition, message):
    if not condition:
        raise StorePause(message)


# Flush directory entries after immutable-file publication and database creation.
def _sync_directory(path):
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


# Require private regular paths without following a supplied symlink.
def _private(path, directory=False):
    info = path.lstat()
    expected = stat.S_ISDIR if directory else stat.S_ISREG
    _require(expected(info.st_mode), "Private regular path required")
    _require(
        stat.S_IMODE(info.st_mode) == (0o700 if directory else 0o600),
        "Private0700/0600 permissions required",
    )


# Persist one identity and authoritative head with indexed, crash-atomic appends.
class Store:
    # Open one private writer requiring every original pool recorded by its persisted mode.
    def __init__(self, root, identity_sha256, expected_head, *, create=False, blob_reservation=None,
                 metadata_reservation=None, sqlite_reservation=None, directory_binding=None):
        self.root = Path(root)
        self.identity = registry.digest(identity_sha256)
        self.owner = uuid4().hex
        self.fault = None
        self.connection = None
        self._spools = {}
        self._blob_reservation = None
        self._metadata_reservation = None
        self._sqlite_reservation = sqlite_reservation
        self._directory_binding = directory_binding
        self._last_clock = None
        self._opened_clock = self._sample_clock()
        if create and sqlite_reservation is None:
            self.root.mkdir(mode=0o700)
        _require(directory_binding is not None or (not os.path.lexists(self.root / 'native-directory-mode')
            and not os.path.lexists(self.root / 'reserved-native-directory')),
            'Original explicit native-directory mode required before connect')
        if directory_binding is not None:
            from backend.market.historical_native_directory_binding import DirectoryBindings

            _require(type(directory_binding) is DirectoryBindings and directory_binding.store == self.root
                and directory_binding.identity == self.identity, 'Original native-directory Store binding required')
        _require(sqlite_reservation is not None or (not os.path.lexists(self.root / 'sqlite-mode')
            and not os.path.lexists(self.root / 'reserved-sqlite')),
                 'Original explicit SQLite bank mode required before connect')
        if sqlite_reservation is not None:
            from backend.market.historical_reserved_sqlite import SQLiteBanks

            _require(type(sqlite_reservation) is SQLiteBanks and sqlite_reservation.root == self.root
                and sqlite_reservation.identity == self.identity
                and not os.path.lexists(self.root / 'state.sqlite'), 'Original separate SQLite bank Store required')
        _private(self.root, True)
        self.lock = os.open(
            self.root / "lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600
        )
        try:
            _private(self.root / "lock")
            fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            if directory_binding is not None:
                directory_binding.owner_fd = self.lock
            if sqlite_reservation is not None:
                sqlite_reservation.owner_fd = self.lock
            for name in ("blobs", "incoming"):
                path = self.root / name
                if create:
                    path.mkdir(mode=0o700)
                _private(path, True)
            database = self.root / "state.sqlite"
            if create and sqlite_reservation is None:
                descriptor = os.open(
                    database, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600
                )
                os.close(descriptor)
            if sqlite_reservation is None:
                _private(database)
            self.connection = (sqlite3.connect(database, isolation_level=None, timeout=0)
                               if sqlite_reservation is None else sqlite_reservation.connect(create=create))
            self.connection.row_factory = sqlite3.Row
            self.connection.setlimit(sqlite3.SQLITE_LIMIT_LENGTH, MAX_META)
            setup = (
                """
                PRAGMA journal_mode=DELETE;
                PRAGMA synchronous=FULL;
                PRAGMA cache_size=-16384;
                PRAGMA mmap_size=0;
                PRAGMA temp_store=FILE;
                CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, raw BLOB);
                CREATE TABLE IF NOT EXISTS entries (
                  sequence INTEGER PRIMARY KEY, sha TEXT UNIQUE, cycle TEXT,
                  stage TEXT, receipt TEXT, raw BLOB, UNIQUE(stage,receipt));
                CREATE INDEX IF NOT EXISTS entry_cycle ON entries(cycle,sequence);
                CREATE TABLE IF NOT EXISTS cycles (sha TEXT PRIMARY KEY);
                CREATE TABLE IF NOT EXISTS operations (
                  id TEXT PRIMARY KEY, cycle TEXT, stage TEXT, parent TEXT,
                  inputs TEXT, owner TEXT, status TEXT, receipt TEXT,
                  UNIQUE(cycle,stage));
                CREATE TABLE IF NOT EXISTS demands (
                  sha TEXT PRIMARY KEY, cycle TEXT UNIQUE, raw BLOB);
                CREATE TABLE IF NOT EXISTS attempts (
                  id TEXT PRIMARY KEY, demand TEXT, query TEXT, page INTEGER,
                  owner TEXT, status TEXT, token TEXT, body TEXT, next_token TEXT,
                  raw BLOB, reserved_utc_us INTEGER, reserved_monotonic_ns INTEGER);
                CREATE INDEX IF NOT EXISTS attempt_group
                  ON attempts(demand,query,page);
                CREATE TABLE IF NOT EXISTS reads (
                  sequence INTEGER PRIMARY KEY, id TEXT UNIQUE, attempt TEXT,
                  allowance INTEGER, actual INTEGER, blob TEXT);
                CREATE INDEX IF NOT EXISTS read_attempt ON reads(attempt,sequence);
            """
                if create
                else """
                PRAGMA journal_mode=DELETE;
                PRAGMA synchronous=FULL;
                PRAGMA cache_size=-16384;
                PRAGMA mmap_size=0;
                PRAGMA temp_store=FILE;
            """
            )
            if sqlite_reservation is not None:
                _require(setup.count('PRAGMA journal_mode=DELETE;') == setup.count('PRAGMA temp_store=FILE;') == 1,
                         'Original ordinary SQLite setup required')
                setup = setup.replace('PRAGMA journal_mode=DELETE;', 'PRAGMA journal_mode=MEMORY;').replace(
                    'PRAGMA temp_store=FILE;', 'PRAGMA temp_store=MEMORY;')
            self.connection.executescript(setup)
            tables = {
                row[0]
                for row in self.connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
            _require(
                tables
                == {
                    "meta",
                    "entries",
                    "cycles",
                    "operations",
                    "demands",
                    "attempts",
                    "reads",
                },
                "Original receipt schema required; no implicit repair",
            )
            for name, columns in (
                ("entry_cycle", ["cycle", "sequence"]),
                ("attempt_group", ["demand", "query", "page"]),
                ("read_attempt", ["attempt", "sequence"]),
            ):
                _require(
                    [
                        row[2]
                        for row in self.connection.execute(
                            "PRAGMA index_info(" + name + ")"
                        )
                    ]
                    == columns,
                    "Original bounded lookup indexes required",
                )
            _require(
                [
                    row[1]
                    for row in self.connection.execute("PRAGMA table_info(attempts)")
                ]
                == [
                    "id",
                    "demand",
                    "query",
                    "page",
                    "owner",
                    "status",
                    "token",
                    "body",
                    "next_token",
                    "raw",
                    "reserved_utc_us",
                    "reserved_monotonic_ns",
                ],
                "Original rate-slot schema required; no implicit migration",
            )
            if create:
                with self._transaction():
                    if sqlite_reservation is not None:
                        self.connection.execute("INSERT INTO meta VALUES ('reserved_sqlite_header',?)",
                                                (demand.encoded(sqlite_reservation.binding),))
                    self._write_state(
                        {
                            "identity": self.identity,
                            "head": None,
                            "sequence": 0,
                            "index": 0,
                            "cycle": None,
                            "used": {"get_attempts": 0, "body_bytes": 0},
                            "confirmed_bytes": 0,
                            "unresolved_gets": 0,
                            "unresolved_bytes": 0,
                        }
                    )
                _sync_directory(self.root)
            state = self._state()
            _require(
                state["identity"] == self.identity and state["head"] == expected_head,
                "Identity or authoritative pinned head differs",
            )
            self._validate_head(state)
            rows = self._rate_rows(state)
            _require(
                not rows or self._opened_clock[0] >= rows[0]["reserved_utc_us"],
                "Actual UTC clock reversal on resume",
            )
            self._restart_quiet = not create and bool(rows)
            reserved = self.connection.execute("SELECT raw FROM meta WHERE key='reserved_blob_header'").fetchone()
            _require(blob_reservation is not None or (reserved is None
                and not os.path.lexists(self.root / 'reserved-blobs')),
                'Original explicit reserved CAS binding required; no downgrade')
            if blob_reservation is not None:
                self.bind_reserved_blobs(blob_reservation)
            metadata = self.connection.execute("SELECT raw FROM meta WHERE key='reserved_metadata_header'").fetchone()
            _require(metadata_reservation is not None or (metadata is None
                and not os.path.lexists(self.root / 'reserved-protocol')),
                'Original explicit metadata namespace required; no downgrade')
            if metadata_reservation is not None:
                self.bind_reserved_metadata(metadata_reservation)
            self.sqlite_reservation
            if directory_binding is not None:
                directory_binding.store_owner = self
                _require(directory_binding.metadata_pool is self._metadata_reservation,
                         'Original retained directory metadata namespace required')
            self.directory_binding
            if sqlite_reservation is not None:
                sqlite_reservation.seal_connection()
        except BaseException:
            self.close()
            raise

    # Expose only the explicitly bound finite CAS, retaining ordinary mode when absent.
    @property
    def blob_reservation(self):
        return self._blob_reservation

    # Require the original directory mode recorded before birth, even after its pool disappears.
    @property
    def directory_binding(self):
        row = self.connection.execute("SELECT raw FROM meta WHERE key='native_directory_header'").fetchone()
        value = self._directory_binding
        _require((row is None and value is None
            and not os.path.lexists(self.root / 'native-directory-mode')
            and not os.path.lexists(self.root / 'reserved-native-directory'))
            or (row is not None and value is not None and row['raw'] == demand.encoded(value.binding)),
            'Original persisted native-directory binding required; no downgrade')
        return value

    # Persist one fresh source-bound namespace guard before any account or stage exists.
    def bind_native_directory(self, value):
        from backend.market.historical_native_directory_binding import DirectoryBindings

        _require(type(value) is DirectoryBindings and value.store == self.root and value.identity == self.identity
            and self.snapshot()['sequence'] == 0 and self._directory_binding is None,
            'Fresh pre-birth native-directory binding required')
        value.owner_fd = self.lock
        value.check()
        _require(self.connection.execute("SELECT raw FROM meta WHERE key='native_directory_header'").fetchone() is None,
                 'Native-directory mode cannot rebind')
        with self._transaction():
            self.connection.execute("INSERT INTO meta VALUES ('native_directory_header',?)",
                                    (demand.encoded(value.binding),))
        self._directory_binding = value
        value.store_owner = self

    # Require the original separate bank mode and forbid a stale native-file fallback.
    @property
    def sqlite_reservation(self):
        row = self.connection.execute("SELECT raw FROM meta WHERE key='reserved_sqlite_header'").fetchone()
        _require((row is None and self._sqlite_reservation is None
            and not getattr(self.connection, 'reserved_bank_mode', False)
            and not os.path.lexists(self.root / 'sqlite-mode')
            and not os.path.lexists(self.root / 'reserved-sqlite'))
            or (row is not None and self._sqlite_reservation is not None
                and self.connection is self._sqlite_reservation.connection
                and row['raw'] == demand.encoded(self._sqlite_reservation.binding)),
            'Original retained SQLite bank binding required; no downgrade')
        return self._sqlite_reservation

    # Persist the exact pool header before selected native work, never adopt legacy blobs.
    def bind_reserved_blobs(self, reservation):
        from backend.market.historical_reserved_blob_store import ReservedCAS

        _require(type(reservation) is ReservedCAS and reservation.identity == self.identity
            and reservation.root == self.root / 'reserved-blobs'
            and self._blob_reservation in (None, reservation), 'Exact same-Store reserved CAS required')
        raw = demand.encoded({'schema': reservation.header['schema'], 'header_sha256': reservation.header_sha256})
        row = self.connection.execute("SELECT raw FROM meta WHERE key='reserved_blob_header'").fetchone()
        if row is None:
            for name in ('blobs', 'incoming'):
                with os.scandir(self.root / name) as entries:
                    _require(next(entries, None) is None, 'Existing Store blob namespace cannot be adopted')
            with self._transaction():
                self.connection.execute("INSERT INTO meta VALUES ('reserved_blob_header',?)", (raw,))
        else:
            _require(row['raw'] == raw, 'Original reserved CAS header differs')
        self._blob_reservation = reservation

    # Require the persisted original metadata mode even if its pool was removed or detached.
    @property
    def metadata_reservation(self):
        row = self.connection.execute("SELECT raw FROM meta WHERE key='reserved_metadata_header'").fetchone()
        _require((row is None and self._metadata_reservation is None
            and not os.path.lexists(self.root / 'reserved-protocol'))
            or (self._metadata_reservation is not None and row is not None
                and row['raw'] == demand.encoded(self._metadata_reservation.binding)),
            'Original retained metadata binding required; no downgrade')
        return self._metadata_reservation

    # Persist an exact pre-birth marker namespace without altering ordinary Store tables or paths.
    def bind_reserved_metadata(self, reservation):
        from backend.market.historical_reserved_protocol import MetadataSlots

        _require(type(reservation) is MetadataSlots and reservation.identity == self.identity
            and reservation.root == self.root / 'reserved-protocol'
            and self._blob_reservation is not None
            and self._metadata_reservation in (None, reservation), 'Exact same-Store metadata namespace required')
        reservation._guard()
        raw = demand.encoded(reservation.binding)
        row = self.connection.execute("SELECT raw FROM meta WHERE key='reserved_metadata_header'").fetchone()
        if row is None:
            _require(self._state()['head'] is None and self._state()['sequence'] == 0,
                     'Metadata namespace binding must precede Store effects')
            _require(reservation._control() == {'operations': [], 'latches': {}, 'pending': None, 'failed': False}
                and not os.path.lexists(Path(reservation.header['account']) / 'paper/state.json'),
                'Existing metadata operations/account cannot be adopted')
            with self._transaction():
                self.connection.execute("INSERT INTO meta VALUES ('reserved_metadata_header',?)", (raw,))
        else:
            _require(row['raw'] == raw, 'Original metadata namespace header differs')
        self._metadata_reservation = reservation

    # Release process ownership without resolving any unfinished external operation.
    def close(self):
        if getattr(self, '_directory_binding', None) is not None:
            self._directory_binding.close()
        if self.connection is not None:
            self.connection.close()
            self.connection = None
        if getattr(self, "lock", None) is not None:
            os.close(self.lock)
            self.lock = None

    # Reject either clock moving backwards within this process before any charge.
    def _sample_clock(self):
        sampled = _clock_values(_clock())
        _require(
            self._last_clock is None
            or all(
                new >= old for new, old in zip(sampled, self._last_clock, strict=True)
            ),
            "Actual acquisition clock reversal",
        )
        self._last_clock = sampled
        return sampled

    # Read only the latest bounded indexed slots and reject missing recent charges.
    def _rate_rows(self, state):
        limit = demand.BUDGET["requests_per_minute"]
        rows = self.connection.execute(
            "SELECT rowid AS sequence, owner, reserved_utc_us, reserved_monotonic_ns "
            "FROM attempts ORDER BY rowid DESC LIMIT ?",
            (limit,),
        ).fetchall()
        charged = state["used"]["get_attempts"]
        _require(len(rows) == min(limit, charged), "Original rate slots missing")
        for offset, row in enumerate(rows):
            _require(
                row["sequence"] == charged - offset
                and type(row["reserved_utc_us"]) is int
                and 0 <= row["reserved_utc_us"] < 2**63
                and type(row["reserved_monotonic_ns"]) is int
                and 0 <= row["reserved_monotonic_ns"] < 2**63
                and type(row["owner"]) is str
                and len(row["owner"]) == 32,
                "Original bounded rate slot differs",
            )
            if offset:
                _require(
                    rows[offset - 1]["reserved_utc_us"] >= row["reserved_utc_us"],
                    "Persisted UTC slot clock reversal",
                )
        return rows

    # Reserve rolling actual-clock capacity without refunding failed or uncertain GETs.
    def _rate_slot(self, state):
        rows = self._rate_rows(state)
        utc, monotonic = self._sample_clock()
        _require(
            not rows or utc >= rows[0]["reserved_utc_us"],
            "Actual UTC clock reversal",
        )
        _require(
            not self._restart_quiet or monotonic - self._opened_clock[1] >= RATE_NS,
            "Restart acquisition quiet period has not elapsed",
        )
        recent = sum(
            row["reserved_utc_us"] > utc - RATE_US
            or (
                row["owner"] == self.owner
                and row["reserved_monotonic_ns"] > monotonic - RATE_NS
            )
            for row in rows
        )
        _require(recent < demand.BUDGET["requests_per_minute"], "Rolling GET rate cap")
        return utc, monotonic

    # Expose deterministic test crash boundaries without performing external work.
    def _point(self, name):
        if self.fault is not None:
            self.fault(name)

    # Return only after ordinary SQLite commit or separately reserved durable-bank publication.
    @contextmanager
    def _transaction(self):
        if self._sqlite_reservation is None:
            _require(not getattr(self.connection, 'reserved_bank_mode', False)
                and not os.path.lexists(self.root / 'sqlite-mode')
                and not os.path.lexists(self.root / 'reserved-sqlite'), 'SQLite bank mode cannot downgrade')
            self.connection.execute("BEGIN IMMEDIATE")
            try:
                yield
                self._point("before_commit")
                self.connection.execute("COMMIT")
                self._point("after_commit")
            except BaseException:
                if self.connection.in_transaction:
                    self.connection.execute("ROLLBACK")
                raise
            return
        try:
            if self._sqlite_reservation is not None:
                row = self.connection.execute("SELECT raw FROM meta WHERE key='state'").fetchone()
                self._sqlite_reservation.begin(None if row is None else _decode(row['raw'])['head'])
            self.connection.execute("BEGIN IMMEDIATE")
            yield
            self._point("before_commit")
            self.connection.execute("COMMIT")
            if self._sqlite_reservation is not None:
                self._point('sqlite_ram_committed')
                self._sqlite_reservation._point('sqlite_ram_committed')
                self._sqlite_reservation.publish(self._state()['head'])
            self._point("after_commit")
        except BaseException:
            try:
                if self.connection.in_transaction:
                    self.connection.execute("ROLLBACK")
            finally:
                self._sqlite_reservation.poison()
            raise

    # Read only bounded singleton state rather than scanning the history.
    def _state(self):
        row = self.connection.execute(
            "SELECT raw FROM meta WHERE key='state'"
        ).fetchone()
        _require(row is not None and len(row[0]) <= MAX_ENTRY, "Bounded state missing")
        return _decode(row[0])

    # Replace the small authoritative state in the same transaction as its receipt.
    def _write_state(self, state):
        raw = demand.encoded(state)
        _require(len(raw) <= MAX_ENTRY, "State metadata cap")
        self.connection.execute(
            "INSERT OR REPLACE INTO meta VALUES ('state',?)", (raw,)
        )

    # Check the indexed head summary before trusting a resumed append.
    def _validate_head(self, state):
        demand.usage(state["used"])
        _require(
            0 <= state["confirmed_bytes"] <= state["used"]["body_bytes"]
            and 0 <= state["unresolved_bytes"] <= state["used"]["body_bytes"]
            and 0 <= state["unresolved_gets"] <= state["used"]["get_attempts"],
            "Charged/confirmed/unresolved summary differs",
        )
        row = self.connection.execute(
            "SELECT * FROM entries ORDER BY sequence DESC LIMIT 1"
        ).fetchone()
        if row is None:
            _require(
                state["sequence"] == state["index"] == 0
                and state["head"] is None
                and state["cycle"] is None,
                "Empty head summary differs",
            )
            return
        _require(len(row["raw"]) <= MAX_ENTRY, "Head receipt cap")
        entry = _decode(row["raw"])
        checkpoint._entry(entry, state["sequence"] - 1, self.identity, entry["parent"])
        index = (
            3
            if entry["stage"] == "ACQUISITION_PROGRESS"
            else (checkpoint.STAGES.index(entry["stage"]) + 1) % len(checkpoint.STAGES)
        )
        _require(
            row["sha"] == entry["sha256"] == state["head"]
            and row["cycle"] == entry["cycle_sha256"] == state["cycle"]
            and index == state["index"]
            and all(state["used"][k] >= entry["used"][k] for k in state["used"]),
            "Authoritative head summary differs",
        )

    # Report charged, confirmed and unresolved domains without treating charges as HTTP.
    def snapshot(self):
        state = self._state()
        return {
            **state,
            "next_stage": checkpoint.STAGES[state["index"]],
            "unresolved": {
                "get_attempts": state["unresolved_gets"],
                "body_bytes": state["unresolved_bytes"],
            },
            "charged_is_not_actual_http_observation": True,
        }

    # Publish durable immutable bytes before any database reference.
    def put_stream(self, stream, *, limit, expected_sha256=None):
        _require(
            type(limit) is int and 0 <= limit <= demand.BUDGET["bytes_per_group"],
            "Bounded blob limit required",
        )
        if expected_sha256 is not None:
            registry.digest(expected_sha256)
        if self._blob_reservation is not None:
            return self._blob_reservation.put_stream(stream, limit=limit, expected_sha256=expected_sha256)
        temporary = self.root / "incoming" / uuid4().hex
        digest, total = hashlib.sha256(), 0
        descriptor = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(descriptor, "wb") as output:
            while True:
                chunk = stream.read(min(CHUNK, limit - total + 1))
                _require(
                    type(chunk) is bytes and len(chunk) <= CHUNK,
                    "Bounded byte stream required",
                )
                if not chunk:
                    break
                total += len(chunk)
                _require(total <= limit, "Blob cap; pause without full allocation")
                digest.update(chunk)
                output.write(chunk)
            output.flush()
            os.fsync(output.fileno())
        self._point("blob_fsynced")
        sha = digest.hexdigest()
        _require(
            expected_sha256 is None or sha == expected_sha256,
            "Original blob digest differs",
        )
        destination = self.root / "blobs" / sha
        try:
            os.link(temporary, destination)
        except FileExistsError:
            _require(
                self.read_blob(sha, limit=limit) == temporary.read_bytes(),
                "Immutable object conflict",
            )
        temporary.unlink()
        _sync_directory(self.root / "blobs")
        self._point("blob_linked")
        return sha, total

    # Reject oversized or nonregular evidence before allocating its bytes.
    def read_blob(self, sha, *, limit):
        registry.digest(sha)
        _require(
            type(limit) is int and 0 <= limit <= demand.BUDGET["bytes_per_group"],
            "Bounded blob read required",
        )
        if self._blob_reservation is not None:
            return self._blob_reservation.read_blob(sha, limit=limit)
        path = self.root / "blobs" / sha
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(descriptor, "rb") as stream:
            info = os.fstat(stream.fileno())
            _require(
                stat.S_ISREG(info.st_mode) and stat.S_IMODE(info.st_mode) == 0o600,
                "Private regular blob required",
            )
            _require(info.st_size <= limit, "Blob read cap before allocation")
            raw = stream.read(limit + 1)
        _require(
            len(raw) == info.st_size and hashlib.sha256(raw).hexdigest() == sha,
            "Original blob bytes differ",
        )
        return raw

    # Require explicit original spool admission after any allocation was attempted.
    def _spool_for(self, attempt, spool):
        from backend.market.historical_packet_spool import ReservedSpool

        _require(spool is self._spools.get(attempt), "Original attempt spool required")
        if spool is not None:
            _require(
                type(spool) is ReservedSpool and spool.store is self,
                "Local original spool required",
            )

    # Adopt exact sealed preallocated extents without copying into a new body file.
    def adopt_spool(self, spool, ref, *, expected_sha256, length):
        _require(self._blob_reservation is None, 'Reserved CAS cannot adopt an external spool')
        self._spool_for(spool.attempt, spool)
        source = spool.resolve(ref, expected_sha256, length)
        registry.digest(expected_sha256)
        descriptor = os.open(source, os.O_RDONLY | os.O_NOFOLLOW)
        try:
            info = os.fstat(descriptor)
            _require(
                info.st_size == length
                and (info.st_dev, info.st_ino) == (ref.device, ref.inode),
                "Exact sealed spool inode/length required",
            )
            digest, total = hashlib.sha256(), 0
            while total < length:
                raw = os.read(descriptor, min(CHUNK, length - total))
                _require(bool(raw), "Sealed spool truncated")
                digest.update(raw)
                total += len(raw)
            _require(
                digest.hexdigest() == expected_sha256,
                "Original sealed spool digest differs",
            )
        finally:
            os.close(descriptor)
        self._point("spool_fsynced")
        destination = self.root / "blobs" / expected_sha256
        try:
            os.link(source, destination)
            linked = destination.lstat()
            _require(
                (linked.st_dev, linked.st_ino) == (ref.device, ref.inode),
                "CAS must adopt the original reserved inode",
            )
        except FileExistsError:
            self.read_blob(expected_sha256, limit=ref.capacity)
        except OSError as error:
            raise StorePause("CAS adoption failed; retain reserved orphan") from error
        try:
            _sync_directory(self.root / "blobs")
        except OSError as error:
            raise StorePause(
                "CAS directory sync failed; retain uncertain orphan"
            ) from error
        self._point("spool_linked")
        return expected_sha256, length

    # Append using indexed membership and the existing pure transition primitives.
    def append(self, *, expected_head, cycle_sha256, stage, receipt_sha256):
        _require(
            stage not in OPERATIONS, "Decision/submission requires prior reservation"
        )
        with self._transaction():
            return self._append(expected_head, cycle_sha256, stage, receipt_sha256)

    # Advance the head atomically without copying or re-verifying the entire chain.
    def _append(self, expected_head, cycle, stage, receipt):
        state = self._state()
        _require(state["head"] == expected_head, "Conflicting or stale descendant")
        body = {
            "sequence": state["sequence"],
            "parent": expected_head,
            "identity_sha256": self.identity,
            "cycle_sha256": cycle,
            "stage": stage,
            "receipt_sha256": receipt,
            "used": demand.usage(state["used"]),
        }
        entry = {**body, "sha256": _digest(body)}
        checkpoint._entry(entry, state["sequence"], self.identity, expected_head)
        if stage in {"DEMAND_FROZEN", "PACKETS_FINALIZED"}:
            declared = self.connection.execute(
                "SELECT sha,raw FROM demands WHERE cycle=?", (cycle,)
            ).fetchone()
            _require(declared is not None, "Original declared demand required")
            _require(
                len(declared["raw"]) <= MAX_META
                and hashlib.sha256(declared["raw"]).hexdigest() == declared["sha"],
                "Original declared demand bytes differ",
            )
            if stage == "DEMAND_FROZEN":
                _require(receipt == declared["sha"], "Original demand receipt required")
            else:
                for query in _decode(declared["raw"])["queries"]:
                    self.page_manifest(declared["sha"], query["sha256"])
        known = self.connection.execute(
            "SELECT 1 FROM entries WHERE cycle=? LIMIT 1", (cycle,)
        ).fetchone()
        index, current = checkpoint._advance(
            entry, state["index"], state["cycle"], {cycle} if known else set()
        )
        if state["index"] == 0:
            self.connection.execute("INSERT INTO cycles VALUES (?)", (cycle,))
        raw = demand.encoded(entry)
        _require(len(raw) <= MAX_ENTRY, "Checkpoint receipt cap")
        self.connection.execute(
            "INSERT INTO entries VALUES (?,?,?,?,?,?)",
            (state["sequence"], entry["sha256"], cycle, stage, receipt, raw),
        )
        self._write_state(
            {
                **state,
                "head": entry["sha256"],
                "sequence": state["sequence"] + 1,
                "index": index,
                "cycle": current,
            }
        )
        return entry

    # Reserve external decision/submission work once before a caller can execute it.
    def reserve_operation(self, *, operation, expected_head, cycle, stage, inputs):
        for sha in (operation, cycle, inputs):
            registry.digest(sha)
        with self._transaction():
            state = self._state()
            _require(
                stage in OPERATIONS
                and checkpoint.STAGES[state["index"]] == stage
                and state["head"] == expected_head
                and state["cycle"] == cycle,
                "Exact next decision/submission reservation required",
            )
            self.connection.execute(
                "INSERT INTO operations VALUES (?,?,?,?,?,?,?,NULL)",
                (operation, cycle, stage, expected_head, inputs, self.owner, "OPEN"),
            )

    # Commit only this live reservation's already-produced receipt and checkpoint.
    def complete_operation(self, operation, receipt):
        with self._transaction():
            row = self.connection.execute(
                "SELECT * FROM operations WHERE id=?", (operation,)
            ).fetchone()
            _require(
                row is not None
                and row["status"] == "OPEN"
                and row["owner"] == self.owner,
                "Unknown/interrupted operation must pause, never re-execute",
            )
            entry = self._append(row["parent"], row["cycle"], row["stage"], receipt)
            self.connection.execute(
                "UPDATE operations SET status='COMMITTED',receipt=? WHERE id=?",
                (entry["sha256"], operation),
            )
            return entry

    # Recover an exact committed outcome without repeating its decision/submission.
    def recover_operation(self, operation):
        row = self.connection.execute(
            "SELECT * FROM operations WHERE id=?", (operation,)
        ).fetchone()
        _require(
            row is not None and row["status"] == "COMMITTED",
            "Uncertain operation remains paused",
        )
        raw = self.connection.execute(
            "SELECT raw FROM entries WHERE sha=?", (row["receipt"],)
        ).fetchone()[0]
        return _decode(raw)

    # Freeze bounded queries against this identity, parent and original charged usage.
    def declare(self, value, reviewed_registry):
        _require(len(value.raw) <= MAX_META, "Demand metadata cap before decoding")
        data = demand.read(value, reviewed_registry)
        state = self._state()
        _require(
            data["identity_sha256"] == self.identity
            and data["parent_sha256"] == state["head"]
            and data["used"] == state["used"]
            and checkpoint.STAGES[state["index"]] == "DEMAND_FROZEN",
            "Demand must bind exact prior state and next stage",
        )
        self.put_stream(
            io.BytesIO(value.raw), limit=MAX_META, expected_sha256=value.sha256
        )
        with self._transaction():
            self.connection.execute(
                "INSERT INTO demands VALUES (?,?,?)",
                (value.sha256, state["cycle"], value.raw),
            )

    # Read a bounded frozen query, never a caller's replacement URL or window.
    def _query(self, sha, query):
        row = self.connection.execute(
            "SELECT raw FROM demands WHERE sha=?", (sha,)
        ).fetchone()
        _require(
            row is not None and len(row[0]) <= MAX_META,
            "Original bounded demand required",
        )
        _require(
            hashlib.sha256(row[0]).hexdigest() == registry.digest(sha),
            "Original declared demand bytes differ",
        )
        data = _decode(row[0])
        found = [item for item in data["queries"] if item["sha256"] == query]
        _require(len(found) == 1, "Query absent from frozen demand")
        return found[0]

    # Charge an authorized attempt without claiming an HTTP request occurred.
    def begin_attempt(self, *, attempt, demand_sha256, query_sha256, page, token):
        registry.digest(attempt)
        self._query(demand_sha256, query_sha256)
        _require(
            type(page) is int and 0 <= page < demand.BUDGET["pages_per_group"],
            "Page cap",
        )
        with self._transaction():
            state = self._state()
            selected = self.connection.execute(
                "SELECT cycle FROM demands WHERE sha=?", (demand_sha256,)
            ).fetchone()
            _require(
                checkpoint.STAGES[state["index"]] == "PACKETS_FINALIZED",
                "Acquisition is only allowed at paused packet stage",
            )
            _require(
                selected is not None and selected[0] == state["cycle"],
                "Acquisition demand belongs to another cycle",
            )
            prior = self.connection.execute(
                "SELECT * FROM attempts WHERE demand=? AND query=? "
                "ORDER BY page LIMIT 11",
                (demand_sha256, query_sha256),
            ).fetchall()
            _require(
                len(prior) == page
                and all(row["status"] == "RETAINED" for row in prior),
                "Uncertain/failed/repeated page cannot be implicitly requested",
            )
            _require(
                token == (prior[-1]["next_token"] if prior else None)
                and (not prior or token is not None),
                "Exact retained predecessor token required",
            )
            _require(
                state["used"]["get_attempts"] < demand.BUDGET["get_attempts"],
                "Cumulative GET resource cap",
            )
            utc, monotonic = self._rate_slot(state)
            state["used"]["get_attempts"] += 1
            state["unresolved_gets"] += 1
            demand.usage(state["used"])
            self.connection.execute(
                "INSERT INTO attempts(rowid,id,demand,query,page,owner,status,token,"
                "body,next_token,raw,reserved_utc_us,reserved_monotonic_ns) "
                "VALUES (?,?,?,?,?,?,'OPEN',?,NULL,NULL,NULL,?,?)",
                (
                    state["used"]["get_attempts"],
                    attempt,
                    demand_sha256,
                    query_sha256,
                    page,
                    self.owner,
                    token,
                    utc,
                    monotonic,
                ),
            )
            self._write_state(state)
        self._point("rate_reserved")
        return {
            "attempt": attempt,
            "reserved_utc_us": utc,
            "reserved_monotonic_ns": monotonic,
            "charged_get_attempts": state["used"]["get_attempts"],
            "acquisition_authorized": False,
        }

    # Reserve a bounded read allowance before the caller receives external body bytes.
    def reserve_read(self, attempt, reservation, allowance):
        registry.digest(reservation)
        _require(
            type(allowance) is int and 0 < allowance <= CHUNK,
            "Bounded body allowance required",
        )
        with self._transaction():
            row = self._owned_attempt(attempt)
            charged = self.connection.execute(
                "SELECT COALESCE(SUM(r.allowance),0) FROM reads r JOIN attempts a "
                "ON a.id=r.attempt WHERE a.demand=? AND a.query=?",
                (row["demand"], row["query"]),
            ).fetchone()[0]
            count = self.connection.execute(
                "SELECT COUNT(*) FROM reads WHERE attempt=?", (attempt,)
            ).fetchone()[0]
            _require(
                charged + allowance <= demand.BUDGET["bytes_per_group"] and count < 321,
                "Bounded group/read-reservation cap",
            )
            state = self._state()
            state["used"]["body_bytes"] += allowance
            state["unresolved_bytes"] += allowance
            demand.usage(state["used"])
            self.connection.execute(
                "INSERT INTO reads(id,attempt,allowance) VALUES (?,?,?)",
                (reservation, attempt, allowance),
            )
            self._write_state(state)

    # Finish only this live process's request, never a post-crash guess.
    def _owned_attempt(self, attempt):
        row = self.connection.execute(
            "SELECT * FROM attempts WHERE id=?", (attempt,)
        ).fetchone()
        _require(
            row is not None and row["status"] == "OPEN" and row["owner"] == self.owner,
            "Interrupted attempt remains uncertain and paused",
        )
        return row

    # Confirm retained chunk bytes independently of the nonrefundable charged allowance.
    def confirm_read(self, reservation, raw, *, spool=None):
        row = self.connection.execute(
            "SELECT * FROM reads WHERE id=?", (reservation,)
        ).fetchone()
        _require(
            row is not None
            and row["actual"] is None
            and type(raw) is bytes
            and len(raw) <= row["allowance"],
            "Exact unconfirmed bounded read required",
        )
        self._owned_attempt(row["attempt"])
        self._spool_for(row["attempt"], spool)
        if spool is None:
            sha, size = self.put_stream(io.BytesIO(raw), limit=row["allowance"])
        else:
            _require(spool.attempt == row["attempt"], "Original attempt spool required")
            ref, sha, size = spool.chunk(reservation, raw, row["allowance"])
            self.adopt_spool(spool, ref, expected_sha256=sha, length=size)
        try:
            with self._transaction():
                self.connection.execute(
                    "UPDATE reads SET actual=?,blob=? WHERE id=?",
                    (size, sha, reservation),
                )
                state = self._state()
                state["confirmed_bytes"] += size
                state["unresolved_bytes"] -= row["allowance"]
                self._write_state(state)
        except sqlite3.Error as error:
            if spool is None:
                raise
            raise StorePause(
                "Read commit failed; retain orphan CAS and pause"
            ) from error

    # Retain complete/failed response bytes without declaring parsed market evidence.
    def finish_attempt(
        self,
        attempt,
        *,
        status,
        complete,
        failure,
        requested_at,
        received_at,
        spool=None,
    ):
        row = self._owned_attempt(attempt)
        self._spool_for(attempt, spool)
        chunks = self.connection.execute(
            "SELECT * FROM reads WHERE attempt=? ORDER BY sequence LIMIT 322",
            (attempt,),
        ).fetchall()
        _require(
            len(chunks) <= 321 and all(chunk["actual"] is not None for chunk in chunks),
            "Uncertain read cannot finalize",
        )
        size = sum(chunk["actual"] for chunk in chunks)
        _require(size <= demand.BUDGET["bytes_per_group"], "Group body cap")
        if spool is None:
            body = b"".join(
                self.read_blob(chunk["blob"], limit=CHUNK) for chunk in chunks
            )
            sha, _ = self.put_stream(
                io.BytesIO(body), limit=demand.BUDGET["bytes_per_group"]
            )
        else:
            _require(spool.attempt == attempt, "Original response spool required")
            ref, sha, length = spool.body(chunks)
            self.adopt_spool(spool, ref, expected_sha256=sha, length=length)
            body = self.read_blob(sha, limit=demand.BUDGET["bytes_per_group"])
        next_token, retained, invalid = None, False, None
        if (
            type(status) is int
            and status == 200
            and complete is True
            and failure is None
        ):
            query = self._query(row["demand"], row["query"])
            try:
                parsed = _decode(body)
                _require(
                    type(parsed) is dict
                    and set(parsed) == {query["kind"], "next_page_token"},
                    "Original provider body shape required",
                )
                next_token = parsed["next_page_token"]
                _require(
                    next_token is None
                    or (type(next_token) is str and 0 < len(next_token) <= 8192),
                    "Bounded continuation token required",
                )
                seen = self.connection.execute(
                    "SELECT 1 FROM attempts WHERE demand=? AND query=? AND "
                    "(token=? OR next_token=?) LIMIT 1",
                    (row["demand"], row["query"], next_token, next_token),
                ).fetchone()
                _require(
                    next_token is None or seen is None, "Repeated continuation token"
                )
                retained = True
            except (ValueError, TypeError):
                invalid = "INVALID_OR_REPEATED_SOURCE_BODY"
        metadata = {
            "status": status,
            "body_complete": complete,
            "failure": failure,
            "requested_at": requested_at,
            "received_at": received_at,
            "reserved_utc_us": row["reserved_utc_us"],
            "reserved_monotonic_ns": row["reserved_monotonic_ns"],
            "body_sha256": sha,
            "body_bytes": size,
            "body_validation_failure": invalid,
            "market_packet_validation": "NOT_PERFORMED",
        }
        if spool is not None:
            metadata["spool_allocation_sha256"] = spool.allocation
        raw = demand.encoded(metadata)
        _require(len(raw) <= MAX_ENTRY, "Page receipt cap")
        if spool is not None:
            ref, receipt_sha, length = spool.receipt(raw)
            self.adopt_spool(spool, ref, expected_sha256=receipt_sha, length=length)
        try:
            with self._transaction():
                self.connection.execute(
                    "UPDATE attempts SET status=?,body=?,next_token=?,raw=? WHERE id=?",
                    (
                        "RETAINED" if retained else "FAILED",
                        sha,
                        next_token,
                        raw,
                        attempt,
                    ),
                )
                state = self._state()
                state["unresolved_gets"] -= 1
                self._write_state(state)
        except sqlite3.Error as error:
            if spool is None:
                raise
            raise StorePause(
                "Response commit failed; retain orphan CAS and pause"
            ) from error
        return metadata

    # Expose one bounded page-reference list without concatenating all groups/history.
    def page_manifest(self, demand_sha256, query_sha256):
        self._query(demand_sha256, query_sha256)
        rows = self.connection.execute(
            "SELECT * FROM attempts WHERE demand=? AND query=? ORDER BY page LIMIT 11",
            (demand_sha256, query_sha256),
        ).fetchall()
        _require(
            0 < len(rows) <= demand.BUDGET["pages_per_group"]
            and all(row["status"] == "RETAINED" for row in rows)
            and rows[-1]["next_token"] is None,
            "Incomplete pagination is a pause, never market missingness",
        )
        return [
            {
                "attempt": row["id"],
                "page": row["page"],
                "token": row["token"],
                "next_token": row["next_token"],
                "receipt": _decode(row["raw"]),
            }
            for row in rows
        ]

    # Stream the full checkpoint audit with bounded memory and indexed membership.
    def audit(self, expected_head):
        prior, index, cycle, count = None, 0, None, 0
        previous = {"get_attempts": 0, "body_bytes": 0}
        for row in self.connection.execute("SELECT * FROM entries ORDER BY sequence"):
            _require(len(row["raw"]) <= MAX_ENTRY, "Checkpoint read cap")
            entry = _decode(row["raw"])
            checkpoint._entry(entry, count, self.identity, prior)
            _require(
                all(
                    row[key] == entry[value]
                    for key, value in (
                        ("sha", "sha256"),
                        ("cycle", "cycle_sha256"),
                        ("stage", "stage"),
                        ("receipt", "receipt_sha256"),
                    )
                ),
                "Checkpoint index differs from original receipt",
            )
            # Indexed prior sequence membership avoids a growing in-memory cycle set.
            seen = self.connection.execute(
                "SELECT 1 FROM entries WHERE cycle=? AND sequence<? LIMIT 1",
                (entry["cycle_sha256"], count),
            ).fetchone()
            index, cycle = checkpoint._advance(
                entry, index, cycle, {entry["cycle_sha256"]} if seen else set()
            )
            used = demand.usage(entry["used"])
            _require(all(used[k] >= previous[k] for k in used), "Usage regressed")
            previous, prior, count = used, entry["sha256"], count + 1
        state = self._state()
        self._rate_rows(state)
        _require(
            self.connection.execute("SELECT COUNT(*) FROM attempts").fetchone()[0]
            == state["used"]["get_attempts"],
            "Full audit GET/rate-slot count differs",
        )
        _require(
            prior == expected_head == state["head"]
            and count == state["sequence"]
            and index == state["index"]
            and cycle == state["cycle"],
            "Authoritative head or summary differs",
        )
        return {
            "head": prior,
            "next_stage": checkpoint.STAGES[index],
            "entries": count,
            "checkpoint_used": previous,
            "charged_used": state["used"],
        }
