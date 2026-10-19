"""PRIVATE prepared native-asdict output plus an explicitly DERIVED settlement tail.

The native function/default path is unchanged. This adapter moves one clone
before resolution; its derived tail is never labelled native whole-code execution.
"""
import ast
from dataclasses import asdict
from hashlib import sha256
import json
from pathlib import Path
from types import CodeType

from backend.agents.trading.desk import paper
from backend.market import historical_packet_demand as demand

SCHEMA = 'synthetic-prepared-native-transition/1'
PAPER_SHA = 'a8c5083f1828df7395164882ba877d5a134d55295d6a0cda0dcdc0047bcde42c'
APPLY, APPLY_CODE = paper.apply_settlements, paper.apply_settlements.__code__
STATE, ASDICT, ENCODER = paper.PaperState, asdict, paper._state_json
ASDICT_CODE, ENCODER_CODE = ASDICT.__code__, ENCODER.__code__
DONE, REBALANCE_EVERY = paper.DONE, paper.REBALANCE_EVERY
DONE_VALUE = frozenset(DONE)
_SOURCE_CERTIFICATE = None


# Hash the exact standalone native writer representation without normalizing nonfinite values.
def native_bytes(state, limit):
    if type(state) is not STATE or type(limit) is not int or limit <= 0:
        raise ValueError('Exact bounded prepared native state required')
    digest, length = sha256(), 0
    for text in json.JSONEncoder(indent=2, default=ENCODER).iterencode(state):
        raw = text.encode('utf-8')
        length += len(raw)
        if length > limit:
            raise ValueError('Prepared native transition exceeds finite byte bound')
        digest.update(raw)
    return {'schema': 'native-paper-serialization/1', 'raw_sha256': digest.hexdigest(), 'raw_bytes': length}


# Copy the complete native settlement tail after its one output-clone statement, with explicit new ownership.
def _apply_owned_tail(state, settled, new):
    journal = {str(row.get("client_order_id") or ""): row for row in state.journal}
    for s in settled:
        previous = journal.get(s.client_order_id, {})
        prior = next(
            (
                row
                for row in state.pending
                if row.get("client_order_id") == s.client_order_id
            ),
            journal.get(s.client_order_id, {}),
        )
        journal[s.client_order_id] = {
            "client_order_id": s.client_order_id,
            "symbol": s.symbol,
            "side": s.side,
            "qty": s.qty,
            "session": s.session,
            "status": s.status,
            "filled_qty": s.filled_qty,
            "filled_price": s.filled_price,
            "terminal": s.terminal,
            "event_id": prior.get("event_id"),
            "kind": s.kind or prior.get("kind"),
            "execution": {
                **journal.get(s.client_order_id, {}).get("execution", {}),
                **prior.get("execution", {}),
                **s.execution,
            },
        }
        # Keep known observations through later partial receipts that omit a field.
        for key, value in (
            ("submitted_qty", s.submitted_qty),
            ("sender_qty", s.sender_qty),
        ):
            if value is not None:
                journal[s.client_order_id][key] = value
            elif key in previous:
                journal[s.client_order_id][key] = previous[key]
        quantity_evidence = s.quantity_evidence or previous.get("quantity_evidence")
        if quantity_evidence is not None:
            journal[s.client_order_id]["quantity_evidence"] = quantity_evidence
        if "execution_policy" in prior:
            journal[s.client_order_id].update(
                {
                    key: prior.get(key)
                    for key in (
                        "execution_policy",
                        "execute_on",
                        "execution_timing",
                        "reason",
                    )
                }
            )
    new.journal = [journal[k] for k in sorted(journal)]
    still_working = {
        s.client_order_id
        for s in settled
        if s.status == "open" or (s.status == "partial" and not s.terminal)
    }
    settled_ids = {s.client_order_id for s in settled}
    new.pending = [
        {
            **row,
            "execution": journal[str(row.get("client_order_id") or "")]["execution"],
        }
        if str(row.get("client_order_id") or "") in still_working
        else row
        for row in new.pending
        if str(row.get("client_order_id") or "") not in settled_ids
        or str(row.get("client_order_id") or "") in still_working
    ]
    if state.unconfirmed_rebalance is None:
        return new
    # The rebalance's whole set of legs, from the journal's latest entry per
    # order, so a terminal leg is never forgotten when another fills later.
    legs = [
        e
        for e in new.journal
        if e["session"] == state.unconfirmed_rebalance and not e.get("event_id")
    ]
    if (
        not legs
        or any(not e["terminal"] for e in legs)
        or any(
            row.get("session") == state.unconfirmed_rebalance
            and not row.get("event_id")
            for row in new.pending
        )
    ):
        # Nothing to conclude yet; ask again next session.
        return new
    if all(e["status"] in DONE for e in legs):
        new.unconfirmed_rebalance = None
        return new
    # It did not go through. Put the clock back so it is tried again.
    new.unconfirmed_rebalance = None
    new.last_rebalance = state.previous_rebalance
    new.sessions_since_rebalance = REBALANCE_EVERY
    return new


_DERIVED_CODE = _apply_owned_tail.__code__


# Certify the complete derived tail once, then require the identical source bytes for its whole lifetime.
def _certificate(native_raw, own_raw, native_path, own_path):
    global _SOURCE_CERTIFICATE
    if _SOURCE_CERTIFICATE is not None:
        if native_raw != _SOURCE_CERTIFICATE[0] or own_raw != _SOURCE_CERTIFICATE[1]:
            raise ValueError('Original certified transition source bytes changed')
        return _SOURCE_CERTIFICATE
    native_tree, own_tree = ast.parse(native_raw), ast.parse(own_raw)
    original = next(n for n in native_tree.body if isinstance(n, ast.FunctionDef) and n.name == 'apply_settlements')
    derived = next(n for n in own_tree.body if isinstance(n, ast.FunctionDef) and n.name == '_apply_owned_tail')
    expected = ast.dump(ast.Module(body=original.body[2:], type_ignores=[]), include_attributes=False)
    actual = ast.dump(ast.Module(body=derived.body, type_ignores=[]), include_attributes=False)
    native_code = next(n for n in compile(native_raw, str(native_path), 'exec', dont_inherit=True).co_consts
                       if type(n) is CodeType and n.co_name == 'apply_settlements')
    derived_code = next(n for n in compile(own_raw, str(own_path), 'exec', dont_inherit=True).co_consts
                        if type(n) is CodeType and n.co_name == '_apply_owned_tail')
    if (sha256(native_raw).hexdigest() != PAPER_SHA or expected != actual
            or native_code != APPLY_CODE or derived_code != _DERIVED_CODE):
        raise ValueError('Exact original native source and complete derived transition tail required')
    _SOURCE_CERTIFICATE = (native_raw, own_raw, sha256(own_raw).hexdigest(),
                           sha256(actual.encode()).hexdigest())
    return _SOURCE_CERTIFICATE


# Recheck full source bytes and every original live dependency without repeated AST materialization.
def sources():
    native_path, own_path = Path(paper.__file__), Path(__file__)
    if native_path.stat().st_size > 262144 or own_path.stat().st_size > 262144:
        raise ValueError('Bounded original transition sources required')
    native_raw, own_raw = native_path.read_bytes(), own_path.read_bytes()
    certificate = _certificate(native_raw, own_raw, native_path, own_path)
    if (sha256(native_raw).hexdigest() != PAPER_SHA
            or paper.apply_settlements is not APPLY or APPLY.__code__ is not APPLY_CODE
            or _apply_owned_tail.__code__ is not _DERIVED_CODE
            or paper.PaperState is not STATE or paper.asdict is not ASDICT or asdict is not ASDICT
            or ASDICT.__code__ is not ASDICT_CODE or ENCODER.__code__ is not ENCODER_CODE
            or paper._state_json is not ENCODER or APPLY.__globals__ is not vars(paper)
            or paper.DONE is not DONE or frozenset(DONE) != DONE_VALUE
            or type(REBALANCE_EVERY) is not int or paper.REBALANCE_EVERY is not REBALANCE_EVERY):
        raise ValueError('Exact native source/globals and complete derived transition tail required')
    return {'native_paper': PAPER_SHA, 'derived_adapter': certificate[2],
            'derived_tail_ast_sha256': certificate[3],
            'execution_mode': 'PRIVATE_DERIVED_TAIL_NOT_NATIVE_WHOLE_FUNCTION'}


# Own the exact original prior and a native-asdict output clone before resolution, consumed only once.
class PreparedTransition:
    # Perform only the full output materialization, never predict post-flush orders or settlements.
    def __init__(self, prior, limit, *, binding):
        self.prior = self.original_prior = prior
        self.output = self.original_output = None
        self.used, self.closed = False, False
        try:
            self.limit = limit
            self.binding = json.loads(demand.encoded(binding))
            self.binding_raw = demand.encoded(self.binding)
            self.native = native_bytes(prior, limit)
            if self.binding['sources'] != sources() or self.binding['native_bytes'] != self.native:
                raise ValueError('Exact original transition input/source binding required')
            self.output = self.original_output = STATE(**ASDICT(prior))
            self.check(binding, unconsumed=True)
        except BaseException:
            self.close()
            raise

    # Recheck exact owned identities, original sources and both initial byte representations before use.
    def check(self, binding, *, unconsumed=False):
        if (self.closed or type(self.used) is not bool or (unconsumed and self.used)
                or self.prior is not self.original_prior or self.output is not self.original_output
                or self.prior is self.output or type(self.prior) is not STATE or type(self.output) is not STATE
                or type(self.limit) is not int or self.limit != self.binding['raw_limit']
                or demand.encoded(binding) != self.binding_raw or demand.encoded(self.binding) != self.binding_raw
                or self.binding['sources'] != sources() or self.native != self.binding['native_bytes']
                or native_bytes(self.prior, self.limit) != self.native
                or (not self.used and native_bytes(self.output, self.limit) != self.native)):
            raise ValueError('Original unused prepared native transition required')

    # Consume the sole original output clone and apply only the explicitly source-bound derived tail.
    def apply(self, prior, settled):
        try:
            self.check(self.binding, unconsumed=True)
            if prior is not self.prior:
                raise ValueError('Original once-owned transition prior required')
            self.used = True
            updated = _apply_owned_tail(prior, settled, self.output)
            if updated is not self.output or native_bytes(prior, self.limit) != self.native:
                raise ValueError('Derived transition changed original prior or output ownership')
            return updated
        except BaseException:
            self.close()
            raise

    # Authenticate consumed metadata after this capsule has released both full state graphs.
    def check_released(self, binding):
        if (not self.closed or self.used is not True
                or any(v is not None for v in (self.prior, self.original_prior, self.output, self.original_output))
                or demand.encoded(binding) != self.binding_raw or demand.encoded(self.binding) != self.binding_raw
                or self.binding['sources'] != sources()):
            raise ValueError('Original consumed and released native transition required')

    # Release owned prior/output references on success and every failed preparation or application.
    def close(self):
        self.closed = True
        self.prior = self.original_prior = self.output = self.original_output = None
