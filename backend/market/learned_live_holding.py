"""Installed learned sizing on authenticated current nightly data.

An explicit reviewed release is required before this factory can select the
paper account. Numeric publication is not economic proof or release approval.
"""

import json
from dataclasses import replace
from datetime import datetime
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

from backend.market import calendar, holding_risk_bank, learned_live_timing
from backend.market import forward_arithmetic as forward
from backend.market import joint_funded_policy as funded
from backend.market import sequential_shadow_context as context

CONFIG = "desk/learned-holding/config.json"


# Keep ordinary nightly planning unchanged unless an explicit release is installed.
def configured(root):
    return (Path(root) / CONFIG).is_file()


# Restrict all installed artifacts to the learned-holding release directory.
def _folder(root, name):
    base = (Path(root) / CONFIG).parent.resolve()
    if not isinstance(name, str) or not name or Path(name).is_absolute():
        raise ValueError("Relative installed holding artifact directory required")
    path = (base / name).resolve()
    if path == base or not path.is_relative_to(base):
        raise ValueError("Holding artifacts must remain under their installed root")
    return path


# Bind approval to every production module that prepares, sizes and sends the plan.
def source_identity():
    root = Path(__file__).resolve().parents[2]
    paths = (
        Path(__file__),
        Path(holding_risk_bank.__file__),
        Path(learned_live_timing.__file__),
        Path(funded.__file__),
        Path(context.__file__),
        root / "backend/cli/market_daily.py",
        root / "backend/agents/trading/desk/nightly_plan.py",
        root / "backend/agents/trading/desk/intraday_orders.py",
        root / "backend/agents/trading/desk/funded_execution.py",
        root / "backend/agents/trading/desk/paper.py",
        root / "backend/agents/trading/desk/event_execution.py",
        root / "backend/agents/trading/desk/event_risk.py",
        root / "backend/market/adaptive_growth_policy.py",
        root / "backend/market/market_conditioned_holding.py",
        root / "backend/market/forward_arithmetic.py",
        root / "backend/market/forward_execution.py",
        root / "backend/market/forward_probability_timing.py",
        root / "backend/market/forward_market_evidence.py",
        root / "backend/market/live_probability_timing.py",
        root / "backend/market/entry_timing.py",
        root / "backend/market/alpaca_trading.py",
        root / "backend/market/learned_personal_guidance.py",
        root / "backend/market/learned_order_observation.py",
        root / "backend/market/decision_view.py",
        root / "backend/market/personal_history.py",
        root / "backend/api/v1/market.py",
    )
    return {
        str(path.relative_to(root)): sha256(path.read_bytes()).hexdigest()
        for path in paths
    }


# Require explicit reviewed source and evidence approval, never an artifact's test flag.
def _release(root, config, now):
    raw = (Path(root) / CONFIG).with_name("release.json").read_bytes()
    if sha256(raw).hexdigest() != config["release_receipt_sha256"]:
        raise ValueError("Original holding release approval differs")
    release = json.loads(raw)
    if (
        set(release)
        != {
            "schema",
            "policy",
            "approved_at",
            "source_sha256",
            "evidence_sha256",
            "approved",
        }
        or release["schema"] != "learned-holding-release/1"
        or release["policy"] != funded.MARKET_TIMED_POLICY
        or release["approved"] is not True
        or release["source_sha256"] != source_identity()
        or context._instant(release["approved_at"], "Release") > now
    ):
        raise ValueError("Exact reviewed learned holding release required")
    evidence = (Path(root) / CONFIG).with_name("evidence.json").read_bytes()
    if sha256(evidence).hexdigest() != release["evidence_sha256"]:
        raise ValueError("Reviewed complete economic evidence differs")
    return release


# Bind current daily bytes to the report before inference or account access.
def _inputs(root, report, now):
    panel = report.panel
    day = panel.dates[-1].astype(object)
    close, _ = forward._close_window(panel.dates[-1], now)
    sources, publications = {}, []
    for column, name in enumerate(panel.tickers):
        path = Path(root) / "bars" / ("asof=" + day.isoformat()) / (name + ".parquet")
        days, adjusted, _, published = context._daily(path, name, day, now, sources)
        # Reparse the same authenticated bytes to bind raw-share marks and all features.
        raw = path.read_bytes()
        if sha256(raw).hexdigest() != sources[str(path.absolute())]["sha256"]:
            raise ValueError("Concurrent current daily bytes differ")
        values = pq.read_table(pa.BufferReader(raw)).to_pydict()
        rows = np.searchsorted(panel.dates, days)
        usable = (rows < len(panel.dates)) & (days >= panel.dates[0])
        rows, days = rows[usable], days[usable]
        if not np.array_equal(panel.dates[rows], days):
            raise ValueError("Current source calendar differs from report")
        for field, original in (
            ("adj_close", adjusted),
            ("open", values["open"]),
            ("high", values["high"]),
            ("low", values["low"]),
            ("close", values["close"]),
            ("volume", values["volume"]),
        ):
            expected = np.full(len(panel.dates), np.nan)
            expected[rows] = np.asarray(original, dtype=float)[usable]
            if not np.array_equal(
                getattr(panel, field)[:, column], expected, equal_nan=True
            ):
                raise ValueError(
                    "Current report differs from original daily bytes: " + field
                )
        publications.append(published)
    if not close <= max(publications) <= now:
        raise ValueError("Available completed current daily publications required")
    context._check_unchanged(sources)
    grades = np.asarray(report.graded.grades)
    membership = grades >= 0
    for benchmark in ("SPY", "QQQ"):
        if benchmark in panel.tickers:
            membership[:, panel.index(benchmark)] = False
    return (
        grades,
        membership,
        {
            "data_as_of": now.isoformat(),
            "daily_published_at": max(publications).isoformat(),
            "grade_observed_at": now.isoformat(),
            "grade_basis": (
                "current_nightly_report_not_reconstructed_historical_publications"
            ),
            "grade_sha256": forward.reference._hash(grades),
            "sources": sources,
            "basis": "current_yahoo_split_and_dividend_adjusted_daily",
        },
    )


# Complete only the observed benchmark omitted by the ordinary nightly stock panel.
def _model_report(root, report, symbols, now):
    panel = report.panel
    if tuple(panel.tickers) == tuple(symbols):
        return report
    missing = set(symbols) - set(panel.tickers)
    if missing != {"QQQ"} or set(panel.tickers) - set(symbols):
        raise ValueError("Current nightly stock cohort differs from installed model")
    day = panel.dates[-1].astype(object)
    path = Path(root) / "bars" / ("asof=" + day.isoformat()) / "QQQ.parquet"
    sources = {}
    days, _, _, _ = context._daily(path, "QQQ", day, now, sources)
    raw = path.read_bytes()
    if sha256(raw).hexdigest() != sources[str(path.absolute())]["sha256"]:
        raise ValueError("Concurrent current benchmark bytes differ")
    values = pq.read_table(pa.BufferReader(raw)).to_pydict()
    rows = np.searchsorted(panel.dates, days)
    usable = (rows < len(panel.dates)) & (days >= panel.dates[0])
    rows, days = rows[usable], days[usable]
    if not np.array_equal(panel.dates[rows], days):
        raise ValueError("Current benchmark calendar differs from nightly report")
    arrays = {}
    grades = np.full((len(panel.dates), len(symbols)), -1, dtype=float)
    for field in ("open", "high", "low", "close", "adj_close", "volume"):
        array = np.full(grades.shape, np.nan)
        for column, name in enumerate(symbols):
            if name == "QQQ":
                key = "adjusted_close" if field == "adj_close" else field
                array[rows, column] = np.asarray(values[key], dtype=float)[usable]
            else:
                original = panel.index(name)
                array[:, column] = getattr(panel, field)[:, original]
                grades[:, column] = report.graded.grades[:, original]
        arrays[field] = array
    context._check_unchanged(sources)
    return SimpleNamespace(
        panel=replace(panel, tickers=tuple(symbols), **arrays),
        graded=SimpleNamespace(grades=grades),
    )


# Admit matching published execution heads and residuals before planning funded legs.
def _timing(root, config, original, now):
    from backend.market import forward_execution, forward_probability_timing
    from backend.market.live_probability_timing import POLICY

    raw = (Path(root) / learned_live_timing.CONFIG).read_bytes()
    timing = json.loads(raw)
    if (
        set(timing)
        != {
            "policy",
            "model_directory",
            "model_receipt_sha256",
            "residual_directory",
            "residual_receipt_sha256",
            "cost_bps",
        }
        or sha256(raw).hexdigest() != config["timing_config_sha256"]
        or timing["policy"] != POLICY
        or timing["cost_bps"] != config["cost_bps"]
    ):
        raise ValueError("Installed holding and execution configuration differ")
    _, publication = forward_execution.load_publication(
        learned_live_timing._folder(root, timing["model_directory"]),
        receipt_sha256=timing["model_receipt_sha256"],
        observed_at=now,
    )
    residual = forward_probability_timing.load_residual_month(
        learned_live_timing._folder(root, timing["residual_directory"]),
        receipt_sha256=timing["residual_receipt_sha256"],
        observed_at=now,
    )
    identity = residual.receipt["identity"]
    if (
        tuple(identity["symbols"]) != original.symbols
        or publication["identity"]["input_identity"].get("cohort")
        != identity["archive_identity"]["cohort"]
        or publication["training"]["fit_date"] != identity["fit_date"]
    ):
        raise ValueError("Original holding and timing cohort/month differ")
    return raw


# Preserve the original funded policy while binding its installed release and inputs.
class InstalledHoldingPolicy(funded.MarketConditionedTimedFundedPolicy):
    # Freeze the admitted release configuration for this one nightly decision.
    def __init__(self, reader, cost_bps, root, config_bytes, admission, observed_at):
        super().__init__(reader, cost_bps)
        self.root = Path(root)
        self.config_bytes = config_bytes
        self.admission = admission
        self.observed_at = observed_at

    # Refuse changed artifacts and any endpoint other than the actual paper broker.
    def admit_broker(self, client, decision_at):
        from backend.market.alpaca_trading import PAPER_URL, AlpacaTradingClient

        if type(client) is not AlpacaTradingClient or client.base_url != PAPER_URL:
            raise ValueError("Installed learned policy permits only the paper endpoint")
        if (
            decision_at != self.observed_at
            or (self.root / CONFIG).read_bytes() != self.config_bytes
        ):
            raise ValueError(
                "Installed nightly configuration or decision clock changed"
            )
        config = json.loads(self.config_bytes)
        if self.cost_bps != config["cost_bps"]:
            raise ValueError(
                "Installed policy costs differ from the approved configuration"
            )
        _release(self.root, config, decision_at)
        if (
            sha256((self.root / learned_live_timing.CONFIG).read_bytes()).hexdigest()
            != config["timing_config_sha256"]
        ):
            raise ValueError("Installed timing changed before nightly account effects")
        context._check_unchanged(self.admission["provenance"]["sources"])
        timestamp = context._instant(client.clock()["timestamp"], "Paper clock")
        if timestamp < decision_at:
            raise ValueError(
                "Paper broker clock precedes the observed nightly decision"
            )
        self.reader.validate_clock(timestamp)
        self.reader.validate_clock(decision_at)


# Authenticate one installed configuration for nightly and personal decision readers.
def read_configuration(root, now):
    raw = (Path(root) / CONFIG).read_bytes()
    config = json.loads(raw)
    if (
        set(config)
        != {
            "policy",
            "risk_directory",
            "risk_receipt_sha256",
            "model_directory",
            "model_receipt_sha256",
            "cost_bps",
            "timing_config_sha256",
            "release_receipt_sha256",
        }
        or config["policy"] != funded.MARKET_TIMED_POLICY
        or isinstance(config["cost_bps"], bool)
        or not isinstance(config["cost_bps"], (int, float))
        or not np.isfinite(config["cost_bps"])
        or not 0 <= config["cost_bps"] < 10000
    ):
        raise ValueError("Exact installed learned holding configuration required")
    _release(root, config, now)
    return raw, config


# Restore original risk and monthly heads, then retain dated current inference.
def prepare(root, report, *, clock=None):
    clock = clock or (lambda: datetime.now(calendar.NEW_YORK))
    started = context._instant(clock(), "Nightly observation")
    raw, config = read_configuration(root, started)
    original, _ = holding_risk_bank.load_bank(
        _folder(root, config["risk_directory"]),
        receipt_sha256=config["risk_receipt_sha256"],
        observed_at=started,
    )
    timing_bytes = _timing(root, config, original, started)
    model_folder = _folder(root, config["model_directory"])
    inference_report = _model_report(root, report, original.symbols, started)
    grades, membership, provenance = _inputs(root, inference_report, started)
    current = forward.observe_close(
        inference_report.panel,
        grades,
        membership,
        provenance,
        model_folder,
        model_receipt_sha256=config["model_receipt_sha256"],
        observed_at=started,
    )
    parent = (Path(root) / CONFIG).parent / "observations"
    parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    folder = parent / uuid4().hex
    digest = forward.write_close(folder, current, clock=clock)
    folder.chmod(0o700)
    for path in folder.iterdir():
        path.chmod(0o600)
    completed = context._instant(clock(), "Nightly completion")
    current = forward.load_close(
        folder, model_folder, receipt_sha256=digest, observed_at=completed
    )
    reader = forward.ForwardVolatilityHoldingReader(original, current)
    reader.validate_report(report)
    context._check_unchanged(provenance["sources"])
    if (Path(root) / CONFIG).read_bytes() != raw or (
        Path(root) / learned_live_timing.CONFIG
    ).read_bytes() != timing_bytes:
        raise ValueError("Concurrent installed policy configuration changes")
    admission = {
        "close_receipt_sha256": digest,
        "close_directory": str(folder),
        "config_sha256": sha256(raw).hexdigest(),
        "provenance": provenance,
    }
    return InstalledHoldingPolicy(
        reader, config["cost_bps"], root, raw, admission, completed
    )
