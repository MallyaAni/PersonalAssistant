"""The closed vocabularies the trading system reads, writes and compares.

A label that names one of a fixed set of choices - an order's side, what the
board says to do about a name, a grade's signal, a timing decision's state - is
a member of one enum here and never a free-form string. A typo in a string
literal compares unequal and silently takes the other branch; a typo in a
member name is an AttributeError at import, and a stored or model-supplied
spelling outside the set is a ValueError at the boundary that read it.

Every enum keeps the exact spelling its field has always had on the wire,
casing included, because stored records, receipts, hashes and API payloads
must stay byte-identical: an order side is "buy", the board's action is
"Buy", a trade is "BUY". The casing differences are historical and each one
is a distinct field, so each has its own enum rather than one vocabulary
re-cased at the edges.

They are `StrEnum`s, so a member *is* its wire string: `json.dumps`, f-strings,
`str()`, dict lookups and hashing all see "buy". Two things do differ, and code
that relies on them must convert with `.value`: `repr()` (``<OrderSide.BUY:
'buy'>``) and an exact type test (`type(member) is str` is False). Pickle
also records the class, so a pickled label is not byte-identical.

Parse a label read from disk, an API or a model with the enum's constructor
(`OrderSide(raw)`) or with `parse` when the caller has its own error wording;
both raise ValueError on anything outside the set. Where existing code
deliberately tolerates an unknown or missing label, that tolerance is kept at
the call site with an equality test against a member and a comment saying so.

A few producers keep their own string literals because their exact source
bytes are pinned (by production code, committed data or the strategy
identity) and changing them would change what stored evidence verifies
against: `paper`, `intraday_orders`, `entry_timing`, the `live_model_history*`
and `historical_*` audits, `probabilistic_execution`, `grade_led_policy` and
the other policy sources. Code that reads what they return parses it through
the type (`TimingState(decision.state)`) before comparing by identity, and
a test pins the order board's and the entry timing's words to these types.
"""

from enum import StrEnum


# Read one label through its enum, with the caller's own error wording when it
# has one, so a value outside the vocabulary fails loudly at the boundary.
def parse[L: StrEnum](kind: type[L], value: object, message: str | None = None) -> L:
    """Return the member of `kind` spelled `value`, else raise ValueError."""
    try:
        return kind(value)
    except (ValueError, TypeError):
        if message is None:
            raise ValueError(f"{value!r} is not a valid {kind.__name__}") from None
        raise ValueError(message) from None


# The exact `str` a label is written as, for the few consumers that test a
# value's type exactly (a canonical encoder, a strict saved-versus-recomputed
# comparison); anything that is not a label is returned unchanged.
def wire(value: object) -> object:
    """Return a label's plain wire string, or `value` itself."""
    return value.value if isinstance(value, StrEnum) else value


# The member spelled `value`, or None when `value` is outside the vocabulary:
# for the call sites that deliberately tolerate an unknown or missing label
# (a display that shows nothing, a measurement that is skipped), so the
# tolerance is written down instead of hidden in a string comparison.
def as_member[L: StrEnum](kind: type[L], value: object) -> L | None:
    """Return the member of `kind` spelled `value`, or None."""
    try:
        return kind(value)
    except (ValueError, TypeError):
        return None


class OrderSide(StrEnum):
    """Which way an order, fill, broker row or timing decision trades."""

    BUY = "buy"
    SELL = "sell"


# The three things the operator can do about a name on the board. A fixed set,
# so it is a type rather than a string literal repeated at a dozen call sites:
# the old vocabulary had seven spellings across the backend, the API contract
# and the page, and "Buy eligible" against "Buy tonight" against "buy" was a
# bug waiting to happen. Defined in `decision_view` first and re-exported there.
class Action(StrEnum):
    """What to do about a name right now (the board's and the strategy's word)."""

    BUY = "Buy"
    SELL = "Sell"
    HOLD = "Hold"


class DeskAction(StrEnum):
    """What the desk's action board says to do about a holding at the next open.

    The first five are what `actions.action_for` derives from a target and a
    holding, and what the decision history classifies a move as. The last two
    exist only on the holdings board (`holdings.board`): BLOCKED overlays a buy
    or an add that the band-reversal gate holds back, and UNCOVERED marks a
    held name the desk has no opinion on. Nothing derives either from weights.
    """

    BUY = "buy"
    ADD = "add"
    HOLD = "hold"
    TRIM = "trim"
    SELL = "sell"
    BLOCKED = "blocked"
    UNCOVERED = "uncovered"


class GradeSignal(StrEnum):
    """What a name's close grade permits, from `grade_led_policy.signals`."""

    BUY = "buy"
    HOLD = "hold"
    SELL = "sell"
    AVOID = "avoid"
    UNAVAILABLE = "unavailable"


class TradeAction(StrEnum):
    """A trade's verb in capitals, as the trade lists and order history print it.

    A buy that opens a position is BUY and one that adds to it ADD; a sell
    that closes it is SELL and one that keeps the name TRIM. Each list uses
    the subset its producer can make: a weight path's trades are BUY or SELL.
    """

    BUY = "BUY"
    ADD = "ADD"
    TRIM = "TRIM"
    SELL = "SELL"


class AllocationAction(StrEnum):
    """A row's action in the funded `allocation_plan` display payload."""

    BUY = "BUY"
    HOLD = "HOLD"
    SELL = "SELL"


class TimingState(StrEnum):
    """A learned timing decision: trade now, wait for a better price, or not."""

    EXECUTE = "execute"
    WAIT = "wait"
    UNAVAILABLE = "unavailable"
    NO_TRADE = "no_trade"


class Grade(StrEnum):
    """A name's letter grade, best first."""

    A_PLUS = "A+"
    A = "A"
    B = "B"
    C = "C"


class ExecutionTiming(StrEnum):
    """When a planned order's row says it executes (its `execution_timing`)."""

    NEXT_OPEN = "next_open"
    # The intraday rule: a 15-minute close through the level, else the close.
    DIP_OR_CLOSE = "dip_or_close"
    # The FOMC restoration, sent on the decision session's last candle.
    DECISION_CLOSE = "decision_close"


class BoardTiming(StrEnum):
    """The execution rule the order board shows for a row (`timing_of`).

    A row's own `ExecutionTiming` where it has one, else EVENT for an FOMC
    order, NEXT_OPEN for a queued buy and CLOSE for a legacy closing sell.
    The order board's `timing` field. Its producer, `intraday_orders`, is a
    source-pinned module that keeps its own string constants; a test pins
    them to this type.
    """

    DIP_OR_CLOSE = "dip_or_close"
    NEXT_OPEN = "next_open"
    DECISION_CLOSE = "decision_close"
    EVENT = "event"
    CLOSE = "close"


class OrderLeg(StrEnum):
    """Which leg of the nightly plan an order belongs to, on the order board.

    The order board's `leg` field, written by the source-pinned
    `intraday_orders` from its own constants; a test pins them to this type.
    """

    RESET = "reset"
    RESET_EXIT = "reset-exit"
    EXIT = "exit"
    REINVEST = "reinvest"
    ENTRY = "entry"
    DEFERRED = "deferred"
    REDEPLOY = "redeploy"
    EVENT = "event"
    # A reason this repository did not write: the raw reason is shown.
    PLAN = "plan"


class EntryTimingState(StrEnum):
    """Where one name's intraday entry-timing rule stands (`entry_timing.timing`).

    The timing row's `state` field. `entry_timing` is source-pinned and keeps
    its own constants (`PRE_OPEN` ...); a test pins them to this type.
    """

    PRE_OPEN = "pre-open"
    WAITING = "waiting"
    TRIGGERED = "triggered"
    CLOSE = "close"
    CLOSED = "closed"


class PlanDay(StrEnum):
    """What kind of day the paper book's own rules planned (`paper.plan`).

    The third value a plan returns is a description written into the record's
    `plan` field. The paper book's rules return one of these words; the FOMC
    event plan and the funded policies return their own sentences, and the
    nightly may join two with "; ", so only these words are compared.
    """

    REBALANCE = "rebalance"
    HOLD = "hold"
    ENTRIES = "entries"
    EXITS = "exits"
    DEFERRED_BUYS = "deferred buys"
    REDEPLOY = "redeploy"


class TimingEntryRule(StrEnum):
    """An entry rule the chart-timing research compares (`timing_research`)."""

    FIRST_OPEN = "first_open"
    TREND_PULLBACK = "trend_pullback"
    BREAKOUT_RETEST = "breakout_retest"


class TimingExitRule(StrEnum):
    """An exit rule the chart-timing research compares; HOLD never exits."""

    HOLD = "hold"
    STRUCTURE = "structure"
    BAND_TRIM_THEN_STRUCTURE = "band_trim_then_structure"


class BacktestPending(StrEnum):
    """What a backtest position will do at the next open (`backtest.Position`)."""

    ENTER = "enter"
    # The two exits, each named by the rule that fired.
    STOP = "stop"
    GRADE = "grade"


class EntryState(StrEnum):
    """A name's price entry trigger at a close (`entry.Entries.kind`), or none."""

    DIP = "dip"
    BREAKOUT = "breakout"
    # Neither trigger fired: the name waits.
    WAIT = "wait"


class Verdict(StrEnum):
    """The one realtime verdict the dashboard shows per entry row."""

    BUY = "buy"
    SELL = "sell"
    NOTHING = "nothing"


class VerdictReason(StrEnum):
    """The closed reason code beside a `Verdict` (`strategy_verdict.REASONS`)."""

    EXECUTE_NOW = "execute_now"
    WAITING_BETTER_PRICE = "waiting_better_price"
    AT_TARGET = "at_target"
    NO_ALLOCATION = "no_allocation"
    GRADE_BELOW_A = "grade_below_a"
    AWAITING_CANDLE = "awaiting_candle"
    PUBLICATION_EXPIRED = "publication_expired"
    QUOTE_STALE = "quote_stale"
    PRICE_UNAVAILABLE = "price_unavailable"
    ENTRY_PENDING = "entry_pending"


class ExecutionIntent(StrEnum):
    """What a bounded IOC execution contract may do (`bounded_execution`).

    A buy is only ever an ENTRY; a sell is a TRIM or an EXIT, and an exit is
    sent without waiting for the entry-timing trigger.
    """

    ENTRY = "entry"
    TRIM = "trim"
    EXIT = "exit"


class ShadowForecastState(StrEnum):
    """The sequential execution shadow's forecast for one observed prefix.

    The learned decision's own states, plus TERMINAL_ATTEMPT on the session's
    last clock, where the shadow attempts whatever is left.
    """

    UNAVAILABLE = "unavailable"
    TERMINAL_ATTEMPT = "terminal_attempt"
    WAIT = "wait"
    EXECUTE = "execute"


class IntradayEntryState(StrEnum):
    """Where the intraday reclaim-above-level entry rule stands for one name."""

    UNAVAILABLE = "unavailable"
    WAIT = "wait"
    SETUP = "setup"
    ENTRY_READY = "entry_ready"
    INVALIDATED = "invalidated"
    AMBIGUOUS = "ambiguous"
    HISTORICAL = "historical"
    EXPIRED = "expired"


# The wire spellings of a vocabulary, in declaration order, for a JSON schema's
# "enum": the engine then cannot emit anything else.
def values(kind: type[StrEnum]) -> list[str]:
    """Return every member's wire string, in declaration order."""
    return [member.value for member in kind]


# The labels a model returns. Each is offered to the engine as a schema enum
# built from the type, sent strict (`backend.core.llm.StrictSchema`), and the
# reply is parsed back through the type, so the prompt's vocabulary, the
# grammar and the code reading the answer are one list.


class BriefStance(StrEnum):
    """The stance a desk brief takes on a name; it must follow the grade."""

    OWN = "own"
    WAIT = "wait"
    AVOID = "avoid"


class ClaimVerdict(StrEnum):
    """The brief checker's verdict on one claim against the measured facts."""

    CONSISTENT = "consistent"
    CONTRADICTS = "contradicts"
    UNCERTAIN = "uncertain"


class InflationPressure(StrEnum):
    """The economist's reading of inflation pressure from dated facts."""

    EASING = "easing"
    BUILDING = "building"
    MIXED = "mixed"
    UNKNOWN = "unknown"


class ChartEntry(StrEnum):
    """A current chart judgment's entry call for one stock."""

    READY = "ready"
    WAIT = "wait"
    AVOID = "avoid"
    # Essential chart evidence is missing; never for a stock with candles.
    UNAVAILABLE = "unavailable"


class ChartExit(StrEnum):
    """A current chart judgment's call for someone already holding the stock."""

    REVIEW = "review"
    HOLD = "hold"


class ChartPriority(StrEnum):
    """How compelling an entry, or how urgent an exit review, a chart reads."""

    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class ChartConfirmation(StrEnum):
    """The price behaviour that would confirm a chart entry, relative to a level."""

    HOLD_ABOVE = "hold_above"
    RECLAIM_ABOVE = "reclaim_above"
    NONE = "none"


class GuidanceChange(StrEnum):
    """What a release says about the company's guidance (grounded research read)."""

    RAISED = "raised"
    LOWERED = "lowered"
    UNCHANGED = "unchanged"
    NOT_COMPARABLE = "not_comparable"
    NOT_STATED = "not_stated"


class DemandTrend(StrEnum):
    """What a release says about demand (grounded research read)."""

    STRENGTHENING = "strengthening"
    WEAKENING = "weakening"
    STABLE = "stable"
    NOT_STATED = "not_stated"


class FinancingRisk(StrEnum):
    """What a release says about financing risk (grounded research read)."""

    INCREASING = "increasing"
    DECREASING = "decreasing"
    STABLE = "stable"
    NOT_STATED = "not_stated"


class FundingPreviewMode(StrEnum):
    """Which decision the desk's funding preview sizes against (`funding-preview`)."""

    EVENING = "evening"
    INTRADAY_RESEARCH = "intraday_research"


# Session vocabularies. Three fields name the time of day, each with its own
# historical spelling, so each has its own type: the exchange calendar's
# phase, the dashboard's phase (the words a broker shows), and the session a
# display quote was observed in.


class ExchangePhase(StrEnum):
    """The exchange calendar's phase (`calendar.exchange_status`)."""

    PRE_MARKET = "pre-market"
    OPEN = "open"
    POST_MARKET = "post-market"
    CLOSED = "closed"
    UNKNOWN = "unknown"


class MarketPhase(StrEnum):
    """The phase the dashboard states beside every recommendation (`market_phase`)."""

    PRE_MARKET = "pre_market"
    REGULAR = "regular"
    AFTER_HOURS = "after_hours"
    OVERNIGHT = "overnight"
    CLOSED = "closed"
    UNKNOWN = "unknown"


class QuoteSession(StrEnum):
    """The trading session a display quote was observed in (`session_prices`)."""

    REGULAR = "regular"
    PRE_MARKET = "pre-market"
    POST_MARKET = "post-market"
    OVERNIGHT = "overnight"
    CLOSED = "closed"
    UNKNOWN = "unknown"


class QuoteFeed(StrEnum):
    """Which market-data feed a display quote came from."""

    SIP = "sip"
    IEX = "iex"
    BOATS = "boats"
    OVERNIGHT = "overnight"
