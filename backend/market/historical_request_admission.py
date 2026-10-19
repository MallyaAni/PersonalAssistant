"""PRIVATE finite admission of original request identities before broker resolution.

This checks the unchanged private reconciliation uniqueness predicate early.
It neither snapshots broker execution fields nor prepares settlement results.
"""
from hashlib import sha256
import json
from pathlib import Path
from types import CodeType

from backend.agents.trading.desk import paper
from backend.market import historical_packet_demand as demand

SCHEMA = 'synthetic-reconciliation-request-admission/1'
CAP = 262144


# Bind the original whole predicate source and exact complete-compilation function code.
def sources(unique):
    path = Path(__file__).with_name('historical_conditional_settlement.py')
    if path.stat().st_size > CAP or Path(__file__).stat().st_size > CAP:
        raise ValueError('Finite request-admission sources required')
    raw, own = path.read_bytes(), Path(__file__).read_bytes()
    code = next(c for c in compile(raw, str(path), 'exec', dont_inherit=True).co_consts
                if type(c) is CodeType and c.co_name == '_unique')
    if (unique.__name__ != '_unique' or unique.__code__ != code
            or unique.__globals__.get('__file__') != str(path) or unique.__defaults__ is not None
            or unique.__code__.co_kwonlyargcount != 0 or unique.__closure__ is not None):
        raise ValueError('Original reconciliation uniqueness predicate required')
    return {'adapter': sha256(own).hexdigest(), 'predicate_source': sha256(raw).hexdigest(),
            'predicate': '_unique', 'scope': 'PRIVATE_INPUT_IDENTITIES_NOT_BROKER_RESULTS'}


# Freeze the exact source/head/input-bound base without constructing any native state.
def base(input_binding, unique):
    return {'schema': SCHEMA, 'sources': sources(unique),
        'prepared_input_sha256': sha256(demand.encoded(input_binding)).hexdigest(),
        **{k: input_binding[k] for k in ('identity', 'account', 'phase', 'head', 'native_io_sha256', 'native_bytes')}}


# Authenticate only finite original identity metadata during read and recovery.
def read_descriptor(value, original, unique):
    if type(value) is not dict or set(value) != set(original) | {'catalogue', 'catalogue_sha256', 'counts'}:
        raise ValueError('Exact original request admission descriptor required')
    catalogue = value['catalogue']
    if type(catalogue) is not dict or set(catalogue) != {'pending', 'journal'}:
        raise ValueError('Exact original request identity catalogue required')
    for identifiers in catalogue.values():
        if (type(identifiers) is not list or any(type(cid) is not str or not cid for cid in identifiers)
                or len(identifiers) != len(set(identifiers))):
            raise ValueError('Original unique request identity catalogue required')
    raw = demand.encoded(catalogue)
    expected = {**original, 'catalogue': catalogue, 'catalogue_sha256': sha256(raw).hexdigest(),
                'counts': {k: len(v) for k, v in catalogue.items()}}
    if len(raw) > CAP or len(demand.encoded(value)) > CAP or demand.encoded(value) != demand.encoded(expected):
        raise ValueError('Original bounded request admission binding required')
    if value['sources'] != sources(unique):
        raise ValueError('Original request admission sources changed')
    return value


# Own one original prior and its finite identity admission, never an order or predicted outcome copy.
class RequestAdmission:
    # Run the exact original pending/journal predicate before producing an admissible descriptor.
    def __init__(self, prior, input_binding, unique):
        self.prior = self.original_prior = prior
        self.unique, self.unique_code = unique, unique.__code__
        self.globals = unique.__globals__
        self.used, self.closed = False, False
        try:
            if type(prior) is not paper.PaperState:
                raise ValueError('Exact original prepared request prior required')
            original = base(input_binding, unique)
            unique(prior.pending)
            unique(prior.journal)
            catalogue = {k: [row['client_order_id'] for row in getattr(prior, k)] for k in ('pending', 'journal')}
            raw = demand.encoded(catalogue)
            self.binding = json.loads(demand.encoded({**original, 'catalogue': catalogue,
                'catalogue_sha256': sha256(raw).hexdigest(), 'counts': {k: len(v) for k, v in catalogue.items()}}))
            self.binding_raw = demand.encoded(self.binding)
            self.check(prior, input_binding, self.binding, unconsumed=True)
        except BaseException:
            self.close()
            raise

    # Authenticate ownership and frozen metadata while the caller separately rechecks full native preimage bytes.
    def check(self, prior, input_binding, descriptor, *, unconsumed=False):
        if (self.closed or type(self.used) is not bool or (unconsumed and self.used)
                or prior is not self.prior or self.prior is not self.original_prior
                or type(prior) is not paper.PaperState or self.unique.__code__ is not self.unique_code
                or self.unique.__globals__ is not self.globals
                or demand.encoded(descriptor) != self.binding_raw
                or demand.encoded(self.binding) != self.binding_raw):
            raise ValueError('Original unused request admission ownership required')
        read_descriptor(descriptor, base(input_binding, self.unique), self.unique)

    # Consume the original admission once immediately before the selected resolution effect.
    def consume(self, prior, input_binding, descriptor):
        self.check(prior, input_binding, descriptor, unconsumed=True)
        self.used = True

    # Read consumed evidence after native-input ownership has been dropped, without repeating its predicate.
    def check_released(self, input_binding, descriptor):
        if (not self.closed or self.used is not True or self.prior is not None or self.original_prior is not None
                or demand.encoded(descriptor) != self.binding_raw or demand.encoded(self.binding) != self.binding_raw):
            raise ValueError('Original consumed and released request admission required')
        read_descriptor(descriptor, base(input_binding, self.unique), self.unique)

    # Drop this scope's original native prior reference on success and every failed preparation.
    def close(self):
        self.closed = True
        self.prior = self.original_prior = None
