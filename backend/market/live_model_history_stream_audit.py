"""Stream original nightly evidence without replaying an account or approving timing."""

import gzip
import io
import json
import os
import stat
from copy import deepcopy
from dataclasses import asdict, dataclass
from datetime import timedelta
from hashlib import sha256
from pathlib import Path
from types import MappingProxyType, SimpleNamespace

import numpy as np

from backend.agents.trading.desk import event_risk, paper
from backend.cli import market_strategy_continue as continuation
from backend.cli import verify_actual_policy_timing as economic
from backend.cli.verify_live_model_history import (
    complete_cohort,
    physical_attempt,
    physical_fill,
)
from backend.market import (
    calendar,
    intraday_sip,
    learned_live_holding,
    live_policy_replay,
)
from backend.market import live_model_history_nightly_audit as controls
from backend.market import live_model_history_nightly_model as numerical
from backend.market import live_model_history_pending_audit as pending
from backend.market.live_model_history import FrozenCurrentGradePolicy
from backend.market.live_model_history_binding import (
    REVIEW_SHA256,
    REVIEWS,
    reviewed_sources,
)
from backend.market.live_model_history_receipts import ReceiptLedger, instant, require
from backend.market.store import MarketStore

MAX_STATE_BYTES = 256 * 1024 * 1024
MAX_METADATA_BYTES = 16 * 1024 * 1024
HASH_CHUNK_BYTES = 1024 * 1024
SOURCE_PATHS = (
    "backend/market/live_model_history.py",
    "backend/market/live_policy_replay.py",
    "backend/cli/market_strategy_continue.py",
    "backend/market/replay_broker.py",
    "backend/market/direct_daily_arithmetic.py",
    "backend/market/learned_retention_models.py",
)


# Hash the complete JSON representation without treating approximate shares as equal.
def digest(value):
    return sha256(
        json.dumps(
            numerical.serialized(value), sort_keys=True, allow_nan=False
        ).encode()
    ).hexdigest()


# Validate an external content identity without accepting coerced digest values.
def expected_digest(expected):
    require(
        type(expected) is str
        and len(expected) == 64
        and all(char in "0123456789abcdef" for char in expected),
        "External original evidence digest required",
    )


# Identify the same regular file before and after an authenticated read.
def file_identity(value):
    require(stat.S_ISREG(value.st_mode), "Regular original evidence file required")
    return (
        value.st_dev,
        value.st_ino,
        value.st_size,
        value.st_mtime_ns,
        value.st_ctime_ns,
    )


# Reject concurrent replacement or size/content changes while evidence is read.
def stable_file(stream, path, before):
    require(
        file_identity(os.fstat(stream.fileno())) == before
        and file_identity(path.stat()) == before,
        "Original evidence changed during authentication",
    )


# Read small metadata only after its size check, with a bounded growth sentinel.
def pinned(path, expected, *, max_bytes=None):
    expected_digest(expected)
    limit = MAX_METADATA_BYTES if max_bytes is None else max_bytes
    require(type(limit) is int and limit >= 0, "Exact evidence size bound required")
    path = Path(path)
    before = file_identity(path.stat())
    require(before[2] <= limit, "Original metadata size exceeds bound")
    with path.open("rb") as stream:
        require(
            file_identity(os.fstat(stream.fileno())) == before,
            "Original evidence changed before reading",
        )
        raw = stream.read(limit + 1)
        require(len(raw) <= limit, "Original metadata size exceeds bound")
        stable_file(stream, path, before)
    require(sha256(raw).hexdigest() == expected, "Pinned stream input bytes differ")
    return raw


# Authenticate large source/model/input files with fixed-memory digest-only reads.
def authenticate_file(path, expected):
    expected_digest(expected)
    path = Path(path)
    before = file_identity(path.stat())
    value = sha256()
    with path.open("rb") as stream:
        require(
            file_identity(os.fstat(stream.fileno())) == before,
            "Original evidence changed before hashing",
        )
        while chunk := stream.read(HASH_CHUNK_BYTES):
            value.update(chunk)
        stable_file(stream, path, before)
    require(value.hexdigest() == expected, "Pinned stream input bytes differ")
    return value.hexdigest()


# Reject duplicate fields, nonfinite constants and overflow in every metadata route.
def strict_json(raw):
    require(type(raw) is bytes, "Immutable original JSON bytes required")
    return json.loads(
        raw,
        object_pairs_hook=pending.unique,
        parse_constant=pending.reject_constant,
        parse_float=pending.finite_float,
    )


# Reject ordinary mutation of an already admitted nested metadata value.
def _immutable(*args, **kwargs):
    raise TypeError("Admitted original metadata is readonly")


# Retain dict-compatible reads without exposing mutable admitted expectations.
class _ReadOnlyDict(dict):
    __slots__ = ()

    # Populate once during construction, before this mapping is exposed.
    def __new__(cls, value):
        result = dict.__new__(cls)
        dict.update(result, value)
        return result

    # Reinitializing an admitted mapping cannot replace its contents.
    def __init__(self, value):
        pass

    # Immutable nested metadata can be shared safely by detached audit copies.
    def __deepcopy__(self, memo):
        return self

    __setitem__ = __delitem__ = __ior__ = _immutable
    clear = pop = popitem = setdefault = update = _immutable


# Retain list-compatible reads while blocking mutations of admitted session records.
class _ReadOnlyList(list):
    __slots__ = ()

    # Populate once during construction, with already frozen nested values.
    def __new__(cls, value):
        result = list.__new__(cls)
        list.extend(result, value)
        return result

    # Reinitializing an admitted sequence cannot change its records.
    def __init__(self, value):
        pass

    # Immutable session metadata needs no mutable duplicate during audit copying.
    def __deepcopy__(self, memo):
        return self

    __setitem__ = __delitem__ = __iadd__ = __imul__ = _immutable
    append = clear = extend = insert = pop = remove = reverse = sort = _immutable


# Freeze admitted metadata once after removing the large comparison-only final state.
def _freeze(value):
    if type(value) is dict:
        return _ReadOnlyDict({name: _freeze(row) for name, row in value.items()})
    if type(value) is list:
        return _ReadOnlyList([_freeze(row) for row in value])
    return value


# Decode bounded original gzip bytes with strict finite and duplicate-free JSON.
def archive_value(raw):
    require(
        len(raw) <= pending.MAX_COMPRESSED_BYTES, "Original stream archive too large"
    )
    with gzip.GzipFile(fileobj=io.BytesIO(raw)) as stream:
        expanded = stream.read(pending.MAX_JSON_BYTES + 1)
    require(
        len(expanded) <= pending.MAX_JSON_BYTES, "Original stream expansion too large"
    )
    return strict_json(expanded)


# Admit optional standalone initial venue facts only under an external byte identity.
@dataclass(frozen=True, slots=True)
class InitialReceipts:
    raw: bytes

    # Keep a separate original receipt file outside the saved initial control state.
    def __init__(self, path, expected_sha256):
        object.__setattr__(self, "raw", pinned(path, expected_sha256))

    # Decode venue attempts without borrowing saved control metadata.
    def attempts(self):
        value = strict_json(self.raw)
        require(type(value) is list, "Original standalone initial attempts required")
        return deepcopy(value)


# Retain authenticated metadata and yield only one immutable session archive at a time.
@dataclass(frozen=True, slots=True)
class OriginalArchives:
    root: Path
    completion_raw: bytes
    completion: dict
    initial_sha256: str
    manifest_path: Path
    manifest_sha256: str
    sources: dict
    ending_state: str
    source_root: Path
    _consumed_inputs: dict
    unused_inputs: int

    # Bind the completed account, initial state and original source manifest externally.
    def __init__(
        self, root, completion_sha256, initial_sha256, manifest, manifest_sha256
    ):
        root = Path(root)
        completion_raw = pinned(
            root / "completion.json", completion_sha256, max_bytes=MAX_STATE_BYTES
        )
        completion = strict_json(completion_raw)
        require(
            completion["status"] == "COMPLETED_UNVERIFIED_CURRENT_MODEL_ACCOUNT",
            "Genuine completed original account required",
        )
        ending_state = digest(completion.pop("paper_state"))
        values = {
            "root": root,
            "completion_raw": completion_raw,
            "completion": _freeze(completion),
            "initial_sha256": initial_sha256,
            "manifest_path": Path(manifest),
            "manifest_sha256": manifest_sha256,
            "sources": _freeze(strict_json(pinned(manifest, manifest_sha256))["files"]),
            "ending_state": ending_state,
            "source_root": Path(__file__).resolve().parents[2],
            "_consumed_inputs": {},
            "unused_inputs": 0,
        }
        for name, value in values.items():
            object.__setattr__(self, name, value)

    # Expose bookkeeping read-only without allowing callers to replace evidence.
    @property
    def consumed_inputs(self):
        return MappingProxyType(self._consumed_inputs)

    # Admit only exact original financial code and the existing explicit source reviews.
    def authenticate_sources(self):
        reviewed_sources(
            self.completion["source_sha256"],
            learned_live_holding.source_identity(),
            [REVIEW_SHA256[name] for name in REVIEWS],
        )
        for name in SOURCE_PATHS:
            authenticate_file(self.source_root / name, self.sources[name])
        require(
            {name: self.sources[name] for name in pending.ORIGINAL_SOURCES}
            == pending.ORIGINAL_SOURCES,
            "Exact original legacy producer profile required",
        )

    # Authenticate consumed inputs without reading unused legacy execution grids.
    def authenticate_inputs(self, market):
        capture_raw = pinned(
            Path(market) / "capture.json", self.completion["capture_sha256"]
        )
        capture = strict_json(capture_raw)
        self._consumed_inputs.clear()
        self._consumed_inputs.update(
            {str(Path(market) / "capture.json"): self.completion["capture_sha256"]}
        )
        for name, expected in capture["files"].items():
            require(
                not Path(name).is_absolute() and ".." not in Path(name).parts,
                "Relative original capture path required",
            )
            authenticate_file(Path(market) / name, expected)
            self._consumed_inputs[str(Path(market) / name)] = expected
        checked = set()
        for name, expected in self.completion["input_sha256"].items():
            if (
                name.startswith((str(Path(market)) + "/", "/observation/", "/actions/"))
                or name
                == "/app/docs/research/actual-policy-action-review-2026-10-04.json"
            ):
                authenticate_file(name, expected)
                checked.add(name)
                self._consumed_inputs[name] = expected
        object.__setattr__(
            self, "unused_inputs", len(set(self.completion["input_sha256"]) - checked)
        )
        return capture

    # Read the initial prior-close snapshot as a comparison target, never a state seed.
    def initial(self):
        return archive_value(
            pinned(
                self.root / "initial.json.gz",
                self.initial_sha256,
                max_bytes=pending.MAX_COMPRESSED_BYTES,
            )
        )

    # Read one original session only after its completion-bound digest matches.
    def sessions(self):
        for record in self.completion["sessions"]:
            name = record["session"]
            require(
                type(name) is str
                and len(name) == 10
                and instant(name + "T00:00:00+00:00").date().isoformat() == name,
                "Exact original stream session required",
            )
            raw = pinned(
                self.root / "sessions" / (name + ".json.gz"),
                record["sha256"],
                max_bytes=pending.MAX_COMPRESSED_BYTES,
            )
            value = archive_value(raw)
            require(value["session"] == name, "Original stream session differs")
            evidence = pending.OriginalProxyEvidence(
                raw,
                record["sha256"],
                {name: self.sources[name] for name in pending.ORIGINAL_SOURCES},
            )
            yield value, evidence

    # Recheck immutable source and account selectors without rewriting original files.
    def unchanged(self):
        authenticate_file(
            self.root / "completion.json", sha256(self.completion_raw).hexdigest()
        )
        authenticate_file(self.root / "initial.json.gz", self.initial_sha256)
        authenticate_file(self.manifest_path, self.manifest_sha256)
        for path, expected in self._consumed_inputs.items():
            authenticate_file(path, expected)
        self.authenticate_sources()


# Derive marks for inherited held assets without manufacturing a current raw price.
def closing_marks(raw, day, at):
    return live_policy_replay.account_marks(raw, day, at, raw.daily_close[day])


# Copy cancellation receipts without importing saved allocation or target inputs.
def cancellation_receipts(value, accepted, outcomes, at):
    result = {}
    for row in value["paper_state"]["journal"]:
        execution = row.get("execution", {})
        if execution.get("canceled_at") != at:
            continue
        cid = row["client_order_id"]
        require(
            cid in accepted and cid not in outcomes, "Unconserved cancellation receipt"
        )
        require(cid not in result, "Duplicate original cancellation receipt")
        result[cid] = {
            key: deepcopy(row[key])
            for key in (
                "client_order_id",
                "symbol",
                "side",
                "qty",
                "status",
                "terminal",
                "filled_qty",
            )
        }
        result[cid]["execution"] = {
            key: execution[key] for key in ("created_at", "submitted_at", "canceled_at")
        }
    return result


# Compare complete independent economic balances without importing saved ledger values.
def compare_account(value, cash, held, basis, dividends, records):
    for name, expected in (
        ("cash", cash),
        ("holdings", held),
        ("average_prices", basis),
        ("dividends", dividends),
    ):
        economic.same(value["broker"][name], expected, "Stream independent " + name)
    for name, expected in records.items():
        economic.same(
            value["broker"].get(name, []), expected, "Stream entitlement " + name
        )


# Select literal same-close facts without using them to choose orders.
def candidate_acknowledgments(rows, accepted, at):
    result = deepcopy(accepted)
    seen = set()
    for row in rows:
        require(
            instant(row["at"]) == instant(at),
            "Exact new nightly receipt clock required",
        )
        cid = row["client_order_id"]
        require(
            cid not in seen and cid not in result,
            "Duplicate new nightly acknowledgment",
        )
        seen.add(cid)
        require(type(row["accepted"]) is bool, "Explicit nightly acceptance required")
        if row["accepted"]:
            result[cid] = deepcopy(row)
    return result


# Compose independent receipts, pending mutations and nightly state lineage.
class StreamAudit:
    # Start from independent zero shares and cash, never any saved paper-state controls.
    def __init__(
        self, archives, market, panel, raw, reader, holding, overlay, *, verified_at
    ):
        require(
            type(archives) is OriginalArchives,
            "Pinned original stream archives required",
        )
        archives.authenticate_sources()
        self.archives, self.market = archives, Path(market)
        self.panel, self.raw, self.reader = panel, raw, reader
        self.completion, self.verified_at = archives.completion, verified_at
        self.policy = FrozenCurrentGradePolicy(reader, holding["cost_bps"])
        capture = archives.authenticate_inputs(market)
        require(
            capture["source_sha256"] == self.completion["source_sha256"],
            "Original capture source profile differs",
        )
        original_holding = strict_json(
            pinned(
                Path(market) / "desk/learned-holding/config.json",
                self.completion["holding_config_sha256"],
            )
        )
        require(holding == original_holding, "Original holding configuration differs")
        for key in ("model_receipt_sha256", "risk_receipt_sha256"):
            require(
                holding[key] == self.completion[key], "Original model receipt differs"
            )
        require(
            holding["policy"] == self.completion["policy"]
            and holding["cost_bps"] == self.completion["cost_bps"] == 10
            and self.completion["real_orders"] is False
            and self.completion["base_models_fitted"] == 0,
            "Exact original frozen model and economics required",
        )
        require(
            numerical.serialized(reader._parent.identity)
            == self.completion["current_model_inference"],
            "Frozen model, feature and complete calibration identity differs",
        )
        self.tickers = complete_cohort(self.completion, overlay, panel)
        expected = panel.dates[
            (panel.dates >= np.datetime64(self.completion["first"]))
            & (panel.dates <= np.datetime64(self.completion["through"]))
        ]
        require(
            [row["session"] for row in self.completion["sessions"]]
            == list(map(str, expected)),
            "Complete original streaming session sequence required",
        )
        self.state, self.intents, self.receipts = (
            paper.PaperState(),
            {},
            ReceiptLedger(),
        )
        self.cash, self.held, self.basis, self.dividends, self.seen = (
            100000,
            {},
            {},
            [],
            set(),
        )
        self.records = {
            name: []
            for name in (
                "security_distributions",
                "share_consolidations",
                "security_exchanges",
                "cash_mergers",
            )
        }
        self.events = economic.source_events(
            {
                "actions": {str(name): rows for name, rows in raw.actions.items()},
                "inherited_actions": {
                    str(name): rows
                    for name, rows in (raw.inherited_actions or {}).items()
                },
            }
        )
        self.counts = {
            name: 0
            for name in (
                "nights",
                "model",
                "event_priority",
                "already_planned",
                "nightly_broker_unavailable",
                "intraday_transitions",
                "filled_receipts",
            )
        }
        self.chain = "0" * 64
        self.next_session = 0

    # Load only this session's authenticated raw quotes, not a full-history SIP grid.
    def quote_prefix(self, day):
        names, dates = self.panel.tickers, self.panel.dates
        require(
            type(day) is int and 0 <= day < len(dates),
            "Exact original quote row required",
        )
        session = str(dates[day])
        opened, closed = np.full(len(names), np.nan), np.full((25, len(names)), np.nan)
        for stock, name in enumerate(names):
            path = (
                self.market
                / "bars_15m_sip"
                / ("asof=" + session)
                / (str(name) + ".parquet")
            )
            expected = self.completion["input_sha256"].get(str(path))
            if expected is None:
                require(not path.exists(), "Original missing raw quote file changed")
                continue
            authenticate_file(path, expected)
            found = intraday_sip.read_session_full(
                MarketStore(self.market), str(name), dates[day].astype(object)
            )
            if found is None or found[2].get("complete") != "true":
                continue
            bars = found[0]
            opened[stock] = bars[0].open
            for slot in range(min(25, len(bars) - 1)):
                closed[slot, stock] = bars[slot].close
        # Readonly views retain global row coordinates without past quote grids.
        return SimpleNamespace(
            dates=dates,
            tickers=names,
            session_open=np.broadcast_to(opened, (len(dates), len(names))),
            observation_close=np.broadcast_to(closed, (len(dates), 25, len(names))),
        )

    # Fold authentic events and executions before the first nightly account read.
    def economic_close(self, value, day, at):
        opening = live_policy_replay.instant(
            self.panel.dates[day], calendar.REGULAR_OPEN
        )
        economic.fold_actions(
            self.events,
            opening,
            self.held,
            self.basis,
            self.dividends,
            self.records,
            self.seen,
            self.completion["broker"],
        )
        for fill in value["fills"]:
            physical_fill(self.market, fill, 10)
        self.cash = economic.fold_fills(
            value["fills"], self.cash, self.held, self.basis
        )
        economic.fold_actions(
            self.events,
            at,
            self.held,
            self.basis,
            self.dividends,
            self.records,
            self.seen,
            self.completion["broker"],
        )
        compare_account(
            value, self.cash, self.held, self.basis, self.dividends, self.records
        )
        return numerical.account(
            self.cash,
            self.held,
            self.basis,
            self.dividends,
            self.records,
            closing_marks(self.raw, day, at),
        )

    # Evaluate one close using only independently derived account and predecessor state.
    def nightly(self, value, day, intraday, observed, *, initial=False):
        session, at = value["session"], value["nightly"]["at"]
        original_previous = self.state
        prior_hash = digest(asdict(original_previous))
        if observed["problem"] is not None:
            pending.compare_unavailable(
                value, original_previous, intraday, observed, self.held, session, at
            )
            require(
                not value["attempts"],
                "Unavailable account has unvalidated nightly attempts",
            )
            self.state, mode = intraday, {"path": "nightly_broker_unavailable"}
        else:
            cancellations = cancellation_receipts(
                value, self.receipts.accepted, self.receipts.outcomes, at
            )
            before, settled, _ = controls.before_plan(
                intraday,
                self.receipts.accepted,
                self.receipts.outcomes,
                session,
                at,
                cancellations=cancellations,
            )
            report = continuation.close_report(
                self.panel, self.raw, self.raw.grades, self.raw.eligible, day
            )
            mode = controls.branch(before, event_risk.decision(report.panel), session)
            self.reader.select(day)
            if mode["model_required"]:
                numerical.prefix_model(self.panel, self.raw, self.reader, day)
            try:
                acknowledgments = candidate_acknowledgments(
                    value["attempts"], self.receipts.accepted, at
                )
                state, planned, entry, mode = numerical.pure_plan(
                    report,
                    self.policy,
                    before,
                    observed,
                    session,
                    at,
                    value["attempts"],
                    acknowledgments,
                )
            except ValueError as exc:
                if (
                    initial
                    and not value["attempts"]
                    and str(exc) == "Original immediate nightly attempt required"
                ):
                    raise ValueError(
                        "UNRECONSTRUCTIBLE_INITIAL_IMMEDIATE_RECEIPTS"
                    ) from exc
                raise
            self.state = numerical.compare_saved(
                value,
                original_previous,
                state,
                planned,
                entry,
                settled,
                report=report,
                started=self.completion["actual_started_at"],
                verified_at=self.verified_at,
            )
            for row in planned:
                cid = row["client_order_id"]
                require(
                    cid not in self.intents, "Duplicate independently planned identity"
                )
                self.intents[cid] = deepcopy(row)
        self.counts["nights"] += 1
        self.counts[mode["path"]] += 1
        self.chain = digest(
            {
                "previous_chain": self.chain,
                "prior_state_sha256": prior_hash,
                "session": session,
                "branch": mode["path"],
                "derived_state_sha256": digest(asdict(self.state)),
                "account_sha256": digest(observed),
            }
        )
        require(
            len(json.dumps(numerical.serialized(asdict(self.state))).encode())
            <= MAX_STATE_BYTES,
            "UNRECONSTRUCTIBLE_DERIVED_STATE_SIZE",
        )
        return mode

    # Recompute the real initial prior-close plan from an empty independent state.
    def initial(self, *, receipts=None):
        require(self.counts["nights"] == 0, "Initial stream close already consumed")
        require(
            receipts is None or type(receipts) is InitialReceipts,
            "Authenticated standalone initial receipts required",
        )
        original = self.archives.initial()
        first = int(
            np.searchsorted(self.panel.dates, np.datetime64(self.completion["first"]))
        )
        require(first > 0, "Original stream start needs prior close")
        day = first - 1
        value = {
            **original,
            "session": str(self.panel.dates[day]),
            "new_intents": original["intents"],
            "attempts": [] if receipts is None else receipts.attempts(),
            "fills": [],
        }
        require(
            value["nightly"]["session"] == value["session"],
            "Initial prior close differs",
        )
        at = instant(value["nightly"]["at"])
        observed = self.economic_close(value, day, at)
        mode = self.nightly(value, day, self.state, observed, initial=True)
        self.receipts.attempts(value["attempts"], self.intents, at)
        self.receipts.durable(
            numerical.serialized(asdict(self.state)), self.intents, at
        )
        self.receipts.funding(value["attempts"], [])
        self.receipts.last_state = at
        return mode

    # Process one immutable session with old intraday facts before new nightly requests.
    def step(self, value, evidence):
        session, at = value["session"], instant(value["nightly"]["at"])
        require(
            self.counts["nights"] > 0
            and self.next_session < len(self.completion["sessions"])
            and session == self.completion["sessions"][self.next_session]["session"],
            "Exact next original streaming session required",
        )
        day = int(np.searchsorted(self.panel.dates, np.datetime64(session)))
        require(
            day < len(self.panel.dates) and str(self.panel.dates[day]) == session,
            "Original stream day absent",
        )
        closing = at - timedelta(minutes=1)
        regular = [row for row in value["attempts"] if instant(row["at"]) < closing]
        nightly = [row for row in value["attempts"] if instant(row["at"]) >= closing]
        for row in value["attempts"]:
            require(
                row["reason"] != "terminated_security",
                "UNRECONSTRUCTIBLE_TERMINATED_ATTEMPT_CONTEXT",
            )
            physical_attempt(self.market, row, self.panel, self.raw)
        self.receipts.attempts(regular, self.intents, at)
        self.receipts.fills(value["fills"], self.intents, at)
        self.receipts.funding(regular, value["fills"])
        observed = self.economic_close(value, day, at)
        intraday, conserved = pending.fold_pending(
            self.state,
            evidence,
            self.receipts.accepted,
            self.receipts.outcomes,
            self.quote_prefix(day),
            day,
            session,
            conserved_attempts=regular,
        )
        self.counts["intraday_transitions"] += len(conserved["transitions"])
        target = {**value, "attempts": nightly}
        mode = self.nightly(target, day, intraday, observed)
        self.receipts.attempts(nightly, self.intents, at)
        self.receipts.durable(
            numerical.serialized(asdict(self.state)), self.intents, at
        )
        self.receipts.funding(nightly, [])
        economic.same(
            self.receipts.cash, self.cash, "Independent streaming cash ledgers differ"
        )
        self.receipts.last_state = at
        self.counts["filled_receipts"] += len(value["fills"])
        self.next_session += 1
        return mode

    # Finish only this audit scope, retaining the separate timing failure.
    def verify(self, *, initial_receipts=None):
        self.initial(receipts=initial_receipts)
        for value, evidence in self.archives.sessions():
            self.step(value, evidence)
        require(
            digest(asdict(self.state)) == self.archives.ending_state,
            "Complete final independently derived state differs",
        )
        require(
            len(self.intents) == self.completion["intents"],
            "Complete independently planned intent count differs",
        )
        require(
            self.counts["filled_receipts"] == self.completion["fills"],
            "Complete original execution count differs",
        )
        self.archives.unchanged()
        return {
            "status": "VERIFIED_STREAMED_ORIGINAL_NIGHTLY_AND_RECEIPT_CHECKS_ONLY",
            "counts": self.counts,
            "state_lineage_sha256": self.chain,
            "final_derived_state_sha256": digest(asdict(self.state)),
            "current_live_timing_parity": "FAILED_SEPARATE_ORIGINAL_PATH_CONTRACT",
            "historical_publication_authorized": False,
            "publication_barrier": "CLOSED",
            "console_stdout_recomputed": False,
            "complete_original_input_manifest_authentication": (
                "UNVERIFIED_SEPARATE_FULL_AUDIT_REQUIRED"
            ),
            "unused_original_inputs_not_read": self.archives.unused_inputs,
            "consumed_input_files_authenticated": len(self.archives.consumed_inputs),
            "account_replay_sender_broker_provider_calls": 0,
            "base_models_fitted": 0,
        }
