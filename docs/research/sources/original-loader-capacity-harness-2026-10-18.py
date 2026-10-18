"""SOURCE ONLY: proposed N2 capacity harness, with no admitted execution entry point.

No application module is imported at module scope. This draft has not been
imported or executed. A separately reviewed controller, exact call manifest,
source tree, runtime/mount admission and synthetic acceptance are still absent.
The Python guards constrain accidental calls in authenticated code; they are
not a sandbox against hostile native extensions or a privileged host.
"""

import dataclasses
import fcntl
import hashlib
import importlib.abc
import importlib.util
import json
import marshal
import os
import resource
import socket
import stat
import sys
import time
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from types import CodeType

CONTRACT_SHA256 = 'ecc58ad7f6ec65bb42a28ef0c2bea8d116b0e9be5ea59e490388fa0e74dfddc8'
RECIPE_SHA256 = '503e8d508ebe5fdc82a17c11974ccce5366c60ce8e78fc549c129fc6c6d81e03'
IMAGE = 'sha256:e0a54c1f3b293c241ea0eae767d8ba017d0e1a05679965935b336910faa63237'
PHASES = ('BOOTSTRAP', 'ADMISSION', 'BEFORE', 'LOAD', 'FROZEN', 'AFTER', 'SERIALIZE', 'DONE')
FAILURE_BYTES = 65536
MAX_PYTHON_BYTES = 1024 ** 2
MAX_METADATA_BYTES = 16 * 1024 ** 2
MAX_CODES_PER_MODULE = 20000
FORBIDDEN_NAMES = frozenset({
    'audit', 'verify', 'distribution', 'select', 'fit', '_fit', 'partial_fit',
    'fit_transform', 'fit_log', 'fit_market_log', 'walk_forward', 'save_state',
    'submit_order', 'cancel_order', 'send_order', 'place_order',
})
EFFECT_MODULES = (
    'backend.market.replay_broker', 'backend.market.alpaca_trading',
    'backend.agents.trading.desk', 'backend.market.joint_funded_policy',
    'backend.market.adaptive_growth_policy',
)
FORBIDDEN_CLASSES = (
    ('backend.market.live_model_history_stream_audit', 'StreamAudit'),
    ('backend.market.live_model_history', 'FrozenCurrentGradePolicy'),
)
DENIED_AUDIT_EVENTS = frozenset({
    'socket.__new__', 'socket.connect', 'socket.bind', 'subprocess.Popen',
    'os.system', 'os.fork', 'os.forkpty', 'os.posix_spawn', 'os.exec',
})


# Refuse unavailable source/admission facts without inventing a default.
def require(condition, message):
    if not condition:
        raise RuntimeError(message)


# Reject duplicate metadata fields without silently selecting a later value.
def unique_fields(pairs):
    result = {}
    for name, value in pairs:
        require(name not in result, 'DUPLICATE_METADATA_FIELD')
        result[name] = value
    return result


# Refuse nonfinite JSON tokens before they become admission facts.
def nonfinite_token(value):
    raise RuntimeError('NONFINITE_METADATA_TOKEN')


# Decode only finite, duplicate-free, bounded external metadata.
def metadata(raw):
    require(type(raw) is bytes and len(raw) <= MAX_METADATA_BYTES, 'BOUNDED_METADATA_BYTES_REQUIRED')
    return json.loads(raw, object_pairs_hook=unique_fields, parse_constant=nonfinite_token)


# Preserve exact physical counters without a floating-point timestamp roundtrip.
def physical(value):
    return {name: str(getattr(value, name)) for name in (
        'st_dev', 'st_ino', 'st_mode', 'st_uid', 'st_nlink', 'st_size',
        'st_mtime_ns', 'st_ctime_ns',
    )}


# Open each directory component without following a source-root symlink.
def directory_fd(path):
    path = PurePosixPath(path)
    require(path.is_absolute() and '..' not in path.parts, 'ABSOLUTE_ROOT_REQUIRED')
    current = os.open('/', os.O_RDONLY | os.O_DIRECTORY)
    try:
        for name in path.parts[1:]:
            following = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=current)
            os.close(current)
            current = following
        return current
    except BaseException:
        os.close(current)
        raise


# Hold only SHA-pinned source files beneath an already held source directory.
class SourceBook:
    # Bind the exact composed recipe before any backend module can be imported.
    def __init__(self, root, pins):
        require(type(pins) is dict and len(pins) == 2446, 'COMPLETE_RECIPE_REQUIRED')
        compact = json.dumps(pins, sort_keys=True, separators=(',', ':')).encode()
        require(hashlib.sha256(compact).hexdigest() == RECIPE_SHA256, 'RECIPE_DIFFERS')
        self.root = str(PurePosixPath(root))
        self.fd = directory_fd(self.root)
        self.pins = dict(pins)
        self.bookends = {}
        self.authenticated = False

    # Read one exact bounded source with held-FD and directory-relative bookends.
    def read(self, name, *, limit=MAX_METADATA_BYTES):
        path = PurePosixPath(name)
        require(not path.is_absolute() and '..' not in path.parts and str(path) == name, 'CANONICAL_SOURCE_NAME_REQUIRED')
        require(name in self.pins, 'UNDECLARED_SOURCE')
        parent = os.dup(self.fd)
        descriptor = None
        try:
            for part in path.parts[:-1]:
                following = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
                os.close(parent)
                parent = following
            descriptor = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=parent)
            before = os.fstat(descriptor)
            require(stat.S_ISREG(before.st_mode) and 0 <= before.st_size <= limit, 'BOUNDED_REGULAR_SOURCE_REQUIRED')
            chunks, count, checksum = [], 0, hashlib.sha256()
            while block := os.read(descriptor, min(65536, limit + 1 - count)):
                count += len(block)
                require(count <= limit, 'SOURCE_GREW_PAST_BOUND')
                checksum.update(block)
                chunks.append(block)
            after = os.fstat(descriptor)
            named = os.stat(path.name, dir_fd=parent, follow_symlinks=False)
            require(physical(before) == physical(after) == physical(named), 'SOURCE_IDENTITY_CHANGED')
            require(count == before.st_size and checksum.hexdigest() == self.pins[name], 'SOURCE_BYTES_DIFFER')
            identity = physical(before)
            if name in self.bookends:
                require(self.bookends[name] == identity, 'SOURCE_CHANGED_SINCE_ADMISSION')
            self.bookends[name] = identity
            return b''.join(chunks)
        finally:
            if descriptor is not None:
                os.close(descriptor)
            os.close(parent)

    # Authenticate the entire composed source recipe without importing its files.
    def authenticate_all(self):
        self.authenticated = False
        for name in sorted(self.pins):
            self.read(name)
        self.authenticated = True

    # Close only this reader's held source-root descriptor.
    def close(self):
        os.close(self.fd)


# Stop a single owned capacity process before an unadmitted call body executes.
class CallFence:
    # Require an external reviewed phase manifest and a preallocated failure slot.
    def __init__(self, book, manifest_raw, manifest_sha256, failure_fd):
        require(type(manifest_raw) is bytes and len(manifest_raw) <= MAX_METADATA_BYTES and hashlib.sha256(manifest_raw).hexdigest() == manifest_sha256, 'EXTERNALLY_PINNED_CALL_MANIFEST_REQUIRED')
        manifest = metadata(manifest_raw)
        require(type(manifest) is dict and set(manifest) == {'schema', 'recipe_sha256', 'contract_sha256', 'calls', 'generated'}, 'EXACT_CALL_MANIFEST_REQUIRED')
        require(manifest['schema'] == 'n2-capacity-call-manifest/1' and manifest['recipe_sha256'] == RECIPE_SHA256 and manifest['contract_sha256'] == CONTRACT_SHA256, 'CALL_MANIFEST_BINDING_DIFFERS')
        require(type(manifest['calls']) is dict and set(manifest['calls']) == set(PHASES), 'ALL_PHASE_CALL_LISTS_REQUIRED')
        require(all(type(rows) is list for rows in manifest['calls'].values()) and type(manifest['generated']) is list, 'EXPLICIT_CALL_LISTS_REQUIRED')
        for rows in manifest['calls'].values():
            require(len(rows) <= 50000, 'PHASE_CALL_COUNT_BOUND')
            keys = set()
            for row in rows:
                require(type(row) is list and len(row) == 3 and type(row[0]) is str and row[0] in book.pins and row[0].endswith('.py') and type(row[1]) is str and len(row[1]) <= 512 and type(row[2]) is int and row[2] > 0, 'EXACT_PHASE_CALL_IDENTITY_REQUIRED')
                require(tuple(row) not in keys, 'DUPLICATE_PHASE_CALL')
                keys.add(tuple(row))
        fields = {'kind', 'phase', 'module', 'qualname', 'line', 'filename', 'code_sha256', 'producer_source_sha256'}
        require(len(manifest['generated']) <= 10000, 'GENERATED_CALL_COUNT_BOUND')
        for row in manifest['generated']:
            require(type(row) is dict and set(row) == fields and all(type(row[name]) is str for name in fields - {'line'}) and type(row['line']) is int and row['line'] > 0, 'EXACT_GENERATED_CODE_IDENTITY_REQUIRED')
            require(row['phase'] in PHASES and row['module'].startswith('backend.') and len(row['qualname']) <= 512, 'GENERATED_CODE_SCOPE_REQUIRED')
            require(all(len(row[name]) == 64 and all(char in '0123456789abcdef' for char in row[name]) for name in ('code_sha256', 'producer_source_sha256')), 'GENERATED_CODE_HASH_REQUIRED')
            if row['kind'] == 'stdlib-dataclass-exact-native-code':
                require(row['filename'] == '<string>', 'EXACT_DATACLASS_FILENAME_REQUIRED')
            else:
                require(row['kind'] == 'exact-original-daily-prefix-transformation-40d0d7cf' and row['filename'] == '<pinned daily prefix>' and row['module'] == 'backend.cli.market_strategy_continue' and row['qualname'] in ('<module>', 'inputs') and row['phase'] == 'LOAD', 'EXACT_DAILY_PREFIX_RECORD_REQUIRED')
        slot = os.fstat(failure_fd)
        flags = fcntl.fcntl(failure_fd, fcntl.F_GETFL)
        require(flags & os.O_ACCMODE == os.O_RDWR and not flags & os.O_APPEND, 'READWRITE_NONAPPEND_FAILURE_SLOT_REQUIRED')
        require(stat.S_ISREG(slot.st_mode) and slot.st_uid == os.getuid() and slot.st_nlink == 1 and slot.st_size == FAILURE_BYTES and slot.st_blocks * 512 >= FAILURE_BYTES, 'PREALLOCATED_FAILURE_SLOT_REQUIRED')
        require(os.pread(failure_fd, FAILURE_BYTES, 0) == bytes(FAILURE_BYTES), 'FAILURE_SLOT_NOT_EMPTY')
        self.book, self.manifest, self.failure_fd = book, manifest, failure_fd
        self.manifest_sha256 = manifest_sha256
        self.phase, self.active, self.installing = 'BOOTSTRAP', False, False
        self.codes, self.seen, self.denied = {}, set(), False
        self.dataclass_source = hashlib.sha256(Path(dataclasses.__file__).read_bytes()).hexdigest()

    # Register only code objects compiled from an authenticated backend file.
    def register(self, path, code):
        pending, count = [code], 0
        while pending:
            item = pending.pop()
            count += 1
            require(count <= MAX_CODES_PER_MODULE, 'COMPILED_SOURCE_CODE_BOUND')
            self.codes[id(item)] = (item, path, item.co_qualname, item.co_firstlineno)
            pending.extend(value for value in item.co_consts if isinstance(value, CodeType))

    # Write one bounded diagnosis and exit even if application code catches errors.
    def trip(self, reason, identity=''):
        self.denied = True
        raw = json.dumps({'status': 'FAILED_CLOSED', 'phase': self.phase, 'reason': reason[:128], 'identity': identity[:1024], 'publication': 'CLOSED'}, sort_keys=True, allow_nan=False).encode()
        try:
            body = raw + bytes(FAILURE_BYTES - len(raw))
            offset = 0
            while offset < len(body):
                count = os.pwrite(self.failure_fd, body[offset:], offset)
                if count <= 0:
                    break
                offset += count
            os.fsync(self.failure_fd)
        finally:
            os._exit(86)

    # Reject Python backend calls by their actual compiled identity, including aliases.
    def profile(self, frame, event, argument):
        if not self.active:
            return
        if event == 'c_call':
            name = getattr(argument, '__name__', '')
            module = getattr(argument, '__module__', '') or ''
            if argument is sys.setprofile and not self.installing:
                self.trip('PROFILE_REPLACEMENT')
            if module == '_thread' and name in ('start_new_thread', 'start_joinable_thread'):
                self.trip('UNADMITTED_PYTHON_THREAD')
            if module.startswith(('numpy', 'scipy', 'sklearn', 'backend')) and name in FORBIDDEN_NAMES:
                self.trip('FORBIDDEN_NATIVE_CALL', module + '.' + name)
            return
        if event != 'call':
            return
        code = frame.f_code
        module = frame.f_globals.get('__name__', '')
        backend = type(module) is str and (module == 'backend' or module.startswith('backend.'))
        if code.co_name in FORBIDDEN_NAMES and (backend or str(module).startswith(('sklearn', 'scipy'))):
            self.trip('FORBIDDEN_FUNCTION', str(module) + '.' + code.co_qualname)
        if not backend and not code.co_filename.startswith(self.book.root + '/backend/'):
            return
        if str(module).startswith(EFFECT_MODULES) and code.co_flags & 0x0002:
            self.trip('BROKER_OR_ACCOUNT_FUNCTION', str(module) + '.' + code.co_qualname)
        if code.co_flags & 0x0002 and any(module == owner and (code.co_qualname == name or code.co_qualname.startswith(name + '.')) for owner, name in FORBIDDEN_CLASSES):
            self.trip('FORBIDDEN_STATEFUL_CLASS', str(module) + '.' + code.co_qualname)
        registered = self.codes.get(id(code))
        if registered is not None and registered[0] is code:
            _, path, qualified, line = registered
            key = [path, qualified, line]
            if key not in self.manifest['calls'][self.phase]:
                self.trip('UNREVIEWED_PHASE_CALL', path + ':' + qualified)
            self.seen.add((self.phase, path, qualified, line))
            return
        # These two producer paths are distinct, exact dynamic-code seams.
        # Neither permits a wildcard filename, source or code fingerprint.
        if code.co_filename == '<string>':
            producer = self.dataclass_source
            kind = 'stdlib-dataclass-exact-native-code'
        elif code.co_filename == '<pinned daily prefix>' and module == 'backend.cli.market_strategy_continue' and code.co_qualname in ('<module>', 'inputs') and self.phase == 'LOAD':
            producer = self.book.pins['backend/market/live_model_history_audit_inputs.py']
            if producer != 'fae5bfc7d7438071094f31f42e884cb48e3709c55f364954e51c28302d3c3e30':
                self.trip('DAILY_PREFIX_PRODUCER_DIFFERS')
            kind = 'exact-original-daily-prefix-transformation-40d0d7cf'
        else:
            self.trip('UNREGISTERED_OR_GENERATED_CODE', str(module) + '.' + code.co_qualname)
        generated = {'kind': kind, 'phase': self.phase, 'module': str(module), 'qualname': code.co_qualname, 'line': code.co_firstlineno, 'filename': code.co_filename, 'code_sha256': hashlib.sha256(marshal.dumps(code)).hexdigest(), 'producer_source_sha256': producer}
        if generated not in self.manifest['generated']:
            self.trip('UNREVIEWED_GENERATED_CODE', str(module) + '.' + code.co_qualname)

    # Deny network/process creation and guard removal without logging arguments.
    def audit(self, event, arguments):
        if not self.active:
            return
        if event in DENIED_AUDIT_EVENTS:
            self.trip('FORBIDDEN_AUDIT_EVENT', event)
        if event in ('sys.setprofile', 'sys.settrace') and not self.installing:
            self.trip('PROFILE_OR_TRACE_REPLACEMENT', event)

    # Install both guards before any backend import; never accept preloaded backend.
    def install(self):
        require(not any(name == 'backend' or name.startswith('backend.') for name in sys.modules), 'BACKEND_PRELOADED')
        require(sys.getprofile() is None and sys.gettrace() is None, 'EXISTING_INSTRUMENTATION')
        self.active, self.installing = True, True
        sys.addaudithook(self.audit)
        sys.setprofile(self.profile)
        self.installing = False
        require(sys.getprofile() == self.profile, 'PROFILE_NOT_INSTALLED')

    # Advance exactly once through the fixed workflow phase order.
    def advance(self, phase):
        require(PHASES.index(phase) == PHASES.index(self.phase) + 1, 'PHASE_ORDER_DIFFERS')
        require(sys.getprofile() == self.profile and self.active and not self.denied, 'CALL_GUARD_NOT_HEALTHY')
        self.phase = phase


# Resolve backend imports only through the authenticated source recipe.
class PinnedBackendFinder(importlib.abc.MetaPathFinder, importlib.abc.Loader):
    # Share the held source book and the guard installed before first import.
    def __init__(self, book, fence):
        self.book, self.fence, self.paths = book, fence, {}

    # Refuse absent or shadowed backend modules instead of falling back to the image.
    def find_spec(self, fullname, path=None, target=None):
        if fullname != 'backend' and not fullname.startswith('backend.'):
            return None
        stem = fullname.replace('.', '/')
        choices = [name for name in (stem + '.py', stem + '/__init__.py') if name in self.book.pins]
        require(len(choices) == 1, 'EXACT_BACKEND_MODULE_REQUIRED')
        selected = choices[0]
        self.paths[fullname] = selected
        spec = importlib.util.spec_from_loader(fullname, self, origin=self.book.root + '/' + selected, is_package=selected.endswith('/__init__.py'))
        spec.has_location = True
        return spec

    # Use import machinery's new empty module without loading ambient bytecode.
    def create_module(self, spec):
        return None

    # Compile authenticated bytes and register all function identities before execution.
    def exec_module(self, module):
        name = self.paths[module.__name__]
        raw = self.book.read(name, limit=MAX_PYTHON_BYTES)
        code = compile(raw, self.book.root + '/' + name, 'exec', dont_inherit=True, optimize=0)
        self.fence.register(name, code)
        exec(code, module.__dict__)


# Check the independently pinned runtime before importing the numerical audit CLI.
def preimport_runtime(value, actual, book):
    require(type(actual) is list and len(actual) == 1, 'ONE_ACTUAL_RUNTIME_REQUIRED')
    row = actual[0]
    config, host = row['Config'], row['HostConfig']
    require(value['profile'] == 'original-full-27471' and row['Image'] == IMAGE, 'EXACT_ORIGINAL_AUDITOR_REQUIRED')
    require(row['Id'].startswith(socket.gethostname()) and config['Hostname'] == socket.gethostname() and config['User'] in ('1000', '1000:1000') and os.getuid() == 1000, 'ACTUAL_OWNER_HOSTNAME_REQUIRED')
    require(host['NetworkMode'] == 'none' and host['ReadonlyRootfs'] is True and host['NanoCpus'] == 1000000000 and host['Memory'] == host['MemorySwap'] == 2147483648 and host['Tmpfs'] == {'/tmp': 'rw,size=64m'}, 'EXACT_EXISTING_RESOURCE_GUARD_REQUIRED')
    require(host.get('Privileged', False) is False and not host.get('CapAdd') and not host.get('Devices'), 'NO_PRIVILEGED_RUNTIME')
    require(sys.flags.optimize == 0 and 'numpy' not in sys.modules and 'sklearn' not in sys.modules, 'PREIMPORT_NATIVE_BOUNDARY_REQUIRED')
    mounts = row['Mounts']
    writable = [item for item in mounts if item['RW']]
    require(len(writable) == 1 and writable[0]['Type'] == 'bind' and writable[0]['Destination'] == value['proof_parent'], 'SOLE_PROOF_BIND_REQUIRED')
    proof_source = PurePosixPath(writable[0]['Source'])
    for item in mounts:
        if item['RW']:
            continue
        source = PurePosixPath(item['Source'])
        require(not proof_source.is_relative_to(source) and not source.is_relative_to(proof_source), 'PROOF_INPUT_OVERLAP')
    for target in (value['account'], value['market'], book.root):
        covering = [item for item in mounts if PurePosixPath(target).is_relative_to(item['Destination'])]
        require(bool(covering), 'READONLY_INPUT_BIND_REQUIRED')
        chosen = max(covering, key=lambda item: len(PurePosixPath(item['Destination']).parts))
        require(chosen['Type'] == 'bind' and chosen['RW'] is False, 'READONLY_INPUT_BIND_REQUIRED')
        if target == value['account']:
            mapped = PurePosixPath(chosen['Source']) / PurePosixPath(target).relative_to(chosen['Destination'])
            require(str(mapped) == '/home/animallya96/scratch/live-model-history-full-20261013-v1/output/account', 'EXACT_ORIGINAL_ACCOUNT_MAPPING_REQUIRED')
    require(book.root == '/app' and value['audit_source_sha256'] == book.pins, 'EXACT_AUDITOR_SOURCE_ROOT_REQUIRED')
    # Full unchanged runtime_admission is still called after importing its
    # authenticated module. This precheck does not replace mount admission.


# Read only a finite kernel counter file, preserving unavailable metrics as failure.
def kernel_text(path):
    with Path(path).open('rb') as source:
        raw = source.read(65537)
    require(len(raw) <= 65536, 'KERNEL_COUNTER_BOUND')
    return raw.decode('ascii').strip()


# Record process and container memory while the actual phase roots remain live.
def measurement(phase):
    require(kernel_text('/proc/self/cgroup') == '0::/', 'PRIVATE_CGROUP_NAMESPACE_REQUIRED')
    require(kernel_text('/sys/fs/cgroup/memory.max') == '2147483648' and kernel_text('/sys/fs/cgroup/memory.swap.max') == '0', 'EXACT_CGROUP_MEMORY_REQUIRED')
    status = dict(line.split(':', 1) for line in kernel_text('/proc/self/status').splitlines() if ':' in line)
    return {
        'phase': phase, 'monotonic': time.monotonic(),
        'ru_maxrss_kib': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        'VmRSS': status['VmRSS'].strip(), 'VmHWM': status['VmHWM'].strip(),
        'cgroup': {name: kernel_text('/sys/fs/cgroup/' + name) for name in ('memory.current', 'memory.peak', 'memory.events', 'memory.swap.current')},
    }


# Inventory retained array ownership without copying buffers or calling properties.
def retained_arrays(root, numpy):
    stack, visited, arrays = [('loaded', root)], set(), []
    while stack:
        name, value = stack.pop()
        if id(value) in visited:
            continue
        visited.add(id(value))
        require(len(visited) <= 100000, 'RETAINED_OBJECT_BOUND')
        if isinstance(value, numpy.ndarray):
            base, seen = value, set()
            while isinstance(base, numpy.ndarray) and base.base is not None:
                require(id(base) not in seen and len(seen) <= 64, 'ARRAY_BASE_CHAIN_BOUND')
                seen.add(id(base))
                base = base.base
            arrays.append({'name': name, 'object_id': str(id(value)), 'base_object_id': str(id(base)), 'shape': list(value.shape), 'dtype': str(value.dtype), 'view_nbytes': str(value.nbytes), 'writeable': bool(value.flags.writeable), 'owns_data': bool(value.flags.owndata)})
            require(len(arrays) <= 10000, 'RETAINED_ARRAY_BOUND')
        elif type(value) is dict:
            require(len(stack) + len(value) <= 100000, 'RETAINED_STACK_BOUND')
            stack.extend((name + '.' + str(key), item) for key, item in value.items())
        elif type(value) in (tuple, list):
            require(len(stack) + len(value) <= 100000, 'RETAINED_STACK_BOUND')
            stack.extend((name + '[' + str(index) + ']', item) for index, item in enumerate(value))
        elif dataclasses.is_dataclass(type(value)):
            stack.extend((name + '.' + field.name, object.__getattribute__(value, field.name)) for field in dataclasses.fields(value))
        else:
            try:
                attributes = object.__getattribute__(value, '__dict__')
            except (AttributeError, TypeError):
                continue
            if type(attributes) is dict:
                stack.extend((name + '.' + key, item) for key, item in attributes.items() if type(key) is str)
    require(len(json.dumps(arrays).encode()) <= 1024 ** 2, 'ARRAY_INVENTORY_BOUND')
    return arrays


# Persist each completed small phase without treating a running PID as success.
def record_phase(destination, marks):
    require(len(marks) <= 8, 'PHASE_RECORD_BOUND')
    body = json.dumps(marks[-1], sort_keys=True, allow_nan=False).encode()
    require(len(body) <= 65536, 'PHASE_RECORD_BYTES_BOUND')
    with (destination / ('phase-' + str(len(marks)) + '.json')).open('xb') as output:
        output.write(body)
        output.flush()
        os.fsync(output.fileno())
    descriptor = directory_fd(str(destination))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


# Describe the real loader workflow for later guarded synthetic source validation.
def _capacity_steps(invocation_path, invocation_sha256, runtime_raw, book, fence):
    import importlib

    require(type(fence) is CallFence and fence.book is book and fence.active and fence.phase == 'BOOTSTRAP' and sys.getprofile() == fence.profile and not fence.denied, 'PREIMPORT_CALL_GUARD_REQUIRED')
    require(type(book) is SourceBook and book.authenticated, 'COMPLETE_SOURCE_ADMISSION_REQUIRED')
    require(bool(sys.meta_path) and type(sys.meta_path[0]) is PinnedBackendFinder and sys.meta_path[0].book is book and sys.meta_path[0].fence is fence, 'PINNED_IMPORT_FINDER_MUST_BE_FIRST')
    require(len(runtime_raw) <= MAX_METADATA_BYTES, 'BOUNDED_RUNTIME_METADATA_REQUIRED')
    with Path(invocation_path).open('rb') as source:
        invocation_raw = source.read(MAX_METADATA_BYTES + 1)
    require(len(invocation_raw) <= MAX_METADATA_BYTES and hashlib.sha256(invocation_raw).hexdigest() == invocation_sha256, 'EXTERNAL_INVOCATION_BYTES_REQUIRED')
    value = metadata(invocation_raw)
    require(hashlib.sha256(runtime_raw).hexdigest() == value['runtime_sha256'], 'EXTERNAL_RUNTIME_BYTES_REQUIRED')
    preimport_runtime(value, metadata(runtime_raw), book)
    audit = importlib.import_module('backend.cli.audit_original_live_model_history')
    fence.advance('ADMISSION')
    require(audit.invocation(invocation_path, invocation_sha256) == value, 'UNCHANGED_INVOCATION_ADMISSION_REQUIRED')
    runtime = audit.runtime_admission(value)
    require(audit.np.__version__ == '2.5.3' and audit.sklearn.__version__ == '1.9.1', 'EXACT_NATIVE_PACKAGES_REQUIRED')
    started = datetime.now(UTC)
    destination = Path(value['proof_parent']) / 'original-loader-capacity'
    parent = audit.byte_auth.physical(value['proof_parent'])
    require(parent.is_dir() and parent.stat().st_uid == 1000 and {p.name for p in parent.iterdir()} == {'guard-failure.bin'}, 'NEW_OWNED_PROOF_ROOT_WITH_ONLY_RESERVED_GUARD_SLOT_REQUIRED')
    require(physical((parent / 'guard-failure.bin').stat(follow_symlinks=False)) == physical(os.fstat(fence.failure_fd)), 'RESERVED_FAILURE_FD_PATH_DIFFERS')
    destination.mkdir(mode=0o700, exist_ok=False)
    archives = audit.OriginalArchives(value['account'], value['completion_sha256'], value['initial_sha256'], value['manifest'], value['manifest_sha256'], scratch=destination / 'streamed-history', external_inputs=True)
    source = audit.source_admission(value, archives)
    producer = audit.producer_admission(value)
    calendar = audit.calendar_admission(archives, value['profile'])
    preserved = audit.preserved_archives(archives, value['physical_sha256'], value['physical_bytes'])
    pins = audit.byte_auth.Pins(value['profile'], value['completion_sha256'], value['manifest_sha256'], value['execution_sha256'])
    marks = [measurement('ADMISSION')]
    record_phase(destination, marks)
    fence.advance('BEFORE')
    before = audit.byte_auth.authenticate(Path(value['account']) / 'completion.json', value['manifest'], value['execution'], pins, external_inputs=True, scratch=destination / 'input-auth-before')
    marks.append(measurement('BEFORE'))
    record_phase(destination, marks)
    fence.advance('LOAD')
    loaded = audit.loader.load(archives, value['market'], observed_at=started)
    fence.advance('FROZEN')
    marks.append(measurement('FROZEN'))
    record_phase(destination, marks)
    inventory = retained_arrays(loaded, audit.np)
    # No select/distribution/StreamAudit/planner/broker/account call follows.
    fence.advance('AFTER')
    after = audit.byte_auth.authenticate(Path(value['account']) / 'completion.json', value['manifest'], value['execution'], pins, external_inputs=True, scratch=destination / 'input-auth-after')
    require(before == after, 'COMPLETE_BYTE_RECEIPTS_CHANGED')
    require(audit.preserved_archives(archives, value['physical_sha256'], value['physical_bytes']) == preserved, 'ORIGINAL_STATE_CHANGED')
    book.authenticate_all()
    marks.append(measurement('AFTER'))
    record_phase(destination, marks)
    fence.advance('SERIALIZE')
    result = {
        'status': 'CAPACITY_CANDIDATE_REQUIRES_INDEPENDENT_TERMINAL_ACCEPTANCE',
        'runtime': runtime, 'source': source, 'producer': producer, 'calendar': calendar,
        'input_bytes': before, 'publication': 'CLOSED',
        'retained_arrays': inventory,
        'current_live_timing_parity': 'FAILED_ORIGINAL_UNCHANGED',
        'historical_publication_authorized': False, 'account_or_orders': False,
        'full_distribution_cache_or_horizon_acceptance': False,
        'full_fixed_calibration_dates': len(loaded.reader._parent._frozen_dates),
        'risk_bank_rows': len(loaded.reader._parent._bank['dates']),
    }
    serialized = json.dumps(result, sort_keys=True, indent=2, allow_nan=False)
    encoded = serialized.encode('utf-8')
    require(len(encoded) <= 256 * 1024 ** 2, 'CAPACITY_RESULT_BOUND_EXCEEDED')
    with (destination / 'candidate.json').open('xb') as output:
        output.write(encoded)
        output.flush()
        os.fsync(output.fileno())
    marks.append(measurement('SERIALIZED_WITH_BOTH_RECEIPTS_AND_LOADED_CONTEXT'))
    record_phase(destination, marks)
    # References deliberately remain live until the last measurement; neither
    # receipt nor the loaded context is dropped to manufacture a smaller peak.
    require(before == after and loaded is not None and archives is not None and serialized and encoded, 'COEXISTENCE_ROOTS_REQUIRED')
    fence.advance('DONE')
    return marks


# Keep every public invocation inert until a different reviewed admission exists.
def execute(*arguments, **keywords):
    raise RuntimeError('SOURCE_ONLY_NO_CONTROLLER_CALL_MANIFEST_OR_EXECUTION_ADMISSION')


if __name__ == '__main__':
    raise SystemExit('SOURCE_ONLY_NOT_EXECUTABLE')
