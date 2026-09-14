"""Forward-observed inflation evidence, with no invented release-time history."""

import csv
import hashlib
import io
import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import httpx

from backend.market.funding import amount

SERIES = {
    "CPIAUCSL": "CPI",
    "CPILFESL": "Core CPI",
    "PPIFIS": "PPI final demand",
    "PCEPI": "PCE",
    "PCEPILFE": "Core PCE",
}
URL = "https://fred.stlouisfed.org/graph/fredgraph.csv"


# Resolve a calendar-month comparison without treating missing rows as adjacent months.
def prior_month(period: date, months: int) -> str:
    index = period.year * 12 + period.month - 1 - months
    return date(index // 12, index % 12 + 1, 1).isoformat()


# Validate the provider columns and retain only dated, finite index observations.
def _histories(content: str, observed_at: datetime) -> dict:
    reader = csv.DictReader(io.StringIO(content))
    if reader.fieldnames != ["observation_date", *SERIES]:
        raise ValueError("Unexpected economic-data columns")
    histories = {key: {} for key in SERIES}
    for row in reader:
        period = date.fromisoformat(row["observation_date"])
        if period.day != 1 or period > observed_at.date():
            raise ValueError("Invalid economic observation period")
        if (observed_at.date() - period).days > 800:
            continue
        for key in SERIES:
            value = row[key]
            if value in ("", "."):
                continue
            number = float(amount(value, "Economic index", positive=True))
            if period.isoformat() in histories[key]:
                raise ValueError("Duplicate economic observation")
            histories[key][period.isoformat()] = number
    return histories


# Derive changes only from matching calendar periods, retaining missing values.
def facts_from_csv(content: str, observed_at: datetime) -> dict:
    histories = _histories(content, observed_at)
    facts = []
    for key, history in histories.items():
        if not history:
            facts.append({"id": key, "label": SERIES[key], "status": "missing"})
            continue
        period = date.fromisoformat(max(history))
        current = history[period.isoformat()]
        comparisons = {}
        for name, offset in (("month_change_pct", 1), ("year_change_pct", 12)):
            base = history.get(prior_month(period, offset))
            comparisons[name] = (current / base - 1) * 100 if base else None
        previous = history.get(prior_month(period, 1))
        year_before_previous = history.get(prior_month(period, 13))
        facts.append(
            {
                "id": key,
                "label": SERIES[key],
                "period": period.isoformat(),
                "status": "stale"
                if (observed_at.date() - period).days > 75
                else "available",
                **comparisons,
                "previous_year_change_pct": (previous / year_before_previous - 1) * 100
                if previous and year_before_previous
                else None,
                "units": "percent change in seasonally adjusted index",
                "source": f"https://fred.stlouisfed.org/series/{key}",
                "release_at": None,
            }
        )
    return {
        "observed_at": observed_at.isoformat(),
        "availability_basis": "collection observation; release timestamps unavailable",
        "vintage_basis": "current revised history; not an historical release vintage",
        "content_sha256": hashlib.sha256(content.encode()).hexdigest(),
        "facts": facts,
        "history": histories,
    }


# Fetch public history; oversized or malformed responses fail closed.
def collect(now: datetime | None = None) -> dict:
    request_time = now or datetime.now(UTC)
    with httpx.Client(timeout=20, follow_redirects=True) as client:
        response = client.get(
            URL,
            params={
                "id": ",".join(SERIES),
                "cosd": (request_time.date() - timedelta(days=800)).isoformat(),
            },
        )
        response.raise_for_status()
        if len(response.content) > 200000:
            raise ValueError("Economic response too large")
        return facts_from_csv(response.text, now or datetime.now(UTC))


# Archive each observed vintage before atomically replacing the dashboard's pointer.
def save(root: Path, snapshot: dict) -> None:
    folder = root / "desk" / "economics"
    folder.mkdir(parents=True, exist_ok=True)
    stamp = datetime.fromisoformat(snapshot["observed_at"]).strftime("%Y%m%dT%H%M%S%fZ")
    content = json.dumps(snapshot, allow_nan=False, indent=2)
    archive = folder / f"{stamp}.json"
    with archive.open("x", encoding="utf-8") as stream:
        stream.write(content)
    pending = folder / f"{stamp}.tmp"
    pending.write_text(content, encoding="utf-8")
    pending.replace(folder / "latest.json")


# Expose collection age separately and withhold stale model assessments.
def load(root: Path, now: datetime | None = None) -> dict | None:
    now = now or datetime.now(UTC)
    try:
        snapshot = json.loads((root / "desk" / "economics" / "latest.json").read_text())
        observed = datetime.fromisoformat(snapshot["observed_at"])
        stale = not 0 <= (now - observed).total_seconds() < 36 * 3600
        return {
            **snapshot,
            "collection_stale": stale,
            "assessment": None if stale else snapshot.get("assessment"),
            "history": None,
        }
    except (OSError, ValueError, KeyError, TypeError):
        return None
