"""Prepare a distinct retained-data observation transport from reviewed finite outer source."""
import ast
import hashlib
from pathlib import Path

HERE = Path(__file__).resolve().parent


# Retain unchanged SSH ownership and cleanup while selecting only the new read-only observer.
def main():
    raw = (HERE / 'callback-symbol-synthetic-transport-v1-2026-10-18.py').read_bytes()
    assert hashlib.sha256(raw).hexdigest() == '2be80072e441080ca8b23a37f544d9804d35a7bb20534eeee245050b62bc02ed'
    source = raw.decode()
    observer = (HERE / 'observe-callback-symbol-synthetic-v1-2026-10-18.py').read_text()
    ast.parse(observer)
    edits = []
    for node in ast.parse(source).body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            name = node.targets[0].id
            if name == 'PINS':
                edits.append((node.lineno, node.end_lineno, 'PINS = {}'))
            elif name == 'BOOTSTRAP':
                edits.append((node.lineno, node.end_lineno, 'BOOTSTRAP = ' + repr(observer)))
            elif name == 'LOCAL':
                edits.append((node.lineno, node.end_lineno, "LOCAL = Path('/tmp/callback-symbol-synthetic-observe-transport-20261018-v1')"))
    lines = source.splitlines(keepends=True)
    for start, end, replacement in sorted(edits, reverse=True):
        lines[start - 1:end] = [replacement + '\n']
    source = ''.join(lines)
    old = "sys.argv[1] in ('stage', 'run')"
    assert source.count(old) == 1
    source = source.replace(old, "sys.argv[1:] == ['observe', 'NONE']")
    source = source.replace('# Authenticate four compressed operational sources for explicit stage or one reviewed Linux synthetic invocation.', '# Observe retained source and result data through one finite read-only SSH without fixture execution.')
    source = source.replace('"""New pinned-key source-only staging or one separately reviewed SYNTHETIC63 invocation."""', '"""Separate pinned-key retained synthetic-data observation with no fixture replay."""')
    ast.parse(source)
    target = HERE / 'callback-symbol-synthetic-observer-transport-v1-2026-10-18.py'
    with target.open('x') as output:
        output.write(source)
    assert target.read_text() == source
    print(target.name, len(source.encode()), hashlib.sha256(source.encode()).hexdigest())


if __name__ == '__main__':
    main()
