"""New finite SYNTHETIC ELF decoder boundary checks, never a native-file or loader test.

Only the two reviewed operational decoders are imported. Fixture bytes are built
here; no retained callback, package, Docker, account or market source is opened.
"""
import hashlib
import json
import pathlib
import resource
import signal
import struct
import time
import types

ROOT = pathlib.Path(__file__).resolve().parent
PRIMARY = 'parse-callback-elf-data-v1-2026-10-18.py'
INDEPENDENT = 'fold-callback-elf-data-v1-2026-10-18.py'
PINS = {
    PRIMARY: 'e5c8040315f3b471a4d35d2c90a82778a78954659d4b66e494d5b18abdf9edaf',
    INDEPENDENT: 'f302196006bc47e3dd7c1a31aa9477d5119e6c18ac0cad015aa5efb302a34dc1',
}
MAX64 = (1 << 64) - 1


# Terminate this owned synthetic control when its whole-process wall deadline expires.
def expired(signum, frame):
    raise TimeoutError('SYNTHETIC_ELF_WALL_BOUND')


# Authenticate a bounded reviewed decoder as operational source before importing its functions.
def load_control(name, module_name):
    path = ROOT / name
    source = path.read_bytes()
    if len(source) > 262144 or hashlib.sha256(source).hexdigest() != PINS.get(name):
        raise ValueError('DECODER_SOURCE_PIN')
    module = types.ModuleType(module_name)
    exec(compile(source, str(path), 'exec', dont_inherit=True), module.__dict__)
    return module


# Construct a tiny ELF-shaped DATA fixture with independently chosen known table positions and values.
def fixture():
    raw = bytearray(2048)
    raw[:16] = bytes((127, 69, 76, 70, 2, 1, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0))
    struct.pack_into('<HHIQQQIHHHHHH', raw, 16,
        3, 183, 1, 0, 64, 1536, 0, 64, 56, 3, 64, 5, 1)
    struct.pack_into('<IIQQQQQQ', raw, 64, 1, 4, 0, 65536, 65536, 2048, 4096, 4096)
    struct.pack_into('<IIQQQQQQ', raw, 120, 2, 6, 256, 65792, 65792, 128, 128, 8)
    struct.pack_into('<IIQQQQQQ', raw, 176, 0, 0, MAX64, MAX64, MAX64, MAX64, MAX64, MAX64)
    slots = ((5, 66048), (10, 64), (1, 1), (1, 9), (-9, MAX64),
        (0, MAX64), (1, MAX64), (29, MAX64))
    for index, (tag, value) in enumerate(slots):
        struct.pack_into('<qQ', raw, 256 + 16 * index, tag, value)
    dynstrings = b'\0libA.so\0\xff.so\0self.so\0\0'
    names = b'\0.shstrtab\0.dynstr\0.dynamic\0.bss\0\0\0'
    raw[512:512 + len(dynstrings)] = dynstrings
    raw[640:640 + len(names)] = names
    rows = ((0, 0, MAX64, MAX64, MAX64, 0, 0, 0, MAX64, MAX64),
        (1, 3, 0, 0, 640, 64, 0, 0, 1, 0),
        (11, 3, 2, 66048, 512, 64, 0, 0, 1, 0),
        (19, 6, 3, 65792, 256, 128, 2, 0, 8, 16),
        (28, 8, 3, 69632, MAX64, MAX64, 0, 0, 16, 0))
    for index, values in enumerate(rows):
        struct.pack_into('<IIQQQQIIQQ', raw, 1536 + 64 * index, *values)
    if len(raw) != 2048:
        raise ValueError('FIXTURE_SLICE_WIDTH')
    return bytes(raw)


# Change one exact little-endian field of a new immutable synthetic input.
def field(raw, offset, value, width, signed=False):
    changed = bytearray(raw)
    changed[offset:offset + width] = value.to_bytes(width, 'little', signed=signed)
    return bytes(changed)


# Require a property without removable assertion statements in the operational test driver.
def check(ok, reason):
    if not ok:
        raise AssertionError(reason)


# Exercise known positive values, complete raw preservation, and narrowly targeted refusal boundaries.
def main():
    check(__debug__, 'OPTIMIZED_CONTROL_REFUSED')
    resource.setrlimit(resource.RLIMIT_AS, (512 * 1024 * 1024, 512 * 1024 * 1024))
    resource.setrlimit(resource.RLIMIT_CPU, (10, 10))
    resource.setrlimit(resource.RLIMIT_FSIZE, (262144, 262144))
    signal.signal(signal.SIGALRM, expired)
    signal.alarm(15)
    started = time.monotonic()
    primary = load_control(PRIMARY, 'elf_primary_control')
    independent = load_control(INDEPENDENT, 'elf_independent_control')
    base = fixture()
    one = primary.parse(base)
    two = independent.reconstruct(base)
    check(one == two, 'FULL_SYNTHETIC_RECORD_FOLD')
    check(one['header']['machine'] == '183' and one['input']['bytes'] == 2048, 'KNOWN_HEADER_VALUES')
    check(len(one['programs']) == 3 and len(one['sections']) == 5
        and len(one['dynamic_slots']) == 8, 'COMPLETE_RECORD_COUNTS')
    check([r['string']['hex'] for r in one['dynamic_string_declarations']]
        == [b'libA.so'.hex(), b'\xff.so'.hex()], 'ORDERED_ARBITRARY_STRING_BYTES')
    check(one['dynamic_slots'][4]['tag'] == '-9'
        and one['dynamic_slots'][5]['value'] == str(MAX64)
        and [r['active_through_first_NULL'] for r in one['dynamic_slots']]
        == [True, True, True, True, True, True, False, False], 'TERMINATOR_AND_SIGNED_RAW_PRESERVATION')
    check(one['programs'][2]['file_payload'] is None
        and one['sections'][0]['file_payload'] is None
        and one['sections'][4]['file_payload'] is None
        and one['sections'][4]['fields']['size'] == str(MAX64), 'NONFILEBACKED_NO_ALLOCATION')
    check(one['programs'][0]['file_payload']['sha256'] == hashlib.sha256(base).hexdigest()
        and one['dynamic_strings_span']['offset'] == '512', 'KNOWN_FULL_SPAN_AUTHENTICATION')
    outcomes = [{'name': 'complete_known_SYNTHETIC_records', 'result': 'PASS', 'scope': 'SYNTHETIC_DATA_ONLY'}]
    positives = (
        ('repeated_needed_kept', field(base, 312, 1, 8)),
        ('soname_string_kept', field(field(base, 320, 14, 8, True), 328, 14, 8)),
        ('substring_string_index', field(base, 296, 4, 8)),
        ('empty_needed_string', field(base, 296, 0, 8)),
    )
    for name, data in positives:
        result = primary.parse(data)
        check(result == independent.reconstruct(data), name + '_FULL_FOLD')
        if name == 'repeated_needed_kept':
            check([r['string']['hex'] for r in result['dynamic_string_declarations']]
                == [b'libA.so'.hex(), b'libA.so'.hex()], name)
        if name == 'soname_string_kept':
            check(result['dynamic_string_declarations'][-1]['tag'] == '14'
                and result['dynamic_string_declarations'][-1]['string']['hex'] == b'self.so'.hex(), name)
        if name == 'substring_string_index':
            check(result['dynamic_string_declarations'][0]['string']['hex'] == b'A.so'.hex(), name)
        if name == 'empty_needed_string':
            check(result['dynamic_string_declarations'][0]['string']['hex'] == '', name)
        outcomes.append({'name': name, 'result': 'PASS', 'scope': 'SYNTHETIC_DATA_ONLY'})
    ambiguous = field(field(field(field(field(field(field(base,
        176, 1, 4), 184, 0, 8), 192, 65536, 8), 200, 65536, 8),
        208, 2048, 8), 216, 4096, 8), 224, 4096, 8)
    no_null = field(field(field(base, 336, -8, 8, True), 352, -7, 8, True), 368, -6, 8, True)
    high_work = bytearray(262144)
    high_work[:len(base)] = base
    struct.pack_into('<H', high_work, 56, 100)
    for index in range(100):
        struct.pack_into('<IIQQQQQQ', high_work, 64 + index * 56,
            1, 4, 0, 65536, 65536, 262144, 262144, 4096)
    negatives = (
        ('short_header', base[:63], 'ELF_INPUT_DOMAIN'),
        ('oversized_body', bytes(262145), 'ELF_INPUT_DOMAIN'),
        ('class32', field(base, 4, 1, 1), 'ELF64_LE_CURRENT_ONLY'),
        ('big_endian', field(base, 5, 2, 1), 'ELF64_LE_CURRENT_ONLY'),
        ('header_version', field(base, 20, 2, 4), 'ELF_DYN_HEADER_DOMAIN'),
        ('extended_phnum', field(base, 56, 65535, 2), 'ELF_EXTENDED_NUMBERING_UNSUPPORTED'),
        ('extended_shnum', field(base, 60, 0, 2), 'ELF_EXTENDED_NUMBERING_UNSUPPORTED'),
        ('extended_shstr', field(base, 62, 65535, 2), 'ELF_EXTENDED_NUMBERING_UNSUPPORTED'),
        ('absent_sections', field(field(base, 40, 0, 8), 60, 0, 2), 'ELF_REQUIRED_TABLE_DOMAIN'),
        ('bad_entry_width', field(base, 54, 55, 2), 'ELF_ENTRY_WIDTH'),
        ('table_over_header', field(base, 32, 0, 8), 'ELF_TABLE_OFFSET_DOMAIN'),
        ('table_over_file', field(base, 40, MAX64, 8), 'ELF_FILE_SPAN'),
        ('payload_over_file', field(base, 128, MAX64, 8), 'ELF_FILE_SPAN'),
        ('load_filesz_gt_memsz', field(base, 104, 2047, 8), 'ELF_LOAD_RANGE'),
        ('load_vaddr_wrap', field(base, 80, MAX64, 8), 'ELF_LOAD_RANGE'),
        ('load_alignment', field(base, 112, 3, 8), 'ELF_LOAD_ALIGNMENT'),
        ('section_alignment', field(base, 1712, 3, 8), 'ELF_SECTION_ALIGNMENT'),
        ('section_name_outside', field(base, 1600, 64, 4), 'ELF_STRING_OFFSET'),
        ('section_name_edge', field(base, 703, 1, 1), 'ELF_SECTION_STRING_EDGES'),
        ('no_dynamic_segment', field(base, 120, 0, 4), 'ELF_SINGLE_DYNAMIC_DOMAIN'),
        ('dynamic_partial_record', field(base, 152, 127, 8), 'ELF_DYNAMIC_WIDTH'),
        ('dynamic_without_null', no_null, 'ELF_DYNAMIC_TERMINATOR'),
        ('duplicate_strtab', field(base, 320, 5, 8, True), 'ELF_DYNAMIC_STRING_SCALARS'),
        ('zero_strsz', field(base, 280, 0, 8), 'ELF_DYNAMIC_STRING_SCALARS'),
        ('dynstr_vaddr_wrap', field(base, 264, MAX64, 8), 'ELF_VADDR_OVERFLOW'),
        ('dynstr_memsz_only', field(base, 264, 68536, 8), 'ELF_DYNAMIC_STRING_MAPPING'),
        ('ambiguous_load', ambiguous, 'ELF_DYNAMIC_STRING_MAPPING'),
        ('dynstr_edge', field(base, 575, 1, 1), 'ELF_DYNAMIC_STRING_EDGES'),
        ('dynamic_section_mismatch', field(base, 1760, 256, 8), 'ELF_DYNAMIC_SECTION_BINDING'),
        ('dynamic_string_link_mismatch', field(base, 1768, 1, 4), 'ELF_DYNAMIC_STRING_SECTION_BINDING'),
        ('needed_outside_table', field(base, 296, 64, 8), 'ELF_STRING_OFFSET'),
        ('overlapping_payload_hash_work', bytes(high_work), 'ELF_HASH_WORK_DOMAIN_BOUND'),
    )
    for name, data, expected in negatives:
        reasons = []
        for parser in (primary.parse, independent.reconstruct):
            try:
                parser(data)
            except ValueError as error:
                reasons.append(str(error))
            else:
                raise AssertionError(name + '_MISSING_REFUSAL')
        check(reasons == [expected, expected], name + '_FIRST_BOUNDARY_' + repr(reasons))
        outcomes.append({'name': name, 'result': 'EXPECTED_REFUSAL', 'reason': expected,
            'scope': 'SYNTHETIC_DATA_ONLY'})
    signal.alarm(0)
    print(json.dumps({'schema': 'synthetic-callback-elf-checks/1', 'outcomes': outcomes,
        'source_sha256': PINS, 'fixture_bytes': len(base), 'fixture_sha256': hashlib.sha256(base).hexdigest(),
        'elapsed_seconds': time.monotonic() - started, 'ru_maxrss_platform_units': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        'actual_callback_opened': False, 'native_code_loaded': False,
        'actual_ELF_or_runtime_or_model_RAM_acceptance': False}, sort_keys=True))


if __name__ == '__main__':
    main()
