"""PRIVATE admission of original inputs for the existing strict finite evidence strategy.

This does not validate quantity policy, predict fills, or normalize native state.
Finite anomalous observations remain eligible for unchanged native diagnostics.
"""
from hashlib import sha256
import json
from pathlib import Path

from backend.agents.trading.desk import paper
from backend.market import historical_packet_demand as demand

SCHEMA = 'synthetic-finite-evidence-inputs/1'
CAP = 262144
PAPER_SHA = 'a8c5083f1828df7395164882ba877d5a134d55295d6a0cda0dcdc0047bcde42c'


# Bind the unchanged native semantics and current finite reconciliation evidence source.
def sources():
    paths = {'paper': Path(paper.__file__), 'adapter': Path(__file__),
        'reconciliation': Path(__file__).with_name('historical_conditional_settlement.py')}
    if any(path.stat().st_size > CAP for path in paths.values()):
        raise ValueError('Finite evidence-input sources required')
    result = {name: sha256(path.read_bytes()).hexdigest() for name, path in paths.items()}
    if result['paper'] != PAPER_SHA:
        raise ValueError('Original native evidence semantics required')
    return result


# Freeze source/head/native-preimage metadata without preparing a settlement or a broker outcome.
def base(input_binding):
    return {'schema': SCHEMA, 'sources': sources(), 'strategy': 'EXISTING_STRICT_FINITE_RECONCILIATION_2',
        'scope': 'ENCODING_ADMISSION_NOT_QUANTITY_POLICY',
        'prepared_input_sha256': sha256(demand.encoded(input_binding)).hexdigest(),
        **{key: input_binding[key] for key in ('identity', 'account', 'phase', 'head', 'native_io_sha256', 'native_bytes')}}


# Check only original paper fields that flow unconverted into native settlement evidence.
def inspect_inputs(prior):
    if type(prior) is not paper.PaperState or type(prior.pending) is not list:
        raise ValueError('Original native evidence input required')
    projected = []
    for row in prior.pending:
        execution = row.get('execution', {})
        if type(execution) is not dict:
            raise ValueError('Native settlement requires an original execution mapping')
        sent = row.get('sent')
        sender_raw = sent.get('qty') if type(sent) is dict else None
        projected.append({'client_order_id': row['client_order_id'], 'kind': row.get('kind') or None,
                          'execution_input': execution, 'sender_quantity_input': sender_raw})
    digest, length = sha256(), 0
    try:
        for part in json.JSONEncoder(sort_keys=True, separators=(',', ':'), allow_nan=False).iterencode(projected):
            raw = part.encode('utf-8')
            length += len(raw)
            if length > CAP:
                raise ValueError('Finite evidence-input allowance exceeded')
            digest.update(raw)
    except (TypeError, ValueError) as error:
        raise ValueError('Original inputs cannot use the strict finite evidence strategy') from error
    return {'sha256': digest.hexdigest(), 'bytes': length, 'pending_count': len(projected)}


# Authenticate original finite-strategy admission metadata without loading paper or recomputing diagnostics.
def read_descriptor(value, input_binding):
    expected = base(input_binding)
    if type(value) is not dict or set(value) != set(expected) | {'inputs'}:
        raise ValueError('Exact finite evidence-input descriptor required')
    inputs = value['inputs']
    if (type(inputs) is not dict or set(inputs) != {'sha256', 'bytes', 'pending_count'}
            or type(inputs['bytes']) is not int or not 0 < inputs['bytes'] <= CAP
            or type(inputs['pending_count']) is not int or inputs['pending_count'] < 0
            or type(inputs['sha256']) is not str or len(inputs['sha256']) != 64):
        raise ValueError('Original finite evidence-input fields required')
    if any(c not in '0123456789abcdef' for c in inputs['sha256']):
        raise ValueError('Original finite evidence-input digest required')
    if demand.encoded(value) != demand.encoded({**expected, 'inputs': inputs}):
        raise ValueError('Original finite evidence-input source/head binding required')
    return value


# Own the original prepared input for one finite-evidence admission before the selected resolution effect.
class EvidenceInput:
    # Refuse incompatible input shape/encoding before output clone and actual broker resolution.
    def __init__(self, prior, input_binding):
        self.prior = self.original_prior = prior
        self.used, self.closed = False, False
        try:
            self.binding = json.loads(demand.encoded({**base(input_binding), 'inputs': inspect_inputs(prior)}))
            self.binding_raw = demand.encoded(self.binding)
            self.check(prior, input_binding, self.binding, unconsumed=True)
        except BaseException:
            self.close()
            raise

    # Check frozen strategy/source metadata and exact original input fields before and after real resolution.
    def check(self, prior, input_binding, descriptor, *, unconsumed=False):
        if (self.closed or type(self.used) is not bool or (unconsumed and self.used)
                or prior is not self.prior or self.prior is not self.original_prior
                or demand.encoded(descriptor) != self.binding_raw or demand.encoded(self.binding) != self.binding_raw):
            raise ValueError('Original unused finite evidence-input ownership required')
        read_descriptor(descriptor, input_binding)
        if demand.encoded(inspect_inputs(prior)) != demand.encoded(self.binding['inputs']):
            raise ValueError('Original finite evidence inputs changed')

    # Consume this original strategy admission once without preparing any future result values.
    def consume(self, prior, input_binding, descriptor):
        self.check(prior, input_binding, descriptor, unconsumed=True)
        self.used = True

    # Read original consumed metadata after owned native references have been released.
    def check_released(self, input_binding, descriptor):
        if (not self.closed or self.used is not True or self.prior is not None or self.original_prior is not None
                or demand.encoded(descriptor) != self.binding_raw or demand.encoded(self.binding) != self.binding_raw):
            raise ValueError('Original consumed and released evidence-input admission required')
        read_descriptor(descriptor, input_binding)

    # Release this capsule's original native references on success and every failure path.
    def close(self):
        self.closed = True
        self.prior = self.original_prior = None
