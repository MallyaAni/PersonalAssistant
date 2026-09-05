"""The market universe the trading agent tracks.

Three layers, matching the plan behind the research system:

- **focus** — the names the operator actually trades (CRWV, IREN, SNDK).
- **comparison** — a broader universe across the themes money rotates
  between (software, AI compute / cloud infrastructure, memory & storage,
  networking, power & cooling). A stock may belong to several themes; the
  theme tags are for reporting breadth and for measuring rotation, never
  inputs to a hand-coded indicator — the model consumes raw normalized
  price/volume and learns structure itself.
- **benchmark** — broad market and sector references the model and the
  reports are measured against (SPY, QQQ, SMH).

The themes are deliberately overlapping baskets, not a single "AI" label:
CoreWeave is cloud infrastructure, SanDisk is NAND storage, and a system
that cannot tell them apart cannot see money rotate between them.
"""

from dataclasses import dataclass

# The themes money rotates between. A member carries any subset of these.
THEMES: tuple[str, ...] = (
    "software",
    "ai-compute",
    "memory-storage",
    "networking",
    "power-cooling",
)

# What role a member plays in the universe. Only the operator's own names
# are "focus"; everything else exists to give the model data and context.
FOCUS = "focus"
COMPARISON = "comparison"
BENCHMARK = "benchmark"

# How old the latest stored bar may be before a ticker is reported stale.
# A long calendar window covers weekends and market holidays without a
# trading calendar dependency.
STALE_AFTER_DAYS = 7


@dataclass(frozen=True, slots=True)
class UniverseMember:
    """One ticker the snapshot tracks, with its themes and role."""

    ticker: str
    themes: tuple[str, ...]
    role: str
    name: str = ""


UNIVERSE: tuple[UniverseMember, ...] = (
    # The operator's own names.
    UniverseMember("CRWV", ("ai-compute",), FOCUS, "CoreWeave"),
    UniverseMember("IREN", ("ai-compute",), FOCUS, "IREN"),
    UniverseMember("SNDK", ("memory-storage",), FOCUS, "SanDisk"),
    # Broad market and sector references.
    UniverseMember("SPY", (), BENCHMARK, "S&P 500"),
    UniverseMember("QQQ", (), BENCHMARK, "Nasdaq 100"),
    UniverseMember("SMH", ("ai-compute", "memory-storage", "networking"), BENCHMARK, "Semis ETF"),
    # Comparison universe, one or more themes each.
    UniverseMember("MSFT", ("software", "ai-compute"), COMPARISON, "Microsoft"),
    UniverseMember("ORCL", ("software", "ai-compute"), COMPARISON, "Oracle"),
    UniverseMember("CRM", ("software",), COMPARISON, "Salesforce"),
    UniverseMember("ADBE", ("software",), COMPARISON, "Adobe"),
    UniverseMember("NOW", ("software",), COMPARISON, "ServiceNow"),
    UniverseMember("NVDA", ("ai-compute", "memory-storage"), COMPARISON, "NVIDIA"),
    UniverseMember("AMD", ("ai-compute", "memory-storage"), COMPARISON, "AMD"),
    UniverseMember("SMCI", ("ai-compute",), COMPARISON, "Super Micro"),
    UniverseMember("DELL", ("ai-compute",), COMPARISON, "Dell"),
    UniverseMember("MU", ("memory-storage",), COMPARISON, "Micron"),
    UniverseMember("WDC", ("memory-storage",), COMPARISON, "Western Digital"),
    UniverseMember("STX", ("memory-storage",), COMPARISON, "Seagate"),
    UniverseMember("AVGO", ("networking", "ai-compute"), COMPARISON, "Broadcom"),
    UniverseMember("ANET", ("networking",), COMPARISON, "Arista"),
    UniverseMember("CSCO", ("networking",), COMPARISON, "Cisco"),
    UniverseMember("VRT", ("power-cooling",), COMPARISON, "Vertiv"),
    UniverseMember("ETN", ("power-cooling",), COMPARISON, "Eaton"),
)

# The single order everything iterates in, so a report is stable across runs.
UNIVERSE_TICKERS: tuple[str, ...] = tuple(m.ticker for m in UNIVERSE)


# The tickers the snapshot refreshes by default: every member, so the model
# eventually has a shared universe to train on, not just the focus names.
def default_tickers(include_benchmarks: bool = True) -> tuple[str, ...]:
    """Return every tracked ticker, or just focus + comparison names."""
    roles = {FOCUS, COMPARISON} if not include_benchmarks else {FOCUS, COMPARISON, BENCHMARK}
    return tuple(m.ticker for m in UNIVERSE if m.role in roles)


# The themes of one ticker, or an empty tuple for an unknown symbol.
def themes_for(ticker: str) -> tuple[str, ...]:
    """Return the theme tags attached to a ticker (empty if unknown)."""
    for member in UNIVERSE:
        if member.ticker == ticker:
            return member.themes
    return ()
