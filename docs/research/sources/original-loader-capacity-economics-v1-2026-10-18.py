"""UNEXECUTED explicit capacity economics; no study, replay or account imports.

The private provenance projection refuses nonfinite scalars instead of converting
them to null. Its only caller compares the actual prepare_passive provenance;
it is not a generic native/account normalizer. That narrower domain needs parity.
Original evidence helper leaf-symlink, two-read and json.loads semantics remain.
"""
import hashlib
import json
import math
from collections.abc import Mapping
from pathlib import Path
from types import SimpleNamespace

import numpy as np

from backend.market.capacity_original_evidence_v1 import authenticate_file, pinned, require, strict_json
from backend.market.live_execution_inputs import PassiveMarks, _actions, _dates_by_name, _inherited_actions, prepare_passive, review_action_export

SCHEMA = 'capacity-original-economics/1'

ECONOMIC_RECEIPT_SHA256 = (
    "afa4edc554a6a2548e2558077833eb53239494dd685f990f685ac63de8b15a30"
)

SNAPSHOT_SHA = "8670c86dd268fdf25ec16b44be86dcd40b840f703b7721ef319bc40e0e22ea58"

ACTIONS_SHA = "0e05a397f3719c61688e2eb79355eb5111961c05f31916db8a16ab6ff01dbcca"

ACTION_REVIEW_SHA = "81106947ba049d0315d610719988a80da8e0efce9d87c52f789f2041901e95e8"

ECONOMIC_INPUT_PROOF_SHA = (
    "2a8ef22bf20de7891b27ae80ab05570a0be20ca170d6176ab596d0ec20aec102"
)

PASSIVE_ARRAYS_SHA = "c07e4615e425e8778282f26c75f18437ca38fa88993a4bab9bfe4b4499e99411"

PASSIVE_RECEIPT_SHA = "2bc957fcf9948981c4139c1868ad1336b0425d0bf5106460974ffb240a2869a9"


# Hash only an explicitly supplied passive evidence path with the original chunked helper.
def _file_sha256(path):
    value = hashlib.sha256()
    with Path(path).open("rb") as handle:
        while data := handle.read(1024 * 1024):
            value.update(data)
    return value.hexdigest()


# Retain original passive evidence Path-versus-JSON, leaf-link and hash behavior.
def _passive_evidence(path, digest, *, json_file=False):
    path = Path(path)
    require(path.is_file() and not path.is_symlink(), "Regular evidence file required")
    require(_file_sha256(path) == digest, f"Original bytes required: {path.name}")
    return json.loads(path.read_text()) if json_file else path


# Project only derived finite passive provenance, refusing rather than normalizing nonfinite values.
def _passive_provenance_plain(value):
    if isinstance(value, Mapping):
        return {str(key): _passive_provenance_plain(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_passive_provenance_plain(item) for item in value]
    if isinstance(value, (float, np.floating)):
        require(math.isfinite(value), "FINITE_PASSIVE_PROVENANCE_REQUIRED")
        return float(value)
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.bool_):
        return bool(value)
    return value


# Retain exact passive NPZ coordinates, fields, source receipts and derived readonly provenance.
def load_passive_inputs(args, dates, names):
    _passive_evidence(args.passive_arrays, PASSIVE_ARRAYS_SHA)
    receipt = _passive_evidence(
        args.passive_receipt, PASSIVE_RECEIPT_SHA, json_file=True
    )
    require(
        receipt["arrays_sha256"] == PASSIVE_ARRAYS_SHA
        and receipt["selection_symbols"] == len(names)
        and receipt["selection_universe_extended"] is False
        and receipt["adoption_eligible"] is False,
        "Original passive receipt cannot extend selection or authorize adoption",
    )
    contract = receipt["passive_provenance"]
    require(
        contract["supplied"]["snapshot_sha256"] == SNAPSHOT_SHA,
        "Passive prices belong to another selection snapshot",
    )
    with np.load(args.passive_arrays, allow_pickle=False) as archive:
        require(
            set(archive.files)
            == {"dates", "symbols", "session_open", "observation_close", "daily_close"}
            and np.array_equal(archive["dates"], dates),
            "Original passive calendar and array fields required",
        )
        passive = prepare_passive(
            archive["dates"],
            names,
            tuple(archive["symbols"].tolist()),
            archive["session_open"],
            archive["observation_close"],
            archive["daily_close"],
            first_session=contract["first_session"],
            complete_through=contract["complete_through"],
            provenance=contract["supplied"],
            price_basis=contract["price_basis"],
        )
    require(
        _passive_provenance_plain(passive.provenance) == contract,
        "Derived passive units, missingness or typed array hashes differ",
    )
    return passive


# Select every original economic receipt path without importing a study CLI.
def economic_paths(receipt=Path("/economic-receipt.json")):
    command = strict_json(pinned(receipt, ECONOMIC_RECEIPT_SHA256))["commands"]["study"]
    require(
        type(command) is list and all(type(item) is str for item in command),
        "EXACT_ECONOMIC_COMMAND_REQUIRED",
    )
    result = {}
    for name in (
        "actions",
        "action_review",
        "passive_arrays",
        "passive_receipt",
        "economic_input_proof",
    ):
        option = "--" + name.replace("_", "-")
        require(command.count(option) == 1, "UNIQUE_ECONOMIC_INPUT_REQUIRED")
        index = command.index(option) + 1
        require(index < len(command), "ECONOMIC_INPUT_PATH_REQUIRED")
        path = Path(command[index])
        require(
            path.is_absolute() and ".." not in path.parts,
            "ABSOLUTE_ECONOMIC_PATH_REQUIRED",
        )
        result[name] = path
    return SimpleNamespace(**result)


# Preserve missing later passive marks and original array allocation order.
def align_passive(panel_dates, passive):
    indices = np.searchsorted(panel_dates, passive.dates)
    require(
        np.all(indices < len(panel_dates))
        and np.array_equal(panel_dates[indices], passive.dates),
        "EXACT_PASSIVE_CALENDAR_REQUIRED",
    )
    shape = (len(panel_dates), len(passive.tickers))
    opening, closing = np.full(shape, np.nan), np.full(shape, np.nan)
    observed = np.full((len(panel_dates), 26, len(passive.tickers)), np.nan)
    opening[indices], closing[indices], observed[indices] = (
        passive.session_open,
        passive.daily_close,
        passive.observation_close,
    )
    return PassiveMarks(
        panel_dates,
        passive.tickers,
        opening,
        observed,
        closing,
        {**dict(passive.provenance), "later_marks": "missing_not_invented"},
    )


# Retain all reviewed economic and inherited action checks with explicit new helper bindings.
def reviewed_economics(panel, factors, events, paths):
    proof = strict_json(
        pinned(paths.economic_input_proof, ECONOMIC_INPUT_PROOF_SHA)
    )
    require(
        proof["status"] == "VERIFIED_INDEPENDENT_REVIEWED_ORIGINAL_INPUTS",
        "REVIEWED_ECONOMIC_PROOF_REQUIRED",
    )
    action_bytes = pinned(paths.actions, ACTIONS_SHA)
    review_bytes = pinned(paths.action_review, ACTION_REVIEW_SHA)
    original, compiled = (
        strict_json(action_bytes),
        review_action_export(action_bytes, review_bytes),
    )
    require(
        not compiled["unresolved"]
        and dict(compiled["scope"])
        == {"first_session": "2018-02-01", "last_session": "2026-09-30"}
        and compiled["execution_readiness"] == "pending_declaration_receipts",
        "EXACT_REVIEWED_ECONOMIC_SCOPE_REQUIRED",
    )
    authenticate_file(paths.passive_arrays, PASSIVE_ARRAYS_SHA)
    pinned(paths.passive_receipt, PASSIVE_RECEIPT_SHA)
    with np.load(paths.passive_arrays, allow_pickle=False) as archive:
        dates = archive["dates"]
    passive = load_passive_inputs(paths, dates, panel.tickers)
    cutoff = dates[-1]
    selected = panel.dates <= cutoff
    require(
        np.array_equal(panel.dates[selected], dates),
        "EXACT_REVIEWED_DAILY_CALENDAR_REQUIRED",
    )
    old_factors, reviewed = _actions(
        compiled["actions"],
        panel.tickers,
        dates,
        _dates_by_name(
            original["basis_as_of"], panel.tickers, "split-adjustment basis"
        ),
        _dates_by_name(
            original["complete_through"], panel.tickers, "action completeness"
        ),
        "split_adjusted_archive_share_dollars",
        passive.tickers,
    )
    require(
        np.allclose(factors[selected], old_factors, rtol=0, atol=1e-12),
        "REVIEWED_ARCHIVE_FACTORS_DIFFER",
    )
    actions = {
        name: [dict(row) for row in reviewed[name]]
        + [row for row in events[name] if row["date"] > str(cutoff)]
        for name in panel.tickers
    }
    inherited = _inherited_actions(compiled.get("inherited_actions"), passive, dates)
    return actions, align_passive(panel.dates, passive), inherited
