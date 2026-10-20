"""Publish model percentages before funded planning, without any account input.

Production admits the ordinary prepared policy and completed-close evidence.
The GET reader restores only finite JSON and checks original publication and
source identities; it never predicts, acquires prices, reads a paper state or
contacts a broker. A position percentage remains a nightly composition, not
an immediate trade amount or an intraday reoptimization.
"""

import json
import math
import os
from datetime import datetime, time, timedelta
from hashlib import sha256
from pathlib import Path
from uuid import uuid4

import numpy as np

from backend.market import adaptive_growth_policy as growth
from backend.market import calendar
from backend.market import grade_led_policy, learned_live_holding, live_model_decision
from backend.market import direct_daily_arithmetic, learned_entry_data, market_conditioned_calibration, probabilistic_execution
from backend.market import strategy_model_allocation
from backend.market.direct_daily_arithmetic import FEATURE_NAMES

VERSION = "strategy-model-allocation/2"
SCHEMA = "strategy-recommendation-publication/1"
DIRECTORY = "desk/strategy-recommendations"
MAX_BYTES = 262144
# The nightly cron publishes on weekdays at 19:30 New York (AGENTS.md, `30 19 * * 1-5`).
NIGHTLY_PUBLICATION = time(19, 30)


# A verified snapshot whose original validity window has closed, carried for display.
class ExpiredError(ValueError):
    # Carry the verified snapshot so the caller can show its last plan.
    def __init__(self, value):
        super().__init__("Original independent publication clock expired or differs")
        self.value = value


# Return the next scheduled nightly publish strictly after `now`, in New York time.
def next_publication_at(now):
    local = now.astimezone(calendar.NEW_YORK)
    candidate = datetime.combine(local.date(), NIGHTLY_PUBLICATION, calendar.NEW_YORK)
    while candidate < local or candidate.weekday() >= 5:
        candidate += timedelta(days=1)
    return candidate


# Hash exact finite public evidence independently of its later consumer or account.
def _digest(value):
    return sha256(json.dumps(value, sort_keys=True, allow_nan=False).encode()).hexdigest()


# Require original lowercase SHA identities before constructing a filesystem name.
def _sha(value):
    if not isinstance(value, str) or len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
        raise ValueError("Original SHA identity required")
    return value


# Pin the independently published calculator in addition to the approved native strategy.
def _sources():
    result = {**learned_live_holding.source_identity(),
            "backend/market/strategy_model_allocation.py": sha256(Path(strategy_model_allocation.__file__).read_bytes()).hexdigest(),
            "backend/market/strategy_publication.py": sha256(Path(__file__).read_bytes()).hexdigest()}
    for module in (direct_daily_arithmetic, learned_entry_data, market_conditioned_calibration, probabilistic_execution):
        result["backend/market/" + Path(module.__file__).name] = sha256(Path(module.__file__).read_bytes()).hexdigest()
    result['backend/market/strategy_entry_context.py'] = sha256(Path(__file__).with_name('strategy_entry_context.py').read_bytes()).hexdigest()
    result['backend/market/strategy_entries.py'] = sha256(Path(__file__).with_name('strategy_entries.py').read_bytes()).hexdigest()
    return result


# Identify the economic strategy without binding history to one funded record or publication date.
def _strategy_identity(sources, cost_bps):
    names = ("adaptive_growth_policy.py", "grade_led_policy.py", "joint_funded_policy.py",
             "market_conditioned_holding.py", "forward_arithmetic.py", "forward_execution.py",
             "live_probability_timing.py", "entry_timing.py", "direct_daily_arithmetic.py",
             "learned_entry_data.py", "market_conditioned_calibration.py", "probabilistic_execution.py")
    return _digest({"policy": grade_led_policy.POLICY,
                    "sources": {name: sources["backend/market/" + name] for name in names},
                    "basis": strategy_model_allocation.BASIS, 'economic_parameters':{'cost_bps':float(cost_bps)}})


# Resolve an original observation across host/container prefixes by its exact receipt and array bytes.
def _close_context(policy, current):
    name = Path(policy.admission['close_directory']).name
    if len(name) != 32 or any(letter not in '0123456789abcdef' for letter in name):
        raise ValueError('Original prepared context name required')
    base = Path(policy.root) / 'desk/learned-holding/observations'
    folder = base / name
    if (folder.is_symlink() or folder.resolve().parent != base.resolve()
            or (folder/'close.json').is_symlink() or (folder/'close.npz').is_symlink()
            or sha256((folder/'close.json').read_bytes()).hexdigest() != policy.admission['close_receipt_sha256']
            or sha256((folder/'close.npz').read_bytes()).hexdigest() != current.receipt['arrays_sha256']):
        raise ValueError('Original prepared context bytes required')
    return {'directory':name,'receipt_sha256':policy.admission['close_receipt_sha256'],
            'arrays_sha256':current.receipt['arrays_sha256']}


# Calculate from the already admitted native close, before creating any account-dependent plan.
def build(policy, report, blocked, *, observed_at):
    if (type(policy) is not learned_live_holding.GradeLedHoldingPolicy
            or not isinstance(observed_at, datetime) or observed_at.utcoffset() is None
            or observed_at < policy.observed_at):
        raise ValueError("Original prepared grade-led policy and real observation required")
    policy.reader.validate_clock(observed_at)
    policy.reader.validate_report(report)
    raw, config = learned_live_holding.read_configuration(policy.root, observed_at)
    if raw != policy.config_bytes or config["policy"] != grade_led_policy.POLICY or policy.cost_bps != config['cost_bps']:
        raise ValueError("Prepared independent configuration changed")
    names = tuple(name for name in report.panel.tickers if name not in ("SPY", "QQQ"))
    if not set(blocked) <= set(report.panel.tickers):
        raise ValueError("Original model entry restrictions required")
    # Benchmarks supply market context but cannot become stock target keys.
    blocked = set(blocked) & set(names)
    targets, readings, receipt = strategy_model_allocation.targets_from_model(
        report, policy.reader, policy.cost_bps, blocked)
    current = policy.reader.current
    session = str(current.dates[-1])
    sources = _sources()
    identity = {"schema": SCHEMA, "policy": config["policy"], "session": session,
                "basis": strategy_model_allocation.BASIS,
                "config_sha256": sha256(raw).hexdigest(),
                "close_receipt_sha256": _sha(policy.admission["close_receipt_sha256"]),
                "holding_model_receipt_sha256": config["model_receipt_sha256"],
                "risk_receipt_sha256": config["risk_receipt_sha256"],
                "timing_config_sha256": config["timing_config_sha256"],
                "economic_parameters":{'cost_bps':policy.cost_bps},
                "strategy_identity": _strategy_identity(sources,policy.cost_bps), "source_sha256": sources,
                "prefix_sha256": current.receipt["identity"]["prefix_sha256"]}
    identity['close_context'] = _close_context(policy,current)
    evidence = {}
    for name in names:
        stock = current.symbols.index(name)
        evidence[name] = {"inputs_as_of": session, "grade": readings[name]["grade"],
                          "model_position_size": targets[name],
                          "features": {key: float(value) for key, value in zip(FEATURE_NAMES, current.features[stock], strict=True) if np.isfinite(value)},
                          "band_blocked": name in blocked,
                          "price_basis": "adjusted_total_return",
                          "reason": readings[name]["reason"],
                          "timing_state": "awaiting_completed_regular_candle"}
    value = {"version": VERSION, "status": "available", "reason": None,
             "policy": config["policy"], "basis": identity["basis"], "session": session,
             "observed_at": current.receipt["identity"]["published_at"],
             "as_of": observed_at.isoformat(), "published_at": observed_at.isoformat(),
             "valid_until": live_model_decision._valid_until(session).isoformat(),
             "strategy_identity": identity["strategy_identity"], "snapshot_id": _digest(identity),
             "identity": identity, "grade_signals": readings,
             "rows": {name: {"target_weight": targets[name], "evidence": evidence[name]} for name in names},
             "calculation_receipt": receipt, "account_basis": "no_account_inputs",
             "timing_basis": "nightly_position_size_not_immediate_trade_size"}
    value["receipt_sha256"] = _digest(value)
    return value


# Check complete percentages, clocks and original evidence before either persistence or display.
def validate(value, now, *, expected_sources=None, config_sha256=None):
    if not isinstance(now, datetime) or now.utcoffset() is None:
        raise ValueError("Aware independent publication observation required")
    if (value["version"] != VERSION or value["status"] != "available"
            or value["policy"] != grade_led_policy.POLICY
            or value["basis"] != strategy_model_allocation.BASIS
            or value["account_basis"] != "no_account_inputs"
            or value["timing_basis"] != "nightly_position_size_not_immediate_trade_size"):
        raise ValueError("Independent publication contract differs")
    identity = value["identity"]
    if (identity["schema"] != SCHEMA or identity["session"] != value["session"]
            or identity["policy"] != value["policy"] or identity["basis"] != value["basis"]
            or _digest(identity) != _sha(value["snapshot_id"])
            or _digest({key: item for key, item in value.items() if key != "receipt_sha256"}) != _sha(value["receipt_sha256"])
            or type(identity['economic_parameters']['cost_bps']) not in (int,float)
            or not math.isfinite(identity['economic_parameters']['cost_bps'])
            or not 0 <= identity['economic_parameters']['cost_bps'] < 10000
            or value["strategy_identity"] != _strategy_identity(identity["source_sha256"],identity['economic_parameters']['cost_bps'])
            or value["strategy_identity"] != identity["strategy_identity"]
            or (expected_sources is not None and identity["source_sha256"] != expected_sources)
            or (config_sha256 is not None and identity["config_sha256"] != config_sha256)):
        raise ValueError("Original independent source or receipt identity differs")
    observed, calculated, published, until = (datetime.fromisoformat(value[key]) for key in ("observed_at", "as_of", "published_at", "valid_until"))
    if (any(clock.utcoffset() is None for clock in (observed, calculated, published, until))
            or not observed <= calculated == published <= now
            or until != live_model_decision._valid_until(value["session"])):
        raise ValueError("Original independent publication clock expired or differs")
    if set(value["rows"]) != set(value["grade_signals"]) or not value["rows"]:
        raise ValueError("Complete independent stock universe required")
    weights = []
    for name, row in value["rows"].items():
        weight, reading, evidence = row["target_weight"], value["grade_signals"][name], row["evidence"]
        if (name in ("SPY", "QQQ") or type(weight) not in (int, float)
                or not math.isfinite(weight) or not 0 <= weight <= growth.CAP
                or reading["session"] != value["session"] or reading["basis"] != "observed_close_grade"
                or reading["action"] not in ("buy", "sell", "hold", "avoid", "unavailable")
                or reading["grade"] not in (None, "A+", "A", "B", "C")
                or evidence["grade"] != reading["grade"] or evidence["inputs_as_of"] != value["session"]
                or evidence["model_position_size"] != weight
                or (weight > 0 and reading["grade"] not in ("A", "A+"))
                or set(evidence["features"]) - set(FEATURE_NAMES)
                or any(type(v) not in (int, float) or not math.isfinite(v) for v in evidence["features"].values())):
            raise ValueError("Original grade-qualified percentages and technical evidence required")
        weights.append(weight)
    if sum(weights) > 1 + 1e-10:
        raise ValueError("Independent percentages exceed unit capital")
    # The receipt and every row have verified; only the display window has closed.
    if now >= until:
        raise ExpiredError(value)
    return value


# Publish an admitted nightly model before its caller can access a funded account.
def publish_prepared(policy, report, *, clock):
    from backend.agents.trading.desk import exit as exit_analyst
    flags = exit_analyst.evidence(report.panel).signalled()[-1]
    blocked = {name for name, flag in zip(report.panel.tickers, flags, strict=True) if flag}
    now = clock()
    value = build(policy, report, blocked, observed_at=now)
    validate(value, now, expected_sources=_sources(), config_sha256=sha256(policy.config_bytes).hexdigest())
    return publish(policy.root, value, now)


# Save one immutable exact snapshot and atomically select it without renewing its original clocks.
def publish(root, value, now):
    # Reading the API remains portable; publishing still requires the original Unix lock.
    import fcntl

    validate(value, now)
    folder = Path(root) / DIRECTORY
    folder.mkdir(mode=0o700, parents=True, exist_ok=True)
    raw = json.dumps(value, sort_keys=True, allow_nan=False).encode()
    if len(raw) > MAX_BYTES:
        raise ValueError("Bounded independent publication required")
    with (folder / "publish.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        path = folder / (value["snapshot_id"] + ".json")
        try:
            with path.open("xb") as stream:
                stream.write(raw); stream.flush(); os.fsync(stream.fileno())
        except FileExistsError:
            original = json.loads(path.read_bytes())
            validate(original, now)
            if any(original[key] != value[key] for key in ("identity", "rows", "grade_signals", "calculation_receipt")):
                raise ValueError("Original immutable publication conflicts")
            value, raw = original, path.read_bytes()
        pointer = {"snapshot_id": value["snapshot_id"], "receipt_sha256": value["receipt_sha256"],
                   "bytes_sha256": sha256(raw).hexdigest(), "session": value["session"]}
        selected = folder / "latest.json"
        if selected.exists():
            previous = json.loads(selected.read_bytes())
            if previous["session"] > value["session"]:
                raise ValueError("Independent publication cannot move backward")
        temporary = folder / ("latest-" + uuid4().hex + ".tmp")
        try:
            with temporary.open("xb") as stream:
                stream.write(json.dumps(pointer, sort_keys=True).encode()); stream.flush(); os.fsync(stream.fileno())
            temporary.replace(selected)
            descriptor = os.open(folder, os.O_RDONLY)
            try: os.fsync(descriptor)
            finally: os.close(descriptor)
        finally:
            temporary.unlink(missing_ok=True)
    return value


# Restore the latest immutable snapshot without loading heads, paper accounts or broker clients.
def read(root, now):
    folder = Path(root) / DIRECTORY
    pointer = json.loads((folder / "latest.json").read_bytes())
    path = folder / (_sha(pointer["snapshot_id"]) + ".json")
    if path.is_symlink() or path.stat().st_size > MAX_BYTES:
        raise ValueError("Original finite independent publication required")
    raw = path.read_bytes()
    if sha256(raw).hexdigest() != _sha(pointer["bytes_sha256"]):
        raise ValueError("Original independent publication bytes differ")
    value = json.loads(raw)
    config, installed = learned_live_holding.read_configuration(root, now)
    expired = None
    try:
        validate(value, now, expected_sources=_sources(), config_sha256=sha256(config).hexdigest())
    except ExpiredError as exception:
        expired = exception
    # Costs and selection stay authoritative before an expired snapshot may wait.
    if value['identity']['economic_parameters']['cost_bps'] != installed['cost_bps']:
        raise ValueError('Original independent publication costs differ from installed configuration')
    if any(pointer[key] != value[key] for key in ("snapshot_id", "receipt_sha256", "session")):
        raise ValueError("Selected independent publication differs")
    if expired is not None:
        raise expired
    return value
