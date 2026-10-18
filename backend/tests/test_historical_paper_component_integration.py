"""Source-isolated component receipts using real native bytes, Store and checkpoints.

The runner supplies CURRENT/native fixtures. Exact Nightly/Cycle CodeTypes run
with an explicitly synthetic broker codec, latch path and source-marker globals.
No model, broker, sender, full Cycle/Nightly constructor or settlement body runs.
"""

import builtins
import ast
from copy import deepcopy
from dataclasses import fields
from datetime import date
import hashlib
import io
import json
import os
from pathlib import Path
import stat
import tempfile
import types
from types import SimpleNamespace
import unittest

from backend.agents.trading.desk import paper
from backend.market import historical_packet_demand as demand
from backend.market import historical_paper_component as component
from backend.market import historical_physical_checkpoint as physical
from backend.market import historical_timing_packet as packet
from backend.market.historical_packet_store import Store, StorePause


# Refuse fixture conditions without importing the real model/forecast module.
def require(condition, message):
    if not condition:
        raise ValueError(message)


# Keep the unchanged bounded legacy reader's native file identity in the fixture.
def identity(path):
    value = Path(path).stat(follow_symlinks=False)
    return value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns, value.st_ctime_ns


# Represent only an unchanged finite synthetic broker component, never an account.
def broker_encode(client, **pins):
    require(client == "SYNTHETIC_BROKER", "Synthetic broker fixture required")
    return b'{"scope":"SYNTHETIC_BROKER_COMPONENT"}'


# Authenticate the actual persisted broker bytes at the restore boundary.
def broker_restore(body, *, expected_sha256, **pins):
    require(hashlib.sha256(body).hexdigest() == expected_sha256, "Broker hash")
    require(body == broker_encode("SYNTHETIC_BROKER"), "Broker bytes")
    return "SYNTHETIC_BROKER"


# Give the isolated receipt a declared synthetic latch path without sender imports.
def latch_path(root, session):
    return Path(root) / "synthetic-latch" / (session.isoformat() + ".json")


# Load exact complete-source CodeTypes while leaving all application imports unrun.
def boundary_namespace(name):
    source = Path('/audit/backend/market') / (name + '.py')
    code = compile(source.read_bytes(), str(source), 'exec', dont_inherit=True)
    codes = {item.co_name: item for item in code.co_consts if isinstance(item, types.CodeType)}
    marker = SimpleNamespace(__file__=__file__)
    namespace = {
        '__name__': 'SYNTHETIC_COMPONENT_BOUNDARY', '__file__': str(source),
        '__builtins__': builtins.__dict__, 'Path': Path, 'os': os, 'stat': stat,
        'io': io, 'hashlib': hashlib, 'sha256': hashlib.sha256, 'deepcopy': deepcopy,
        'date': date, 'fields': fields, 'paper': paper, 'packet': packet,
        'demand': demand, 'StorePause': StorePause, 'META_CAP': 262144, 'CAP': 262144,
        'DAY': date(2019, 3, 1), 'CURRENT': physical.CURRENT,
        'market': marker, 'completion': marker,
        'entry_timing': SimpleNamespace(latch_path=latch_path),
        'codec': SimpleNamespace(encode=broker_encode, restore=broker_restore,
                                 CAPS={'bytes': 65536}),
        'admitted': SimpleNamespace(require=require, identity=identity,
                                    encoded=demand.encoded, decoded=packet._decode),
    }
    selected = ({'physical_identity', 'physical', 'put', 'components'}
        if name == 'historical_conditional_nightly' else
        {'sha', '_file', '_put', '_components', '_receipt', '_read_receipt',
         '_final_settlement', 'restore_receipt', 'restore_operation'})
    declarations = {node.name: node for node in ast.parse(source.read_bytes()).body
                    if isinstance(node, ast.FunctionDef)}
    for key in selected:
        function = types.FunctionType(codes[key], namespace)
        declaration = declarations[key]
        function.__defaults__ = tuple(default_value(node, namespace)
                                      for node in declaration.args.defaults) or None
        function.__kwdefaults__ = {
            argument.arg: default_value(node, namespace)
            for argument, node in zip(declaration.args.kwonlyargs, declaration.args.kw_defaults)
            if node is not None
        }
        namespace[key] = function
    if name == 'historical_conditional_nightly':
        namespace['Nightly'] = builtins.__build_class__(
            types.FunctionType(codes['Nightly'], namespace), 'Nightly')
    return namespace


# Restore only original literal/name defaults; no application expression is evaluated.
def default_value(node, namespace):
    if isinstance(node, ast.Name):
        return namespace[node.id]
    require(isinstance(node, ast.Constant), 'Only source literal/name defaults')
    return node.value


# Test persisted component receipts without admitting any genuine trading workflow.
class PaperComponentIntegrationTests(unittest.TestCase):
    # Read only the externally pinned public CURRENT identity.
    @classmethod
    def setUpClass(cls):
        cls.profile = json.loads(Path('/fixture/current-identity.json').read_bytes())
        cls.pin = physical._sha(physical._encoded(cls.profile))
        cls.writer = Path(paper.__file__).resolve()

    # Reserve a small finite raw checkpoint and create an actual private SQLite/CAS Store.
    def setUp(self):
        parent = Path('/out/cases')
        parent.mkdir(mode=0o700, exist_ok=True)
        self.root = Path(tempfile.mkdtemp(prefix=self._testMethodName + '-', dir=parent))
        self.store = Store(self.root / 'store', self.pin, None, create=True)
        self.account = self.store.root / 'synthetic-account'
        self.account.mkdir(mode=0o700)
        self.raw = physical.reserve(
            self.root / 'checkpoint', identity=self.profile, identity_sha256=self.pin,
            writer=self.writer, limits={
                'span_bytes': 65536, 'raw_bytes': 1024 * 1024, 'history_rows': 32,
                'body_slots': 32, 'page_slots': 24, 'directory_headroom_bytes': 65536,
            })
        self.pins = {'identity': self.profile, 'identity_sha256': self.pin}
        self.nightly = boundary_namespace('historical_conditional_nightly')
        self.cycle = boundary_namespace('historical_conditional_cycle')

    # Release the actual Store writer lock without deleting retained test evidence.
    def tearDown(self):
        self.store.close()

    # Write real native dataclass bytes with large history and optional native NaN.
    def write(self, *, large=True, nonfinite=True):
        state = paper.PaperState(
            start_equity=float('nan') if nonfinite else 100000,
            history=[{'synthetic_row': index, 'text': 'x' * 25000}
                     for index in range(12)] if large else [],
        )
        return paper.save_state(self.account, state).read_bytes()

    # Persist one actual versioned Cycle receipt through the production helper body.
    def receipt(self, *, raw=True, settle=False):
        return self.cycle['_receipt'](
            self.store, 'SYNTHETIC_BROKER', self.account, self.pins,
            {'stage': 'SYNTHETIC_COMPONENT_SNAPSHOT'},
            raw_checkpoint=self.raw if raw else None, settle_current=settle)

    # Authenticate raw Nightly components and actual persisted finite broker bytes.
    def test_nightly_component_capture_retains_large_nan(self):
        original = self.write()
        refs = self.nightly['components'](
            self.store, 'SYNTHETIC_BROKER', self.account, self.pins,
            raw_checkpoint=self.raw)
        self.assertEqual(self.store.read_blob(refs['broker'], limit=65536), broker_encode('SYNTHETIC_BROKER'))
        root = component.verify(refs['paper'], self.raw, expected_identity=self.pin)
        self.assertEqual(root['raw_sha256'], hashlib.sha256(original).hexdigest())
        self.assertGreater(root['raw_bytes'], 262144)
        self.assertEqual(root['history_rows'], 12)
        self.assertIn(b'NaN', original)
        self.assertFalse(refs['paper']['native_operation_committed'])

    # Read a persisted CAS receipt after Store reopen and restore the exact native path.
    def test_cycle_v2_persistence_restore_and_native_roundtrip(self):
        original = self.write()
        reference = self.receipt()
        value = packet._decode(self.store.read_blob(reference, limit=262144))
        self.assertEqual(value['schema'], 'private-conditional-cycle-receipt/2')
        self.assertIs(type(value['components']['paper']), dict)
        self.store.close()
        self.store = Store(self.root / 'store', self.pin, None)
        reopened = physical.PhysicalCheckpoint(self.raw.root, identity_sha256=self.pin, writer=self.writer)
        fresh = self.store.root / 'fresh-native-account'
        client, readback = self.cycle['restore_receipt'](
            self.store, reference, fresh, pins=self.pins, raw_checkpoint=reopened)
        self.assertEqual(client, 'SYNTHETIC_BROKER')
        self.assertEqual(readback, value)
        target = paper.state_path(fresh)
        self.assertEqual(target.read_bytes(), original)
        self.assertEqual(target.stat().st_ino, (reopened.root / 'restore').stat().st_ino)
        paper.save_state(fresh, paper.load_state(fresh))
        self.assertEqual(target.read_bytes(), original)
        self.assertEqual(paper.state_path(self.account).read_bytes(), original)

    # Older captured content remains readable while a reserved restore remains one-shot.
    def test_older_reference_and_consumed_restore(self):
        original = self.write()
        prior = component.capture(self.raw, paper.state_path(self.account), expected_identity=self.pin)
        paper.save_state(self.account, paper.PaperState(history=[{'later': True}]))
        current = component.capture(self.raw, paper.state_path(self.account), expected_identity=self.pin)
        self.assertNotEqual(prior['checkpoint'], current['checkpoint'])
        with self.assertRaisesRegex(physical.PhysicalPause, 'completed local capture'):
            self.raw.completed(prior['checkpoint'])
        self.assertEqual(component.verify(prior, self.raw, expected_identity=self.pin)['raw_sha256'], hashlib.sha256(original).hexdigest())
        first = self.root / 'first-restored.json'
        component.restore(prior, self.raw, first, expected_identity=self.pin)
        self.assertEqual(first.read_bytes(), original)
        second = self.root / 'second-restored.json'
        with self.assertRaisesRegex(physical.PhysicalPause, 'already consumed'):
            component.restore(current, self.raw, second, expected_identity=self.pin)
        self.assertFalse(second.exists())
        self.assertIsNone(physical._fixed_read(self.raw.root / 'control')['operation'])

    # Reject every altered descriptor binding rather than accepting a count-only match.
    def test_descriptor_tampering_is_refused(self):
        self.write()
        valid = component.capture(self.raw, paper.state_path(self.account), expected_identity=self.pin)
        changes = {
            'schema': 'unknown/1', 'scope': 'ADMITTED', 'identity_sha256': '0' * 64,
            'primitive_sha256': '0' * 64, 'adapter_sha256': '0' * 64,
            'limits_sha256': '0' * 64, 'raw_sha256': '0' * 64,
            'raw_bytes': True, 'history_rows': 12.0,
            'native_operation_committed': True, 'durable_simulator_adoption': True,
            'checkpoint': {'sha256': '../not-a-path', 'length': 1},
        }
        for name, value in changes.items():
            with self.subTest(field=name):
                changed = {**valid, name: value}
                with self.assertRaises((ValueError, OSError)):
                    component.verify(changed, self.raw, expected_identity=self.pin)
        with self.assertRaises(ValueError):
            component.verify({**valid, 'extra': True}, self.raw, expected_identity=self.pin)
        self.assertEqual(component.verify(valid, self.raw, expected_identity=self.pin)['raw_bytes'], valid['raw_bytes'])

    # Reject account mismatches before capture can change the raw control marker.
    def test_cross_account_capture_is_refused(self):
        self.write()
        before = physical._fixed_read(self.raw.root / 'control')
        with self.assertRaisesRegex(physical.PhysicalPause, 'same-account'):
            component.capture(self.raw, paper.state_path(self.account), expected_identity='0' * 64)
        self.assertEqual(physical._fixed_read(self.raw.root / 'control'), before)

    # Keep the default finite small-state blob representation and restore unchanged.
    def test_legacy_finite_blob_receipt_and_restore(self):
        original = self.write(large=False, nonfinite=False)
        reference = self.receipt(raw=False)
        value = self.cycle['_read_receipt'](self.store, reference, self.pins)
        self.assertEqual(value['schema'], 'private-conditional-cycle-receipt/1')
        self.assertIs(type(value['components']['paper']), str)
        self.assertEqual(self.store.read_blob(value['components']['paper'], limit=262144), original)
        fresh = self.store.root / 'legacy-restored'
        self.cycle['restore_receipt'](self.store, reference, fresh, pins=self.pins)
        self.assertEqual(paper.state_path(fresh).read_bytes(), original)

    # Reproduce both legacy component boundaries without weakening their caps/parsers.
    def test_legacy_large_and_nan_still_refuse(self):
        self.write()
        with self.assertRaisesRegex(ValueError, '256KiB cap'):
            self.nightly['components'](self.store, 'SYNTHETIC_BROKER', self.account, self.pins)
        with self.assertRaisesRegex(StorePause, 'cap'):
            self.cycle['_components'](self.store, 'SYNTHETIC_BROKER', self.account, self.pins)
        original = self.write(large=False)
        with self.assertRaisesRegex(StorePause, 'exact bytes retained'):
            self.nightly['components'](self.store, 'SYNTHETIC_BROKER', self.account, self.pins)
        with self.assertRaises(ValueError):
            self.cycle['_components'](self.store, 'SYNTHETIC_BROKER', self.account, self.pins)
        self.assertEqual(paper.state_path(self.account).read_bytes(), original)

    # Raw settlement refuses before capture or native fold/save, preserving all bytes.
    def test_raw_settlement_is_refused_before_work(self):
        original = self.write()
        before = physical._fixed_read(self.raw.root / 'control')
        with self.assertRaisesRegex(ValueError, 'settlement is not admitted'):
            self.receipt(settle=True)
        self.assertEqual(physical._fixed_read(self.raw.root / 'control'), before)
        reference = self.receipt()
        value = self.cycle['_read_receipt'](self.store, reference, self.pins, raw_checkpoint=self.raw)
        with self.assertRaisesRegex(ValueError, 'settlement is not admitted'):
            self.cycle['_final_settlement'](self.store, value, self.pins)
        forged = {**value, 'current_settlement_sha256': '0' * 64}
        encoded = demand.encoded(forged)
        digest = self.store.put_stream(io.BytesIO(encoded), limit=262144)[0]
        with self.assertRaisesRegex(ValueError, 'settlement not admitted'):
            self.cycle['_read_receipt'](self.store, digest, self.pins, raw_checkpoint=self.raw)
        self.assertEqual(paper.state_path(self.account).read_bytes(), original)

    # Require explicit external storage and prevent raw references masquerading as v1.
    def test_receipt_storage_modes_are_distinct(self):
        self.write()
        reference = self.receipt()
        with self.assertRaisesRegex(ValueError, 'storage required'):
            self.cycle['_read_receipt'](self.store, reference, self.pins)
        value = packet._decode(self.store.read_blob(reference, limit=262144))
        value['schema'] = 'private-conditional-cycle-receipt/1'
        body = demand.encoded(value)
        forged = self.store.put_stream(io.BytesIO(body), limit=262144)[0]
        with self.assertRaisesRegex(ValueError, 'storage mode differs'):
            self.cycle['_read_receipt'](self.store, forged, self.pins)

    # Keep raw components outside standalone Nightly v1 completion and continuation.
    def test_nightly_raw_continuation_remains_closed(self):
        self.write()
        refs = self.nightly['components'](self.store, 'SYNTHETIC_BROKER', self.account,
                                          self.pins, raw_checkpoint=self.raw)
        instance = object.__new__(self.nightly['Nightly'])
        with self.assertRaisesRegex(ValueError, 'continuation is not admitted'):
            instance.complete(None, None, {'components': refs})
        instance.store = self.store
        body = demand.encoded({'schema': 'standalone-current-nightly/1',
            'components': refs, 'identity': self.pin, 'packet_pipeline_integrated': False,
            'publication_barrier': 'CLOSED'})
        digest = self.store.put_stream(io.BytesIO(body), limit=262144)[0]
        with self.assertRaisesRegex(ValueError, 'Original standalone nightly'):
            instance.read_original(digest)

    # Keep the owning legacy predecessor bridge pinned to the edited Cycle source.
    def test_nightly_cycle_source_pin_matches(self):
        root = Path('/audit/backend/market')
        tree = ast.parse((root / 'historical_conditional_nightly.py').read_bytes())
        values = [node.value.value for node in tree.body
                  if isinstance(node, ast.Assign) and len(node.targets) == 1
                  and isinstance(node.targets[0], ast.Name)
                  and node.targets[0].id == 'CYCLE']
        self.assertEqual(values, [hashlib.sha256(
            (root / 'historical_conditional_cycle.py').read_bytes()).hexdigest()])
