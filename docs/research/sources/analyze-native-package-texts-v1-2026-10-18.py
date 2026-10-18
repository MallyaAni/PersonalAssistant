"""Analyze authenticated retained text with stdlib AST only; never import package payloads."""
import ast
import copy
import hashlib
import json
import os
from pathlib import Path
import resource
import signal
import stat
import time

SOURCE = Path('/home/animallya96/scratch/capacity-native-package-text-census-20261018-v1')
PRIOR = Path('/home/animallya96/scratch/capacity-native-package-text-census-review-20261018-v1/proof.json')
PRIOR_SHA = 'f26f8539c52247f03e7e7c92daaa57a28bb06ccf3b5dfeb6024d1ff2ae6b1aa1'
ROOT = Path('/home/animallya96/scratch/capacity-native-package-source-analysis-20261018-v1')
CAP = 262144
MODULES = ('pyarrow._generated_version', 'pyarrow.ipc', 'pyarrow.types', 'pyarrow.util', 'pyarrow.compute', 'numpy.version', 'numpy._distributor_init', 'numpy._core', 'scipy.version', 'scipy._distributor_init', 'scipy._lib._ccallback', 'sklearn._config', 'sklearn._distributor_init', 'sklearn.base', 'sklearn.utils._show_versions')
SELECTED = {}


# Bind copied file physical fields without rounding nanosecond values through floats.
def physical(value):
    return {key: str(getattr(value, key)) for key in ('st_dev', 'st_ino', 'st_mode',
        'st_uid', 'st_nlink', 'st_size', 'st_blocks', 'st_mtime_ns', 'st_ctime_ns')}


# Authenticate each copied source against its independent proof and held-file bookends.
def read(path, expected):
    assert path.resolve(strict=True) == path
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        before = os.fstat(descriptor)
        assert stat.S_ISREG(before.st_mode) and before.st_uid == 1000 and before.st_nlink == 1
        assert 0 <= before.st_size <= CAP
        raw = os.read(descriptor, CAP + 1)
        os.lseek(descriptor, 0, os.SEEK_SET)
        assert os.read(descriptor, CAP + 1) == raw and len(raw) == before.st_size
        assert physical(before) == physical(os.fstat(descriptor)) == physical(path.stat(follow_symlinks=False))
        row = {'sha256': hashlib.sha256(raw).hexdigest(), 'bytes': len(raw), 'physical': physical(before)}
        for key, value in expected.items():
            assert row[key] == value
        return raw, row
    finally:
        os.close(descriptor)


# Retain a new finite JSON observation with exclusive creation and fsynced readback.
def save(name, value):
    raw = json.dumps(value, sort_keys=True, indent=2, allow_nan=False).encode() + b'\n'
    assert len(raw) <= CAP and Path(name).name == name
    with (ROOT / name).open('xb') as stream:
        stream.write(raw); stream.flush(); os.fsync(stream.fileno())
    assert (ROOT / name).read_bytes() == raw
    return {'file': name, 'sha256': hashlib.sha256(raw).hexdigest(), 'bytes': len(raw)}


# Record lexical ancestor fields explicitly without pretending to evaluate definition expressions.
def ancestry(node, parents):
    result = []
    while node in parents:
        parent, field = parents[node]
        if isinstance(parent, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda,
                ast.If, ast.Try, ast.For, ast.While, ast.With, ast.Match, ast.GeneratorExp)):
            result.append({'kind': type(parent).__name__, 'name': getattr(parent, 'name', None),
                'line': parent.lineno, 'child_field': field})
        node = parent
    return list(reversed(result))


# Name declarations only from their source nesting, not compiled code identities.
def qualified(node, parents):
    names = [getattr(node, 'name', '<lambda>')]
    while node in parents:
        node, field = parents[node]
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.append(node.name)
    return '.'.join(reversed(names))


# Bound the work without executing any copied package function or class body.
def alarm(signum, frame):
    raise TimeoutError('PACKAGE_TEXT_ANALYSIS_WALL_BOUND')


# Inventory imports, call syntax and generated-source expressions from all fifteen newly pinned texts.
def analyze(raw, module):
    tree = ast.parse(raw.decode('utf-8'), filename=module, mode='exec')
    parents = {}
    for parent in ast.walk(tree):
        for field, value in ast.iter_fields(parent):
            for child in value if isinstance(value, list) else [value]:
                if isinstance(child, ast.AST):
                    parents[child] = (parent, field)
    imports, calls, declarations, selected = [], [], [], []
    generated = 0
    for node in ast.walk(tree):
        context = ancestry(node, parents)
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            imports.append({'line': node.lineno, 'source': ast.unparse(node), 'ancestors': context})
        if isinstance(node, ast.Call):
            calls.append({'line': node.lineno, 'function_syntax': ast.unparse(node.func), 'ancestors': context})
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            name = qualified(node, parents)
            item = {'kind': type(node).__name__, 'name': name, 'line': node.lineno,
                'ast_sha256': hashlib.sha256(ast.dump(node, include_attributes=False).encode()).hexdigest()}
            declarations.append(item)
            if name in SELECTED.get(module, set()):
                projection = copy.deepcopy(node)
                if projection.body and isinstance(projection.body[0], ast.Expr) and isinstance(projection.body[0].value, ast.Constant) and isinstance(projection.body[0].value.value, str):
                    projection.body = projection.body[1:]
                selected.append({**item, 'source_without_leading_docstring': ast.unparse(projection),
                    'scope': 'DISPLAY_ONLY_SOURCE_PROJECTION_NOT_CODETYPE_OR_EXECUTABLE'})
        if isinstance(node, (ast.Lambda, ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)):
            generated += 1
    assert len(calls) == sum(isinstance(node, ast.Call) for node in ast.walk(tree))
    return {'module': module, 'imports': imports, 'calls': calls, 'declarations': declarations,
        'selected': selected, 'top_level_assignment_syntax': [{'line': node.lineno, 'source': ast.unparse(node)} for node in tree.body if isinstance(node, (ast.Assign, ast.AnnAssign))], 'generated_source_expression_count': generated,
        'source_AST_sha256': hashlib.sha256(ast.dump(tree, include_attributes=False).encode()).hexdigest()}


# Perform one isolated source analysis from immutable copies with no Docker or package imports.
def main():
    assert __debug__ and os.getuid() == 1000
    os.umask(0o077); os.nice(10)
    resource.setrlimit(resource.RLIMIT_AS, (536870912, 536870912))
    resource.setrlimit(resource.RLIMIT_CPU, (20, 20))
    resource.setrlimit(resource.RLIMIT_FSIZE, (CAP, CAP))
    prior_raw, prior_row = read(PRIOR, {'sha256': PRIOR_SHA, 'bytes': 51904})
    prior = json.loads(prior_raw)
    assert prior['status'] == 'VERIFIED_FIFTEEN_PAIRED_TEXT_SOURCE_COPIES_ONLY_NOT_PACKAGE_RUNTIME_CLOSURE'
    assert prior['source_files'] == 15 and prior['source_bytes'] == 137785
    assert ROOT.parent.resolve(strict=True) == ROOT.parent
    ROOT.mkdir(mode=0o700, exist_ok=False)
    previous = signal.signal(signal.SIGALRM, alarm)
    signal.alarm(30)
    try:
        summaries, pages, physical_rows = [], [], {}
        for index, module in enumerate(MODULES):
            name = 'source-%02d.py.txt' % index
            raw, row = read(SOURCE / name, prior['source_inventory'][name])
            physical_rows[name] = row
            value = analyze(raw, module)
            records = [{'section': section, 'value': record} for section in ('imports', 'calls', 'declarations') for record in value[section]]
            for offset in range(0, len(records), 64):
                page_name = 'module-%02d-page-%03d.json' % (index, offset // 64)
                pages.append(save(page_name, {'module': module, 'source_sha256': row['sha256'], 'records': records[offset:offset + 64]}))
            module_calls = [call for call in value['calls'] if not any(
                ancestor['kind'] in ('FunctionDef', 'AsyncFunctionDef', 'Lambda') and ancestor['child_field'] == 'body'
                for ancestor in call['ancestors'])]
            summaries.append({'module': module, 'source': row,
                'imports': value['imports'], 'module_definition_call_syntax': module_calls,
                'call_count': len(value['calls']), 'declaration_count': len(value['declarations']),
                'generated_source_expression_count': value['generated_source_expression_count'],
                'source_AST_sha256': value['source_AST_sha256'], 'selected': value['selected'],
                'top_level_assignment_syntax': value['top_level_assignment_syntax'],
                'small_version_or_distributor_source': raw.decode('utf-8') if index in (0, 5, 6, 8, 9, 12) else None})
        for name, row in physical_rows.items():
            read(SOURCE / name, row)
        read(PRIOR, prior_row)
        summary = {'schema': 'native-package-text-analysis/1',
            'status': 'SOURCE_SYNTAX_INVENTORY_ONLY_NOT_EVALUATED_IMPORT_NATIVE_CALL_CLOSURE',
            'prior_proof_sha256': PRIOR_SHA, 'modules': summaries, 'pages': pages,
            'observed_at_ns': str(time.time_ns()), 'copied_sources_physical_bookends_equal': True,
            'payload_import_CodeType_or_body': False, 'runtime_admission': None}
        pointer = save('summary.json', summary)
        descriptor = os.open(ROOT, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        os.fsync(descriptor); os.close(descriptor)
        print(json.dumps({'summary': summary, 'pointer': pointer}, sort_keys=True), flush=True)
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, previous)


if __name__ == '__main__':
    main()
