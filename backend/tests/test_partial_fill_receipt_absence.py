"""Known partial executions must survive a later absent ordinary broker receipt."""

from copy import deepcopy
from dataclasses import asdict
from datetime import datetime

from backend.agents.trading.desk import paper

CID = "anios-2026-10-13-buy-aaa-7"
SINCE = "2026-10-13T00:00:00Z"
OBSERVED = datetime.fromisoformat("2026-10-14T10:15:00-04:00")


# Supply only explicitly queued broker reads and refuse every order mutation.
class ReadOnlySyntheticClient:
    # Retain independent response pages and an audit of actual client calls.
    def __init__(self, responses):
        self.responses = deepcopy(responses)
        self.reads = []
        self.mutations = []

    # Return the next explicit observation without inferring an order from positions.
    def orders_since(self, since):
        self.reads.append(since)
        assert self.responses, "Unexpected broker read after supplied observations"
        return deepcopy(self.responses.pop(0))

    # Make any attempted execution fail visibly instead of reaching a broker.
    def _refuse(self, operation):
        self.mutations.append(operation)
        raise AssertionError(f"Synthetic reconciliation must not {operation}")

    # Refuse ordinary market submissions during read-only reconciliation.
    def submit_market(self, *args, **kwargs):
        self._refuse("submit_market")

    # Refuse closing-auction submissions during read-only reconciliation.
    def submit_market_on_close(self, *args, **kwargs):
        self._refuse("submit_market_on_close")

    # Refuse bounded IOC submissions during read-only reconciliation.
    def submit_limit_ioc(self, *args, **kwargs):
        self._refuse("submit_limit_ioc")

    # Refuse cancellation rather than treating it as a source of terminal evidence.
    def cancel_orders(self, *args, **kwargs):
        self._refuse("cancel_orders")


# Describe the original desired quantity separately from the sender's accepted amount.
def intent():
    return {
        "client_order_id": CID,
        "symbol": "AAA",
        "side": "buy",
        "qty": 8,
        "session": "2026-10-13",
        "execute_on": "2026-10-14",
        "execution_timing": "dip_or_close",
        "sent": {"qty": 5, "at": "2026-10-14T09:30:01-04:00"},
        "execution": {
            "decision_at": "2026-10-13T23:45:00Z",
            "reference_price": 100.0,
            "reference_session": "2026-10-13",
            "reference_source": "synthetic original daily close",
        },
    }


# Give native settlement explicit original broker quantities and execution clocks.
def receipt(status="partially_filled", filled="2", price="101.25"):
    return {
        "client_order_id": CID,
        "symbol": "AAA",
        "side": "buy",
        "qty": "5",
        "status": status,
        "filled_qty": filled,
        "filled_avg_price": price,
        "created_at": "2026-10-14T13:30:00Z",
        "submitted_at": "2026-10-14T13:30:01Z",
        "filled_at": "2026-10-14T13:31:00Z",
    }


# Materialize a real working partial through native fold, serializer and file reopen.
def saved_partial(root):
    original = paper.PaperState(pending=[intent()])
    before = deepcopy(asdict(original))
    observed = receipt()
    settled = paper.settle(original.pending, [observed])
    assert (settled[0].status, settled[0].terminal) == ("partial", False)
    result = paper.apply_settlements(original, settled)
    assert asdict(original) == before
    paper.save_state(root, result)
    saved = paper.load_state(root)
    assert len(saved.pending) == len(saved.journal) == 1
    row = saved.journal[0]
    assert (row["qty"], row["submitted_qty"], row["sender_qty"], row["filled_qty"]) == (
        8, 5, 5, 2,
    )
    assert row["filled_price"] == 101.25
    assert row["execution"]["filled_at"] == observed["filled_at"]
    return saved


# A later successful empty response cannot erase an execution already saved to disk.
def test_confirmed_partial_survives_absent_ordinary_receipt(tmp_path):
    from backend.cli import market_daily

    state = saved_partial(tmp_path)
    original_journal = deepcopy(state.journal)
    original_pending = deepcopy(state.pending)
    client = ReadOnlySyntheticClient([[], []])
    updated, settled = market_daily._reconcile(
        client, state, tmp_path, True, decision_at=OBSERVED
    )
    reopened = paper.load_state(tmp_path)
    assert reopened.journal[0]["filled_qty"] == 2
    assert reopened.journal[0]["filled_price"] == 101.25
    assert reopened.journal == original_journal
    assert reopened.pending == original_pending
    assert asdict(updated) == asdict(reopened)
    assert not any(row.status == "missing" for row in settled)
    repeated, _ = market_daily._reconcile(
        client, reopened, tmp_path, True, decision_at=OBSERVED
    )
    assert asdict(paper.load_state(tmp_path)) == asdict(repeated) == asdict(reopened)
    assert client.reads == [SINCE, SINCE]
    assert client.responses == []
    assert client.mutations == []


# Original later terminal evidence can advance the preserved partial and remove pending.
def test_later_authoritative_receipt_completes_original_partial(tmp_path):
    from backend.cli import market_daily

    state = saved_partial(tmp_path)
    terminal = receipt(status="filled", filled="5", price="102.5")
    terminal["filled_at"] = "2026-10-14T13:35:00Z"
    original_terminal = deepcopy(terminal)
    client = ReadOnlySyntheticClient([[], [terminal]])
    state, _ = market_daily._reconcile(
        client, state, tmp_path, True, decision_at=OBSERVED
    )
    state = paper.load_state(tmp_path)
    result, settled = market_daily._reconcile(
        client, state, tmp_path, True, decision_at=OBSERVED
    )
    reopened = paper.load_state(tmp_path)
    assert reopened.pending == []
    assert len(reopened.journal) == 1
    row = reopened.journal[0]
    assert row["client_order_id"] == CID
    assert (row["qty"], row["submitted_qty"], row["sender_qty"], row["filled_qty"]) == (
        8, 5, 5, 5,
    )
    assert (row["status"], row["terminal"], row["filled_price"]) == (
        "partial", True, 102.5,
    )
    assert row["execution"]["submitted_at"] == original_terminal["submitted_at"]
    assert row["execution"]["filled_at"] == original_terminal["filled_at"]
    assert [(item.client_order_id, item.filled_qty, item.terminal) for item in settled] == [
        (CID, 5, True)
    ]
    assert asdict(result) == asdict(reopened)
    assert client.reads == [SINCE, SINCE]
    assert client.responses == []
    assert client.mutations == []
    assert terminal == original_terminal


# A never-acknowledged intent still becomes missing once its original window has ended.
def test_never_acknowledged_intent_retains_original_missing_behavior(tmp_path):
    from backend.cli import market_daily

    pending = intent()
    pending.pop("sent")
    state = paper.PaperState(pending=[pending])
    paper.save_state(tmp_path, state)
    state = paper.load_state(tmp_path)
    client = ReadOnlySyntheticClient([[]])
    result, settled = market_daily._reconcile(
        client,
        state,
        tmp_path,
        True,
        decision_at=datetime.fromisoformat("2026-10-14T17:00:00-04:00"),
    )
    reopened = paper.load_state(tmp_path)
    assert reopened.pending == []
    assert len(reopened.journal) == 1
    row = reopened.journal[0]
    assert (row["client_order_id"], row["qty"], row["filled_qty"]) == (CID, 8, 0)
    assert (row["status"], row["terminal"], row["filled_price"]) == (
        "missing", True, 0.0,
    )
    assert "submitted_qty" not in row
    assert "sender_qty" not in row
    assert [(item.status, item.filled_qty, item.terminal) for item in settled] == [
        ("missing", 0, True)
    ]
    assert asdict(result) == asdict(reopened)
    assert client.reads == [SINCE]
    assert client.responses == []
    assert client.mutations == []


# A real acknowledgment with zero fills remains unresolved without rewriting its state.
def test_acknowledged_zero_fill_survives_absence_without_native_save(tmp_path):
    from backend.cli import market_daily

    original = paper.PaperState(pending=[intent()])
    accepted = receipt(status="accepted", filled="0", price="0")
    accepted["filled_at"] = None
    settled = paper.settle(original.pending, [accepted])
    state = paper.apply_settlements(original, settled)
    paper.save_state(tmp_path, state)
    state = paper.load_state(tmp_path)
    expected = deepcopy(asdict(state))
    path = paper.state_path(tmp_path)
    before_bytes = path.read_bytes()
    before = path.stat()
    client = ReadOnlySyntheticClient([[]])
    result, outcomes = market_daily._reconcile(
        client, state, tmp_path, True, decision_at=OBSERVED
    )
    after = path.stat()
    assert asdict(result) == asdict(paper.load_state(tmp_path)) == expected
    assert outcomes == []
    assert path.read_bytes() == before_bytes
    assert (before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns) == (
        after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns,
    )
    assert result.pending[0]["client_order_id"] == CID
    assert (result.journal[0]["status"], result.journal[0]["filled_qty"]) == ("open", 0)
    assert client.reads == [SINCE]
    assert client.responses == []
    assert client.mutations == []


# An unknown partial does not block a different order's authoritative terminal receipt.
def test_known_receipt_reconciles_beside_unknown_acknowledged_partial(tmp_path):
    from backend.cli import market_daily

    state = saved_partial(tmp_path)
    unknown = deepcopy(state.journal[0])
    known_intent = intent()
    known_intent.update(client_order_id="anios-2026-10-13-buy-bbb-8", symbol="BBB")
    state.pending.append(known_intent)
    paper.save_state(tmp_path, state)
    state = paper.load_state(tmp_path)
    before = deepcopy(asdict(state))
    known_receipt = receipt(status="filled", filled="5", price="105.5")
    known_receipt.update(
        client_order_id=known_intent["client_order_id"], symbol="BBB"
    )
    client = ReadOnlySyntheticClient([[known_receipt]])
    result, settled = market_daily._reconcile(
        client, state, tmp_path, True, decision_at=OBSERVED
    )
    saved = paper.load_state(tmp_path)
    assert asdict(state) == before
    assert asdict(result) == asdict(saved)
    assert [row["client_order_id"] for row in saved.pending] == [CID]
    journal = {row["client_order_id"]: row for row in saved.journal}
    assert journal[CID] == unknown
    terminal = journal[known_intent["client_order_id"]]
    assert (terminal["qty"], terminal["submitted_qty"], terminal["sender_qty"]) == (
        8, 5, 5,
    )
    assert (terminal["filled_qty"], terminal["terminal"], terminal["filled_price"]) == (
        5, True, 105.5,
    )
    assert [row.client_order_id for row in settled] == [known_intent["client_order_id"]]
    assert client.reads == [SINCE]
    assert client.responses == []
    assert client.mutations == []
