"""Pure selected ELF symbol/version DATA decoding; no IO or native loading."""
import hashlib
import json
import struct

CAP = 262144
WORK = 16777216
ROWS = 8192
SH = ('name', 'type', 'flags', 'addr', 'offset', 'size', 'link', 'info', 'addralign', 'entsize')
SYM = ('name', 'info', 'other', 'shndx', 'value', 'size')
VN = ('version', 'cnt', 'file', 'aux', 'next')
VA = ('hash', 'flags', 'other', 'name', 'next')
KINDS = ('selected_sections', 'symbols', 'versions', 'needs', 'gaps', 'associations')


# Reject unsupported or malformed DATA with a stable finite reason.
def need(condition, reason):
    if not condition:
        raise ValueError(reason)


# Reject duplicate JSON keys before they can replace authenticated record declarations.
def pairs(items):
    result = {}
    for key, value in items:
        need(key not in result, 'SYM_PAGE_DUPLICATE_KEY')
        result[key] = value
    return result


# Hash one bounded complete span after charging every hashed byte to the shared work ledger.
def span(raw, offset, size, work):
    need(type(offset) is int and type(size) is int and 0 <= offset <= len(raw)
        and 0 <= size <= len(raw) - offset, 'SYM_FILE_SPAN')
    work[0] += size
    need(work[0] <= WORK, 'SYM_HASH_WORK_BOUND')
    return {'offset': str(offset), 'bytes': str(size),
        'sha256': hashlib.sha256(raw[offset:offset + size]).hexdigest()}


# Decode one fixed-width record while preserving its complete bytes and charged span hash.
def record(raw, offset, fmt, names, work):
    proof = span(raw, offset, struct.calcsize(fmt), work)
    fields = dict(zip(names, struct.unpack_from(fmt, raw, offset), strict=True))
    return fields, {'offset': str(offset), 'raw_hex': raw[offset:offset + int(proof['bytes'])].hex(), 'span': proof}


# Preserve a linked-table byte string together with its exact terminating-NUL span.
def string(raw, section, table, index, work):
    start, size = table['offset'], table['size']
    need(0 <= index < size, 'SYM_STRING_INDEX')
    end = raw.find(b'\0', start + index, start + min(size, index + 4097))
    need(end >= 0, 'SYM_STRING_NUL_OR_BOUND')
    return {'table_section': section, 'table_index': str(index),
        'bytes': str(end - start - index), 'hex': raw[start + index:end].hex(),
        'span': span(raw, start + index, end - start - index + 1, work)}


# Encode finite canonical DATA with a fixed complete-result bound.
def encoded(value):
    body = json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True,
        allow_nan=False).encode('ascii') + b'\n'
    need(len(body) <= WORK, 'SYM_CANONICAL_BOUND')
    return body


# Decode both complete symbol arrays and version declarations against supplied authenticated section bytes.
def decode(raw, page_raw):
    need(__debug__ and type(raw) is bytes and 64 <= len(raw) <= CAP
        and type(page_raw) is bytes and len(page_raw) <= 65536, 'SYM_INPUT_DOMAIN')
    work = [0]
    input_span = span(raw, 0, len(raw), work)
    page_span = span(page_raw, 0, len(page_raw), work)
    need(raw[:7] == b'\x7fELF\x02\x01\x01', 'SYM_ELF64_LE_CURRENT')
    eh = struct.unpack_from('<HHIQQQIHHHHHH', raw, 16)
    need(eh[0] == 3 and eh[2] == 1 and eh[7] == 64 and eh[10] == 64
        and 0 < eh[11] <= 4096 and eh[5] >= 64, 'SYM_ELF_HEADER_DOMAIN')
    page = json.loads(page_raw, object_pairs_hook=pairs)
    need(type(page) is dict and set(page) == {'schema', 'kind', 'start', 'binary_sha256', 'records'}
        and page['schema'] == 'callback-elf-record-page/1' and page['kind'] == 'sections'
        and type(page['start']) is int and page['start'] == 0
        and page['binary_sha256'] == input_span['sha256'], 'SYM_PAGE_BINDING')
    rows = page['records']
    need(type(rows) is list and len(rows) == eh[11], 'SYM_PAGE_SECTION_COUNT')
    values = []
    for index, row in enumerate(rows):
        need(type(row) is dict and type(row.get('index')) is int and row['index'] == index,
            'SYM_SECTION_INDEX')
        fields, proof = record(raw, eh[5] + index * 64, '<IIQQQQIIQQ', SH, work)
        need(row.get('header_offset') == proof['offset'] and row.get('raw_hex') == proof['raw_hex']
            and row.get('fields') == {key: str(value) for key, value in fields.items()}, 'SYM_SECTION_HEADER_BINDING')
        values.append(fields)
    need(not any(s['type'] in (18, 1879048189) for s in values), 'SYM_EXTENDED_OR_VERDEF_UNSUPPORTED')
    chosen = {}
    for typ in (2, 11, 1879048191, 1879048190):
        indices = [i for i, s in enumerate(values) if s['type'] == typ]
        need(len(indices) == 1, 'SYM_TABLE_SET_DOMAIN')
        chosen[typ] = indices[0]
    dynamic, regular, version, needed = chosen[11], chosen[2], chosen[1879048191], chosen[1879048190]
    linked = {values[dynamic]['link'], values[regular]['link'], values[needed]['link']}
    need(all(0 <= i < len(values) and values[i]['type'] == 3 for i in linked), 'SYM_STRING_LINK')
    need(values[needed]['link'] == values[dynamic]['link'] and values[version]['link'] == dynamic,
        'SYM_VERSION_LINK')
    indices = sorted({dynamic, regular, version, needed} | linked)
    selected = []
    for index in indices:
        fields = values[index]
        proof = span(raw, fields['offset'], fields['size'], work)
        need(rows[index].get('file_payload') == proof, 'SYM_SECTION_PAYLOAD_BINDING')
        selected.append({'index': index, 'fields': rows[index]['fields'],
            'header_span': span(raw, eh[5] + index * 64, 64, work), 'payload_span': proof})
        if index in linked:
            need(fields['size'] > 0 and raw[fields['offset']] == raw[fields['offset'] + fields['size'] - 1] == 0,
                'SYM_STRING_EDGES')
    counts = {}
    for section in sorted((dynamic, regular)):
        table = values[section]
        need(table['entsize'] == 24 and table['size'] > 0 and table['size'] % 24 == 0, 'SYM_SYMBOL_WIDTH')
        count = table['size'] // 24
        need(count <= ROWS and 1 <= table['info'] <= count, 'SYM_SYMBOL_COUNT_OR_INFO')
        counts[section] = count
    base_rows = len(selected) + sum(counts.values()) + 2 * counts[dynamic] + values[needed]['info']
    need(base_rows <= ROWS, 'SYM_RECORD_BOUND')
    symbols = []
    for section in sorted((dynamic, regular)):
        table, count = values[section], counts[section]
        for index in range(count):
            need(len(symbols) < ROWS, 'SYM_RECORD_BOUND')
            fields, proof = record(raw, table['offset'] + index * 24, '<IBBHQQ', SYM, work)
            need(index != 0 or not any(fields.values()), 'SYM_ZERO_SYMBOL')
            need((fields['info'] >> 4 == 0) == (index < table['info']), 'SYM_LOCAL_PARTITION')
            shndx = fields['shndx']
            need(shndx != 65535, 'SYM_XINDEX_UNSUPPORTED')
            need(shndx == 0 or shndx >= 65280 or shndx < len(values), 'SYM_ORDINARY_SECTION_INDEX')
            name = string(raw, table['link'], values[table['link']], fields['name'], work)
            symbols.append(dict(proof, table_section=section, index=index,
                fields={key: str(value) for key, value in fields.items()},
                binding=str(fields['info'] >> 4), symbol_type=str(fields['info'] & 15),
                visibility_low2=str(fields['other'] & 3), visibility_low3=str(fields['other'] & 7),
                section_class='UNDEFINED' if shndx == 0 else 'RESERVED' if shndx >= 65280 else 'ORDINARY', name=name))
    table = values[version]
    need(table['entsize'] == 2 and table['size'] == counts[dynamic] * 2, 'SYM_VERSYM_WIDTH_OR_COUNT')
    versions = []
    for index in range(counts[dynamic]):
        fields, proof = record(raw, table['offset'] + index * 2, '<H', ('value',), work)
        value = fields['value']
        versions.append(dict(proof, section=version, symbol_index=index, raw_value=str(value),
            low15_index=str(value & 32767), high_bit=bool(value & 32768)))
    table = values[needed]
    need(table['entsize'] == 0 and table['size'] >= 16 and 1 <= table['info'] <= ROWS,
        'SYM_VERNEED_DOMAIN')
    occupied, needs, auxiliary_count = [], [], 0
    current = 0
    for index in range(table['info']):
        need(current % 4 == 0 and 0 <= current <= table['size'] - 16, 'SYM_VERSION_RECORD_RANGE')
        need(all(current + 16 <= a or b <= current for a, b in occupied), 'SYM_VERSION_OVERLAP')
        occupied.append((current, current + 16))
        fields, proof = record(raw, table['offset'] + current, '<HHIII', VN, work)
        need(fields['version'] == 1, 'SYM_VERSION_REVISION_UNSUPPORTED')
        need(fields['cnt'] <= ROWS and base_rows + auxiliary_count + fields['cnt'] <= ROWS, 'SYM_RECORD_BOUND')
        need((fields['cnt'] == 0) == (fields['aux'] == 0), 'SYM_AUX_COUNT_OR_OFFSET')
        auxiliary_count += fields['cnt']
        file_name = string(raw, table['link'], values[table['link']], fields['file'], work)
        aux, auxiliary = current + fields['aux'], []
        for ai in range(fields['cnt']):
            need(aux % 4 == 0 and 0 <= aux <= table['size'] - 16, 'SYM_VERSION_RECORD_RANGE')
            need(all(aux + 16 <= a or b <= aux for a, b in occupied), 'SYM_VERSION_OVERLAP')
            occupied.append((aux, aux + 16))
            af, ap = record(raw, table['offset'] + aux, '<IHHII', VA, work)
            name = string(raw, table['link'], values[table['link']], af['name'], work)
            auxiliary.append(dict(ap, index=ai, fields={k: str(v) for k, v in af.items()}, name=name))
            need((af['next'] == 0) == (ai == fields['cnt'] - 1), 'SYM_AUX_TERMINATOR_OR_COUNT')
            if af['next']:
                need(af['next'] >= 16, 'SYM_VERSION_PROGRESS')
                aux += af['next']
        needs.append(dict(proof, index=index, section=needed,
            fields={key: str(value) for key, value in fields.items()}, file=file_name, auxiliaries=auxiliary))
        need((fields['next'] == 0) == (index == table['info'] - 1), 'SYM_NEED_TERMINATOR_OR_COUNT')
        if fields['next']:
            need(fields['next'] >= 16, 'SYM_VERSION_PROGRESS')
            current += fields['next']
    gaps, cursor = [], 0
    for start, end in sorted(occupied):
        if cursor < start:
            gaps.append(dict(span(raw, table['offset'] + cursor, start - cursor, work), section=needed,
                raw_hex=raw[table['offset'] + cursor:table['offset'] + start].hex()))
        cursor = end
    if cursor < table['size']:
        gaps.append(dict(span(raw, table['offset'] + cursor, table['size'] - cursor, work), section=needed,
            raw_hex=raw[table['offset'] + cursor:table['offset'] + table['size']].hex()))
    declarations = {}
    for entry in needs:
        for aux in entry['auxiliaries']:
            value = int(aux['fields']['other']) & 32767
            declarations.setdefault(value, []).append({'need_index': entry['index'], 'aux_index': aux['index']})
    associations, fanout = [], 0
    retained_rows = len(selected) + len(symbols) + 2 * len(versions) + len(needs) + len(gaps) + auxiliary_count
    need(retained_rows <= ROWS, 'SYM_RECORD_BOUND')
    for entry in versions:
        raw_value, value = int(entry['raw_value']), int(entry['low15_index'])
        candidates = [] if value in (0, 1) or raw_value >= 65280 else declarations.get(value, [])
        fanout += len(candidates)
        need(retained_rows + fanout <= ROWS, 'SYM_ASSOCIATION_FANOUT_BOUND')
        kind = ('RESERVED' if raw_value >= 65280 else 'LOCAL' if value == 0 else 'GLOBAL' if value == 1
            else 'MISSING_DECLARATION' if not candidates else 'MATCHED_DECLARATION' if len(candidates) == 1
            else 'AMBIGUOUS_DECLARATION')
        associations.append({'symbol_index': entry['symbol_index'], 'low15_index': str(value),
            'classification': kind, 'candidates': candidates})
    result = {'schema': 'callback-symbol-version-data/1', 'input': input_span, 'section_page': page_span,
        'selected_sections': selected, 'symbols': symbols, 'versions': versions, 'needs': needs,
        'gaps': gaps, 'associations': associations, 'hash_work_bytes_before_output_hashes': work[0],
        'visibility_conventions': 'low2 glibc2.42 and low3 ELF4.3 DRAFT projections; original st_other retained',
        'native_runtime_dependency_resolution_or_model_RAM_admission': False}
    need(sum(len(result[kind]) for kind in KINDS) + auxiliary_count <= ROWS, 'SYM_RECORD_BOUND')
    encoded(result)
    return result


# Partition complete ordered records by both encoded byte size and record count without truncation.
def pages(result):
    encoded(result)
    output, total = [], 0
    for kind in KINDS:
        start = 0
        while start < len(result[kind]):
            batch = []
            while start + len(batch) < len(result[kind]) and len(batch) < 64:
                candidate = batch + [result[kind][start + len(batch)]]
                page = {'schema': 'callback-symbol-record-page/1', 'binary_sha256': result['input']['sha256'],
                    'kind': kind, 'start': start, 'records': candidate}
                if len(encoded(page)) > 65536:
                    need(bool(batch), 'SYM_SINGLE_RECORD_PAGE_BOUND')
                    break
                batch = candidate
            need(bool(batch) and len(output) < 256, 'SYM_PAGE_COUNT_BOUND')
            body = encoded(dict(page, records=batch))
            total += len(body)
            need(total <= WORK, 'SYM_OUTPUT_BOUND')
            output.append(body)
            start += len(batch)
    return output
