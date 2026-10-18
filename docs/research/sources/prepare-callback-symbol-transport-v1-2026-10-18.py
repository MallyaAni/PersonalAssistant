"""Derive a new compressed-envelope two-phase transport from authenticated old source only."""
import ast
import hashlib
from pathlib import Path

HERE = Path(__file__).resolve().parent


# Replace one exact source fragment and refuse ambiguous or missing preparation inputs.
def replace_once(source, old, new):
    assert source.count(old) == 1
    return source.replace(old, new)


# Write one new inert transport while preserving existing finite SSH ownership and cleanup source.
def main():
    old_path = HERE / 'callback-elf-synthetic-transport-v1-2026-10-18.py'
    raw = old_path.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == '777950f1bac4d9674518ce6a2e72d8398f6bdf9288c45e367e68c5867f325a19'
    source = raw.decode()
    tree = ast.parse(source)
    bootstrap = (HERE / 'callback-symbol-synthetic-bootstrap-v1-2026-10-18.py').read_text()
    boot_tree = ast.parse(bootstrap)
    pins_node = next(node for node in boot_tree.body if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'PINS' for t in node.targets))
    pins = {name: row[0] for name, row in ast.literal_eval(pins_node.value).items()}
    edits = []
    for node in tree.body:
        if isinstance(node, ast.Assign):
            names = [t.id for t in node.targets if isinstance(t, ast.Name)]
            if names == ['PINS']:
                edits.append((node.lineno, node.end_lineno, 'PINS = ' + repr(pins)))
            elif names == ['BOOTSTRAP']:
                edits.append((node.lineno, node.end_lineno, 'BOOTSTRAP = ' + repr(bootstrap)))
    lines = source.splitlines(keepends=True)
    for start, end, replacement in sorted(edits, reverse=True):
        lines[start - 1:end] = [replacement + '\n']
    source = ''.join(lines)
    source = replace_once(source, 'import hashlib\n', 'import hashlib\nimport gzip\nimport sys\n')
    source = replace_once(source, "LOCAL = Path('/tmp/callback-elf-synthetic-transport-20261018-v1')", "LOCAL = Path('/tmp/callback-symbol-synthetic-' + sys.argv[1] + '-transport-20261018-v1')")
    source = replace_once(source, "packet[name] = base64.b64encode(body).decode('ascii')", "packet[name] = base64.b64encode(gzip.compress(body, mtime=0)).decode('ascii')")
    source = replace_once(source, "str(TRUSTED),\n        'animallya96@172.16.8.3', shlex.join(['python3', '-I', '-S', '-B', '-c', BOOTSTRAP])]", "str(TRUSTED),\n        'animallya96@172.16.8.3', shlex.join(['python3', '-I', '-S', '-B', '-c', BOOTSTRAP, *sys.argv[1:]])]")
    source = replace_once(source, '    assert __debug__ and TRUSTED.read_bytes() == KEYS', "    assert __debug__ and len(sys.argv) == 3 and sys.argv[1] in ('stage', 'run')\n    assert TRUSTED.read_bytes() == KEYS")
    source = replace_once(source, '# Authenticate four operational sources and dispatch one synthetic-only Linux attempt without retries.', '# Authenticate four compressed operational sources for explicit stage or one reviewed Linux synthetic invocation.')
    source = replace_once(source, '"""One new pinned-key Linux invocation of synthetic-only ELF control checks."""', '"""New pinned-key source-only staging or one separately reviewed SYNTHETIC63 invocation."""')
    ast.parse(source)
    destination = HERE / 'callback-symbol-synthetic-transport-v1-2026-10-18.py'
    with destination.open('x') as output:
        output.write(source)
    assert destination.read_text() == source
    print(destination.name, len(source.encode()), hashlib.sha256(source.encode()).hexdigest())


if __name__ == '__main__':
    main()
