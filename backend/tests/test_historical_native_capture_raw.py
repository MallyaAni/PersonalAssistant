"""Observer integration over synthetic states, without importing a model.

The Linux runner supplies the pinned CURRENT declaration and readable native
source. NativeCapture is instantiated from its exact complete-source CodeType
with explicitly synthetic broker/policy bindings. The actual imported native
writer and actual checkpoint execute; whole Nightly/model admission is excluded.
"""

import builtins
import hashlib
import io
import json
import os
import tempfile
import types
import unittest
from pathlib import Path
from threading import Lock, get_ident
from types import SimpleNamespace

from backend.agents.trading.desk import paper
from backend.market import historical_physical_checkpoint as raw


# Refuse fixture conditions without importing the application or its model closure.
def require(condition, message):
    if not condition:
        raise ValueError(message)


# Retain the same physical identity fields as the real bounded observer reader.
def identity(path):
    info = Path(path).stat(follow_symlinks=False)
    require(Path(path).is_file() and not Path(path).is_symlink(), "Regular file")
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns


# Provide only the exact broker type/submit boundary needed by the observer fixture.
class SyntheticBroker:
    # Record whether the observer allowed a submission to reach its effect boundary.
    def __init__(self):
        self.calls = 0

    # Make any unexpected broker invocation observable in a datastore-free fixture.
    def _submit(self, *args, **kwargs):
        self.calls += 1
        raise AssertionError("Submission crossed the raw-only observer boundary")


# Provide only the exact policy type required at this isolated observer boundary.
class SyntheticPolicy:
    # Fail if this write-only test accidentally enters planning or model execution.
    def decide(self, *args, **kwargs):
        raise AssertionError("No model decision is in this fixture")


# Use full-source code objects rather than a rewritten copy of the observer logic.
def observer_namespace():
    source = Path("/audit/backend/market/historical_conditional_nightly.py")
    module = compile(source.read_bytes(), str(source), "exec", dont_inherit=True)
    codes = {
        item.co_name: item
        for item in module.co_consts
        if isinstance(item, types.CodeType)
    }
    namespace = {
        "__name__": "SYNTHETIC_NATIVE_CAPTURE_BOUNDARY",
        "__builtins__": builtins.__dict__,
        "Path": Path,
        "stat": __import__("stat"),
        "os": os,
        "io": io,
        "sha256": hashlib.sha256,
        "get_ident": get_ident,
        "LOCK": Lock(),
        "CAP": 256 * 1024,
        "paper": paper,
        "SAVE_STATE": paper.save_state,
        "native": SimpleNamespace(ReplayBroker=SyntheticBroker),
        "SUBMIT": SyntheticBroker._submit,
        "FrozenCurrentGradePolicy": SyntheticPolicy,
        "admitted": SimpleNamespace(require=require, identity=identity),
    }
    for name in ("physical_identity", "physical", "put"):
        namespace[name] = types.FunctionType(codes[name], namespace)
    namespace["NativeCapture"] = builtins.__build_class__(
        types.FunctionType(codes["NativeCapture"], namespace), "NativeCapture"
    )
    return namespace


# Exercise the actual save observer and local raw capture, never a genuine account.
class NativeCaptureRawTests(unittest.TestCase):
    # Read the external public CURRENT identity before any synthetic writes.
    @classmethod
    def setUpClass(cls):
        cls.profile = json.loads(Path("/fixture/current-identity.json").read_bytes())
        cls.pin = raw._sha(raw._encoded(cls.profile))
        cls.writer = Path(paper.__file__).resolve()

    # Allocate a fresh finite checkpoint before entering the native observer scope.
    def setUp(self):
        parent = Path(os.environ.get("ANIOS_RAW_OBSERVER_OUT", "/out/cases"))
        parent.mkdir(mode=0o700, exist_ok=True)
        self.root = Path(tempfile.mkdtemp(prefix=self._testMethodName + "-", dir=parent))
        self.account = self.root / "synthetic-account"
        self.account.mkdir(mode=0o700)
        self.namespace = observer_namespace()
        self.client, self.policy = SyntheticBroker(), SyntheticPolicy()
        self.checkpoint = raw.reserve(
            self.root / "checkpoint",
            identity=self.profile,
            identity_sha256=self.pin,
            writer=self.writer,
            limits={
                "span_bytes": 65536,
                "raw_bytes": 1024 * 1024,
                "history_rows": 32,
                "body_slots": 24,
                "page_slots": 12,
                "directory_headroom_bytes": 65536,
            },
        )
        self.store = SimpleNamespace(identity=self.pin)
        self.original_save = paper.save_state
        self.assertTrue(self.namespace["LOCK"].acquire(blocking=False))

    # Check every observer restored the native hook even after a capture refusal.
    def tearDown(self):
        self.assertIs(paper.save_state, self.original_save)
        self.assertIs(SyntheticBroker._submit, self.namespace["SUBMIT"])
        self.namespace["LOCK"].release()

    # Generate actual native dataclass output above the old cap with opaque NaN bytes.
    def state(self):
        return paper.PaperState(
            start_equity=float("nan"),
            history=[{"synthetic_row": index, "text": "x" * 25000} for index in range(12)],
        )

    # Reproduce the original first failure after the real writer already persisted.
    def test_default_reader_still_refuses_large_native_write(self):
        capture = self.namespace["NativeCapture"](
            self.store, self.account, self.client, self.policy
        )
        with capture:
            with self.assertRaisesRegex(ValueError, "256KiB cap"):
                paper.save_state(self.account, self.state())
        body = paper.state_path(self.account).read_bytes()
        self.assertGreater(len(body), 256 * 1024)
        self.assertIn(b"NaN", body)
        self.assertEqual(capture.writes, [])
        self.assertEqual(capture.raw_writes, [])

    # Preserve exact native bytes through the observer and a fresh reserved restore.
    def test_large_nan_native_write_captures_and_restores_exactly(self):
        capture = self.namespace["NativeCapture"](
            self.store, self.account, self.client, self.policy,
            raw_checkpoint=self.checkpoint,
        )
        with capture:
            saved = paper.save_state(self.account, self.state())
        original = saved.read_bytes()
        self.assertGreater(len(original), 256 * 1024)
        self.assertIn(b"NaN", original)
        self.assertEqual(capture.writes, [])
        self.assertEqual(len(capture.raw_writes), 1)
        receipt = capture.raw_writes[0]
        self.assertEqual(receipt["schema"], "native-observer-raw-write/1")
        self.assertEqual(receipt["raw_sha256"], hashlib.sha256(original).hexdigest())
        self.assertEqual(receipt["raw_bytes"], len(original))
        self.assertEqual(receipt["identity_sha256"], self.pin)
        self.assertFalse(receipt["native_operation_committed"])
        self.assertFalse(receipt["durable_simulator_adoption"])
        fresh = self.root / "fresh-restored.json"
        reopened = raw.PhysicalCheckpoint(
            self.checkpoint.root, identity_sha256=self.pin, writer=self.writer
        )
        restored = reopened.restore(receipt["checkpoint"], fresh)
        self.assertEqual(fresh.read_bytes(), original)
        self.assertEqual(saved.read_bytes(), original)
        self.assertEqual(restored["history_rows"], 12)
        self.assertEqual(fresh.stat().st_ino, (reopened.root / "restore").stat().st_ino)
        roundtrip = self.root / "native-roundtrip"
        roundtrip.mkdir(mode=0o700)
        target = paper.state_path(roundtrip)
        target.parent.mkdir(mode=0o700)
        target.write_bytes(fresh.read_bytes())
        paper.save_state(roundtrip, paper.load_state(roundtrip))
        self.assertEqual(target.read_bytes(), original)

    # An opted-in write observer must not silently reuse legacy submission receipts.
    def test_raw_only_observer_blocks_before_broker_submission(self):
        capture = self.namespace["NativeCapture"](
            self.store, self.account, self.client, self.policy,
            raw_checkpoint=self.checkpoint,
        )
        with capture:
            with self.assertRaisesRegex(ValueError, "PAUSED before submit"):
                self.client._submit("SYNTHETIC")
        self.assertEqual(self.client.calls, 0)

    # Checkpoint capacity failure retains the completed native write and OPEN evidence.
    def test_checkpoint_refusal_never_repeats_or_erases_native_write(self):
        capture = self.namespace["NativeCapture"](
            self.store, self.account, self.client, self.policy,
            raw_checkpoint=self.checkpoint,
        )
        oversized = paper.PaperState(history=[{"text": "x" * 70000}])
        with capture:
            with self.assertRaisesRegex(raw.PhysicalPause, "line.*cap|span.*cap|bound"):
                paper.save_state(self.account, oversized)
        original = paper.state_path(self.account).read_bytes()
        self.assertIn(b"x" * 70000, original)
        self.assertEqual(capture.raw_writes, [])
        control = raw._fixed_read(self.checkpoint.root / "control")
        self.assertEqual(control["operation"], "CAPTURE")
        with self.assertRaisesRegex(raw.PhysicalPause, "remains OPEN"):
            self.checkpoint.capture(paper.state_path(self.account))
        self.assertEqual(paper.state_path(self.account).read_bytes(), original)

    # Refuse a cross-account checkpoint before installing any native observer hooks.
    def test_checkpoint_identity_must_match_observer_store(self):
        with self.assertRaisesRegex(ValueError, "same-account"):
            self.namespace["NativeCapture"](
                SimpleNamespace(identity="0" * 64), self.account,
                self.client, self.policy, raw_checkpoint=self.checkpoint,
            )
