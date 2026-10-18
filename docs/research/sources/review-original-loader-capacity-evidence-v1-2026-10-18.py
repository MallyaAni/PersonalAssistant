"""Pin a new unexecuted evidence module and its exact static dependency cut."""
import ast
import copy
import hashlib
import json
import os
from pathlib import Path

REPO=Path('/Users/animallya/.codex/worktrees/learned-live-release-20261006/PersonalAssistant')
DOCS=REPO/'docs/research'
MODULE='sources/original-loader-capacity-evidence-v1-2026-10-18.py'
ADAPTATIONS='sources/original-loader-capacity-archive-adaptations-v1-2026-10-18.py'
STREAM='backend/market/live_model_history_stream_audit.py'
PENDING='backend/market/live_model_history_pending_audit.py'
RECEIPTS='backend/market/live_model_history_receipts.py'
ORIGINS={
    'require':RECEIPTS,
    **{name:STREAM for name in ('expected_digest','file_identity','stable_file','pinned','authenticate_file','strict_json','_immutable','_ReadOnlyDict','_ReadOnlyList','_freeze','archive_value')},
    **{name:PENDING for name in ('unique','reject_constant','finite_float')},
}
REBINDINGS={'unique','reject_constant','finite_float','MAX_COMPRESSED_BYTES','MAX_JSON_BYTES'}

# Identify whole source bytes and complete declaration ASTs independently of comments.
def sha(raw):
    return hashlib.sha256(raw).hexdigest()

# Find a complete named declaration without compiling or importing its source.
def declaration(tree,name):
    matches=[node for node in tree.body if isinstance(node,(ast.FunctionDef,ast.ClassDef)) and node.name==name]
    assert len(matches)==1
    return matches[0]

# Remove only the five explicitly recorded pending-module dependency qualifiers.
class LocalValidators(ast.NodeTransformer):
    # Rebind exact pending validators/constants without changing any other expression.
    def visit_Attribute(self,node):
        if isinstance(node.value,ast.Name) and node.value.id=='pending' and node.attr in REBINDINGS:
            return ast.Name(id=node.attr,ctx=copy.deepcopy(node.ctx))
        return self.generic_visit(node)

# Preserve a new finite static artifact with fsync and exact byte readback.
def save(path,value):
    raw=json.dumps(value,sort_keys=True,indent=2,allow_nan=False).encode()+b'\n'
    assert len(raw)<=262144
    with path.open('xb') as output:
        output.write(raw);output.flush();os.fsync(output.fileno())
    assert path.read_bytes()==raw
    descriptor=os.open(path.parent,os.O_RDONLY|os.O_DIRECTORY)
    try:os.fsync(descriptor)
    finally:os.close(descriptor)
    return {'path':str(path.relative_to(DOCS)),'sha256':sha(raw),'bytes':len(raw)}

# Record the exact static primitive cut and the unfulfilled genuine composition obligations.
def main():
    full_raw=(DOCS/'original-loader-genuine-source-map-2026-10-18.json').read_bytes()
    assert sha(full_raw)=='9a0bfbeb59e0a63072453a6ac0e930e65a89684efd90bc705febf9b1bdbe6224'
    full=json.loads(full_raw)
    trees={};sources={}
    for name in sorted(set(ORIGINS.values())):
        raw=(REPO/name).read_bytes();assert sha(raw)==full[name]
        trees[name]=ast.parse(raw)
        sources[name]={'sha256':sha(raw),'bytes':len(raw)}
    module_raw=(DOCS/MODULE).read_bytes();module=ast.parse(module_raw)
    imports=[ast.unparse(node) for node in module.body if isinstance(node,(ast.Import,ast.ImportFrom))]
    assert imports==['import gzip','import io','import json','import math','import os','import stat','from hashlib import sha256','from pathlib import Path']
    assert {node.name for node in module.body if isinstance(node,(ast.FunctionDef,ast.ClassDef))}==set(ORIGINS)
    declarations={};unchanged=0;rebound=0
    for name,origin in ORIGINS.items():
        original=declaration(trees[origin],name);candidate=declaration(module,name)
        old=ast.dump(original,include_attributes=False);new=ast.dump(candidate,include_attributes=False)
        expected=ast.dump(LocalValidators().visit(copy.deepcopy(original)),include_attributes=False)
        assert expected==new,name
        mode='EXACT_AST' if old==new else 'EXACT_AST_WITH_DECLARED_LOCAL_REBINDINGS'
        unchanged+=old==new;rebound+=old!=new
        declarations[name]={'origin':origin,'original_AST_sha256':sha(old.encode()),'candidate_AST_sha256':sha(new.encode()),'comparison':mode,'original_line':original.lineno,'original_end_line':original.end_lineno,'candidate_line':candidate.lineno,'candidate_end_line':candidate.end_lineno}
    assert unchanged==13 and rebound==2 and len(declarations)==15
    assignments={node.targets[0].id:ast.literal_eval(node.value) for node in module.body if isinstance(node,ast.Assign) and isinstance(node.targets[0],ast.Name) and isinstance(node.value,ast.Constant)}
    assert assignments['SCHEMA']=='capacity-original-evidence-primitives/1'
    bound_names=('MAX_METADATA_BYTES','HASH_CHUNK_BYTES','MAX_COMPRESSED_BYTES','MAX_JSON_BYTES')
    for name,origin in zip(bound_names,(STREAM,STREAM,PENDING,PENDING),strict=True):
        old=next(node.value for node in trees[origin].body if isinstance(node,ast.Assign) and any(isinstance(target,ast.Name) and target.id==name for target in node.targets))
        new=next(node.value for node in module.body if isinstance(node,ast.Assign) and any(isinstance(target,ast.Name) and target.id==name for target in node.targets))
        assert ast.dump(old,include_attributes=False)==ast.dump(new,include_attributes=False)
    functions=sum(isinstance(node,ast.FunctionDef) for node in ast.walk(module))
    assert functions==19
    primitive_pin={'path':MODULE,'sha256':sha(module_raw),'bytes':len(module_raw),'schema':assignments['SCHEMA']}
    adaptation_raw=(DOCS/ADAPTATIONS).read_bytes();adaptations=ast.parse(adaptation_raw)
    adaptation_imports=[ast.unparse(node) for node in adaptations.body if isinstance(node,(ast.Import,ast.ImportFrom))]
    assert adaptation_imports==['import ast','import json','import math','from hashlib import sha256','from backend.market import original_history_json as streamed','from backend.market import capacity_original_evidence_v1 as evidence']
    assert {node.name for node in adaptations.body if isinstance(node,ast.FunctionDef)}=={'finite_controls','logical_digest','source_digests','review_catalog','guard_extension','reviewed_n2_sources'}
    adaptation_pin={'path':ADAPTATIONS,'sha256':sha(adaptation_raw),'bytes':len(adaptation_raw),'schema':'capacity-original-archive-adaptations/1','functions':6}
    pure_sources={}
    for name in ('backend/__init__.py','backend/market/__init__.py','backend/market/original_history_json.py'):
        raw=(REPO/name).read_bytes();assert sha(raw)==full[name]
        tree=ast.parse(raw)
        if name.endswith('__init__.py'):assert len(tree.body)==1 and isinstance(tree.body[0],ast.Expr) and isinstance(tree.body[0].value,ast.Constant) and type(tree.body[0].value.value) is str
        else:assert all(not (isinstance(node,ast.ImportFrom) and node.module and node.module.startswith('backend')) and not (isinstance(node,ast.Import) and any(item.name.startswith('backend') for item in node.names)) for node in ast.walk(tree))
        pure_sources[name]={'sha256':sha(raw),'bytes':len(raw)}
    old_contract=(DOCS/'original-loader-capacity-contract-2026-10-18.json').read_bytes()
    contract={
        'schema':'capacity-original-evidence-contract/1',
        'status':'SOURCE_ONLY_PRIMITIVE_MODULE_UNEXECUTED_NO_CAPACITY_ADMISSION',
        'starting_revision':'f75ed133b9ffae4baa5394a7a9b3f5de67a219fa',
        'primitive':primitive_pin,
        'proposed_primitive_source_map':{'/app/backend/market/capacity_original_evidence_v1.py':primitive_pin['sha256']},
        'archive_adaptations':adaptation_pin,
        'proposed_adaptation_source_map':{'/app/backend/market/capacity_original_archive_adaptations_v1.py':adaptation_pin['sha256'],'/app/backend/market/capacity_original_evidence_v1.py':primitive_pin['sha256'],**{'/app/'+name:item['sha256'] for name,item in pure_sources.items()}},
        'adaptation_dependency_scope':'Static source closure only: two separately versioned modules at explicit new backend.market paths plus actual unchanged original_history_json and docstring-only backend package initializers. Future real file finder/import recipe must bind all five paths; no sys.modules injection. Existing2446 SourceBook/old harness map is NOT extended or admitted here. CPython/stdlib/image/executable closure still unadmitted; no source tree assembled.',
        'complete_executor_source_map':None,
        'original_source_map':{'original_revision':'27471b9c61b958f759e9f48b80acaf60cdf75f2e','original_file_count':2431,'native31_compact_sha256':'99e62ab9f8b02bc315ce59b81f8b461ae5c988e275cdf09cacf2d36b1025f8ab','composed2446_map_sha256':sha(full_raw),'composed2446_compact_sha256':'503e8d508ebe5fdc82a17c11974ccce5366c60ce8e78fc549c129fc6c6d81e03','old_contract_sha256':sha(old_contract),'changed_or_reinterpreted':False},
        'declared_differences':{'new_module_and_class_identity':True,'local_JSON_callbacks':'pending.unique/reject_constant/finite_float become the exact copied local definitions','local_archive_constants':'pending.MAX_COMPRESSED_BYTES/MAX_JSON_BYTES become equal local expressions','primitive_body_changes_beyond_declared_rebindings':False,'limits_changed':False},
        'identity_rules':['New module/__module__/class/CodeType identities are separate; do not relabel them as stream_audit originals.','No __file__ remapping, runtime projection, sys.modules injection or manifest broadening.','Actual future executed-source closure and exact full-compilation fingerprints require a separately reviewed map/phase manifest before runtime admission.','Original2431/N2native31/producer27471 source chains and old2446/ecc/guard/G08 remain unchanged.'],
        'scope':'Byte file authentication, finite duplicate-free metadata/gzip parsing and ordinary readonly metadata containers only. No original account, schema, archive, source-chain, producer, calendar, model or RAM admission is supplied.',
        'file_semantics':'Retains original Path.stat/open/file_identity behavior, including following symlinks and accepting hardlinks; outer no-follow source/mount admission remains required. No stronger file isolation or hostile-code immutability claim.',
        'excluded':['OriginalArchives constructor/authenticate_sources/authenticate_inputs','invocation/runtime/source/producer/calendar/preserved_archives admissions','general numerical.serialized/live_policy_replay.plain normalization, numpy scalars/custom mappings, native nonfinite values and arbitrary Rows placement','StreamAudit/nightly/account/planner/broker/policy imports','loader/daily-prefix/passive economics/reader classes/model arrays'],
        'adaptation_domain':{'logical_digest':'UNEXECUTED hypothesis limited to exact decoded finite JSON controls, new readonly dict/list, string keys and optional exact real streamed.Rows reference at top-level history only. Retains JSON roundtrip and actual streamed.digest, no numpy conversion/nonfinite normalization/custom objects/tuple coercion. Exact Rows type is NOT row content, finite-value or provenance admission; raw row refs are trusted as in the original digest. A future archive context MUST bind rows to the authenticated strict reader/sealed spool and preserve their complete ordering/hashes/lifetime. Raw physical NaNs remain handled only by the existing separately source-bound original logical comparison.','review_chain':'UNEXECUTED hypothesis authenticates all THREE original catalog entries (8b628c76/2f048a80/875976f6), preserving the third byte check even though only the original first TWO transitions are selected toward exact31 N2 map99e62. Holding source bytes wholeSHA25fee then all original holding-function ASTs checked. CURRENT settlement transition never admitted. New source-reader-authenticated flag always False; full actual SourceBook binding is a separate unmet prerequisite.','actual_parity':'ALL_UNRUN; these new type/domain/refusal/source-representation differences are not claimed identical over the old general function domain.'},
        'synthetic_acceptance_required_before_integration':[
            'Prepare a DISTINCT source-pinned synthetic-only proposal/caller/packet and independently reviewed fresh source/image/UID/jobs/absent-root/resource/exact-invocation admission; all bodies currently UNRUN.',
            'Compare isolated original full-source declaration reference against actual new module with exact values/types/exception reasons, byte/Unicode/key order, signed zero, nested containers and finite number edge cases.',
            'Pinned/hash reads: exact SHA, digest type/case/length, empty file, exact bound/one-byte excess, custom bound/bool refusal, regular-file refusal, held/named identity mismatch and actual concurrent replace/growth controls at first boundary; verify source unchanged.',
            'JSON: duplicates at nested levels, nonfinite constants, exponent overflow, malformed/trailing JSON, bytes type refusal, finite underflow/signed zero/Unicode/large integer parity; retain exact failures.',
            'Freeze: for parsed plain JSON dict/list trees, exact nested values/iteration/JSON/digest representation, deepcopy returns the same readonly identity, no alias to original mutable input containers; ordinary mutators refuse, explicit reinitialization is a no-op preserving content/identity. Custom objects/subclasses are returned unchanged; direct dict/list base mutators remain an inherited limitation, not a security barrier.',
            'Gzip: exact decoded bytes, compressed/expanded guard boundaries and malformed/truncated/concatenated stream behavior. Guard controls may be explicitly injected smaller UNIT bounds but are not genuine cap/RAM acceptance.',
            'Real import trace proves only stdlib imports; no original module/backend/numerical/account imports. Original reference namespace is explicitly SYNTHETIC and never a genuine account context.',
            'Container/log/source physical bookends, two independent full evidence reads and source hashes required; headroom/log caps are not daemon/model/full-horizon RAM bounds.'
            ,'Digest: compare actual proposed logical_digest with isolated original numerical.serialized+streamed.digest on its admitted finite JSON/readonly/top-history real Rows domain; exact Unicode/order/large-int/float/signed-zero/all-row bytes/digest and close/release behavior. Nonfinite, numpy, custom mapping, tuple and nested/subclass Rows controls explicitly refuse; original reference synthetic only.'
            ,'Review chain: compare original two-transition reviewed_sources with new actual proposal on exact original30→N2 transition; authenticate all THREE catalog byte hashes including unused settlement entry, exact selected review ordering/predecessors/holding wholeSHA+function AST/new31 map. Wrong/missing/duplicate/reordered/tampered catalog entry (including third), attempted CURRENT settlement transition, wrong holding byte/AST/source map/type controls refuse. Actual complete source reader binding and full source admission must be independently reviewed before genuine use.'
        ],
        'remaining_composition_obligations':[
            'A separately versioned archive context must preserve streamed completion/sessions/spool lifetime and new readonly class identity, with exact original logical digest and raw-byte preservation verified.',
            'Separate source-review data/AST binding from learned_live_holding import; keep complete original2431 and native31 authentication, review catalogs and producer/config/calendar/preservation admissions.',
            'Separate daily-prefix and passive-economics helpers from study CLIs; no runtime AST projection masquerading as original.',
            'Explicit reader classes must retain two feature constructions, constructor prediction, readonly/aliasing/deepcopy/allocation lifetimes and exact type relationships; source-file receipt identities remain distinct and pure calibration files stay at real paths.',
            'Genuine combined loaded context + archives/spools + both full receipt graphs + final JSON/UTF8 requires fresh exact executable/source/mount/runtime/resource admission; stop at loader return/no fitting.'
        ],
        'model_import_strategy':None,'entrypoint':None,'launch':None,'admission':None,'test_outcomes':None,'execution_authorized':False,'genuine_capacity_ready':False,
        'unchanged':{'original_timing':'FAILED','publication':'CLOSED','genuine_v6':'OPEN_PAUSED_NO_REPLAY_ADOPTION_NEW_RUN','historical_weekday_intraday_fill_UI_RAM_horizon':'UNVERIFIED','heartbeat':'ACTIVE'},
    }
    contract_pin=save(DOCS/'original-loader-capacity-evidence-contract-v1-2026-10-18.json',contract)
    report={'schema':'capacity-original-evidence-static-review/1','status':'SOURCE_AST_PINNED_NOT_BEHAVIORAL_PARITY','primitive':primitive_pin,'contract':contract_pin,'archive_adaptations':adaptation_pin,'adaptation_imports':adaptation_imports,'pure_unchanged_dependency_sources':pure_sources,'original_sources':sources,'declarations':declarations,'unchanged_AST_declarations':unchanged,'explicitly_rebound_AST_declarations':rebound,'functions_including_methods':functions,'imports':imports,'limits':'Original16MiBmetadata/1MiBhashchunk/64MiBcompressed/256MiBexpanded expressions identical; no native/model/log cap changes.','analyzer':{'path':str(Path(__file__).relative_to(DOCS)),'sha256':sha(Path(__file__).read_bytes())},'application_import_compile_exec_or_test':False,'remote_or_runtime_operations':False,'old_gate_replay':False,'selected_model_import_strategy':None}
    print(json.dumps({'contract':contract_pin,'review':save(DOCS/'original-loader-capacity-evidence-review-v1-2026-10-18.json',report),'primitive':primitive_pin,'functions':functions},sort_keys=True))

if __name__=='__main__':main()
