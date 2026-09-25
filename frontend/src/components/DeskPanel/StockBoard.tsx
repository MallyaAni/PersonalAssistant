import { Fragment, useEffect, useRef, useState, type ReactNode } from 'react'
import type { DeskDecisions, DeskHolding, DeskLive, DeskLiveGrade, DeskPayload, DeskRecord, DeskPaperLive, DeskSessionPrices } from '../../services/api'
import { analystLabel } from './analystLabels'

// Scope known execution-clock reasons to the regular session without changing readiness.
export const executionClockMessage = (reason?: string | null) => {
  if (!['market closed or clock unavailable', 'market closed'].includes(reason?.toLowerCase() ?? '')) return null
  return {short: 'Regular-session execution blocked', full: 'Regular-session execution is blocked; the session is closed or its clock is unavailable'}
}

// Accept only the documented schedule vocabulary; a schedule is never proof of venue availability.
const quoteSchedule = (value: unknown): DeskSessionPrices['session'] | null =>
  typeof value === 'string' && ['pre-market', 'post-market', 'overnight', 'regular', 'closed', 'unknown'].includes(value)
    ? value as DeskSessionPrices['session'] : null

// Validate dated quote evidence independently of regular-session scheduling and execution policy.
const sessionPrice = (live: DeskLive, ticker: string, now: number) => {
  const envelope = live.extended_hours
  const quote = envelope?.quotes[ticker]
  const observed = Date.parse(quote?.at ?? '')
  const captured = Date.parse(envelope?.as_of ?? '')
  const until = Date.parse(quote?.valid_until ?? '')
  const dated = typeof quote?.feed === 'string' && quote.feed.trim().length > 0
    && Number.isFinite(observed) && observed <= captured && captured <= now
    && envelope?.signal_scope === 'regular-session'
  const priced = typeof quote?.price === 'number' && Number.isFinite(quote.price) && quote.price > 0
  const valid = dated && priced && quote?.status === 'fresh'
    && now - captured < 60_000 && now - observed < 60_000
    && Number.isFinite(until) && until > now
  const state = valid ? 'fresh' : dated && (quote?.status === 'stale' || priced && quote?.status === 'fresh'
    && (until <= now || now - observed >= 60_000 || now - captured >= 60_000)) ? 'stale' : 'unavailable'
  const envelopeSchedule = quoteSchedule(envelope?.session)
  const regularSchedule = live.market_status?.phase === 'open' ? 'regular' : quoteSchedule(live.market_status?.phase)
  const regularAt = Date.parse(live.market_status?.as_of ?? '')
  // XNYS pre/post phases include overnight; only its explicit open maps exactly to this finer schedule.
  const currentSchedule = regularSchedule === 'regular' && Number.isFinite(regularAt) && regularAt > captured && regularAt <= now
    ? 'regular' : envelopeSchedule ?? regularSchedule ?? 'unknown'
  // Legacy extension envelopes carried their observation phase; a legacy regular envelope did not.
  const observationSchedule = quoteSchedule(quote?.session)
    ?? (envelopeSchedule && ['pre-market', 'post-market', 'overnight'].includes(envelopeSchedule) ? envelopeSchedule : null)
  const namedSession = observationSchedule && !['closed', 'unknown'].includes(observationSchedule) ? observationSchedule : null
  return {quote, state, observed, session: namedSession, currentSchedule,
    previousSession: namedSession !== null && currentSchedule !== 'unknown' && namedSession !== currentSchedule,
    unrecordedSession: observationSchedule === null}
}

// Include the New York date when a time alone could be mistaken for today's observation.
const quoteTime = (observed: number, now: number): string | null => {
  if (!Number.isFinite(observed)) return null
  const observation = new Date(observed)
  const current = new Date(now)
  const sameDay = observation.toLocaleDateString('en-CA', {timeZone: 'America/New_York'})
    === current.toLocaleDateString('en-CA', {timeZone: 'America/New_York'})
  const sameYear = observation.toLocaleDateString('en-US', {timeZone: 'America/New_York', year: 'numeric'})
    === current.toLocaleDateString('en-US', {timeZone: 'America/New_York', year: 'numeric'})
  return observation.toLocaleString('en-US', {timeZone: 'America/New_York', hour: 'numeric', minute: '2-digit', second: '2-digit',
    ...(!sameDay ? {month: 'short', day: 'numeric', ...(!sameYear ? {year: 'numeric'} : {})} as const : {})})
}

// Explain current or missing display quotes plainly without changing execution or candle evidence.
export const SessionPrice = ({live, ticker, now, compact = false, close}: {live: DeskLive; ticker: string; now: number; compact?: boolean; close?: number | null}) => {
  const {quote, state, observed, session, currentSchedule, previousSession, unrecordedSession} = sessionPrice(live, ticker, now)
  const regular = live.quotes[ticker]
  const at = quoteTime(observed, now)
  const source = `${quote?.indicative ? 'Indicative · ' : ''}${quote?.feed?.toUpperCase() || 'Source unavailable'}`
  const regularText = regular && Number.isFinite(regular.last) ? `Regular-session bar $${regular.last.toFixed(2)} · ${regular.bar}` : 'Regular-session bar unavailable'
  const qualification = previousSession ? ' · previous-session observation' : unrecordedSession ? ' · session unrecorded' : ''
  const displayReason = quote?.status === 'unavailable' && quote.reason
    ? quote.reason === 'No fresh quote from available feeds' ? 'No usable bid/ask midpoint was returned for this display.' : `Price-data detail: ${quote.reason}` : null
  return <div aria-label={`${ticker} session price`} title={`${regularText}. Signal: regular session. Midpoint is not a trade or guaranteed fill. Reported quote timestamp: ${quote?.at ?? 'unavailable'}. Expected schedule: ${currentSchedule}; not proof of venue availability. For display only; execution checks are separate.${displayReason ? ` ${displayReason}` : ''}`}>
    {state === 'fresh' ? <><span className="font-medium">${quote!.price!.toFixed(2)}</span><span className="ml-1">{session ?? 'Quote'} · {source} · {at} ET{qualification}</span></>
      : <><span className="text-[#9a6700]">{state === 'stale' ? `No recent quote to display${at ? ` · Last quote: ${at} ET` : ''}${session ? ` · ${session}` : ''} · ${source}${qualification}` : 'No recent quote to display'}</span>
        {compact && <div>{regular && Number.isFinite(regular.last) ? <>Regular bar ${regular.last.toFixed(2)}<ChangeMark last={regular.last} close={close} /></> : 'Regular bar unavailable'}</div>}</>}
    {!compact && <p className="text-[11px] text-[#6e6e73]">Price signals use regular-session candles.</p>}
  </div>
}

// The three things the desk can be doing about a name. Declared here because
// this is the board that lists them and DeskPanel already imports from it; the
// other direction would be a cycle.
export const PLAN_ACTIONS = ['Buy', 'Sell', 'Hold'] as const
export type PlanAction = (typeof PLAN_ACTIONS)[number]

const ORDER: Record<string, number> = {'A+': 3, A: 2, B: 1, C: 0}
type SortColumn = 'ticker' | 'grade' | 'opportunity' | 'plan' | 'weight' | 'size'
// The natural first direction for each column: a name list reads A to Z, a
// measure reads biggest first.
const DESCENDING_FIRST: Record<SortColumn, boolean> = {ticker: false, grade: true, opportunity: true, plan: false, weight: true, size: true}

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
      <summary className="cursor-pointer">ML paper comparison · {ml.session ?? 'awaiting first close'} · input validation incomplete</summary>
      <p className="my-2 text-[#9a6700]">Input validation incomplete: known financial/share-unit issues. These frozen accounts do not establish superiority over the live strategy.</p>
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
        aria-label={filtered ? 'Filter strategy intent (filtered)' : 'Filter strategy intent'}
        title="Show only selected strategy intents; a blocked intent is not an executable order"
        className={`flex items-center gap-1 rounded font-normal hover:text-[#0071e3] ${filtered ? 'text-[#0071e3]' : ''}`}
        onClick={() => setOpen(!open)}
      >
        Action
        <span aria-hidden="true" className={filtered ? 'text-[#0071e3]' : 'text-[#c7c7cc]'}>{'▾'}</span>
      </button>
      <button
        type="button"
        title="Sort the board by strategy intent"
        aria-label="Sort by strategy intent"
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
export const StockBoard = ({latest, live, grades, research, paper, ml, coverage, decisions, holdings, broker, event, now, onOpen, holdingsError, expand, toolbar, trade, footer, closes, planAction, extraNames = []}: {
  latest: DeskRecord; live: DeskLive; grades: Record<string, DeskLiveGrade>;
  research: DeskPayload['intraday_research']; holdings: DeskHolding[] | null;
  broker?: DeskPaperLive | null;
  paper?: DeskPayload['board_paper'];
  ml?: DeskPayload['ml_forward'];
  decisions?: DeskDecisions;
  coverage?: DeskPayload['coverage'];
  event: BoardEvent | null; now: number;
  onOpen: (ticker: string) => void;
  holdingsError?: string;
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
  // Sizes are 15-minute research allocations. They are current only while the
  // backend says the collection succeeded for this decision and its evidence
  // deadline has not passed. A failed collection may deliberately preserve an
  // older target for audit; it must not be relabelled as this bar's output.
  const marketClosed = live.market_status?.open !== true
  // Which sizing policy the board is showing. It used to be inferred: live
  // sizes when a current bar existed, plan targets otherwise, with no way to
  // ask for the other one. A trader comparing "what the rebalance will do"
  // against "what this bar says" had to read two different places, so it is
  // a control now, and picking one re-sizes and re-ranks the list in place.
  const researchDeadline = Date.parse(research?.valid_until ?? '')
  const liveSizingReady = research?.status === 'available'
    && research.session === latest.session
    && !!research.targets
    && Number.isFinite(researchDeadline)
    && researchDeadline > now
  // Live sizes when a current bar exists is the default: it is the answer to
  // "what this bar says", which is what a trader scanning the board wants
  // first, and the plan is one click away. e1f2a87 flipped this to 'plan' and
  // every test written to the original 'live' default started failing.
  const [policy, setPolicy] = useState<'live' | 'plan'>('live')
  const showSizes = liveSizingReady && policy === 'live'
  // The adopted book omits covered names with zero weight; match the account planner.
  const planTargets = Array.isArray(latest.book) ? {
    ...Object.fromEntries(Object.keys(latest.grades).map(ticker => [ticker, 0])),
    ...Object.fromEntries(latest.book.map(b => [b.ticker, b.weight])),
  } : {}
  const weightOf = (ticker: string) => {
    if (hidden) return null
    const weights = showSizes ? (research!.targets ?? {}) : planTargets
    if (showSizes && !marketClosed && research!.bar !== live.quotes[ticker]?.bar) return null
    const weight = weights[ticker]
    return Number.isFinite(weight) && (weight as number) >= 0 ? (weight as number) * exposure : null
  }
  const graded = Object.keys(latest.grades)
  const freshGradeCount = graded.filter(ticker => grades[ticker] !== undefined).length
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
  const sizingLine = !showSizes
    ? research?.status && research.status !== 'available'
      ? `Strategy reset targets · current-bar research unavailable${research.reason ? `: ${research.reason}` : ''}`
      : research?.status === 'available' && research.session !== latest.session
        ? `Strategy reset targets · research allocation belongs to ${research.session ?? 'another decision'}, not this decision`
        : research?.status === 'available' && Number.isFinite(researchDeadline) && researchDeadline <= now
          ? 'Strategy reset targets · research allocation expired; refresh for a current bar'
          : 'Strategy reset targets'
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
  const brokerCurrent = broker !== null && broker !== undefined && broker.reason === undefined
  const paperAvailable = brokerCurrent ? Array.isArray(broker.positions) : Array.isArray(latest.paper?.positions)
  const brokerPositions = brokerCurrent ? broker.positions ?? [] : latest.paper?.positions ?? []
  const otherNames = [...new Set([...extraNames, ...Object.keys(decisions?.rows ?? {}),
    ...Object.keys(planTargets), ...(holdings ?? []).map(h => h.ticker), ...brokerPositions.map(p => p.symbol)])]
  // Rank the same strategy action that the row displays, including an event pause.
  const planOf = (ticker: string): PlanAction => {
    if (paused) return 'Hold'
    const said = planAction?.(ticker)
    return PLAN_ACTIONS.includes(said as PlanAction) ? (said as PlanAction) : 'Hold'
  }
  // Rank only the executable addition or reduction displayed in the Size column.
  const executableSize = (ticker: string): number | null => {
    const row = decisions?.session === latest.session && decisions.written === latest.written
      ? decisions.rows[ticker] : undefined
    return !paused && !marketClosed && row?.executable === true && row.action !== 'Hold'
      && Date.parse(row.valid_until ?? '') > now && Number.isFinite(row.move_weight)
      ? Math.abs(row.move_weight) : null
  }
  const stocks = [...Object.entries(latest.grades).map(([ticker, grade]) => ({
    ticker, grade: grades[ticker]?.grade_live ?? grade.grade,
    score: grades[ticker]?.score_live ?? grade.score,
    opportunity: opportunity(ticker),
    narrow: narrow(ticker),
    weight: weightOf(ticker),
  })), ...otherNames.filter(ticker => !(ticker in latest.grades)).map(ticker => ({ticker, grade: '', score: -Infinity, opportunity: null, narrow: [] as string[], weight: null}))].sort((a, b) =>
    // Visible ranking: grade, Buy/Sell/Hold, executable size, then the grade score.
    // Reset targets and research allocations are not current trade sizes.
    (ORDER[b.grade] ?? -1) - (ORDER[a.grade] ?? -1)
    || PLAN_ACTIONS.indexOf(planOf(a.ticker)) - PLAN_ACTIONS.indexOf(planOf(b.ticker))
    || (executableSize(b.ticker) ?? -1) - (executableSize(a.ticker) ?? -1)
    || b.score - a.score || a.ticker.localeCompare(b.ticker))
  const heldNames = new Set((holdings ?? []).map((h) => h.ticker))
  const planGross = !showSizes && !hidden
    // `* exposure` to match weightOf: every row is scaled by it, so the cash
    // remainder must be too or the column does not sum to the account during
    // an FOMC cycle.
    ? Object.values(planTargets).reduce((sum, w) => sum + (Number.isFinite(w) ? (w as number) : 0), 0) * exposure
    : null
  // What the desk leaves uninvested, which is one minus what it has sized.
  //
  // This used to fall back to 100% when the operator had recorded no holdings
  // of his own, and print "Cash - 100% recorded" beside it. Both were reading
  // his bookkeeping: an empty holdings file is not a statement that the desk
  // is in cash. Nothing else on this board reads that file any more, and the
  // cash row is part of the same book as the rows above it.
  const cash = {ticker: '__cash__', grade: '', score: 0, opportunity: null, narrow: [] as string[], weight: sized ? Math.max(0, 1 - gross!) : planGross !== null ? Math.max(0, 1 - planGross) : null}
  const cashIndex = paused ? 0 : stocks.length
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
  const plans = PLAN_ACTIONS.map(name => ({
    name,
    count: stocks.filter(s => s.ticker !== '__cash__' && planOf(s.ticker) === name).length,
  }))
  const everyPlan = PLAN_ACTIONS.every(name => shownPlans[name])
  // Cash is not one of the three plans, so a board narrowed to a plan drops
  // it rather than pinning it to a list it is not part of. It was exempted to
  // keep it from vanishing; vanishing is the correct behaviour when the
  // question is "what is the desk trading".
  const byPlan = everyPlan ? stocks : stocks.filter(s => s.ticker !== '__cash__' && shownPlans[planOf(s.ticker)])
  const filtered = searchText ? byPlan.filter((s) => s.ticker.toLowerCase().includes(searchText)) : byPlan
  // A chosen column replaces the desk's ranking; a name the column cannot
  // measure sorts to the bottom either way, so a dash never leads the board.
  const sorted = !sort ? filtered : [...filtered].sort((a, b) => {
    const missing = (row: typeof a) =>
      sort.column === 'opportunity' ? row.opportunity === null
      : sort.column === 'size' ? executableSize(row.ticker) === null
      : sort.column === 'weight' ? row.weight === null
      : sort.column === 'grade' ? !row.grade
      : false
    if (missing(a) !== missing(b)) return missing(a) ? 1 : -1
    const of = (row: typeof a) =>
      sort.column === 'ticker' ? row.ticker
      : sort.column === 'size' ? (executableSize(row.ticker) ?? -Infinity)
      : sort.column === 'grade' ? (ORDER[row.grade] ?? -1)
      : sort.column === 'opportunity' ? (row.opportunity ?? -Infinity)
      : sort.column === 'plan' ? PLAN_ACTIONS.indexOf(planOf(row.ticker))
      : (row.weight ?? -Infinity)
    const left = of(a), right = of(b)
    const order = typeof left === 'string' && typeof right === 'string'
      ? left.localeCompare(right as string)
      : (left as number) - (right as number)
    return sort.descending ? -order : order
  })
  const ranked = [...sorted]
  if (!searchText && !sort) ranked.splice(cashIndex < 0 ? ranked.length : Math.min(cashIndex, ranked.length), 0, cash)
  const bar = showSizes && !marketClosed ? research!.bar : live.data_at
  const time = bar ? new Date(bar).toLocaleString('en-US', {timeZone: 'America/New_York', month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit'}) : null
  return <section aria-label="Stocks and cash" className="flex min-h-0 flex-1 flex-col overflow-hidden rounded-2xl border border-black/[0.08] bg-white [container-type:inline-size]">
    <div className="shrink-0 border-b border-black/[0.06] px-3 py-2 text-xs text-[#6e6e73]">
      <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
        <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
          <h3 className="text-sm font-semibold text-[#1d1d1f]">Stock rankings</h3>
          {!sort ? <span title="Grades highest first; then Buy, Sell, Hold; then executable size. Ties use grade score, then ticker.">Grade ↓ · Action · Size ↓</span>
            : <button type="button" className="text-[#0071e3] hover:underline" onClick={() => setSort(null)}>Reset ranking</button>}
          {fomcLine && <p>{fomcLine}</p>}
        </div>
      </div>
      <p className="mt-0.5" title="Fundamental analysis is nightly. Regular-session signals use completed 15-minute bars. While open, the dashboard checks for display-only session quotes every minute; browser refresh and provider collection have separate schedules. A refresh does not guarantee a new or fresh quote.">{time ? `Regular-session bar ${time} ET` : 'Regular-session bar unavailable'} · completed 15-minute bars; dashboard checks for session quotes every minute{live.stale ? ' · regular bar stale' : ''}</p>
      <details className="mt-1"><summary className="cursor-pointer">Data & sizing details</summary>
        {liveSizingReady && !hidden && (
          <div className="flex shrink-0 gap-1" role="group" aria-label="Sizing policy">
            {([['live', 'Research · this bar'], ['plan', 'Strategy · reset targets']] as const).map(([value, label]) => (
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
        <p>{sizingLine}</p>
        <p aria-label="Intraday grade coverage">{freshGradeCount}/{graded.length} fresh intraday grades{freshGradeCount < graded.length ? ` · other grades: ${latest.session} close` : ''}. Grades are not entry signals.</p>
        {coverage && <p>{coverage.graded} graded · {coverage.tracked} tracked</p>}
        <p>Action is the strategy recommendation. Blocked recommendations have no trade size. Size is a change in your account allocation, not a profit target.</p>
      </details>
    </div>
    {toolbar}
    <div className="min-h-0 flex-1 overflow-auto">
      <table className="w-full min-w-max text-left text-sm tabular-nums [&_td]:px-2 [&_th]:px-2" aria-label="Ranked stocks and cash">
        <thead className="sticky top-0 z-10 bg-[#f5f5f7] text-xs text-[#6e6e73]">
          <tr className="border-b border-black/[0.06]">
            <th colSpan={5} className="py-2 pr-3 font-normal">
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
            <SortHead column="grade" sort={sort ?? {column: 'grade', descending: true}} onSort={setSort} title="Latest valid grade; expired intraday readings revert to the dated close.">Grade</SortHead>
            {planAction
              ? <PlanHead sort={sort} onSort={setSort} plans={plans} shown={shownPlans} onShown={(next) => { setShownPlans(next); setVisible(10) }} />
              : <SortHead column="plan" sort={sort} onSort={setSort} title="The adopted strategy's recommendation; a blocked recommendation is not executable">Action</SortHead>}
            <SortHead column="size" sort={sort} onSort={setSort} title="Executable change as a percentage of your account; not a profit target.">Size</SortHead>

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
          const decision = decisions?.session === latest.session && decisions.written === latest.written ? decisions.rows[row.ticker] : undefined
          const strategyMove = decision?.strategy_move_weight ?? decision?.move_weight
          const deadline = Date.parse(decision?.valid_until ?? '')
          const canSize = executableSize(row.ticker) !== null
          const plan = paused ? 'Hold' : planOf(row.ticker)
          const readiness = paused ? 'FOMC pause' : plan === 'Hold' ? decision?.entry_status === 'unavailable' ? 'Data missing' : null : decision?.executable === false
            ? decision.blocker || (marketClosed ? 'Market closed' : 'Blocked now')
            : marketClosed ? 'Market closed'
            : !Number.isFinite(deadline) || deadline <= now ? 'Price check needed' : null
          const clockRestriction = executionClockMessage(readiness)
          const position = brokerPositions.find(p => p.symbol === row.ticker)
          const reason = paused ? 'FOMC cycle: regular trading paused'
            : !(row.ticker in latest.grades) ? 'Outside current coverage; review manually'
            : plan === 'Hold' && decision?.entry_status === 'unavailable' ? decision.entry_reason || 'Entry data unavailable'
            : decision?.reason || decision?.blocker || 'No current strategy decision'
          // The plan cell is the full trade affordance (eligibility, record
          // fill) when the read answers for this name; a name the plan feed
          // did not answer keeps the bare action word as before.
          const tradeNode = trade ? trade(row.ticker) : null
          return <Fragment key={row.ticker}><tr className={`border-t border-black/[0.05] ${isCash ? 'bg-[#0071e3]/10' : ''}`}>
            <td className="w-7 text-xs text-[#6e6e73]">{isCash || !expand ? index + 1 : <button type="button" aria-label={`details for ${row.ticker}`} aria-expanded={open} className="w-5 text-[#0071e3]" onClick={() => setOpened(open ? null : row.ticker)}>{open ? '▾' : '▸'}</button>}</td>
            <td className="py-2">
              {isCash ? <span className="font-semibold">USD</span> : <button className="font-semibold hover:text-[#0071e3]" onClick={() => onOpen(row.ticker)}>{row.ticker}</button>}
              <div className="text-[11px] text-[#6e6e73]">{isCash ? paused ? hidden ? 'Hold available cash' : 'Cash held through FOMC' : 'Uninvested allocation' : <><SessionPrice live={live} ticker={row.ticker} now={now} compact close={closes?.[row.ticker]} />{held ? ` · ${held.shares.toLocaleString()} held` : ''}</>}</div>
            </td>
            <td className="text-xs" aria-label={`${row.ticker} displayed grade`} title={isCash ? undefined : grades[row.ticker] ? 'Current intraday grade' : `Recorded grade at the ${latest.session} close`}>
              {!isCash && <><span className={`font-semibold ${row.grade === 'A+' || row.grade === 'A' ? 'text-[#1e7a3a]' : row.grade === 'C' ? 'text-[#b42318]' : 'text-[#6e6e73]'}`}>{row.grade || '—'}</span>
                <div className="text-[10px] text-[#6e6e73]">{row.grade ? grades[row.ticker] ? 'Intraday' : 'Close' : 'Unrated'}</div></>}
            </td>
            <td className="text-xs"><span aria-label={isCash ? undefined : `${row.ticker} strategy intent`} className={`font-medium ${plan === 'Buy' ? 'text-[#1e7a3a]' : plan === 'Sell' ? 'text-[#b42318]' : 'text-[#6e6e73]'}`}>{isCash ? 'HOLD' : plan === 'Hold' ? 'Hold' : plan.toUpperCase()}</span>
              {readiness && <div aria-label={`${row.ticker} execution readiness`} title={clockRestriction?.full ?? readiness} className="text-[11px] text-[#9a6700]">{clockRestriction?.short ?? readiness}</div>}
              {!isCash && (decision?.quote?.spread_verified === false || decision?.quote?.eligible && decision.quote.spread_verified !== true) &&
                <div aria-label={`${row.ticker} spread verification`} className="text-[11px] text-[#9a6700]">{decision.quote.spread_verified === false
                  ? `${decision.quote.feed?.toUpperCase() ?? 'Quote'} spread unverified`
                  : 'Spread verification unrecorded'}</div>}</td>
            <td className="text-xs" aria-label={`${row.ticker} size`}>{isCash && row.weight !== null ? `${percentage(row.weight)} unallocated` : !isCash && canSize ? <>{percentage(Math.abs(decision!.move_weight))}<span className="hidden sm:inline"> of account</span></> : '—'}</td>

          </tr>
          {/* Details follow the visible board width, not the horizontally scrollable table. */}
          {open && expand && <tr><td colSpan={5} className="border-t border-black/[0.05] bg-[#0071e3]/5 px-3 py-2"><div className="w-[calc(100cqw-1.5rem)]">
            <p aria-label={`${row.ticker} decision reason`} className="mb-2 text-xs">{reason}</p>
            <dl aria-label={`${row.ticker} allocation and evidence`} className="mb-3 grid gap-x-6 gap-y-2 text-xs sm:grid-cols-2">
              <div><dt className="text-[#6e6e73]">Regular-session signal price</dt><dd>{quote && Number.isFinite(quote.last) ? `$${quote.last.toFixed(2)} · ${quote.bar}` : 'Unavailable'}</dd></div>
              <div><dt className="text-[#6e6e73]">Combined grade · not an entry signal</dt><dd aria-label={`${row.ticker} grade`}>{row.grade || 'Unavailable'} · {grades[row.ticker] ? 'intraday' : `${latest.session} close`}</dd></div>
              <div><dt className="text-[#6e6e73]">Analyst conviction · not a return forecast</dt><dd aria-label={`${row.ticker} opportunity`}>{row.opportunity !== null ? `${row.opportunity.toFixed(1)}/10` : 'Unavailable'}{row.narrow.length > 0 && ` · missing ${row.narrow.map(analystLabel).join(', ')}`}</dd></div>
              <div><dt className="text-[#6e6e73]">{showSizes ? 'Experimental research allocation' : 'Strategy target at reset'}</dt><dd aria-label={`${row.ticker} target allocation`}>{row.weight !== null ? percentage(row.weight) : 'Unavailable'}</dd></div>
              <div><dt className="text-[#6e6e73]">Intended allocation change · before readiness checks</dt><dd aria-label={`${row.ticker} move`}>{plan === 'Hold' || strategyMove === undefined ? '—' : `${strategyMove > 0 ? '+' : ''}${percentage(strategyMove)}`}</dd></div>
              <div><dt className="text-[#6e6e73]">Recorded personal position</dt><dd aria-label={`${row.ticker} recorded personal position`}>{holdings === null ? 'Unavailable' : held ? <>{held.shares.toLocaleString()} shares · entry ${held.entry_price.toFixed(2)}{quote && Number.isFinite(quote.last) && <div>P/L {((quote.last - held.entry_price) * held.shares).toLocaleString('en-US', {style: 'currency', currency: 'USD'})}</div>}</> : 'None recorded'}</dd></div>
              <div><dt className="text-[#6e6e73]">Separate paper position · {brokerCurrent ? 'broker snapshot' : latest.paper ? `saved ${latest.paper.session}` : broker == null ? 'loading' : 'unavailable'}</dt><dd aria-label={`${row.ticker} paper position`}>{!paperAvailable ? 'Unavailable' : position ? <>{position.qty.toLocaleString()} shares<div>{Number.isFinite(position.unrealized_pl) ? `P/L ${position.unrealized_pl.toLocaleString('en-US', {style: 'currency', currency: 'USD'})}` : 'P/L unavailable'}</div></> : 'None'}</dd></div>
            </dl>
            {decision?.risk_plan && <div aria-label={`${row.ticker} risk and reward`} className="mb-3 rounded border border-black/[0.08] p-2 text-xs">
              <p className="font-medium">Risk / reward scenario</p>
              <p>{decision.risk_plan.reason}</p>
              {decision.risk_plan.entry !== null && <p>Entry reference ${decision.risk_plan.entry.toFixed(2)}
                {decision.risk_plan.reference_support !== null && ` · support $${decision.risk_plan.reference_support.toFixed(2)}`}
                {decision.risk_plan.reference_resistance !== null && ` · resistance $${decision.risk_plan.reference_resistance.toFixed(2)}`}</p>}
              {decision.risk_plan.reward_risk_ratio !== null && <p>Potential reward / risk {decision.risk_plan.reward_risk_ratio.toFixed(2)}:1</p>}
              {decision.risk_plan.risk_budget_pct !== null && <p>Risk budget {decision.risk_plan.risk_budget_pct}% of account
                {decision.risk_plan.max_add_weight !== null && ` · allocation cap ${percentage(decision.risk_plan.max_add_weight)}`}</p>}
              <p className="text-[#6e6e73]">Reference levels are scenarios, not forecasts or guaranteed stops. Gaps can exceed the risk budget. {decision.risk_plan.basis}</p>
            </div>}
            {expand(row.ticker)}
            {tradeNode && <details className="mt-2 text-xs"><summary className="cursor-pointer">Confirmed fill controls</summary>{tradeNode}</details>}
          </div></td></tr>}
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
  </section>
}
