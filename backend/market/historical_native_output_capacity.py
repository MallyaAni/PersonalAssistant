"""PRIVATE conservative native output-byte admission before actual resolution.

This binds the whole native journal/pending/rebalance serialization growth to
the original finite save slot. It reserves no Python RAM or filesystem metadata
and never constructs a predicted settlement, execution result or saved state.
"""
from hashlib import sha256
import json
from pathlib import Path

from backend.agents.trading.desk import paper
from backend.market import historical_broker_checkpoint as codec
from backend.market import historical_packet_demand as demand
from backend.market import historical_prepared_transition as transition
from backend.market import historical_synthetic_native_write as writer

SCHEMA = 'synthetic-native-output-byte-capacity/1'
PAPER_SHA = 'a8c5083f1828df7395164882ba877d5a134d55295d6a0cda0dcdc0047bcde42c'
BROKER_SHA = 'c3d427e180e6b7527d3b666a450c6076b24e1cd75bfce1786852dced9eb2d616'
WRITER_SHA = '21f5c29c89405d6b9b59e081b14e6a2c649e4547b86dba9c314a7efba1fb7501'
CAP = 1048576


# Bind native outcome builders, serializer and original one-MiB writer without changing them.
def sources():
    paths = {'paper': Path(paper.__file__), 'broker': Path(paper.__file__).parents[3] / 'market/replay_broker.py',
        'writer': Path(writer.__file__), 'adapter': Path(__file__)}
    if any(path.stat().st_size > 262144 for path in paths.values()):
        raise ValueError('Finite original native output sources required')
    result = {k: sha256(path.read_bytes()).hexdigest() for k, path in paths.items()}
    if any(result[k] != v for k, v in (('paper', PAPER_SHA), ('broker', BROKER_SHA), ('writer', WRITER_SHA))):
        raise ValueError('Original native output growth and writer semantics required')
    transition.sources()
    return result


# Count exact native JSON fragments at journal-row depth while preserving NaN and original encoding.
def measure(value, limit=CAP):
    size, digest = 0, sha256()
    for part in json.JSONEncoder(indent=2, default=paper._state_json).iterencode({'journal': [value]}):
        raw = part.encode('utf-8')
        size += len(raw)
        if size > limit:
            raise ValueError('Native output variable-field allowance exceeded')
        digest.update(raw)
    return size, digest.hexdigest()


# Measure only original rows that can be copied into new journal or working-pending records.
def inputs(prior):
    if type(prior) is not paper.PaperState or type(prior.pending) is not list or type(prior.journal) is not list:
        raise ValueError('Original native journal/pending input required')
    journal = {}
    for row in prior.journal:
        if type(row) is not dict:
            raise ValueError('Native journal records must be mappings before resolution')
        if prior.unconfirmed_rebalance is not None:
            if 'session' not in row or (row['session'] == prior.unconfirmed_rebalance and not row.get('event_id')
                    and not {'terminal', 'status'} <= row.keys()):
                raise ValueError('Original journal rebalance fields required before resolution')
        journal[str(row.get('client_order_id') or '')] = row
    digest, length = sha256(), 0
    for row in prior.pending:
        if type(row) is not dict or type(row.get('client_order_id')) is not str or not row['client_order_id']:
            raise ValueError('Original native pending identifier required')
        previous = journal.get(row['client_order_id'], {})
        if type(row.get('execution', {})) is not dict or type(previous.get('execution', {})) is not dict:
            raise ValueError('Native execution merge mappings required before resolution')
        for value in (row, previous):
            size, hashed = measure(value)
            length += size
            if length > CAP:
                raise ValueError('Native output original variable allowance exceeded')
            digest.update(demand.encoded([size, hashed]))
    # The previous rebalance can also become last_rebalance without changing its native bytes.
    size, hashed = measure(prior.previous_rebalance)
    length += size
    digest.update(demand.encoded([size, hashed]))
    return {'bytes': length, 'sha256': digest.hexdigest(), 'pending': len(prior.pending)}


# Bound complete native output growth without estimating a status, fill or execution time.
def upper(native_bytes, projected, broker_bytes):
    # The unchanged native tail retains unaffected state/history and cannot add
    # more than one journal row and one working-pending row per original intent.
    # Eight copies of each exact wrapped original row cover merged execution,
    # echoed raw quantity diagnostics, inherited optional fields and indentation.
    # Four original broker images cover its copied strings and numeric spellings.
    # Per-intent8192 covers all fixed native keys/status/anomaly labels, at most
    # six aware timestamp fields, finite float/int formatting and list framing.
    # Fixed1024 covers rebalance counter/scalar changes and enclosing JSON growth.
    # Nothing here is materialized as an outcome, result, placeholder evidence or RAM reserve.
    return native_bytes + 8 * projected['bytes'] + 4 * broker_bytes + 8192 * projected['pending'] + 1024


# Authenticate original source/input/save-slot arithmetic without loading or producing native state.
def read_descriptor(value, binding):
    keys = {'schema', 'sources', 'input_sha256', 'native_bytes', 'inputs', 'broker_bytes', 'broker_sha256',
            'slot_bytes', 'raw_limit', 'output_upper_bytes', 'scope'}
    if type(value) is not dict or set(value) != keys or value['schema'] != SCHEMA or value['sources'] != sources():
        raise ValueError('Original native output-byte descriptor required')
    projected = value['inputs']
    if type(projected) is not dict or set(projected) != {'bytes', 'sha256', 'pending'}:
        raise ValueError('Original native output input fields required')
    numbers = [value[k] for k in ('native_bytes', 'broker_bytes', 'slot_bytes', 'raw_limit', 'output_upper_bytes')]
    if any(type(n) is not int or n < 0 for n in numbers + [projected['bytes'], projected['pending']]):
        raise ValueError('Exact integer native output allowances required')
    if (value['input_sha256'] != sha256(demand.encoded(binding)).hexdigest()
            or value['native_bytes'] != binding['native_bytes']['raw_bytes']
            or value['raw_limit'] != binding['raw_limit'] or not 0 < value['raw_limit'] <= CAP
            or value['slot_bytes'] != writer.SLOT_BYTES or value['slot_bytes'] != CAP
            or value['scope'] != 'BYTE_ADMISSION_NOT_RAM_OR_METADATA_RESERVATION'
            or value['output_upper_bytes'] != upper(value['native_bytes'], projected, value['broker_bytes'])
            or not 0 < value['output_upper_bytes'] <= min(value['slot_bytes'], value['raw_limit'])):
        raise ValueError('Native output capacity unavailable before resolution')
    for hashed in (projected['sha256'], value['broker_sha256']):
        if type(hashed) is not str or len(hashed) != 64 or any(c not in '0123456789abcdef' for c in hashed):
            raise ValueError('Original native output digest required')
    return value


# Own one original source/head/preimage-bound byte allowance for the whole late native transition.
class NativeOutputCapacity:
    # Refuse an insufficient final save-slot allowance before output cloning or broker resolution.
    def __init__(self, prior, client, binding, pins, slot_bytes):
        self.prior = self.original_prior = prior
        self.client = client
        self.closed = self.used = self.failed = self.checked = False
        try:
            broker = codec.encode(client, **pins)
            projected = inputs(prior)
            self.binding = {'schema': SCHEMA, 'sources': sources(),
                'input_sha256': sha256(demand.encoded(binding)).hexdigest(),
                'native_bytes': binding['native_bytes']['raw_bytes'], 'inputs': projected,
                'broker_bytes': len(broker), 'broker_sha256': sha256(broker).hexdigest(),
                'slot_bytes': slot_bytes, 'raw_limit': binding['raw_limit'],
                'output_upper_bytes': upper(binding['native_bytes']['raw_bytes'], projected, len(broker)),
                'scope': 'BYTE_ADMISSION_NOT_RAM_OR_METADATA_RESERVATION'}
            read_descriptor(self.binding, binding)
            if transition.native_bytes(prior, binding['raw_limit']) != binding['native_bytes']:
                raise ValueError('Original native output allowance preimage required')
            self.raw = demand.encoded(self.binding)
        except BaseException:
            self.failed = True
            self.close()
            raise

    # Recheck frozen admission metadata and original variable inputs without fixing future outcomes.
    def check(self, prior, client, binding, descriptor):
        try:
            if (self.closed or self.failed or prior is not self.prior or self.prior is not self.original_prior
                    or client is not self.client or type(self.used) is not bool
                    or demand.encoded(self.binding) != self.raw or demand.encoded(descriptor) != self.raw):
                raise ValueError('Original owned native output allowance required')
            read_descriptor(descriptor, binding)
            if transition.native_bytes(prior, binding['raw_limit']) != binding['native_bytes']:
                raise ValueError('Original native output allowance preimage changed')
            if inputs(prior) != descriptor['inputs']:
                raise ValueError('Original native output allowance inputs changed')
        except BaseException:
            self.failed = True
            raise

    # Consume the original allowance once against the exact pre-resolution native broker image.
    def consume(self, prior, client, binding, descriptor, pins):
        try:
            self.check(prior, client, binding, descriptor)
            if self.used or sha256(codec.encode(client, **pins)).hexdigest() != descriptor['broker_sha256']:
                raise ValueError('Original unused native output allowance required')
            self.used = True
        except BaseException:
            self.failed = True
            raise

    # Check actual native serialization against its original upper bound before native saving.
    def output(self, actual):
        try:
            if (self.closed or self.failed or self.used is not True or self.checked
                    or demand.encoded(self.binding) != self.raw or type(actual) is not dict
                    or type(actual.get('raw_bytes')) is not int
                    or not 0 < actual['raw_bytes'] <= self.binding['output_upper_bytes']):
                raise ValueError('Actual native output exceeds original byte allowance')
            self.checked = True
        except BaseException:
            self.failed = True
            raise

    # Read only original consumed and checked metadata after all native references are released.
    def check_released(self, binding, descriptor):
        if (not self.closed or self.failed or self.used is not True or self.checked is not True
                or self.prior is not None or self.original_prior is not None or self.client is not None
                or demand.encoded(self.binding) != self.raw or demand.encoded(descriptor) != self.raw):
            raise ValueError('Original checked and released native output allowance required')
        read_descriptor(descriptor, binding)

    # Release original native input and broker ownership on success and every failure path.
    def close(self):
        self.closed = True
        self.prior = self.original_prior = self.client = None
