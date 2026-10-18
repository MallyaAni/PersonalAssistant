"""UNRUN 44 reader/context/preservation controls on distinct tiny SYNTHETIC files."""
import ast
import copy
import dataclasses
import hashlib
import json
import os
from pathlib import Path
from types import MappingProxyType

from fixtures import AUDIT, Fixture, encoded, outcome, reference, sha, source_copy, write


# Prove actual new reader content binding without claiming original source-root authority.
def readers(env, target, rows):
    cls = env.context.CapacitySourceReaderV1
    pins = source_copy(target / 'source')
    root = target / 'source'
    reader = cls(root, pins)
    descriptor = reader.paper_descriptor()
    outcome(rows, 'reader-exact31-and-paper-descriptor', lambda: (
        reader.authenticate_native() == pins and descriptor['physical_state_fields'] == list(env.metadata.FIELDS)))
    other = target / 'identical-copy'
    source_copy(other)
    outcome(rows, 'reader-identical-copy-content-equivalent', lambda: cls(other, pins).authenticate_native() == pins)
    for case, value, refusal in (
        ('reader-map-type-refusal', MappingProxyType(pins), ('ValueError', 'EXACT_NATIVE_SOURCE_DICT_REQUIRED')),
        ('reader-map-count-refusal', dict(list(pins.items())[:-1]), ('RuntimeError', 'EXACT_N2_SOURCE_READER_REQUIRED')),
        ('reader-map-hash-refusal', {**pins, next(iter(pins)): '0' * 64}, ('RuntimeError', 'EXACT_N2_NATIVE31_MAP_REQUIRED'))):
        outcome(rows, case, lambda value=value: cls(root, value), refusal=refusal)
    name = next(iter(pins))
    path = root / name
    original = path.read_bytes()
    path.unlink()
    outcome(rows, 'reader-missing-source-refusal', lambda: cls(root, pins), refusal=('FileNotFoundError', None))
    write(path, original + b'\n')
    outcome(rows, 'reader-changed-source-refusal', lambda: cls(root, pins), refusal=('ValueError', 'Pinned stream input bytes differ'))
    for case, name, reason in (
        ('reader-absolute-path-refusal', '/backend/x.py', 'CANONICAL_RELATIVE_NATIVE_SOURCE_REQUIRED'),
        ('reader-traversal-path-refusal', '../x.py', 'CANONICAL_RELATIVE_NATIVE_SOURCE_REQUIRED'),
        ('reader-noncanonical-path-refusal', 'backend//x.py', 'CANONICAL_RELATIVE_NATIVE_SOURCE_REQUIRED'),
        ('reader-nonmember-refusal', 'backend/x.py', 'NATIVE_SOURCE_MEMBER_REQUIRED')):
        outcome(rows, case, lambda name=name: reader.read(name), refusal=('ValueError', reason))
    # Subclass construction must refuse before exposing a reader with a different identity.
    class DifferentReader(cls):
        pass
    outcome(rows, 'reader-subclass-refusal', lambda: DifferentReader(other, pins), refusal=('ValueError', 'EXACT_CAPACITY_SOURCE_READER_REQUIRED'))
    outcome(rows, 'reader-recheck-changed-bytes-refusal', reader.authenticate_native,
        refusal=('ValueError', 'Pinned stream input bytes differ'))


# Compare constructor results using semantic controls while keeping path and class identities explicit.
def projection(archives, env):
    inputs = archives.completion['input_sha256']
    if type(inputs) is env.streamed.ShaMap:
        pairs = list(inputs.items())
        assert copy.deepcopy(inputs) is inputs
        inputs.verify()
        assert inputs.canonical_sha256 == sha(json.dumps(dict(pairs), sort_keys=True).encode())
        assert inputs.index.is_file() and inputs.spool.is_file()
    else:
        pairs = list(inputs.items())
    assert archives.completion_raw is None
    return {'ending': archives.ending_state, 'status': archives.completion['status'],
        'input_values': sorted(value for _, value in pairs), 'sessions': list(archives.completion['sessions']),
        'initial': archives.initial(), 'readonly': type(archives.completion) is not dict}


# Compare the actual new constructor against the isolated original class on separate files.
def constructors(env, target, rows, ref):
    for case, external in (('constructor-external-ShaMap-retained', True), ('constructor-plain-input-map-mode', False)):
        left = Fixture(env, target / (case + '-candidate'), external=external)
        right = Fixture(env, target / (case + '-reference'), external=external)
        candidate, original = left.candidate(), right.original(ref)
        assert (type(candidate.completion['input_sha256']) is env.streamed.ShaMap) is external
        outcome(rows, case, lambda: projection(candidate, env), reference=lambda: projection(original, env),
            scope='ISOLATED_SYNTHETIC_CONSTRUCTOR_PARITY_DECLARED_CLASS_AND_ROOT_DIFFERENCES')
    fixture = Fixture(env, target / 'ending-release')
    value = fixture.candidate()
    # Read the same authenticated completion independently to inspect actual ordered Rows provenance.
    inspect = target / 'ending-inspection'
    inspect.mkdir()
    parsed = env.streamed.read(fixture.root / 'completion.json', fixture.completion_sha, directory=inspect)
    history = parsed['paper_state']['history']
    assert type(history) is env.streamed.Rows and len(history) == 3
    assert list(history) == fixture.ending['history'] and all(row.path.is_file() and sha(row.raw()) == row.sha256 for row in history.entries)
    expected = env.adapt.logical_digest(parsed['paper_state'])
    env.streamed.release(parsed)
    assert not any(inspect.iterdir())
    outcome(rows, 'constructor-ending-Rows-digest-and-release', lambda: value.ending_state == expected and
        {p.name for p in fixture.scratch.iterdir()} == {value.completion['input_sha256'].index.name, value.completion['input_sha256'].spool.name})
    # Ordinary mutation refusal and deepcopy identity concern readonly controls and sealed map, not the new class.
    def immutable():
        for action in (lambda: value.completion.__setitem__('x', 1), lambda: value.completion['sessions'].append({})):
            try:
                action()
            except TypeError as caught:
                assert str(caught) == 'Admitted original metadata is readonly'
            else:
                raise AssertionError('MUTABLE_COMPLETION')
        assert copy.deepcopy(value.completion) is value.completion
        assert copy.deepcopy(value.completion['input_sha256']) is value.completion['input_sha256']
        assert type(value.consumed_inputs) is MappingProxyType
        return True
    outcome(rows, 'constructor-readonly-and-deepcopy', immutable)
    outcome(rows, 'constructor-explicit-root-scratch-identity', lambda: value.root == fixture.root and value.source_root == fixture.source and value.scratch == fixture.scratch and value.source_reader is fixture.reader)
    outcome(rows, 'constructor-scratch-collision-refusal', fixture.candidate, refusal=('FileExistsError', None))
    bad = Fixture(env, target / 'reader-type')
    outcome(rows, 'constructor-reader-type-refusal', lambda: bad.candidate(source_reader=object()), refusal=('ValueError', 'EXACT_CAPACITY_SOURCE_READER_REQUIRED'))
    outcome(rows, 'constructor-bool-mode-refusal', lambda: bad.candidate(external_inputs=1), refusal=('ValueError', 'EXACT_EXTERNAL_INPUT_MODE_REQUIRED'))
    # Keep pre-extraction failures and their scratch visible rather than claiming constructor cleanup.
    status = Fixture(env, target / 'bad-status', completion_change=lambda v: v.update(status='SYNTHETIC_BAD_STATUS'))
    outcome(rows, 'constructor-status-refusal-retains-scratch', status.candidate,
        refusal=('ValueError', 'Genuine completed original account required'))
    assert status.scratch.is_dir() and any(status.scratch.iterdir())
    missing = Fixture(env, target / 'missing-ending', completion_change=lambda v: v.pop('paper_state'))
    outcome(rows, 'constructor-missing-ending-retains-scratch', missing.candidate, refusal=('KeyError', "'paper_state'"))
    assert missing.scratch.is_dir() and any(missing.scratch.iterdir())
    malformed = Fixture(env, target / 'malformed')
    (malformed.root / 'completion.json').unlink()
    malformed.completion_sha = write(malformed.root / 'completion.json', b'{')
    outcome(rows, 'constructor-malformed-completion-refusal', malformed.candidate, refusal=('ValueError', None))


# Check input bookkeeping and selectors on actual tiny parser outputs without source/input confusion.
def inputs_and_sources(env, target, rows):
    fixture = Fixture(env, target / 'inputs')
    archives = fixture.candidate()
    outcome(rows, 'inputs-capture-selection-and-unused-count', lambda: archives.authenticate_inputs(fixture.market) ==
        {'files': {'quotes.json': sha((fixture.market / 'quotes.json').read_bytes())}, 'source_sha256': {}}
        and archives.unused_inputs == 1 and set(archives.consumed_inputs) == {str(fixture.market / 'capture.json'), str(fixture.market / 'quotes.json')})
    relative = Fixture(env, target / 'relative')
    capture = relative.market / 'capture.json'
    capture.unlink()
    capture_sha = write(capture, encoded({'files': {'../escape': 'a' * 64}}))
    completion = json.loads((relative.root / 'completion.json').read_bytes())
    completion['capture_sha256'] = capture_sha
    (relative.root / 'completion.json').unlink()
    relative.completion_sha = write(relative.root / 'completion.json', encoded(completion))
    outcome(rows, 'inputs-relative-capture-path-refusal', lambda: relative.candidate().authenticate_inputs(relative.market), refusal=('ValueError', 'Relative original capture path required'))
    with (fixture.market / 'quotes.json').open('ab') as output:
        output.write(b' ')
    outcome(rows, 'inputs-changed-consumed-file-refusal', lambda: archives.authenticate_inputs(fixture.market), refusal=('ValueError', 'Pinned stream input bytes differ'))
    for kind in ('index', 'spool'):
        broken = Fixture(env, target / ('tamper-' + kind))
        candidate = broken.candidate()
        path = getattr(candidate.completion['input_sha256'], kind)
        with path.open('ab') as output:
            output.write(b'x')
        outcome(rows, 'unchanged-ShaMap-' + kind + '-tamper-refusal', candidate.unchanged,
            refusal=('ValueError', 'SHA map ' + kind + ' changed'))
    selector = Fixture(env, target / 'selector')
    candidate = selector.candidate()
    with (selector.root / 'initial.json.gz').open('ab') as output:
        output.write(b'x')
    outcome(rows, 'unchanged-original-selector-tamper-refusal', candidate.unchanged,
        refusal=('ValueError', 'Pinned stream input bytes differ'))
    chain = Fixture(env, target / 'chain')
    candidate = chain.candidate()
    outcome(rows, 'source-chain-three-catalog-two-transition', lambda: candidate.authenticate_sources() is None)
    third = chain.source / env.context.CATALOG_PATHS[2]
    with third.open('ab') as output:
        output.write(b' ')
    outcome(rows, 'source-chain-changed-third-catalog-refusal', candidate.authenticate_sources,
        refusal=('ValueError', 'Pinned stream input bytes differ'))
    legacy = Fixture(env, target / 'legacy')
    candidate = legacy.candidate()
    # Exercise all six physical checks, then the distinct five-entry producer manifest boundary.
    def legacy_and_producer():
        for name in env.context.SOURCE_PATHS:
            path = legacy.source / name
            raw = path.read_bytes()
            path.write_bytes(raw + b' ')
            try:
                candidate.authenticate_sources()
            except ValueError:
                pass
            else:
                raise AssertionError('LEGACY_BYTE_CHANGE_ACCEPTED')
            path.write_bytes(raw)
        changed = dict(candidate.sources)
        changed[next(iter(env.context.ORIGINAL_SOURCES))] = '0' * 64
        object.__setattr__(candidate, 'sources', env.evidence._freeze(changed))
        candidate.authenticate_sources()
    outcome(rows, 'source-chain-legacy6-and-producer5-refusal', legacy_and_producer,
        refusal=('ValueError', 'Exact original legacy producer profile required'))


# Exercise exact physical schema and hash preservation on tiny synthetic archives only.
def preservation(env, target, rows):
    fixture = Fixture(env, target / 'all')
    archives = fixture.candidate()
    expected = {str(fixture.root / 'sessions' / (r['session'] + '.json.gz')): r['sha256'] for r in archives.completion['sessions']}
    expected[str(fixture.physical)] = fixture.physical_sha
    outcome(rows, 'preservation-all-session-and-physical-hashes', lambda: env.context.preserved_archives(archives, fixture.physical_sha, fixture.physical_size), reference=lambda: expected,
        scope='SYNTHETIC_RAW_HASH_PRESERVATION_NOT_GENUINE_ORIGINAL_ARCHIVES')
    tree = ast.parse((fixture.source / 'backend/agents/trading/desk/paper.py').read_bytes())
    fields = [n.target.id for c in tree.body if isinstance(c, ast.ClassDef) and c.name == 'PaperState' for n in c.body if isinstance(n, ast.AnnAssign)]
    outcome(rows, 'preservation-source-bound17fields-and-path', lambda: fixture.reader.paper_descriptor()['physical_state_fields'] == fields and len(fields) == 17 and
        env.metadata.physical_state_path(fixture.root / 'state', fixture.reader.paper_descriptor()) == fixture.physical)
    nonfinite = Fixture(env, target / 'physical-nonfinite', nonfinite=True)
    candidate = nonfinite.candidate()
    outcome(rows, 'preservation-original-physical-nonfinite-logical-domain', lambda: env.context.preserved_archives(candidate, nonfinite.physical_sha, nonfinite.physical_size)[str(nonfinite.physical)] == nonfinite.physical_sha,
        scope='EXISTING_EXPLICIT_PHYSICAL_TRUE_LOGICAL_COMPARISON_ONLY')
    outcome(rows, 'preservation-physical-size-refusal', lambda: env.context.preserved_archives(archives, fixture.physical_sha, fixture.physical_size + 1), refusal=('ValueError', 'EXTERNAL_PHYSICAL_SIZE_DIFFERS'))
    outcome(rows, 'preservation-physical-SHA-refusal', lambda: env.context.preserved_archives(archives, '0' * 64, fixture.physical_size), refusal=('ValueError', None))
    session = fixture.root / 'sessions/2019-03-01.json.gz'
    with session.open('ab') as output:
        output.write(b'x')
    outcome(rows, 'preservation-session-SHA-refusal', lambda: env.context.preserved_archives(archives, fixture.physical_sha, fixture.physical_size), refusal=('ValueError', 'Pinned stream input bytes differ'))
    for case, change, reason in (
        ('preservation-missing-field-refusal', lambda v: v.pop('order_seq'), 'EXACT_ORIGINAL_PHYSICAL_STATE_SCHEMA_REQUIRED'),
        ('preservation-extra-field-refusal', lambda v: v.update(extra=1), 'EXACT_ORIGINAL_PHYSICAL_STATE_SCHEMA_REQUIRED'),
        ('preservation-logical-ending-mismatch-refusal', lambda v: v.update(order_seq=3), 'FINAL_PHYSICAL_STATE_DIFFERS_FROM_COMPLETION')):
        changed = Fixture(env, target / case, physical_change=change)
        candidate = changed.candidate()
        outcome(rows, case, lambda: env.context.preserved_archives(candidate, changed.physical_sha, changed.physical_size), refusal=('ValueError', reason))
    # CURRENT source rejection is an exact source-byte boundary, not native-map acceptance after mutation.
    outcome(rows, 'preservation-CURRENT-paper-source-refusal', lambda: env.metadata.paper_descriptor((AUDIT / 'current-paper-source.txt').read_bytes()), refusal=('RuntimeError', 'EXACT_N2_PAPER_SOURCE_REQUIRED'), scope='SOURCE_DESCRIPTOR_BOUNDARY_ONLY_CONTEXT_NATIVE31_WOULD_REFUSE_EARLIER')
    outcome(rows, 'preservation-archive-type-refusal', lambda: env.context.preserved_archives(object(), '0' * 64, 0), refusal=('ValueError', 'EXACT_CAPACITY_ARCHIVES_REQUIRED'))


# Run the first two explicitly isolated groups without invoking any old test entry point.
def context_group(env, target):
    rows = []
    readers(env, target, rows)
    ref = reference(env)
    constructors(env, target, rows, ref)
    inputs_and_sources(env, target, rows)
    return rows
