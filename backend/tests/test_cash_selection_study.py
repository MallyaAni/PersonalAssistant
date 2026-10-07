"""Pin saved-evidence refusal, account replay and exact paired score arithmetic."""

import json
from dataclasses import replace

import numpy as np
import pytest

from backend.market import cash_selection_study as study
from backend.market.learned_entry_models import _array_hash
from backend.tests.test_cash_selection_simulator import report_fixture


# Write a small exact-grid archive of saved forecasts and verified control NAV.
def saved_fixture(tmp_path, monkeypatch):
    panel = report_fixture().panel
    panel = replace(
        panel,
        tickers=(*panel.tickers, "QQQ"),
        **{
            key: np.column_stack((getattr(panel, key), getattr(panel, key)[:, -1]))
            for key in ("open", "high", "low", "close", "adj_close", "volume")
        },
    )
    monkeypatch.setattr(study.prior, "START", panel.dates[0])
    monkeypatch.setattr(study.prior, "END", panel.dates[-1])
    monkeypatch.setattr(study.prior, "COSTS", (10,))
    monkeypatch.setattr(study.prior, "OFFSETS", (0,))
    monkeypatch.setattr(
        study.prior, "WINDOWS", {"fixture": (panel.dates[0], panel.dates[-1])}
    )
    nav = np.ones(len(panel.dates))
    relative = np.full(panel.close.shape, -0.02)
    relative[:, -2:] = np.nan
    np.savez(
        tmp_path / "forecasts.npz", dates=panel.dates, relative=relative, spy=nav * 0
    )
    controls = {f"{arm}-10-0": nav for arm in study.prior.ARMS}
    controls.update({"SPY-10": nav, "QQQ-10": nav})
    np.savez(tmp_path / "curves.npz", dates=panel.dates, **controls)
    public = {
        "accounts": [
            {
                "account": f"{arm}-10-0",
                "arm": arm,
                "cost_bps": 10,
                "offset": 0,
                "nav_sha256": _array_hash(nav),
                "score": study.prior.score(panel.dates, nav, nav * 0, nav * 0, {}),
            }
            for arm in study.prior.ARMS
        ]
    }
    return panel, public


# Saved controls with a shifted calendar cannot create seemingly comparable scores.
def test_saved_forecast_clock_refuses(tmp_path, monkeypatch):
    panel, public = saved_fixture(tmp_path, monkeypatch)
    dates = panel.dates + np.timedelta64(1, "D")
    np.savez(
        tmp_path / "forecasts.npz",
        dates=dates,
        relative=panel.close * 0,
        spy=dates.astype(float),
    )
    with pytest.raises(ValueError, match="calendar"):
        study.saved_arrays(tmp_path, panel, public, {}, {"original_inputs": {}})


# Saved NAV alteration is refused even when its date count still looks plausible.
def test_saved_control_nav_refuses(tmp_path, monkeypatch):
    panel, public = saved_fixture(tmp_path, monkeypatch)
    public["accounts"][0]["nav_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="NAV differs"):
        study.saved_arrays(tmp_path, panel, public, {}, {"original_inputs": {}})


# Original artifact-byte corruption is rejected before any saved scores are consumed.
def test_prior_original_bytes_refuse(tmp_path):
    (tmp_path / "result.json").write_text("{}")
    with pytest.raises(ValueError, match="result bytes"):
        study.authenticate_prior(tmp_path, "unused", "unused")


# Paired differences use matched account values rather than subtracting table medians.
def test_exact_paired_arithmetic(monkeypatch):
    monkeypatch.setattr(study.prior, "WINDOWS", {"test": None})
    row = {"cost_bps": 10, "offset": 7, "score": {"test": {"metrics": {"total": 0.12}}}}
    controls = [
        {
            "arm": arm,
            "cost_bps": 10,
            "offset": 7,
            "score": {"test": {"metrics": {"total": gain}}},
        }
        for arm, gain in zip(study.prior.ARMS, [0.1, 0.05, 0.2], strict=True)
    ]
    result = study.paired_results([row], controls)
    np.testing.assert_allclose(
        [r["paired_total_gain"] for r in result], [0.02, 0.07, -0.08]
    )
    row["score"]["test"]["metrics"] = None
    assert all(
        r["paired_total_gain"] is None for r in study.paired_results([row], controls)
    )


# The actual runner consumes saved forecasts, records funded accounts and never fits.
def test_actual_joint_account_archive_uses_saved_models(tmp_path, monkeypatch):
    panel, public = saved_fixture(tmp_path, monkeypatch)
    grades = np.column_stack(
        (report_fixture().graded.grades, np.zeros(len(panel.dates)))
    )
    eligible = np.ones(panel.close.shape, dtype=bool)
    eligible[:, -2:] = False
    monkeypatch.setattr(
        study.retention_inputs, "load", lambda *args: (panel, grades, eligible, {})
    )
    monkeypatch.setattr(
        study, "authenticate_prior", lambda *args: (public, {"original_inputs": {}})
    )
    monkeypatch.setattr(
        study.prior, "authenticate_source", lambda *args: {"fixture": True}
    )
    snapshot = tmp_path / "snapshot"
    snapshot.write_text("fixture")
    monkeypatch.setattr(study.prior, "SNAPSHOT_SHA256", study.digest(snapshot))

    # Any accidental fitting through the old runner fails this real account workflow.
    def forbid_fit(*args, **kwargs):
        raise AssertionError("Saved model study must never fit")

    monkeypatch.setattr(study.prior, "fit", forbid_fit)
    root = study.Path(study.__file__).resolve().parents[2]
    files = study.prior.source_hashes()
    for name in (
        "backend/market/cash_selection_study.py",
        "backend/market/learned_cash_selection.py",
        "backend/cli/market_cash_selection_study.py",
        "docs/research/joint-cash-selection-plan-2026-10-03.md",
    ):
        files[name] = study.digest(root / name)
    manifest = tmp_path / "source.json"
    manifest.write_text(json.dumps({"files": files}))
    output = tmp_path / "output"
    result = study.run(
        snapshot,
        "unused",
        "unused",
        tmp_path,
        "unused",
        "unused",
        output,
        "fixture",
        manifest,
    )
    assert len(result["accounts"]) == 1
    account = result["accounts"][0]
    assert account["journal"]["proof"]["ok"]
    assert account["score"]["fixture"]["metrics"]["total"] == 0
    assert len(result["paired_results"]) == 3
    assert result["adoption"] is False
    with np.load(output / "curves.npz") as curves:
        np.testing.assert_array_equal(curves["joint-10-0"], np.ones(len(panel.dates)))


# One matched cell pins incremental components and the explicit account interaction.
def test_attribution_paired_arithmetic_and_missing_interaction(monkeypatch):
    monkeypatch.setattr(study.prior, "COSTS", (10,))
    monkeypatch.setattr(study.prior, "OFFSETS", (0,))
    monkeypatch.setattr(study.prior, "WINDOWS", {"fixture": None})
    rows = [
        {
            "arm": arm,
            "cost_bps": 10,
            "offset": 0,
            "score": {"fixture": {"metrics": {"total": total}}},
        }
        for arm, total in (
            ("quantity_control", 0.2),
            ("buy_only", 0.4),
            ("exit_only", 0.1),
            ("joint", 0.35),
            ("learned", 0.18),
        )
    ]
    pairs, interaction = study.attribution_results(rows[:3], rows[3:4], rows[4:])
    np.testing.assert_allclose(
        [p["paired_total_gain"] for p in pairs], [0.2, -0.1, 0.15, -0.05, 0.25, 0.02]
    )
    assert interaction[0]["interaction_total_gain"] == pytest.approx(0.05)
    rows[1]["score"]["fixture"]["metrics"] = None
    pairs, interaction = study.attribution_results(rows[:3], rows[3:4], rows[4:])
    assert pairs[0]["paired_total_gain"] is None
    assert pairs[3]["paired_total_gain"] is None
    assert interaction[0]["interaction_total_gain"] is None
    with pytest.raises(ValueError, match="Duplicate"):
        study.attribution_results(rows[:3] * 2, rows[3:4], rows[4:])


# Joint controls must be byte-authenticated before they can be used as evidence.
def test_joint_control_corruption_refuses(tmp_path):
    (tmp_path / "result.json").write_text("{}")
    with pytest.raises(ValueError, match="verified joint control bytes"):
        study.authenticate_joint(tmp_path, "unused", "unused", np.array([]))


# A partial control configuration is refused before a numerical workflow starts.
@pytest.mark.parametrize(
    "args",
    [(True, None, None, None), (False, "directory", None, None), (1, None, None, None)],
)
def test_ambiguous_experiment_refuses(args):
    with pytest.raises(ValueError, match="Boolean|requires all"):
        study.experiment_arms(*args)


# The actual three-arm runner writes funded ledgers without fitting or replaying joint.
def test_actual_attribution_archives_all_declared_modes(tmp_path, monkeypatch):
    panel, public = saved_fixture(tmp_path, monkeypatch)
    grades = np.column_stack(
        (report_fixture().graded.grades, np.zeros(len(panel.dates)))
    )
    eligible = np.ones(panel.close.shape, dtype=bool)
    eligible[:, -2:] = False
    joint = [{**public["accounts"][0], "arm": "joint", "account": "joint-10-0"}]
    monkeypatch.setattr(
        study.retention_inputs, "load", lambda *args: (panel, grades, eligible, {})
    )
    monkeypatch.setattr(
        study, "authenticate_prior", lambda *args: (public, {"original_inputs": {}})
    )
    monkeypatch.setattr(study, "authenticate_joint", lambda *args: (joint, {}))
    monkeypatch.setattr(study.prior, "authenticate_source", lambda *args: {})
    snapshot = tmp_path / "snapshot"
    snapshot.write_text("fixture")
    monkeypatch.setattr(study.prior, "SNAPSHOT_SHA256", study.digest(snapshot))

    # Fail rather than silently training a replacement head in this saved-output study.
    def forbid_fit(*args, **kwargs):
        raise AssertionError("Attribution must never refit models")

    monkeypatch.setattr(study.prior, "fit", forbid_fit)
    root = study.Path(study.__file__).resolve().parents[2]
    files = study.prior.source_hashes()
    for name in (
        "backend/market/cash_selection_study.py",
        "backend/market/learned_cash_selection.py",
        "backend/cli/market_cash_selection_study.py",
        "docs/research/joint-cash-selection-plan-2026-10-03.md",
        "docs/research/cash-selection-attribution-plan-2026-10-03.md",
    ):
        files[name] = study.digest(root / name)
    manifest = tmp_path / "source.json"
    manifest.write_text(json.dumps({"files": files}))
    output = tmp_path / "output"
    result = study.run(
        snapshot,
        "unused",
        "unused",
        tmp_path,
        "unused",
        "unused",
        output,
        "fixture",
        manifest,
        attribution=True,
        joint_directory="unused",
        joint_proof="unused",
        joint_public="unused",
    )
    assert [r["arm"] for r in result["accounts"]] == list(study.ATTRIBUTION_ARMS)
    assert all(r["journal"]["proof"]["ok"] for r in result["accounts"])
    assert len(result["paired_results"]) == 6
    assert len(result["interactions"]) == 1
    assert result["schema"] == "cash-selection-attribution-funded/1"
    assert result["adoption"] is False
    with np.load(output / "curves.npz") as curves:
        np.testing.assert_array_equal(
            curves["buy_only-10-0"], np.ones(len(panel.dates))
        )
    fees = {
        r["arm"]: r["score"]["fixture"]["fees_nav1"]
        for r in result["accounts"]
    }
    assert fees["exit_only"] > fees["quantity_control"] > fees["buy_only"] == 0
    for arm in study.ATTRIBUTION_ARMS:
        records = json.loads((output / f"{arm}-10-0-decisions.json").read_text())
        assert records["selection"]
        assert all(r["mode"] == arm for r in records["selection"])
