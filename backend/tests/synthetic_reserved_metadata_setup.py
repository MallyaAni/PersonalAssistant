"""Synthetic setup-only copies; no previously closed test scenario is present."""
import builtins


from datetime import UTC, datetime


import hashlib


import json


from pathlib import Path


from threading import Lock, get_ident


import types


from types import SimpleNamespace


import unittest


from backend.agents.trading.desk import paper


from backend.market import historical_native_metadata as metadata


from backend.market import historical_packet_demand as demand


from backend.market import historical_packet_registry as registry


from backend.market import historical_physical_checkpoint as physical


from backend.market.historical_packet_store import Store, StorePause


from backend.tests import synthetic_reserved_component_setup as fixture


# Return synthetic decisions only, never a fitted policy or inference invocation.
class SyntheticPolicy:
    # Preserve the supplied synthetic native-domain values without conversion.
    def decide(self, value):
        return value['targets'], value['receipt']


# Make any attempted broker effect observable before it can occur.
class SyntheticBroker:
    # Refuse an unexpected invocation rather than simulating a successful order.
    def _submit(self, *args, **kwargs):
        raise AssertionError('Unexpected broker effect')


# Instantiate exact full-source methods with explicit synthetic outer bindings.
def namespace():
    result = fixture.boundary_namespace('historical_conditional_nightly')
    path = Path(result['__file__'])
    compiled = compile(path.read_bytes(), str(path), 'exec', dont_inherit=True)
    codes = {item.co_name: item for item in compiled.co_consts if isinstance(item, types.CodeType)}
    result.update({'datetime': datetime, 'UTC': UTC, 'get_ident': get_ident,
        'LOCK': Lock(), 'SAVE_STATE': paper.save_state, 'SUBMIT': SyntheticBroker._submit,
        'native': SimpleNamespace(ReplayBroker=SyntheticBroker),
        'FrozenCurrentGradePolicy': SyntheticPolicy,
        'sources': synthetic_sources, 'Store': Store})
    for name in ('sync_directory', 'write_once'):
        result[name] = types.FunctionType(codes[name], result)
    result['NativeCapture'] = builtins.__build_class__(
        types.FunctionType(codes['NativeCapture'], result), 'NativeCapture')
    return result


# Bind the actual edited source while declaring that full source admission is absent.
def synthetic_sources():
    path = Path('/audit/backend/market/historical_conditional_nightly.py')
    return {'SYNTHETIC_SOURCE_MANIFEST_ONLY': hashlib.sha256(path.read_bytes()).hexdigest()}


# Exercise only the new metadata and durable continuation acceptance boundary.
class RawNightlyMetadataTests(unittest.TestCase):

    # Reuse actual Store/checkpoint setup without loading any previously closed suite.
    def setUp(self):
        fixture.PaperComponentIntegrationTests.setUpClass()
        self.fixture = fixture.PaperComponentIntegrationTests()
        self.fixture.setUp()
        self.store, self.raw, self.account = self.fixture.store, self.fixture.raw, self.fixture.account
        self.raw = physical.reserve(self.fixture.root / 'metadata-checkpoint',
            identity=self.fixture.profile, identity_sha256=self.fixture.pin,
            writer=self.fixture.writer, limits={
                'span_bytes': 512 * 1024, 'raw_bytes': 1024 * 1024, 'history_rows': 32,
                'body_slots': 8, 'page_slots': 12, 'directory_headroom_bytes': 65536})
        self.ns = namespace()
        self.producer = hashlib.sha256(Path(self.ns['__file__']).read_bytes()).hexdigest()
        self.nightly = object.__new__(self.ns['Nightly'])
        self.nightly.store, self.nightly.root = self.store, self.account
        self.nightly.expected_head = None
        (self.account / 'operations').mkdir(mode=0o700)

    # Keep all evidence files and release the actual SQLite writer lock.
    def tearDown(self):
        self.store.close()


