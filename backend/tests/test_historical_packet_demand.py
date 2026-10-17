"""Synthetic multi-name protocol tests; no provider identity, GET or model proof."""

import base64
import hashlib
from copy import deepcopy
from urllib.parse import urlencode

import pytest

from backend.market import historical_packet_checkpoint as checkpoint
from backend.market import historical_packet_demand as demand
from backend.market import historical_packet_parser as parser
from backend.market import historical_packet_registry as registry
from backend.market.historical_timing_packet import _digest

COMPLETED = "2019-03-01T14:45:00Z"
VERIFIED = "2026-10-17T16:00:00Z"


# Pin explicit synthetic evidence without implying an issuer or real source observation.
def sha(value):
    return hashlib.sha256(value).hexdigest()


# Build synthetic conditional mappings without claiming issuer identity.
def source_registry(names=("AAPL", "MSFT"), status="REVIEWED_CONDITIONAL_MAPPING"):
    raw_source = b"SYNTHETIC requested-name source metadata, not real issuer proof"
    review = (
        b"SYNTHETIC review accepting provider mapping only as a declared assumption"
    )
    evidence = {sha(raw_source): raw_source, sha(review): review}
    rows = []
    for name in names:
        rows.append(
            {
                "cohort_key": name,
                "query_symbol": name,
                "entity_asof": "2026-10-12",
                "status": status,
                "issuer_identity": None,
                "assumption": "SYNTHETIC fixed-date provider mapping assumption"
                if status == "REVIEWED_CONDITIONAL_MAPPING"
                else None,
                "sources": [
                    {
                        "kind": "request_metadata",
                        "sha256": sha(raw_source),
                        "source_label": name,
                    }
                ],
                "review_sha256": sha(review)
                if status == "REVIEWED_CONDITIONAL_MAPPING"
                else None,
            }
        )
    raw = demand.encoded({"schema": "historical-entity-registry/1", "entries": rows})
    return registry.registry(raw, sha(raw), evidence)


# Declare held MSFT and due AAPL before evaluating current forecasts or quotes.
def declaration(reg=None, **changes):
    reg = reg or source_registry()
    values = {
        "identity_sha256": "1" * 64,
        "parent_sha256": "2" * 64,
        "completed_at": COMPLETED,
        "prior": {k: "3" * 64 for k in demand.PRIOR},
        "held": ["MSFT"],
        "legs": [
            {
                "client_order_id": "synthetic-aapl-buy",
                "symbol": "AAPL",
                "side": "buy",
                "qty": 2,
                "phase": "market",
                "session": "2019-03-01",
            }
        ],
        "used": {"get_attempts": 0, "body_bytes": 0},
    }
    values.update(changes)
    return demand.build(reg, **values)


# Encode synthetic provider pages with exact query and acquisition-clock fields.
def page(query, members, token=None, next_token=None):
    body = demand.encoded({query["kind"]: members, "next_page_token": next_token})
    params = dict(query["parameters"])
    if token is not None:
        params["page_token"] = token
    return {
        "url": query["endpoint"] + "?" + urlencode(params),
        "requested_at": "2026-10-17T15:59:02Z" if token else "2026-10-17T15:59:00Z",
        "received_at": "2026-10-17T15:59:03Z" if token else "2026-10-17T15:59:01Z",
        "status": 200,
        "body_base64": base64.b64encode(body).decode(),
        "sha256": sha(body),
        "body_complete": True,
        "failure": None,
    }


# Construct groups with a deliberately short symbol-first continuation page.
def capture(reg, manifest):
    data = demand.read(manifest, reg)
    groups = {}
    for query in data["queries"]:
        if query["kind"] == "quotes":
            groups[query["sha256"]] = [
                page(
                    query,
                    {
                        "AAPL": [
                            {
                                "t": "2019-03-01T14:45:30.5Z",
                                "bp": 100,
                                "ap": 100.01,
                                "bs": 1,
                                "as": 1,
                            }
                        ]
                    },
                    next_token="private-next",
                ),
                page(query, {"MSFT": []}, token="private-next"),
            ]
        else:
            groups[query["sha256"]] = [page(query, {"AAPL": []})]
    return {
        "schema": "historical-demand-capture/1",
        "demand_sha256": manifest.sha256,
        "complete": True,
        "failure": None,
        "groups": groups,
    }


# Seal synthetic captures through the retained-evidence parser.
def parse(value, manifest, reg):
    raw = demand.encoded(value)
    sealed = parser.packets(raw, sha(raw), manifest, reg, VERIFIED)
    return parser.read(sealed, manifest, reg)


# Find the declared quote group without depending on incidental dictionary order.
def quote_key(value, manifest, reg):
    return next(
        q["sha256"]
        for q in demand.read(manifest, reg)["queries"]
        if q["kind"] == "quotes"
    )


# Check declared holding coverage without inventing fresh marks.
def test_complete_symbol_first_capture_and_explicit_empty():
    reg = source_registry()
    manifest = declaration(reg)
    value = capture(reg, manifest)
    result = parse(value, manifest, reg)
    key = quote_key(value, manifest, reg)
    assert result["groups"][key]["AAPL"]["status"] == "COMPLETE_ROWS"
    assert result["groups"][key]["MSFT"] == {"status": "COMPLETE_EMPTY", "rows": []}
    assert result["used"]["get_attempts"] == 3
    assert result["post_resolution_marks"] == "UNRESOLVED_NO_FRESH_MARK_SELECTION"
    assert result["issuer_identity_proven_by_parser"] is False
    assert result["acquisition_authorized"] is False
    data = demand.read(manifest, reg)
    assert data["held"] == ["MSFT"]
    assert data["potential_holdings"] == ["AAPL", "MSFT"]
    assert data["queries"][0]["parameters"]["asof"] == "2026-10-12"
    assert data["window"]["completed_at"].startswith("2019-03-01")


# Preserve absent-key evidence separately from a returned explicitly empty row list.
def test_complete_missing_name_is_not_zero_price_or_identity_failure():
    reg = source_registry()
    manifest = declaration(reg)
    value = capture(reg, manifest)
    key = quote_key(value, manifest, reg)
    query = demand.read(manifest, reg)["queries"][0]
    value["groups"][key] = [page(query, {})]
    result = parse(value, manifest, reg)
    assert result["groups"][key]["MSFT"] == {
        "status": "COMPLETE_ABSENT_KEY",
        "rows": [],
    }


# Expose unadmitted provenance while refusing to query unknown or merely named entities.
@pytest.mark.parametrize("status", ["UNRESOLVED", "REQUEST_NAME_ONLY"])
def test_request_name_provenance_is_retained_but_not_admitted(status):
    reg = source_registry(status=status)
    assert registry.entries(reg)["AAPL"]["status"] == status
    assert registry.entries(reg)["AAPL"]["issuer_identity"] is None
    with pytest.raises(ValueError, match="Unresolved/request-name-only"):
        declaration(reg)


# Refuse forged registry evidence, mappings or unsupported security claims.
@pytest.mark.parametrize(
    "mutation", ["source", "duplicate", "issuer", "asof", "review"]
)
def test_registry_corruption(mutation):
    original = source_registry()
    data = registry.pinned(original.raw, original.sha256)
    row = data["entries"][0]
    evidence = dict(original.evidence)
    if mutation == "source":
        evidence[row["sources"][0]["sha256"]] = b"changed"
    elif mutation == "duplicate":
        data["entries"].append(deepcopy(row))
    elif mutation == "issuer":
        row["issuer_identity"] = {
            "scheme": "invented",
            "value": "fake",
            "share_class": "fake",
        }
    elif mutation == "asof":
        row["entity_asof"] = "-"
    else:
        row["review_sha256"] = "f" * 64
    raw = demand.encoded(data)
    with pytest.raises(
        ValueError, match="bytes|Duplicate|identity|date|isoformat|review"
    ):
        registry.registry(raw, sha(raw), evidence)


# Ensure held-only unknown names cannot disappear behind an otherwise valid due order.
def test_missing_held_entity_refuses_before_packet_admission():
    with pytest.raises(ValueError, match="MSFT"):
        declaration(source_registry(("AAPL",)))


# Reject quantity/cohort/phase corruption before any acquisition or account mutation.
@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("qty", True),
        ("qty", 2.0),
        ("qty", 0),
        ("phase", "open"),
        ("session", "2019-03-04"),
    ],
)
def test_due_leg_guards(field, value):
    reg = source_registry()
    leg = demand.read(declaration(reg), reg)["legs"][0]
    leg[field] = value
    with pytest.raises(ValueError, match="market legs"):
        declaration(reg, legs=[leg])


# Rebuild demand to detect omitted groups and altered windows or budgets.
@pytest.mark.parametrize(
    "field",
    ["queries", "window", "budget", "potential_holdings", "acquisition_authorized"],
)
def test_demand_tamper_rejected(field):
    reg = source_registry()
    manifest = declaration(reg)
    data = demand.read(manifest, reg)
    if field == "queries":
        data[field] = data[field][1:]
    elif field == "window":
        data[field]["quote_end"] = "2019-03-01T14:46:00Z"
    elif field == "budget":
        data[field]["get_attempts"] += 1
    elif field == "potential_holdings":
        data[field] = ["AAPL"]
    else:
        data[field] = True
    raw = demand.encoded(data)
    with pytest.raises(ValueError, match="Canonical"):
        demand.read(demand.Demand(raw, sha(raw)), reg)


# Keep query, pagination and clock corruption separate from missing market data.
@pytest.mark.parametrize(
    "mutation",
    [
        "short",
        "extra",
        "http",
        "future",
        "failed",
        "truncated",
        "symbol",
        "order",
        "token",
        "asof",
        "bodyhash",
        "group",
        "pagecap",
        "nan",
        "duplicate_key",
    ],
)
def test_packet_corruption(mutation):  # noqa: C901 -- Explicit corruption matrix.
    reg = source_registry()
    manifest = declaration(reg)
    value = capture(reg, manifest)
    key = quote_key(value, manifest, reg)
    pages = value["groups"][key]
    query = demand.read(manifest, reg)["queries"][0]
    if mutation == "short":
        pages.pop()
    elif mutation == "extra":
        pages.append(deepcopy(pages[-1]))
    elif mutation == "http":
        pages[0]["status"] = 429
    elif mutation == "future":
        pages[0]["received_at"] = "2099-01-01T00:00:00Z"
    elif mutation == "failed":
        value["complete"], value["failure"] = False, "transport failed"
    elif mutation == "truncated":
        pages[0]["body_complete"] = False
    elif mutation == "symbol":
        pages[:] = [page(query, {"ZZZ": []})]
    elif mutation == "order":
        pages[:] = [
            page(query, {"MSFT": [{"t": "2019-03-01T14:45:30.5Z"}]}, next_token="next"),
            page(query, {"AAPL": [{"t": "2019-03-01T14:45:30.5Z"}]}, token="next"),
        ]
    elif mutation == "token":
        pages[-1] = page(query, {}, token="wrong")
    elif mutation == "asof":
        pages[0]["url"] = pages[0]["url"].replace("asof=2026-10-12", "asof=2019-03-01")
    elif mutation == "bodyhash":
        pages[0]["sha256"] = "0" * 64
    elif mutation == "group":
        value["groups"].pop(key)
    elif mutation == "pagecap":
        pages[:] = [deepcopy(pages[0]) for _ in range(11)]
    else:
        raw = (
            b'{"quotes":{"AAPL":[{"t":"2019-03-01T14:45:30.5Z","p":1e999}]},"next_page_token":null}'
            if mutation == "nan"
            else b'{"quotes":{},"quotes":{},"next_page_token":null}'
        )
        pages[:] = [page(query, {})]
        pages[0].update(body_base64=base64.b64encode(raw).decode(), sha256=sha(raw))
    expected = {
        "short": "Short pages",
        "extra": "Short pages",
        "http": "Acquisition failure",
        "future": "Actual acquisition clocks",
        "failed": "Failed/incomplete capture",
        "truncated": "Truncated/failed body",
        "symbol": "Unexpected symbol",
        "order": "symbol-first pagination",
        "token": "Exact fixed query",
        "asof": "Exact fixed query",
        "bodyhash": "Original provider body",
        "group": "Every original required group",
        "pagecap": "group page cap",
        "nan": "Out of range float",
        "duplicate_key": "Duplicate JSON key",
    }[mutation]
    with pytest.raises(ValueError, match=expected):
        parse(value, manifest, reg)


# Pause at resource caps without resetting counters or extending windows.
@pytest.mark.parametrize("counter", ["get_attempts", "body_bytes"])
def test_global_cap(counter):
    reg = source_registry()
    used = {"get_attempts": 0, "body_bytes": 0}
    used[counter] = demand.BUDGET[counter]
    manifest = declaration(reg, used=used)
    with pytest.raises(ValueError, match="Resource cap"):
        parse(capture(reg, manifest), manifest, reg)


# Append a synthetic cycle with receipt hashes and monotone usage.
def cycle(chain=None, cycle_id="a" * 64, count=7):
    chain = [] if chain is None else chain
    for stage in checkpoint.STAGES[:count]:
        chain = checkpoint.append(
            chain,
            identity_sha256="1" * 64,
            cycle_sha256=cycle_id,
            stage=stage,
            receipt_sha256=_digest([cycle_id, stage]),
            used={"get_attempts": len(chain), "body_bytes": len(chain) * 10},
            expected_head=chain[-1]["sha256"] if chain else None,
        )
    return chain


# Resume an exact paused stage without repeating decision or native submission receipts.
def test_checkpoint_resume_is_next_stage_only():
    chain = cycle(count=3)
    frozen = deepcopy(chain)
    state = checkpoint.verify(
        chain, identity_sha256="1" * 64, expected_head=chain[-1]["sha256"]
    )
    assert state["next_stage"] == "PACKETS_FINALIZED"
    for stage in checkpoint.STAGES[3:]:
        chain = checkpoint.append(
            chain,
            identity_sha256="1" * 64,
            cycle_sha256="a" * 64,
            stage=stage,
            receipt_sha256=_digest(stage),
            used={"get_attempts": 3, "body_bytes": 30},
            expected_head=chain[-1]["sha256"],
        )
    assert chain[:3] == frozen
    assert (
        checkpoint.verify(
            chain, identity_sha256="1" * 64, expected_head=chain[-1]["sha256"]
        )["next_stage"]
        == "PRIOR_VERIFIED"
    )
    with pytest.raises(ValueError, match="next checkpoint"):
        checkpoint.append(
            chain,
            identity_sha256="1" * 64,
            cycle_sha256="a" * 64,
            stage="SUBMISSION_CAPTURED",
            receipt_sha256="f" * 64,
            used={"get_attempts": 3, "body_bytes": 30},
            expected_head=chain[-1]["sha256"],
        )


# Refuse altered heads, identity, stage order and resource counters.
@pytest.mark.parametrize(
    "mutation", ["head", "identity", "parent", "stage", "usage", "cycle"]
)
def test_checkpoint_corruption(mutation):
    chain = cycle(count=4)
    expected = chain[-1]["sha256"]
    if mutation == "head":
        expected = "f" * 64
    else:
        row = chain[-1]
        if mutation == "identity":
            row["identity_sha256"] = "f" * 64
        elif mutation == "parent":
            row["parent"] = "f" * 64
        elif mutation == "stage":
            row["stage"] = "SUBMISSION_CAPTURED"
        elif mutation == "usage":
            row["used"] = {"get_attempts": 0, "body_bytes": 0}
        else:
            row["cycle_sha256"] = "f" * 64
        row["sha256"] = _digest({k: v for k, v in row.items() if k != "sha256"})
        expected = row["sha256"]
    with pytest.raises(ValueError, match="head|identity|stage|usage|cycle"):
        checkpoint.verify(chain, identity_sha256="1" * 64, expected_head=expected)


# Prevent restarting a completed old cycle after another cycle was committed.
def test_completed_cycle_cannot_be_replayed_later():
    chain = cycle(cycle(cycle_id="a" * 64), cycle_id="b" * 64)
    with pytest.raises(ValueError, match="cannot be repeated"):
        cycle(chain, cycle_id="a" * 64, count=1)


# Keep immutable bytes detached from mutable read results.
def test_registry_and_demand_remain_immutable():
    reg = source_registry()
    manifest = declaration(reg)
    exposed = demand.read(manifest, reg)
    exposed["held"].clear()
    assert demand.read(manifest, reg)["held"] == ["MSFT"]
    with pytest.raises(ValueError, match="Pinned original bytes"):
        registry.entries(registry.Registry(reg.raw + b" ", reg.sha256, reg.evidence))


# Bound each group while retaining every name and its individually frozen lookup date.
def test_many_names_group_deterministically_without_dropping_held_names():
    names = tuple("S" + str(i).zfill(2) for i in range(10))
    reg = source_registry(names)
    manifest = declaration(reg, held=list(names), legs=[])
    queries = demand.read(manifest, reg)["queries"]
    assert [len(q["cohort_keys"]) for q in queries] == [8, 2]
    assert [n for q in queries for n in q["cohort_keys"]] == list(names)
    assert all(q["kind"] == "quotes" for q in queries)


# Do not combine distinct entity lookup dates merely because event windows coincide.
def test_lookup_dates_are_per_mapping_not_session_defaults():
    original = source_registry()
    data = registry.pinned(original.raw, original.sha256)
    data["entries"][1]["entity_asof"] = "2026-09-01"
    raw = demand.encoded(data)
    reg = registry.registry(raw, sha(raw), dict(original.evidence))
    queries = demand.read(declaration(reg), reg)["queries"]
    quote_queries = [q for q in queries if q["kind"] == "quotes"]
    assert len(quote_queries) == 2
    assert {q["parameters"]["asof"] for q in quote_queries} == {
        "2026-09-01",
        "2026-10-12",
    }


# Preserve paused-attempt counters without repeating decisions or submissions.
def test_acquisition_progress_preserves_same_cycle_and_monotone_budget():
    chain = cycle(count=3)
    for index in (10, 11):
        chain = checkpoint.append(
            chain,
            identity_sha256="1" * 64,
            cycle_sha256="a" * 64,
            stage="ACQUISITION_PROGRESS",
            receipt_sha256=_digest(["failed-or-incomplete", index]),
            used={"get_attempts": index, "body_bytes": index * 10},
            expected_head=chain[-1]["sha256"],
        )
    state = checkpoint.verify(
        chain, identity_sha256="1" * 64, expected_head=chain[-1]["sha256"]
    )
    assert state["next_stage"] == "PACKETS_FINALIZED"
    assert state["used"] == {"get_attempts": 11, "body_bytes": 110}
    assert state["cycle_sha256"] == "a" * 64
    with pytest.raises(ValueError, match="Receipt already consumed"):
        checkpoint.append(
            chain,
            identity_sha256="1" * 64,
            cycle_sha256="a" * 64,
            stage="ACQUISITION_PROGRESS",
            receipt_sha256=chain[-1]["receipt_sha256"],
            used=state["used"],
            expected_head=chain[-1]["sha256"],
        )


# No-intent and no-position demand remains empty evidence rather than an invented HOLD.
def test_empty_demand_is_not_a_model_action_or_zero_price():
    reg = source_registry()
    manifest = declaration(reg, held=[], legs=[])
    value = {
        "schema": "historical-demand-capture/1",
        "demand_sha256": manifest.sha256,
        "complete": True,
        "failure": None,
        "groups": {},
    }
    result = parse(value, manifest, reg)
    assert result["groups"] == {}
    assert result["used"] == {"get_attempts": 0, "body_bytes": 0}
    assert result["post_resolution_marks"].startswith("UNRESOLVED")
