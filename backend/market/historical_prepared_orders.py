"""PRIVATE order containers prepared before resolution, populated from real results.

The reconciliation entry below is explicitly DERIVED: only its late orders copy
is replaced. The original module and its default reconciliation API are unchanged.
No execution values are copied into the prepared containers before resolution.
"""
import ast
from copy import deepcopy
from hashlib import sha256
from pathlib import Path
from types import CodeType, FunctionType

from backend.market import historical_broker_checkpoint as codec
from backend.market import historical_packet_demand as demand
from backend.market import replay_broker as native

SCHEMA = 'synthetic-prepared-native-orders/1'
MODE = 'PRIVATE_DERIVED_RECONCILE_NOT_UNCHANGED_WHOLE_FUNCTION'
SETTLEMENT_SHA = '36372b959a59650a259328478709038fa21676c22324c031cc3f7255f5b7c28e'
BROKER_SHA = 'c3d427e180e6b7527d3b666a450c6076b24e1cd75bfce1786852dced9eb2d616'
EXTRA = ('filled_at', 'expired_at')
CAP = 262144


# Bind the unchanged native in-place mutation rules and original complete reconciliation source.
def sources():
    paths = {'adapter': Path(__file__), 'broker': Path(native.__file__),
             'reconciliation': Path(__file__).with_name('historical_conditional_settlement.py')}
    if any(path.stat().st_size > CAP for path in paths.values()):
        raise ValueError('Finite prepared-order source bytes required')
    result = {name: sha256(path.read_bytes()).hexdigest() for name, path in paths.items()}
    if result['broker'] != BROKER_SHA or result['reconciliation'] != SETTLEMENT_SHA:
        raise ValueError('Exact original prepared-order mutation and reconciliation sources required')
    return result


# Replace exactly one original orders allocation, keeping every other reconciliation statement intact.
def derive(original):
    path = Path(original.__globals__['__file__'])
    raw = path.read_bytes()
    if len(raw) > CAP or sha256(raw).hexdigest() != SETTLEMENT_SHA:
        raise ValueError('Original complete reconciliation source required')
    complete = compile(raw, str(path), 'exec', dont_inherit=True)
    expected = next(c for c in complete.co_consts if type(c) is CodeType and c.co_name == 'reconcile_raw')
    if original.__code__ != expected:
        raise ValueError('Original complete reconciliation CodeType required')
    node = next(n for n in ast.parse(raw).body if isinstance(n, ast.FunctionDef) and n.name == 'reconcile_raw')
    old = ast.parse('orders = deepcopy(list(client._orders.values()))').body[0]
    matches = [n for n in node.body if ast.dump(n, include_attributes=False) == ast.dump(old, include_attributes=False)]
    if len(matches) != 1:
        raise ValueError('Exact sole original reconciliation orders-copy statement required')
    derived = deepcopy(node)
    index = node.body.index(matches[0])
    derived.body[index] = ast.copy_location(ast.parse('orders = prepared_orders.take(client)').body[0], matches[0])
    derived.name = '_derived_reconcile_prepared_orders'
    derived.args.kwonlyargs.append(ast.arg(arg='prepared_orders'))
    derived.args.kw_defaults.append(None)
    tree = ast.fix_missing_locations(ast.Module(body=[derived], type_ignores=[]))
    code = next(c for c in compile(tree, str(path) + '[DERIVED prepared orders]', 'exec', dont_inherit=True).co_consts
                if type(c) is CodeType and c.co_name == derived.name)
    result = FunctionType(code, dict(original.__globals__), derived.name, original.__defaults__)
    result.__kwdefaults__ = dict(original.__kwdefaults__ or {})
    return result


# Read only the persisted source/head/input and original container-shape metadata during recovery.
def read_descriptor(value, binding):
    if type(value) is not dict or set(value) != {'schema', 'mode', 'sources', 'input_sha256', 'orders', 'shape_bytes', 'shape_sha256'}:
        raise ValueError('Exact original prepared-order descriptor required')
    if (value['schema'] != SCHEMA or value['mode'] != MODE or value['sources'] != sources()
            or value['input_sha256'] != sha256(demand.encoded(binding)).hexdigest()
            or type(value['orders']) is not int or not 0 <= value['orders'] <= codec.CAPS['orders']
            or type(value['shape_bytes']) is not int or not 0 < value['shape_bytes'] <= CAP):
        raise ValueError('Original prepared-order source/head/input/shape binding required')
    digest = value['shape_sha256']
    if type(digest) is not str or len(digest) != 64 or any(c not in '0123456789abcdef' for c in digest):
        raise ValueError('Original prepared-order shape digest required')
    return value


# Own detached preallocated containers while all native execution values remain solely in the broker.
class PreparedOrders:
    # Allocate list/dictionary containers and certify the derived entry before selected native effects.
    def __init__(self, client, binding, reconcile, pins):
        self.client = client
        self.orders = self.original_orders = self.rows = self.pairs = None
        self.derived = self.original_function = self.original_globals = None
        self.used = self.failed = self.closed = False
        try:
            if type(client) is not native.ReplayBroker:
                raise ValueError('Exact original native broker required')
            codec.encode(client, **pins)
            self.pairs = tuple((cid, row, tuple(row)) for cid, row in client._orders.items())
            shape = demand.encoded([(cid, keys) for cid, _, keys in self.pairs])
            if len(shape) > CAP:
                raise ValueError('Original finite order-container shape allowance exceeded')
            self.binding = {'schema': SCHEMA, 'mode': MODE, 'sources': sources(),
                'input_sha256': sha256(demand.encoded(binding)).hexdigest(), 'orders': len(self.pairs),
                'shape_bytes': len(shape), 'shape_sha256': sha256(shape).hexdigest()}
            self.raw = demand.encoded(self.binding)
            self.input_binding = deepcopy(binding)
            self.empty = object()
            self.orders = self.original_orders = [dict.fromkeys(keys + tuple(k for k in EXTRA if k not in keys), self.empty)
                                                   for _, _, keys in self.pairs]
            self.rows = tuple(self.orders)
            self.original_function = reconcile
            self.original_code = reconcile.__code__
            self.original_globals = dict(reconcile.__globals__)
            self.derived = derive(reconcile)
            self.derived_code = self.derived.__code__
            self.check(client, binding, self.binding)
        except BaseException:
            self.failed = True
            self.close()
            raise

    # Recheck original containers and native row identities without freezing mutable execution values.
    def check(self, client, binding, descriptor):
        try:
            if (self.closed or self.failed or type(self.used) is not bool or client is not self.client
                    or self.orders is not self.original_orders or len(self.orders) != len(self.rows)
                    or len(client._orders) != len(self.pairs) or demand.encoded(descriptor) != self.raw
                    or demand.encoded(self.binding) != self.raw
                    or self.original_function.__code__ is not self.original_code or self.derived.__code__ is not self.derived_code
                    or set(self.original_function.__globals__) != set(self.original_globals)
                    or set(self.derived.__globals__) != set(self.original_globals)
                    or any(self.original_function.__globals__[k] is not v or self.derived.__globals__[k] is not v
                           for k, v in self.original_globals.items())):
                raise ValueError('Original owned prepared-order containers required')
            read_descriptor(descriptor, binding)
            for index, ((cid, row, keys), (live_cid, live_row)) in enumerate(zip(self.pairs, client._orders.items())):
                target = self.orders[index]
                if (cid != live_cid or row is not live_row or target is not self.rows[index] or target is row
                        or any(k not in row for k in keys) or any(k not in keys and k not in EXTRA for k in row)):
                    raise ValueError('Original prepared-order row/key identity required')
                if tuple(row) != keys + tuple(k for k in EXTRA if k not in keys and k in row):
                    raise ValueError('Original native order field ordering required')
                if self.used:
                    if tuple(target) != tuple(row) or any(type(target[k]) is not type(v) or target[k] != v for k, v in row.items()):
                        raise ValueError('Actual once-copied native order values changed')
                elif any(v is not self.empty for v in target.values()):
                    raise ValueError('Prepared containers cannot pre-snapshot native execution values')
        except BaseException:
            self.failed = True
            raise

    # Copy only actual post-resolution immutable scalar fields into the original containers once.
    def take(self, client):
        try:
            self.check(client, self.input_binding, self.binding)
            if self.closed or self.failed or self.used or client is not self.client:
                raise ValueError('Original once-only prepared orders required')
            if len(client._orders) != len(self.pairs):
                raise ValueError('Original prepared-order membership changed')
            for index, ((cid, row, keys), (live_cid, live_row)) in enumerate(zip(self.pairs, client._orders.items())):
                target = self.orders[index]
                if (cid != live_cid or row is not live_row or target is not self.rows[index]
                        or any(k not in row for k in keys) or any(k not in target for k in row)
                        or any(v is not self.empty for v in target.values())
                        or any(type(v) not in (str, int, float, bool, type(None)) for v in row.values())):
                    raise ValueError('Original actual native scalar orders and owned empty containers required')
            self.used = True
            for target, (_, row, _) in zip(self.orders, self.pairs):
                for key in EXTRA:
                    if key in target and key not in row:
                        del target[key]
                for key, value in row.items():
                    target[key] = value
            return self.orders
        except BaseException:
            self.failed = True
            raise

    # Run the explicitly derived reconciliation after real resolution using this original typed owner.
    def reconcile(self, original, client, state, **kwargs):
        if self.closed or self.failed or original is not self.original_function or client is not self.client:
            self.failed = True
            raise ValueError('Original derived reconciliation and prepared orders required')
        try:
            return self.derived(client, state, prepared_orders=self, **kwargs)
        except BaseException:
            self.failed = True
            raise

    # Validate original consumed metadata after all native/container references have been released.
    def check_released(self, binding, descriptor):
        if (not self.closed or self.failed or self.used is not True or any(v is not None for v in
                (self.client, self.orders, self.original_orders, self.rows, self.pairs, self.derived,
                 self.original_function, self.original_globals)) or demand.encoded(descriptor) != self.raw
                or demand.encoded(self.binding) != self.raw):
            raise ValueError('Original consumed and released prepared orders required')
        read_descriptor(descriptor, binding)

    # Release native rows, output containers and function globals on success and every failure path.
    def close(self):
        self.closed = True
        self.client = self.orders = self.original_orders = self.rows = self.pairs = None
        self.derived = self.original_function = self.original_globals = None
