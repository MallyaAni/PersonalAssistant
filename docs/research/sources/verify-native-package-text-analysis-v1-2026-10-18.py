"""Independently fold source syntax counts and preserved AST inventory pages without imports."""
import ast
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import resource
import signal
import stat

ROOT = Path('/home/animallya96/scratch/capacity-native-package-source-analysis-20261018-v1')
SOURCE = Path('/home/animallya96/scratch/capacity-native-package-text-census-20261018-v1')
PRIOR = Path('/home/animallya96/scratch/capacity-native-package-text-census-review-20261018-v1/proof.json')
OUT = Path('/home/animallya96/scratch/capacity-native-package-text-analysis-independent-20261018-v1')
CAP = 262144


# Return physical metadata with exact integer string fields for local copied evidence.
def physical(value):
    return {key: str(getattr(value, key)) for key in ('st_dev', 'st_ino', 'st_mode',
        'st_uid', 'st_nlink', 'st_size', 'st_blocks', 'st_mtime_ns', 'st_ctime_ns')}


# Authenticate one bounded file twice using a held descriptor and named physical bookends.
def read(path, expected=None):
    assert path.resolve(strict=True) == path
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        before = os.fstat(descriptor)
        assert stat.S_ISREG(before.st_mode) and before.st_uid == 1000 and before.st_nlink == 1
        assert 0 <= before.st_size <= CAP
        raw = os.read(descriptor, CAP + 1); os.lseek(descriptor, 0, os.SEEK_SET)
        assert os.read(descriptor, CAP + 1) == raw and len(raw) == before.st_size
        assert physical(before) == physical(os.fstat(descriptor)) == physical(path.stat(follow_symlinks=False))
        row = {'sha256': hashlib.sha256(raw).hexdigest(), 'bytes': len(raw), 'physical': physical(before)}
        if expected is not None:
            for key, value in expected.items():
                assert row[key] == value
        return raw, row
    finally:
        os.close(descriptor)


# Bound the independent source analysis without compiling package CodeTypes or executing bodies.
def alarm(signum, frame):
    raise TimeoutError('PACKAGE_TEXT_INDEPENDENT_WALL_BOUND')


# Recompute source AST counts and exact call/import/declaration multisets independently.
def main():
    assert __debug__ and os.getuid() == 1000
    os.umask(0o077); os.nice(10)
    resource.setrlimit(resource.RLIMIT_AS, (536870912, 536870912))
    resource.setrlimit(resource.RLIMIT_CPU, (20, 20))
    resource.setrlimit(resource.RLIMIT_FSIZE, (CAP, CAP))
    previous = signal.signal(signal.SIGALRM, alarm); signal.alarm(30)
    try:
        summary_raw, summary_row = read(ROOT / 'summary.json', {'sha256': '5b36cad5f5c293e6e3a2236b77e2475dfb84c0328315ebc37747b174e80847b6', 'bytes': 70746})
        summary = json.loads(summary_raw)
        prior_raw, prior_row = read(PRIOR, {'sha256': 'f26f8539c52247f03e7e7c92daaa57a28bb06ccf3b5dfeb6024d1ff2ae6b1aa1', 'bytes': 51904})
        prior = json.loads(prior_raw)
        assert summary['payload_import_CodeType_or_body'] is False and summary['runtime_admission'] is None
        assert [row['module'] for row in summary['modules']] == ['pyarrow._generated_version', 'pyarrow.ipc', 'pyarrow.types', 'pyarrow.util', 'pyarrow.compute', 'numpy.version', 'numpy._distributor_init', 'numpy._core', 'scipy.version', 'scipy._distributor_init', 'scipy._lib._ccallback', 'sklearn._config', 'sklearn._distributor_init', 'sklearn.base', 'sklearn.utils._show_versions'] and len(summary['pages']) <= 128
        names = [row['file'] for row in summary['pages']]
        assert len(set(names)) == len(names) and set(names) | {'summary.json'} == {p.name for p in ROOT.iterdir()}
        physical_rows, sections = {}, {}
        for row in summary['pages']:
            assert Path(row['file']).name == row['file']
            raw, observed = read(ROOT / row['file'], {key: row[key] for key in ('sha256', 'bytes')})
            physical_rows[row['file']] = observed
            page = json.loads(raw)
            assert 1 <= len(page['records']) <= 64
            matches = [module for module in summary['modules'] if module['module'] == page['module']]
            assert len(matches) == 1 and page['source_sha256'] == matches[0]['source']['sha256']
            sections.setdefault(page['module'], []).extend(page['records'])
        totals = {'calls': 0, 'imports': 0, 'declarations': 0, 'generated_source_expressions': 0}
        source_rows, compute_source_text = {}, None
        for index, module in enumerate(summary['modules']):
            name = 'source-%02d.py.txt' % index
            raw, row = read(SOURCE / name, prior['source_inventory'][name])
            assert module['source'] == row
            source_rows[name] = row
            if module['module'] == 'pyarrow.compute':
                assert compute_source_text is None
                compute_source_text = raw.decode('utf-8')
            tree = ast.parse(raw.decode('utf-8'), filename=module['module'])
            assert hashlib.sha256(ast.dump(tree, include_attributes=False).encode()).hexdigest() == module['source_AST_sha256']
            records = sections.get(module['module'], [])
            imports = [item['value'] for item in records if item['section'] == 'imports']
            calls = [item['value'] for item in records if item['section'] == 'calls']
            declarations = [item['value'] for item in records if item['section'] == 'declarations']
            assert all(item['section'] in ('imports', 'calls', 'declarations') for item in records)
            assert imports == module['imports'] and len(calls) == module['call_count'] and len(declarations) == module['declaration_count']
            assert Counter((row['line'], row['source']) for row in imports) == Counter((node.lineno, ast.unparse(node)) for node in ast.walk(tree) if isinstance(node, (ast.Import, ast.ImportFrom)))
            assert Counter((row['line'], row['function_syntax']) for row in calls) == Counter((node.lineno, ast.unparse(node.func)) for node in ast.walk(tree) if isinstance(node, ast.Call))
            assert Counter((row['line'], row['kind'], row['ast_sha256']) for row in declarations) == Counter((node.lineno, type(node).__name__, hashlib.sha256(ast.dump(node, include_attributes=False).encode()).hexdigest()) for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)))
            assert module['top_level_assignment_syntax'] == [{'line': node.lineno, 'source': ast.unparse(node)} for node in tree.body if isinstance(node, (ast.Assign, ast.AnnAssign))]
            assert module['small_version_or_distributor_source'] == (raw.decode('utf-8') if index in (0, 5, 6, 8, 9, 12) else None)
            generated = sum(isinstance(node, (ast.Lambda, ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)) for node in ast.walk(tree))
            assert generated == module['generated_source_expression_count']
            totals['calls'] += len(calls); totals['imports'] += len(imports)
            totals['declarations'] += len(declarations); totals['generated_source_expressions'] += generated
        assert totals['calls'] == sum(row['call_count'] for row in summary['modules']) and totals['imports'] == sum(len(row['imports']) for row in summary['modules'])
        for name, row in source_rows.items():
            read(SOURCE / name, row)
        for name, row in physical_rows.items():
            read(ROOT / name, row)
        read(ROOT / 'summary.json', summary_row); read(PRIOR, prior_row)
        proof = {'schema': 'native-package-text-analysis-independent/1',
            'status': 'VERIFIED_STATIC_SYNTAX_COUNTS_MULTISETS_AND_FILE_BINDINGS_NOT_RUNTIME_CLOSURE',
            'summary': summary_row, 'prior': prior_row, 'sources': source_rows,
            'pages': physical_rows, 'totals': totals,
            'selected_compute_source_text': compute_source_text,
            'scope_limit': 'Does not independently reconstruct every lexical ancestor/qualified-name/display projection. No evaluated branch, package import, CodeType, native/thread/network/model/RAM acceptance.',
            'runtime_admission': None, 'payload_body_executed': False}
        body = json.dumps(proof, sort_keys=True, indent=2, allow_nan=False).encode() + b'\n'
        assert len(body) <= CAP and OUT.parent.resolve(strict=True) == OUT.parent
        OUT.mkdir(mode=0o700, exist_ok=False)
        with (OUT / 'proof.json').open('xb') as stream:
            stream.write(body); stream.flush(); os.fsync(stream.fileno())
        assert read(OUT / 'proof.json')[0] == body
        descriptor = os.open(OUT, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        os.fsync(descriptor); os.close(descriptor)
        print(body.decode(), end='')
    finally:
        signal.alarm(0); signal.signal(signal.SIGALRM, previous)


if __name__ == '__main__':
    main()
