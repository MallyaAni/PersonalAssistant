"""The market universe the research system learns from.

Three roles:

- **focus** — the names the operator actually trades (CRWV, IREN, SNDK).
  They are the *targets* of position sizing, not the training set: a model
  trained on three names with a year of history learns noise.
- **member** — the broad cross-section a ranking model learns from: every
  current S&P 500 constituent (with its GICS sector and sub-industry) plus an
  overlay of the mid- and small-cap names in the AI-infrastructure, memory,
  networking and power baskets that the index does not hold. Breadth is what
  makes sector rotation measurable; it is a cross-sectional phenomenon.
- **benchmark** — the ETFs a name is measured against: the market, and the
  sector baskets money rotates between.

Themes are overlapping baskets a name can belong to several of. They come
from two places: a small mapping of GICS sub-industries to themes, and an
explicit overlay for names whose thesis the index classification misses
(CoreWeave is "ai-compute" whichever sub-industry it lands in). Theme tags
feed the theme-relative channels and the rotation baselines; they are never
a hand-coded trading signal on their own.

Survivorship bias, stated plainly: the constituent list is *today's* S&P
500. Names that left the index are absent, so any back-test over this
universe is biased toward survivors. The honest fix is a point-in-time
constituent history, which no free source provides; until then every result
is read with that caveat, and the constituent file records the date it was
taken so the bias is at least dated.
"""

import csv
from dataclasses import dataclass
from pathlib import Path

# The themes money rotates between. A member carries any subset of these.
SOFTWARE = "software"
AI_COMPUTE = "ai-compute"
MEMORY_STORAGE = "memory-storage"
NETWORKING = "networking"
POWER_COOLING = "power-cooling"
HYPERSCALER = "hyperscaler"
THEMES: tuple[str, ...] = (
    SOFTWARE,
    AI_COMPUTE,
    MEMORY_STORAGE,
    NETWORKING,
    POWER_COOLING,
    HYPERSCALER,
)

FOCUS = "focus"
MEMBER = "member"
BENCHMARK = "benchmark"

# The broad market benchmark every relative channel is computed against.
MARKET_BENCHMARK = "SPY"

# How old the latest stored session may be before a ticker is reported stale.
# A long calendar window covers weekends and market holidays.
STALE_AFTER_DAYS = 7

# The committed constituent file, produced by `backend.cli.market_universe`.
CONSTITUENTS_PATH = Path(__file__).parent / "data" / "constituents.csv"


@dataclass(frozen=True, slots=True)
class UniverseMember:
    """One ticker the research system tracks, with its role and themes."""

    ticker: str
    role: str
    themes: tuple[str, ...] = ()
    name: str = ""
    sector: str = ""
    sub_industry: str = ""


# GICS sub-industries that map cleanly onto a theme. Everything else keeps
# its sector and sub-industry as data and carries no theme.
SUB_INDUSTRY_THEMES: dict[str, tuple[str, ...]] = {
    "Semiconductors": (AI_COMPUTE,),
    "Semiconductor Materials & Equipment": (AI_COMPUTE,),
    "Application Software": (SOFTWARE,),
    "Systems Software": (SOFTWARE,),
    "Communications Equipment": (NETWORKING,),
    "Electrical Components & Equipment": (POWER_COOLING,),
    "Heavy Electrical Equipment": (POWER_COOLING,),
    "Independent Power Producers & Energy Traders": (POWER_COOLING,),
    "Electric Utilities": (POWER_COOLING,),
}

# Names whose thesis the index classification misses, or that the index does
# not hold at all. Applied on top of the constituent file: an overlay entry
# for a constituent adds themes; an overlay entry for a non-constituent adds
# the member. Focus names live here too.
OVERLAY: tuple[UniverseMember, ...] = (
    # The operator's own names.
    UniverseMember("CRWV", FOCUS, (AI_COMPUTE,), "CoreWeave"),
    UniverseMember("IREN", FOCUS, (AI_COMPUTE, POWER_COOLING), "IREN"),
    UniverseMember("SNDK", FOCUS, (MEMORY_STORAGE,), "SanDisk"),
    # Hyperscalers: the capex that everything downstream depends on.
    UniverseMember("MSFT", MEMBER, (HYPERSCALER, SOFTWARE), "Microsoft"),
    UniverseMember("AMZN", MEMBER, (HYPERSCALER,), "Amazon"),
    UniverseMember("GOOGL", MEMBER, (HYPERSCALER,), "Alphabet"),
    UniverseMember("META", MEMBER, (HYPERSCALER,), "Meta"),
    UniverseMember("ORCL", MEMBER, (HYPERSCALER, SOFTWARE), "Oracle"),
    # AI compute and the neoclouds.
    UniverseMember("NVDA", MEMBER, (AI_COMPUTE, MEMORY_STORAGE), "NVIDIA"),
    UniverseMember("AMD", MEMBER, (AI_COMPUTE,), "AMD"),
    UniverseMember("AVGO", MEMBER, (AI_COMPUTE, NETWORKING), "Broadcom"),
    UniverseMember("MRVL", MEMBER, (AI_COMPUTE, NETWORKING), "Marvell"),
    UniverseMember("SMCI", MEMBER, (AI_COMPUTE,), "Super Micro"),
    UniverseMember("DELL", MEMBER, (AI_COMPUTE,), "Dell"),
    UniverseMember("HPE", MEMBER, (AI_COMPUTE, NETWORKING), "HPE"),
    UniverseMember("NBIS", MEMBER, (AI_COMPUTE,), "Nebius"),
    UniverseMember("APLD", MEMBER, (AI_COMPUTE, POWER_COOLING), "Applied Digital"),
    UniverseMember("CIFR", MEMBER, (AI_COMPUTE, POWER_COOLING), "Cipher Mining"),
    UniverseMember("WULF", MEMBER, (AI_COMPUTE, POWER_COOLING), "TeraWulf"),
    UniverseMember("CORZ", MEMBER, (AI_COMPUTE, POWER_COOLING), "Core Scientific"),
    UniverseMember("HUT", MEMBER, (AI_COMPUTE, POWER_COOLING), "Hut 8"),
    UniverseMember("GLXY", MEMBER, (AI_COMPUTE,), "Galaxy Digital"),
    UniverseMember("ARM", MEMBER, (AI_COMPUTE,), "Arm"),
    UniverseMember("TSM", MEMBER, (AI_COMPUTE,), "TSMC"),
    UniverseMember("ASML", MEMBER, (AI_COMPUTE,), "ASML"),
    UniverseMember("ALAB", MEMBER, (AI_COMPUTE, NETWORKING), "Astera Labs"),
    UniverseMember("CRDO", MEMBER, (NETWORKING,), "Credo"),
    # Memory and storage.
    UniverseMember("MU", MEMBER, (MEMORY_STORAGE,), "Micron"),
    UniverseMember("WDC", MEMBER, (MEMORY_STORAGE,), "Western Digital"),
    UniverseMember("STX", MEMBER, (MEMORY_STORAGE,), "Seagate"),
    UniverseMember("NTAP", MEMBER, (MEMORY_STORAGE,), "NetApp"),
    UniverseMember("SIMO", MEMBER, (MEMORY_STORAGE,), "Silicon Motion"),
    # Networking and optics.
    UniverseMember("ANET", MEMBER, (NETWORKING,), "Arista"),
    UniverseMember("CSCO", MEMBER, (NETWORKING,), "Cisco"),
    UniverseMember("CIEN", MEMBER, (NETWORKING,), "Ciena"),
    UniverseMember("COHR", MEMBER, (NETWORKING,), "Coherent"),
    UniverseMember("LITE", MEMBER, (NETWORKING,), "Lumentum"),
    UniverseMember("FN", MEMBER, (NETWORKING,), "Fabrinet"),
    UniverseMember("AAOI", MEMBER, (NETWORKING,), "Applied Opto"),
    # Power and cooling.
    UniverseMember("VRT", MEMBER, (POWER_COOLING,), "Vertiv"),
    UniverseMember("ETN", MEMBER, (POWER_COOLING,), "Eaton"),
    UniverseMember("GEV", MEMBER, (POWER_COOLING,), "GE Vernova"),
    UniverseMember("CEG", MEMBER, (POWER_COOLING,), "Constellation"),
    UniverseMember("VST", MEMBER, (POWER_COOLING,), "Vistra"),
    UniverseMember("TLN", MEMBER, (POWER_COOLING,), "Talen"),
    UniverseMember("OKLO", MEMBER, (POWER_COOLING,), "Oklo"),
    UniverseMember("SMR", MEMBER, (POWER_COOLING,), "NuScale"),
    UniverseMember("BE", MEMBER, (POWER_COOLING,), "Bloom Energy"),
    UniverseMember("POWL", MEMBER, (POWER_COOLING,), "Powell"),
    UniverseMember("MOD", MEMBER, (POWER_COOLING,), "Modine"),
    # Software the money leaves for, or comes back to.
    UniverseMember("SNOW", MEMBER, (SOFTWARE,), "Snowflake"),
    UniverseMember("DDOG", MEMBER, (SOFTWARE,), "Datadog"),
    UniverseMember("MDB", MEMBER, (SOFTWARE,), "MongoDB"),
    UniverseMember("NET", MEMBER, (SOFTWARE,), "Cloudflare"),
    UniverseMember("CRWD", MEMBER, (SOFTWARE,), "CrowdStrike"),
    UniverseMember("PLTR", MEMBER, (SOFTWARE,), "Palantir"),
    UniverseMember("NOW", MEMBER, (SOFTWARE,), "ServiceNow"),
    UniverseMember("CRM", MEMBER, (SOFTWARE,), "Salesforce"),
    UniverseMember("ADBE", MEMBER, (SOFTWARE,), "Adobe"),
    UniverseMember("INTU", MEMBER, (SOFTWARE,), "Intuit"),
    UniverseMember("WDAY", MEMBER, (SOFTWARE,), "Workday"),
    UniverseMember("TEAM", MEMBER, (SOFTWARE,), "Atlassian"),
    UniverseMember("ZS", MEMBER, (SOFTWARE,), "Zscaler"),
    UniverseMember("PANW", MEMBER, (SOFTWARE,), "Palo Alto"),
)

# The market and the sector baskets, as ETFs. The market benchmark is the
# reference for every relative channel; the rest are the rotation gauges.
BENCHMARKS: tuple[UniverseMember, ...] = (
    UniverseMember("SPY", BENCHMARK, (), "S&P 500"),
    UniverseMember("QQQ", BENCHMARK, (), "Nasdaq 100"),
    UniverseMember("IWM", BENCHMARK, (), "Russell 2000"),
    UniverseMember("SMH", BENCHMARK, (AI_COMPUTE,), "Semis"),
    UniverseMember("SOXX", BENCHMARK, (AI_COMPUTE,), "Semis (iShares)"),
    UniverseMember("IGV", BENCHMARK, (SOFTWARE,), "Software"),
    UniverseMember("XLK", BENCHMARK, (), "Technology"),
    UniverseMember("XLU", BENCHMARK, (POWER_COOLING,), "Utilities"),
    UniverseMember("XLI", BENCHMARK, (), "Industrials"),
    UniverseMember("XLE", BENCHMARK, (), "Energy"),
    UniverseMember("XLF", BENCHMARK, (), "Financials"),
    UniverseMember("XLV", BENCHMARK, (), "Health care"),
    UniverseMember("XLC", BENCHMARK, (), "Communication"),
    UniverseMember("XLY", BENCHMARK, (), "Consumer discretionary"),
    UniverseMember("XLP", BENCHMARK, (), "Consumer staples"),
)


# Turn an index-style symbol into the form the data source uses: a class
# share written BRK.B is BRK-B at Yahoo.
def source_symbol(ticker: str) -> str:
    """Return the ticker in the data source's symbol form."""
    return ticker.strip().upper().replace(".", "-")


# Read the committed constituent file. Each row is one index member with its
# GICS sector and sub-industry; the header comment line records when it was
# taken, which is the date the survivorship caveat applies to.
def load_constituents(path: Path = CONSTITUENTS_PATH) -> list[UniverseMember]:
    """Return the index constituents from the committed CSV, themes from GICS."""
    if not path.exists():
        return []
    members: list[UniverseMember] = []
    with path.open(newline="", encoding="utf-8") as handle:
        rows = [line for line in handle if not line.startswith("#")]
    for row in csv.DictReader(rows):
        ticker = source_symbol(row["ticker"])
        sub_industry = row.get("sub_industry", "")
        members.append(
            UniverseMember(
                ticker=ticker,
                role=MEMBER,
                themes=SUB_INDUSTRY_THEMES.get(sub_industry, ()),
                name=row.get("name", ""),
                sector=row.get("sector", ""),
                sub_industry=sub_industry,
            )
        )
    return members


# Merge the constituent file, the overlay and the benchmarks into one
# universe, one entry per ticker, in a stable order: focus names first, then
# members alphabetically, then benchmarks.
#
# An overlay entry for a constituent keeps the constituent's sector data and
# adds the overlay's themes; the overlay's role wins (so SNDK, an index
# member, is still "focus").
def build_universe(
    constituents: list[UniverseMember] | None = None,
) -> tuple[UniverseMember, ...]:
    """Return the full universe: constituents + overlay + benchmarks, deduplicated."""
    if constituents is None:
        constituents = load_constituents()
    by_ticker: dict[str, UniverseMember] = {m.ticker: m for m in constituents}
    for entry in OVERLAY:
        existing = by_ticker.get(entry.ticker)
        if existing is None:
            by_ticker[entry.ticker] = entry
            continue
        themes = tuple(dict.fromkeys(existing.themes + entry.themes))
        by_ticker[entry.ticker] = UniverseMember(
            ticker=entry.ticker,
            role=entry.role,
            themes=themes,
            name=existing.name or entry.name,
            sector=existing.sector,
            sub_industry=existing.sub_industry,
        )
    for bench in BENCHMARKS:
        by_ticker[bench.ticker] = bench
    focus = sorted(
        (m for m in by_ticker.values() if m.role == FOCUS), key=lambda m: m.ticker
    )
    members = sorted(
        (m for m in by_ticker.values() if m.role == MEMBER), key=lambda m: m.ticker
    )
    benches = [by_ticker[b.ticker] for b in BENCHMARKS]
    return tuple(focus + members + benches)


# The tickers of one or more roles, in universe order.
def tickers_with_role(
    universe: tuple[UniverseMember, ...], *roles: str
) -> tuple[str, ...]:
    """Return the tickers in the universe whose role is one of `roles`."""
    wanted = set(roles) or {FOCUS, MEMBER, BENCHMARK}
    return tuple(m.ticker for m in universe if m.role in wanted)


# Ticker -> themes for every entry in the universe.
def theme_map(universe: tuple[UniverseMember, ...]) -> dict[str, tuple[str, ...]]:
    """Return a mapping from ticker to its theme tags."""
    return {m.ticker: m.themes for m in universe}


# The names the operator actually watches: the AI-infrastructure cluster and
# software. Everything the S&P tags as a semiconductor, communications
# equipment or software sub-industry, plus every overlay name. Plain
# utilities and electrical equipment that only carry the power theme through
# the index mapping stay out; they are not what the book trades.
BOOK_SUB_INDUSTRIES: frozenset[str] = frozenset(
    {
        "Semiconductors",
        "Semiconductor Materials & Equipment",
        "Communications Equipment",
        "Application Software",
        "Systems Software",
    }
)
AI_SIDE = "ai"
SOFTWARE_SIDE = "software"
_AI_THEMES = frozenset({AI_COMPUTE, MEMORY_STORAGE, NETWORKING, POWER_COOLING})


# Ticker -> side ("ai" or "software") for the names the book trades. A name
# is software when it carries the software theme and no AI-infrastructure
# theme (a hyperscaler that also sells software, like MSFT, is software; a
# chip name is AI). Benchmarks and everything else are left out.
def book_sides(universe: tuple[UniverseMember, ...]) -> dict[str, str]:
    """Return {ticker: "ai" | "software"} for the AI-and-software book."""
    overlay = {m.ticker for m in OVERLAY}
    sides: dict[str, str] = {}
    for m in universe:
        if m.role not in (FOCUS, MEMBER):
            continue
        if m.ticker not in overlay and m.sub_industry not in BOOK_SUB_INDUSTRIES:
            continue
        themes = set(m.themes)
        if SOFTWARE in themes and not themes & _AI_THEMES:
            sides[m.ticker] = SOFTWARE_SIDE
        elif themes & (_AI_THEMES | {HYPERSCALER}):
            sides[m.ticker] = AI_SIDE
    return sides
