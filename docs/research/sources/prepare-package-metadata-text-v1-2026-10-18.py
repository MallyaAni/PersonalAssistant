"""Prepare new bounded metadata-content controls from pinned operational source only."""
import ast
import hashlib
from pathlib import Path
import sys

SOURCES = Path(__file__).resolve().parent
HEAD_SHA = '4a30076a7e6b530b7e24ffa1990abeb6d7a817974d96ef3d6f8100b1e7e111ab'
PATH_DECLARATION = """PATHS = ('/usr/local/lib/python3.12/site-packages/pyarrow-25.0.1.dist-info/METADATA',
    '/usr/local/lib/python3.12/site-packages/pyarrow-25.0.1.dist-info/RECORD',
    '/usr/local/lib/python3.12/site-packages/numpy-2.5.3.dist-info/METADATA',
    '/usr/local/lib/python3.12/site-packages/numpy-2.5.3.dist-info/RECORD',
    '/usr/local/lib/python3.12/site-packages/scipy-1.18.1.dist-info/METADATA',
    '/usr/local/lib/python3.12/site-packages/scipy-1.18.1.dist-info/RECORD')
SIZES = (3031, 78313, 6635, 111517, 62353, 201096)
PRIOR = Path('/home/animallya96/scratch/capacity-package-metadata-head-independent-20261018-v1/proof.json')
HEAD_SHA = '4a30076a7e6b530b7e24ffa1990abeb6d7a817974d96ef3d6f8100b1e7e111ab'
BASELINE = 'd5265be87b979e83e396e18d1d9d4571cc6e1db5aa09239200004a2809bd90d2'"""


# Require one exact declared text change rather than silently accepting drift.
def once(text, old, new):
    assert text.count(old) == 1, old[:90]
    return text.replace(old, new, 1)


# Read one pinned operational source as text, never importing its module.
def source(name, sha):
    raw = (SOURCES / name).read_bytes()
    assert hashlib.sha256(raw).hexdigest() == sha
    return raw.decode()


# Select a complete function plus purpose comment using source positions only.
def function(text, name):
    node, = [node for node in ast.parse(text).body if isinstance(node, ast.FunctionDef) and node.name == name]
    return '\n'.join(text.splitlines()[node.lineno - 2:node.end_lineno])


# Replace only the fixed-path declaration while preserving surrounding source.
def paths(text):
    node, = [node for node in ast.parse(text).body if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == 'PATHS' for target in node.targets)]
    lines = text.splitlines(keepends=True)
    return ''.join(lines[:node.lineno - 1]) + PATH_DECLARATION + '\n' + ''.join(lines[node.end_lineno:])


# Retain a fresh parseable control source and return its whole-byte pin.
def write(name, text):
    raw = text.encode()
    ast.parse(raw)
    with (SOURCES / name).open('xb') as stream:
        stream.write(raw)
    assert (SOURCES / name).read_bytes() == raw
    return hashlib.sha256(raw).hexdigest(), len(raw)


# Derive a new one-shot transport without running SSH or the prepared helper.
def transport(helper_name, sha, size, independent):
    text = source('capacity-native-package-text-transport-v1-2026-10-18.py',
        '518ded7394ae1b04db85f32b89e15693086f8e184c231ac2b891391d2f749b08')
    label = 'independent-' if independent else ''
    changes = {
        'capacity-native-package-text-census-v1-2026-10-18.py': helper_name,
        '296d0e8dd4d58883388a5c8f5b2d5c0b6d09ccfdbf82cb44c060333637bb1428': sha,
        '13080': str(size),
        'capacity-native-package-text-transport-20261018-v1': 'capacity-package-metadata-text-' + label + 'transport-20261018-v1',
        'capacity-native-package-text-census-tools-20261018-v1': 'capacity-package-metadata-text-' + label + 'tools-20261018-v1',
        'collect-new-native-package-texts': 'verify-six-metadata-texts' if independent else 'collect-six-metadata-texts',
    }
    for old, new in changes.items():
        assert old in text
        text = text.replace(old, new)
    if independent:
        text = once(text, 'timeout=120', 'timeout=70')
    write('package-metadata-text-' + label + 'transport-v1-2026-10-18.py', text)


# Prepare paired metadata copies with exact prior HEAD bindings and unchanged wire/content limits.
def primary():
    text = paths(source('capacity-native-package-text-census-v1-2026-10-18.py',
        '296d0e8dd4d58883388a5c8f5b2d5c0b6d09ccfdbf82cb44c060333637bb1428'))
    text = text.replace('capacity-native-package-text-census-20261018-v1', 'capacity-package-metadata-text-census-20261018-v1')
    text = once(text, 'import sys\n', 'import sys\nimport stat\n')
    old_checker = source('verify-native-package-text-census-v1-2026-10-18.py',
        '3b41d5ae9449b724cd8cb31333d1c8479475c580ab63d21370056bd0628c22ee')
    marker = '# Propose exact source reads only; collection requires a separately reviewed concrete invocation.'
    text = once(text, marker, function(old_checker, 'physical') + '\n\n\n' + function(old_checker, 'read')
        + '\n\n\n# Copy exactly six metadata files without importing packages or interpreting their contents.')
    text = once(text, "['collect-new-native-package-texts']", "['collect-six-metadata-texts']")
    text = once(text, '        assert 0 < member.size <= CAP and not member.linkname',
        '        assert member.size == SIZES[PATHS.index(path)] <= CAP and not member.linkname')
    text = once(text, "        before = inspect_source(command('inspect-before', ('container', 'inspect', CID), deadline))",
        """        prior_raw, prior_row = read(PRIOR)
        assert digest(prior_raw) == HEAD_SHA and len(prior_raw) == 23927
        prior = json.loads(prior_raw)
        assert prior['status'] == 'VERIFIED_RETAINED_PAIRED_DAEMON_PATH_METADATA_ONLY'
        assert [row['container_path'] for row in prior['path_observations']] == list(PATHS)
        assert [row['path_metadata']['stat']['size'] for row in prior['path_observations']] == list(SIZES)
        assert all(row['path_metadata']['http_status'] == 200 for row in prior['path_observations'])
        saved_prior = save('prior-head-proof.json', prior_raw)
        before_raw = command('inspect-before', ('container', 'inspect', CID), deadline)
        before = inspect_source(before_raw)
        assert digest(before_raw) == BASELINE""")
    text = text.replace('source-%02d.py.txt', 'source-%02d.metadata.txt')
    text = once(text, "        after = inspect_source(command('inspect-after', ('container', 'inspect', CID), deadline))",
        "        after_raw = command('inspect-after', ('container', 'inspect', CID), deadline)\n        after = inspect_source(after_raw)\n        assert digest(after_raw) == BASELINE\n        assert read(PRIOR) == (prior_raw, prior_row)")
    text = once(text, "'stopped-n2-native-package-text-census/1'", "'stopped-n2-package-metadata-text-census/1'")
    text = once(text, "'container': CID, 'image': IMAGE, 'sources': sources,",
        "'container': CID, 'image': IMAGE, 'sources': sources,\n            'prior_head_proof': saved_prior, 'prior_head_physical': prior_row,")
    text = once(text, '"""Unexecuted bounded source census for one exact stopped N2 native-probe container."""',
        '"""Copy six exact metadata texts from the retained stopped N2 container without package execution."""')
    name = 'capacity-package-metadata-text-census-v1-2026-10-18.py'
    sha, size = write(name, text)
    transport(name, sha, size, False)
    print(sha, size)


# Bind a separately reviewed independent readback to the observed primary candidate.
def independent(candidate_sha):
    assert len(candidate_sha) == 64 and all(c in '0123456789abcdef' for c in candidate_sha)
    text = paths(source('verify-native-package-text-census-v1-2026-10-18.py',
        '3b41d5ae9449b724cd8cb31333d1c8479475c580ab63d21370056bd0628c22ee'))
    text = text.replace('capacity-native-package-text-census-20261018-v1', 'capacity-package-metadata-text-census-20261018-v1')
    text = text.replace('capacity-native-package-text-census-review-20261018-v1', 'capacity-package-metadata-text-independent-20261018-v1')
    text = once(text, '288d593318086a0399137f4734f3a9b9930cb5b793c217203cf569a49788d6e8', candidate_sha)
    text = once(text, "'stopped-n2-native-package-text-census/1'", "'stopped-n2-package-metadata-text-census/1'")
    text = once(text, "    names = {'candidate.json', 'prerequisites.json'}",
        "    names = {'candidate.json', 'prerequisites.json', 'prior-head-proof.json'}")
    text = once(text, 'len(names) == 113', 'len(names) == 51')
    text = text.replace('source-%02d.py.txt', 'source-%02d.metadata.txt')
    text = once(text, "    for index, row in enumerate(candidate['sources']):",
        """    prior_raw, prior_row = read(PRIOR)
    assert digest(prior_raw) == HEAD_SHA and len(prior_raw) == 23927
    assert bodies['prior-head-proof.json'] == prior_raw
    assert candidate['prior_head_proof'] == {'file': 'prior-head-proof.json', 'bytes': len(prior_raw), 'sha256': HEAD_SHA}
    assert candidate['prior_head_physical'] == prior_row
    prior = json.loads(prior_raw)
    assert [row['container_path'] for row in prior['path_observations']] == list(PATHS)
    assert [row['path_metadata']['stat']['size'] for row in prior['path_observations']] == list(SIZES)
    for index, row in enumerate(candidate['sources']):""")
    text = once(text, "        bodies[name].decode('utf-8', errors='strict')",
        "        bodies[name].decode('utf-8', errors='strict')\n        assert len(bodies[name]) == SIZES[index] and len(row['reads']) == 2")
    text = once(text, '                assert member.name == Path(PATHS[index]).name and member.isfile() and not member.sparse and not member.linkname',
        '                assert member.name == Path(PATHS[index]).name and member.isfile() and not member.sparse and not member.linkname\n                assert member.size == SIZES[index] and not member.issym() and not member.islnk()\n                assert 1024 <= len(wire) <= CAP and len(wire) % 512 == 0')
    text = once(text, '    assert json.loads(fresh) == before',
        "    assert json.loads(fresh) == before and digest(fresh) == BASELINE\n    for name in sorted(names):\n        assert read(ROOT / name) == (bodies[name], inventory[name])\n    assert read(PRIOR) == (prior_raw, prior_row)")
    text = once(text, "'stopped-n2-native-package-text-census-independent/1'", "'stopped-n2-package-metadata-text-census-independent/1'")
    text = once(text, 'VERIFIED_FIFTEEN_PAIRED_TEXT_SOURCE_COPIES_ONLY_NOT_PACKAGE_RUNTIME_CLOSURE',
        'VERIFIED_SIX_PAIRED_METADATA_TEXT_COPIES_ONLY_NOT_INSTALLED_VERSION_OR_NATIVE_CLOSURE')
    text = once(text, "'source_files': 15, 'full_readback_files': 113", "'source_files': 6, 'full_readback_files': 51")
    text = once(text, 'range(15)', 'range(6)')
    text = once(text, "        'container_file_physical_identity': None, 'transitive_package_closure': None}",
        "        'container_file_physical_identity': None, 'transitive_package_closure': None,\n        'prior_head_proof': prior_row}")
    start = text.index('    watched = (signal.SIGALRM, signal.SIGHUP, signal.SIGINT, signal.SIGTERM)')
    end = text.index('    fresh_row = ', start)
    assert 'signal.alarm(10)' in text[start:end] and 'signal.alarm(0)' in text[start:end]
    text = text[:start] + "    fresh = command('independent-fresh-inspect', ('container', 'inspect', CID), time.monotonic() + 5)\n" + text[end:]
    text = once(text, "    assert arguments in (('container', 'inspect', CID),) or (\n        len(arguments) == 4 and arguments[:2] == ('container', 'cp')\n        and arguments[2] in tuple(CID + ':' + path for path in PATHS) and arguments[3] == '-')",
        "    assert arguments == ('container', 'inspect', CID)")
    text = once(text, "if __name__ == '__main__':\n    main()", """# Bound all independent file reads as well as the one fresh stopped inspection.
def run(arguments):
    assert arguments == ['verify-six-metadata-texts']
    previous = {sig: signal.signal(sig, alarm) for sig in (signal.SIGALRM, signal.SIGHUP, signal.SIGINT, signal.SIGTERM)}
    signal.alarm(30)
    try:
        main()
    finally:
        signal.alarm(0)
        for sig, handler in previous.items():
            signal.signal(sig, handler)


if __name__ == '__main__':
    run(sys.argv[1:])""")
    text = once(text, 'import time\n', 'import time\nimport sys\n')
    name = 'verify-package-metadata-text-census-v1-2026-10-18.py'
    sha, size = write(name, text)
    transport(name, sha, size, True)
    print(sha, size)


if __name__ == '__main__':
    assert len(sys.argv) in (2, 3)
    if sys.argv[1] == 'primary':
        assert len(sys.argv) == 2
        primary()
    else:
        assert sys.argv[1] == 'independent' and len(sys.argv) == 3
        independent(sys.argv[2])
