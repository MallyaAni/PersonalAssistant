"""PRIVATE static request INPUT admission; broker execution results stay post-resolution.

The predicate below is explicitly DERIVED from private _requests, omitting only
its post-resolution accepted-market outcome check. Native/default code is unchanged.
"""
import ast
from hashlib import sha256
import json
from pathlib import Path
from types import CodeType, FunctionType

from backend.market import historical_broker_checkpoint as codec
from backend.market import historical_packet_demand as demand
from backend.market import historical_request_admission as identities
from backend.market import replay_broker as native

SCHEMA = 'synthetic-reconciliation-static-inputs/1'
CAP = 262144
BROKER_SHA = 'c3d427e180e6b7527d3b666a450c6076b24e1cd75bfce1786852dced9eb2d616'
CERTIFICATE = None


# Check the complete original static input conditions, excluding only the unresolved-outcome branch.
def _static_request_inputs(prior, orders, observed):
    _unique(prior.pending)
    _unique(prior.journal)
    known = {row["client_order_id"] for row in orders}
    if any(
        (market_daily._acknowledged(row) or row.get("sent"))
        and row["client_order_id"] not in known
        for row in prior.pending
    ):
        raise ValueError("Acknowledged request lacks original native broker receipt")
    by_id = {row["client_order_id"]: row for row in orders}
    for row in prior.pending:
        codec.symbol(row.get("symbol"))
        if row.get("side") not in ("buy", "sell"):
            raise ValueError("Original buy/sell request side required")
        if type(row.get("qty")) is not int or row["qty"] <= 0:
            raise ValueError("Original positive whole desired quantity required")
        order = by_id.get(row["client_order_id"])
        if order is not None and (
            order["symbol"] != row.get("symbol")
            or order["side"] != row.get("side")
            or not 0 < int(order["qty"]) <= row["qty"]
            or native._instant(order["submitted_at"]) > observed
        ):
            raise ValueError("Original desired/submitted request binding differs")
    return known


STATIC_CODE = _static_request_inputs.__code__


# Bind unchanged sources and the exact derived predicate without importing native CLI startup.
def sources(requests):
    global CERTIFICATE
    unique = requests.__globals__['_unique']
    original = identities.sources(unique)
    ack = requests.__globals__['market_daily']._acknowledged
    paths = (Path(unique.__globals__['__file__']), Path(ack.__code__.co_filename),
             Path(native.__file__), Path(__file__))
    if any(p.stat().st_size > CAP for p in paths):
        raise ValueError('Finite original static-input sources required')
    bodies = tuple(p.read_bytes() for p in paths)
    if CERTIFICATE is None:
        request_tree, own_tree = ast.parse(bodies[0]), ast.parse(bodies[3])
        node = next(n for n in request_tree.body if isinstance(n, ast.FunctionDef) and n.name == '_requests')
        derived = next(n for n in own_tree.body if isinstance(n, ast.FunctionDef) and n.name == '_static_request_inputs')
        if (not isinstance(node.body[4], ast.If)
                or ast.dump(node.body[4]).count('Conditional market outcome remains unresolved') != 1):
            raise ValueError('Exact original post-resolution branch required')
        expected = ast.dump(ast.Module(body=node.body[:4] + node.body[5:], type_ignores=[]), include_attributes=False)
        actual = ast.dump(ast.Module(body=derived.body, type_ignores=[]), include_attributes=False)
        request_code = next(c for c in compile(bodies[0], str(paths[0]), 'exec', dont_inherit=True).co_consts
                            if type(c) is CodeType and c.co_name == '_requests')
        ack_code = next(c for c in compile(bodies[1], str(paths[1]), 'exec', dont_inherit=True).co_consts
                        if type(c) is CodeType and c.co_name == '_acknowledged')
        own_code = next(c for c in compile(bodies[3], str(paths[3]), 'exec', dont_inherit=True).co_consts
                        if type(c) is CodeType and c.co_name == '_static_request_inputs')
        if expected != actual or own_code != STATIC_CODE or sha256(bodies[2]).hexdigest() != BROKER_SHA:
            raise ValueError('Exact complete private static-input predicate required')
        CERTIFICATE = (bodies, request_code, ack_code, sha256(actual.encode()).hexdigest())
    if (bodies != CERTIFICATE[0] or requests.__code__ != CERTIFICATE[1] or ack.__code__ != CERTIFICATE[2]
            or _static_request_inputs.__code__ is not STATIC_CODE
            or requests.__globals__['native'] is not native or requests.__globals__['codec'] is not codec
            or ack.__globals__.get('__file__') != str(paths[1])):
        raise ValueError('Original static-input source or dependency changed')
    return {'identity_admission': original, 'requests': sha256(bodies[0]).hexdigest(),
        'acknowledged': sha256(bodies[1]).hexdigest(), 'broker': BROKER_SHA,
        'adapter': sha256(bodies[3]).hexdigest(), 'derived_ast': CERTIFICATE[3],
        'execution_mode': 'PRIVATE_DERIVED_STATIC_INPUTS_NOT_WHOLE_REQUESTS'}


# Instantiate only the certified derived CodeType in the original private predicate globals.
def predicate(requests):
    sources(requests)
    return FunctionType(STATIC_CODE, requests.__globals__, '_static_request_inputs')


# Read only immutable submission inputs and original pending intent semantics, never execution outcomes.
def projection(prior, client, requests):
    ack = requests.__globals__['market_daily']._acknowledged
    return {'pending': [{'client_order_id': row['client_order_id'], 'symbol': row.get('symbol'),
        'side': row.get('side'), 'qty': row.get('qty'), 'acknowledged': bool(ack(row) or row.get('sent'))}
        for row in prior.pending],
        'submissions': [{key: row[key] for key in ('client_order_id', 'symbol', 'side', 'qty', 'submitted_at')}
                        for row in client._orders.values()]}


# Authenticate finite original input metadata during recovery without reconstructing native state or outcomes.
def read_descriptor(value, input_binding, requests, resolution_at):
    unique = requests.__globals__['_unique']
    if type(value) is not dict or set(value) != {'schema', 'sources', 'identity_admission', 'resolution_at',
                                                'static_inputs', 'static_inputs_sha256'}:
        raise ValueError('Exact finite static-input descriptor required')
    identities.read_descriptor(value['identity_admission'], identities.base(input_binding, unique), unique)
    rows = value['static_inputs']
    if type(rows) is not dict or set(rows) != {'pending', 'submissions'}:
        raise ValueError('Original finite input projection required')
    if any(type(rows[k]) is not list for k in rows):
        raise ValueError('Exact static-input row lists required')
    for kind, fields in (('pending', {'client_order_id', 'symbol', 'side', 'qty', 'acknowledged'}),
                         ('submissions', {'client_order_id', 'symbol', 'side', 'qty', 'submitted_at'})):
        ids = []
        for row in rows[kind]:
            if type(row) is not dict or set(row) != fields:
                raise ValueError('Exact static-input fields required')
            cid = row['client_order_id']
            if type(cid) is not str or not cid:
                raise ValueError('Original input identity required')
            ids.append(cid)
            codec.symbol(row['symbol'])
            if row['side'] not in ('buy', 'sell'):
                raise ValueError('Original input side required')
        if len(ids) != len(set(ids)):
            raise ValueError('Original unique input identities required')
    if [row['client_order_id'] for row in rows['pending']] != value['identity_admission']['catalogue']['pending']:
        raise ValueError('Original pending input order required')
    known = {row['client_order_id']: row for row in rows['submissions']}
    clock = native._instant(resolution_at)
    for row in rows['submissions']:
        if type(row['qty']) is not str or int(row['qty']) <= 0 or type(row['submitted_at']) is not str:
            raise ValueError('Original native submitted quantity/time types required')
        native._instant(row['submitted_at'])
    for row in rows['pending']:
        if type(row['qty']) is not int or row['qty'] <= 0 or type(row['acknowledged']) is not bool:
            raise ValueError('Original desired quantity and acknowledgement types required')
        order = known.get(row['client_order_id'])
        if row['acknowledged'] and order is None:
            raise ValueError('Original acknowledged submission membership required')
        if order is not None and (order['symbol'] != row['symbol'] or order['side'] != row['side']
                or not 0 < int(order['qty']) <= row['qty'] or native._instant(order['submitted_at']) > clock):
            raise ValueError('Original desired/submitted input binding required')
    raw = demand.encoded(rows)
    expected = {'schema': SCHEMA, 'sources': sources(requests),
        'identity_admission': value['identity_admission'], 'resolution_at': resolution_at,
        'static_inputs': rows, 'static_inputs_sha256': sha256(raw).hexdigest()}
    if len(demand.encoded(value)) > CAP or demand.encoded(value) != demand.encoded(expected):
        raise ValueError('Original bounded static-input binding required')
    return value


# Own a finite original input admission while real mutable broker results remain outside the descriptor.
class StaticAdmission:
    # Run the certified static predicate against original references before output materialization or resolution.
    def __init__(self, prior, client, input_binding, requests, resolution_at):
        self.prior = self.original_prior = prior
        self.client = self.original_client = client
        self.requests, self.request_code = requests, requests.__code__
        self.identity_admission = None
        self.used, self.closed = False, False
        try:
            if type(client) is not native.ReplayBroker:
                raise ValueError('Exact original static-input broker required')
            unique = requests.__globals__['_unique']
            self.identity_admission = identities.RequestAdmission(prior, input_binding, unique)
            predicate(requests)(prior, list(client._orders.values()), native._instant(resolution_at))
            rows = projection(prior, client, requests)
            self.binding = json.loads(demand.encoded({'schema': SCHEMA, 'sources': sources(requests),
                'identity_admission': self.identity_admission.binding, 'resolution_at': resolution_at,
                'static_inputs': rows, 'static_inputs_sha256': sha256(demand.encoded(rows)).hexdigest()}))
            self.binding_raw = demand.encoded(self.binding)
            self.check(prior, input_binding, self.binding, unconsumed=True)
        except BaseException:
            self.close()
            raise

    # Recheck original references, frozen metadata and unchanged static fields before and after actual resolution.
    def check(self, prior, input_binding, descriptor, *, unconsumed=False):
        if (self.closed or type(self.used) is not bool or (unconsumed and self.used)
                or prior is not self.prior or self.prior is not self.original_prior
                or self.client is not self.original_client or self.requests.__code__ is not self.request_code
                or self.used is not self.identity_admission.used
                or demand.encoded(descriptor) != self.binding_raw or demand.encoded(self.binding) != self.binding_raw):
            raise ValueError('Original unused static-input ownership required')
        self.identity_admission.check(prior, input_binding, descriptor['identity_admission'], unconsumed=unconsumed)
        read_descriptor(descriptor, input_binding, self.requests, self.binding['resolution_at'])
        if demand.encoded(projection(prior, self.client, self.requests)) != demand.encoded(self.binding['static_inputs']):
            raise ValueError('Original static request inputs changed')

    # Consume both the identity lease and static-input admission once immediately before real resolution.
    def consume(self, prior, input_binding, descriptor):
        self.check(prior, input_binding, descriptor, unconsumed=True)
        self.identity_admission.consume(prior, input_binding, descriptor['identity_admission'])
        self.used = True

    # Verify only original metadata after owned native references have been released.
    def check_released(self, input_binding, descriptor):
        if (not self.closed or self.used is not True or any(v is not None for v in
                (self.prior, self.original_prior, self.client, self.original_client))
                or demand.encoded(descriptor) != self.binding_raw or demand.encoded(self.binding) != self.binding_raw):
            raise ValueError('Original consumed and released static-input admission required')
        self.identity_admission.check_released(input_binding, descriptor['identity_admission'])
        read_descriptor(descriptor, input_binding, self.requests, self.binding['resolution_at'])

    # Release this scope's prior and broker references on success and every failed preparation.
    def close(self):
        self.closed = True
        self.prior = self.original_prior = self.client = self.original_client = None
        if self.identity_admission is not None:
            self.identity_admission.close()

