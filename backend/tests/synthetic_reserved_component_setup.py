"""Synthetic setup-only copies; no previously closed test scenario is present."""
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


