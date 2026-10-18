"""Independent width/cursor symbol-version DATA fold; never imports the primary."""
import hashlib
import json


# Refuse a narrow-domain or malformed DATA input with a stable reason.
def require(ok, reason):
    if not ok:
        raise ValueError(reason)


# Preserve JSON object membership by rejecting duplicate source declaration keys.
def unique_pairs(entries):
    output = {}
    for key, value in entries:
        require(key not in output, 'SYM_PAGE_DUPLICATE_KEY')
        output[key] = value
    return output


class Data:
    # Hold only immutable DATA and a single charged hash-work counter for this fold.
    def __init__(self, raw):
        self.raw = raw
        self.used = 0

    # Charge and hash a complete bounded region of either authenticated input.
    def region(self, blob, start, length):
        require(type(start) is int and type(length) is int and 0 <= start <= len(blob)
            and 0 <= length <= len(blob) - start, 'SYM_FILE_SPAN')
        self.used += length
        require(self.used <= 16777216, 'SYM_HASH_WORK_BOUND')
        return {'offset': str(start), 'bytes': str(length),
            'sha256': hashlib.sha256(blob[start:start + length]).hexdigest()}

    # Read explicit little-endian unsigned widths without struct or primary decoder calls.
    def fields(self, offset, names, widths):
        length = sum(widths)
        proof = self.region(self.raw, offset, length)
        body, cursor, values = self.raw[offset:offset + length], 0, {}
        for name, width in zip(names, widths, strict=True):
            values[name] = int.from_bytes(body[cursor:cursor + width], 'little')
            cursor += width
        return values, {'offset': str(offset), 'raw_hex': body.hex(), 'span': proof}

    # Scan at most4097 bytes for a NUL while retaining the complete arbitrary byte-name span.
    def name(self, section, table, index):
        require(0 <= index < table['size'], 'SYM_STRING_INDEX')
        body = bytearray()
        cursor = table['offset'] + index
        limit = table['offset'] + min(table['size'], index + 4097)
        while cursor < limit and self.raw[cursor] != 0:
            body.append(self.raw[cursor])
            cursor += 1
        require(cursor < limit and self.raw[cursor] == 0, 'SYM_STRING_NUL_OR_BOUND')
        return {'table_section': section, 'table_index': str(index), 'bytes': str(len(body)),
            'hex': bytes(body).hex(), 'span': self.region(self.raw, table['offset'] + index, len(body) + 1)}


# Reconstruct complete symbol/version records using independent fixed-width cursor reads.
def fold(raw, page_raw):
    require(__debug__ and type(raw) is bytes and 64 <= len(raw) <= 262144
        and type(page_raw) is bytes and len(page_raw) <= 65536, 'SYM_INPUT_DOMAIN')
    data = Data(raw)
    input_span = data.region(raw, 0, len(raw))
    page_span = data.region(page_raw, 0, len(page_raw))
    require(raw[0:7] == bytes((127, 69, 76, 70, 2, 1, 1)), 'SYM_ELF64_LE_CURRENT')
    header = {}
    cursor = 16
    for name, width in zip(('type', 'machine', 'version', 'entry', 'phoff', 'shoff', 'flags',
            'ehsize', 'phentsize', 'phnum', 'shentsize', 'shnum', 'shstrndx'),
            (2, 2, 4, 8, 8, 8, 4, 2, 2, 2, 2, 2, 2), strict=True):
        header[name] = int.from_bytes(raw[cursor:cursor + width], 'little')
        cursor += width
    require(header['type'] == 3 and header['version'] == 1 and header['ehsize'] == 64
        and header['shentsize'] == 64 and 0 < header['shnum'] <= 4096
        and header['shoff'] >= 64, 'SYM_ELF_HEADER_DOMAIN')
    page = json.loads(page_raw, object_pairs_hook=unique_pairs)
    require(type(page) is dict and set(page) == {'schema', 'kind', 'start', 'binary_sha256', 'records'}
        and page['schema'] == 'callback-elf-record-page/1' and page['kind'] == 'sections'
        and type(page['start']) is int and page['start'] == 0
        and page['binary_sha256'] == input_span['sha256'], 'SYM_PAGE_BINDING')
    declarations = page['records']
    require(type(declarations) is list and len(declarations) == header['shnum'], 'SYM_PAGE_SECTION_COUNT')
    sections = []
    for i in range(len(declarations)):
        row = declarations[i]
        require(type(row) is dict and type(row.get('index')) is int and row['index'] == i, 'SYM_SECTION_INDEX')
        values, proof = data.fields(header['shoff'] + i * 64,
            ('name', 'type', 'flags', 'addr', 'offset', 'size', 'link', 'info', 'addralign', 'entsize'),
            (4, 4, 8, 8, 8, 8, 4, 4, 8, 8))
        require(row.get('header_offset') == proof['offset'] and row.get('raw_hex') == proof['raw_hex']
            and row.get('fields') == {k: str(v) for k, v in values.items()}, 'SYM_SECTION_HEADER_BINDING')
        sections.append(values)
    require(all(s['type'] not in (18, 1879048189) for s in sections), 'SYM_EXTENDED_OR_VERDEF_UNSUPPORTED')
    type_indices = {}
    for typ in (2, 11, 1879048191, 1879048190):
        matching = tuple(i for i in range(len(sections)) if sections[i]['type'] == typ)
        require(len(matching) == 1, 'SYM_TABLE_SET_DOMAIN')
        type_indices[typ] = matching[0]
    dyn, sym, vers, req = (type_indices[t] for t in (11, 2, 1879048191, 1879048190))
    strings = {sections[dyn]['link'], sections[sym]['link'], sections[req]['link']}
    require(all(0 <= i < len(sections) and sections[i]['type'] == 3 for i in strings), 'SYM_STRING_LINK')
    require(sections[req]['link'] == sections[dyn]['link'] and sections[vers]['link'] == dyn, 'SYM_VERSION_LINK')
    picked = []
    for i in sorted(strings | {dyn, sym, vers, req}):
        s = sections[i]
        payload = data.region(raw, s['offset'], s['size'])
        require(declarations[i].get('file_payload') == payload, 'SYM_SECTION_PAYLOAD_BINDING')
        picked.append({'index': i, 'fields': declarations[i]['fields'],
            'header_span': data.region(raw, header['shoff'] + i * 64, 64), 'payload_span': payload})
        if i in strings:
            require(s['size'] > 0 and raw[s['offset']] == 0 and raw[s['offset'] + s['size'] - 1] == 0,
                'SYM_STRING_EDGES')
    sizes = {}
    for i in sorted((dyn, sym)):
        s = sections[i]
        require(s['entsize'] == 24 and s['size'] > 0 and s['size'] % 24 == 0, 'SYM_SYMBOL_WIDTH')
        n = s['size'] // 24
        require(n <= 8192 and 1 <= s['info'] <= n, 'SYM_SYMBOL_COUNT_OR_INFO')
        sizes[i] = n
    initial_rows = len(picked) + sum(sizes.values()) + 2 * sizes[dyn] + sections[req]['info']
    require(initial_rows <= 8192, 'SYM_RECORD_BOUND')
    symbols = []
    for i in sorted((dyn, sym)):
        s, n = sections[i], sizes[i]
        for j in range(n):
            require(len(symbols) < 8192, 'SYM_RECORD_BOUND')
            f, proof = data.fields(s['offset'] + j * 24,
                ('name', 'info', 'other', 'shndx', 'value', 'size'), (4, 1, 1, 2, 8, 8))
            require(j != 0 or all(v == 0 for v in f.values()), 'SYM_ZERO_SYMBOL')
            binding = f['info'] // 16
            require((binding == 0) == (j < s['info']), 'SYM_LOCAL_PARTITION')
            si = f['shndx']
            require(si != 65535, 'SYM_XINDEX_UNSUPPORTED')
            require(si == 0 or si >= 65280 or si < len(sections), 'SYM_ORDINARY_SECTION_INDEX')
            proof.update({'table_section': i, 'index': j, 'fields': {k: str(v) for k, v in f.items()},
                'binding': str(binding), 'symbol_type': str(f['info'] % 16),
                'visibility_low2': str(f['other'] % 4), 'visibility_low3': str(f['other'] % 8),
                'section_class': 'UNDEFINED' if si == 0 else 'RESERVED' if si >= 65280 else 'ORDINARY',
                'name': data.name(s['link'], sections[s['link']], f['name'])})
            symbols.append(proof)
    s = sections[vers]
    require(s['entsize'] == 2 and s['size'] == sizes[dyn] * 2, 'SYM_VERSYM_WIDTH_OR_COUNT')
    versions = []
    for j in range(sizes[dyn]):
        f, proof = data.fields(s['offset'] + j * 2, ('value',), (2,))
        value = f['value']
        proof.update({'section': vers, 'symbol_index': j, 'raw_value': str(value),
            'low15_index': str(value % 32768), 'high_bit': value >= 32768})
        versions.append(proof)
    s = sections[req]
    require(s['entsize'] == 0 and s['size'] >= 16 and 1 <= s['info'] <= 8192, 'SYM_VERNEED_DOMAIN')
    consumed, needs, used_aux = set(), [], 0
    position = 0
    for ni in range(s['info']):
        require(position % 4 == 0 and 0 <= position <= s['size'] - 16, 'SYM_VERSION_RECORD_RANGE')
        require(not any(k in consumed for k in range(position, position + 16)), 'SYM_VERSION_OVERLAP')
        consumed.update(range(position, position + 16))
        f, proof = data.fields(s['offset'] + position, ('version', 'cnt', 'file', 'aux', 'next'), (2, 2, 4, 4, 4))
        require(f['version'] == 1, 'SYM_VERSION_REVISION_UNSUPPORTED')
        require(f['cnt'] <= 8192 and initial_rows + used_aux + f['cnt'] <= 8192, 'SYM_RECORD_BOUND')
        require((f['cnt'] == 0) == (f['aux'] == 0), 'SYM_AUX_COUNT_OR_OFFSET')
        used_aux += f['cnt']
        file_name = data.name(s['link'], sections[s['link']], f['file'])
        ap, auxiliaries = position + f['aux'], []
        for ai in range(f['cnt']):
            require(ap % 4 == 0 and 0 <= ap <= s['size'] - 16, 'SYM_VERSION_RECORD_RANGE')
            require(not any(k in consumed for k in range(ap, ap + 16)), 'SYM_VERSION_OVERLAP')
            consumed.update(range(ap, ap + 16))
            af, aux = data.fields(s['offset'] + ap, ('hash', 'flags', 'other', 'name', 'next'), (4, 2, 2, 4, 4))
            aux.update({'index': ai, 'fields': {k: str(v) for k, v in af.items()},
                'name': data.name(s['link'], sections[s['link']], af['name'])})
            auxiliaries.append(aux)
            require((af['next'] == 0) == (ai == f['cnt'] - 1), 'SYM_AUX_TERMINATOR_OR_COUNT')
            if af['next'] != 0:
                require(af['next'] >= 16, 'SYM_VERSION_PROGRESS')
                ap = ap + af['next']
        proof.update({'index': ni, 'section': req, 'fields': {k: str(v) for k, v in f.items()},
            'file': file_name, 'auxiliaries': auxiliaries})
        needs.append(proof)
        require((f['next'] == 0) == (ni == s['info'] - 1), 'SYM_NEED_TERMINATOR_OR_COUNT')
        if f['next'] != 0:
            require(f['next'] >= 16, 'SYM_VERSION_PROGRESS')
            position = position + f['next']
    gaps = []
    cursor = 0
    while cursor < s['size']:
        if cursor in consumed:
            cursor += 1
            continue
        start = cursor
        while cursor < s['size'] and cursor not in consumed:
            cursor += 1
        proof = data.region(raw, s['offset'] + start, cursor - start)
        proof.update({'section': req, 'raw_hex': raw[s['offset'] + start:s['offset'] + cursor].hex()})
        gaps.append(proof)
    bindings = {}
    for ni, entry in enumerate(needs):
        for ai, aux in enumerate(entry['auxiliaries']):
            key = int(aux['fields']['other']) % 32768
            bindings.setdefault(key, []).append({'need_index': ni, 'aux_index': ai})
    retained_rows = len(picked) + len(symbols) + 2 * len(versions) + len(needs) + len(gaps) + used_aux
    require(retained_rows <= 8192, 'SYM_RECORD_BOUND')
    candidate_references = sum(len(bindings.get(int(v['low15_index']), [])) for v in versions
        if int(v['raw_value']) < 65280 and int(v['low15_index']) not in (0, 1))
    require(retained_rows + candidate_references <= 8192, 'SYM_ASSOCIATION_FANOUT_BOUND')
    associations = []
    for j, entry in enumerate(versions):
        value, original = int(entry['low15_index']), int(entry['raw_value'])
        candidates = []
        if original >= 65280:
            kind = 'RESERVED'
        elif value == 0:
            kind = 'LOCAL'
        elif value == 1:
            kind = 'GLOBAL'
        else:
            candidates = bindings.get(value, [])
            kind = {0: 'MISSING_DECLARATION', 1: 'MATCHED_DECLARATION'}.get(len(candidates), 'AMBIGUOUS_DECLARATION')
        associations.append({'symbol_index': j, 'low15_index': str(value), 'classification': kind, 'candidates': candidates})
    result = {'schema': 'callback-symbol-version-data/1', 'input': input_span, 'section_page': page_span,
        'selected_sections': picked, 'symbols': symbols, 'versions': versions, 'needs': needs,
        'gaps': gaps, 'associations': associations, 'hash_work_bytes_before_output_hashes': data.used,
        'visibility_conventions': 'low2 glibc2.42 and low3 ELF4.3 DRAFT projections; original st_other retained',
        'native_runtime_dependency_resolution_or_model_RAM_admission': False}
    require(sum(len(result[k]) for k in ('selected_sections', 'symbols', 'versions', 'needs', 'gaps', 'associations'))
        + used_aux <= 8192, 'SYM_RECORD_BOUND')
    canonical(result)
    return result


# Encode exactly the independently reconstructed finite canonical result within its original bound.
def canonical(value):
    body = json.dumps(value, ensure_ascii=True, allow_nan=False, sort_keys=True, separators=(',', ':')).encode('ascii') + bytes((10,))
    require(len(body) <= 16777216, 'SYM_CANONICAL_BOUND')
    return body


# Independently reconstruct each complete greedy page under both byte and record limits.
def fold_pages(result):
    canonical(result)
    outputs, charged = [], 0
    for kind in ('selected_sections', 'symbols', 'versions', 'needs', 'gaps', 'associations'):
        rows = result[kind]
        offset = 0
        while offset < len(rows):
            best, end = None, offset
            while end < min(len(rows), offset + 64):
                proposed = canonical({'schema': 'callback-symbol-record-page/1', 'binary_sha256': result['input']['sha256'],
                    'kind': kind, 'start': offset, 'records': rows[offset:end + 1]})
                if len(proposed) > 65536:
                    require(best is not None, 'SYM_SINGLE_RECORD_PAGE_BOUND')
                    break
                best = proposed
                end += 1
            require(best is not None and len(outputs) < 256, 'SYM_PAGE_COUNT_BOUND')
            charged += len(best)
            require(charged <= 16777216, 'SYM_OUTPUT_BOUND')
            outputs.append(best)
            offset = end
    return outputs
