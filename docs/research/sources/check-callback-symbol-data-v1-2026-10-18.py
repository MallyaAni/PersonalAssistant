"""UNRUN synthetic known-value symbol/version fixtures; not an actual callback reader."""
import hashlib
import json
import struct

CASES = (
    ('baseline_arbitrary_names_values_and_gaps', 'positive', {}),
    ('two_aux_relative_chain_and_ambiguous_index', 'positive', {'patches': ((434, 'H', 2), (460, 'I', 16), (464, 'IHHII', 9, 0, 2, 12, 0))}),
    ('missing_version_declaration', 'positive', {'patches': ((408, 'H', 4),)}),
    ('reserved_raw_version', 'positive', {'patches': ((404, 'H', 65280),)}),
    ('high_bit_global_raw_retained', 'positive', {'patches': ((402, 'H', 32769),)}),
    ('zero_aux_retains_uncovered_bytes', 'positive', {'patches': ((434, 'H', 0), (440, 'I', 0))}),
    ('repeated_dependency_byte_name', 'positive', {'patches': ((484, 'I', 7),)}),
    ('exact4096_byte_name', 'positive', {'mode': 'long'}),
    ('contiguous_version_records_no_gap', 'positive', {'headers': ((4, 'size', 64),),
        'patches': ((444, 'I', 32), (464, 'HHIII', 1, 1, 18, 16, 0), (480, 'IHHII', 2271560481, 0, 3, 23, 0))}),
    ('input_type', 'SYM_INPUT_DOMAIN', {'input_kind': 'bytearray'}),
    ('input_file_cap', 'SYM_INPUT_DOMAIN', {'input_kind': 'oversize'}),
    ('input_header_short', 'SYM_INPUT_DOMAIN', {'input_kind': 'short'}),
    ('section_page_byte_cap', 'SYM_INPUT_DOMAIN', {'page_edit': 'oversize'}),
    ('ELF_class', 'SYM_ELF64_LE_CURRENT', {'patches': ((4, 'B', 1),)}),
    ('ELF_type', 'SYM_ELF_HEADER_DOMAIN', {'patches': ((16, 'H', 2),)}),
    ('section_header_file_range', 'SYM_FILE_SPAN', {'patches': ((40, 'Q', 4096),)}),
    ('selected_payload_file_range', 'SYM_FILE_SPAN', {'headers': ((5, 'offset', 4096),)}),
    ('page_binary_binding', 'SYM_PAGE_BINDING', {'page_edit': 'binary_sha'}),
    ('page_duplicate_key', 'SYM_PAGE_DUPLICATE_KEY', {'page_edit': 'duplicate_key'}),
    ('page_section_count', 'SYM_PAGE_SECTION_COUNT', {'page_edit': 'count'}),
    ('page_record_index', 'SYM_SECTION_INDEX', {'page_edit': 'index'}),
    ('page_header_raw', 'SYM_SECTION_HEADER_BINDING', {'page_edit': 'raw_header'}),
    ('selected_payload_SHA', 'SYM_SECTION_PAYLOAD_BINDING', {'page_edit': 'payload_sha'}),
    ('unsupported_verdef', 'SYM_EXTENDED_OR_VERDEF_UNSUPPORTED', {'headers': ((7, 'type', 1879048189),)}),
    ('unsupported_index_extension_table', 'SYM_EXTENDED_OR_VERDEF_UNSUPPORTED', {'headers': ((7, 'type', 18),)}),
    ('missing_symbol_table', 'SYM_TABLE_SET_DOMAIN', {'headers': ((2, 'type', 1),)}),
    ('bad_string_link', 'SYM_STRING_LINK', {'headers': ((1, 'link', 7),)}),
    ('bad_version_link', 'SYM_VERSION_LINK', {'headers': ((3, 'link', 2),)}),
    ('symbol_record_width', 'SYM_SYMBOL_WIDTH', {'headers': ((1, 'entsize', 23),)}),
    ('symbol_size_remainder', 'SYM_SYMBOL_WIDTH', {'headers': ((1, 'size', 119),)}),
    ('symbol_local_info', 'SYM_SYMBOL_COUNT_OR_INFO', {'headers': ((1, 'info', 6),)}),
    ('nonzero_first_symbol', 'SYM_ZERO_SYMBOL', {'patches': ((136, 'Q', 1),)}),
    ('local_partition', 'SYM_LOCAL_PARTITION', {'patches': ((156, 'B', 16),)}),
    ('symbol_extended_index', 'SYM_XINDEX_UNSUPPORTED', {'patches': ((206, 'H', 65535),)}),
    ('symbol_ordinary_section_index', 'SYM_ORDINARY_SECTION_INDEX', {'patches': ((230, 'H', 8),)}),
    ('string_index', 'SYM_STRING_INDEX', {'patches': ((152, 'I', 32),)}),
    ('string_edges', 'SYM_STRING_EDGES', {'patches': ((591, 'B', 65),)}),
    ('string4097_bound', 'SYM_STRING_NUL_OR_BOUND', {'mode': 'too_long'}),
    ('versym_width', 'SYM_VERSYM_WIDTH_OR_COUNT', {'headers': ((3, 'entsize', 1),)}),
    ('versym_count', 'SYM_VERSYM_WIDTH_OR_COUNT', {'headers': ((3, 'size', 8),)}),
    ('verneed_domain', 'SYM_VERNEED_DOMAIN', {'headers': ((4, 'entsize', 16),)}),
    ('version_revision', 'SYM_VERSION_REVISION_UNSUPPORTED', {'patches': ((432, 'H', 2),)}),
    ('version_aux_unaligned', 'SYM_VERSION_RECORD_RANGE', {'patches': ((440, 'I', 18),)}),
    ('version_aux_overlaps_parent', 'SYM_VERSION_OVERLAP', {'patches': ((440, 'I', 4),)}),
    ('version_aux_range', 'SYM_VERSION_RECORD_RANGE', {'patches': ((440, 'I', 96),)}),
    ('version_aux_count_budget_before_loop', 'SYM_RECORD_BOUND', {'patches': ((434, 'H', 8192),)}),
    ('version_aux_count_zero_with_pointer', 'SYM_AUX_COUNT_OR_OFFSET', {'patches': ((434, 'H', 0),)}),
    ('version_aux_early_end', 'SYM_AUX_TERMINATOR_OR_COUNT', {'patches': ((434, 'H', 2),)}),
    ('version_aux_late_end', 'SYM_AUX_TERMINATOR_OR_COUNT', {'patches': ((460, 'I', 16),)}),
    ('version_aux_nonprogress', 'SYM_VERSION_PROGRESS', {'patches': ((434, 'H', 2), (460, 'I', 4))}),
    ('version_need_early_end', 'SYM_NEED_TERMINATOR_OR_COUNT', {'patches': ((444, 'I', 0),)}),
    ('version_need_late_end', 'SYM_NEED_TERMINATOR_OR_COUNT', {'patches': ((492, 'I', 16),)}),
    ('version_need_nonprogress', 'SYM_VERSION_PROGRESS', {'patches': ((444, 'I', 4),)}),
    ('version_next_parent_overlaps_prior_aux', 'SYM_VERSION_OVERLAP', {'patches': ((444, 'I', 16),)}),
    ('version_need_range_wrap_shape', 'SYM_VERSION_RECORD_RANGE', {'patches': ((444, 'I', 4294967292),)}),
    ('version_file_is_linked_string_index', 'SYM_STRING_INDEX', {'patches': ((436, 'I', 32),)}),
    ('version_aux_name_is_linked_string_index', 'SYM_STRING_INDEX', {'patches': ((456, 'I', 32),)}),
    ('global_row_budget_before_traversal', 'SYM_RECORD_BOUND', {'headers': ((4, 'info', 8192),)}),
    ('aggregate_hash_work_not_just_input_size', 'SYM_HASH_WORK_BOUND', {'mode': 'hash_work'}),
    ('association_reference_fanout_before_serialization', 'SYM_ASSOCIATION_FANOUT_BOUND', {'mode': 'fanout'}),
)
PAGE_UNITS = (
    ('single_complete_record_byte_bound', 'SYM_SINGLE_RECORD_PAGE_BOUND'),
    ('page_count_bound', 'SYM_PAGE_COUNT_BOUND'),
    ('canonical_bound', 'SYM_CANONICAL_BOUND'),
)


# Build only synthetic ELF-shaped bytes and matching section declarations with explicit mutations.
def fixture(options):
    mode = options.get('mode', 'normal')
    large = mode in ('hash_work', 'fanout')
    length, shoff = (262144, 240000) if large else (16384, 12288) if mode in ('long', 'too_long') else (4096, 2048)
    count = 100 if mode == 'fanout' else 2000 if large else 5
    dyn, sym, vers, verneed = (128, 6000, 12000, 20000) if mode == 'fanout' else (128, 60000, 120000, 130000) if large else (128, 256, 400, 432)
    first, second = (140000, 150000) if large else (560, 5000) if length == 16384 else (560, 672)
    strings = b'\0' + b'A' * (4097 if mode == 'too_long' else 4096) + b'\0' if mode not in ('normal', 'fanout') else b'\0alpha\0libA\0VER_A\0libB\0VER_B\0\xffz\0'
    raw = bytearray(length)
    raw[:16] = b'\x7fELF\x02\x01\x01' + b'\0' * 9
    struct.pack_into('<HHIQQQIHHHHHH', raw, 16, 3, 183, 1, 0, 0, shoff, 0, 64, 56, 0, 64, 8, 0)
    for start in (first, second):
        raw[start:start + len(strings)] = strings
    for offset in (dyn, sym):
        if large:
            for index in range(1, count):
                struct.pack_into('<IBBHQQ', raw, offset + index * 24, 1, 18, 0, 7, 1, 1)
        else:
            for index, fields in enumerate(((0, 0, 0, 0, 0, 0), (1, 0, 0, 7, 42, 9),
                    (2, 18, 5, 0, 0, 0), (29, 34, 255, 65521, (1 << 64) - 1, (1 << 64) - 1),
                    (1, 18, 0, 7, 99, 1))):
                struct.pack_into('<IBBHQQ', raw, offset + index * 24, *fields)
    for index in range(count):
        value = (0 if index == 0 else 2) if large else (0, 1, 2, 32770, 3)[index]
        struct.pack_into('<H', raw, vers + index * 2, value)
    raw[verneed:verneed + 96] = b'G' * 96
    struct.pack_into('<HHIII', raw, verneed, 1, 1, 7, 16, 48)
    struct.pack_into('<IHHII', raw, verneed + 16, 305419896, 2, 2, 12, 0)
    struct.pack_into('<HHIII', raw, verneed + 48, 1, 1, 18, 16, 0)
    struct.pack_into('<IHHII', raw, verneed + 64, 2271560481, 0, 3, 23, 0)
    if mode == 'fanout':
        struct.pack_into('<HHIII', raw, verneed, 1, 500, 7, 16, 0)
        for index in range(500):
            struct.pack_into('<IHHII', raw, verneed + 16 + index * 16, 1, 0, 2, 12, 0 if index == 499 else 16)
    fields = [{k: 0 for k in ('name', 'type', 'flags', 'addr', 'offset', 'size', 'link', 'info', 'addralign', 'entsize')}
        for _ in range(8)]
    for i, typ, offset, size, link, info, alignment, width in (
            (1, 11, dyn, count * 24, 5, 1 if large else 2, 8, 24),
            (2, 2, sym, count * 24, 6, 1 if large else 2, 8, 24),
            (3, 1879048191, vers, count * 2, 1, 0, 2, 2),
            (4, 1879048190, verneed, 8016 if mode == 'fanout' else 96, 5, 1 if mode == 'fanout' else 2, 4, 0),
            (5, 3, first, len(strings), 0, 0, 1, 0),
            (6, 3, second, len(strings), 0, 0, 1, 0),
            (7, 1, 64, 1, 0, 0, 1, 0)):
        fields[i].update(type=typ, offset=offset, size=size, link=link, info=info, addralign=alignment, entsize=width)
    for i, key, value in options.get('headers', ()):
        fields[i][key] = value
    for index, s in enumerate(fields):
        struct.pack_into('<IIQQQQIIQQ', raw, shoff + index * 64,
            *(s[k] for k in ('name', 'type', 'flags', 'addr', 'offset', 'size', 'link', 'info', 'addralign', 'entsize')))
    for offset, fmt, *values in options.get('patches', ()):
        struct.pack_into('<' + fmt, raw, offset, *values)
    rows = []
    for i, s in enumerate(fields):
        start, size = s['offset'], s['size']
        rows.append({'index': i, 'header_offset': str(shoff + i * 64),
            'raw_hex': bytes(raw[shoff + i * 64:shoff + (i + 1) * 64]).hex(),
            'fields': {k: str(v) for k, v in s.items()},
            'name': {'bytes': '0', 'hex': '', 'table_index': '0'},
            'file_payload': None if s['type'] in (0, 8) else {'offset': str(start), 'bytes': str(size),
                'sha256': hashlib.sha256(bytes(raw[start:start + size])).hexdigest()}})
    page = {'schema': 'callback-elf-record-page/1', 'kind': 'sections', 'start': 0,
        'binary_sha256': hashlib.sha256(raw).hexdigest(), 'records': rows}
    edit = options.get('page_edit')
    if edit == 'binary_sha':
        page['binary_sha256'] = '0' * 64
    elif edit == 'count':
        rows.pop()
    elif edit == 'index':
        rows[1]['index'] = 2
    elif edit == 'raw_header':
        rows[1]['raw_hex'] = '0' * 128
    elif edit == 'payload_sha':
        rows[1]['file_payload']['sha256'] = '0' * 64
    page_raw = json.dumps(page, sort_keys=True, separators=(',', ':')).encode() + b'\n'
    if edit == 'duplicate_key':
        page_raw = b'{"kind":"sections",' + page_raw[1:]
    elif edit == 'oversize':
        page_raw = b' ' * 65537
    kind = options.get('input_kind')
    return (bytearray(raw) if kind == 'bytearray' else b'X' * 262145 if kind == 'oversize'
        else b'X' * 63 if kind == 'short' else bytes(raw)), page_raw


# Assert independent known values and declarations rather than trusting decoder equality alone.
def known(result, options):
    mode = options.get('mode', 'normal')
    assert len(result['symbols']) == 10 and len(result['versions']) == 5 and len(result['needs']) == 2
    assert [r['index'] for r in result['selected_sections']] == [1, 2, 3, 4, 5, 6]
    symbols = result['symbols']
    assert symbols[0]['fields'] == {'name': '0', 'info': '0', 'other': '0', 'shndx': '0', 'value': '0', 'size': '0'}
    assert symbols[3]['fields']['value'] == symbols[3]['fields']['size'] == '18446744073709551615'
    assert symbols[3]['section_class'] == 'RESERVED' and symbols[2]['section_class'] == 'UNDEFINED'
    assert symbols[3]['visibility_low2'] == '3' and symbols[3]['visibility_low3'] == '7'
    if mode == 'long':
        assert symbols[1]['name']['bytes'] == '4096' and symbols[1]['name']['hex'] == '41' * 4096
    else:
        assert symbols[1]['name']['hex'] == symbols[4]['name']['hex'] == '616c706861'
        assert symbols[2]['name']['hex'] == '6c706861' and symbols[3]['name']['hex'] == 'ff7a'
        assert result['needs'][0]['file']['hex'] == '6c696241'
        assert result['needs'][1]['file']['hex'] == ('6c696241' if options.get('patches') == ((484, 'I', 7),) else '6c696242')
        for ni, entry in enumerate(result['needs']):
            for auxiliary in entry['auxiliaries']:
                assert auxiliary['name']['hex'] == ('5645525f41' if ni == 0 else '5645525f42')
        assert result['needs'][0]['offset'] == '432'
        assert result['needs'][1]['offset'] == ('464' if options.get('headers') == ((4, 'size', 64),) else '480')
        assert result['needs'][1]['fields']['next'] == '0'
    assert result['native_runtime_dependency_resolution_or_model_RAM_admission'] is False
    assert all(r['span']['bytes'] == '24' for r in symbols)
    assert all(r['span']['bytes'] == '2' for r in result['versions'])


# Exercise one proposed pure-parser case with exact positive contents or exact refusal reason.
def case(primary, independent, name, expected, options):
    raw, page = fixture(options)
    if expected == 'positive':
        left, right = primary.decode(raw, page), independent.fold(raw, page)
        assert left == right
        known(left, options)
        assert primary.encoded(left) == independent.canonical(right)
        pages = primary.pages(left)
        assert pages == independent.fold_pages(right)
        assert all(len(p) <= 65536 and len(json.loads(p)['records']) <= 64 for p in pages)
        collections = {kind: [] for kind in ('selected_sections', 'symbols', 'versions', 'needs', 'gaps', 'associations')}
        for body in pages:
            page = json.loads(body)
            assert page['start'] == len(collections[page['kind']])
            assert page['binary_sha256'] == left['input']['sha256']
            collections[page['kind']].extend(page['records'])
        assert collections == {kind: left[kind] for kind in collections}
        association = left['associations']
        if name == 'two_aux_relative_chain_and_ambiguous_index':
            assert association[2]['classification'] == 'AMBIGUOUS_DECLARATION'
            assert association[2]['candidates'] == [{'need_index': 0, 'aux_index': 0}, {'need_index': 0, 'aux_index': 1}]
        if name == 'missing_version_declaration':
            assert association[4]['classification'] == 'MISSING_DECLARATION'
        if name == 'reserved_raw_version':
            assert association[2]['classification'] == 'RESERVED' and association[2]['candidates'] == []
        if name == 'high_bit_global_raw_retained':
            assert left['versions'][1]['high_bit'] is True and association[1]['classification'] == 'GLOBAL'
        if name == 'zero_aux_retains_uncovered_bytes':
            assert left['needs'][0]['auxiliaries'] == [] and sum(int(g['bytes']) for g in left['gaps']) == 48
        if name == 'contiguous_version_records_no_gap':
            assert left['gaps'] == []
        if name == 'baseline_arbitrary_names_values_and_gaps':
            assert [g['offset'] for g in left['gaps']] == ['464', '512']
            assert [g['bytes'] for g in left['gaps']] == ['16', '16']
            assert [a['classification'] for a in association] == ['LOCAL', 'GLOBAL', 'MATCHED_DECLARATION', 'MATCHED_DECLARATION', 'MATCHED_DECLARATION']
        return {'name': name, 'status': 'positive', 'scope': 'SYNTHETIC_KNOWN_VALUES_FULL_CANONICAL_AND_PAGE_PARITY'}
    reasons = []
    for parser in (primary.decode, independent.fold):
        try:
            parser(raw, page)
        except ValueError as exc:
            reasons.append(str(exc))
        else:
            raise AssertionError('MISSING_EXPECTED_REFUSAL:' + name)
    assert reasons == [expected, expected]
    return {'name': name, 'status': 'expected_refusal', 'reason': expected, 'scope': 'SYNTHETIC_DATA_PARSER'}


# Check page bounds as explicitly injected JSON units, separate from decoded-binary evidence.
def page_unit(primary, independent, name, expected):
    value = {'input': {'sha256': '0' * 64}, **{kind: [] for kind in
        ('selected_sections', 'symbols', 'versions', 'needs', 'gaps', 'associations')}}
    value['symbols'] = [{'hex': 'a' * 70000}] if name == 'single_complete_record_byte_bound' else (
        [{}] * 16385 if name == 'page_count_bound' else [{'hex': 'a' * 16777216}])
    reasons = []
    for pager in (primary.pages, independent.fold_pages):
        try:
            pager(value)
        except ValueError as exc:
            reasons.append(str(exc))
        else:
            raise AssertionError('MISSING_EXPECTED_PAGE_REFUSAL:' + name)
    assert reasons == [expected, expected]
    return {'name': name, 'status': 'expected_refusal', 'reason': expected,
        'scope': 'INJECTED_JSON_PAGING_UNIT_NOT_BINARY_DECODING'}


# Run only the declared new synthetic cases and return every outcome for a future finite owner to retain.
def run(primary, independent):
    outcomes = []
    for name, expected, options in CASES:
        try:
            outcomes.append(case(primary, independent, name, expected, options))
        except Exception as exc:
            outcomes.append({'name': name, 'status': 'UNEXPECTED_FAILURE',
                'exception': type(exc).__name__, 'reason': str(exc)[:1024]})
    for name, expected in PAGE_UNITS:
        try:
            outcomes.append(page_unit(primary, independent, name, expected))
        except Exception as exc:
            outcomes.append({'name': name, 'status': 'UNEXPECTED_FAILURE',
                'exception': type(exc).__name__, 'reason': str(exc)[:1024]})
    return {'schema': 'callback-symbol-synthetic-results/1', 'outcomes': outcomes,
        'all_pass': all(row['status'] != 'UNEXPECTED_FAILURE' for row in outcomes),
        'actual_callback_or_native_runtime_acceptance': False}
