"""Explicit SYNTHETIC reserved-save composition; no genuine execution admission.

Native paper globals remain untouched. A separately source-bound synthetic trade
accepts native_save explicitly. Slot extents are reserved; directory metadata,
Store/latch/decision capacity, replicas and whole-horizon RAM are not reserved.
Captured global identities do not constitute a sandbox or deep immutability.
"""
from contextlib import contextmanager
from copy import deepcopy
from hashlib import sha256
from pathlib import Path
from threading import get_ident
from types import CodeType, FunctionType

from backend.agents.trading.desk import paper
from backend.market import historical_physical_checkpoint as physical
from backend.market import historical_reserved_protocol as protocol
from backend.market import historical_synthetic_native_write as writer_module

SCHEMA = 'synthetic-reserved-native-io/2'
METADATA_SCHEMA = 'synthetic-reserved-native-io/3'
SQLITE_SCHEMA = 'synthetic-reserved-native-io/4'
DIRECTORY_SCHEMA = 'synthetic-reserved-native-io/5'


# Bind the exact synthetic executor source/code and all original global identities.
class SyntheticNativeIO:
    # Retain a finite original-writer pool and an explicitly declared synthetic executor.
    def __init__(self, writer, trade, *, trade_sha256):
        physical._require(type(writer) is writer_module.ReservedWriter
            and type(trade) is FunctionType and trade.__closure__ is None,
            'Exact synthetic writer/executor required')
        self.writer, self.trade = writer, trade
        self._trade, self._trade_code, self._trade_name = trade, trade.__code__, trade.__name__
        self._trade_globals = trade.__globals__
        self.trade_path = Path(trade.__code__.co_filename)
        self.trade_sha256 = physical._digest(trade_sha256)
        self.globals = dict(trade.__globals__)
        self.defaults, self.kwdefaults = trade.__defaults__, deepcopy(trade.__kwdefaults__)
        self.directory, self.saved = None, []
        self.failed = False
        self.guard()

    # Refuse source, callable, defaults or global substitution without patching native globals.
    def guard(self):
        self.writer._guard()
        physical._require(self.trade_path.stat().st_size <= physical.META,
                          'Bounded synthetic executor source required')
        raw = self.trade_path.read_bytes()
        codes = [item for item in compile(raw, str(self.trade_path), 'exec', dont_inherit=True).co_consts
                 if type(item) is CodeType and item.co_name == self.trade.__name__]
        physical._require(self.trade is self._trade and self.trade.__code__ is self._trade_code
            and self.trade.__name__ == self._trade_name and self.trade.__globals__ is self._trade_globals
            and len(raw) <= physical.META and sha256(raw).hexdigest() == self.trade_sha256
            and codes == [self.trade.__code__] and self.trade.__closure__ is None
            and self.trade.__defaults__ is self.defaults and self.trade.__kwdefaults__ == self.kwdefaults
            and set(self.trade.__globals__) == set(self.globals)
            and all(self.trade.__globals__[key] is value for key, value in self.globals.items())
            and self.globals.get('paper') is paper,
            'Source-bound synthetic executor differs')

    # Reserve the starting native cursor and optional exact CAS phase before native work.
    def begin(self, nightly, directory, legacy, *, effect_binding=None):
        self.guard()
        if effect_binding is not None:
            physical._digest(effect_binding)
        physical._require(not self.failed and nightly.root == self.writer.root / 'work'
            and nightly.store.identity == self.writer.header['identity_sha256'],
            'Synthetic account must originate inside its reserved workspace')
        with self.writer._locked(shared=True):
            before = self.writer._control()
            physical._require(before['operation'] is None, 'OPEN native writer; never replay')
            destination = paper.state_path(nightly.root)
            physical._require((not destination.exists() and before['current'] is None)
                or (before['current'] is not None and writer_module._image(destination) == before['current']),
                'Original reserved native preimage required')
        namespace = protocol.pool(nightly)
        metadata_ref = protocol.reference(nightly, directory)
        if namespace is not None:
            namespace.check_effects(directory)
            physical._require(metadata_ref['head'] == nightly.expected_head
                and (effect_binding is None or metadata_ref['inputs'] == effect_binding),
                'Original pre-effect metadata head/input binding required')
        self.bound_nightly, self.metadata_pool, self.metadata_ref = nightly, namespace, metadata_ref
        self.metadata_legacy = legacy
        extra = {} if namespace is None else {'protocol': metadata_ref}
        self.directory_pool = nightly.store.directory_binding
        physical._require(self.directory_pool is None or (namespace is not None
            and self.directory_pool.writer is self.writer), 'Original typed native-directory mode required')
        self.directory_lease = None if self.directory_pool is None else self.directory_pool.arm(metadata_ref)
        if self.directory_pool is not None:
            extra['native_directory'] = self.directory_lease
        self.sqlite_pool = nightly.store.sqlite_reservation
        physical._require(self.sqlite_pool is None or namespace is not None,
                          'SQLite banks require the original typed metadata claim')
        self.sqlite_lease = None if self.sqlite_pool is None else self.sqlite_pool.arm(metadata_ref)
        if self.sqlite_pool is not None:
            extra['reserved_sqlite'] = self.sqlite_lease
        value = {'schema': DIRECTORY_SCHEMA if self.directory_pool is not None else SQLITE_SCHEMA if self.sqlite_pool is not None else
                 SCHEMA if namespace is None else METADATA_SCHEMA, **extra, 'identity': nightly.store.identity,
            'account': str(nightly.root), 'writer_root': str(self.writer.root),
            'sources': sources(), 'trade_sha256': self.trade_sha256, 'trade_path': str(self.trade_path),
            'header_sha256': sha256((self.writer.root / 'header').read_bytes()).hexdigest(),
            'before': before, 'native_operation_adopted': False, 'effect_binding': effect_binding}
        pool = nightly.store.blob_reservation
        value['reserved_cas'] = None if pool is None else pool.arm(
            operation=operation_identity(nightly, directory, effect_binding),
            head=nightly.expected_head)
        try:
            protocol.write(nightly, directory / 'reserved-native-save.json', legacy.admitted.encoded(value), legacy)
        except BaseException:
            self.failed = True
            raise
        self.directory, self.saved, self.cursor = directory, [], deepcopy(before)
        self.reserved_cas = value['reserved_cas']
        self.effect_binding = effect_binding
        self.cas_pool, self.cas_store = pool, nightly.store

    # Save only to the original workspace using the next preallocated native inode.
    def save(self, root, state):
        physical._require(not self.failed, 'Uncertain reserved native IO; never replay')
        try:
            return self._save(root, state)
        except BaseException:
            self.failed = True
            raise

    # Bind each actual write to the original or last successfully completed cursor.
    def _save(self, root, state):
        self.guard()
        self._lease()
        physical._require(self.directory is not None and Path(root) == self.writer.root / 'work',
                          'Explicit reserved native operation/root required')
        with self.writer._locked(shared=True):
            before = self.writer._control()
        physical._require(before == self.cursor, 'Reserved native cursor changed before save')
        receipt = (self.writer.save(state, expected_preimage=self.cursor['current']) if self.directory_pool is None
            else self.directory_pool.save(self.directory_lease, state, expected_preimage=self.cursor['current']))
        physical._require(self.writer.completed() == receipt, 'Original native completion differs')
        expected = {'operation': None, 'next_slot': self.cursor['next_slot'] + 1,
            'current': receipt['state'], 'last': {'slot': receipt['slot'],
            'receipt_sha256': physical._sha(physical._encoded(receipt))}}
        with self.writer._locked(shared=True):
            physical._require(self.writer._control() == expected, 'Reserved native completion cursor differs')
        self.cursor = expected
        self.saved.append(receipt)
        return paper.state_path(root)

    # Return finite physical evidence while keeping local completion distinct from adoption.
    def evidence(self):
        self.guard()
        self._lease()
        physical._require(not self.failed and self.directory is not None,
                          'Uncertain/unreserved operation has no evidence')
        with self.writer._locked(shared=True):
            physical._require(self.writer._control() == self.cursor, 'Reserved native evidence cursor differs')
        extra = {} if self.metadata_pool is None else {'protocol': self.metadata_ref}
        if self.sqlite_pool is not None:
            extra['reserved_sqlite'] = self.sqlite_lease
        if self.directory_pool is not None:
            extra['native_directory'] = self.directory_lease
        return {'schema': DIRECTORY_SCHEMA if self.directory_pool is not None else SQLITE_SCHEMA if self.sqlite_pool is not None else
                SCHEMA if self.metadata_pool is None else METADATA_SCHEMA, **extra,
            'reservation_sha256': sha256(protocol.read(self.bound_nightly,
                self.directory / 'reserved-native-save.json', self.metadata_legacy)).hexdigest(),
            'saves': deepcopy(self.saved), 'native_operation_adopted': False,
            'reserved_cas': self.reserved_cas, 'effect_binding': self.effect_binding}

    # Observe explicit saves and policy calls without replacing paper.save_state.
    @contextmanager
    def capture(self, legacy, store, root, client, policy, checkpoint, write_reference):
        self.guard()
        capture = legacy.NativeCapture(store, root, client, policy, raw_checkpoint=checkpoint)
        physical._require(legacy.LOCK.locked() and paper.save_state is self.writer.writer
            and legacy.native.ReplayBroker._submit is legacy.SUBMIT
            and 'decide' not in policy.__dict__, 'Original reserved observation scope required')
        original = policy.decide
        owner = get_ident()

        # Reject changed ownership or hooks before observing any explicit native operation.
        def owned():
            self.guard()
            self._lease()
            physical._require(not self.failed and legacy.LOCK.locked() and get_ident() == owner
                and paper.save_state is self.writer.writer
                and legacy.native.ReplayBroker._submit is submit
                and policy.__dict__.get('decide') is decide, 'Reserved observation scope changed')

        # Keep actual native persistence before raw capture and retain uncertainty on failure.
        def save(account, state):
            owned()
            try:
                result = self.save(account, state)
                reference = checkpoint.capture(result)
                capture.raw_writes.append(write_reference(checkpoint, reference))
                return result
            except BaseException:
                self.failed = True
                capture.recording_failures.append('Reserved native save/capture uncertainty; never replay')
                raise

        # Refuse all broker submissions structurally in this raw synthetic composition.
        def submit(*args, **kwargs):
            owned()
            raise ValueError('Reserved raw synthetic capture has no submission admission')

        # Retain the original synthetic policy's actual answer and observable invocation count.
        def decide(*args, **kwargs):
            owned()
            targets, receipt = original(*args, **kwargs)
            capture.decisions.append(deepcopy({'targets': targets, 'receipt': receipt}))
            return targets, receipt

        capture.save = save
        legacy.native.ReplayBroker._submit, policy.decide = submit, decide
        try:
            yield capture
        finally:
            changed = legacy.native.ReplayBroker._submit is not submit or policy.__dict__.get('decide') is not decide
            legacy.native.ReplayBroker._submit = legacy.SUBMIT
            policy.__dict__.pop('decide', None)
            physical._require(not changed, 'Changed reserved observation bindings')
            self.guard()

    # Refuse further native effects or fresh evidence once the exact CAS lease is uncertain.
    def _lease(self):
        if getattr(self, 'directory_pool', None) is not None:
            try:
                physical._require(self.bound_nightly.store.directory_binding is self.directory_pool,
                                  'Original native-directory pool required before effects')
                self.directory_pool.check(self.directory_lease)
            except BaseException:
                self.failed = True
                raise
        if getattr(self, 'sqlite_pool', None) is not None:
            try:
                physical._require(self.bound_nightly.store.sqlite_reservation is self.sqlite_pool,
                                  'Original SQLite pool required before native work')
                self.sqlite_pool.check(self.sqlite_lease)
            except BaseException:
                self.failed = True
                raise
        if getattr(self, 'metadata_pool', None) is not None:
            try:
                physical._require(protocol.pool(self.bound_nightly) is self.metadata_pool
                    and protocol.reference(self.bound_nightly, self.directory) == self.metadata_ref,
                    'Original retained metadata claim required before native work')
                self.metadata_pool.check_effects(self.directory)
            except BaseException:
                self.failed = True
                raise
        if getattr(self, 'reserved_cas', None) is not None:
            try:
                physical._require(self.cas_store.blob_reservation is self.cas_pool,
                                  'Original retained CAS pool required before native work')
                _, group = self.cas_pool.group(self.reserved_cas, active=True)
                physical._require(group['metadata_pending'] is None,
                                  'Uncertain metadata lease; no further native work')
            except BaseException:
                self.failed = True
                raise


# Bind the exact optional metadata claim into CAS identity while preserving unbound version two.
def operation_identity(nightly, directory, effect_binding):
    reference = protocol.reference(nightly, directory)
    if reference is not None:
        pool = nightly.store.sqlite_reservation
        extra = {} if pool is None else {'sqlite': pool.binding}
        directory_pool = nightly.store.directory_binding
        if directory_pool is not None:
            extra['native_directory'] = directory_pool.binding
        return sha256(physical._encoded({'directory': str(directory),
            'effect_binding': effect_binding, 'protocol': reference, **extra})).hexdigest()
    return (sha256(str(directory).encode()).hexdigest() if effect_binding is None else
        sha256(physical._encoded({'directory': str(directory), 'effect_binding': effect_binding})).hexdigest())


# Authenticate the separate narrow writer and this explicit composition implementation.
def sources():
    return {name: sha256(Path(path).read_bytes()).hexdigest() for name, path in
            (('composition', __file__), ('writer', writer_module.__file__))}


# Validate original slot receipts and anchored bytes without saving or advancing control.
def validate(nightly, directory, evidence, native_contents, legacy, expected):
    raw = protocol.read(nightly, directory / 'reserved-native-save.json', legacy)
    namespace = protocol.pool(nightly)
    extra = set() if namespace is None else {'protocol'}
    sqlite_pool = nightly.store.sqlite_reservation
    directory_pool = nightly.store.directory_binding
    if sqlite_pool is not None:
        extra.add('reserved_sqlite')
    if directory_pool is not None:
        extra.add('native_directory')
    value = legacy.admitted.decoded(raw)
    physical._require(type(value) is dict and set(value) == {'schema', 'identity', 'account',
        'writer_root', 'sources', 'trade_sha256', 'trade_path', 'header_sha256', 'before',
        'native_operation_adopted', 'reserved_cas', 'effect_binding'} | extra and type(evidence) is dict and set(evidence) ==
        ({'schema', 'reservation_sha256', 'saves', 'native_operation_adopted', 'reserved_cas', 'effect_binding'} | extra)
        and evidence['schema'] == value['schema'] == (DIRECTORY_SCHEMA if directory_pool is not None else SQLITE_SCHEMA if sqlite_pool is not None else
            SCHEMA if namespace is None else METADATA_SCHEMA)
        and (namespace is None or value['protocol'] == evidence['protocol'] == protocol.reference(nightly, directory))
        and (namespace is None or value['protocol']['head'] == value['reserved_cas']['head']
             and (value['effect_binding'] is None or value['protocol']['inputs'] == value['effect_binding']))
        and expected == {**evidence, 'saves': []}
        and evidence['reservation_sha256'] == sha256(raw).hexdigest()
        and evidence['native_operation_adopted'] is value['native_operation_adopted'] is False
        and value['identity'] == nightly.store.identity and value['sources'] == sources()
        and value['account'] == str(nightly.root)
        and Path(value['writer_root']) / 'work' == nightly.root,
        'Original synthetic reserved native evidence required')
    if sqlite_pool is not None:
        physical._require(value['reserved_sqlite'] == evidence['reserved_sqlite']
            and value['reserved_sqlite']['claim'] == value['protocol'], 'Original SQLite phase binding differs')
        sqlite_pool.verify(value['reserved_sqlite'])
    if directory_pool is not None:
        physical._require(value['native_directory'] == evidence['native_directory']
            and value['native_directory']['claim'] == value['protocol'], 'Original directory phase binding differs')
        directory_pool.verify(value['native_directory'])
    physical._require(evidence['reserved_cas'] == value['reserved_cas'], 'Original CAS lease differs')
    physical._require(evidence['effect_binding'] == value['effect_binding'], 'Original effect inputs differ')
    if value['reserved_cas'] is None:
        physical._require(nightly.store.blob_reservation is None, 'Reserved CAS mode cannot downgrade')
    else:
        physical._require(nightly.store.blob_reservation is not None, 'Original reserved CAS binding required')
        nightly.store.blob_reservation.group(value['reserved_cas'])
    trade_path = Path(value['trade_path'])
    physical._require(trade_path.stat().st_size <= physical.META
        and sha256(trade_path.read_bytes()).hexdigest() == value['trade_sha256'],
        'Original synthetic executor source differs')
    writer = writer_module.ReservedWriter(Path(value['writer_root']), writer=paper.save_state,
        writer_source=Path(paper.__file__), identity_sha256=nightly.store.identity)
    physical._require(sha256((writer.root / 'header').read_bytes()).hexdigest() == value['header_sha256']
        and value['before']['operation'] is None and type(evidence['saves']) is list
        and len(evidence['saves']) <= writer.header['slots'], 'Reserved native header/range differs')
    prior = value['before']['current']
    for offset, receipt in enumerate(evidence['saves']):
        if directory_pool is not None:
            directory_pool.verify_save(value['native_directory'], receipt)
        slot = value['before']['next_slot'] + offset
        writer._receipt(receipt, {'last': {'slot': slot}})
        physical._require(physical._fixed_read(writer.root / 'receipts' / str(slot)) == receipt
            and receipt['prior'] == prior
            and writer_module._image(writer.root / 'anchors' / str(slot)) == receipt['state'],
            'Original reserved native slot/anchor differs')
        prior = receipt['state']
    expected = [(row['state']['sha256'], row['state']['length']) for row in evidence['saves']]
    physical._require(expected == list(native_contents), 'Reserved native saves/captures differ')
    return evidence


# Seal only the original published result's reserved phase, including metadata-only recovery.
def complete(nightly, declaration, result):
    if declaration is not None and declaration.get('native_directory') is not None:
        physical._require(nightly.store.directory_binding is not None, 'Original directory phase mode required')
        nightly.store.directory_binding.complete(declaration['native_directory'], result)
    if declaration is not None and declaration.get('reserved_sqlite') is not None:
        physical._require(nightly.store.sqlite_reservation is not None, 'Original SQLite phase mode required')
        nightly.store.sqlite_reservation.complete(declaration['reserved_sqlite'], result)
    if declaration is not None and declaration['reserved_cas'] is not None:
        physical._require(nightly.store.blob_reservation is not None, 'Original reserved CAS binding required')
        nightly.store.blob_reservation.complete(declaration['reserved_cas'], result)


# Validate pre-close bytes without allocating or publishing a duplicate Store component.
def current_components(nightly, client, prior, checkpoint, legacy):
    root = checkpoint.verify(prior['paper']['checkpoint'])
    image = writer_module._image(paper.state_path(nightly.root))
    physical._require((image['sha256'], image['length']) == (root['raw_sha256'], root['raw_bytes'])
        and nightly.store.read_blob(prior['broker'], limit=legacy.codec.CAPS['bytes'])
            == legacy.codec.encode(client, **nightly.pins()),
        'Original reserved pre-close components differ')
    return prior
