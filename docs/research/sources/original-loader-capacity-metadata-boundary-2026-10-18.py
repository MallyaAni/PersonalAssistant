"""INERT SOURCE PROPOSAL: read exact N2 declarations without importing account code.

This helper has not been imported or executed. It is not a SourceBook, audit
admission, model loader or substitute account. A future caller must bind
read_source to the actual authenticated source reader under a separately
reviewed contract/recipe, with guards installed before every backend import.
No existing 2446/ecc/v3 route imports this helper. Original physical bytes and
the existing explicit logical comparison semantics remain unchanged.
"""
import ast
import hashlib
import json
from pathlib import Path

PAPER_SHA256 = 'e2eef2f0270497d9a5944212d6581b7ebf503d2675687a172e76690fcc7bc3c3'
PAPER_STATE_AST_SHA256 = 'c078b1b68eece974a12dffd97cb5493ef6cecc4e70cafb33865f360d61ccba2b'
STATE_PATH_AST_SHA256 = 'c046afe1c46ed85fc6e38d469415dfdbe9bad0fed7e7e247db47c7943f68d06b'
N2_NATIVE31_SHA256 = '99e62ab9f8b02bc315ce59b81f8b461ae5c988e275cdf09cacf2d36b1025f8ab'
FIELDS = (
    'sessions_seen', 'last_rebalance', 'sessions_since_rebalance',
    'policy_version', 'opened', 'start_equity', 'history', 'pending', 'journal',
    'unconfirmed_rebalance', 'previous_rebalance', 'order_seq', 'event_cycle',
    'event_outcomes', 'deferred_buys', 'rebalance_targets', 'allocation_state',
)
MAX_PYTHON_BYTES = 1024**2
MAX_SOURCE_BYTES = 16*1024**2

# Refuse changed declarations rather than falling back to a guessed layout.
def require(condition, message):
    if not condition:
        raise RuntimeError(message)

# Derive only authenticated field names and path components; never create PaperState.
def paper_descriptor(raw):
    require(type(raw) is bytes and len(raw) <= MAX_PYTHON_BYTES, 'EXACT_BOUNDED_PAPER_BYTES_REQUIRED')
    require(hashlib.sha256(raw).hexdigest() == PAPER_SHA256, 'EXACT_N2_PAPER_SOURCE_REQUIRED')
    tree = ast.parse(raw)
    states = [node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == 'PaperState']
    paths = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == 'state_path']
    kinds = [node.value for node in tree.body if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == 'PAPER_KIND' for target in node.targets)]
    require(len(states) == len(paths) == len(kinds) == 1, 'UNIQUE_ORIGINAL_LAYOUT_DECLARATIONS_REQUIRED')
    require(hashlib.sha256(ast.dump(states[0], include_attributes=False).encode()).hexdigest() == PAPER_STATE_AST_SHA256, 'EXACT_PAPERSTATE_DECLARATION_REQUIRED')
    require(hashlib.sha256(ast.dump(paths[0], include_attributes=False).encode()).hexdigest() == STATE_PATH_AST_SHA256, 'EXACT_STATE_PATH_DECLARATION_REQUIRED')
    fields = tuple(node.target.id for node in states[0].body if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name))
    require(fields == FIELDS and len(set(fields)) == 17, 'EXACT_ORIGINAL_PHYSICAL_FIELDS_REQUIRED')
    require(isinstance(kinds[0], ast.Constant) and type(kinds[0].value) is str and kinds[0].value == 'paper', 'EXACT_ORIGINAL_PAPER_KIND_REQUIRED')
    return {
        'schema': 'original-n2-paper-layout/1', 'source_sha256': PAPER_SHA256,
        'PaperState_ast_sha256': PAPER_STATE_AST_SHA256,
        'state_path_ast_sha256': STATE_PATH_AST_SHA256,
        'physical_state_fields': list(fields),
        'relative_state_components': ['paper', 'state.json'],
    }

# Resolve only the exact declared path without calling account code or touching disk.
def physical_state_path(root, descriptor):
    expected = {
        'schema': 'original-n2-paper-layout/1', 'source_sha256': PAPER_SHA256,
        'PaperState_ast_sha256': PAPER_STATE_AST_SHA256,
        'state_path_ast_sha256': STATE_PATH_AST_SHA256,
        'physical_state_fields': list(FIELDS),
        'relative_state_components': ['paper', 'state.json'],
    }
    require(type(descriptor) is dict and descriptor == expected, 'EXACT_SOURCE_BOUND_LAYOUT_REQUIRED')
    return Path(root) / 'paper' / 'state.json'

# Hash every exact N2 source through a future authenticated reader, not module imports.
def native_source_identity(pins, read_source):
    require(type(pins) is dict and len(pins) == 31 and callable(read_source), 'EXACT_N2_SOURCE_READER_REQUIRED')
    require(all(type(name) is str and type(value) is str for name, value in pins.items()), 'EXACT_N2_SOURCE_FIELDS_REQUIRED')
    compact = json.dumps(pins, sort_keys=True, separators=(',', ':')).encode()
    require(hashlib.sha256(compact).hexdigest() == N2_NATIVE31_SHA256, 'EXACT_N2_NATIVE31_MAP_REQUIRED')
    observed = {}
    for name in sorted(pins):
        raw = read_source(name)
        require(type(raw) is bytes and len(raw) <= MAX_SOURCE_BYTES, 'BOUNDED_AUTHENTICATED_SOURCE_BYTES_REQUIRED')
        actual = hashlib.sha256(raw).hexdigest()
        require(actual == pins[name], 'N2_SOURCE_BYTES_DIFFER')
        observed[name] = actual
    require(observed == pins, 'ALL31_N2_SOURCES_REQUIRED')
    return observed

if __name__ == '__main__':
    raise SystemExit('SOURCE_ONLY_NOT_EXECUTABLE_NOT_ADMITTED')
