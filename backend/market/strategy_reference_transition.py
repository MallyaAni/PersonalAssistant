"""Explicit model-reference transitions, separate from a viewer's account.

This numerical adapter is not yet selected by the live publisher. Its caller
must authenticate the reference provenance, original close marks and observed
market evidence. A hash binds supplied evidence; it does not prove that a
position was owned or that a recommendation was filled. No book is advanced by
issuing advice. The existing simulation supplies the unchanged fractional
grade-preservation rule and the native probability model decides both sides.
"""

from dataclasses import asdict, dataclass
from hashlib import sha256
import math
import json
from pathlib import Path

from backend.market import forward_probability_timing as inference
from backend.market import probabilistic_execution as timing
from backend.market import strategy_model_history as history
from backend.market import strategy_publication as publication
from backend.market import strategy_entry_context, strategy_history_installation

VERSION = "strategy-reference-transition/1"
BASIS = "counterfactual_model_reference_not_viewer_holdings"
PRICE_BASIS = "adjusted_total_return"


# Bind the exact numerical adapter and the unchanged rules it actually calls.
def sources():
    return {Path(module.__file__).name: sha256(Path(module.__file__).read_bytes()).hexdigest()
            for module in (history, timing, publication, inference, strategy_entry_context,
                           strategy_history_installation, strategy_history_installation.history)} | {
                Path(__file__).name: sha256(Path(__file__).read_bytes()).hexdigest()}


# Refuse ambiguous numbers without rounding away small genuine model transitions.
def _number(value, *, positive=False):
    return (type(value) in (int, float) and math.isfinite(value)
            and (value > 0 if positive else value >= 0))


# Own fractional units and original marks without retaining caller dictionaries.
@dataclass(frozen=True)
class ReferenceBook:
    strategy_identity: str
    through: str
    cost_bps: float
    positions: tuple[tuple[str, float, float], ...]
    cash: float
    evidence_sha256: str
    price_basis: str = PRICE_BASIS
    basis: str = BASIS

    # Reject partial universes, foreign economics and unpriced reference ownership.
    def validate(self, snapshot):
        publication._sha(self.evidence_sha256)
        if (self.strategy_identity != snapshot["strategy_identity"]
                or self.through != snapshot["session"]
                or not _number(self.cost_bps) or self.cost_bps >= 10000
                or self.cost_bps != snapshot["identity"]["economic_parameters"]["cost_bps"]
                or self.basis != BASIS or self.price_basis != PRICE_BASIS
                or type(self.positions) is not tuple
                or not _number(self.cash)
                or any(type(row) is not tuple or len(row) != 3
                       or not _number(row[1]) or not _number(row[2], positive=True)
                       for row in self.positions)
                or tuple(row[0] for row in self.positions) != tuple(sorted(snapshot["rows"]))):
            raise ValueError("Complete original model reference and matching economics required")
        nav = self.cash + sum(units * mark for _, units, mark in self.positions)
        if not _number(nav, positive=True):
            raise ValueError("Positive finite reference capital required")
        return nav


# Read the exact reviewed simulation endpoint as a separate scenario, never as owned or filled live positions.
def from_reviewed_history(root, snapshot, source, review, now):
    context = strategy_entry_context.load(root, snapshot, now)
    prepared = strategy_history_installation.prepare(
        source, review, snapshot['identity']['economic_parameters']['cost_bps'])
    manifest = json.loads(prepared['manifest'])
    if (manifest['through'] != snapshot['session']
            or prepared['binding']['strategy_identity'] != snapshot['strategy_identity']
            or set(prepared['files']) != set(snapshot['rows'])
            or not manifest['curve'] or manifest['curve'][-1]['date'] != manifest['through']):
        raise ValueError('Reviewed reference endpoint must match the original model close')
    names = tuple(context.panel.tickers)
    positions = []
    for name in sorted(snapshot['rows']):
        stock = json.loads(prepared['files'][name])
        if (stock['ticker'] != name or stock['through'] != manifest['through']
                or stock['counterfactual'] is not True or stock['real_orders'] is not False):
            raise ValueError('Original counterfactual reference stock required')
        positions.append((name, stock['latest_holding'], float(context.panel.adj_close[-1, names.index(name)])))
    evidence = {'schema': 'strategy-reference-preparation/1', 'basis': BASIS,
                'history_sha256': review['history_sha256'], 'audit_sha256': review['audit_sha256'],
                'binding_sha256': review['binding_sha256'], 'review_sha256': publication._digest(review),
                'close_context': context.receipt, 'snapshot_id': snapshot['snapshot_id'],
                'publication_receipt_sha256': snapshot['receipt_sha256'], 'source_sha256': sources()}
    reference = ReferenceBook(snapshot['strategy_identity'], manifest['through'],
        manifest['provenance']['cost_bps'], tuple(positions), manifest['curve'][-1]['cash'], publication._digest(evidence))
    nav = reference.validate(snapshot)
    if not math.isclose(nav, manifest['curve'][-1]['equity'], rel_tol=1e-12, abs_tol=1e-12):
        raise ValueError('Reviewed reference units and original capital accounting differ')
    return reference, evidence


# Keep a prepared unit objective distinct from both trade percentages and fills.
@dataclass(frozen=True)
class TransitionPlan:
    snapshot_id: str
    publication_receipt_sha256: str
    reference: ReferenceBook
    rows: tuple[tuple[str, float, float, float, str | None], ...]
    source_sha256: tuple[tuple[str, str], ...]

    # Expose a reproducible identity without exposing a mutable internal payload.
    def receipt_sha256(self):
        return publication._digest(asdict(self))


# Fix native-equivalent desired units at the original close, before later price observations.
def prepare(snapshot, reference, now):
    publication.validate(snapshot, now)
    if type(reference) is not ReferenceBook:
        raise ValueError("Explicit typed model reference required")
    nav = reference.validate(snapshot)
    current = {name: units * mark / nav for name, units, mark in reference.positions if units > 0}
    ordinals = {None: -1, "C": 0, "B": 1, "A": 2, "A+": 3}
    grades = {name: ordinals[row["evidence"]["grade"]] for name, row in snapshot["rows"].items()}
    weights = history.continuous_targets(
        {name: row["target_weight"] for name, row in snapshot["rows"].items()}, current, grades)
    rows = tuple((name, units, weights[name] * nav / mark, weights[name],
                  snapshot["rows"][name]["evidence"]["grade"])
                 for name, units, mark in reference.positions)
    if any(not _number(wanted) or not _number(target) for _, _, wanted, target, _ in rows):
        raise ValueError("Finite model reference objective required")
    return TransitionPlan(snapshot["snapshot_id"], snapshot["receipt_sha256"], reference,
                          rows, tuple(sorted(sources().items())))


# Evaluate unchanged native buy and sell timing against one explicitly marked reference book.
def project(plan, marks, distributions, *, evidence_sha256, price_basis, terminal=False):
    required = {name for name, units, wanted, _, _ in plan.rows
                if units > 0 or abs(wanted - units) > 1e-12} if type(plan) is TransitionPlan else set()
    if (type(plan) is not TransitionPlan or type(terminal) is not bool
            or plan.source_sha256 != tuple(sorted(sources().items()))
            or price_basis != plan.reference.price_basis
            or set(marks) - {row[0] for row in plan.rows} or not required <= set(marks)
            or any(not _number(value, positive=True) for value in marks.values())):
        raise ValueError("Original transition source and complete compatible marks required")
    publication._sha(evidence_sha256)
    forecast_sha256 = inference._digest(inference._forecast_identity(distributions))
    nav = plan.reference.cash + sum(units * marks[name] for name, units, _, _, _ in plan.rows if units > 0)
    # The original replay contributes zero for an unpriced, unowned change below its pending-unit threshold.
    spend = sum((wanted - units) * marks.get(name, 0.0) for name, units, wanted, _, _ in plan.rows if wanted > units)
    spend *= 1 + plan.reference.cost_bps / 10000
    if not _number(nav, positive=True) or not _number(spend):
        raise ValueError("Finite marked reference wealth required")
    # Exactly as in the simulation, suggested sales cannot fund proposed purchases.
    funded = min(1.0, plan.reference.cash / spend) if spend > 0 else 1.0
    rows = {}
    for name, units, wanted, target, grade in plan.rows:
        delta = wanted - units
        buying = delta > 0
        amount = (delta * funded if buying else min(-delta, units)) if abs(delta) > 1e-12 else 0.0
        size = amount * marks[name] / nav if amount > 0 else 0.0
        mandatory = grade in ("B", "C") and units > 0
        if mandatory:
            amount, size = units, units * marks[name] / nav
            choice = timing.Decision("execute", reason="mandatory_grade_exit")
        elif amount <= 0:
            choice = timing.Decision("no_trade", reason="No funded model reference change")
        elif terminal:
            choice = timing.Decision("execute", reason="shared_terminal_deadline")
        else:
            choice = timing.decision(distributions.get(name), "buy" if buying else "sell",
                                     size, plan.reference.cost_bps, horizon=timing.HORIZON)
        rows[name] = {"action": ("Sell" if mandatory or delta < 0 else "Buy") if amount > 0 else None,
                      "state": choice.state, "trade_weight": size, "reference_units": units,
                      "proposed_units": amount, "model_position_weight": target,
                      "reference_position_weight": units * marks[name] / nav if units > 0 else 0.0,
                      "reason": choice.reason, "waiting_log_utility": choice.expected_log_utility}
    value = {"version": VERSION, "basis": BASIS, "price_basis": price_basis,
             "snapshot_id": plan.snapshot_id, "publication_receipt_sha256": plan.publication_receipt_sha256,
             "strategy_identity": plan.reference.strategy_identity, "reference_evidence_sha256": plan.reference.evidence_sha256,
             "plan_sha256": plan.receipt_sha256(), "market_evidence_sha256": evidence_sha256,
             "timing_distributions_sha256": forecast_sha256, "terminal": terminal,
             "marked_prices": dict(marks), "reference_equity": nav, "buy_funding_factor": funded,
             "rows": rows, "recommendation_not_fill": True, "account_inputs": False,
             "source_sha256": dict(plan.source_sha256)}
    value["receipt_sha256"] = publication._digest(value)
    return value
