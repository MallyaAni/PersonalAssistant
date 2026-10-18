"""Prepare a new two-phase symbol DATA transport builder from authenticated operational source only."""
import ast
import hashlib
from pathlib import Path

HERE = Path(__file__).resolve().parent


# Narrow the old source recipe to new drivers and decoder pins without invoking any preserved job.
def main():
    raw = (HERE / 'prepare-callback-elf-data-transports-v1-2026-10-18.py').read_bytes()
    assert len(raw) == 7155 and hashlib.sha256(raw).hexdigest() == '195a85672e13e3e2c06d2c5707c3fafdf73622153f382848d938547a50f58cff'
    source = raw.decode()
    source = source.replace('callback-elf', 'callback-symbol')
    assert source.count("TEMPLATE = BASE / 'callback-symbol-synthetic-transport-v1-2026-10-18.py'") == 1
    source = source.replace("TEMPLATE = BASE / 'callback-symbol-synthetic-transport-v1-2026-10-18.py'",
        "TEMPLATE = BASE / 'callback-elf-synthetic-transport-v1-2026-10-18.py'")
    replacements = {
        'e5c8040315f3b471a4d35d2c90a82778a78954659d4b66e494d5b18abdf9edaf':
            '6fe24522e57910ed2f9136762ea4f910f46fd6a6a91afe4f55c80b5e8462bd11',
        'f302196006bc47e3dd7c1a31aa9477d5119e6c18ac0cad015aa5efb302a34dc1':
            'a526e85d63313fac8a4de11eb31dc34964ad9eaeed6d93a4a78d25cb5b469127',
        'RETAINED_CALLBACK_ELF_DATA_ONLY': 'RETAINED_CALLBACK_SYMBOL_DATA_ONLY',
        'retained-callback ELF DATA': 'retained-callback symbol/version DATA',
    }
    for old, new in replacements.items():
        assert source.count(old) == 1
        source = source.replace(old, new)
    ast.parse(source)
    destination = HERE / 'prepare-callback-symbol-data-transports-v1-2026-10-18.py'
    with destination.open('x') as output:
        output.write(source)
    assert destination.read_text() == source
    print(destination.name, len(source.encode()), hashlib.sha256(source.encode()).hexdigest())


if __name__ == '__main__':
    main()
