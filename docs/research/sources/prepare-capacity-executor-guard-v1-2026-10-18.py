"""Build inert guard source from pinned text; never import or compile payload code."""

import ast
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
RESEARCH = ROOT / 'docs/research'
SOURCES = RESEARCH / 'sources'
OLD = SOURCES / 'original-loader-capacity-harness-v3-2026-10-18.py'
DEST = SOURCES / 'capacity-executor-source-guard-v1-2026-10-18.py'
OLD_SHA = '030cb5bb25f89c2785e6acbd55aceff5c99b632a5eb538079ee027362ae6178a'
CONTRACT_SHA = 'c2a720543b3f2dda0d824e61b6d15f5ee7f7fa47669dad8891d33ff584971b63'
MAP_SHA = '544fe1859ec11e62f2bf506eff70e9111a6a930d53dff59450d9d4816abaa202'


# Replace exactly one declared source fragment, refusing silent generator drift.
def replace_once(text, old, new):
    assert text.count(old) == 1, old[:100]
    return text.replace(old, new, 1)


# Preserve original source text up to the finder, with explicit constructor deltas.
def build():
    old_raw = OLD.read_bytes()
    assert hashlib.sha256(old_raw).hexdigest() == OLD_SHA
    contract = (RESEARCH / 'original-loader-data-closure-contract-v1-2026-10-18.json').read_bytes()
    assert hashlib.sha256(contract).hexdigest() == CONTRACT_SHA
    map_raw = (RESEARCH / 'original-loader-data-composition-source-map-v1-2026-10-18.json').read_bytes()
    assert hashlib.sha256(map_raw).hexdigest() == MAP_SHA
    pins = json.loads(map_raw)['files']
    assert len(pins) == 2468
    recipe = hashlib.sha256(json.dumps(pins, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    prior_raw = (RESEARCH / 'original-loader-stopped-package-source-independent-v1-2026-10-18.json').read_bytes()
    assert hashlib.sha256(prior_raw).hexdigest() == '6860a76c8a50e4891549ea656ed881cf81518ae1e7d28b02ba65bd32d045c08b'
    prior = json.loads(prior_raw)
    dataclass_sha = prior['source_inventory']['source-00.py.txt']['sha256']
    text = old_raw.decode().split('# Check the independently pinned runtime before importing the numerical audit CLI.')[0].rstrip() + '\n'
    start = text.index('import dataclasses\n')
    text = '''"""SOURCE ONLY: distinct 2468 executor source book, finder and guard proposal.

Every payload body is UNRUN. No tree, call/generated/native manifest, bootstrap,
runtime or admission is supplied. This is not the tested old2446 guard identity.
Selected global/type/dataclass-class-flag/native provenance remains external and
UNRESOLVED; these source checks alone do not establish executable closure.
The guards constrain mistakes in trusted code, not hostile native extensions.
"""

''' + text[start:]
    for line in ('import resource\n', 'import socket\n', 'import time\n', 'from datetime import UTC, datetime\n'):
        text = replace_once(text, line, '')
    text = replace_once(text, "CONTRACT_SHA256 = 'ecc58ad7f6ec65bb42a28ef0c2bea8d116b0e9be5ea59e490388fa0e74dfddc8'", "CONTRACT_SHA256 = '" + CONTRACT_SHA + "'")
    text = replace_once(text, "RECIPE_SHA256 = '503e8d508ebe5fdc82a17c11974ccce5366c60ce8e78fc549c129fc6c6d81e03'", "RECIPE_SHA256 = '" + recipe + "'\nEXECUTOR_MAP_SHA256 = '" + MAP_SHA + "'\nDATACLASSES_SHA256 = '" + dataclass_sha + "'")
    text = replace_once(text, 'class SourceBook:', 'class CapacitySourceBookV1:')
    text = replace_once(text, 'class CallFence:', 'class CapacityCallFenceV1:')
    text = replace_once(text, 'class PinnedBackendFinder(', 'class CapacityBackendFinderV1(')
    old_constructor = text[text.index('    # Bind the exact composed recipe'):text.index('    # Read one exact bounded source')]
    text = replace_once(text, old_constructor, '''    # Bind the distinct complete map and externally authenticated physical root.
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

''')
    text = replace_once(text, "        path = PurePosixPath(name)\n", "        require(type(limit) is int and 0 <= limit <= MAX_METADATA_BYTES, 'UNCHANGED_SOURCE_BOUND_REQUIRED')\n        self.assert_root()\n        path = PurePosixPath(name)\n")
    text = replace_once(text, "            self.bookends[name] = identity\n            return b''.join(chunks)", "            self.bookends[name] = identity\n            self.assert_root()\n            return b''.join(chunks)")
    text = replace_once(text, '            self.read(name)\n        self.authenticated = True', "            self.read(name, limit=MAX_PYTHON_BYTES if name.endswith('.py') else MAX_METADATA_BYTES)\n        self.assert_root()\n        self.authenticated = True")
    text = replace_once(text, '    def __init__(self, book, manifest_raw, manifest_sha256, failure_fd):', "    def __init__(self, book, manifest_raw, manifest_sha256, failure_fd):\n        require(type(book) is CapacitySourceBookV1 and book.authenticated is True, 'FULL_EXECUTOR_BOOK_REQUIRED')\n        book.assert_root()")
    text = replace_once(text, "{'schema', 'recipe_sha256', 'contract_sha256', 'fingerprint', 'calls', 'generated'}", "{'schema', 'recipe_sha256', 'executor_map_sha256', 'root_identity', 'contract_sha256', 'dataclasses', 'fingerprint', 'calls', 'generated'}")
    text = replace_once(text, "manifest['schema'] == 'n2-capacity-call-manifest/2'", "manifest['schema'] == 'capacity-executor-call-manifest/1' and manifest['executor_map_sha256'] == EXECUTOR_MAP_SHA256 and manifest['root_identity'] == book.root_identity")
    text = replace_once(text, "            if row['kind'] == 'stdlib-dataclass-exact-native-code':\n                require(row['filename'] == '<string>', 'EXACT_DATACLASS_FILENAME_REQUIRED')\n            else:\n                require(row['kind'] == 'exact-original-daily-prefix-transformation-40d0d7cf' and row['filename'] == '<pinned daily prefix>' and row['module'] == 'backend.cli.market_strategy_continue' and row['qualname'] in ('<module>', 'inputs') and row['phase'] == 'LOAD', 'EXACT_DAILY_PREFIX_RECORD_REQUIRED')", "            require(row['kind'] == 'stdlib-dataclass-exact-native-code' and row['filename'] == '<string>' and row['producer_source_sha256'] == DATACLASSES_SHA256, 'EXACT_DATACLASS_RECORD_REQUIRED')")
    text = replace_once(text, "        self.dataclass_source = hashlib.sha256(Path(dataclasses.__file__).read_bytes()).hexdigest()", "        self.dataclass_source = pinned_dataclasses(manifest['dataclasses'])")
    text = replace_once(text, "        pending, count = [code], 0", "        require(path in self.book.pins and path.endswith('.py') and type(code) is CodeType and code.co_filename == self.book.root + '/' + path, 'AUTHENTICATED_COMPILED_SOURCE_REQUIRED')\n        pending, count = [code], 0")
    dynamic_start = text.index('        # These two producer paths')
    dynamic_end = text.index("        generated = {'kind': kind", dynamic_start)
    text = text[:dynamic_start] + '''        # Only exact declared dataclass records may describe dynamic backend code.
        if code.co_filename != '<string>':
            self.trip('UNREGISTERED_OR_GENERATED_CODE', str(module) + '.' + code.co_qualname)
        producer = self.dataclass_source
        kind = 'stdlib-dataclass-exact-native-code'
''' + text[dynamic_end:]
    finder_constructor = text.index('    # Share the held source book')
    text = text[:finder_constructor] + '''    # Bind the distinct fully authenticated source book to its exact guard object.
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
'''
    text = replace_once(text, 'from pathlib import Path, PurePosixPath', 'from pathlib import PurePosixPath')
    ast.parse(text, filename=str(DEST))
    assert '<pinned daily prefix>' not in text and '40d0d7cf' not in text
    with DEST.open('xb') as target:
        target.write(text.encode())
    print(json.dumps({'path': str(DEST), 'bytes': len(text.encode()), 'sha256': hashlib.sha256(text.encode()).hexdigest(), 'recipe_sha256': recipe, 'payload_bodies': 'UNRUN'}))


if __name__ == '__main__':
    build()
