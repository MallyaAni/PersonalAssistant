"""Derive one new page-only transport from authenticated operational SOURCE."""
import ast
import hashlib
import json
import os
from pathlib import Path

BASE = Path(__file__).resolve().parent
OLD = BASE / 'callback-elf-data-primary-transport-v1-2026-10-18.py'
DRIVER = 'observe-callback-section-page-v1-2026-10-18.py'
OUT = BASE / 'callback-section-page-transport-v1-2026-10-18.py'


# Replace one exact source fragment and refuse a stale or ambiguous template.
def change(text, old, new):
    assert text.count(old) == 1
    return text.replace(old, new)


# Replace complete top-level constants without altering the transport's cleanup functions.
def constants(text, values):
    lines = text.splitlines(keepends=True)
    nodes = {node.targets[0].id: node for node in ast.parse(text).body
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name)}
    changes = []
    for name, value in values.items():
        node = nodes[name]
        literal = 'Path(' + repr(str(value)) + ')' if isinstance(value, Path) else repr(value)
        changes.append((node.lineno - 1, node.end_lineno, name + ' = ' + literal + '\n'))
    for start, end, replacement in sorted(changes, reverse=True):
        lines[start:end] = [replacement]
    return ''.join(lines)


# Freeze one source-derived invocation and prove every existing transport function AST remains equal.
def main():
    raw = OLD.read_bytes()
    assert len(raw) == 8347 and hashlib.sha256(raw).hexdigest() == '6c85dd69fa8054a6b2b27d20798e2ea509c441e589c6faea4e14bfca521da7ab'
    driver_raw = (BASE / DRIVER).read_bytes()
    assert len(driver_raw) <= 262144
    pins = {DRIVER: hashlib.sha256(driver_raw).hexdigest()}
    tree = ast.parse(raw)
    boot_node = next(n for n in tree.body if isinstance(n, ast.Assign)
        and isinstance(n.targets[0], ast.Name) and n.targets[0].id == 'BOOTSTRAP')
    boot = ast.literal_eval(boot_node.value)
    boot = constants(boot, {'expected': pins})
    boot = change(boot, 'capacity-callback-elf-primary-tools-20261018-v1', 'capacity-callback-section-page-tools-20261018-v1')
    boot = change(boot, "target=pathlib.Path('/home/animallya96/scratch/capacity-callback-elf-data-analysis-20261018-v1')\nassert not os.path.lexists(target)\n", '')
    boot = change(boot, "'RETAINED_CALLBACK_ELF_DATA_ONLY'", "'RETAINED_SECTION_PAGE_DATA_ONLY'")
    boot = change(boot, "'phase':'primary'", "'phase':'section-page'")
    boot = change(boot, "path=root/'analyze-callback-elf-retained-v1-2026-10-18.py'", 'path=root/' + repr(DRIVER))
    ast.parse(boot)
    text = constants(raw.decode(), {'LOCAL': Path('/tmp/callback-section-page-transport-20261018-v1'), 'PINS': pins, 'BOOTSTRAP': boot})
    text = change(text, "'One reviewed retained-callback ELF DATA invocation; no native loading or old gates.'", "'One reviewed retained section-page DATA observation; no binary or parser execution.'")
    text = change(text, '# Authenticate two reviewed operational sources and dispatch one retained-binary DATA operation.', '# Authenticate one reviewed operational source and dispatch one retained-page DATA observation.')
    old_functions = [ast.dump(n, include_attributes=False) for n in tree.body if isinstance(n, ast.FunctionDef)]
    new_functions = [ast.dump(n, include_attributes=False) for n in ast.parse(text).body if isinstance(n, ast.FunctionDef)]
    assert old_functions == new_functions and len(old_functions) == 3
    body = text.encode()
    with OUT.open('xb') as stream:
        stream.write(body)
        stream.flush()
        os.fsync(stream.fileno())
    assert OUT.read_bytes() == body
    descriptor = os.open(BASE, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    print(json.dumps({'transport_sha256': hashlib.sha256(body).hexdigest(), 'bytes': len(body),
        'driver_sha256': pins, 'unchanged_function_ASTs': 3}, sort_keys=True))


if __name__ == '__main__':
    main()
