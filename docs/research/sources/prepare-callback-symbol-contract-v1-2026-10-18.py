"""Freeze exact section DATA and a narrow, unexecuted symbol/version reader contract."""
import base64
import hashlib
import json
import os
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
LOCAL = Path('/tmp/callback-section-page-transport-20261018-v1')
PAGE_SHA = '43ce64015bf67ad315821caa994123c7134d55e4dabb89c7bea9414607a5daa3'


# Write a new bounded artifact once, sync it, and verify its complete bytes.
def retain(path, raw):
    assert len(raw) <= 262144
    with path.open('xb') as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    assert path.read_bytes() == raw


# Encode only finite JSON while retaining exact decimal strings and complete record order.
def encoded(value):
    return json.dumps(value, sort_keys=True, indent=2, ensure_ascii=True, allow_nan=False).encode('ascii') + b'\n'


# Authenticate the one successful page observation and freeze selected records with explicit future obligations.
def main():
    lines = (LOCAL / 'stdout').read_bytes().splitlines(keepends=True)
    assert len(lines) == 2 and (LOCAL / 'stderr').read_bytes() == b''
    exit_receipt = json.loads((LOCAL / 'exit.json').read_bytes())
    assert exit_receipt['exit'] == 0
    assert all(exit_receipt[key] is None for key in ('failure_class', 'cleanup_failure_class', 'owned_SSH_group_stop'))
    stage, observation = map(json.loads, lines)
    raw = base64.b64decode(observation['page_base64'], validate=True)
    assert len(raw) == 15279 and hashlib.sha256(raw).hexdigest() == PAGE_SHA
    prior_raw = (BASE / 'original-loader-callback-elf-data-independent-v1-2026-10-18.json').read_bytes()
    assert hashlib.sha256(prior_raw).hexdigest() == '20c33344ece0c69c550f23771dbea6d9ab8d1eb6c2344a6fac2366224d817889'
    prior = json.loads(prior_raw)
    page_path = '/home/animallya96/scratch/capacity-callback-elf-data-analysis-20261018-v1/page-0001.json'
    assert observation['inputs'][page_path] == prior['input_inventory'][page_path]
    page = json.loads(raw)
    assert page['schema'] == 'callback-elf-record-page/1' and page['kind'] == 'sections' and page['start'] == 0
    records = page['records']
    assert [record['index'] for record in records] == list(range(30))
    assert page['binary_sha256'] == '9edf4136653a328edcc88dc97f6d828440ad96550c436cbe087951845c89903b'
    selected = [records[index] for index in (3, 4, 5, 6, 27, 28)]
    assert [record['fields']['type'] for record in selected] == ['11', '3', '1879048191', '1879048190', '2', '3']
    assert records[3]['fields']['link'] == '4' and records[27]['fields']['link'] == '28'
    assert records[5]['fields']['link'] == '3' and records[6]['fields']['link'] == '4'
    assert [int(records[i]['fields']['size']) // int(records[i]['fields']['entsize']) for i in (3, 27, 5)] == [163, 329, 163]
    assert not any(record['fields']['type'] in ('1879048189', '18') for record in records)
    contract = {
        'schema': 'callback-selected-symbol-version-requirements/1',
        'status': 'SOURCE_DATA_REVIEWED_REQUIREMENTS_ONLY_NO_NEW_SYMBOL_OR_VERSION_DECODER',
        'page_sha256': PAGE_SHA, 'page_bytes': len(raw), 'page_original_physical': observation['inputs'][page_path]['physical'],
        'prior_independent_sha256': hashlib.sha256(prior_raw).hexdigest(),
        'binary': prior['input_inventory']['/home/animallya96/scratch/capacity-callback-binary-copy-20261018-v1/callback.bin'],
        'selection_basis': 'Numeric section types, complete header records, links and exact spans; names retained as byte data only.',
        'complete_selected_section_records': selected,
        'derived_table_row_counts_NOT_decoded_symbols': {'section_3': 163, 'section_27': 329, 'section_5': 163},
        'complete_header_type_absence_only': {'SHT_GNU_verdef_1879048189': True, 'SHT_SYMTAB_SHNDX_18': True},
        'proposed_domain': 'Exact authenticated ELF64 little-endian callback; two 24-byte symbol arrays, linked string tables, 2-byte versym array and bounded GNU verneed chains. No relocations or runtime resolution.',
        'symbol_requirements': [
            'Authenticate full binary and complete prior section page by SHA, size and decimal physical identity with two held/named reads and later full bookends. Reuse authenticated header declarations, never rerun closed decoders for documentation.',
            'Before parsing verify each selected section header raw bytes at header_offset and each complete payload SHA/offset/size against retained records; verify exact numeric type/link/entsize and divisible sizes. Strings must use the numeric linked SHT_STRTAB, not a section-name lookup.',
            'Preserve every symbol in both arrays in table/index order, including all-zero index zero and duplicates: st_name u32, st_info u8, st_other u8, st_shndx u16, st_value u64, st_size u64; full rawhex, file offsets and per-record span hashes. Keep full st_info/st_other and report bit projections separately under named reference conventions.',
            'Preserve arbitrary byte names as hex with exact linked-table index, byte length and terminating-NUL span; permit zero/substring/duplicate names, no UTF8 assumption. Every name must terminate inside its linked table and fit the unchanged 4096-byte string bound.',
            'Do not dereference st_value or allocate st_size. Preserve undefined/reserved indices as raw declarations; classify SHN_XINDEX as explicitly unsupported without a reviewed companion-table domain. Classify out-of-range ordinary section indices precisely. sh_info local partition is a validation obligation, not proof of exported/callable/loaded symbols.',
        ],
        'version_requirements': [
            'Preserve every raw u16 versym value by dynamic-symbol index; require exact count equality 163. Retain raw value, low15 index and high bit separately; do not map version 0/1 or reserved indices to invented dependency entries.',
            'Decode each Verneed as u16 version,u16 count,u32 file,u32 aux,u32 next and each Vernaux as u32 hash,u16 flags,u16 other,u32 name,u32 next. vn_file and vna_name are offsets into the linked string table; vn_aux and vn_next are relative to the current Verneed, while vna_next is relative to the current Vernaux. Check bounds before each read, finite count, alignment, progress, cycles, overlaps, auxiliary count and terminating next zero. Preserve uncovered bytes as exact gap spans, never silently discard them.',
            'Section6 sh_info declares 2 top-level records, not 2 already decoded dependencies. Require complete chain/count agreement and linked section4 strings. Preserve all raw fields, hashes, names, repeated names/indices and auxiliary order. Unknown structure revision must refuse as unsupported domain; malformed pointers/counts get distinct bounded refusals.',
            'Retain version associations as explicit byte declarations with multiplicity. Report ambiguous or missing associations rather than inventing a unique provider. No version-definition section in the complete header type set does not certify provider availability or version compatibility.',
        ],
        'independent_and_resource_requirements': [
            'Separate independent implementation must not import or call primary; independently reconstruct every field, raw span, string, relation, gap, page, order and complete canonical byte result from authenticated binary and source pins, not compare counts only.',
            'Input/file262144, string4096, page<=65536 encoded bytes AND<=64 records, max256 pages, output/canonical16MiB; charge every whole-input/table/record/string/gap hash byte to one unchanged16MiB work ledger before hashing. Bound all loops before traversal. Refuse a single oversized record rather than split or truncate it.',
            'Prepare independent positive and refusal fixtures with known values for both symbol arrays, duplicates/substring/nonUTF8/zero names, undefined/reserved/XINDEX, bad links/widths/bounds/local partition, versym mismatch/high bits, version chain cycles/overlaps/counts/revisions/gaps and hash/page/record budgets; do not rerun old37.',
            'Exact source/invocation/resource review BEFORE any new decoder/fixture/binary use; finite owned children/CPU/AS/wall/file/log cleanup and fresh headroom. Headroom and helper limits are not a native/model/daemon memory reservation or combined peak bound.',
        ],
        'dependency_origin_requirements': [
            'Existing ordered DT_NEEDED libm.so.6 and libc.so.6 remain names only. No resolved directories, host substitutes or transitive providers may be guessed. Symbol rows and GNU version names also remain declarations.',
            'Official CPython3.12.14 importdl.c uses module spec name/origin and derives the init lookup name; dynload_shlib.c obtains interpreter flags, calls dlopen then dlsym. Matching upstream tag is reference source, not authentication of this installed Python binary/build, actual flags, mapped providers or executed initialization.',
            'Official glibc2.42 elf.h supplies GNU record layouts; dl-version.c walks required/version-provider records; dl-load.c contains loader search behavior. Actual N2 loader/libc build and configuration are still unauthenticated. No upstream version is adopted as an installed version.',
            'Before any origin/compatibility claim bind actual interpreter and loader bytes/build, relevant environment/search state/cache/config/preloads/security mode/namespace and already-loaded/global symbols, complete provider bytes/aliases/physical identities/versions and transitive dependencies under separately reviewed bounded DATA observers. Existing package source/METADATA does not supply these proofs.',
            'No package import, dlopen/dlsym, ldd/readelf, native execution, other19 native-body read, host-library substitution, cap relaxation, account/provider/model access or original/production mutation is authorized by this contract.',
        ],
        'references_read_only_NOT_actual_runtime_build_certificates': [
            'https://gabi.xinuos.com/elf/05-symtab.html',
            'https://raw.githubusercontent.com/bminor/glibc/glibc-2.42/elf/elf.h',
            'https://raw.githubusercontent.com/bminor/glibc/glibc-2.42/elf/dl-version.c',
            'https://raw.githubusercontent.com/bminor/glibc/glibc-2.42/elf/dl-load.c',
            'https://raw.githubusercontent.com/python/cpython/v3.12.14/Python/importdl.c',
            'https://raw.githubusercontent.com/python/cpython/v3.12.14/Python/dynload_shlib.c',
        ],
        'new_symbol_decoder': None, 'new_independent_decoder': None, 'new_fixture_harness': None,
        'new_symbol_invocation': None, 'dependency_origin_observer': None,
        'actual_loader_Python_build_authentication': None, 'native_runtime_admission': None,
        'execution_authorized': False,
    }
    retain(BASE / 'original-loader-callback-section-page-v1-2026-10-18.json', raw)
    retain(BASE / 'original-loader-callback-section-page-observation-v1-2026-10-18.json', lines[1])
    retain(BASE / 'original-loader-callback-section-page-stage-v1-2026-10-18.json', lines[0])
    retain(BASE / 'original-loader-callback-symbol-requirements-v1-2026-10-18.json', encoded(contract))
    descriptor = os.open(BASE, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    print(json.dumps({'complete_section_records': len(records), 'selected_section_indices': [r['index'] for r in selected],
        'page_sha256': PAGE_SHA, 'symbol_version_contents_interpreted': False, 'stage': stage}, sort_keys=True))


if __name__ == '__main__':
    main()
