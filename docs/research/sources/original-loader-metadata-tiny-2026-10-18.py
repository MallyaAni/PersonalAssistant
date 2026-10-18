"""SOURCE ONLY: two fresh synthetic metadata children; no genuine loader or account."""
import ast
import dataclasses
import gzip
import hashlib
import importlib.util
import io
import json
import os
import resource
import signal
import subprocess
import sys
import types
from pathlib import Path

SELF = Path(__file__)
AUDIT = Path('/audit')
FIXTURE = AUDIT / 'fixture'
OUT = Path('/out')
HELPER = 'd413e748bf2b1eb63f4d267371f22cf6431f6ae650368676c815b07779723135'
HARNESS = '030cb5bb25f89c2785e6acbd55aceff5c99b632a5eb538079ee027362ae6178a'
CHILDREN = []

# Name exact complete source or observation bytes.
def sha(raw):
    return hashlib.sha256(raw).hexdigest()

# Persist one bounded new finite observation without overwriting evidence.
def save(path, value):
    raw = json.dumps(value, sort_keys=True, indent=2, allow_nan=False).encode() + b'\n'
    assert len(raw) <= 262144
    with path.open('xb') as output:
        output.write(raw); output.flush(); os.fsync(output.fileno())
    assert path.read_bytes() == raw

# Import only the exact stdlib research helper, never a backend application module.
def module(name, path, expected):
    raw = path.read_bytes()
    assert len(raw) <= 262144 and sha(raw) == expected
    value = types.ModuleType(name)
    value.__file__ = str(path)
    exec(compile(raw, str(path), 'exec', dont_inherit=True), value.__dict__)
    return value

# Refuse any accidental application or numerical import in either fresh child.
def no_application():
    assert not any(name == 'backend' or name.startswith(('backend.', 'numpy', 'scipy', 'sklearn')) for name in sys.modules)

# Retain first-boundary expected exceptions without weakening a failed assertion.
def refusal(rows, name, action, reason):
    try:
        action()
    except RuntimeError as error:
        assert str(error) == reason, (name, type(error).__name__, str(error))
        rows.append({'case': name, 'status': 'EXPECTED_REFUSAL', 'reason': reason})
    else:
        raise AssertionError('EXPECTED_REFUSAL_ABSENT:' + name)

# Bind the actual partial SourceBook reader; this is not full2446 authentication.
def partial_identity(helper, harness, book, fullpins, native, reader=None):
    if type(book) is not harness.SourceBook or book.root != str(FIXTURE) or book.pins != fullpins or book.authenticated is not False or 'read' in vars(book):
        raise RuntimeError('ACTUAL_PARTIAL_SOURCEBOOK_BINDING_REQUIRED')
    bound = book.read if reader is None else reader
    if type(bound) is not types.MethodType or bound.__self__ is not book or bound.__func__ is not harness.SourceBook.read:
        raise RuntimeError('ACTUAL_PARTIAL_SOURCEBOOK_BINDING_REQUIRED')
    if type(book.fd) is not int or book.fd < 0 or set(vars(book)) != {'root', 'fd', 'pins', 'bookends', 'authenticated'}:
        raise RuntimeError('ACTUAL_PARTIAL_SOURCEBOOK_BINDING_REQUIRED')
    root_identity = os.fstat(book.fd)
    named = FIXTURE.stat(follow_symlinks=False)
    if (root_identity.st_dev, root_identity.st_ino, root_identity.st_mode) != (named.st_dev, named.st_ino, named.st_mode):
        raise RuntimeError('ACTUAL_PARTIAL_SOURCEBOOK_BINDING_REQUIRED')
    before = (book.root, book.fd, dict(book.pins), book.authenticated, root_identity.st_dev, root_identity.st_ino)
    observed = helper.native_source_identity(native, bound)
    after_fd = os.fstat(book.fd)
    assert before == (book.root, book.fd, book.pins, book.authenticated, after_fd.st_dev, after_fd.st_ino)
    assert 'read' not in vars(book) and book.read.__func__ is harness.SourceBook.read
    return observed

# Compare exact declarations in a separately labelled synthetic reference namespace.
def reference(destination):
    no_application()
    raw = (FIXTURE / 'backend/agents/trading/desk/paper.py').read_bytes()
    assert sha(raw) == 'e2eef2f0270497d9a5944212d6581b7ebf503d2675687a172e76690fcc7bc3c3'
    tree = ast.parse(raw)
    state = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == 'PaperState')
    kind = next(node.value.value for node in tree.body if isinstance(node, ast.Assign) and any(isinstance(item, ast.Name) and item.id == 'PAPER_KIND' for item in node.targets))
    name = 'synthetic_paper_declaration_reference'
    value = types.ModuleType(name)
    value.__dict__.update(dataclass=dataclasses.dataclass, field=dataclasses.field)
    sys.modules[name] = value
    try:
        exec(compile(ast.Module(body=[state], type_ignores=[]), '<synthetic declaration reference>', 'exec', dont_inherit=True), value.__dict__)
        fields = [item.name for item in dataclasses.fields(value.PaperState)]
        compiled = compile(raw, '<inert full original paper source>', 'exec', dont_inherit=True)
        code = next(item for item in compiled.co_consts if isinstance(item, types.CodeType) and item.co_name == 'state_path')
        function = types.FunctionType(code, {'Path': Path, 'PAPER_KIND': kind})
        paths = [str(function(Path(root))) for root in ('/synthetic/no-account', 'relative-reference')]
    finally:
        del sys.modules[name]
    no_application()
    save(destination / 'result.json', {'scope': 'ISOLATED_SYNTHETIC_DECLARATION_REFERENCE', 'fields': fields, 'paths': paths, 'paper_instance_created': False, 'full_original_module_imported': False})

# Exercise unchanged helper bodies and a real constructor/read on31 retained source files.
def candidate(destination):
    no_application()
    helper = module('metadata_candidate', AUDIT / 'helper.py', HELPER)
    harness = module('sourcebook_library', AUDIT / 'harness.py', HARNESS)
    compressed = (AUDIT / 'full-map.json.gz').read_bytes()
    assert len(compressed) <= 262144
    with gzip.GzipFile(fileobj=io.BytesIO(compressed)) as stream:
        raw_map = stream.read(279396)
        assert len(raw_map) == 279395 and stream.read(1) == b''
    assert len(raw_map) == 279395 and sha(raw_map) == '9a0bfbeb59e0a63072453a6ac0e930e65a89684efd90bc705febf9b1bdbe6224'
    fullpins = json.loads(raw_map)
    native = json.loads((AUDIT / 'native31.json').read_bytes())
    raw = (FIXTURE / 'backend/agents/trading/desk/paper.py').read_bytes()
    descriptor = helper.paper_descriptor(raw)
    fields, paths = descriptor['physical_state_fields'], [str(helper.physical_state_path(Path(root), descriptor)) for root in ('/synthetic/no-account', 'relative-reference')]
    book = harness.SourceBook(str(FIXTURE), fullpins)
    rows = []
    try:
        identity = partial_identity(helper, harness, book, fullpins, native)
        assert identity == native and len(book.bookends) == 31 and book.authenticated is False
        before = dict(book.bookends)
        assert partial_identity(helper, harness, book, fullpins, native) == native and book.bookends == before
        rows.append({'case': 'real-partial31-reader-twice', 'status': 'PASS', 'read_sources': 31, 'full2446_authenticated': False})
        refusal(rows, 'paper-byte', lambda: helper.paper_descriptor(raw + b' '), 'EXACT_N2_PAPER_SOURCE_REQUIRED')
        refusal(rows, 'CURRENT-paper', lambda: helper.paper_descriptor((AUDIT / 'current-paper-source.txt').read_bytes()), 'EXACT_N2_PAPER_SOURCE_REQUIRED')
        refusal(rows, 'paper-type', lambda: helper.paper_descriptor(bytearray(raw)), 'EXACT_BOUNDED_PAPER_BYTES_REQUIRED')
        refusal(rows, 'paper-bound', lambda: helper.paper_descriptor(bytes(1024**2 + 1)), 'EXACT_BOUNDED_PAPER_BYTES_REQUIRED')
        for key, value in (('schema', 'original-n2-paper-layout/0'), ('source_sha256', '0'*64), ('PaperState_ast_sha256', '0'*64), ('state_path_ast_sha256', '0'*64), ('physical_state_fields', fields[:-1]), ('relative_state_components', ['other', 'state.json'])):
            changed = {**descriptor, key: value}
            refusal(rows, 'descriptor-' + key, lambda changed=changed: helper.physical_state_path('/synthetic/no-account', changed), 'EXACT_SOURCE_BOUND_LAYOUT_REQUIRED')
        refusal(rows, 'descriptor-type', lambda: helper.physical_state_path('/synthetic/no-account', []), 'EXACT_SOURCE_BOUND_LAYOUT_REQUIRED')
        first = sorted(native)[0]
        wrongpin = {**native, first: '0'*64}
        refusal(rows, 'wrong31-pin', lambda: helper.native_source_identity(wrongpin, book.read), 'EXACT_N2_NATIVE31_MAP_REQUIRED')
        refusal(rows, 'missing31', lambda: helper.native_source_identity({key: value for key, value in native.items() if key != first}, book.read), 'EXACT_N2_SOURCE_READER_REQUIRED')
        refusal(rows, 'reader-type', lambda: helper.native_source_identity(native, None), 'EXACT_N2_SOURCE_READER_REQUIRED')
        refusal(rows, 'adapter-fake-book', lambda: partial_identity(helper, harness, object(), fullpins, native), 'ACTUAL_PARTIAL_SOURCEBOOK_BINDING_REQUIRED')
        refusal(rows, 'adapter-lambda', lambda: partial_identity(helper, harness, book, fullpins, native, lambda name: book.read(name)), 'ACTUAL_PARTIAL_SOURCEBOOK_BINDING_REQUIRED')
        original_root, original_pins, original_fd = book.root, book.pins, book.fd
        try:
            book.root = str(destination)
            refusal(rows, 'adapter-wrong-root', lambda: partial_identity(helper, harness, book, fullpins, native), 'ACTUAL_PARTIAL_SOURCEBOOK_BINDING_REQUIRED')
            book.root = original_root
            book.pins = native
            refusal(rows, 'adapter-wrong-pins', lambda: partial_identity(helper, harness, book, fullpins, native), 'ACTUAL_PARTIAL_SOURCEBOOK_BINDING_REQUIRED')
            book.pins = original_pins
            wrong_fd = os.open(destination, os.O_RDONLY | os.O_DIRECTORY)
            try:
                book.fd = wrong_fd
                refusal(rows, 'adapter-wrong-root-fd', lambda: partial_identity(helper, harness, book, fullpins, native), 'ACTUAL_PARTIAL_SOURCEBOOK_BINDING_REQUIRED')
            finally:
                book.fd = original_fd
                os.close(wrong_fd)
            book.read = lambda name: b''
            refusal(rows, 'adapter-instance-read', lambda: partial_identity(helper, harness, book, fullpins, native), 'ACTUAL_PARTIAL_SOURCEBOOK_BINDING_REQUIRED')
        finally:
            book.root, book.pins, book.fd = original_root, original_pins, original_fd
            vars(book).pop('read', None)
        # These are explicitly injected unit-refusal callbacks, never positive reader acceptance.
        refusal(rows, 'unit-wrong-bytes', lambda: helper.native_source_identity(native, lambda name: book.read(name) + b' '), 'N2_SOURCE_BYTES_DIFFER')
        refusal(rows, 'unit-wrong-byte-type', lambda: helper.native_source_identity(native, lambda name: bytearray(book.read(name))), 'BOUNDED_AUTHENTICATED_SOURCE_BYTES_REQUIRED')
        no_application()
        assert book.bookends == before and not book.authenticated
        save(destination / 'result.json', {'scope': 'SYNTHETIC_METADATA_ACTUAL_HELPER_PARTIAL_SOURCEBOOK_NOT_GENUINE_ADMISSION', 'fields': fields, 'paths': paths, 'cases': rows, 'native31': identity, 'source_bookends_before': before, 'source_bookends_after': book.bookends, 'complete2446_source_admission': False, 'callback_refusal_cases_explicitly_injected': True, 'helper_sha256': HELPER, 'harness_sha256': HARNESS})
    finally:
        book.close()

# Bound child CPU and each log or evidence file independently.
def limits():
    resource.setrlimit(resource.RLIMIT_CPU, (10, 10))
    resource.setrlimit(resource.RLIMIT_FSIZE, (262144, 262144))

# Raise a real deadline interruption while retaining owned-child cleanup.
def alarm(signum, frame):
    raise KeyboardInterrupt('METADATA_TINY_PARENT_DEADLINE')

# Run exactly two fresh children and retain their exits and comparison.
def diagnose():
    assert os.getuid() == 1000 and list(OUT.iterdir()) == []
    no_application()
    signal.signal(signal.SIGALRM, alarm)
    signal.setitimer(signal.ITIMER_REAL, 45)
    try:
        for mode in ('reference', 'candidate'):
            target = OUT / mode
            target.mkdir(mode=0o700)
            stdout, stderr = (target/'stdout.log').open('xb'), (target/'stderr.log').open('xb')
            process, stopped = None, None
            try:
                prior = signal.pthread_sigmask(signal.SIG_BLOCK, {signal.SIGALRM})
                try:
                    process = subprocess.Popen([sys.executable, '-I', '-S', '-B', str(SELF), mode, str(target)], stdin=subprocess.DEVNULL, stdout=stdout, stderr=stderr, preexec_fn=limits)
                    CHILDREN.append(process)
                finally:
                    signal.pthread_sigmask(signal.SIG_SETMASK, prior)
                process.wait(timeout=15)
            finally:
                if process is not None and process.poll() is None:
                    stopped = 'TERM'; process.terminate()
                    try:
                        process.wait(timeout=1)
                    except subprocess.TimeoutExpired:
                        stopped = 'KILL'; process.kill(); process.wait(timeout=1)
                for output in (stdout, stderr):
                    output.flush(); os.fsync(output.fileno()); output.close()
                save(target/'exit.json', {'pid': None if process is None else str(process.pid), 'exit': None if process is None else process.returncode, 'owned_stop': stopped})
            assert process.returncode == 0 and stopped is None
            assert (target/'stdout.log').read_bytes() == (target/'stderr.log').read_bytes() == b''
        reference_value = json.loads((OUT/'reference/result.json').read_bytes())
        candidate_value = json.loads((OUT/'candidate/result.json').read_bytes())
        assert reference_value['fields'] == candidate_value['fields'] and len(candidate_value['fields']) == 17
        assert reference_value['paths'] == candidate_value['paths']
        save(OUT/'comparison.json', {'status': 'METADATA_TINY_CANDIDATE_REQUIRES_INDEPENDENT_REVIEW', 'children': 2, 'cases': len(candidate_value['cases']), 'fields': 17, 'paths_equal': True, 'native_sources': 31, 'genuine_source_admission': False, 'model_or_account': False})
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        for process in CHILDREN:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=1)
                except subprocess.TimeoutExpired:
                    process.kill(); process.wait(timeout=1)

if __name__ == '__main__':
    if len(sys.argv) == 2 and sys.argv[1] == 'diagnose':
        diagnose()
    elif len(sys.argv) == 3 and sys.argv[1] in ('reference', 'candidate'):
        {'reference': reference, 'candidate': candidate}[sys.argv[1]](Path(sys.argv[2]))
    else:
        raise SystemExit('SOURCE_ONLY_NO_METADATA_TINY_INVOCATION')
