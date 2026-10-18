"""Prepare new source-only syntax tools for fifteen already authenticated package texts."""

import ast
import hashlib
import json
from pathlib import Path
import sys

SOURCES = Path(__file__).resolve().parent
MODULES = ('pyarrow._generated_version', 'pyarrow.ipc', 'pyarrow.types', 'pyarrow.util',
    'pyarrow.compute', 'numpy.version', 'numpy._distributor_init', 'numpy._core',
    'scipy.version', 'scipy._distributor_init', 'scipy._lib._ccallback',
    'sklearn._config', 'sklearn._distributor_init', 'sklearn.base', 'sklearn.utils._show_versions')


# Refuse undeclared text drift instead of silently omitting a generator change.
def once(text, old, new):
    assert text.count(old) == 1, old[:100]
    return text.replace(old, new, 1)


# Replace a single literal source assignment without executing its module.
def assignment(text, name, expression):
    tree = ast.parse(text)
    node = next(node for node in tree.body if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == name for target in node.targets))
    lines = text.splitlines(keepends=True)
    return ''.join(lines[:node.lineno - 1]) + name + ' = ' + expression + '\n' + ''.join(lines[node.end_lineno:])


# Write one new operational helper and repin the existing bounded SSH transport text.
def output(helper_name, text, transport_old, transport_sha, transport_name, old_helper, old_sha, old_size):
    ast.parse(text)
    helper = SOURCES / helper_name
    with helper.open('xb') as stream:
        stream.write(text.encode())
    raw = (SOURCES / transport_old).read_bytes()
    assert hashlib.sha256(raw).hexdigest() == transport_sha
    transport = raw.decode().replace('capacity-package-', 'capacity-native-package-')
    transport = once(transport, old_helper, helper_name)
    transport = transport.replace(old_sha, hashlib.sha256(text.encode()).hexdigest())
    transport = transport.replace(str(old_size), str(len(text.encode())))
    ast.parse(transport)
    target = SOURCES / transport_name
    with target.open('xb') as stream:
        stream.write(transport.encode())
    print(json.dumps({path.name: {'sha256': hashlib.sha256(path.read_bytes()).hexdigest(), 'bytes': path.stat().st_size} for path in (helper, target)}, sort_keys=True))


# Declare source analysis for the new fifteen copies, retaining assignment syntax only.
def primary():
    raw = (SOURCES / 'analyze-stopped-package-texts-v1-2026-10-18.py').read_bytes()
    assert hashlib.sha256(raw).hexdigest() == '5992dab789eb1a7136a77469bce2dd30a67b573cfed47fa8f7345070755b1867'
    text = raw.decode().replace('capacity-stopped-package-source-census', 'capacity-native-package-text-census').replace('capacity-package-source-analysis', 'capacity-native-package-source-analysis')
    text = assignment(text, 'PRIOR_SHA', repr('f26f8539c52247f03e7e7c92daaa57a28bb06ccf3b5dfeb6024d1ff2ae6b1aa1'))
    text = assignment(text, 'MODULES', repr(MODULES))
    text = assignment(text, 'SELECTED', '{}')
    text = once(text, "'bytes': 36153", "'bytes': 51904")
    text = once(text, 'VERIFIED_TEN_PAIRED_TEXT_SOURCE_COPIES_ONLY_NOT_PACKAGE_RUNTIME_CLOSURE', 'VERIFIED_FIFTEEN_PAIRED_TEXT_SOURCE_COPIES_ONLY_NOT_PACKAGE_RUNTIME_CLOSURE')
    text = once(text, "prior['source_files'] == 10 and prior['source_bytes'] == 337466", "prior['source_files'] == 15 and prior['source_bytes'] == 137785")
    text = once(text, 'from all ten pinned texts.', 'from all fifteen newly pinned texts.')
    text = once(text, "'selected': selected, 'generated_source_expression_count': generated,", "'selected': selected, 'top_level_assignment_syntax': [{'line': node.lineno, 'source': ast.unparse(node)} for node in tree.body if isinstance(node, (ast.Assign, ast.AnnAssign))], 'generated_source_expression_count': generated,")
    text = once(text, "'source_AST_sha256': value['source_AST_sha256'], 'selected': value['selected']", "'source_AST_sha256': value['source_AST_sha256'], 'selected': value['selected'],\n                'top_level_assignment_syntax': value['top_level_assignment_syntax'],\n                'small_version_or_distributor_source': raw.decode('utf-8') if index in (0, 5, 6, 8, 9, 12) else None")
    text = once(text, "'stopped-package-text-analysis/1'", "'native-package-text-analysis/1'")
    output('analyze-native-package-texts-v1-2026-10-18.py', text,
        'stopped-package-text-analysis-transport-v1-2026-10-18.py',
        '3ce05f3d0fffc59a2a8d0fcf68cc0527dc5b64ac7c8f15d0a8863fccea023954',
        'native-package-text-analysis-transport-v1-2026-10-18.py',
        'analyze-stopped-package-texts-v1-2026-10-18.py',
        '5992dab789eb1a7136a77469bce2dd30a67b573cfed47fa8f7345070755b1867', 9446)


# Bind observed summary bytes before preparing the distinct independent AST fold.
def independent(summary_sha, summary_bytes):
    assert len(summary_sha) == 64 and all(char in '0123456789abcdef' for char in summary_sha)
    assert 0 < summary_bytes <= 262144
    raw = (SOURCES / 'verify-package-text-analysis-v1-2026-10-18.py').read_bytes()
    assert hashlib.sha256(raw).hexdigest() == '32ef34ba819c00301efcabf03288fb73f438bc4bd01cae033df8ecea2753c42b'
    text = raw.decode().replace('capacity-package-', 'capacity-native-package-').replace('capacity-stopped-package-source-census', 'capacity-native-package-text-census')
    text = once(text, '5b06e98e1335a62a8c71b0240653cb73fd13f1c009e7b5867914fcec8e02bb6e', summary_sha)
    text = once(text, "'bytes': 137883", "'bytes': " + str(summary_bytes))
    text = once(text, '6860a76c8a50e4891549ea656ed881cf81518ae1e7d28b02ba65bd32d045c08b', 'f26f8539c52247f03e7e7c92daaa57a28bb06ccf3b5dfeb6024d1ff2ae6b1aa1')
    text = once(text, "'bytes': 36153", "'bytes': 51904")
    text = once(text, "len(summary['modules']) == 10 and len(summary['pages']) == 32", "[row['module'] for row in summary['modules']] == " + repr(list(MODULES)) + " and len(summary['pages']) <= 128")
    text = once(text, 'len(set(names)) == 32', 'len(set(names)) == len(names)')
    text = once(text, "records = sections[module['module']]", "records = sections.get(module['module'], [])")
    text = once(text, "            generated = sum(isinstance(node,", "            assert module['top_level_assignment_syntax'] == [{'line': node.lineno, 'source': ast.unparse(node)} for node in tree.body if isinstance(node, (ast.Assign, ast.AnnAssign))]\n            assert module['small_version_or_distributor_source'] == (raw.decode('utf-8') if index in (0, 5, 6, 8, 9, 12) else None)\n            generated = sum(isinstance(node,")
    text = once(text, "        assert totals == {'calls': 1231, 'imports': 170, 'declarations': 279, 'generated_source_expressions': 82}", "        assert totals['calls'] == sum(row['call_count'] for row in summary['modules']) and totals['imports'] == sum(len(row['imports']) for row in summary['modules'])")
    text = once(text, "'package-text-analysis-independent/1'", "'native-package-text-analysis-independent/1'")
    text = once(text, 'source_rows = {}', 'source_rows, compute_source_text = {}, None')
    text = once(text, '            source_rows[name] = row', "            source_rows[name] = row\n            if module['module'] == 'pyarrow.compute':\n                assert compute_source_text is None\n                compute_source_text = raw.decode('utf-8')")
    text = once(text, "'pages': physical_rows, 'totals': totals,", "'pages': physical_rows, 'totals': totals,\n            'selected_compute_source_text': compute_source_text,")
    output('verify-native-package-text-analysis-v1-2026-10-18.py', text,
        'package-text-analysis-independent-transport-v1-2026-10-18.py',
        '315c3d07f73473c02674dac8e0f7ba6684621a6b349988dc351bc22b327150f4',
        'native-package-text-analysis-independent-transport-v1-2026-10-18.py',
        'verify-package-text-analysis-v1-2026-10-18.py',
        '32ef34ba819c00301efcabf03288fb73f438bc4bd01cae033df8ecea2753c42b', 7816)


if __name__ == '__main__':
    if sys.argv[1:] == ['primary']:
        primary()
    else:
        assert len(sys.argv) == 4 and sys.argv[1] == 'independent'
        independent(sys.argv[2], int(sys.argv[3]))
