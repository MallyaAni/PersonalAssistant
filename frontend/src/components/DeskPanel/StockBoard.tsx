import { Fragment, useEffect, useRef, useState, type ReactNode } from 'react'
import type { DeskDecisions, DeskHolding, DeskLive, DeskLiveGrade, DeskPayload, DeskRecord } from '../../services/api'

// The three things the desk can be doing about a name. Declared here because
// this is the board that lists them and DeskPanel already imports from it; the
// other direction would be a cycle.
export const PLAN_ACTIONS = ['Buy', 'Sell', 'Hold'] as const
export type PlanAction = (typeof PLAN_ACTIONS)[number]

const ORDER: Record<string, number> = {'A+': 3, A: 2, B: 1, C: 0}
type SortColumn = 'ticker' | 'grade' | 'opportunity' | 'plan' | 'weight'
// The natural first direction for each column: a name list reads A to Z, a
// measure reads biggest first.
const DESCENDING_FIRST: Record<SortColumn, boolean> = {ticker: false, grade: true, opportunity: true, plan: false, weight: true}

// Format a portfolio weight without rounding a small positive allocation to zero.
const percentage = (weight: number) => weight > 0 && weight < .001 ? '<0.1%' : `${(weight * 100).toFixed(1)}%`

// A name's move against its last close, in green or red with an arrow so the
// direction reads without colour; nothing when there is no close to compare
// against. This is the row a trader scans for, so it sits beside the price.
const ChangeMark = ({ last, close }: { last: number; close: number | null | undefined }) => {
  if (close == null || close <= 0 || !Number.isFinite(last)) return null
  const raw = (last / close - 1) * 100
  // Below a twentieth of a point the row would print a signed zero, which
  // reads as a move that did not happen.
  const change = Math.abs(raw) < 0.05 ? 0 : raw
  const up = change > 0
  const down = change < 0
  const cls = up ? 'text-[#1e7a3a]' : down ? 'text-[#b42318]' : 'text-[#6e6e73]'
  const mark = up ? '↑' : down ? '↓' : '·'
  const sign = change > 0 ? '+' : ''
  return <span className={`ml-1 ${cls}`} title="vs the last close">{mark} {sign}{change.toFixed(1)}%</span>
}

// Whether the exchange is open at `now`, on New York time.
export const marketOpenAt = (now: number) => {
  const parts = new Intl.DateTimeFormat('en-US', {timeZone: 'America/New_York', weekday: 'short', hour: 'numeric', minute: 'numeric', hour12: false}).formatToParts(new Date(now))
  const get = (type: string) => parts.find(p => p.type === type)?.value ?? ''
  const minutes = Number(get('hour')) * 60 + Number(get('minute'))
  return !['Sat', 'Sun'].includes(get('weekday')) && minutes >= 9 * 60 + 30 && minutes < 16 * 60
}

// Keep the confirmed fill date on the exchange's calendar.
const today = () => new Intl.DateTimeFormat('en-CA', {timeZone: 'America/New_York', year: 'numeric', month: '2-digit', day: '2-digit'}).format(new Date())

// What the board shows during an FOMC cycle: the exposure the desk actually
// holds (null while the cycle's current policy status is unknown), the
// decision the cycle belongs to, and whether the calendar itself is missing.
export type BoardEvent = {exposure: number | null; decisionDate: string | null; calendarUnknown: boolean}

// The board's own simulation, read as a footer under the research view:
// measurement, not a decision, so it no longer sits under the stock list.
export const BoardSimulation = ({paper, now}: {paper?: DeskPayload['board_paper']; now: number}) => {
  return paper?.equity === undefined ? null : <p aria-label="Board simulation" className="border-t px-3 py-2 text-[11px] text-[#6e6e73]" title="Separate local simulation, not a brokerage account. Delayed quotes, spread and 10 bp extra cost per side. No real orders. Overnight marks wait for corporate-action validation.">
      Board simulation · research, not the practice account · {paper.equity.toLocaleString('en-US', {style: 'currency', currency: 'USD'})} · USD {percentage(paper.cash / paper.equity)} · {((paper.equity / paper.initial_capital - 1) * 100).toFixed(2)}% since start {new Date(paper.started_at).toLocaleDateString('en-US', {timeZone: 'America/New_York', month: 'short', day: 'numeric'})}
      <span className="ml-1">· {new Date(paper.as_of).toLocaleString('en-US', {timeZone: 'America/New_York', month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit'})} ET{now - Date.parse(paper.as_of) >= 900000 ? ' · awaiting update' : ''}</span>
    </p>
}

// The frozen ML shadow against the desk, research only.
export const MlComparison = ({ml}: {ml?: DeskPayload['ml_forward']}) => {
  return !ml ? null : <details aria-label="ML forward comparison" className="shrink-0 border-t px-3 py-2 text-xs">
      <summary className="cursor-pointer">ML paper comparison · {ml.session ?? 'awaiting first close'}</summary>
      <p className="my-2 text-[#6e6e73]">Separate simulated accounts starting at $100,000 each. Frozen model; no real orders. Updated nightly. Costs of 10 or 30 basis points per traded dollar are included. This research portfolio does not follow the live desk’s FOMC policy.</p>
      <p>{ml.status}</p>
      {ml.observed_at && <p>Last observed {new Date(ml.observed_at).toLocaleString('en-US', {timeZone: 'America/New_York'})} ET</p>}
      <table aria-label="ML paper returns" className="mt-2 w-full tabular-nums"><thead><tr><th className="text-left">Policy / cost</th><th>Account</th><th>Return</th></tr></thead>
        <tbody>{Object.entries(ml.accounts).map(([name, account]) => <tr key={name}><td>{name}</td><td className="text-center">{account.equity.toLocaleString('en-US', {style: 'currency', currency: 'USD'})}</td><td className="text-center">{(account.total_return * 100).toFixed(2)}%</td></tr>)}</tbody>
      </table>
    </details>
}

// A column heading that sorts. It says which way it is sorting, and a third
// click hands the board back to the desk's own ranking.
const SortHead = ({column, sort, onSort, children, className = '', title}: {
  column: SortColumn
  sort: {column: SortColumn; descending: boolean} | null
  onSort: (next: {column: SortColumn; descending: boolean} | null) => void
  children: ReactNode
  className?: string
  title?: string
}) => {
  const active = sort?.column === column
  return <th className={className} aria-sort={!active ? 'none' : sort!.descending ? 'descending' : 'ascending'}>
    <button
      type="button"
      title={title}
      className="flex items-center gap-1 font-normal hover:text-[#0071e3]"
      onClick={() => onSort(
        !active ? {column, descending: DESCENDING_FIRST[column]}
        : sort!.descending === DESCENDING_FIRST[column] ? {column, descending: !DESCENDING_FIRST[column]}
        : null,
      )}
    >
      {children}
      <span aria-hidden="true" className={active ? 'text-[#0071e3]' : 'text-[#c7c7cc]'}>{!active ? '↕' : sort!.descending ? '↓' : '↑'}</span>
    </button>
  </th>
}

// The Plan heading: it sorts like the others, and it carries the filter for
// its own column. A board of ninety names is mostly Hold - on the live book
// eighty-eight of ninety-three - so the handful the desk is trading is a few
// rows buried among them, below the first page. The filter is here rather
// than in the toolbar because it belongs to this column and because a row of
// checkboxes standing permanently above the table is noise for a reader who
// never wants them.
const PlanHead = ({sort, onSort, plans, shown, onShown}: {
  sort: {column: SortColumn; descending: boolean} | null
  onSort: (next: {column: SortColumn; descending: boolean} | null) => void
  plans: {name: PlanAction; count: number}[]
  shown: Record<PlanAction, boolean>
  onShown: (next: Record<PlanAction, boolean>) => void
}) => {
  const [open, setOpen] = useState(false)
  const box = useRef<HTMLDivElement>(null)
  const filtered = PLAN_ACTIONS.some(name => !shown[name])
  const active = sort?.column === 'plan'
  // Close on a click anywhere else, and on Escape, so the popover never
  // strands itself over the board.
  useEffect(() => {
    if (!open) return
    const away = (e: MouseEvent) => { if (box.current && !box.current.contains(e.target as Node)) setOpen(false) }
    const key = (e: KeyboardEvent) => { if (e.key === 'Escape') setOpen(false) }
    document.addEventListener('mousedown', away)
    document.addEventListener('keydown', key)
    return () => { document.removeEventListener('mousedown', away); document.removeEventListener('keydown', key) }
  }, [open])
  return <th aria-sort={!active ? 'none' : sort!.descending ? 'descending' : 'ascending'}>
    <div ref={box} className="relative flex items-center gap-1">
      {/* The heading filters and the arrow sorts, not the other way round.
          Clicking the word "Plan" sorted the board, which is what every other
          column does and is not what this one is for: on a board that is
          eighty-eight Holds out of ninety-three, what a reader wants from this
          column is to see the few names being traded, and sorting leaves all
          ninety-three in place. Sorting is still here, on the arrow. */}
      <button
        type="button"
        aria-haspopup="true"
        aria-expanded={open}
        aria-label={filtered ? 'Filter the plan column (filtered)' : 'Filter the plan column'}
        title="Show only certain plans"
        className={`flex items-center gap-1 rounded font-normal hover:text-[#0071e3] ${filtered ? 'text-[#0071e3]' : ''}`}
        onClick={() => setOpen(!open)}
      >
        Plan
        <span aria-hidden="true" className={filtered ? 'text-[#0071e3]' : 'text-[#c7c7cc]'}>{'▾'}</span>
      </button>
      <button
        type="button"
        title="Sort the board by plan"
        aria-label="Sort by plan"
        className="rounded px-0.5 leading-none hover:text-[#0071e3]"
        onClick={() => onSort(
          !active ? {column: 'plan', descending: DESCENDING_FIRST.plan}
          : sort!.descending === DESCENDING_FIRST.plan ? {column: 'plan', descending: !DESCENDING_FIRST.plan}
          : null,
        )}
      >
        <span aria-hidden="true" className={active ? 'text-[#0071e3]' : 'text-[#c7c7cc]'}>{!active ? '↕' : sort!.descending ? '↓' : '↑'}</span>
      </button>
      {open && (
        <div role="group" aria-label="Show these plans" className="absolute left-0 top-full z-20 mt-1 w-40 rounded-lg border border-black/[0.1] bg-white p-2 shadow-lg">
          {plans.map(({name, count}) => (
            <label key={name} className="flex cursor-pointer items-center gap-2 rounded px-1 py-1 font-normal text-[#1d1d1f] hover:bg-[#f5f5f7]">
              <input
                type="checkbox"
                className="cursor-pointer accent-[#0071e3]"
                checked={shown[name]}
                aria-label={`Show ${name} rows`}
                onChange={(e) => onShown({...shown, [name]: e.target.checked})}
              />
              <span className="flex-1">{name}</span>
              <span className="tabular-nums text-[#6e6e73]">{count}</span>
            </label>
          ))}
          <button
            type="button"
            className="mt-1 w-full rounded px-1 py-1 text-left font-normal text-[#0071e3] hover:bg-[#f5f5f7]"
            onClick={() => onShown({Buy: true, Sell: true, Hold: true})}
          >
            Show all
          </button>
        </div>
      )}
    </div>
  </th>
}

// Present stocks and cash together, with details deferred until a person asks.
export const StockBoard = ({latest, live, grades, research, paper, ml, coverage, decisions, holdings, event, now, action, onOpen, onBuy, saving, error, holdingsError, expand, toolbar, trade, footer, closes, planAction, extraNames = []}: {
  latest: DeskRecord; live: DeskLive; grades: Record<string, DeskLiveGrade>;
  research: DeskPayload['intraday_research']; holdings: DeskHolding[] | null;
  paper?: DeskPayload['board_paper'];
  ml?: DeskPayload['ml_forward'];
  decisions?: DeskDecisions;
  coverage?: DeskPayload['coverage'];
  event: BoardEvent | null; now: number; action: (ticker: string, allocation: number | null) => ReactNode;
  onOpen: (ticker: string) => void;
  onBuy?: (ticker: string, price: number, shares: number, date: string) => Promise<boolean>;
  saving: boolean; error: string; holdingsError?: string;
  // What a row shows when opened in place: the plan for that name, its
  // reasons and a way to the full panel.
  expand?: (ticker: string) => ReactNode;
  // The account's controls above the list, the plan for a name in its row,
  // and the note under the list.
  toolbar?: ReactNode;
  trade?: (ticker: string) => ReactNode;
  footer?: ReactNode;
  // What the Plan column says for a name, so that column can sort.
  planAction?: (ticker: string) => string;
  // Each name's last close, to show today's move against it on the row.
  closes?: Record<string, number | null>;
  // Names the account holds that the desk does not grade: listed last,
  // never folded, so a held position is never invisible.
  extraNames?: string[];
}) => {
  const [buy, setBuy] = useState<string | null>(null)
  const [shares, setShares] = useState('')
  const [price, setPrice] = useState('')
  const [date, setDate] = useState(today)
  const [query, setQuery] = useState('')
  // Which plans to list. All three on is the whole board, the view this has
  // always shown, so the filter costs a reader who ignores it nothing.
  const [shownPlans, setShownPlans] = useState<Record<PlanAction, boolean>>({Buy: true, Sell: true, Hold: true})
  const [visible, setVisible] = useState(10)
  const [opened, setOpened] = useState<string | null>(null)
  // Any column sorts on a click: first click takes the useful direction for
  // that column (best grade, biggest score, biggest size, A to Z), a second
  // reverses it, a third returns to the desk's own ranking.
  const [sort, setSort] = useState<{column: SortColumn; descending: boolean} | null>(null)
  const pending = useRef(false)
  // A research size is shown only while it is current for that one name: the
  // allocation was built on a single bar, so a name whose own live quote does
  // not share that bar gets a dash instead of turning the whole board off.
  // The cash row and the weight ranking still need the complete, synchronized
  // set, so those stay all-or-nothing.
  // During an FOMC cycle the sizes stay on the board at the exposure the
  // desk holds - half while reduced, full once restoration is queued - so a
  // 20% target reads 10% and cash carries the rest. They are hidden only
  // while that exposure is unknown: a missing calendar, or an active cycle
  // whose current policy status has not been read.
  const paused = event !== null
  const hidden = paused && (event.calendarUnknown || event.exposure === null)
  const exposure = paused && event.exposure !== null ? event.exposure : 1
  // Sizes are the 15-minute model allocations and stay on the board once
  // collected for this decision: through the close and through a gap in the
  // candle run, so the column never blanks between sessions. Before the
  // candle run has produced an allocation for the current decision (a new
  // nightly record, overnight, pre- or post-market) the board shows the
  // adopted plan's target weights instead, so the column always reads.
  const marketClosed = !marketOpenAt(now)
  // Which sizing policy the board is showing. It used to be inferred: live
  // sizes when a current bar existed, plan targets otherwise, with no way to
  // ask for the other one. A trader comparing "what the rebalance will do"
  // against "what this bar says" had to read two different places, so it is
  // a control now, and picking one re-sizes and re-ranks the list in place.
  const liveSizingReady = research?.session === latest.session && !!research?.targets
  const [policy, setPolicy] = useState<'live' | 'plan'>('live')
  const showSizes = liveSizingReady && policy === 'live'
  const planTargets = Object.fromEntries((latest.book ?? []).map(b => [b.ticker, b.weight]))
  const weightOf = (ticker: string) => {
    if (hidden) return null
    const weights = showSizes ? (research!.targets ?? {}) : planTargets
    if (showSizes && !marketClosed && research!.bar !== live.quotes[ticker]?.bar) return null
    const weight = weights[ticker]
    return Number.isFinite(weight) && (weight as number) >= 0 ? (weight as number) * exposure : null
  }
  const graded = Object.keys(latest.grades)
  const sizedNames = !hidden ? graded.filter(ticker => weightOf(ticker) !== null) : []
  const fullCoverage = showSizes && sizedNames.length === graded.length && graded.length > 0
  const gross = fullCoverage ? Object.values(research!.targets ?? {}).reduce((sum, weight) => sum + weight, 0) * exposure : null
  const sized = fullCoverage && gross !== null && gross <= 1.000001
  const fomcLine = !paused ? null
    : event.calendarUnknown ? 'FOMC calendar unavailable · exposure changes and sizing paused'
    : event.exposure === null ? 'FOMC cycle in progress · sizes paused until the policy status is current'
    : event.exposure < 1 ? `FOMC · sizes at ${event.exposure === 0.5 ? 'half' : `${Math.round(event.exposure * 100)}%`} exposure · restores at the open after the ${event.decisionDate ?? 'FOMC'} decision`
    : 'FOMC · restoration queued for the next open'
  // The policy toggle beside this already names which sizing is showing, so
  // the line says what is true of it rather than repeating the label.
  const sizingLine = !showSizes ? 'Target weights'
    : sized ? 'Sizes for this bar'
    : sizedNames.length > 0 ? `Sized on this bar for ${sizedNames.length} of ${graded.length} names`
    : marketClosed ? 'Sizes return with the first completed bar after the open'
    : 'Sizing unavailable · waiting for fresh data'
  // The conviction index is dated to its bar and survives the close, so the
  // column is never blank overnight or pre- and post-market; only the
  // decision it belongs to changes what is shown.
  const opportunity = (ticker: string) => {
    const value = decisions?.rows[ticker]?.opportunity
    return decisions?.session === latest.session && decisions.written === latest.written
      && value?.bar === live.quotes[ticker]?.bar
      && Number.isFinite(value?.score) ? value!.score : null
  }
  // Which analysts had no reading for this name. The score is renormalised
  // over the rest, so a name scored on a narrow panel is not comparable to
  // one scored on the full five, and the board has to say so rather than
  // printing a number that looks like everyone else's.
  const narrow = (ticker: string): string[] => decisions?.rows[ticker]?.opportunity?.missing ?? []
  const stocks = [...Object.entries(latest.grades).map(([ticker, grade]) => ({
    ticker, grade: grades[ticker]?.grade_live ?? grade.grade,
    score: grades[ticker]?.score_live ?? grade.score,
    opportunity: opportunity(ticker),
    narrow: narrow(ticker),
    weight: weightOf(ticker),
  })), ...extraNames.filter(ticker => !(ticker in latest.grades)).map(ticker => ({ticker, grade: '', score: -Infinity, opportunity: null, narrow: [] as string[], weight: null}))].sort((a, b) =>
    // The book leads. A trader's first question is what to own and how
    // much, and the handful of names carrying a target weight is the whole
    // answer; the rest of the graded universe is a watchlist behind it.
    // Sorting by grade alone buried a sized A under an unsized A+, which is
    // backwards for anyone deciding what to do now. Every column still
    // sorts on a click when a different question is being asked.
    ((b.weight ?? -1) > 0 ? 1 : 0) - ((a.weight ?? -1) > 0 ? 1 : 0)
    || ((a.weight ?? 0) > 0 && (b.weight ?? 0) > 0 ? (b.weight ?? 0) - (a.weight ?? 0) : 0)
    || (ORDER[b.grade] ?? -1) - (ORDER[a.grade] ?? -1)
    || (b.opportunity ?? -1) - (a.opportunity ?? -1)
    || (sized ? (b.weight ?? 0) - (a.weight ?? 0) : 0)
    || b.score - a.score || a.ticker.localeCompare(b.ticker))
  const emptyAccount = holdings !== null && holdings.length === 0
  const heldNames = new Set((holdings ?? []).map((h) => h.ticker))
  const planGross = !showSizes && !hidden
    // `* exposure` to match weightOf: every row is scaled by it, so the cash
    // remainder must be too or the column does not sum to the account during
    // an FOMC cycle.
    ? Object.values(planTargets).reduce((sum, w) => sum + (Number.isFinite(w) ? (w as number) : 0), 0) * exposure
    : null
  const cash = {ticker: '__cash__', grade: '', score: 0, opportunity: null, narrow: [] as string[], weight: sized ? Math.max(0, 1 - gross!) : planGross !== null ? Math.max(0, 1 - planGross) : paused && emptyAccount ? 1 : null}
  const cashIndex = hidden || (paused && !sized) ? 0 : sized ? stocks.findIndex(stock => stock.weight! <= cash.weight!) : stocks.length
  // The board opens with the top page of names and pages on request, so a
  // ninety-name list never becomes a wall to scroll through. A search narrows
  // to the names that match, and the cash row anchors only the full board: a
  // search looks for a name, not for uninvested cash.
  const searchText = query.trim().toLowerCase()
  // And the plan filter, which answers the question the search box cannot:
  // not "where is this name" but "what is the desk actually doing today".
  // On a ninety-name board the handful of Buys and Sells is a few rows among
  // eighty-odd Holds, and finding them meant reading every one.
  //
  // The cash row is not a plan, so it is never filtered out by one.
  // Anything that is not one of the three counts as Hold rather than opening a
  // fourth bucket no checkbox controls: a stray word would otherwise become a
  // row that every filter hides. "Wait" reached this column once already.
  const planOf = (ticker: string): PlanAction => {
    const said = planAction?.(ticker)
    return PLAN_ACTIONS.includes(said as PlanAction) ? (said as PlanAction) : 'Hold'
  }
  const plans = PLAN_ACTIONS.map(name => ({
    name,
    count: stocks.filter(s => s.ticker !== '__cash__' && planOf(s.ticker) === name).length,
  }))
  const everyPlan = PLAN_ACTIONS.every(name => shownPlans[name])
  const byPlan = everyPlan
    ? stocks
    : stocks.filter(s => s.ticker === '__cash__' || shownPlans[planOf(s.ticker)])
  const filtered = searchText ? byPlan.filter((s) => s.ticker.toLowerCase().includes(searchText)) : byPlan
  // A chosen column replaces the desk's ranking; a name the column cannot
  // measure sorts to the bottom either way, so a dash never leads the board.
  const sorted = !sort ? filtered : [...filtered].sort((a, b) => {
    const missing = (row: typeof a) =>
      sort.column === 'opportunity' ? row.opportunity === null
      : sort.column === 'weight' ? row.weight === null
      : sort.column === 'grade' ? !row.grade
      : false
    if (missing(a) !== missing(b)) return missing(a) ? 1 : -1
    const of = (row: typeof a) =>
      sort.column === 'ticker' ? row.ticker
      : sort.column === 'grade' ? (ORDER[row.grade] ?? -1)
      : sort.column === 'opportunity' ? (row.opportunity ?? -Infinity)
      : sort.column === 'plan' ? (planAction?.(row.ticker) ?? '')
      : (row.weight ?? -Infinity)
    const left = of(a), right = of(b)
    const order = typeof left === 'string' && typeof right === 'string'
      ? left.localeCompare(right as string)
      : (left as number) - (right as number)
    return (sort.descending ? -order : order) || a.ticker.localeCompare(b.ticker)
  })
  const ranked = [...sorted]
  if (!searchText && !sort) ranked.splice(cashIndex < 0 ? ranked.length : Math.min(cashIndex, ranked.length), 0, cash)
  const bar = showSizes && !marketClosed ? research!.bar : live.data_at
  const time = bar ? new Date(bar).toLocaleString('en-US', {timeZone: 'America/New_York', month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit'}) : null
  return <section aria-label="Stocks and cash" className="flex min-h-0 flex-1 flex-col overflow-hidden rounded-2xl border border-black/[0.08] bg-white">
    <div className="shrink-0 border-b border-black/[0.06] px-3 py-2 text-xs text-[#6e6e73]">
      <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
        <p>{fomcLine ?? sizingLine}</p>
        {/* Switching the policy re-sizes and re-ranks the list in place, so
            "what the rebalance will do" and "what this bar says" are the
            same list read two ways rather than two screens. */}
        {liveSizingReady && !hidden && (
          <div className="flex shrink-0 gap-1" role="group" aria-label="Sizing policy">
            {([['live', 'This bar'], ['plan', 'At the reset']] as const).map(([value, label]) => (
              <button
                key={value}
                type="button"
                aria-pressed={policy === value}
                onClick={() => setPolicy(value)}
                className={`rounded px-2 py-0.5 ${policy === value ? 'bg-[#1d1d1f] text-white' : 'bg-[#f5f5f7] text-[#6e6e73] hover:text-[#0071e3]'}`}
              >
                {label}
              </button>
            ))}
          </div>
        )}
      </div>
      {fomcLine && !hidden && <p className="mt-0.5">{sizingLine}</p>}
      <p className="mt-0.5" title="Fundamental analysis is nightly; prices and technical grades use completed intraday bars.">{time ? `Bar ${time} ET` : 'No current bar'} · updates every 15 minutes while the market is open{live.stale && !marketClosed ? ' · market data stale' : ''}</p>
      {coverage && <p className="mt-0.5" title="The tracked universe spans sectors. Only names with a desk grade are ranked here; broader grading is not yet validated.">{coverage.graded} graded · {coverage.tracked} tracked</p>}
    </div>
    {toolbar}
    <div className="min-h-0 flex-1 overflow-auto">
      <table className="w-full min-w-max text-left text-sm tabular-nums [&_td]:px-2 [&_th]:px-2" aria-label="Ranked stocks and cash">
        <thead className="sticky top-0 z-10 bg-[#f5f5f7] text-xs text-[#6e6e73]">
          <tr className="border-b border-black/[0.06]">
            <th colSpan={7} className="py-2 pr-3 font-normal">
              <div className="flex flex-wrap items-center gap-2">
                <input
                  type="search"
                  value={query}
                  onChange={(e) => { setQuery(e.target.value); setVisible(10) }}
                  placeholder="Search a ticker"
                  aria-label="Search the stock list"
                  className="w-full max-w-52 rounded-md border border-black/[0.12] bg-white px-2 py-1 text-sm text-[#1d1d1f] placeholder:text-[#9ca3af]"
                />
                {searchText && <span className="text-[#6e6e73]">{filtered.length} match{filtered.length === 1 ? '' : 'es'}</span>}
              </div>
            </th>
          </tr>
          <tr>
            <th className="py-2">#</th>
            <SortHead column="ticker" sort={sort} onSort={setSort}>Stock</SortHead>
            <SortHead column="grade" sort={sort} onSort={setSort} title={`A+ down to C from the ${latest.session} close, or the intraday grade where one is current`}>Grade</SortHead>
            <SortHead column="opportunity" sort={sort} onSort={setSort} className="hidden sm:table-cell" title="The analysts' combined conviction at this bar, 0 to 10, not a return forecast. A star marks a name scored without the full panel.">Opportunity</SortHead>
            {planAction
              ? <PlanHead sort={sort} onSort={setSort} plans={plans} shown={shownPlans} onShown={(next) => { setShownPlans(next); setVisible(10) }} />
              : <SortHead column="plan" sort={sort} onSort={setSort} title="The desk's plan for this name">Plan</SortHead>}
            <SortHead column="weight" sort={sort} onSort={setSort} title="Share of the account under the sizing policy above.">Size %</SortHead>
            <th><span className="sr-only">Record purchase</span></th>
          </tr>
        </thead>
        <tbody>{ranked.map((row, index) => {
          // A held position stays on the board even beyond the current
          // page: a held name must never scroll out of sight. The cash row
          // is not exempt, because planned cash already reads in the strip
          // above the board and the top page should stay "top names".
          if (index >= visible && !heldNames.has(row.ticker)) return null
          const held = holdings?.find(position => position.ticker === row.ticker)
          const quote = live.quotes[row.ticker]
          const isCash = row.ticker === '__cash__'
          const open = opened === row.ticker
          return <Fragment key={row.ticker}><tr className={`border-t border-black/[0.05] ${isCash ? 'bg-[#0071e3]/10' : ''}`}>
            <td className="w-7 text-xs text-[#6e6e73]">{isCash || !expand ? index + 1 : <button type="button" aria-label={`details for ${row.ticker}`} aria-expanded={open} className="w-5 text-[#0071e3]" onClick={() => setOpened(open ? null : row.ticker)}>{open ? '▾' : '▸'}</button>}</td>
            <td className="py-2">
              {isCash ? <span className="font-semibold">USD</span> : <button className="font-semibold hover:text-[#0071e3]" onClick={() => onOpen(row.ticker)}>{row.ticker}</button>}
              <div className="text-[11px] text-[#6e6e73]">{isCash ? emptyAccount ? 'Cash · 100% recorded' : paused ? hidden ? 'Hold available cash' : 'Cash held through FOMC' : 'Uninvested allocation' : <>{quote && Number.isFinite(quote.last) ? quote.last.toLocaleString('en-US', {style: 'currency', currency: 'USD'}) : 'Price unavailable'}{quote && Number.isFinite(quote.last) && <ChangeMark last={quote.last} close={closes?.[row.ticker]} />}{held ? ` · ${held.shares.toLocaleString()} held` : ''}</>}</div>
            </td>
            <td className="text-xs" aria-label={isCash ? undefined : `${row.ticker} grade`}>{isCash ? '' : <span title={grades[row.ticker] ? 'Intraday grade' : `Grade at the ${latest.session} close`} className={grades[row.ticker] ? 'font-medium text-[#1d1d1f]' : ''}>{row.grade}{grades[row.ticker] ? ' ·' : ''}</span>}</td>
            <td className="hidden text-xs tabular-nums sm:table-cell" aria-label={isCash ? undefined : `${row.ticker} opportunity`}>{isCash ? '' : row.opportunity !== null ? <>
              {row.opportunity.toFixed(1)}/10
              {!!row.narrow.length && <span
                className="ml-0.5 cursor-help font-medium text-[#9a6700]"
                title={`Scored without ${row.narrow.join(' and ')}: this name is missing the data ${row.narrow.length === 1 ? 'that analyst needs' : 'those analysts need'}, so the score is the rest renormalised. Open the name for the parts.`}
              >*</span>}
            </> : '—'}</td>
            <td className="text-xs">{isCash ? 'Hold'
              : trade?.(row.ticker) ?? (paused ? <span title={held ? exposure < 1 ? 'Held at reduced size through the decision; the rest restores at the next open' : 'Restoration queued for the next open' : 'No new buys during the FOMC cycle'}>{held ? 'Hold · FOMC' : 'Wait · FOMC'}</span>
              : action(row.ticker, row.weight))}</td>
            <td className="text-xs" aria-label={isCash ? undefined : `${row.ticker} size`}>{row.weight !== null ? percentage(row.weight)
              : isCash ? '—'
              : hidden ? <span title="The FOMC cycle's exposure is not current, so no size is shown">—</span>
              : <span className="cursor-help text-[#6e6e73]" title="Graded but unsized. Sizing ranks on the continuous score; the grade is a multiplier on top.">—</span>}</td>
            <td className="text-right">{!isCash && <button disabled={!onBuy || saving} aria-label={`Record purchase of ${row.ticker}`} className="text-xs text-[#0071e3] disabled:opacity-40 hover:underline" onClick={() => {setBuy(row.ticker);setShares('');setPrice('');setDate(today())}}>Record</button>}</td>
          </tr>
          {open && expand && <tr><td colSpan={7} className="border-t border-black/[0.05] bg-[#0071e3]/5 px-3 py-2">{expand(row.ticker)}</td></tr>}
          </Fragment>
        })}</tbody>
      </table>
      {footer}
      {searchText && filtered.length === 0 && (
        <p className="border-t border-black/[0.05] px-3 py-2 text-xs text-[#6e6e73]">No name matches “{query}”. Clear the search to see the ranked board.</p>
      )}
      {ranked.length > visible && (
        <button type="button" className="w-full border-t border-black/[0.05] px-3 py-2 text-left text-xs text-[#0071e3]" onClick={() => setVisible((v) => v + 10)}>
          Show more · {Math.min(ranked.length, visible + 10)} of {ranked.length} names
        </button>
      )}
    </div>
    <BoardSimulation paper={paper} now={now} />
    {holdings === null && <p role="alert" className="px-3 py-2 text-xs text-[#b42318]">{holdingsError ?? 'Positions unavailable. Recording is disabled.'}</p>}
    <MlComparison ml={ml} />
    {buy && <div role="dialog" aria-modal="true" aria-label={`Record ${buy} buy`} className="fixed inset-0 z-50 flex items-center justify-center bg-black/30 p-4">
      <form className="w-full max-w-sm space-y-3 rounded-2xl bg-white p-5 text-sm shadow-xl" onSubmit={async event => {
        event.preventDefault()
        if (saving || pending.current || !onBuy) return
        pending.current = true
        try {
          if (await onBuy(buy, Number(price), Number(shares), date)) setBuy(null)
        } finally { pending.current = false }
      }}>
        <h3 className="font-semibold">Record {buy} buy</h3>
        <p className="text-xs text-[#6e6e73]">Enter your confirmed brokerage fill. This tracks your position; it does not place an order.</p>
        <label className="block">Shares<input autoFocus aria-label="Filled shares" className="mt-1 block w-full rounded-lg border p-2" type="number" min="0.000001" step="any" required value={shares} onChange={event => setShares(event.target.value)} /></label>
        <label className="block">Fill price $<input aria-label="Average fill price" className="mt-1 block w-full rounded-lg border p-2" type="number" min="0.000001" step="any" required value={price} onChange={event => setPrice(event.target.value)} /></label>
        <label className="block">Date<input aria-label="Fill date" className="mt-1 block w-full rounded-lg border p-2" type="date" required max={today()} value={date} onChange={event => setDate(event.target.value)} /></label>
        {error && <p role="alert" className="text-xs text-[#b42318]">{error}</p>}
        <div className="flex justify-end gap-4"><button type="button" disabled={saving} onClick={() => setBuy(null)}>Cancel</button><button className="rounded-full bg-[#0071e3] px-4 py-2 text-white disabled:opacity-40" disabled={saving} type="submit">{saving ? 'Saving…' : 'Save position'}</button></div>
      </form>
    </div>}
  </section>
}
