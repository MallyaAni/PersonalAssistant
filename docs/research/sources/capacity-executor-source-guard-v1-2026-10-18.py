"""SOURCE ONLY: distinct 2468 executor source book, finder and guard proposal.

Every payload body is UNRUN. No tree, call/generated/native manifest, bootstrap,
runtime or admission is supplied. This is not the tested old2446 guard identity.
Selected global/type/dataclass-class-flag/native provenance remains external and
UNRESOLVED; these source checks alone do not establish executable closure.
The guards constrain mistakes in trusted code, not hostile native extensions.
"""

import dataclasses
import fcntl
import hashlib
import importlib.abc
import importlib.util
import json
import marshal
import os
import stat
import sys
from pathlib import PurePosixPath
from types import CodeType

CONTRACT_SHA256 = 'c2a720543b3f2dda0d824e61b6d15f5ee7f7fa47669dad8891d33ff584971b63'
RECIPE_SHA256 = 'b7043211743bad04da3cc894faa6d2d85977d93ff10f4345178fdbad0ff1d3bd'
EXECUTOR_MAP_SHA256 = '544fe1859ec11e62f2bf506eff70e9111a6a930d53dff59450d9d4816abaa202'
DATACLASSES_SHA256 = 'd242aea5fcf6408b1c1f622442f88f68b9526ce1f8bd2890d74a144677c427d9'
IMAGE = 'sha256:e0a54c1f3b293c241ea0eae767d8ba017d0e1a05679965935b336910faa63237'
PHASES = ('BOOTSTRAP', 'ADMISSION', 'BEFORE', 'LOAD', 'FROZEN', 'AFTER', 'SERIALIZE', 'DONE')
FAILURE_BYTES = 65536
MAX_PYTHON_BYTES = 1024 ** 2
MAX_METADATA_BYTES = 16 * 1024 ** 2
MAX_CODES_PER_MODULE = 20000
GENERATED_FINGERPRINT_ALGORITHM = 'cpython-code-marshal-format-2-sha256/1'
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
class CapacitySourceBookV1:
    # Bind the distinct complete map and externally authenticated physical root.
    def __init__(self, root, pins, root_identity):
        require(type(root) is str and str(PurePosixPath(root)) == root, 'CANONICAL_EXECUTOR_ROOT_REQUIRED')
        require(type(pins) is dict and len(pins) == 2468, 'COMPLETE_EXECUTOR_RECIPE_REQUIRED')
        require(all(type(name) is str and str(PurePosixPath(name)) == name and not PurePosixPath(name).is_absolute() and '..' not in PurePosixPath(name).parts and type(value) is str and len(value) == 64 and all(char in '0123456789abcdef' for char in value) for name, value in pins.items()), 'EXACT_EXECUTOR_PINS_REQUIRED')
        compact = json.dumps(pins, sort_keys=True, separators=(',', ':')).encode()
        require(hashlib.sha256(compact).hexdigest() == RECIPE_SHA256, 'EXECUTOR_RECIPE_DIFFERS')
        require(type(root_identity) is dict and all(type(value) is str and value.isdecimal() for value in root_identity.values()), 'EXTERNAL_ROOT_IDENTITY_REQUIRED')
        descriptor = directory_fd(root)
        try:
            require(physical(os.fstat(descriptor)) == root_identity, 'HELD_EXECUTOR_ROOT_DIFFERS')
            self.root, self.fd = root, descriptor
            self.root_identity = dict(root_identity)
            self.pins, self.bookends, self.authenticated = dict(pins), {}, False
            self.assert_root()
        except BaseException:
            os.close(descriptor)
            raise

    # Reopen the named no-follow root and compare it with the held external identity.
    def assert_root(self):
        named = directory_fd(self.root)
        try:
            require(physical(os.fstat(self.fd)) == physical(os.fstat(named)) == self.root_identity, 'EXECUTOR_ROOT_CHANGED')
        finally:
            os.close(named)

    # Read one exact bounded source with held-FD and directory-relative bookends.
    def read(self, name, *, limit=MAX_METADATA_BYTES):
        require(type(limit) is int and 0 <= limit <= MAX_METADATA_BYTES, 'UNCHANGED_SOURCE_BOUND_REQUIRED')
        self.assert_root()
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
            self.assert_root()
            return b''.join(chunks)
        finally:
            if descriptor is not None:
                os.close(descriptor)
            os.close(parent)

    # Authenticate the entire composed source recipe without importing its files.
    def authenticate_all(self):
        self.authenticated = False
        for name in sorted(self.pins):
            self.read(name, limit=MAX_PYTHON_BYTES if name.endswith('.py') else MAX_METADATA_BYTES)
        self.assert_root()
        self.authenticated = True

    # Close only this reader's held source-root descriptor.
    def close(self):
        os.close(self.fd)


# Stop a single owned capacity process before an unadmitted call body executes.
class CapacityCallFenceV1:
    # Require an external reviewed phase manifest and a preallocated failure slot.
    def __init__(self, book, manifest_raw, manifest_sha256, failure_fd):
        require(type(book) is CapacitySourceBookV1 and book.authenticated is True, 'FULL_EXECUTOR_BOOK_REQUIRED')
        book.assert_root()
        require(type(manifest_raw) is bytes and len(manifest_raw) <= MAX_METADATA_BYTES and hashlib.sha256(manifest_raw).hexdigest() == manifest_sha256, 'EXTERNALLY_PINNED_CALL_MANIFEST_REQUIRED')
        manifest = metadata(manifest_raw)
        require(type(manifest) is dict and set(manifest) == {'schema', 'recipe_sha256', 'executor_map_sha256', 'root_identity', 'contract_sha256', 'dataclasses', 'fingerprint', 'calls', 'generated'}, 'EXACT_CALL_MANIFEST_REQUIRED')
        require(manifest['schema'] == 'capacity-executor-call-manifest/1' and manifest['executor_map_sha256'] == EXECUTOR_MAP_SHA256 and manifest['root_identity'] == book.root_identity and manifest['recipe_sha256'] == RECIPE_SHA256 and manifest['contract_sha256'] == CONTRACT_SHA256, 'CALL_MANIFEST_BINDING_DIFFERS')
        require(type(manifest['fingerprint']) is dict and set(manifest['fingerprint']) == {'algorithm', 'marshal_version'} and manifest['fingerprint']['algorithm'] == GENERATED_FINGERPRINT_ALGORITHM and type(manifest['fingerprint']['marshal_version']) is int and manifest['fingerprint']['marshal_version'] == 2, 'GENERATED_FINGERPRINT_BINDING_DIFFERS')
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
            require(row['kind'] == 'stdlib-dataclass-exact-native-code' and row['filename'] == '<string>' and row['producer_source_sha256'] == DATACLASSES_SHA256, 'EXACT_DATACLASS_RECORD_REQUIRED')
        slot = os.fstat(failure_fd)
        flags = fcntl.fcntl(failure_fd, fcntl.F_GETFL)
        require(flags & os.O_ACCMODE == os.O_RDWR and not flags & os.O_APPEND, 'READWRITE_NONAPPEND_FAILURE_SLOT_REQUIRED')
        require(stat.S_ISREG(slot.st_mode) and slot.st_uid == os.getuid() and slot.st_nlink == 1 and slot.st_size == FAILURE_BYTES and slot.st_blocks * 512 >= FAILURE_BYTES, 'PREALLOCATED_FAILURE_SLOT_REQUIRED')
        require(os.pread(failure_fd, FAILURE_BYTES, 0) == bytes(FAILURE_BYTES), 'FAILURE_SLOT_NOT_EMPTY')
        self.book, self.manifest, self.failure_fd = book, manifest, failure_fd
        self.manifest_sha256 = manifest_sha256
        self.phase, self.active, self.installing = 'BOOTSTRAP', False, False
        self.codes, self.seen, self.denied = {}, set(), False
        self.dataclass_source = pinned_dataclasses(manifest['dataclasses'])

    # Register only code objects compiled from an authenticated backend file.
    def register(self, path, code):
        require(path in self.book.pins and path.endswith('.py') and type(code) is CodeType and code.co_filename == self.book.root + '/' + path, 'AUTHENTICATED_COMPILED_SOURCE_REQUIRED')
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
        # Only exact declared dataclass records may describe dynamic backend code.
        if code.co_filename != '<string>':
            self.trip('UNREGISTERED_OR_GENERATED_CODE', str(module) + '.' + code.co_qualname)
        producer = self.dataclass_source
        kind = 'stdlib-dataclass-exact-native-code'
        generated = {'kind': kind, 'phase': self.phase, 'module': str(module), 'qualname': code.co_qualname, 'line': code.co_firstlineno, 'filename': code.co_filename, 'code_sha256': hashlib.sha256(marshal.dumps(code, 2)).hexdigest(), 'producer_source_sha256': producer}
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
class CapacityBackendFinderV1(importlib.abc.MetaPathFinder, importlib.abc.Loader):
    # Bind the distinct fully authenticated source book to its exact guard object.
    def __init__(self, book, fence):
        require(type(book) is CapacitySourceBookV1 and type(fence) is CapacityCallFenceV1 and fence.book is book and book.authenticated is True, 'EXACT_EXECUTOR_FINDER_BINDING_REQUIRED')
        self.book, self.fence, self.paths = book, fence, {}

    # Resolve only exact declared modules under the expected authenticated parent.
    def find_spec(self, fullname, path=None, target=None):
        if fullname != 'backend' and not fullname.startswith('backend.'):
            return None
        require(target is None and fullname not in self.paths, 'BACKEND_RELOAD_OR_PENDING_IMPORT')
        require(all(part.isidentifier() for part in fullname.split('.')), 'CANONICAL_BACKEND_MODULE_REQUIRED')
        expected_parent = self.book.root + '/' + fullname.rpartition('.')[0].replace('.', '/')
        require((fullname == 'backend' and path is None) or (fullname != 'backend' and type(path) is list and path == [expected_parent]), 'SHADOWED_BACKEND_PARENT')
        stem = fullname.replace('.', '/')
        choices = [name for name in (stem + '.py', stem + '/__init__.py') if name in self.book.pins]
        require(len(choices) == 1, 'EXACT_BACKEND_MODULE_REQUIRED')
        selected = choices[0]
        self.paths[fullname] = selected
        spec = importlib.util.spec_from_loader(fullname, self, origin=self.book.root + '/' + selected, is_package=selected.endswith('/__init__.py'))
        spec.has_location = True
        if selected.endswith('/__init__.py'):
            spec.submodule_search_locations = [self.book.root + '/' + stem]
        return spec

    # Use import machinery's new empty module without loading ambient bytecode.
    def create_module(self, spec):
        return None

    # Compile bounded authenticated source and register nested code before its body.
    def exec_module(self, module):
        require(sys.meta_path[0] is self and self.fence.active and sys.getprofile() == self.fence.profile, 'EXECUTOR_GUARD_NOT_INSTALLED')
        name = self.paths.pop(module.__name__)
        filename = self.book.root + '/' + name
        require(module.__spec__.loader is self and module.__loader__ is self and module.__spec__.origin == filename and module.__file__ == filename, 'EXECUTOR_MODULE_ORIGIN_DIFFERS')
        if name.endswith('/__init__.py'):
            require(module.__path__ == [filename.rsplit('/', 1)[0]], 'EXECUTOR_PACKAGE_PATH_DIFFERS')
        raw = self.book.read(name, limit=MAX_PYTHON_BYTES)
        code = compile(raw, filename, 'exec', dont_inherit=True, optimize=0)
        self.fence.register(name, code)
        self.book.assert_root()
        exec(code, module.__dict__)

    # Install first only after the audit/profile guard and before any backend import.
    def install(self):
        require(not any(name == 'backend' or name.startswith('backend.') for name in sys.modules), 'BACKEND_PRELOADED')
        require(self.fence.active and not self.fence.denied and sys.getprofile() == self.fence.profile and self not in sys.meta_path, 'EXECUTOR_GUARD_NOT_INSTALLED')
        self.book.assert_root()
        sys.meta_path.insert(0, self)


# Bind the exact observed stdlib producer without importing any application package.
def pinned_dataclasses(binding):
    expected = {'implementation': 'cpython', 'version': [3, 12, 14], 'cache_tag': 'cpython-312', 'path': '/usr/local/lib/python3.12/dataclasses.py', 'source_sha256': DATACLASSES_SHA256}
    require(type(binding) is dict and binding == expected, 'EXACT_DATACLASSES_BINDING_REQUIRED')
    require(sys.implementation.name == binding['implementation'] and list(sys.version_info[:3]) == binding['version'] and sys.implementation.cache_tag == binding['cache_tag'] and dataclasses.__file__ == binding['path'], 'DATACLASSES_RUNTIME_DIFFERS')
    path = PurePosixPath(binding['path'])
    parent = directory_fd(str(path.parent))
    descriptor = None
    try:
        descriptor = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=parent)
        before = os.fstat(descriptor)
        require(stat.S_ISREG(before.st_mode) and 0 < before.st_size <= MAX_PYTHON_BYTES, 'BOUNDED_DATACLASSES_SOURCE_REQUIRED')
        checksum, count = hashlib.sha256(), 0
        while block := os.read(descriptor, min(65536, MAX_PYTHON_BYTES + 1 - count)):
            count += len(block)
            require(count <= MAX_PYTHON_BYTES, 'DATACLASSES_SOURCE_GREW')
            checksum.update(block)
        require(physical(before) == physical(os.fstat(descriptor)) == physical(os.stat(path.name, dir_fd=parent, follow_symlinks=False)) and count == before.st_size, 'DATACLASSES_SOURCE_CHANGED')
        require(checksum.hexdigest() == DATACLASSES_SHA256, 'DATACLASSES_SOURCE_DIFFERS')
        return checksum.hexdigest()
    finally:
        if descriptor is not None:
            os.close(descriptor)
        os.close(parent)


# Refuse execution until separate selected-call, generated, native and runtime admission.
def execute(*args, **kwargs):
    raise RuntimeError('CAPACITY_EXECUTOR_RUNTIME_UNADMITTED')
