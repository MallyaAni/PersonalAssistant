"""Prepare a new fixed-path stopped-source census; never run its remote helpers."""

import ast
import hashlib
import json
from pathlib import Path

RESEARCH = Path(__file__).resolve().parents[1]
SOURCES = RESEARCH / 'sources'


# Replace one declared whole-text delta rather than accepting silent source drift.
def once(text, old, new):
    assert text.count(old) == 1, old[:100]
    return text.replace(old, new, 1)


# Replace one top-level literal assignment while preserving all other source bytes.
def assignment(text, name, expression):
    tree = ast.parse(text)
    node = next(node for node in tree.body if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == name for target in node.targets))
    lines = text.splitlines(keepends=True)
    return ''.join(lines[:node.lineno - 1]) + name + ' = ' + expression + '\n' + ''.join(lines[node.end_lineno:])


# Copy reviewed operational code with only new paths, pins, deadlines and identities.
def main():
    seam_raw = (RESEARCH / 'original-loader-package-native-seams-v1-2026-10-18.json').read_bytes()
    assert hashlib.sha256(seam_raw).hexdigest() == 'ada07c95284817b7d918b01b8024c1d828c65fc6f129de1a6c69edcdb178398e'
    paths = tuple('/usr/local/lib/python3.12/site-packages/' + path for path in json.loads(seam_raw)['bounded_next_source_reads']['candidate_new_text_paths'])
    assert len(paths) == len(set(paths)) == 15
    old_raw = (SOURCES / 'capacity-stopped-package-source-census-v1-2026-10-18.py').read_bytes()
    assert hashlib.sha256(old_raw).hexdigest() == '8bcecaf2cd1765e698465758f1959e59b022091f2df5b09e6636c1630a3ad515'
    old = old_raw.decode()
    old_paths = ast.literal_eval(next(node.value for node in ast.parse(old).body if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == 'PATHS' for target in node.targets)))
    assert not set(paths) & set(old_paths)
    text = assignment(old, 'PATHS', repr(paths))
    text = assignment(text, 'KNOWN', '{}')
    text = once(text, 'capacity-stopped-package-source-census-20261018-v1', 'capacity-native-package-text-census-20261018-v1')
    text = once(text, "['collect-stopped-sources']", "['collect-new-native-package-texts']")
    text = once(text, 'signal.alarm(50)', 'signal.alarm(95)')
    text = once(text, 'time.monotonic() + 45', 'time.monotonic() + 90')
    text = once(text, "'stopped-n2-package-source-census/1'", "'stopped-n2-native-package-text-census/1'")
    helper = SOURCES / 'capacity-native-package-text-census-v1-2026-10-18.py'
    ast.parse(text)
    if helper.exists():
        assert helper.read_bytes() == text.encode()
    else:
        with helper.open('xb') as output:
            output.write(text.encode())
    transport_raw = (SOURCES / 'capacity-stopped-package-source-transport-v1-2026-10-18.py').read_bytes()
    assert hashlib.sha256(transport_raw).hexdigest() == '0c84e4b1f89815a7ca085c07695386824802b9c742c20f6df7152d4312b4e6d2'
    transport = transport_raw.decode()
    transport = transport.replace('capacity-stopped-package-source', 'capacity-native-package-text')
    transport = transport.replace('8bcecaf2cd1765e698465758f1959e59b022091f2df5b09e6636c1630a3ad515', hashlib.sha256(text.encode()).hexdigest())
    transport = transport.replace('12911', str(len(text.encode())))
    transport = once(transport, "'collect-stopped-sources'", "'collect-new-native-package-texts'")
    transport = once(transport, 'timeout=70', 'timeout=120')
    target = SOURCES / 'capacity-native-package-text-transport-v1-2026-10-18.py'
    ast.parse(transport)
    with target.open('xb') as output:
        output.write(transport.encode())
    print(json.dumps({path.name: {'sha256': hashlib.sha256(path.read_bytes()).hexdigest(), 'bytes': path.stat().st_size} for path in (helper, target)}, sort_keys=True))


if __name__ == '__main__':
    main()
