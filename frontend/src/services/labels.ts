// The closed label vocabularies the desk API writes, spelled exactly as they
// arrive on the wire. They mirror `backend/market/labels.py`: one tuple per
// vocabulary, its union type, and one guard, so a component never compares
// against a free-form string or a list it typed for itself.
//
// These are wire values, not display text. Several vocabularies share
// spellings in different casings on purpose (an order side is `buy`, a plan
// action `Buy`, a simulated trade `BUY`) because each is what a different
// record has always stored; the words a person reads are mapped from these
// in the components, never derived by changing a label's case.

// A broker order or recorded fill direction.
export const ORDER_SIDES = ['buy', 'sell'] as const
export type OrderSide = (typeof ORDER_SIDES)[number]

// The plan action of a live decision row (`strategy_action` too).
export const PLAN_ACTIONS = ['Buy', 'Sell', 'Hold'] as const
export type PlanAction = (typeof PLAN_ACTIONS)[number]
// The two of them that trade, as a strategy entry or reference row names them.
export const PLAN_TRADES = ['Buy', 'Sell'] as const satisfies readonly PlanAction[]
export type PlanTrade = (typeof PLAN_TRADES)[number]

// What the action board does about a name; `blocked` and `uncovered` are the
// two rows that are not trades.
export const DESK_ACTIONS = ['buy', 'add', 'hold', 'trim', 'sell', 'blocked', 'uncovered'] as const
export type DeskActionLabel = (typeof DESK_ACTIONS)[number]
// The subset a replayed history row can carry.
export type HistoryAction = Exclude<DeskActionLabel, 'blocked' | 'uncovered'>
// The four of them that trade.
export const TRADED_ACTIONS = ['buy', 'add', 'trim', 'sell'] as const satisfies readonly HistoryAction[]
export type TradedAction = (typeof TRADED_ACTIONS)[number]
// The subset an admitted numeric model decision can carry.
export type ModelAction = Exclude<HistoryAction, 'add'>
export const MODEL_ACTIONS = ['buy', 'trim', 'sell', 'hold'] as const satisfies readonly ModelAction[]

// The grade-led policy's reading of one grade.
export const GRADE_SIGNALS = ['buy', 'hold', 'sell', 'avoid', 'unavailable'] as const
export type GradeSignal = (typeof GRADE_SIGNALS)[number]
// The two signals a positive model position may carry.
export const HOLDING_SIGNALS = ['buy', 'hold'] as const satisfies readonly GradeSignal[]

// A stock grade, best first.
export const GRADES = ['A+', 'A', 'B', 'C'] as const
export type Grade = (typeof GRADES)[number]
// The grades the grade-led policy admits a new entry at.
export const ENTRY_GRADES = ['A+', 'A'] as const satisfies readonly Grade[]

// A simulated or replayed trade of the strategy chart.
export const TRADE_ACTIONS = ['BUY', 'ADD', 'TRIM', 'SELL'] as const
export type TradeAction = (typeof TRADE_ACTIONS)[number]
// The three a strategy simulation decision row can carry.
export const SIMULATED_ACTIONS = ['BUY', 'SELL', 'TRIM'] as const satisfies readonly TradeAction[]
export type SimulatedAction = (typeof SIMULATED_ACTIONS)[number]

// A learned execution-timing decision.
export const TIMING_STATES = ['execute', 'wait', 'unavailable', 'no_trade'] as const
export type TimingState = (typeof TIMING_STATES)[number]

// The live entry-timing state of a `/4` decision row.
export const ENTRY_TIMING_STATES = ['pre-open', 'waiting', 'triggered', 'close', 'closed'] as const
export type EntryTimingState = (typeof ENTRY_TIMING_STATES)[number]

// The execution timing a planned order's row records (`execution_timing`)
// and the paper plan's rule (`ExecutionTiming` in the backend).
export const EXECUTION_TIMINGS = ['next_open', 'dip_or_close', 'decision_close'] as const
export type ExecutionTiming = (typeof EXECUTION_TIMINGS)[number]

// An execution timing a paper order or replayed trade names.
export const ORDER_TIMINGS = ['dip_or_close', 'decision_close', 'next_open', 'close', 'event'] as const
export type OrderTiming = (typeof ORDER_TIMINGS)[number]

// Where one paper order stands on the order board. The backend writes these
// words in `intraday_orders` (a source-bound module the labels enums do not
// reach), so this list is their one typed copy.
export const PAPER_ORDER_STATES = [
  'planned', 'waiting', 'due', 'sent', 'queued', 'filled', 'partial', 'held', 'cancelled', 'rejected', 'missed', 'problem',
] as const
export type PaperOrderState = (typeof PAPER_ORDER_STATES)[number]
// The states of an order that is over.
export const FINISHED_ORDER_STATES = ['filled', 'cancelled', 'rejected', 'missed'] as const satisfies readonly PaperOrderState[]
// The states of an order not yet handed to the broker.
export const UNSENT_ORDER_STATES = ['planned', 'waiting', 'due'] as const satisfies readonly PaperOrderState[]
// The states of an order the broker holds that has not finished filling.
export const SUBMITTED_ORDER_STATES = ['sent', 'queued', 'partial'] as const satisfies readonly PaperOrderState[]

// Where the current chart-judgment collection stands (`current_opportunities`).
export const OPPORTUNITY_STATUSES = ['pending', 'unavailable', 'stale', 'building', 'collected'] as const
export type OpportunityStatus = (typeof OPPORTUNITY_STATUSES)[number]

// The board's verdict on one name.
export const VERDICTS = ['buy', 'sell', 'nothing'] as const
export type Verdict = (typeof VERDICTS)[number]

// A current chart judgment.
export const CHART_ENTRIES = ['ready', 'wait', 'avoid', 'unavailable'] as const
export type ChartEntry = (typeof CHART_ENTRIES)[number]
export const CHART_EXITS = ['review', 'hold'] as const
export type ChartExit = (typeof CHART_EXITS)[number]
export const CHART_PRIORITIES = ['high', 'medium', 'low'] as const
export type ChartPriority = (typeof CHART_PRIORITIES)[number]

// The session a quote was observed in.
export const QUOTE_SESSIONS = ['pre-market', 'post-market', 'overnight', 'regular', 'closed', 'unknown'] as const
export type QuoteSession = (typeof QUOTE_SESSIONS)[number]
// The sessions outside the regular one in which a quote can still be observed.
export const EXTENDED_SESSIONS = ['pre-market', 'post-market', 'overnight'] as const satisfies readonly QuoteSession[]
// The two that name no trading session at all.
export const NO_SESSIONS = ['closed', 'unknown'] as const satisfies readonly QuoteSession[]

// The exchange's phase as the market status reports it.
export const EXCHANGE_PHASES = ['unknown', 'closed', 'pre-market', 'open', 'post-market'] as const
export type ExchangePhase = (typeof EXCHANGE_PHASES)[number]

// The trading-calendar phase the session clock reports.
export const MARKET_PHASES = ['pre_market', 'regular', 'after_hours', 'overnight', 'closed', 'unknown'] as const
export type MarketPhase = (typeof MARKET_PHASES)[number]

// The stance a model-written desk brief takes on a name.
export const BRIEF_STANCES = ['own', 'wait', 'avoid'] as const
export type BriefStance = (typeof BRIEF_STANCES)[number]

// The entry trigger the intraday candidate records for a name.
export const ENTRY_STATES = ['dip', 'breakout', 'wait'] as const
export type EntryState = (typeof ENTRY_STATES)[number]

// The economist's inflation reading.

export const INFLATION_PRESSURES = ['easing', 'building', 'mixed', 'unknown'] as const
export type InflationPressure = (typeof INFLATION_PRESSURES)[number]

// Whether the installed rule's account simulation exists for the record shown.
export const SIMULATION_STATUSES = ['available', 'missing'] as const
export type SimulationStatus = (typeof SIMULATION_STATUSES)[number]

// The nightly check of the paper plan against the account simulator: its
// verdict, what a mismatch row is about, and which planner owned the night.
export const PLAN_PARITY_VERDICTS = ['ok', 'mismatch', 'unavailable'] as const
export type PlanParityVerdict = (typeof PLAN_PARITY_VERDICTS)[number]
export const PLAN_PARITY_KINDS = ['policy', 'path', 'inputs', 'sizing', 'holding'] as const
export type PlanParityKind = (typeof PLAN_PARITY_KINDS)[number]
export const PLAN_PATHS = ['ordinary', 'event'] as const
export type PlanPath = (typeof PLAN_PATHS)[number]

// A grade's place in the order, best highest.
export const GRADE_RANK: Record<Grade, number> = {'A+': 3, A: 2, B: 1, C: 0}

// Whether `value` is one of `kind`'s labels, exactly as spelled.
export const isLabel = <const T extends readonly string[]>(kind: T, value: unknown): value is T[number] =>
  typeof value === 'string' && (kind as readonly string[]).includes(value)

// Read a table keyed by one vocabulary for a value that may be outside it:
// undefined unless `value` is one of the table's own labels.
export const lookup = <K extends string, V>(table: Record<K, V>, value: unknown): V | undefined =>
  typeof value === 'string' && Object.prototype.hasOwnProperty.call(table, value) ? table[value as K] : undefined

// The end of an exhaustive switch over a label: a new label fails to compile
// here, and a value outside the vocabulary fails loudly at run time.
export const assertNever = (value: never, kind: string): never => {
  throw new Error(`Unknown ${kind} label: ${String(value)}`)
}

// The end of an exhaustive switch in display code: a new label fails to
// compile here, while a value outside the vocabulary that reached the page
// anyway renders as `fallback` instead of taking the page down.
export const exhausted = <T>(value: never, fallback: T): T => {
  void value
  return fallback
}
