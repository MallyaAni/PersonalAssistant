"""Archive reviewed historical cohort facts without inventing a tradable history.

Original source bytes, cited passages and publication/ingestion clocks remain
separate. Hash and passage checks prove integrity, not the truth or completeness
of a reviewer's extraction. Membership below means membership under the supplied
sources; it is not proof that every historical event has been collected.
"""

from __future__ import annotations

import json
import math
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from hashlib import sha256
from html.parser import HTMLParser
from pathlib import Path
from types import MappingProxyType
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

import numpy as np

from backend.market.membership import MembershipRecord

SCHEMA = "historical-cohort/1"
NEW_YORK = ZoneInfo("America/New_York")
FEATURE_BASES = frozenset({"recorded", "source_reconstruction", "retrospective_model"})


@dataclass(frozen=True)
class Cohort:
    """One original manifest and its immutable, hash-checked source bodies."""

    original_manifest: bytes
    source_bytes: Mapping[str, bytes]

    # Return a fresh manifest so a caller cannot revise the validated archive in place.
    @property
    def manifest(self) -> dict:
        return json.loads(self.original_manifest)


class _DocumentText(HTMLParser):
    """Read HTML text structurally; no document instruction is ever executed."""

    # Collect text nodes while leaving the archived HTML unchanged.
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []

    # Preserve words from each node for whitespace-normalized passage matching.
    def handle_data(self, data):
        self.parts.append(data)


# Require explicit nonempty identifiers and evidence fields rather than default values.
def _text(value, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be nonempty text")
    return value


# Refuse timezone guesses and retain the source's full publication precision.
def _instant(value, label: str) -> datetime:
    try:
        result = datetime.fromisoformat(_text(value, label).replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{label} must be an ISO timestamp") from exc
    if result.tzinfo is None or result.utcoffset() is None:
        raise ValueError(f"{label} must be timezone-aware")
    return result


# Keep effective session dates distinct from publication timestamps.
def _day(value, label: str) -> date:
    try:
        result = date.fromisoformat(_text(value, label))
    except ValueError as exc:
        raise ValueError(f"{label} must be an ISO date") from exc
    if result.isoformat() != value:
        raise ValueError(f"{label} must be a plain YYYY-MM-DD date")
    return result


# Preserve date-only publication evidence and derive a conservative availability bound.
def _publication(source) -> datetime:
    precision = source.get("publication_precision", "instant")
    if precision == "day_conservative":
        if source.get("published_at") is not None:
            raise ValueError("Date-only publication cannot assert an exact timestamp")
        published = _day(source["published_on"], "published_on")
        return datetime.combine(published + timedelta(days=1), time(), NEW_YORK)
    if precision != "instant" or source.get("published_on") is not None:
        raise ValueError("Unknown or contradictory source publication precision")
    return _instant(source["published_at"], "published_at")


# Normalize only document structure and whitespace, never the meaning of a passage.
def _document_text(body: bytes, media_type: str) -> str:
    decoded = body.decode("utf-8-sig")
    if media_type == "text/html":
        parser = _DocumentText()
        parser.feed(decoded)
        decoded = " ".join(parser.parts)
    elif media_type not in ("text/plain", "application/json"):
        raise ValueError("Unsupported source media type")
    return " ".join(decoded.split())


# Bind an extracted assertion to a passage in the exact retained source document.
def _evidence(reference, sources, texts) -> dict:
    if not isinstance(reference, dict):
        raise ValueError("A source_id and quoted passage are required")
    source_id = reference.get("source_id")
    if source_id not in sources:
        raise ValueError("Evidence refers to an unknown source")
    quote = " ".join(_text(reference.get("quote"), "evidence quote").split())
    if quote not in texts[source_id]:
        raise ValueError(f"Evidence passage is absent from archived source {source_id}")
    return sources[source_id]


# Verify source identity, bytes and clocks before any extracted fact is consumed.
def _sources(manifest, bodies):
    sources, texts = {}, {}
    for source in manifest["sources"]:
        identity = _text(source["source_id"], "source_id")
        if identity in sources:
            raise ValueError("Duplicate source_id")
        url = urlsplit(_text(source["url"], "source URL"))
        if url.scheme != "https" or not url.hostname or url.username or url.password:
            raise ValueError("Source URL must be HTTPS without credentials")
        body = bodies.get(identity)
        if not isinstance(body, bytes) or not body:
            raise ValueError(f"Missing source bytes: {identity}")
        if sha256(body).hexdigest() != source["sha256"]:
            raise ValueError(f"Source byte hash mismatch: {identity}")
        published = _publication(source)
        ingested = _instant(source["ingested_at"], "ingested_at")
        if source.get("publication_precision") == "day_conservative":
            # A conservative availability bound is not an exact publication instant.
            after_ingestion = (
                _day(source["published_on"], "published_on")
                > ingested.astimezone(NEW_YORK).date()
            )
        else:
            after_ingestion = published > ingested
        if after_ingestion:
            raise ValueError("Source publication follows its ingestion")
        texts[identity] = _document_text(body, source["media_type"])
        sources[identity] = source
    if not sources or set(sources) != set(bodies):
        raise ValueError("Exactly the declared nonempty source set is required")
    for source in sources.values():
        _evidence(source["publication_evidence"], sources, texts)
    return sources, texts


# Validate stable identities and preserve every named security, even without prices.
def _securities(manifest, sources, texts):
    securities = {}
    stable_keys = set()
    for security in manifest["securities"]:
        for key in (
            "security_id",
            "identifier_scheme",
            "issuer_id",
            "share_class",
            "ticker",
        ):
            _text(security.get(key), key)
        if security["identifier_scheme"] != "sec_cik_and_share_class":
            raise ValueError("Supported identity scheme is SEC CIK plus share class")
        issuer = security["issuer_id"]
        if len(issuer) != 10 or not issuer.isascii() or not issuer.isdigit():
            raise ValueError("SEC issuer identity requires a ten-digit CIK")
        identity = security["security_id"]
        stable = (
            security["identifier_scheme"],
            security["issuer_id"],
            security["share_class"],
        )
        if identity in securities or stable in stable_keys:
            raise ValueError("Duplicate security identity")
        _evidence(security["identity_evidence"], sources, texts)
        stable_keys.add(stable)
        securities[identity] = security
    if not securities:
        raise ValueError("At least one stable security identity is required")
    return securities


# Retain real effective intervals while allowing an announcement to arrive later.
def _memberships(manifest, securities, sources, texts):
    records = {}
    for item in manifest["memberships"]:
        identity = item["security_id"]
        if identity not in securities:
            raise ValueError("Membership refers to an unknown security")
        entry = _day(item["entered"], "entered")
        entry_source = _evidence(item["entry_evidence"], sources, texts)
        exit_day, exit_source = None, None
        if item.get("exited") is not None:
            exit_day = _day(item["exited"], "exited")
            exit_source = _evidence(item["exit_evidence"], sources, texts)
            if exit_day <= entry:
                raise ValueError("Membership exit must follow entry")
        elif item.get("exit_evidence") is not None:
            raise ValueError("Exit evidence requires an effective exit")
        # The existing interval type retains dates; this importer additionally gates
        # full timestamps and permits truthful late filings rather than backdating them.
        record = MembershipRecord(
            identity,
            entry,
            _publication(entry_source).astimezone(NEW_YORK).date(),
            exit_day,
            None
            if exit_source is None
            else _publication(exit_source).astimezone(NEW_YORK).date(),
            entry_source["source_id"],
            manifest["cohort"]["id"],
        )
        records.setdefault(identity, []).append((record, item))
    for intervals in records.values():
        intervals.sort(key=lambda pair: pair[0].entered)
        for (previous, _), (following, _) in zip(
            intervals, intervals[1:], strict=False
        ):
            if previous.exited is None or previous.exited > following.entered:
                raise ValueError("Overlapping membership intervals")
    return records


# Require sourced consideration separately from whether or when cash was settled.
def _terminal_outcomes(manifest, securities, sources, texts):
    outcomes = {}
    for item in manifest["terminal_outcomes"]:
        identity = item["security_id"]
        if identity not in securities or identity in outcomes:
            raise ValueError("Terminal outcome has an unknown or duplicate security")
        _evidence(item["evidence"], sources, texts)
        effective = _day(item["effective_on"], "effective_on")
        settlement = item.get("settlement_on")
        if settlement is not None and _day(settlement, "settlement_on") < effective:
            raise ValueError("Settlement cannot precede the terminal event")
        kind = item["kind"]
        if kind not in (
            "cash_merger",
            "cash_liquidation",
            "share_exchange",
            "mixed_consideration",
        ):
            raise ValueError("Unknown terminal outcome kind")
        _cash_terms(item)
        _share_terms(item, securities)
        outcomes[identity] = item
    return outcomes


# Keep a terminal cash entitlement finite, currency-labelled and separate from shares.
def _cash_terms(item):
    cash, currency = item.get("cash_per_share"), item.get("currency")
    if item["kind"] == "share_exchange":
        if cash is not None or currency is not None:
            raise ValueError("Share-only consideration cannot imply cash")
        return
    if (
        isinstance(cash, bool)
        or not isinstance(cash, (int, float))
        or not math.isfinite(cash)
        or cash < 0
    ):
        raise ValueError("Terminal cash must be finite and nonnegative")
    if (
        not isinstance(currency, str)
        or len(currency) != 3
        or not currency.isalpha()
        or not currency.isupper()
    ):
        raise ValueError("Terminal cash requires its currency")


# Resolve share consideration to a distinct declared security without inventing a price.
def _share_terms(item, securities):
    shares, successor = item.get("shares_per_share"), item.get("successor_security_id")
    if item["kind"] not in ("share_exchange", "mixed_consideration"):
        if shares is not None or successor is not None:
            raise ValueError("Cash-only consideration cannot imply successor shares")
        return
    if successor not in securities or successor == item["security_id"]:
        raise ValueError("Share consideration requires a distinct known successor")
    if (
        isinstance(shares, bool)
        or not isinstance(shares, (int, float))
        or not math.isfinite(shares)
        or shares <= 0
    ):
        raise ValueError("Share consideration requires a positive ratio")


# Keep each feature's version, source and actual availability without late substitution.
def _features(manifest, securities, sources, texts):
    features = {}
    for item in manifest["features"]:
        if item["security_id"] not in securities:
            raise ValueError("Feature refers to an unknown security")
        _day(item["session"], "feature session")
        _text(item["name"], "feature name")
        _text(item["version"], "feature version")
        source = _evidence(item["evidence"], sources, texts)
        available = _instant(item["available_at"], "feature available_at")
        if available < _publication(source):
            raise ValueError("Feature availability precedes source publication")
        if item["basis"] not in FEATURE_BASES:
            raise ValueError("Unknown feature evidence basis")
        if item["basis"] == "recorded" and available < _instant(
            source["ingested_at"], "ingested_at"
        ):
            raise ValueError(
                "A later source ingestion cannot prove an earlier recorded feature"
            )
        if "value" not in item:
            raise ValueError("Feature value must be supplied, including explicit null")
        value = item["value"]
        if value is not None and (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
        ):
            raise ValueError("Feature values must be finite numbers or explicit null")
        key = (item["security_id"], item["session"], item["name"])
        versions = features.setdefault(key, [])
        if any(
            _instant(row["available_at"], "available_at") == available
            for row in versions
        ):
            raise ValueError("Ambiguous feature versions at the same availability time")
        versions.append(item)
    return features


# Validate the complete reviewed manifest while refusing claims of automatic readiness.
def _validated(cohort: Cohort):
    manifest = cohort.manifest
    if manifest.get("schema") != SCHEMA:
        raise ValueError("Unknown historical cohort schema")
    rule = manifest["cohort"]
    for key in ("id", "rule", "basis"):
        _text(rule.get(key), f"cohort {key}")
    if rule["basis"] not in ("retrospective_demonstration", "sourced_historical_rule"):
        raise ValueError("Unknown cohort selection basis")
    _instant(rule["selected_at"], "cohort selected_at")
    if not isinstance(rule.get("limitations"), list) or not rule["limitations"]:
        raise ValueError("Cohort limitations must be explicit")
    for limitation in rule["limitations"]:
        _text(limitation, "cohort limitation")
    sources, texts = _sources(manifest, cohort.source_bytes)
    securities = _securities(manifest, sources, texts)
    memberships = _memberships(manifest, securities, sources, texts)
    outcomes = _terminal_outcomes(manifest, securities, sources, texts)
    features = _features(manifest, securities, sources, texts)
    return manifest, sources, securities, memberships, outcomes, features


# Load only declared local source files under the manifest's directory and verify bytes.
def load_cohort(manifest_path: str | Path) -> Cohort:
    path = Path(manifest_path)
    original = path.read_bytes()
    manifest = json.loads(original)
    root = path.parent.resolve()
    bodies = {}
    for source in manifest["sources"]:
        relative = Path(_text(source["file"], "source file"))
        resolved = (root / relative).resolve()
        if relative.is_absolute() or not resolved.is_relative_to(root):
            raise ValueError("Source files must remain inside the manifest directory")
        bodies[source["source_id"]] = resolved.read_bytes()
    cohort = Cohort(original, MappingProxyType(bodies))
    _validated(cohort)
    return cohort


# Copy verified original bytes to a new archive, publishing its manifest last.
def archive_cohort(cohort: Cohort, destination: str | Path) -> Path:
    manifest, *_ = _validated(cohort)
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=False)
    (destination / "sources").mkdir()
    copied = set()
    for source in manifest["sources"]:
        relative = f"sources/{source['sha256']}.bin"
        if relative not in copied:
            with (destination / relative).open("xb") as stream:
                stream.write(cohort.source_bytes[source["source_id"]])
            copied.add(relative)
        source["file"] = relative
    with (destination / "original-manifest.json").open("xb") as stream:
        stream.write(cohort.original_manifest)
    manifest["input_manifest_sha256"] = sha256(cohort.original_manifest).hexdigest()
    path = destination / "cohort.json"
    with path.open("x", encoding="utf-8") as stream:
        json.dump(manifest, stream, sort_keys=True, indent=2, allow_nan=False)
        stream.write("\n")
    return path


# Admit a source only after its original stated publication, never its event date.
def _known(reference, sources, decision: datetime) -> bool:
    source = sources[reference["source_id"]]
    return _publication(source) <= decision


# Replay membership without letting an unseen future filing change the past.
def _membership_state(intervals, sources, decision: datetime) -> tuple[str, str]:
    session = decision.astimezone(NEW_YORK).date()
    state, reason = "unknown", "no_available_entry_evidence"
    for interval, item in intervals:
        if not _known(item["entry_evidence"], sources, decision):
            continue
        if interval.entered > session:
            if state == "unknown":
                state, reason = "absent", "before_declared_entry"
            continue
        state, reason = "present", "active_supplied_interval"
        if (
            interval.exited is not None
            and interval.exited <= session
            and _known(item["exit_evidence"], sources, decision)
        ):
            state, reason = "absent", "after_known_exit"
    return state, reason


# Describe terminal consideration without treating its unknown payment as funded cash.
def _outcome_at(outcome, sources, decision):
    if outcome is None or not _known(outcome["evidence"], sources, decision):
        return None
    if (
        _day(outcome["effective_on"], "effective_on")
        > decision.astimezone(NEW_YORK).date()
    ):
        return None
    return {
        key: outcome.get(key)
        for key in (
            "kind",
            "effective_on",
            "cash_per_share",
            "currency",
            "successor_security_id",
            "shares_per_share",
            "settlement_on",
            "evidence",
        )
    } | {"cash_is_funded": False}


# Select the latest feature version actually available at this specific decision.
def _feature_at(versions, decision):
    known = [
        row
        for row in versions
        if _instant(row["available_at"], "available_at") <= decision
    ]
    if not known:
        return {"status": "unavailable", "value": None}
    row = max(known, key=lambda item: _instant(item["available_at"], "available_at"))
    status = "missing" if row["value"] is None else "available"
    if row["basis"] == "retrospective_model":
        status = "retrospective_model_unverified"
    return {
        key: row[key]
        for key in ("value", "version", "basis", "available_at", "evidence")
    } | {"status": status}


# Require explicit decision instants on one unchanged daily calendar.
def _decision_grid(sessions, decision_times, required_features):
    days = np.asarray(sessions)
    if days.ndim != 1 or days.dtype != np.dtype("datetime64[D]") or not len(days):
        raise ValueError("A nonempty daily session calendar is required")
    if (
        np.isnat(days).any()
        or np.any(days[1:] <= days[:-1])
        or len(days) != len(decision_times)
    ):
        raise ValueError("One decision timestamp per sorted unique session is required")
    if not required_features or len(set(required_features)) != len(required_features):
        raise ValueError("Declare a nonempty unique required-feature set")
    for feature in required_features:
        _text(feature, "required feature")
    for day, decision in zip(days, decision_times, strict=True):
        if (
            not isinstance(decision, datetime)
            or decision.tzinfo is None
            or decision.utcoffset() is None
        ):
            raise ValueError("Decision timestamps must be timezone-aware")
        if str(day) != decision.astimezone(NEW_YORK).date().isoformat():
            raise ValueError("Decision timestamp differs from its New York session")
    return days


# Preserve a security's membership and every required evidence gap for a decision.
def _security_row(
    security, intervals, outcome, features, sources, day, decision, required_features
):
    identity = security["security_id"]
    state, membership_basis = _membership_state(intervals, sources, decision)
    identity_known = _known(security["identity_evidence"], sources, decision)
    gaps = []
    if not identity_known:
        gaps.append("identity_unavailable")
    if state == "unknown":
        gaps.append("membership_unknown")
    selected = {
        name: _feature_at(features.get((identity, str(day), name), ()), decision)
        for name in required_features
    }
    if state == "present":
        gaps.extend(
            f"{name}:{item['status']}"
            for name, item in selected.items()
            if item["status"] != "available"
        )
    outcome = _outcome_at(outcome, sources, decision)
    if membership_basis == "after_known_exit" and outcome is None:
        gaps.append("terminal_outcome_not_supplied_or_not_yet_known")
    if outcome is not None and outcome["settlement_on"] is None:
        gaps.append("terminal_settlement_unknown")
    eligible = state == "present" and identity_known
    if state == "present" and outcome is not None:
        gaps.append("terminal_event_conflicts_with_active_membership")
        eligible = False
    return {
        "session": str(day),
        "decision_at": decision.isoformat(),
        "security_id": identity,
        "ticker": security["ticker"],
        "membership": state,
        "membership_basis": membership_basis,
        "eligible_under_supplied_membership": eligible,
        "required_features_complete": all(
            item["status"] == "available" for item in selected.values()
        ),
        "features": selected,
        "terminal_outcome": outcome,
        "gaps": gaps,
    }


# Report session/security gaps separately from source integrity and provenance review.
def readiness(
    cohort: Cohort,
    sessions: np.ndarray,
    decision_times: Sequence[datetime],
    required_features: tuple[str, ...],
) -> dict:
    manifest, sources, securities, memberships, outcomes, features = _validated(cohort)
    days = _decision_grid(sessions, decision_times, required_features)
    rows, counts = [], Counter()
    for day, decision in zip(days, decision_times, strict=True):
        for identity, security in securities.items():
            row = _security_row(
                security,
                memberships.get(identity, ()),
                outcomes.get(identity),
                features,
                sources,
                day,
                decision,
                required_features,
            )
            rows.append(row)
            counts.update(row["gaps"])
    return {
        "schema": SCHEMA,
        "cohort": manifest["cohort"],
        "source_integrity_verified": True,
        "sources": [
            {
                **source,
                "availability_bound_at": _publication(source).isoformat(),
                "publication_semantics": (
                    "reviewed extraction; not independently authenticated"
                ),
            }
            for source in sources.values()
        ],
        "source_count": len(sources),
        "security_count": len(securities),
        "sessions": len(days),
        "session_security_rows": len(rows),
        "all_named_securities_retained": len(rows) == len(days) * len(securities),
        "feature_complete_rows": sum(row["required_features_complete"] for row in rows),
        "gap_counts": dict(sorted(counts.items())),
        "rows": rows,
        "historical_backtest_ready": False,
        "adoption_eligible": False,
        "independent_validation": False,
        "limitations": [
            "Hashes and quoted passages verify retained bytes, not extraction truth, "
            "publication authenticity, or complete historical event coverage.",
            "Membership follows supplied published intervals; uncollected removals "
            "remain possible. The source-selected cohort is not the full live book.",
            "The caller supplies exchange sessions and decision times; this importer "
            "does not certify calendar completeness or run a funded account.",
            "Terminal consideration is an entitlement. Cash availability requires "
            "separate settlement and ledger evidence, even when a date is supplied.",
        ],
    }
