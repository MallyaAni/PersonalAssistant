"""SOURCE ONLY finite-control digest and original-two-review N2 chain proposals.

No archive context or genuine caller exists. These new identities are not the
original audit functions. Behavioral/reference/source-binding acceptance is UNRUN.
"""
import ast
import json
import math
from hashlib import sha256

from backend.market import original_history_json as streamed
from backend.market import capacity_original_evidence_v1 as evidence

SCHEMA = 'capacity-original-archive-adaptations/1'
N2 = '99e62ab9f8b02bc315ce59b81f8b461ae5c988e275cdf09cacf2d36b1025f8ab'
REVIEWS = (
    '8b628c76066f62ee724a36d3d07219848786d49d51bb243d73e3e056d7c72bd4',
    '2f048a8040532bfdaa49b1101e552457454b526b510b4ee9f2422f3a67a3e5f7',
)
CATALOG = REVIEWS + (
    '875976f63a530bc14898f3d3121e6177421f82e2275f7a8dabc5cf2b94266ac6',
)
HOLDING = '25fee57bd3dc57c2b945e204aa3b83e39434cf4f84f8a165a4b9e41f9f6183e1'


# Admit only decoded finite JSON controls and these new ordinary readonly containers.
def finite_controls(value):
    kind = type(value)
    if kind in (dict, evidence._ReadOnlyDict):
        evidence.require(all(type(key) is str for key in value), 'FINITE_STRING_KEY_CONTROLS_REQUIRED')
        return {key: finite_controls(row) for key, row in value.items()}
    if kind in (list, evidence._ReadOnlyList):
        return [finite_controls(row) for row in value]
    if kind is float:
        evidence.require(math.isfinite(value), 'FINITE_DECODED_CONTROLS_REQUIRED')
        return value
    evidence.require(kind in (str, int, bool, type(None)), 'FINITE_DECODED_CONTROLS_REQUIRED')
    return value


# Digest admitted controls/row references without authenticating their content or provenance.
def logical_digest(value):
    if type(value) in (dict, evidence._ReadOnlyDict) and isinstance(value.get('history'), streamed.Rows):
        evidence.require(type(value['history']) is streamed.Rows, 'EXACT_ORIGINAL_ROWS_REQUIRED')
        controls = finite_controls({name: row for name, row in value.items() if name != 'history'})
        result = json.loads(json.dumps(controls, allow_nan=False))
        result['history'] = value['history']
    else:
        result = json.loads(json.dumps(finite_controls(value), allow_nan=False))
    return streamed.digest(result)


# Validate a complete map's digest shape without coercing or substituting source keys.
def source_digests(source):
    evidence.require(type(source) in (dict, evidence._ReadOnlyDict), 'EXACT_SOURCE_MAP_REQUIRED')
    for name, value in source.items():
        evidence.require(type(name) is str, 'EXACT_SOURCE_PATH_REQUIRED')
        evidence.expected_digest(value)


# Authenticate all three original catalog entries while selecting only two transitions.
def review_catalog(review_bytes):
    evidence.require(type(review_bytes) is tuple and len(review_bytes) == 3, 'EXACT_ORIGINAL_THREE_ENTRY_CATALOG_REQUIRED')
    catalog = {}
    for expected, raw in zip(CATALOG, review_bytes, strict=True):
        evidence.require(type(raw) is bytes and len(raw) <= 262144 and sha256(raw).hexdigest() == expected, 'EXACT_ORIGINAL_REVIEW_BYTES_REQUIRED')
        catalog[expected] = evidence.strict_json(raw)
    return catalog


# Apply the unchanged three-path guard extension using separately authenticated source bytes.
def guard_extension(candidate, review, holding_source):
    paths = {
        'backend/api/v1/market.py',
        'backend/market/learned_live_holding.py',
        'backend/market/live_model_decision.py',
    }
    if set(review['source_changes']) != paths:
        raise ValueError('Exact reviewed source guard extension paths required')
    for name, change in review['source_changes'].items():
        if set(change) != {'before_sha256', 'after_sha256'}:
            raise ValueError('Exact reviewed source guard extension schema required')
        if candidate.get(name) != change['before_sha256']:
            raise ValueError('Historical source guard extension predecessor differs')
        if (name not in candidate) != (name == 'backend/market/live_model_decision.py'):
            raise ValueError('Only the reviewed read-only projection may extend sources')
        candidate[name] = change['after_sha256']
    evidence.require(type(holding_source) is bytes and len(holding_source) <= 262144 and sha256(holding_source).hexdigest() == HOLDING, 'EXACT_N2_HOLDING_SOURCE_BYTES_REQUIRED')
    tree = ast.parse(holding_source)
    functions = {
        node.name: sha256(ast.dump(node, include_attributes=False).encode()).hexdigest()
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name != 'source_identity'
    }
    if functions != review['original_holding_function_ast_sha256']:
        raise ValueError('Source guard renewal changed a holding function')


# Propose only the original approval plus numeric guard-extension transition to exact N2.
def reviewed_n2_sources(original, n2, review_bytes, holding_source):
    source_digests(original)
    source_digests(n2)
    evidence.require(len(n2) == 31 and sha256(json.dumps(n2, sort_keys=True, separators=(',', ':')).encode()).hexdigest() == N2, 'EXACT_N2_NATIVE31_MAP_REQUIRED')
    evidence.require(len(original) == 30 or (len(original) == 31 and sha256(json.dumps(original, sort_keys=True, separators=(',', ':')).encode()).hexdigest() == N2), 'EXACT_ORIGINAL_SOURCE_PROFILE_REQUIRED')
    catalog = review_catalog(review_bytes)
    candidate = dict(original)
    for receipt in REVIEWS:
        review = catalog[receipt]
        if review['status'] == 'REVIEWED_EXACT_SERVING_SOURCE_GUARD_EXTENSION':
            guard_extension(candidate, review, holding_source)
            continue
        name = review['changed_reviewed_file']
        if (
            review['status'] != 'REVIEWED_EXACT_SERVING_SOURCE_APPROVAL_CANDIDATE'
            or name != 'backend/api/v1/market.py'
            or isinstance(review['other_reviewed_sources_unchanged'], bool)
            or not isinstance(review['other_reviewed_sources_unchanged'], int)
            or review['other_reviewed_sources_unchanged'] != len(candidate) - 1
            or candidate.get(name) != review['previous_approved_sha256']
            or review['reviewed_serving_sha256'] == candidate.get(name)
        ):
            raise ValueError('Unreviewed historical-to-serving trading source change')
        candidate[name] = review['reviewed_serving_sha256']
    if candidate != n2:
        raise ValueError('Unreviewed historical-to-serving trading source change')
    return {'schema': SCHEMA, 'reviews': list(REVIEWS), 'source_count': 31, 'native31_compact_sha256': N2, 'source_reader_authenticated': False}
