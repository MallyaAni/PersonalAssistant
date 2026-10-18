"""Create pinned bounded transports for new data-only package metadata analysis controls."""
import ast
import hashlib
import json
from pathlib import Path
import sys

SOURCES = Path(__file__).resolve().parent


# Bind one new operational helper to a fresh one-shot SSH transport without executing it.
def main(role):
    assert role in ('primary', 'independent')
    helper_name = ('analyze-package-metadata-records-v1-2026-10-18.py' if role == 'primary'
        else 'verify-package-metadata-records-v1-2026-10-18.py')
    helper = (SOURCES / helper_name).read_bytes()
    ast.parse(helper)
    old = (SOURCES / 'capacity-native-package-text-transport-v1-2026-10-18.py').read_bytes()
    assert hashlib.sha256(old).hexdigest() == '518ded7394ae1b04db85f32b89e15693086f8e184c231ac2b891391d2f749b08'
    label = 'analysis' if role == 'primary' else 'independent'
    text = old.decode()
    changes = {
        'capacity-native-package-text-census-v1-2026-10-18.py': helper_name,
        '296d0e8dd4d58883388a5c8f5b2d5c0b6d09ccfdbf82cb44c060333637bb1428': hashlib.sha256(helper).hexdigest(),
        '13080': str(len(helper)),
        'capacity-native-package-text-transport-20261018-v1': 'capacity-package-metadata-record-' + label + '-transport-20261018-v1',
        'capacity-native-package-text-census-tools-20261018-v1': 'capacity-package-metadata-record-' + label + '-tools-20261018-v1',
        'collect-new-native-package-texts': 'parse-copied-package-metadata' if role == 'primary' else 'verify-copied-package-metadata',
        'timeout=120': 'timeout=70'
    }
    for old_text, new_text in changes.items():
        assert old_text in text
        text = text.replace(old_text, new_text)
    ast.parse(text)
    target = SOURCES / ('package-metadata-record-' + label + '-transport-v1-2026-10-18.py')
    with target.open('xb') as stream:
        stream.write(text.encode())
    assert target.read_bytes() == text.encode()
    print(json.dumps({'helper_sha256': hashlib.sha256(helper).hexdigest(), 'helper_bytes': len(helper),
        'transport_sha256': hashlib.sha256(target.read_bytes()).hexdigest(), 'transport_bytes': target.stat().st_size}))


if __name__ == '__main__':
    assert len(sys.argv) == 2
    main(sys.argv[1])
