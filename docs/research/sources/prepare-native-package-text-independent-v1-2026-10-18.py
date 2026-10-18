"""Prepare a separate readback verifier after receiving the exact candidate pin."""

import ast
import hashlib
import json
from pathlib import Path
import sys

SOURCES = Path(__file__).resolve().parent


# Refuse missing or repeated text matches when declaring each verifier delta.
def once(text, old, new):
    assert text.count(old) == 1, old[:100]
    return text.replace(old, new, 1)


# Bind the observed candidate and preserve the reviewed independent fold mechanism.
def main(candidate_sha):
    assert len(candidate_sha) == 64 and all(char in '0123456789abcdef' for char in candidate_sha)
    old_raw = (SOURCES / 'verify-stopped-package-source-census-v1-2026-10-18.py').read_bytes()
    assert hashlib.sha256(old_raw).hexdigest() == '5f7385ef5baa13d64c6775c60bd116ec9dcf24d3b3b984bd848db5a064085eea'
    collector = (SOURCES / 'capacity-native-package-text-census-v1-2026-10-18.py').read_bytes()
    assert hashlib.sha256(collector).hexdigest() == '296d0e8dd4d58883388a5c8f5b2d5c0b6d09ccfdbf82cb44c060333637bb1428'
    tree = ast.parse(collector)
    paths = next(node for node in tree.body if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == 'PATHS' for target in node.targets))
    paths_expression = ast.get_source_segment(collector.decode(), paths)
    text = old_raw.decode()
    old_tree = ast.parse(text)
    old_paths = next(node for node in old_tree.body if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == 'PATHS' for target in node.targets))
    lines = text.splitlines(keepends=True)
    text = ''.join(lines[:old_paths.lineno - 1]) + paths_expression + '\n' + ''.join(lines[old_paths.end_lineno:])
    text = text.replace('capacity-stopped-package-source-census', 'capacity-native-package-text-census')
    text = once(text, '1d74567f0ec18673868461c4f122c02a994acfce1bb31abd426d81c4b01cdebe', candidate_sha)
    text = once(text, "'stopped-n2-package-source-census/1'", "'stopped-n2-native-package-text-census/1'")
    text = once(text, 'len(names) == 78', 'len(names) == 113')
    text = once(text, "    assert inventory['source-00.py.txt']['sha256'] == 'd242aea5fcf6408b1c1f622442f88f68b9526ce1f8bd2890d74a144677c427d9'\n", '')
    text = once(text, "    assert inventory['source-01.py.txt']['sha256'] == '09295a80660f17925ae23765ce8cbd7ff7ceae968d5f2f89349f1cb74c0b9e11'\n", '')
    text = once(text, "    before = json.loads(bodies['inspect-before.stdout'])", "    assert hashlib.sha256(bodies['inspect-before.stdout']).hexdigest() == 'd5265be87b979e83e396e18d1d9d4571cc6e1db5aa09239200004a2809bd90d2'\n    before = json.loads(bodies['inspect-before.stdout'])")
    text = once(text, "'stopped-n2-package-source-census-independent/1'", "'stopped-n2-native-package-text-census-independent/1'")
    text = once(text, 'VERIFIED_TEN_PAIRED_TEXT_SOURCE_COPIES_ONLY_NOT_PACKAGE_RUNTIME_CLOSURE', 'VERIFIED_FIFTEEN_PAIRED_TEXT_SOURCE_COPIES_ONLY_NOT_PACKAGE_RUNTIME_CLOSURE')
    text = once(text, "'source_files': 10, 'full_readback_files': 78", "'source_files': 15, 'full_readback_files': 113")
    text = once(text, 'range(10)', 'range(15)')
    helper = SOURCES / 'verify-native-package-text-census-v1-2026-10-18.py'
    ast.parse(text)
    with helper.open('xb') as output:
        output.write(text.encode())
    old_transport = (SOURCES / 'capacity-stopped-package-source-independent-transport-v1-2026-10-18.py').read_bytes()
    assert hashlib.sha256(old_transport).hexdigest() == '22aa585d4debf80d7c88f18cc6c59eaf11df910b1e067067ad9fa49c58c96e7e'
    transport = old_transport.decode().replace('capacity-stopped-package-source', 'capacity-native-package-text')
    transport = once(transport, 'verify-stopped-package-source-census-v1-2026-10-18.py', helper.name)
    transport = transport.replace('5f7385ef5baa13d64c6775c60bd116ec9dcf24d3b3b984bd848db5a064085eea', hashlib.sha256(text.encode()).hexdigest())
    transport = transport.replace('15537', str(len(text.encode())))
    target = SOURCES / 'capacity-native-package-text-independent-transport-v1-2026-10-18.py'
    ast.parse(transport)
    with target.open('xb') as output:
        output.write(transport.encode())
    print(json.dumps({path.name: {'sha256': hashlib.sha256(path.read_bytes()).hexdigest(), 'bytes': path.stat().st_size} for path in (helper, target)}, sort_keys=True))


if __name__ == '__main__':
    assert len(sys.argv) == 2
    main(sys.argv[1])
