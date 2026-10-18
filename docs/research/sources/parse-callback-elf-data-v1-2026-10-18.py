"""Pure ELF64 little-endian DATA parser; no file IO, imports of payloads or loader calls."""
import hashlib
import struct

CAP = 262144
MAX64 = (1 << 64) - 1
EH_NAMES = ('type', 'machine', 'version', 'entry', 'phoff', 'shoff', 'flags',
    'ehsize', 'phentsize', 'phnum', 'shentsize', 'shnum', 'shstrndx')
PH_NAMES = ('type', 'flags', 'offset', 'vaddr', 'paddr', 'filesz', 'memsz', 'align')
SH_NAMES = ('name', 'type', 'flags', 'addr', 'offset', 'size', 'link', 'info', 'addralign', 'entsize')


# Refuse unsupported or malformed data without relying on removable assertion statements.
def need(condition, reason):
    if not condition:
        raise ValueError(reason)


# Bound a complete file span and retain its exact SHA without interpreting its contents.
def span(raw, start, size, work):
    need(type(start) is int and type(size) is int and 0 <= start <= len(raw)
        and 0 <= size <= len(raw) - start, 'ELF_FILE_SPAN')
    work[0] += size
    need(work[0] <= 16 * 1024 * 1024, 'ELF_HASH_WORK_DOMAIN_BOUND')
    return {'offset': str(start), 'bytes': str(size),
        'sha256': hashlib.sha256(raw[start:start + size]).hexdigest()}


# Decode one complete standard-width record and preserve its uninterpreted raw bytes.
def record(raw, offset, fmt, names, work):
    width = struct.calcsize(fmt)
    span(raw, offset, width, work)
    values = dict(zip(names, struct.unpack_from(fmt, raw, offset), strict=True))
    return values, raw[offset:offset + width].hex()


# Read an arbitrary NUL-terminated string as bytes within its complete validated string table.
def string(raw, table_offset, table_size, index, work):
    span(raw, table_offset, table_size, work)
    need(0 <= index < table_size, 'ELF_STRING_OFFSET')
    end = raw.find(b'\0', table_offset + index, table_offset + table_size)
    need(end >= 0, 'ELF_STRING_NUL')
    need(end - table_offset - index <= 4096, 'ELF_STRING_DOMAIN_BOUND')
    body = raw[table_offset + index:end]
    return {'table_index': str(index), 'bytes': str(len(body)), 'hex': body.hex()}


# Reconstruct complete bounded headers, sections and dynamic declarations for the stated narrow domain.
def parse(raw):
    need(__debug__ and type(raw) is bytes and 64 <= len(raw) <= CAP, 'ELF_INPUT_DOMAIN')
    need(raw[:4] == b'\x7fELF' and raw[4:7] == b'\x02\x01\x01', 'ELF64_LE_CURRENT_ONLY')
    work = [len(raw)]  # Include the final complete-input hash in the same work limit.
    header, _ = record(raw, 16, '<HHIQQQIHHHHHH', EH_NAMES, work)
    need(header['type'] == 3 and header['version'] == 1 and header['ehsize'] == 64, 'ELF_DYN_HEADER_DOMAIN')
    need(header['phnum'] != 0xffff and header['shstrndx'] != 0xffff
        and not (header['shoff'] and header['shnum'] == 0), 'ELF_EXTENDED_NUMBERING_UNSUPPORTED')
    need(0 < header['phnum'] < 0xffff and 0 < header['shnum'] < 0xff00
        and 0 < header['shstrndx'] < header['shnum'], 'ELF_REQUIRED_TABLE_DOMAIN')
    need(header['phentsize'] == 56 and header['shentsize'] == 64, 'ELF_ENTRY_WIDTH')
    need(header['phoff'] >= 64 and header['shoff'] >= 64, 'ELF_TABLE_OFFSET_DOMAIN')
    ph_span = span(raw, header['phoff'], header['phnum'] * 56, work)
    sh_span = span(raw, header['shoff'], header['shnum'] * 64, work)
    programs, pvalues = [], []
    last_load = -1
    for index in range(header['phnum']):
        offset = header['phoff'] + index * 56
        fields, raw_hex = record(raw, offset, '<IIQQQQQQ', PH_NAMES, work)
        payload = None if fields['type'] == 0 else span(raw, fields['offset'], fields['filesz'], work)
        if fields['type'] == 1:
            need(fields['filesz'] <= fields['memsz']
                and fields['vaddr'] >= last_load
                and fields['memsz'] <= MAX64 - fields['vaddr'], 'ELF_LOAD_RANGE')
            align = fields['align']
            need(align in (0, 1) or (align & (align - 1) == 0
                and fields['vaddr'] % align == fields['offset'] % align), 'ELF_LOAD_ALIGNMENT')
            last_load = fields['vaddr']
        pvalues.append(fields)
        programs.append({'index': index, 'header_offset': str(offset), 'raw_hex': raw_hex,
            'fields': {key: str(value) for key, value in fields.items()}, 'file_payload': payload})
    sections, svalues = [], []
    for index in range(header['shnum']):
        offset = header['shoff'] + index * 64
        fields, raw_hex = record(raw, offset, '<IIQQQQIIQQ', SH_NAMES, work)
        payload = None if fields['type'] in (0, 8) else span(raw, fields['offset'], fields['size'], work)
        if fields['type'] != 0:
            align = fields['addralign']
            need(align in (0, 1) or align & (align - 1) == 0, 'ELF_SECTION_ALIGNMENT')
        svalues.append(fields)
        sections.append({'index': index, 'header_offset': str(offset), 'raw_hex': raw_hex,
            'fields': {key: str(value) for key, value in fields.items()}, 'file_payload': payload})
    need(svalues[0]['type'] == 0 and svalues[0]['size'] == 0
        and svalues[0]['link'] == 0 and svalues[0]['info'] == 0, 'ELF_SECTION_ZERO_DOMAIN')
    shstrings = svalues[header['shstrndx']]
    need(shstrings['type'] == 3 and shstrings['size'] > 0, 'ELF_SECTION_STRING_TABLE')
    span(raw, shstrings['offset'], shstrings['size'], work)
    need(raw[shstrings['offset']] == raw[shstrings['offset'] + shstrings['size'] - 1] == 0, 'ELF_SECTION_STRING_EDGES')
    for row, fields in zip(sections, svalues, strict=True):
        row['name'] = string(raw, shstrings['offset'], shstrings['size'], fields['name'], work)
    dynamic_segments = [(i, p) for i, p in enumerate(pvalues) if p['type'] == 2]
    need(len(dynamic_segments) == 1, 'ELF_SINGLE_DYNAMIC_DOMAIN')
    dynamic_index, dynamic = dynamic_segments[0]
    need(dynamic['filesz'] > 0 and dynamic['filesz'] % 16 == 0, 'ELF_DYNAMIC_WIDTH')
    dynamic_span = span(raw, dynamic['offset'], dynamic['filesz'], work)
    slots, active, ended = [], [], False
    for index in range(dynamic['filesz'] // 16):
        offset = dynamic['offset'] + index * 16
        fields, raw_hex = record(raw, offset, '<qQ', ('tag', 'value'), work)
        is_active = not ended
        slots.append({'index': index, 'header_offset': str(offset), 'raw_hex': raw_hex,
            'tag': str(fields['tag']), 'value': str(fields['value']), 'active_through_first_NULL': is_active})
        if is_active and fields['tag'] != 0:
            active.append((index, fields['tag'], fields['value']))
        if fields['tag'] == 0:
            ended = True
    need(ended, 'ELF_DYNAMIC_TERMINATOR')
    addresses = [value for i, tag, value in active if tag == 5]
    sizes = [value for i, tag, value in active if tag == 10]
    need(len(addresses) == len(sizes) == 1 and sizes[0] > 0, 'ELF_DYNAMIC_STRING_SCALARS')
    address, size = addresses[0], sizes[0]
    need(size <= MAX64 - address, 'ELF_VADDR_OVERFLOW')
    maps = [(i, p['offset'] + address - p['vaddr']) for i, p in enumerate(pvalues)
        if p['type'] == 1 and p['vaddr'] <= address and address - p['vaddr'] <= p['filesz']
        and size <= p['filesz'] - (address - p['vaddr'])]
    need(len(maps) == 1, 'ELF_DYNAMIC_STRING_MAPPING')
    map_index, file_offset = maps[0]
    dynstr_span = span(raw, file_offset, size, work)
    need(raw[file_offset] == raw[file_offset + size - 1] == 0, 'ELF_DYNAMIC_STRING_EDGES')
    dynamic_sections = [s for s in svalues if s['type'] == 6]
    need(len(dynamic_sections) == 1, 'ELF_SINGLE_DYNAMIC_SECTION_DOMAIN')
    dynamic_section = dynamic_sections[0]
    need(dynamic_section['offset'] == dynamic['offset'] and dynamic_section['size'] == dynamic['filesz']
        and dynamic_section['entsize'] == 16 and 0 <= dynamic_section['link'] < len(svalues), 'ELF_DYNAMIC_SECTION_BINDING')
    linked = svalues[dynamic_section['link']]
    need(linked['type'] == 3 and linked['offset'] == file_offset and linked['size'] == size, 'ELF_DYNAMIC_STRING_SECTION_BINDING')
    declarations = []
    for i, tag, value in active:
        if tag in (1, 14, 15, 29):
            declarations.append({'slot_index': i, 'tag': str(tag),
                'string': string(raw, file_offset, size, value, work)})
    return {'schema': 'callback-elf64-le-data/1',
        'domain': 'ELF64_LE_CURRENT_ET_DYN_STANDARD_NONEXTENDED_HEADERS_ONE_DYNAMIC_WITH_SECTION_NAMES',
        'input': {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()},
        'ident_hex': raw[:16].hex(), 'elf_header_raw_hex': raw[:64].hex(),
        'header': {key: str(value) for key, value in header.items()},
        'program_table_span': ph_span, 'section_table_span': sh_span,
        'programs': programs, 'sections': sections, 'dynamic_program_index': dynamic_index,
        'dynamic_span': dynamic_span, 'dynamic_slots': slots,
        'dynamic_strings_span': dynstr_span, 'dynamic_strings_PT_LOAD_index': map_index,
        'dynamic_string_declarations': declarations,
        'complete_ELF_conformance_or_runtime_dependency_resolution': False,
        'native_loading_execution_or_model_RAM_admission': False}
