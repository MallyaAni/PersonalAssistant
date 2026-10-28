"""Read-only published model percentages, independent of live paper-account access."""

import asyncio
import json
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path

from fastapi import APIRouter, Depends, Response

from backend.api.v1 import market
from backend.core.auth import authorize_path_user
from backend.market import (
    deskrecord,
    grade_led_leader_policy,
    learned_live_holding,
    market_phase,
    model_allocation_view,
    strategy_entries,
    strategy_entry_history,
    strategy_position_view,
    strategy_publication,
)
from backend.market import strategy_verdict as verdicts
from backend.market.labels import TimingState

router = APIRouter(
    prefix="/market/{user_id}",
    tags=["market"],
    dependencies=[Depends(authorize_path_user)],
)

# How far inside the original window the expiry probe reads. The publication
# reader admits a snapshot only while `now < valid_until`; one microsecond
# before the close is still inside the window and after every other clock the
# snapshot carries.
PROBE = timedelta(microseconds=1)
# Bound at import: the HTTP tests replace this module's `datetime` with a
# fixed clock that has only `now`, and the probe must still parse a stamp.
_parse_instant = datetime.fromisoformat


# The verified snapshot an expired publication still is, or None when the
# bytes fail any check other than their clock. The reader itself is one of
# the sources the installed release approval binds, so expiry is told apart
# here by reading once more with the clock set just inside the window: a
# snapshot that verifies then, and only then, has merely expired.
def _expired_snapshot(root, now):
    folder = root / strategy_publication.DIRECTORY
    try:
        pointer = json.loads((folder / "latest.json").read_bytes())
        stored = json.loads((folder / f"{pointer['snapshot_id']}.json").read_bytes())
        until = _parse_instant(stored["valid_until"])
    except (OSError, ValueError, TypeError, KeyError):
        return None
    if until.utcoffset() is None or now < until:
        return None
    try:
        return strategy_publication.read(root, until - PROBE)
    except (OSError, ValueError, TypeError, KeyError, AttributeError, OverflowError):
        return None


# A verified publication whose policy has since been replaced: the installed
# configuration no longer binds it, so `read` refuses it, but its own
# identity and clocks still verify. Until the next nightly publishes under
# the new policy the board shows it as the last plan, with the moment the
# policy changed, rather than nothing.
def _superseded_snapshot(root, now):
    folder = root / strategy_publication.DIRECTORY
    try:
        pointer = json.loads((folder / "latest.json").read_bytes())
        raw = (folder / f"{pointer['snapshot_id']}.json").read_bytes()
        if sha256(raw).hexdigest() != pointer["bytes_sha256"]:
            return None
        stored = json.loads(raw)
        until = _parse_instant(stored["valid_until"])
        if until.utcoffset() is None:
            return None
        strategy_publication.validate(stored, min(now, until - PROBE))
        config, installed = learned_live_holding.read_configuration(root, now)
        if sha256(config).hexdigest() == stored["identity"]["config_sha256"]:
            return None
        replaced = datetime.fromtimestamp(
            (root / learned_live_holding.CONFIG).stat().st_mtime, tz=UTC
        )
    except (OSError, ValueError, TypeError, KeyError, AttributeError, OverflowError):
        return None
    return {
        "snapshot": stored,
        "policy": installed["policy"],
        "replaced_at": replaced.isoformat(),
        "expired_at": stored["valid_until"] if now >= until else None,
    }


# The one-word verdict beside each served numerical row. The rows come from
# sealed engines whose modules the release approval binds, so the verdict is
# added here, on the way out, from the evidence the rows already carry.
def _with_verdicts(assessment, snapshot, *, reason_key, held_key=None):
    if not isinstance(assessment, dict):
        return assessment
    if not isinstance(assessment.get("rows"), dict):
        return assessment
    rows = {}
    for name, row in assessment["rows"].items():
        if not isinstance(row, dict):
            rows[name] = row
            continue
        target = row.get("model_position_weight")
        if target is None:
            target = snapshot.get("rows", {}).get(name, {}).get("target_weight")
        rows[name] = verdicts.annotate(
            row,
            reason_key=reason_key,
            target_weight=target,
            held_weight=row.get(held_key) if held_key else 0,
            quote_available=row.get("quote_at") is not None,
            distribution_available=row.get("state") != TimingState.UNAVAILABLE
            or "distribution" not in str(row.get("reason", "")).lower(),
            mandatory=row.get("reason") == "mandatory_grade_exit",
            resolved=bool(row.get("attempt_resolved")),
        )
    return {**assessment, "rows": rows}


# Read original publication and persisted model objectives without recovering,
# recalculating or accessing accounts.
# The leader-weight policy's plan() routes every leg to the next open, so its
# day's action is the plan's change from the previous plan, not a fifteen-minute
# entry; the learned-sizing policy acts on fifteen-minute entries.
OPEN_EXECUTED_POLICIES = frozenset({grade_led_leader_policy.POLICY})


# The latest publication before the current one that still verifies on its
# own identity and clocks, as the previous plan the current one changes from.
# Its policy may differ: the first plan under a new policy changes from the
# last plan under the old one, which is what the desk trades at the open.
def _previous_plan(root, current):
    folder = root / strategy_publication.DIRECTORY
    best = None
    for path in folder.glob("*.json"):
        if path.name == "latest.json":
            continue
        try:
            stored = json.loads(path.read_bytes())
            session = stored["session"]
            if (
                stored["version"] != strategy_publication.VERSION
                or session >= current["session"]
                or best is not None
                and (session, stored["published_at"]) <= best[0]
            ):
                continue
            until = _parse_instant(stored["valid_until"])
            strategy_publication.validate(stored, until - PROBE)
        except (
            OSError,
            ValueError,
            TypeError,
            KeyError,
            AttributeError,
            OverflowError,
        ):
            continue
        best = ((session, stored["published_at"]), stored)
    if best is None:
        return None
    stored = best[1]
    return {
        "session": stored["session"],
        "policy": stored["policy"],
        "published_at": stored["published_at"],
        "rows": {name: row["target_weight"] for name, row in stored["rows"].items()},
    }


# How the installed policy acts on its plan, and what the plan changes from.
def _execution(root, snapshot):
    if snapshot["policy"] not in OPEN_EXECUTED_POLICIES:
        return {"execution": {"timing": "fifteen_minute"}}
    return {
        "execution": {"timing": "next_open"},
        "previous_plan": _previous_plan(root, snapshot),
    }


def allocation(root, now):
    root = Path(root)
    # Every answer carries the exchange clock, so the board can say which
    # phase the market is in and when the desk acts next instead of leaving
    # an evening or a weekend to be read as a failure.
    phase = market_phase.describe(now)
    if (root / strategy_publication.DIRECTORY).exists():
        try:
            snapshot = strategy_publication.read(root, now)
            positions = strategy_position_view.read(root, snapshot, now)
            entries = _with_verdicts(
                strategy_entries.read(root, snapshot, now),
                snapshot,
                reason_key="reason",
            )
            # Reference-position rows carry a target for the next session and
            # no state or action, so a verdict read from them said "nothing"
            # for a name the plan buys at the open; the board reads the plan
            # from the target itself.
            return {
                **snapshot,
                "entry_assessment": entries,
                **({"reference_positions": positions} if positions is not None else {}),
                **_execution(root, snapshot),
                "recorded_history_version": strategy_entry_history.PAGE_SCHEMA,
                "market_phase": phase,
            }
        except (
            OSError,
            ValueError,
            TypeError,
            KeyError,
            AttributeError,
            OverflowError,
        ):
            expired = _expired_snapshot(root, now)
            superseded = (
                None if expired is not None else _superseded_snapshot(root, now)
            )
            if superseded is not None:
                stored = superseded["snapshot"]
                return {
                    "version": strategy_publication.VERSION,
                    "status": "awaiting_nightly",
                    "policy": superseded["policy"],
                    "superseded_policy": stored["policy"],
                    "superseded_at": superseded["replaced_at"],
                    "rows": {},
                    "expired_at": superseded["expired_at"],
                    "next_publication_at": market_phase.next_publication_at(
                        now
                    ).isoformat(),
                    "last_session": stored["session"],
                    "last_rows": stored["rows"],
                    "as_of": now.isoformat(),
                    "valid_until": None,
                    "market_phase": phase,
                }
            if expired is not None:
                # A verified publication whose window has closed is a plan
                # waiting for tonight's, not an integrity failure.
                return {
                    "version": strategy_publication.VERSION,
                    "status": "awaiting_nightly",
                    "policy": expired["policy"],
                    "rows": {},
                    "expired_at": expired["valid_until"],
                    "next_publication_at": market_phase.next_publication_at(
                        now
                    ).isoformat(),
                    "last_session": expired["session"],
                    "last_rows": expired["rows"],
                    "as_of": now.isoformat(),
                    "valid_until": None,
                    "market_phase": phase,
                }
            return {
                "version": strategy_publication.VERSION,
                "status": "unavailable",
                "policy": "grade-led-learned-sizing/1",
                "rows": {},
                "reason": "Independent strategy publication could not be verified",
                "as_of": now.isoformat(),
                "valid_until": None,
                "market_phase": phase,
            }
    try:
        record, _ = deskrecord.latest_pair(root)
    except (OSError, ValueError, TypeError):
        return model_allocation_view.unavailable(
            {}, now, "Published model record could not be read"
        )
    return model_allocation_view.read(root, record, now)


# Serve authenticated percentages without recalculating or recording advice.
@router.get("/desk/model-allocation")
async def model_allocation(user_id: market.UserId, response: Response):
    market._operator_only(user_id)
    response.headers["Cache-Control"] = "private, no-store"
    return await asyncio.to_thread(allocation, market._root(), datetime.now(UTC))
