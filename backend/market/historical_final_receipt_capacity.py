"""PRIVATE conservative byte admission for the existing finite Cycle receipt.

This accounts for original input lengths and bounded native output shapes. It
does not manufacture a result, reserve RAM, or admit a genuine trading run.
"""
from hashlib import sha256
import json
from pathlib import Path

from backend.agents.trading.desk import paper
from backend.market import historical_broker_checkpoint as codec
from backend.market import historical_packet_demand as demand

SCHEMA = 'synthetic-final-receipt-capacity/1'
CAP = 262144
FIXED = 65536
PAPER_SHA = 'a8c5083f1828df7395164882ba877d5a134d55295d6a0cda0dcdc0047bcde42c'
BROKER_SHA = 'c3d427e180e6b7527d3b666a450c6076b24e1cd75bfce1786852dced9eb2d616'
RECONCILE_SHA = '36372b959a59650a259328478709038fa21676c22324c031cc3f7255f5b7c28e'
CYCLE_SHA = 'b2e53c71f386bf58aeb2af8aed9a93cfbc0039be60e48f49550636778d482a61'


# Bind the exact native output builders and unchanged enclosing receipt representation.
def sources():
    paths = {'paper': Path(paper.__file__), 'broker': Path(paper.__file__).parents[3] / 'market/replay_broker.py',
        'reconciliation': Path(__file__).with_name('historical_conditional_settlement.py'),
        'cycle': Path(__file__).with_name('historical_conditional_cycle.py'), 'adapter': Path(__file__)}
    rows = {name: sha256(path.read_bytes()).hexdigest() for name, path in paths.items()}
    if any(rows[k] != v for k, v in (('paper', PAPER_SHA), ('broker', BROKER_SHA),
            ('reconciliation', RECONCILE_SHA), ('cycle', CYCLE_SHA))):
        raise ValueError('Original final receipt byte-bound sources required')
    return rows


# Measure only original fields copied to settled evidence and retained pending identities.
def input_size(prior):
    rows = [{'client_order_id': row['client_order_id'], 'symbol': row['symbol'], 'side': row['side'],
        'qty': row['qty'], 'session': str(row.get('session') or ''), 'kind': row.get('kind') or None,
        'execution': row.get('execution', {}), 'sender': (row['sent'].get('qty') if type(row.get('sent')) is dict else None)}
        for row in prior.pending]
    digest, size = sha256(), 0
    for fragment in json.JSONEncoder(sort_keys=True, separators=(',', ':'), allow_nan=False).iterencode(rows):
        raw = fragment.encode()
        size += len(raw)
        if size > CAP:
            raise ValueError('Original finite receipt input allowance exceeded')
        digest.update(raw)
    return {'bytes': size, 'sha256': digest.hexdigest(), 'pending': len(rows)}


# Derive one conservative budget from input lengths without predicting status, quantities or execution fields.
def budget(inputs, broker_bytes, declaration_bytes, source_bytes, order_count):
    # Native settle emits at most one row per pending input. Three copies of its
    # original variable fields pay for evidence and enclosing receipt duplication.
    # Existing broker bytes twice pay for retained native strings/quantities and
    # possible fill records. Per-order1024 pays for the exact _fill keys, finite
    # scalar formatting, status/reason alternatives and generated timestamps.
    # Per-pending1024 pays for Settled fixed keys, normalized scalar alternatives,
    # native diagnostic labels and merged execution timestamp keys. Four original
    # declaration copies pay for request/lineage/context metadata and JSON framing.
    # Source map twice plus64KiB pays for both component descriptors, digests,
    # source/serialization metadata and the final operation link. This is a byte
    # upper allowance, not a synthetic predicted result or a capacity reservation.
    return FIXED + 3 * inputs['bytes'] + 2 * broker_bytes + 4 * declaration_bytes + 2 * source_bytes + 1024 * (order_count + inputs['pending'])


# Authenticate finite original budget metadata without reading native state or estimating a new result.
def read_descriptor(value, binding):
    keys = {'schema', 'sources', 'input_sha256', 'inputs', 'broker_bytes', 'broker_sha256',
            'declaration_bytes', 'source_bytes', 'orders', 'receipt_upper_bytes', 'limit'}
    if type(value) is not dict or set(value) != keys or value['schema'] != SCHEMA or value['sources'] != sources():
        raise ValueError('Original finite final-receipt allowance required')
    if value['input_sha256'] != sha256(demand.encoded(binding)).hexdigest() or value['limit'] != CAP:
        raise ValueError('Original receipt allowance input binding required')
    inputs = value['inputs']
    if type(inputs) is not dict or set(inputs) != {'bytes', 'sha256', 'pending'}:
        raise ValueError('Original receipt allowance input fields required')
    for number in [value[k] for k in ('broker_bytes', 'declaration_bytes', 'source_bytes', 'orders', 'receipt_upper_bytes', 'limit')] + [inputs['bytes'], inputs['pending']]:
        if type(number) is not int or number < 0:
            raise ValueError('Exact integer receipt byte allowances required')
    for digest in (inputs['sha256'], value['broker_sha256']):
        if type(digest) is not str or len(digest) != 64 or any(c not in '0123456789abcdef' for c in digest):
            raise ValueError('Original receipt allowance digest required')
    expected = budget(inputs, value['broker_bytes'], value['declaration_bytes'], value['source_bytes'], value['orders'])
    if value['receipt_upper_bytes'] != expected or not 0 < expected <= CAP:
        raise ValueError('Final receipt capacity unavailable before resolution')
    return value


# Own one source/head/input-bound budget until the original result bytes have been checked.
class ReceiptCapacity:
    # Refuse an unavailable finite receipt allowance before the original output clone or broker flush.
    def __init__(self, prior, client, binding, declaration, pins, source_map):
        self.prior = self.original_prior = prior
        self.client = client
        self.closed = self.used = False
        try:
            broker = codec.encode(client, **pins)
            inputs = input_size(prior)
            dbytes, sbytes = len(demand.encoded(declaration)), len(demand.encoded(source_map))
            self.binding = {'schema': SCHEMA, 'sources': sources(),
                'input_sha256': sha256(demand.encoded(binding)).hexdigest(), 'inputs': inputs,
                'broker_bytes': len(broker), 'broker_sha256': sha256(broker).hexdigest(),
                'declaration_bytes': dbytes, 'source_bytes': sbytes, 'orders': len(client._orders),
                'receipt_upper_bytes': budget(inputs, len(broker), dbytes, sbytes, len(client._orders)), 'limit': CAP}
            read_descriptor(self.binding, binding)
            self.raw = demand.encoded(self.binding)
        except BaseException:
            self.close()
            raise

    # Recheck frozen metadata and original owned fields without treating future outcomes as fixed inputs.
    def check(self, prior, client, binding, descriptor):
        if (self.closed or prior is not self.prior or self.prior is not self.original_prior or client is not self.client
                or type(self.used) is not bool or demand.encoded(self.binding) != self.raw
                or demand.encoded(descriptor) != self.raw):
            raise ValueError('Original owned receipt allowance required')
        read_descriptor(descriptor, binding)
        if input_size(prior) != descriptor['inputs']:
            raise ValueError('Original receipt allowance inputs changed')

    # Consume the original allowance once immediately before native resolution.
    def consume(self, prior, client, binding, descriptor, pins):
        self.check(prior, client, binding, descriptor)
        if self.used or sha256(codec.encode(client, **pins)).hexdigest() != descriptor['broker_sha256']:
            raise ValueError('Original unused pre-resolution receipt allowance required')
        self.used = True

    # Check actual original output length against its pre-effect upper allowance without altering the bytes.
    def output(self, raw):
        if self.used is not True or demand.encoded(self.binding) != self.raw or type(raw) is not bytes or len(raw) > self.binding['receipt_upper_bytes']:
            raise ValueError('Actual final receipt exceeds original byte allowance')
        return len(raw)

    # Validate original metadata after ownership release without re-preparing paper or broker state.
    def check_released(self, binding, descriptor):
        if not self.closed or self.used is not True or self.prior is not None or self.client is not None or demand.encoded(descriptor) != self.raw or demand.encoded(self.binding) != self.raw:
            raise ValueError('Original released receipt allowance required')
        read_descriptor(descriptor, binding)

    # Drop every native reference on success and all failure paths.
    def close(self):
        self.closed = True
        self.prior = self.original_prior = self.client = None
