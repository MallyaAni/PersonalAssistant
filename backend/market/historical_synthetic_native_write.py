"""SYNTHETIC1MiB native-writer reservation, not genuine simulator admission.

The NEW FunctionType callable retains a8 writer code but changes only its private
tempfile binding. No shared tempfile attribute is changed. Actual preallocated
inodes own the bytes written; fixed receipts retain uncertainty and old anchors.
Directory metadata, Store, restore, replicas and full lifecycle RAM are NOT
reserved. Neither readable bytes nor local completion authorizes simulator use.
"""

import builtins
import dataclasses
import fcntl
import hashlib
import io
import json
import os
import tempfile
from contextlib import contextmanager
from pathlib import Path
from types import CodeType, FunctionType, SimpleNamespace

from backend.market import historical_physical_checkpoint as physical

HELPER = "5d6169282f5054bc9871a5f4e3dec572a1b0b31482e4ff15ee6bc92ee7803604"
VERSION = "synthetic-current-native-write/1"
SLOT_BYTES = 1024**2
MAX_SLOTS = 16
JSON_DUMP = json.dump
FSYNC = os.fsync
REPLACE = Path.replace
TEMPORARY = tempfile.NamedTemporaryFile
NAMES = {"save_state", "state_path", "_state_json"}


# Authenticate the frozen raw helper before using its private finite-file primitives.
def _helper():
    path = Path(physical.__file__)
    physical._require(
        path.stat().st_size < physical.META, "Bounded helper source required"
    )
    physical._require(
        physical._sha(path.read_bytes()) == HELPER, "Frozen raw helper differs"
    )


# Compile source code objects without executing native imports or model logic.
def _codes(source, filename):
    compiled = compile(source, filename, "exec", dont_inherit=True)
    result = {
        item.co_name: item
        for item in compiled.co_consts
        if type(item) is CodeType and item.co_name in NAMES
    }
    physical._require(set(result) == NAMES, "Exact native writer/support code required")
    return result


# Retain an exact bounded physical preimage without interpreting its native JSON.
def _image(path):
    before = physical._regular(path, private=True)
    physical._require(
        0 < before.st_size <= SLOT_BYTES, "Bounded native preimage required"
    )
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    hashed = hashlib.sha256()
    try:
        physical._opened(path, descriptor, before)
        while chunk := os.read(descriptor, physical.READ):
            hashed.update(chunk)
        physical._opened(path, descriptor, before)
    finally:
        os.close(descriptor)
    return {
        "sha256": hashed.hexdigest(),
        "length": before.st_size,
        "device": before.st_dev,
        "inode": before.st_ino,
    }


# Recompute all file-extent/inode claims independently of a supplied header.
def _amounts(slots):
    return {
        "reserved_file_bytes": slots * (SLOT_BYTES + physical.META)
        + 2 * physical.META
        + 4096,
        "reserved_file_inodes": 2 * slots + 3,
        "precreated_work_links": slots,
    }


# Reserve one exclusive local namespace with actual writer/receipt inodes and links.
def reserve(root, *, writer, writer_source, identity, identity_sha256, slots):
    _helper()
    admitted = physical._identity(identity, identity_sha256, writer_source)
    physical._require(
        type(writer) is FunctionType, "Exact native writer callable required"
    )
    physical._require(
        type(slots) is int and 1 <= slots <= MAX_SLOTS, "Finite writer slots required"
    )
    root = physical._path(root)
    root.mkdir(mode=0o700)
    for name in ("anchors", "receipts", "work", "work/paper"):
        (root / name).mkdir(mode=0o700)
    for name in ("header", "control"):
        physical._allocate(root / name, physical.META)
    physical._allocate(root / "lock", 4096)
    for index in range(slots):
        anchor = root / "anchors" / str(index)
        physical._allocate(anchor, SLOT_BYTES)
        physical._allocate(root / "receipts" / str(index), physical.META)
        os.link(
            anchor,
            root / "work/paper" / f".reserved-{index}.tmp",
            follow_symlinks=False,
        )
    for name in ("anchors", "receipts", "work/paper", "work", "."):
        physical._sync(root / name)
    header = {
        "version": VERSION,
        "identity": admitted,
        "identity_sha256": identity_sha256,
        "writer_sha256": physical.PAPER,
        "helper_sha256": HELPER,
        "adapter_sha256": physical._sha(Path(__file__).read_bytes()),
        "slots": slots,
        "slot_bytes": SLOT_BYTES,
        **_amounts(slots),
        "directory_metadata_reserved": False,
        "dual_host_reserved": False,
        "restore_reserved": False,
        "native_operation_adoption": False,
    }
    physical._fixed_write(root / "header", header)
    physical._fixed_write(
        root / "control",
        {"operation": None, "next_slot": 0, "current": None, "last": None},
    )
    physical._sync(root)
    physical._sync(root.parent)
    return ReservedWriter(
        root,
        writer=writer,
        writer_source=writer_source,
        identity_sha256=identity_sha256,
    )


# Bound every physical write before touching bytes outside the reserved native inode.
class _Raw(io.RawIOBase):
    # Bind one real descriptor to its reserved anchor and monotonically used bytes.
    def __init__(self, owner, descriptor, anchor, work, before):
        super().__init__()
        self.owner, self.descriptor, self.anchor, self.before = (
            owner,
            descriptor,
            anchor,
            before,
        )
        self.used = 0
        self.work = work

    # Permit only the native writer's output direction.
    def writable(self):
        return True

    # Expose the real native fsync descriptor rather than a synthetic receipt.
    def fileno(self):
        physical._require(not self.closed, "Native writer already closed")
        return self.descriptor

    # Report the shared byte offset without a text-encoding cookie.
    def tell(self):
        return os.lseek(self.descriptor, 0, os.SEEK_CUR)

    # Return the actual write count so BufferedWriter handles any short syscall.
    def write(self, value):
        physical._require(not self.closed, "Native writer already closed")
        physical._require(
            self.tell() == self.used and self.used + len(value) <= SLOT_BYTES,
            "Native writer byte reservation exhausted",
        )
        self.owner._guard()
        physical._written(self.anchor, self.descriptor, self.before, SLOT_BYTES)
        physical._written(self.work, self.descriptor, self.before, SLOT_BYTES)
        self.owner._point("before_raw_write")
        count = os.write(self.descriptor, value)
        physical._require(not value or count > 0, "Native write made no progress")
        self.used += count
        physical._written(self.anchor, self.descriptor, self.before, SLOT_BYTES)
        physical._written(self.work, self.descriptor, self.before, SLOT_BYTES)
        self.owner._point("raw_write_returned")
        return count

    # Close this descriptor while preserving the independent truncate descriptor.
    def close(self):
        if not self.closed:
            try:
                os.close(self.descriptor)
            finally:
                super().close()


# Match the exact native writer's small file interface over a nontruncating byte stream.
class _Handle:
    # Preserve a real workname, byte stream and post-close control descriptor.
    def __init__(self, owner, path, anchor, before):
        self.owner, self.path, self.anchor, self.before = owner, path, anchor, before
        descriptor = os.open(path, os.O_RDWR | os.O_NOFOLLOW)
        try:
            physical._opened(path, descriptor, before)
            physical._require(
                os.lseek(descriptor, 0, os.SEEK_SET) == 0,
                "Native writer must start at byte0",
            )
            self.control = os.dup(descriptor)
        except BaseException:
            os.close(descriptor)
            raise
        self.raw = _Raw(owner, descriptor, anchor, path, before)
        self.text = io.TextIOWrapper(
            io.BufferedWriter(self.raw, physical.READ), encoding="utf-8", newline=None
        )
        self.flushed, self.fileno_seen, self.prepared = False, False, False

    # Supply the actual precreated native temporary pathname used by Path.replace.
    @property
    def name(self):
        return str(self.path)

    # Keep JSON serialization in the original native writer.
    def write(self, value):
        self.flushed = False
        return self.text.write(value)

    # Observe a returned native flush, not an unobservable successful fsync syscall.
    def flush(self):
        self.text.flush()
        self.flushed = True
        self.owner._point("native_flush_returned")

    # Require the original flush-before-fsync order and return its real descriptor.
    def fileno(self):
        physical._require(self.flushed, "Native flush must precede fileno")
        self.fileno_seen = True
        self.owner._point("native_fileno")
        return self.raw.fileno()

    # Close the writer before truncating its reserved padding.
    def close(self):
        self.text.close()

    # Return only this bounded private native handle.
    def __enter__(self):
        return self

    # Propagate native errors and truncate only after a successful native block.
    def __exit__(self, kind, error, traceback):
        if kind is not None:
            self.abort()
            return False
        physical._require(
            self.flushed and self.fileno_seen,
            "Original native flush/fsync block required",
        )
        self.owner._point("native_block_returned")
        self.close()
        self.owner._point("writer_closed")
        length = os.lseek(self.control, 0, os.SEEK_CUR)
        physical._require(
            length == self.raw.used and 0 < length <= SLOT_BYTES,
            "Final native byte offset differs",
        )
        physical._written(self.anchor, self.control, self.before, SLOT_BYTES)
        os.ftruncate(self.control, length)
        self.owner._point("truncated")
        os.fsync(self.control)
        physical._written(self.anchor, self.control, self.before, length)
        physical._written(self.path, self.control, self.before, length)
        self.owner._point("truncated_fsynced")
        os.close(self.control)
        self.control = None
        self.prepared = True
        self.owner._point("before_native_replace")
        return False

    # Close uncertain descriptors without removing anchors or manufacturing completion.
    def abort(self):
        try:
            self.close()
        except (OSError, ValueError):
            pass
        finally:
            if self.control is not None:
                os.close(self.control)
                self.control = None


# Hold a source-pinned NEW writer callable and one exclusive private finite slot pool.
class ReservedWriter:
    # Reopen only complete matching resource declarations and exact native source code.
    def __init__(self, root, *, writer, writer_source, identity_sha256):
        _helper()
        self.root, self.source = physical._path(root), physical._path(writer_source)
        physical._require(
            self.root.stat().st_mode & 0o777 == 0o700, "Private writer root required"
        )
        self.header = physical._fixed_read(self.root / "header")
        expected = {
            "version",
            "identity",
            "identity_sha256",
            "writer_sha256",
            "helper_sha256",
            "adapter_sha256",
            "slots",
            "slot_bytes",
            "reserved_file_bytes",
            "reserved_file_inodes",
            "precreated_work_links",
            "directory_metadata_reserved",
            "dual_host_reserved",
            "restore_reserved",
            "native_operation_adoption",
        }
        physical._require(
            type(self.header) is dict and set(self.header) == expected,
            "Exact writer header required",
        )
        physical._require(
            type(self.header["slots"]) is int
            and 1 <= self.header["slots"] <= MAX_SLOTS,
            "Finite writer pool required",
        )
        physical._require(
            self.header["version"] == VERSION
            and self.header["slot_bytes"] == SLOT_BYTES
            and self.header["identity_sha256"] == identity_sha256
            and self.header["writer_sha256"] == physical.PAPER
            and self.header["helper_sha256"] == HELPER
            and self.header["adapter_sha256"]
            == physical._sha(Path(__file__).read_bytes()),
            "Writer source/profile differs",
        )
        physical._require(
            all(
                self.header[key] is False
                for key in (
                    "directory_metadata_reserved",
                    "dual_host_reserved",
                    "restore_reserved",
                    "native_operation_adoption",
                )
            ),
            "Unsupported writer adoption/reservation claim",
        )
        physical._require(
            all(
                type(self.header[key]) is int and self.header[key] == value
                for key, value in _amounts(self.header["slots"]).items()
            ),
            "Writer pool arithmetic differs",
        )
        physical._identity(self.header["identity"], identity_sha256, self.source)
        physical._require(
            type(writer) is FunctionType, "Exact native writer callable required"
        )
        self.writer, self._baseline = writer, dict(writer.__globals__)
        self._annotations = dict(writer.__annotations__)
        self._codes = _codes(self.source.read_bytes(), writer.__code__.co_filename)
        self._state_type = self._baseline.get("PaperState")
        self._active, self._handle = None, None
        self._factory_call = self._factory
        self._facade = SimpleNamespace(NamedTemporaryFile=self._factory_call)
        namespace = {**self._baseline, "tempfile": self._facade}
        self._clone = FunctionType(
            writer.__code__,
            namespace,
            writer.__name__,
            writer.__defaults__,
            writer.__closure__,
        )
        self._clone.__annotations__ = dict(writer.__annotations__)
        self._guard()

    # Admit only unchanged native code/globals and the one explicitly different factory.
    def _guard(self):
        physical._require(
            type(self.writer) is FunctionType
            and self.writer.__code__ == self._codes["save_state"]
            and self.writer.__defaults__ is None
            and self.writer.__kwdefaults__ is None
            and self.writer.__closure__ is None
            and self.writer.__name__ == "save_state",
            "Exact native writer callable required",
        )
        live = self.writer.__globals__
        physical._require(
            set(live) == set(self._baseline)
            and all(live[key] is value for key, value in self._baseline.items()),
            "Native callable globals drift",
        )
        standard = {
            "Path": Path,
            "json": json,
            "os": os,
            "tempfile": tempfile,
            "fields": dataclasses.fields,
            "is_dataclass": dataclasses.is_dataclass,
        }
        physical._require(
            all(live.get(key) is value for key, value in standard.items())
            and live.get("PAPER_KIND") == "paper"
            and live.get("save_state") is self.writer
            and dataclasses.is_dataclass(self._state_type),
            "Native support/global binding differs",
        )
        for name in ("state_path", "_state_json"):
            function = live.get(name)
            physical._require(
                type(function) is FunctionType
                and function.__code__ == self._codes[name]
                and function.__globals__ is live
                and function.__defaults__ is None
                and function.__closure__ is None,
                "Native support function differs",
            )
        for name in ("isinstance", "type", "getattr", "TypeError", "BaseException"):
            physical._require(
                live.get(name, getattr(builtins, name)) is getattr(builtins, name),
                "Native builtin shadow differs",
            )
        physical._require(
            json.dump is JSON_DUMP
            and os.fsync is FSYNC
            and Path.replace is REPLACE
            and tempfile.NamedTemporaryFile is TEMPORARY,
            "Native standard callable drift",
        )
        physical._require(
            self._clone is not self.writer
            and self._clone.__code__ is self.writer.__code__
            and set(self._clone.__globals__) == set(live)
            and all(
                value is (self._facade if key == "tempfile" else live[key])
                for key, value in self._clone.__globals__.items()
            ),
            "Only private tempfile binding may differ",
        )
        physical._require(
            self._clone.__defaults__ is self.writer.__defaults__
            and self._clone.__kwdefaults__ is self.writer.__kwdefaults__
            and self._clone.__closure__ is self.writer.__closure__
            and self._clone.__name__ == self.writer.__name__
            and self.writer.__annotations__
            == self._annotations
            == self._clone.__annotations__,
            "NEW callable attributes differ",
        )
        physical._require(
            vars(self._facade) == {"NamedTemporaryFile": self._factory_call},
            "Private factory facade drift",
        )

    # Serialize readers and writers through the same real inode and reject substitution.
    @contextmanager
    def _locked(self, *, shared=False):
        lock = self.root / "lock"
        before = physical._extent(lock, 4096, 1)
        descriptor = os.open(lock, os.O_RDWR | os.O_NOFOLLOW)
        try:
            physical._opened(lock, descriptor, before)
            try:
                fcntl.flock(
                    descriptor,
                    (fcntl.LOCK_SH if shared else fcntl.LOCK_EX) | fcntl.LOCK_NB,
                )
            except BlockingIOError as error:
                raise physical.PhysicalPause("Native writer already active") from error
            physical._opened(lock, descriptor, before)
            yield
            physical._opened(lock, descriptor, before)
        finally:
            os.close(descriptor)

    # Expose infrastructure cuts without forging syscall or native results.
    def _point(self, name):
        pass

    # Return the charged native inode with exact original factory arguments.
    def _factory(self, *args, **kwargs):
        self._guard()
        physical._require(
            self._active is not None and self._handle is None,
            "Single armed native factory required",
        )
        physical._require(
            not args
            and set(kwargs) == {"mode", "encoding", "dir", "delete"}
            and kwargs["mode"] == "w"
            and kwargs["encoding"] == "utf-8"
            and kwargs["delete"] is False
            and kwargs["dir"] == self.root / "work/paper",
            "Exact native temporary arguments required",
        )
        index = self._active
        anchor, work = (
            self.root / "anchors" / str(index),
            self.root / "work/paper" / f".reserved-{index}.tmp",
        )
        before = physical._extent(anchor, SLOT_BYTES, 2)
        physical._require(
            physical._fingerprint(before)
            == physical._fingerprint(physical._regular(work, private=True)),
            "Reserved workname/anchor differs",
        )
        self._handle = _Handle(self, work, anchor, before)
        self._point("factory_ready")
        return self._handle

    # Read a strict charged cursor without inferring native-operation adoption.
    def _control(self):
        value = physical._fixed_read(self.root / "control")
        physical._require(
            type(value) is dict
            and set(value) == {"operation", "next_slot", "current", "last"}
            and (value["operation"] is None or type(value["operation"]) is int)
            and type(value["next_slot"]) is int
            and 0 <= value["next_slot"] <= self.header["slots"],
            "Exact charged writer control required",
        )
        physical._require(
            value["operation"] is None or value["operation"] == value["next_slot"] - 1,
            "Writer OPEN slot differs",
        )
        physical._require(
            (value["current"] is None) == (value["last"] is None),
            "Writer completion binding differs",
        )
        if value["current"] is not None:
            self._preimage(value["current"])
            physical._require(
                type(value["last"]) is dict
                and set(value["last"]) == {"slot", "receipt_sha256"}
                and type(value["last"]["slot"]) is int
                and 0 <= value["last"]["slot"] < value["next_slot"],
                "Writer last receipt differs",
            )
            physical._digest(value["last"]["receipt_sha256"])
        return value

    # Validate physical references without financial or native JSON admission.
    def _preimage(self, value):
        physical._require(
            type(value) is dict
            and set(value) == {"sha256", "length", "device", "inode"}
            and all(
                type(value[key]) is int and value[key] > 0
                for key in ("length", "device", "inode")
            )
            and value["length"] <= SLOT_BYTES,
            "Exact physical preimage required",
        )
        physical._digest(value["sha256"])

    # Write once from the admitted prior state, retaining OPEN uncertainty on failure.
    def save(self, state, *, expected_preimage):
        self._guard()
        physical._identity(
            self.header["identity"], self.header["identity_sha256"], self.source
        )
        physical._require(
            type(state) is self._state_type,
            "Original supplied PaperState type required",
        )
        with self._locked():
            return self._save_locked(state, expected_preimage)

    # Keep charged operation work under the already-held exclusive inode lock.
    def _save_locked(self, state, expected_preimage):
        try:
            if expected_preimage is not None:
                self._preimage(expected_preimage)
                expected_preimage = physical._decoded(
                    physical._encoded(expected_preimage)
                )
            control = self._control()
            physical._require(control["operation"] is None, "Writer OPEN; never replay")
            destination = self.root / "work/paper/state.json"
            physical._require(
                expected_preimage == control["current"],
                "Authoritative prior image differs",
            )
            if expected_preimage is None:
                physical._require(
                    not destination.exists() and not destination.is_symlink(),
                    "Unexpected existing native destination",
                )
            else:
                self._preimage(expected_preimage)
                physical._require(
                    _image(destination) == expected_preimage,
                    "Native destination preimage differs",
                )
            index = control["next_slot"]
            physical._require(
                index < self.header["slots"], "Native writer slots exhausted"
            )
            control.update(operation=index, next_slot=index + 1)
            physical._fixed_write(self.root / "control", control)
            self._active, self._handle = index, None
            self._point("armed")
            result = self._clone(self.root / "work", state)
            self._point("native_returned")
            physical._require(
                result == destination
                and self._handle is not None
                and self._handle.prepared,
                "Original native writer return differs",
            )
            image = _image(destination)
            anchor = self.root / "anchors" / str(index)
            physical._require(
                image == _image(anchor), "Native result is not reserved inode"
            )
            physical._sync(destination.parent)
            self._point("state_verified")
            receipt = {
                "version": VERSION,
                "identity_sha256": self.header["identity_sha256"],
                "adapter_sha256": self.header["adapter_sha256"],
                "writer_sha256": physical.PAPER,
                "slot": index,
                "prior": expected_preimage,
                "state": image,
                "callable": "NEW_FUNCTIONTYPE_ONLY_PRIVATE_TEMPFILE_DIFFERS",
                "native_operation_adopted": False,
                "directory_metadata_reserved": False,
                "dual_host_reserved": False,
                "restore_reserved": False,
            }
            physical._fixed_write(self.root / "receipts" / str(index), receipt)
            self._point("receipt_written")
            self._guard()
            control.update(
                operation=None,
                current=image,
                last={
                    "slot": index,
                    "receipt_sha256": physical._sha(physical._encoded(receipt)),
                },
            )
            physical._fixed_write(self.root / "control", control)
            return receipt
        finally:
            if self._handle is not None:
                self._handle.abort()
            self._active = None

    # Validate the exact local receipt schema without interpreting native account bytes.
    def _receipt(self, receipt, control):
        expected = {
            "version",
            "identity_sha256",
            "adapter_sha256",
            "writer_sha256",
            "slot",
            "prior",
            "state",
            "callable",
            "native_operation_adopted",
            "directory_metadata_reserved",
            "dual_host_reserved",
            "restore_reserved",
        }
        physical._require(
            type(receipt) is dict and set(receipt) == expected,
            "Exact local receipt required",
        )
        physical._require(
            receipt["version"] == VERSION
            and receipt["identity_sha256"] == self.header["identity_sha256"]
            and receipt["adapter_sha256"] == self.header["adapter_sha256"]
            and receipt["writer_sha256"] == physical.PAPER
            and type(receipt["slot"]) is int
            and receipt["slot"] == control["last"]["slot"]
            and receipt["callable"] == "NEW_FUNCTIONTYPE_ONLY_PRIVATE_TEMPFILE_DIFFERS",
            "Local receipt source differs",
        )
        physical._require(
            all(
                receipt[key] is False
                for key in (
                    "native_operation_adopted",
                    "directory_metadata_reserved",
                    "dual_host_reserved",
                    "restore_reserved",
                )
            ),
            "Unsupported local receipt claim",
        )
        self._preimage(receipt["state"])
        if receipt["prior"] is not None:
            self._preimage(receipt["prior"])

    # Read latest locally committed bytes, never an OPEN writer's readable orphan.
    def completed(self):
        self._guard()
        with self._locked(shared=True):
            control = self._control()
            physical._require(
                control["operation"] is None and control["last"] is not None,
                "No local completion; OPEN writer cannot be adopted",
            )
            receipt = physical._fixed_read(
                self.root / "receipts" / str(control["last"]["slot"])
            )
            self._receipt(receipt, control)
            physical._require(
                physical._sha(physical._encoded(receipt))
                == control["last"]["receipt_sha256"]
                and receipt["state"]
                == control["current"]
                == _image(self.root / "work/paper/state.json")
                and self._control() == control,
                "Local writer completion differs",
            )
            return receipt

