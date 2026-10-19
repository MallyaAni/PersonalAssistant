"""PRIVATE preallocated native result storage, initialized only with actual outcomes.

Both settlement and reconciliation entries here are explicitly DERIVED. The
unchanged native initializer populates reserved private instances once after
resolution. Empty storage is never exposed as settlement evidence.
"""
import ast
from copy import deepcopy
from dataclasses import fields
from hashlib import sha256
from pathlib import Path
from types import CodeType, FunctionType

from backend.agents.trading.desk import paper
from backend.market import historical_packet_demand as demand
from backend.market import replay_broker as native

SCHEMA = 'synthetic-prepared-native-results/1'
MODE = 'PRIVATE_DERIVED_RESULT_STORAGE_NOT_NATIVE_WHOLE_FUNCTION'
PAPER_SHA = 'a8c5083f1828df7395164882ba877d5a134d55295d6a0cda0dcdc0047bcde42c'
RECONCILE_SHA = '36372b959a59650a259328478709038fa21676c22324c031cc3f7255f5b7c28e'
CLI_SHA = '0db03a31af2400d777d3a5b46b8fda96dbb3cc4ec32d8a39bee41be362afe819'
CAP = 262144
SETTLED, SETTLE = paper.Settled, paper.settle
INIT, INIT_CODE = SETTLED.__init__, SETTLED.__init__.__code__
SETTLE_CODE = SETTLE.__code__
NAMES = tuple(field.name for field in fields(SETTLED))


# Bind exact native record initialization, settlement and original pending-selection source bytes.
def sources():
    base = Path(paper.__file__).parents[3]
    paths = {'paper': Path(paper.__file__), 'adapter': Path(__file__),
        'reconciliation': Path(__file__).with_name('historical_conditional_settlement.py'),
        'cli': base / 'cli/market_daily.py'}
    if any(path.stat().st_size > CAP for path in paths.values()):
        raise ValueError('Finite original native result sources required')
    result = {name: sha256(path.read_bytes()).hexdigest() for name, path in paths.items()}
    if (result['paper'] != PAPER_SHA or result['reconciliation'] != RECONCILE_SHA or result['cli'] != CLI_SHA
            or paper.Settled is not SETTLED or SETTLED.__init__ is not INIT or INIT.__code__ is not INIT_CODE
            or SETTLED.__new__ is not object.__new__ or not SETTLED.__dataclass_params__.frozen
            or tuple(field.name for field in fields(SETTLED)) != NAMES
            or paper.settle is not SETTLE or SETTLE.__code__ is not SETTLE_CODE):
        raise ValueError('Original frozen native result type/initializer/settler required')
    return result


# Instantiate a derived function without executing any application module startup.
def function(node, path, namespace, defaults=None, kwdefaults=None):
    tree = ast.fix_missing_locations(ast.Module(body=[node], type_ignores=[]))
    code = next(c for c in compile(tree, str(path) + '[DERIVED result storage]', 'exec', dont_inherit=True).co_consts
                if type(c) is CodeType and c.co_name == node.name)
    result = FunctionType(code, dict(namespace), node.name, defaults)
    result.__kwdefaults__ = dict(kwdefaults or {})
    return result


# Replace only the native output-list initialization and record construction/append statement.
def derive_settle():
    path = Path(paper.__file__)
    raw = path.read_bytes()
    expected = next(c for c in compile(raw, str(path), 'exec', dont_inherit=True).co_consts
                    if type(c) is CodeType and c.co_name == 'settle')
    if expected != SETTLE_CODE:
        raise ValueError('Original complete native settle CodeType required')
    node = deepcopy(next(n for n in ast.parse(raw).body if isinstance(n, ast.FunctionDef) and n.name == 'settle'))
    allocation = ast.parse('out: list[Settled] = []').body[0]
    matches = [n for n in node.body if ast.dump(n, include_attributes=False) == ast.dump(allocation, include_attributes=False)]
    if len(matches) != 1:
        raise ValueError('Exact native result-list initialization required')
    index = node.body.index(matches[0])
    node.body[index] = ast.copy_location(ast.parse('out = prepared_results.begin(pending)').body[0], matches[0])
    loop = next(n for n in node.body if isinstance(n, ast.For))
    calls = [n for n in loop.body if isinstance(n, ast.Expr) and isinstance(n.value, ast.Call)
        and isinstance(n.value.func, ast.Attribute) and isinstance(n.value.func.value, ast.Name)
        and n.value.func.value.id == 'out' and n.value.func.attr == 'append']
    if len(calls) != 1:
        raise ValueError('Exact sole native result append required')
    original = calls[0].value.args[0]
    if not isinstance(original, ast.Call) or not isinstance(original.func, ast.Name) or original.func.id != 'Settled' or original.args or tuple(k.arg for k in original.keywords) != NAMES:
        raise ValueError('Exact complete native result constructor fields required')
    replacement = ast.Call(func=ast.Attribute(value=ast.Name(id='prepared_results', ctx=ast.Load()), attr='store', ctx=ast.Load()),
                           args=[], keywords=deepcopy(original.keywords))
    loop.body[loop.body.index(calls[0])] = ast.copy_location(ast.Expr(value=replacement), calls[0])
    node.name = '_derived_settle_preallocated_results'
    node.args.kwonlyargs.append(ast.arg(arg='prepared_results'))
    node.args.kw_defaults.append(None)
    return function(node, path, vars(paper), SETTLE.__defaults__, SETTLE.__kwdefaults__)


# Replace the two explicitly named order/result statements while preserving every other raw reconciliation statement.
def derive_reconcile(original):
    path = Path(original.__globals__['__file__'])
    raw = path.read_bytes()
    expected = next(c for c in compile(raw, str(path), 'exec', dont_inherit=True).co_consts
                    if type(c) is CodeType and c.co_name == 'reconcile_raw')
    if sha256(raw).hexdigest() != RECONCILE_SHA or original.__code__ != expected:
        raise ValueError('Original complete raw reconciliation required')
    node = deepcopy(next(n for n in ast.parse(raw).body if isinstance(n, ast.FunctionDef) and n.name == 'reconcile_raw'))
    for old, new in (('orders = deepcopy(list(client._orders.values()))', 'orders = prepared_orders.take(client)'),
                     ('settled = paper.settle(due, orders)', 'settled = prepared_results.settle(due, orders)')):
        target = ast.parse(old).body[0]
        matches = [n for n in node.body if ast.dump(n, include_attributes=False) == ast.dump(target, include_attributes=False)]
        if len(matches) != 1:
            raise ValueError('Exact original order/result reconciliation statements required')
        node.body[node.body.index(matches[0])] = ast.copy_location(ast.parse(new).body[0], matches[0])
    node.name = '_derived_reconcile_prepared_results'
    for name in ('prepared_orders', 'prepared_results'):
        node.args.kwonlyargs.append(ast.arg(arg=name))
        node.args.kw_defaults.append(None)
    return function(node, path, original.__globals__, original.__defaults__, original.__kwdefaults__)


# Authenticate original finite source/input/due-membership metadata without allocating any native results.
def read_descriptor(value, binding):
    if type(value) is not dict or set(value) != {'schema', 'mode', 'sources', 'input_sha256', 'resolution_at', 'due_ids', 'due_sha256', 'count', 'fields'}:
        raise ValueError('Exact original prepared-result descriptor required')
    ids = value['due_ids']
    if (value['schema'] != SCHEMA or value['mode'] != MODE or value['sources'] != sources()
            or value['input_sha256'] != sha256(demand.encoded(binding)).hexdigest()
            or type(ids) is not list or any(type(cid) is not str or not cid for cid in ids) or len(ids) != len(set(ids))
            or type(value['count']) is not int or value['count'] != len(ids) or value['fields'] != list(NAMES)
            or value['due_sha256'] != sha256(demand.encoded(ids)).hexdigest() or len(demand.encoded(value)) > CAP
            or type(value['resolution_at']) is not str or native._instant(value['resolution_at']).isoformat() != value['resolution_at']):
        raise ValueError('Original result source/input/due-membership fields required')
    return value


# Own private native-instance storage before effects and initialize each result exactly once from real outcomes.
class PreparedResults:
    # Select only original input membership and allocate empty storage without constructing settlement evidence.
    def __init__(self, prior, client, binding, reconcile, resolution_at):
        self.prior, self.client = prior, client
        self.output = self.original_output = self.rows = self.due = self.native_fn = self.reconcile_fn = None
        self.closed = self.failed = self.used = self.finished = False
        self.index = 0
        try:
            sources()
            self.pending_fn = reconcile.__globals__['market_daily']._reconciliation_pending
            self.pending_module = reconcile.__globals__['market_daily']
            self.ack_fn = self.pending_module._acknowledged
            self.pending_code, self.ack_code = self.pending_fn.__code__, self.ack_fn.__code__
            cli = Path(paper.__file__).parents[3] / 'cli/market_daily.py'
            codes = {c.co_name: c for c in compile(cli.read_bytes(), str(cli), 'exec', dont_inherit=True).co_consts
                     if type(c) is CodeType}
            if (self.pending_code != codes['_reconciliation_pending'] or self.ack_code != codes['_acknowledged']
                    or self.pending_fn.__globals__.get('_acknowledged') is not self.ack_fn):
                raise ValueError('Original complete pending-selection CodeTypes required')
            self.pending_globals = dict(self.pending_fn.__globals__)
            self.ack_globals = dict(self.ack_fn.__globals__)
            self.original = reconcile
            self.original_code = reconcile.__code__
            self.original_globals = dict(reconcile.__globals__)
            self.clock = native._instant(resolution_at)
            self.due = tuple(self.pending_fn(prior.pending, set(client._orders), self.clock))
            ids = [row['client_order_id'] for row in self.due]
            self.binding = {'schema': SCHEMA, 'mode': MODE, 'sources': sources(),
                'input_sha256': sha256(demand.encoded(binding)).hexdigest(), 'resolution_at': resolution_at,
                'due_ids': ids, 'due_sha256': sha256(demand.encoded(ids)).hexdigest(), 'count': len(ids), 'fields': list(NAMES)}
            read_descriptor(self.binding, binding)
            self.raw, self.input_binding = demand.encoded(self.binding), deepcopy(binding)
            self.empty = object()
            self.output = self.original_output = [object.__new__(SETTLED) for _ in self.due]
            for record in self.output:
                record.__dict__.update(dict.fromkeys(NAMES, self.empty))
            self.rows = tuple(self.output)
            self.native_fn, self.reconcile_fn = derive_settle(), derive_reconcile(reconcile)
            self.native_globals = dict(vars(paper))
            self.native_code, self.reconcile_code = self.native_fn.__code__, self.reconcile_fn.__code__
            self.check(prior, client, binding, self.binding)
        except BaseException:
            self.failed = True
            self.close()
            raise

    # Recheck original input membership and private storage ownership before any result can be consumed.
    def check(self, prior, client, binding, descriptor):
        try:
            if (self.closed or self.failed or prior is not self.prior or client is not self.client
                    or self.output is not self.original_output or len(self.output) != len(self.rows)
                    or demand.encoded(self.binding) != self.raw or demand.encoded(descriptor) != self.raw
                    or self.original.__code__ is not self.original_code or self.native_fn.__code__ is not self.native_code
                    or self.reconcile_fn.__code__ is not self.reconcile_code
                    or self.pending_module._reconciliation_pending is not self.pending_fn
                    or self.pending_module._acknowledged is not self.ack_fn
                    or self.pending_fn.__code__ is not self.pending_code or self.ack_fn.__code__ is not self.ack_code
                    or any(set(live) != set(original) or any(live[k] is not v for k, v in original.items())
                           for live, original in ((self.original.__globals__, self.original_globals),
                               (self.reconcile_fn.__globals__, self.original_globals),
                               (vars(paper), self.native_globals), (self.native_fn.__globals__, self.native_globals),
                               (self.pending_fn.__globals__, self.pending_globals), (self.ack_fn.__globals__, self.ack_globals)))):
                raise ValueError('Original owned prepared native result storage required')
            read_descriptor(descriptor, binding)
            current = self.pending_fn(prior.pending, set(client._orders), self.clock)
            if len(current) != len(self.due) or any(a is not b for a, b in zip(current, self.due)):
                raise ValueError('Original prepared-result due input membership changed')
            for record, original in zip(self.output, self.rows):
                if record is not original or type(record) is not SETTLED or tuple(record.__dict__) != NAMES:
                    raise ValueError('Original native result instance storage required')
                if not self.used and any(v is not self.empty for v in record.__dict__.values()):
                    raise ValueError('Empty result storage cannot hold predicted evidence')
            if self.used and (not self.finished or self.index != len(self.rows)):
                raise ValueError('Only complete original native results can be observed')
        except BaseException:
            self.failed = True
            raise

    # Hand the original output list to the derived native loop once, after its actual due-input selection.
    def begin(self, pending):
        if self.closed or self.failed or self.used or len(pending) != len(self.due) or any(a is not b for a, b in zip(pending, self.due)):
            self.failed = True
            raise ValueError('Original once-only native result initialization required')
        self.check(self.prior, self.client, self.input_binding, self.binding)
        self.used = True
        return self.output

    # Invoke the unchanged native frozen initializer once on original storage with actual computed fields.
    def store(self, **values):
        try:
            sources()
            if (self.closed or self.failed or not self.used or self.finished or self.index >= len(self.rows)
                    or demand.encoded(self.binding) != self.raw
                    or tuple(values) != NAMES or values['client_order_id'] != self.binding['due_ids'][self.index]
                    or self.native_fn.__code__ is not self.native_code):
                raise ValueError('Original ordered actual native result values required')
            record = self.output[self.index]
            if record is not self.rows[self.index] or any(v is not self.empty for v in record.__dict__.values()):
                raise ValueError('Original empty native result storage required')
            INIT(record, **values)
            self.index += 1
        except BaseException:
            self.failed = True
            raise

    # Run the exact derived native loop on actual post-resolution orders and require complete initialization.
    def settle(self, pending, orders):
        try:
            result = self.native_fn(pending, orders, prepared_results=self)
            if result is not self.output or self.index != len(self.rows):
                raise ValueError('Complete original initialized native results required')
            self.finished = True
            self.check(self.prior, self.client, self.input_binding, self.binding)
            return result
        except BaseException:
            self.failed = True
            raise

    # Compose the explicitly derived raw reconciliation with original prepared orders and actual native results.
    def reconcile(self, original, client, state, *, prepared_orders, **kwargs):
        try:
            self.check(self.prior, client, self.input_binding, self.binding)
            if original is not self.original:
                raise ValueError('Original derived result reconciliation required')
            return self.reconcile_fn(client, state, prepared_orders=prepared_orders, prepared_results=self, **kwargs)
        except BaseException:
            self.failed = True
            raise

    # Authenticate only original completed metadata after native references and private storage are released.
    def check_released(self, binding, descriptor):
        if (not self.closed or self.failed or not self.used or not self.finished
                or any(v is not None for v in (self.prior, self.client, self.output, self.original_output, self.rows,
                    self.due, self.native_fn, self.reconcile_fn, self.original, self.original_globals, self.pending_fn,
                    self.pending_module, self.ack_fn, self.pending_globals, self.ack_globals, self.native_globals))
                or demand.encoded(self.binding) != self.raw or demand.encoded(descriptor) != self.raw):
            raise ValueError('Original initialized and released native result storage required')
        read_descriptor(descriptor, binding)

    # Drop input, result storage and copied globals on successful publication and every failure path.
    def close(self):
        self.closed = True
        self.prior = self.client = self.output = self.original_output = self.rows = self.due = None
        self.native_fn = self.reconcile_fn = self.original = self.original_globals = self.pending_fn = None
        self.pending_module = self.ack_fn = self.pending_globals = self.ack_globals = self.native_globals = None
