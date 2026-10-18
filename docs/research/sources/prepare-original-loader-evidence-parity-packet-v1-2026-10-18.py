"""Build only new source bytes/proposal/packet; never import or execute payloads."""
import ast
import base64
import hashlib
import json
import os
from pathlib import Path

REPO=Path('/Users/animallya/.codex/worktrees/learned-live-release-20261006/PersonalAssistant')
DOCS=REPO/'docs/research'
LOCAL=Path('/tmp/capacity-evidence-parity-packet-20261018-v1')
SOURCES=DOCS/'sources'

# Identify immutable bytes with the complete SHA256 algorithm.
def sha(raw):
    return hashlib.sha256(raw).hexdigest()

# Save one new finite artifact with fsync and exact byte readback.
def save(path,raw):
    assert len(raw)<=2*1024**2
    with path.open('xb') as output:output.write(raw);output.flush();os.fsync(output.fileno())
    assert path.read_bytes()==raw
    descriptor=os.open(path.parent,os.O_RDONLY|os.O_DIRECTORY)
    try:os.fsync(descriptor)
    finally:os.close(descriptor)
    return {'sha256':sha(raw),'bytes':len(raw)}

# Encode finite source-only metadata with exact literal byte counts.
def encoded(value):
    return json.dumps(value,sort_keys=True,indent=2,allow_nan=False).encode()+b'\n'

# Assemble only the new small real module tree, original reference text and source caller.
def main():
    LOCAL.mkdir(mode=0o700,exist_ok=False)
    map_raw=(DOCS/'original-loader-genuine-source-map-2026-10-18.json').read_bytes()
    assert sha(map_raw)=='9a0bfbeb59e0a63072453a6ac0e930e65a89684efd90bc705febf9b1bdbe6224'
    pins=json.loads(map_raw);files={};origins={}
    mapping={
      'audit/bootstrap.py':'sources/original-loader-evidence-parity-bootstrap-v1-2026-10-18.py',
      'owner/parity-owner.py':'sources/original-loader-evidence-parity-owner-v1-2026-10-18.py',
      'owner/caller.py':'sources/original-loader-evidence-parity-caller-v1-2026-10-18.py',
      'owner/controller.py':'sources/original-loader-guard-controller-v2-2026-10-18.py',
      'audit/app/backend/market/capacity_original_evidence_v1.py':'sources/original-loader-capacity-evidence-v1-2026-10-18.py',
      'audit/app/backend/market/capacity_original_archive_adaptations_v1.py':'sources/original-loader-capacity-archive-adaptations-v1-2026-10-18.py',
    }
    for name,path in mapping.items():files[name]=(DOCS/path).read_bytes();origins[name]='docs/research/'+path
    proof=json.loads((DOCS/'original-loader-capacity-evidence-source-proof-2026-10-18.json').read_bytes())
    for name in ('audit/app/backend/market/capacity_original_evidence_v1.py','audit/app/backend/market/capacity_original_archive_adaptations_v1.py'):
        item=proof['artifacts'][mapping[name]];assert len(files[name])==item['bytes'] and sha(files[name])==item['sha256']
    assert sha(files['owner/controller.py'])=='2e505205cc8a3793d7b3313a5b5c3b670b00134575982d26c725787b6530df5a'
    app=('backend/__init__.py','backend/market/__init__.py','backend/market/original_history_json.py')
    references=('backend/market/live_model_history_stream_audit.py','backend/market/live_model_history_pending_audit.py','backend/market/live_model_history_receipts.py','backend/market/live_policy_replay.py','backend/market/live_model_history_nightly_model.py','backend/market/live_model_history_binding.py','backend/market/learned_live_holding.py')
    for prefix,names in (('audit/app/',app),('audit/reference/',references)):
        for name in names:
            raw=(REPO/name).read_bytes();assert sha(raw)==pins[name]
            files[prefix+name]=raw;origins[prefix+name]=name
    review_paths=('docs/research/trading-source-approval-review-2026-10-17.json','docs/research/trading-numeric-source-review-2026-10-17.json','docs/research/settlement-metadata-source-review-2026-10-17.json')
    review_hashes=('8b628c76066f62ee724a36d3d07219848786d49d51bb243d73e3e056d7c72bd4','2f048a8040532bfdaa49b1101e552457454b526b510b4ee9f2422f3a67a3e5f7','875976f63a530bc14898f3d3121e6177421f82e2275f7a8dabc5cf2b94266ac6')
    for name,expected in zip(review_paths,review_hashes,strict=True):
        raw=(REPO/name).read_bytes();assert sha(raw)==expected;files['audit/reference/'+name]=raw;origins['audit/reference/'+name]=name
    native=json.loads((DOCS/'original-loader-capacity-contract-2026-10-18.json').read_bytes())['source_recipe']['native31']
    assert len(native)==31 and sha(json.dumps(native,sort_keys=True,separators=(',',':')).encode())=='99e62ab9f8b02bc315ce59b81f8b461ae5c988e275cdf09cacf2d36b1025f8ab'
    files['audit/native31.json']=encoded(native)
    files['audit/reference-config.json']=encoded({'review_paths':review_paths,'review_pins':dict(zip(review_paths,review_hashes,strict=True)),'native31_compact_sha256':'99e62ab9f8b02bc315ce59b81f8b461ae5c988e275cdf09cacf2d36b1025f8ab'})
    child_pins={name.removeprefix('audit/'):{'sha256':sha(raw),'bytes':len(raw)} for name,raw in files.items() if name.startswith(('audit/app/','audit/reference/')) or name in ('audit/native31.json','audit/reference-config.json')}
    files['audit/pins.json']=encoded(child_pins)
    assert all(len(raw)<=262144 for raw in files.values())
    book={'schema':'capacity-evidence-parity-source/1','files':{name:{'sha256':sha(raw),'bytes':len(raw)} for name,raw in sorted(files.items())}}
    book_raw=encoded(book)
    payload=encoded({'schema':'capacity-evidence-parity-packet/1','scope':'SYNTHETIC_NEW_MODULE_PARITY_ONLY','files':{name:{'base64':base64.b64encode(raw).decode(),'sha256':sha(raw),'bytes':len(raw)} for name,raw in sorted(files.items())},'source_book':book})
    packet_pin=save(LOCAL/'packet.json',payload);book_pin=save(LOCAL/'source-book.json',book_raw)
    tree=ast.parse(files['audit/bootstrap.py'])
    cases=ast.literal_eval(next(node.value for node in tree.body if isinstance(node,ast.Assign) and any(isinstance(target,ast.Name) and target.id=='CASES' for target in node.targets)))
    assert len(cases['primitives'])==53 and len(cases['adaptations'])==27 and len(set(sum(cases.values(),[])))==80
    proposal={
      'schema':'capacity-evidence-parity-proposal/1','status':'SOURCE_PREPARED_ALL80_BODIES_UNRUN','starting_revision':'444cc1dd9e7a9b51c96271ec1a957b158b8d4b45','contract':{'path':'original-loader-capacity-evidence-contract-v1-2026-10-18.json','sha256':sha((DOCS/'original-loader-capacity-evidence-contract-v1-2026-10-18.json').read_bytes())},
      'packet':{**packet_pin,'records':len(files),'decoded_source_bytes':sum(map(len,files.values()))},'source_book':{**book_pin,'records':len(book['files'])},'file_pins':book['files'],'file_origins':origins,'case_ids':cases,
      'proposed_runtime':'ONE new e0 UID1000:1000/none/readOnly/1CPU/2GiB RAM=swap/PIDs32/tmp64MiB/noHC/lognone/capdropALL/no-new-privileges; auditRO+outRW only. No genuine original/model/account/credentials/socket mounts.',
      'deadlines':'15s child CPU/20s wait/55s parent/85s phase/130s owner; each child file262KiB. New transport/outer deadline and exact invocation not prepared/admitted.',
      'candidate_import_recipe':'Real app files under /audit/app/backend, exact child pins before sys.path insertion; only 5 real backend modules allowed. No fake modules/sys.modules injection. Candidate module import trace must be backend-pure/no numpy. No old2446 SourceBook/guard public route invoked.',
      'reference':'Full-source compilation CodeType functions/class bodies in explicit ISOLATED_SYNTHETIC_ORIGINAL_REFERENCE globals; original modules never imported/executed. SimpleNamespace binds original callback namespaces only in reference; real unchanged parser imported normally. This is NOT genuine original runtime/identity acceptance.',
      'numpy_reference':'Real NumPy solely in adaptations reference for original plain and numpy-scalar narrow-domain controls; explicit proposed /usr/local/lib/python3.12/site-packages added after candidate import trace. Child OPENBLAS/OMP/MKL/NUMEXPR/VECLIB/BLIS thread envs pinned1 before import. Actual path/version/native origin/source-image facts UNVERIFIED and must be freshly independently checked BEFORE admission. No model loading/feature arrays/inference.',
      'coverage_limits':['53primitive+27adaptation named outcomes; every body UNRUN.','Stable-file growth/replacement uses actual synthetic output files at stable_file boundary, not a full pinned mid-read race.','Custom file bounds and injected smaller gzip UNIT bounds only; no actual16MiB/64MiB/256MiB boundary or peakRAM acceptance.','Three synthetic rows from real strict reader, not whole1916 history or genuine archive/spool capacity.','Reconstructed30 predecessor is explicitly SYNTHETIC from exact N2/review data; not genuine original completion provenance.','Positive import paths/value/digest/reference parity only in the declared domain; narrower-domain controls are explicitly separate from original behavior parity.'],
      'required_before_execution':['Independent exact source/case/packet review','Separately pinned exclusive stager and source/prerequisite/terminal/preservation verifier','Fresh actual cached e0/Python/NumPy path-origin/UID/jobs/absent roots/resources/exact caller review','ONE new scoped synthetic admission; never reuse old roots/admissions'],
      'source_root':'/home/animallya96/scratch/capacity-evidence-parity-source-20261018-v1','run_root':'/home/animallya96/scratch/capacity-evidence-parity-20261018-v1','local_packet_root':str(LOCAL),'builder_sha256':sha(Path(__file__).read_bytes()),'admission':None,'launch':None,'actual_resources':None,'test_acceptance':None,'genuine_execution_authorized':False,
      'unchanged':{'original_timing':'FAILED','publication':'CLOSED','genuine_v6':'OPEN_PAUSED_NO_REPLAY_ADOPTION_NEW_RUN','model_import_strategy':None,'historical_weekday_intraday_fill_UI_RAM_horizon':'UNVERIFIED','heartbeat':'ACTIVE'}
    }
    proposal_pin=save(DOCS/'original-loader-evidence-parity-proposal-v1-2026-10-18.json',encoded(proposal))
    save(LOCAL/'build.json',encoded({'files':book['files'],'origins':origins,'packet':packet_pin,'book':book_pin,'payload_execution':False}))
    print(json.dumps({'proposal':proposal_pin,'packet':packet_pin,'book':book_pin,'files':len(files),'cases':80},sort_keys=True))

if __name__=='__main__':main()
