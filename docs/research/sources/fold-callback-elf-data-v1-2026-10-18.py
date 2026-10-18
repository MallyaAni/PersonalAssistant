"""Independent byte-field reconstruction of the narrow ELF DATA schema.

This control never imports the primary decoder. It uses explicit byte widths,
signed conversion and cursor advancement rather than struct formats.
"""
from hashlib import sha256


# Reject a failed predicate with the same public refusal category as the primary decoder.
def require(ok, label):
    if not ok:
        raise ValueError(label)


# Authenticate an entire bounded byte interval without interpreting it as native code.
def extent(data, offset, count, ledger):
    require(type(offset) is int and type(count) is int and offset >= 0
        and offset <= len(data) and count >= 0 and count <= len(data) - offset, 'ELF_FILE_SPAN')
    ledger[0] += count
    require(ledger[0] <= 16777216, 'ELF_HASH_WORK_DOMAIN_BOUND')
    return {'offset': str(offset), 'bytes': str(count),
        'sha256': sha256(data[offset:offset + count]).hexdigest()}


# Decode named integer fields in order using an independent width-and-signedness description.
def fields_at(data, offset, widths, ledger):
    total = sum(width for name, width, signed in widths)
    extent(data, offset, total, ledger)
    cursor = offset
    values = {}
    for name, width, signed in widths:
        values[name] = int.from_bytes(data[cursor:cursor + width], 'little', signed=signed)
        cursor += width
    return values, data[offset:cursor].hex()


# Find a terminating zero with an explicit bounded cursor and preserve arbitrary string bytes.
def bytes_name(data, start, count, number, ledger):
    extent(data, start, count, ledger)
    require(0 <= number < count, 'ELF_STRING_OFFSET')
    cursor = start + number
    while cursor < start + count and data[cursor] != 0:
        cursor += 1
    require(cursor < start + count, 'ELF_STRING_NUL')
    require(cursor - start - number <= 4096, 'ELF_STRING_DOMAIN_BOUND')
    return {'table_index': str(number), 'bytes': str(cursor - start - number),
        'hex': data[start + number:cursor].hex()}


# Independently reconstruct all records and string declarations for the explicit supported domain.
def reconstruct(data):
    require(__debug__ and type(data) is bytes and 64 <= len(data) <= 262144, 'ELF_INPUT_DOMAIN')
    require(data[0:7] == bytes((127, 69, 76, 70, 2, 1, 1)), 'ELF64_LE_CURRENT_ONLY')
    ledger = [len(data)]  # Charge the complete-input digest before decoding any records.
    eh, _ = fields_at(data, 16, (
        ('type', 2, False), ('machine', 2, False), ('version', 4, False),
        ('entry', 8, False), ('phoff', 8, False), ('shoff', 8, False), ('flags', 4, False),
        ('ehsize', 2, False), ('phentsize', 2, False), ('phnum', 2, False),
        ('shentsize', 2, False), ('shnum', 2, False), ('shstrndx', 2, False)), ledger)
    require(eh['type'] == 3 and eh['version'] == 1 and eh['ehsize'] == 64, 'ELF_DYN_HEADER_DOMAIN')
    require(eh['phnum'] != 65535 and eh['shstrndx'] != 65535
        and not (eh['shoff'] != 0 and eh['shnum'] == 0), 'ELF_EXTENDED_NUMBERING_UNSUPPORTED')
    require(eh['phnum'] > 0 and eh['phnum'] < 65535 and eh['shnum'] > 0
        and eh['shnum'] < 65280 and eh['shstrndx'] > 0
        and eh['shstrndx'] < eh['shnum'], 'ELF_REQUIRED_TABLE_DOMAIN')
    require(eh['phentsize'] == 56 and eh['shentsize'] == 64, 'ELF_ENTRY_WIDTH')
    require(eh['phoff'] >= 64 and eh['shoff'] >= 64, 'ELF_TABLE_OFFSET_DOMAIN')
    ph_extent = extent(data, eh['phoff'], eh['phnum'] * 56, ledger)
    sh_extent = extent(data, eh['shoff'], eh['shnum'] * 64, ledger)
    phs = []
    ph_out = []
    previous = -1
    for number in range(eh['phnum']):
        address = eh['phoff'] + 56 * number
        ph, encoded = fields_at(data, address, (
            ('type', 4, False), ('flags', 4, False), ('offset', 8, False),
            ('vaddr', 8, False), ('paddr', 8, False), ('filesz', 8, False),
            ('memsz', 8, False), ('align', 8, False)), ledger)
        file_part = None
        if ph['type'] != 0:
            file_part = extent(data, ph['offset'], ph['filesz'], ledger)
        if ph['type'] == 1:
            require(ph['filesz'] <= ph['memsz'] and ph['vaddr'] >= previous
                and ph['vaddr'] + ph['memsz'] <= 18446744073709551615, 'ELF_LOAD_RANGE')
            alignment = ph['align']
            power = alignment > 0 and alignment.bit_count() == 1
            require(alignment in (0, 1) or (power and
                (ph['vaddr'] - ph['offset']) % alignment == 0), 'ELF_LOAD_ALIGNMENT')
            previous = ph['vaddr']
        phs.append(ph)
        ph_out.append({'index': number, 'header_offset': str(address), 'raw_hex': encoded,
            'fields': {name: str(value) for name, value in ph.items()}, 'file_payload': file_part})
    shs = []
    sh_out = []
    for number in range(eh['shnum']):
        address = eh['shoff'] + 64 * number
        sh, encoded = fields_at(data, address, (
            ('name', 4, False), ('type', 4, False), ('flags', 8, False),
            ('addr', 8, False), ('offset', 8, False), ('size', 8, False),
            ('link', 4, False), ('info', 4, False), ('addralign', 8, False), ('entsize', 8, False)), ledger)
        file_part = None
        if sh['type'] != 0 and sh['type'] != 8:
            file_part = extent(data, sh['offset'], sh['size'], ledger)
        if sh['type'] != 0:
            alignment = sh['addralign']
            require(alignment in (0, 1) or (alignment > 0 and alignment.bit_count() == 1),
                'ELF_SECTION_ALIGNMENT')
        shs.append(sh)
        sh_out.append({'index': number, 'header_offset': str(address), 'raw_hex': encoded,
            'fields': {name: str(value) for name, value in sh.items()}, 'file_payload': file_part})
    first = shs[0]
    require(first['type'] == 0 and first['size'] == 0 and first['link'] == 0
        and first['info'] == 0, 'ELF_SECTION_ZERO_DOMAIN')
    names = shs[eh['shstrndx']]
    require(names['type'] == 3 and names['size'] > 0, 'ELF_SECTION_STRING_TABLE')
    extent(data, names['offset'], names['size'], ledger)
    require(data[names['offset']] == 0 and data[names['offset'] + names['size'] - 1] == 0,
        'ELF_SECTION_STRING_EDGES')
    for number in range(len(shs)):
        sh_out[number]['name'] = bytes_name(data, names['offset'], names['size'], shs[number]['name'], ledger)
    candidates = [number for number in range(len(phs)) if phs[number]['type'] == 2]
    require(len(candidates) == 1, 'ELF_SINGLE_DYNAMIC_DOMAIN')
    dyn_number = candidates[0]
    dyn = phs[dyn_number]
    require(dyn['filesz'] > 0 and dyn['filesz'] % 16 == 0, 'ELF_DYNAMIC_WIDTH')
    dyn_extent = extent(data, dyn['offset'], dyn['filesz'], ledger)
    dyn_out = []
    usable = []
    has_end = False
    for number in range(dyn['filesz'] // 16):
        offset = dyn['offset'] + number * 16
        slot, encoded = fields_at(data, offset, (('tag', 8, True), ('value', 8, False)), ledger)
        enabled = not has_end
        dyn_out.append({'index': number, 'header_offset': str(offset), 'raw_hex': encoded,
            'tag': str(slot['tag']), 'value': str(slot['value']), 'active_through_first_NULL': enabled})
        if enabled and slot['tag'] != 0:
            usable.append((number, slot['tag'], slot['value']))
        if slot['tag'] == 0:
            has_end = True
    require(has_end, 'ELF_DYNAMIC_TERMINATOR')
    pointers = [item[2] for item in usable if item[1] == 5]
    lengths = [item[2] for item in usable if item[1] == 10]
    require(len(pointers) == 1 and len(lengths) == 1 and lengths[0] > 0, 'ELF_DYNAMIC_STRING_SCALARS')
    pointer = pointers[0]
    length = lengths[0]
    require(pointer + length <= 18446744073709551615, 'ELF_VADDR_OVERFLOW')
    matches = []
    for number, ph in enumerate(phs):
        if ph['type'] != 1:
            continue
        delta = pointer - ph['vaddr']
        if delta >= 0 and delta <= ph['filesz'] and length <= ph['filesz'] - delta:
            matches.append((number, ph['offset'] + delta))
    require(len(matches) == 1, 'ELF_DYNAMIC_STRING_MAPPING')
    load_number, string_start = matches[0]
    string_extent = extent(data, string_start, length, ledger)
    require(data[string_start] == 0 and data[string_start + length - 1] == 0, 'ELF_DYNAMIC_STRING_EDGES')
    dyn_sections = [sh for sh in shs if sh['type'] == 6]
    require(len(dyn_sections) == 1, 'ELF_SINGLE_DYNAMIC_SECTION_DOMAIN')
    ds = dyn_sections[0]
    require(ds['offset'] == dyn['offset'] and ds['size'] == dyn['filesz']
        and ds['entsize'] == 16 and ds['link'] >= 0 and ds['link'] < len(shs), 'ELF_DYNAMIC_SECTION_BINDING')
    ls = shs[ds['link']]
    require(ls['type'] == 3 and ls['offset'] == string_start and ls['size'] == length,
        'ELF_DYNAMIC_STRING_SECTION_BINDING')
    strings = []
    for number, tag, value in usable:
        if tag == 1 or tag == 14 or tag == 15 or tag == 29:
            strings.append({'slot_index': number, 'tag': str(tag),
                'string': bytes_name(data, string_start, length, value, ledger)})
    return {'schema': 'callback-elf64-le-data/1',
        'domain': 'ELF64_LE_CURRENT_ET_DYN_STANDARD_NONEXTENDED_HEADERS_ONE_DYNAMIC_WITH_SECTION_NAMES',
        'input': {'bytes': len(data), 'sha256': sha256(data).hexdigest()},
        'ident_hex': data[:16].hex(), 'elf_header_raw_hex': data[:64].hex(),
        'header': {name: str(value) for name, value in eh.items()},
        'program_table_span': ph_extent, 'section_table_span': sh_extent,
        'programs': ph_out, 'sections': sh_out, 'dynamic_program_index': dyn_number,
        'dynamic_span': dyn_extent, 'dynamic_slots': dyn_out,
        'dynamic_strings_span': string_extent, 'dynamic_strings_PT_LOAD_index': load_number,
        'dynamic_string_declarations': strings,
        'complete_ELF_conformance_or_runtime_dependency_resolution': False,
        'native_loading_execution_or_model_RAM_admission': False}
