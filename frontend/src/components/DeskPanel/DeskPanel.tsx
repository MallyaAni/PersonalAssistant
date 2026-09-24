import { useEffect, useRef, useState, type ReactNode } from 'react'
import { RefreshCw, X } from 'lucide-react'
import { EconomicContext } from './EconomicContext'
import { ForwardEvidence } from './ForwardEvidence'
import { FomcGate } from './FomcGate'
import { ExecutionQuality } from './ExecutionQuality'
import { BoardSimulation, MlComparison, PLAN_ACTIONS, StockBoard, type BoardEvent, type PlanAction } from './StockBoard'
import { RecommendationTimeline } from './RecommendationTimeline'
import { PersonalDecisionHistory, type PersonalHistoryContext } from './PersonalDecisionHistory'
import { TickerChart } from './TickerChart'
import { StrategyBench } from './StrategyBench'
import { NeuralStudy } from './NeuralStudy'
import { OpportunityCard } from './OpportunityCard'
import { ANALYST_MEANINGS, EVENING_VOTE_CONTEXT, analystLabel } from './analystLabels'
import {
  getDesk,
  getDeskEarnings,
  getDeskHistory,
  getDeskHoldings,
  getDeskIntraday,
  getDeskLive,
  getDeskLiveRead,
  getDeskMine,
  getDeskPaper,
  getTradingAutopsy,
  putDeskHoldings,
  type DeskCurve,
  type DeskDecisions,
  type DeskBrief,
  type DeskEarnings,
  type DeskGrade,
  type DeskHolding,
  type DeskHistory,
  type DeskHistoryRow,
  type DeskIntraday,
  type DeskLive,
  type DeskLiveRead,
  type DeskLiveGrade,
  type DeskMineRow,
  type DeskPaperLive,
  type DeskPayload,
  type DeskQuote,
  type DeskRecord,
  type TradingAutopsy,
} from '../../services/api'

interface DeskPanelProps {
  userId: string
  // Whether this identity may write the desk - the primary operator alone.
  // A named extra account reads the shared book and never edits it.
  canWrite: boolean
}

// The page asks for a fresh record every few minutes: the desk writes one
// a session, so that is plenty. Prices follow the fifteen-minute candle.
const REFRESH_MS = 60 * 1000
const CANDLE_MS = 15 * 60 * 1000
const POLL_MS = 60 * 1000

// Revert an expired intraday opinion to the recorded evening evidence.
const eveningRow = (row: DeskMineRow): DeskMineRow => ({
  ...row, grade_live: row.grade, grade_source: 'evening', stances_live: row.stances,
  ranks_live: row.ranks, score_live: null, grade_margin_live: null,
  technical_now: null, technical_close: null, value_now: null, value_close: null,
})

// Show the date and exchange timezone so an old candle cannot look current.
const marketTime = (value: string | null | undefined) => {
  if (!value || Number.isNaN(Date.parse(value))) return 'unknown time'
  return `${new Date(value).toLocaleString('en-US', {
    timeZone: 'America/New_York', month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit',
  })} ET`
}

// Turn the backend-authored XNYS phase and schedule into one precise label;
// this never infers holidays or trading hours in the browser.
const exchangeState = (status: DeskLive['market_status']) => {
  if (!status || status.phase === 'unknown') return {open: false, known: false, label: 'XNYS schedule unavailable · execution status unknown'}
  // Format only the reviewed schedule timestamps supplied by the backend.
  const time = (value: string | null) => value && !Number.isNaN(Date.parse(value))
    ? `${new Date(value).toLocaleTimeString('en-US', {timeZone: 'America/New_York', hour: 'numeric', minute: '2-digit'})} ET`
    : null
  const opens = time(status.opens_at)
  const closes = time(status.closes_at)
  if (status.open) return {open: true, known: true, label: `XNYS regular session scheduled open${closes ? ` · scheduled close ${closes}` : ''}`}
  if (!status.is_session) return {open: false, known: true, label: 'XNYS closed by schedule · no regular session today'}
  if (status.phase === 'pre-market') return {open: false, known: true, label: `Before XNYS regular session${opens ? ` · scheduled open ${opens}` : ''}`}
  return {open: false, known: true, label: `XNYS regular session closed${closes ? ` · scheduled close ${closes}` : ''}`}
}

// Keep seconds visible when comparing decision, broker submission and completion times.
const executionTime = (value: string | undefined) => {
  if (!value || Number.isNaN(Date.parse(value))) return 'not recorded'
  return `${new Date(value).toLocaleString('en-US', {
    timeZone: 'America/New_York', year: 'numeric', month: 'short', day: 'numeric',
    hour: '2-digit', minute: '2-digit', second: '2-digit',
  })} ET`
}

const GRADE_ORDER: Record<string, number> = { 'A+': 3, A: 2, B: 1, C: 0 }
const GRADE_STYLE: Record<string, string> = {
  'A+': 'bg-[#e6f4ea] text-[#1e7a3a]',
  A: 'bg-[#eaf3ff] text-[#0b5cad]',
  B: 'bg-[#fff6e5] text-[#9a6200]',
  C: 'bg-[#f5f5f7] text-[#6e6e73]',
}
const ACTION_STYLE: Record<string, string> = {
  buy: 'bg-[#e6f4ea] text-[#1e7a3a]',
  add: 'bg-[#e6f4ea] text-[#1e7a3a]',
  trim: 'bg-[#fff6e5] text-[#9a6200]',
  sell: 'bg-[#fdecea] text-[#b42318]',
  hold: 'bg-[#f5f5f7] text-[#6e6e73]',
  uncovered: 'bg-[#eef1f6] text-[#3a3a3c]',
  blocked: 'bg-[#f5f5f7] text-[#6e6e73]',
}
const STANCE_MARK: Record<number, string> = { 1: '+', 0: '·', [-1]: '−' }
const TRIGGER_ORDER: [string, string][] = [
  ['fundamental', 'F'],
  ['technical', 'T'],
  ['sentiment', 'S'],
  ['value', 'V'],
  ['rotation', 'R'],
]
const TRIGGER_LEGEND =
  `${ANALYST_MEANINGS} + for, · neutral or unavailable, − against.`

// The desk's warnings in plain words. A flag not listed shows as written.
const FLAG_WORDS: Record<string, string> = {
  'not enough history to judge participation': 'too little history to compare AI trading activity with its past',
  'participation below its two-year median': 'AI trading activity is below its historical median',
  'participation in its top quintile (hype)': 'AI trading activity is in the highest fifth of its historical readings',
  'AI-vs-software co-movement far from its history': 'AI and software stocks are moving together unusually, so the usual patterns may not hold',
  'theme co-movement structure has changed shape': 'the way these stocks move together has changed, so the desk trusts its picks less',
  'AI basket more than 25% off its yearly high': 'the AI basket has a large decline from its trailing high',
  'the ten-year yield is rising sharply': 'interest rates are rising fast, which usually hurts these stocks',
}

// Per-browser convenience: the account size typed in.
const EQUITY_KEY = 'desk.equity'
const readStored = (key: string): string | null => {
  try {
    return window.localStorage.getItem(key)
  } catch {
    return null
  }
}
const pct = (value: number) => `${(value * 100).toFixed(1)}%`
const signed = (value: number) => `${value >= 0 ? '+' : ''}${(value * 100).toFixed(1)}%`
const money = (value: number) =>
  value.toLocaleString(undefined, { style: 'currency', currency: 'USD', maximumFractionDigits: 0 })
// Preserve cents in per-share prices while account totals remain rounded for scanning.
const priceMoney = (value: number) =>
  value.toLocaleString('en-US', { style: 'currency', currency: 'USD', minimumFractionDigits: 2, maximumFractionDigits: 2 })
// A dollar P/L with the sign, the direction and the currency, so a live
// figure reads as money rather than as a bare number.
const signedMoney = (value: number) =>
  `${value >= 0 ? '+' : '−'}${money(Math.abs(value))}`
const sizing = (r: DeskMineRow, quote: DeskQuote | undefined, equity: number) => {
  const price = quote?.last ?? r.last ?? r.last_close ?? 0
  const qty = price > 0 ? Math.round((Math.abs(r.delta_weight) * equity) / price) : 0
  return { price, qty }
}
// Default a recorded fill to the exchange's calendar date, including after UTC midnight.
const today = () => new Intl.DateTimeFormat('en-CA', {
  timeZone: 'America/New_York', year: 'numeric', month: '2-digit', day: '2-digit',
}).format(new Date())

// A signed value in green or red with an arrow, so the direction reads
// without color (a colour-blind reader sees the arrow, not the shade).
// A flat zero keeps a neutral mark instead of an arrow: zero is not an up move.
const Trend = ({ value, suffix = '%' }: { value: number; suffix?: string }) => {
  const up = value > 0
  const down = value < 0
  if (!up && !down) {
    return <span className="text-[#6e6e73]" aria-label={`flat ${value.toFixed(1)}${suffix}`}><span aria-hidden="true">·</span> {value.toFixed(1)}{suffix}</span>
  }
  return (
    <span className={up ? 'text-[#1e7a3a]' : 'text-[#b42318]'} aria-label={`${up ? 'up' : 'down'} ${value.toFixed(1)}${suffix}`}>
      <span aria-hidden="true">{up ? '↑' : '↓'}</span> {up ? '+' : ''}
      {value.toFixed(1)}
      {suffix}
    </span>
  )
}

// A dollar P/L in green or red with an arrow and a currency sign, so the
// direction reads without colour and the figure reads as money. Flat at zero.
const TrendUsd = ({ value }: { value: number }) => {
  const up = value > 0
  const down = value < 0
  if (!up && !down) {
    return <span className="text-[#6e6e73]" aria-label={`flat ${money(Math.abs(value))}`}><span aria-hidden="true">·</span> {money(Math.abs(value))}</span>
  }
  return (
    <span className={up ? 'text-[#1e7a3a]' : 'text-[#b42318]'} aria-label={`${up ? 'up' : 'down'} ${signedMoney(value)}`}>
      <span aria-hidden="true">{up ? '↑' : '↓'}</span> {signedMoney(value)}
    </span>
  )
}

const shortDate = (iso: string) => {
  const date = new Date(`${iso}T00:00:00`)
  const thisYear = date.getFullYear() === new Date().getFullYear()
  return date.toLocaleDateString(undefined, thisYear ? { month: 'short', day: 'numeric' } : { month: 'short', day: 'numeric', year: 'numeric' })
}

// Apply only the actual shares and average fill price confirmed from the broker.
const afterTrade = (holdings: DeskHolding[], r: Pick<DeskMineRow, 'ticker' | 'action'>, price: number, qty: number, fillDate = today()): DeskHolding[] => {
  if (!Number.isFinite(price) || price <= 0 || !Number.isFinite(qty) || qty <= 0) {
    throw new Error('Enter positive filled shares and average fill price.')
  }
  const rest = holdings.filter((h) => h.ticker !== r.ticker)
  const mine = holdings.find((h) => h.ticker === r.ticker)
  if (r.action === 'sell' || r.action === 'trim') {
    if (!mine || qty > mine.shares) throw new Error('Filled shares exceed the recorded position. Reconcile your positions first.')
    if (mine.shares === qty) return rest
    return [...rest, { ...mine, shares: mine.shares - qty }]
  }
  if (mine) {
    const shares = mine.shares + qty
    const entry = (mine.shares * mine.entry_price + qty * price) / shares
    return [...rest, { ...mine, shares, entry_price: entry, last_buy_date: fillDate }]
  }
  return [...rest, { ticker: r.ticker, shares: qty, entry_price: price, entry_date: fillDate, last_buy_date: fillDate }]
}

// Show each valid percentile beside its separate vote; missing or invalid parts remain unknown.
const ratings = (ranks: Record<string, number> | undefined, stances: Record<string, number>) =>
  TRIGGER_ORDER.filter(([k]) => (ranks && k in ranks) || k in stances)
    .map(([k, letter]) => {
      const rank = ranks?.[k]
      const number = typeof rank === 'number' && Number.isFinite(rank) && rank >= 0 && rank <= 1 ? Math.round(rank * 100) : ''
      return `${letter}${number}${k in stances ? STANCE_MARK[stances[k]] ?? '?' : '?'}`
    })
    .join(' ')

// Explain the percentile/vote shorthand without presenting the parts as individual letter grades.
const AnalystRatings = ({ranks, stances, session}: {ranks?: Record<string, number>; stances: Record<string, number>; session: string}) => (
  <div className="mt-2 text-xs text-[#6e6e73]">
    <p>Analyst percentiles and votes · intraday where available; otherwise {session} close</p>
    <p className="font-mono text-[11px]" title={TRIGGER_LEGEND}>{ratings(ranks, stances) || 'Analyst parts not recorded.'}</p>
    <p className="mt-1 text-[11px]">Numbers are rounded percentiles (0–100); signs are votes, not individual letter grades or probabilities of profit. No number means no valid percentile is available. ? means the vote is missing or invalid.</p>
    <p className="mt-1 text-[11px]">{EVENING_VOTE_CONTEXT}</p>
  </div>
)

const FUNDAMENTAL_PERIOD_LABELS: [string, string][] = [
  ['revenue_yoy', 'Revenue growth, year over year'],
  ['revenue_qoq', 'Revenue growth, quarter over quarter'],
  ['revenue_acceleration', 'Revenue growth acceleration'],
  ['gross_margin', 'Gross margin'],
  ['net_margin', 'Net margin'],
  ['capex_to_revenue', 'Capital expenditure / revenue'],
  ['ocf_to_revenue', 'Operating cash flow / revenue'],
]

// Keep only actual ISO calendar dates, without normalizing invalid dates into a different quarter.
const recordedFiscalDate = (value: string | undefined): string | null => {
  if (!value || !/^\d{4}-\d{2}-\d{2}$/.test(value)) return null
  const parsed = new Date(`${value}T00:00:00Z`)
  return Number.isFinite(parsed.getTime()) && parsed.toISOString().slice(0, 10) === value ? value : null
}

// Scope stored fiscal metadata to this decision and expose the absence of a grade-linked release.
const RecordedAnalystDates = ({fundamental, ticker}: {fundamental: DeskRecord['fundamental']; ticker: string}) => {
  const dates = fundamental?.dates?.[ticker]
  const periods = FUNDAMENTAL_PERIOD_LABELS.map(([key, label]) => ({key, label, date: recordedFiscalDate(dates?.[key])}))
  const hasDates = periods.some(period => period.date !== null)
  return <section aria-label="Recorded analyst evidence dates" className="mt-2 text-xs text-[#6e6e73]">
    <details>
      <summary className="cursor-pointer text-[#0071e3]">Evidence dates for this decision</summary>
      <p className="mt-2">F reference fiscal period ends, not filing or release dates. Metrics can refer to different periods; these dates do not date S or V.</p>
      <p className="mt-1">These dates describe recorded evidence, not necessarily the readings that established a persisted vote.</p>
      <p className="mt-1">F fiscal-date metadata source: {fundamental?.source || 'not recorded'}.</p>
      {hasDates ? <table aria-label="Fundamental fiscal period ends" className="mt-2 w-full text-left">
        <thead><tr><th className="font-medium">Metric</th><th className="font-medium">Fiscal period end</th></tr></thead>
        <tbody>{periods.map(period => <tr key={period.key}><td className="pr-3 py-0.5">{period.label}</td><td className="whitespace-nowrap">{period.date ?? 'Unavailable'}</td></tr>)}</tbody>
      </table> : <p className="mt-1">F fiscal period dates are unavailable for this name. Missing or invalid dates do not establish that the analyst had no financial evidence.</p>}
      <p className="mt-2">No source-release link is recorded for the S vote. Dates in the separately loaded earnings read do not identify the release used for this grade.</p>
    </details>
  </section>
}

// Preserve each recorded reasoning line without rewriting or truncating its text.
const ReasonLines = ({ text }: { text: string }) => (
  <ul className="mt-1 space-y-0.5 text-[#1d1d1f]">
    {text.split('\n').filter(Boolean).map((line, i) => (
      <li key={i}>{line}</li>
    ))}
  </ul>
)

// Date the stored grade and its own metadata while preserving the original headline and reasons.
const EveningAnalysis = ({grade, session, written, fundamental, ticker}: {grade: DeskGrade; session: string; written: string; fundamental: DeskRecord['fundamental']; ticker: string}) => (
  <section aria-label="Evening analysis">
    <h4 className="font-medium text-[#6e6e73]">Evening analysis · {session}</h4>
    <p className="font-medium text-[#1d1d1f]">Recorded grade {grade.grade}</p>
    <p className="font-mono text-[11px] text-[#6e6e73]" title={TRIGGER_LEGEND}>{triggers(grade.stances ?? {}) || 'Analyst votes not recorded.'}</p>
    <p className="text-xs text-[#6e6e73]">Combined analyst grade. Not a current trade instruction.</p>
    <p className="mt-1 text-[11px] text-[#6e6e73]">{ANALYST_MEANINGS}</p>
    <p className="mt-1 text-[11px] text-[#6e6e73]">Stored readings are not a causal breakdown of the votes. {EVENING_VOTE_CONTEXT}</p>
    {grade.reason && <ReasonLines text={grade.reason} />}
    <RecordedAnalystDates fundamental={fundamental} ticker={ticker} />
    {grade.headline && <details className="mt-2 text-xs">
      <summary className="cursor-pointer text-[#0071e3]">Original recorded wording</summary>
      <p className="mt-1 text-[#6e6e73]">Written {marketTime(written)}. Preserved unchanged; this historical wording is not a current trade instruction.</p>
      <p className="mt-1 whitespace-pre-wrap text-[#1d1d1f]">{grade.headline}</p>
    </details>}
  </section>
)

// One number to read at a glance: the paper account's worth, its return
// since the desk started trading it, today's move, the rules' track record
// against the market, how much of the book the desk is carrying, and when
// it next rebalances. Everything here is read from the record or the live
// broker, nothing is invented.
const SummaryStrip = ({
  latest,
  paperLive,
  curve,
  currentPolicyVersion,
}: {
  latest: DeskRecord
  paperLive: DeskPaperLive | null
  curve: DeskCurve | undefined
  currentPolicyVersion?: string
}) => {
  const paper = latest.paper
  const brokerCurrent = paperLive !== null && paperLive.reason === undefined
  const worth = brokerCurrent ? paperLive.equity : paper?.equity
  // The lifetime move from the paper book's starting equity, live when the
  // broker is reachable, and today's move; both as percentages so they read
  // beside the dollar figure. The record's own pl_pct is the fallback when
  // the broker is away.
  const since = brokerCurrent ? paperLive.pl_pct : paper?.pl_pct
  const dayPct = brokerCurrent ? paperLive.day_pl_pct : undefined
  const dayPl = brokerCurrent ? paperLive.day_pl : undefined
  const backtest = curve?.backtest
  const stats = backtest?.stats
  const currentPolicy = backtest?.strategy_policy === (currentPolicyVersion ?? 'cash-bounded-breakout-rotation/3')
  // A curve whose simulation read the frozen EDGAR snapshot - or a record
  // written before the source was carried - is an older fundamental-input
  // simulation even when the execution policy version matches. The source is
  // separate from the policy, so a matching version number must not present a
  // legacy-input curve as measured under corrected fundamentals.
  const currentFundamentals = backtest?.fundamentals_source === 'fundamentals-features/1'
  const curveLabel = currentPolicy
    ? currentFundamentals
      ? 'Current policy simulation'
      : 'Current policy, older fundamental inputs'
    : 'Older policy simulation'
  const last = (arr?: number[]) => (arr && arr.length ? arr[arr.length - 1] : null)
  const rulesTotal = last(backtest?.rules)
  const spyTotal = last(backtest?.spy)
  const qqqTotal = last(backtest?.qqq)
  // The share of the account actually at work, read live from the paper
  // positions; the record's regime exposure only when the broker is not
  // reachable, and never as a claim about what is really invested.
  const investedUsd = paperLive?.positions?.reduce((sum, p) => sum + (p.market_value ?? 0), 0) ?? null
  const liveInvested =
    investedUsd !== null && paperLive?.equity
      ? investedUsd / paperLive.equity
      : null
  const cells = [
    {
      label: 'Practice account',
      value:
        worth !== undefined ? (
          <>
            {money(worth)}
            {typeof since === 'number' && Number.isFinite(since) && (
              <span className="ml-2 text-xs font-normal" title="since the paper book started">
                <Trend value={since * 100} />
              </span>
            )}
          </>
        ) : (
          '—'
        ),
      note: brokerCurrent
        ? `live broker snapshot${paperLive?.as_of ? ` fetched ${marketTime(paperLive.as_of)}` : ''} · simulated funds, no real-money orders`
        : paper
          ? `saved paper snapshot · ${paper.session} · broker refresh ${paperLive === null ? 'pending' : 'unavailable'}`
          : `paper account ${paperLive === null ? 'loading' : 'unavailable'} · no saved snapshot`,
    },
    {
      label: 'Broker day P/L',
      value:
        typeof dayPl === 'number' && Number.isFinite(dayPl) ? (
          <>
            <TrendUsd value={dayPl} />
            {typeof dayPct === 'number' && Number.isFinite(dayPct) && (
              <span className="ml-2 text-xs font-normal text-[#6e6e73]" title="change from the broker's prior closing equity">
                (<Trend value={dayPct * 100} />)
              </span>
            )}
          </>
        ) : (
          '—'
        ),
      note: 'change from the broker’s prior closing equity; not a calendar-day return',
    },
    // The forward track has no numbers until it has a run of sessions, so
    // the cell is not shown empty: a "—" with a cryptic note reads as broken.
    ...(rulesTotal !== null
      ? [
          {
            label: curveLabel,
            value: (
              <>
                <Trend value={rulesTotal * 100} />
                <span className="ml-2 text-xs font-normal text-[#6e6e73]">
                  {spyTotal !== null && <>vs SPY <Trend value={spyTotal * 100} /></>}
                  {qqqTotal !== null && (
                    <>
                      {' '}
                      · QQQ <Trend value={qqqTotal * 100} />
                    </>
                  )}
                </span>
              </>
            ),
            note: !currentPolicy ? 'Predates the shared strategy rules; awaiting a new nightly simulation.' : !currentFundamentals
              ? 'Current policy, but its history was simulated on the frozen EDGAR snapshot (legacy or unrecorded fundamentals); it is not measured on the corrected point-in-time data.'
              : backtest?.funding_model === 'cash-at-fill-v1'
                ? 'cash capped after costs; fractional simulated fills, not broker execution; a universe chosen with hindsight, not evidence of future returns'
                : stats && stats.drawdown !== null
                  ? `legacy simulation permits borrowing without financing costs · worst drawdown ${(stats.drawdown * 100).toFixed(0)}%`
                  : 'legacy simulation permits borrowing without financing costs; not evidence for current cash-only returns',
          },
        ]
      : []),
    {
      label: 'Money at work',
      value:
        liveInvested !== null ? (
          <span>{Math.round(liveInvested * 100)}% invested</span>
        ) : (
          '—'
        ),
      note: 'share of the practice account in positions',
    },
  ]
  const fundamentalSource = latest.provenance?.data?.fundamentals
  // The same concise source wording as the label beside the board, so the
  // at-a-glance strip never claims a source the decision was not read with.
  const fundamentalNotice = !fundamentalSource
    ? 'Fundamentals: data source not tagged.'
    : fundamentalSource === 'fundamentals-features/1'
      ? 'Fundamentals: stored point-in-time filing versions.'
      : 'Fundamentals: frozen EDGAR snapshot (legacy).'
  return (
    <section className="rounded-2xl border border-black/[0.08] bg-white p-4" aria-label="The desk at a glance">
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
        {cells.map((c) => (
          <div key={c.label} className="rounded-2xl border border-black/[0.08] bg-white p-3">
            <p className="text-xs text-[#6e6e73]">{c.label}</p>
            <p className="mt-0.5 truncate text-lg font-semibold text-[#1d1d1f]">{c.value}</p>
            <p className="mt-0.5 text-xs text-[#6e6e73]">{c.note}</p>
          </div>
        ))}
      </div>
      <p className="mt-3 border-t border-black/[0.06] pt-2 text-xs text-[#6e6e73]">
        {fundamentalNotice}
      </p>
    </section>
  )
}

// The regime in front of the board, not at the bottom: the warnings change
// how much of the board to trust, so they lead it. Plain words for each
// flag, and a line when the desk has sized down because of them.
const RegimeBanner = ({ regime, session }: { regime: DeskRecord['regime']; session: string }) => {
  const flags = regime.flags ?? []
  if (flags.length === 0) return null
  const exposure = regime.exposure ?? 1
  return (
    <section className="rounded-xl border border-[#9a6200]/30 bg-[#fff6e5] px-3 py-2" role="note">
      {/* The multiplier goes in the summary, not at the bottom of the fold.
          It is what halves the book - on the live record exposure 0.5 against
          an FOMC gate that is idle - and a reader looking at 57% cash had to
          open a collapsed section to find the only sentence explaining it. */}
      <details><summary className="cursor-pointer text-xs font-medium text-[#9a6200]">Market risk · {session} close · {flags.length} flags{exposure < 1 ? ` · target sizing at ${Math.round(exposure * 100)}%` : ''}</summary>
      <p className="mt-1 text-xs text-[#7a5200]">Reassessed nightly. Intraday research sizing has its own dated inputs.</p>
      <ul className="mt-1 list-disc space-y-0.5 pl-5 text-sm text-[#7a5200]">
        {flags.map((flag) => (
          <li key={flag}>{FLAG_WORDS[flag] ?? flag}</li>
        ))}
      </ul>
      {exposure < 1 && (
        <p className="mt-2 text-sm text-[#7a5200]">
          These flags set the strategy target-size multiplier to {Math.round(exposure * 100)}%.
          The FOMC policy is separate. This is not your invested percentage or a claim about available cash;
          actual holdings depend on recorded fills.
        </p>
      )}
      </details>
    </section>
  )
}

// What moved since the previous session: the upgrades, the downgrades, the
// orders that rebalance the book, and the flags that appeared or cleared.
// The API computes this; the page used to throw it away.
const WhatChanged = ({ changes }: { changes: NonNullable<DeskPayload['changes']> }) => {
  const words = (flag: string) => FLAG_WORDS[flag] ?? flag
  const chips: string[] = []
  if (changes.upgrades.length)
    chips.push(`Upgraded: ${changes.upgrades.map((m) => `${m.ticker} ${m.from}→${m.to}`).join(', ')}`)
  if (changes.downgrades.length)
    chips.push(`Downgraded: ${changes.downgrades.map((m) => `${m.ticker} ${m.from}→${m.to}`).join(', ')}`)
  const rows = [...changes.upgrades, ...changes.downgrades]
  const moved = rows.length > 0 || changes.orders.length > 0 || changes.flags_raised.length > 0 || changes.flags_cleared.length > 0
  if (!moved && !changes.since) return null
  return (
    <section className="rounded-2xl border border-black/[0.08] bg-white p-4">
      <h3 className="mb-1 text-sm font-semibold text-[#1d1d1f]">
        What changed{' '}
        <span className="ml-2 text-xs font-normal text-[#6e6e73]">
          {changes.since ? `since ${shortDate(changes.since)}` : 'the first session on file'}
        </span>
      </h3>
      {moved ? (
        <ul className="space-y-1 text-sm text-[#1d1d1f]">
          {chips.map((c) => (
            <li key={c}>{c}</li>
          ))}
          {changes.orders.length > 0 && (
            <li>
              Changes between recorded strategy target weights, not submitted orders:{' '}
              {changes.orders.map((o) => `${o.action} ${o.ticker}`).join(', ')}
            </li>
          )}
          {changes.flags_raised.length > 0 && (
            <li className="text-[#9a6200]">
              New warning{changes.flags_raised.length === 1 ? '' : 's'}:{' '}
              {changes.flags_raised.map(words).join('; ')}
            </li>
          )}
          {changes.flags_cleared.length > 0 && (
            <li className="text-[#1e7a3a]">
              Cleared: {changes.flags_cleared.map(words).join('; ')}
            </li>
          )}
        </ul>
      ) : (
        <p className="text-sm text-[#6e6e73]">No tracked grade, target-weight or warning changes between the last two evening decisions.</p>
      )}
    </section>
  )
}

// The page must never pass an old decision off as tonight's. When the last
// completed session has no record, or the frozen ML accounts have not
// observed it, by the next morning, say so in one sentence at the top.
function RecordStatus({status, prose, session}: {status?: DeskPayload['record_status']; prose?: {state?: string; status?: string}; session?: string}) {
  const lines: string[] = []
  if (prose?.state && ['partial', 'timed_out', 'unavailable'].includes(prose.state)) lines.push(`Model-written briefs and reads for ${session ?? 'this decision'}: ${prose.status ?? prose.state.replace('_', ' ')}. The decision and its deterministic reads stand.`)
  // An absent block is the usual "not written yet", except when prose from an
  // earlier run of the same session predates this decision: then the block's
  // own status names why it was refused, and the page must say that rather
  // than a generic "have not been written yet".
  if (prose?.state === 'absent') lines.push(`Model-written briefs and reads for ${session ?? 'this decision'}: ${prose.status ?? 'have not been written yet'}. The decision and its deterministic reads stand.`)
  if (status?.record.status === 'late') lines.push(status.record.session
    ? `No decision record for ${status.expected} yet. The evening record is the ${status.record.session} decision; quotes and account data have separate timestamps.`
    : `No decision record for ${status.expected} yet.`)
  if (status?.ml_forward.status === 'late') lines.push(`The frozen ML paper accounts have not observed ${status.expected}.`)
  if (lines.length === 0) return null
  return <div role="status" aria-label="Record status" className="rounded-xl border border-[#b45309]/30 bg-[#fffbeb] px-3 py-2 text-sm text-[#92400e]">
    {lines.map(line => <p key={line}>{line}</p>)}
  </div>
}

// A small dependency-free SVG line chart of the track record: the desk's
// rules, SPY and QQQ on the same sessions, and the paper account's live
// equity normalized to the same start. Hovering shows the values on one
// session.
const CurveChart = ({
  backtest,
  paper,
}: {
  backtest: DeskCurve['backtest']
  paper?: DeskCurve['paper']
}) => {
  const svgRef = useRef<SVGSVGElement | null>(null)
  const [hover, setHover] = useState<number | null>(null)
  // The backtest spans years while the paper account started a few
  // sessions ago. Aligning every series to one merged date axis keeps the
  // paper curve at its real dates; drawing it at the backtest's indices
  // used to put its September 2026 points at the 2015 start of the chart.
  const btDates = backtest?.dates ?? []
  const paperDates = paper?.sessions ?? []
  const dates = [...new Set([...btDates, ...paperDates])].sort()
  const align = (d: string[], values: number[]) => {
    const by = new Map(d.map((date, i) => [date, values[i]] as const))
    return dates.map((date) => by.get(date) ?? NaN)
  }
  const series: { label: string; color: string; values: number[] }[] = []
  if (backtest) {
    series.push({ label: 'stored simulation', color: '#1e7a3a', values: align(btDates, backtest.rules) })
    series.push({ label: 'SPY', color: '#9ca3af', values: align(btDates, backtest.spy) })
    if (backtest.qqq && backtest.qqq.length) series.push({ label: 'QQQ', color: '#0b5cad', values: align(btDates, backtest.qqq) })
  }
  if (paper && paper.equity.length > 1) {
    const base = paper.equity[0] || 1
    series.push({
      label: 'practice account (recorded equity)',
      color: '#d97706',
      values: align(paperDates, paper.equity.map((e) => e / base - 1)),
    })
  }
  const width = 800
  const height = 240
  const padT = 14
  const padB = 26
  const padL = 8
  const padR = 8
  const innerW = width - padL - padR
  const innerH = height - padT - padB
  const all = series.flatMap((s) => s.values).filter(Number.isFinite).concat(0)
  const min = Math.min(...all, 0)
  const max = Math.max(...all, 0)
  const span = max - min || 1
  const x = (i: number) => (dates.length > 1 ? padL + (i / (dates.length - 1)) * innerW : padL + innerW / 2)
  const y = (v: number) => padT + (1 - (v - min) / span) * innerH
  // A polyline per run of finite values, so a series that starts later
  // (the paper account) or skips a date does not draw a false bridge.
  // A missing value must close the current run: appending the next finite
  // point to the last non-empty segment would draw the gap as a straight
  // line, which is exactly the bridge this is meant to avoid.
  const line = (values: number[]) => {
    const segs: { x: number; y: number }[][] = []
    for (const [i, v] of values.entries()) {
      if (!Number.isFinite(v)) {
        if (segs.length && segs[segs.length - 1].length) segs.push([])
        continue
      }
      if (!segs.length || !segs[segs.length - 1].length) segs.push([])
      segs[segs.length - 1].push({ x: x(i), y: y(v) })
    }
    return segs
      .filter((seg) => seg.length)
      .map((seg) => seg.map((p) => `${p.x.toFixed(1)},${p.y.toFixed(1)}`).join(' '))
  }
  const zeroY = y(0)
  const ticks = [0, min / 2, max / 2, max]
  const tickLabels = [...new Set([min, max, 0])]
  const onMove = (e: React.MouseEvent) => {
    const rect = svgRef.current?.getBoundingClientRect()
    if (!rect || dates.length < 2) return
    const fx = ((e.clientX - rect.left) / rect.width) * width
    const idx = Math.round(((fx - padL) / innerW) * (dates.length - 1))
    setHover(Math.max(0, Math.min(dates.length - 1, idx)))
  }
  const hoverSeries = hover !== null ? series.map((s) => ({ ...s, v: s.values[hover] ?? NaN })) : []
  return (
    <div className="relative">
      <svg
        ref={svgRef}
        viewBox={`0 0 ${width} ${height}`}
        className="h-auto w-full"
        role="img"
        aria-label="The desk's track record against SPY and QQQ"
        onMouseMove={onMove}
        onMouseLeave={() => setHover(null)}
      >
        <line x1={padL} x2={width - padR} y1={zeroY} y2={zeroY} stroke="#d1d5db" strokeWidth={1} strokeDasharray="4 4" />
        {series.map((s) =>
          line(s.values).map((points, i) => (
            <polyline key={`${s.label}-${i}`} points={points} fill="none" stroke={s.color} strokeWidth={2} strokeLinejoin="round" strokeLinecap="round" />
          )),
        )}
        {hover !== null && (
          <>
            <line x1={x(hover)} x2={x(hover)} y1={padT} y2={height - padB} stroke="#9ca3af" strokeWidth={1} />
            <circle cx={x(hover)} cy={y(series[0]?.values[hover] ?? 0)} r={3.5} fill="#1d1d1f" />
          </>
        )}
        <text x={padL} y={height - 6} fontSize={11} fill="#6e6e73">
          {dates.length ? shortDate(dates[0]) : ''}
        </text>
        <text x={width - padR} y={height - 6} fontSize={11} fill="#6e6e73" textAnchor="end">
          {dates.length ? shortDate(dates[dates.length - 1]) : ''}
        </text>
        {tickLabels.map((v) => (
          <text key={v} x={width - padR} y={y(v) - 3} fontSize={10} fill="#6e6e73" textAnchor="end">
            {v === 0 ? '0' : `${(v * 100).toFixed(0)}%`}
          </text>
        ))}
        <g aria-hidden="true" transform="translate(6, 6)">
          {series.map((s, i) => (
            <g key={s.label} transform={`translate(0, ${i * 14})`}>
              <rect width={10} height={10} rx={2} fill={s.color} />
              <text x={16} y={9} fontSize={11} fill="#1d1d1f">
                {s.label}
              </text>
            </g>
          ))}
        </g>
      </svg>
      {hover !== null && hoverSeries.length > 0 && (
        <div
          className="pointer-events-none absolute z-10 rounded-lg border border-black/[0.08] bg-white px-2 py-1 text-xs shadow-md"
          style={{ left: `${(x(hover) / width) * 100}%`, top: 0, transform: 'translate(-50%, -110%)' }}
        >
          <p className="font-medium text-[#1d1d1f]">{dates[hover]}</p>
          {hoverSeries.map((s) => (
            <p key={s.label} className="text-[#6e6e73]">
              {s.label}: {Number.isFinite(s.v) ? `${(s.v * 100).toFixed(1)}%` : '—'}
            </p>
          ))}
        </div>
      )}
    </div>
  )
}

// The trust anchor: the rules' track record in words and the curve. Absent
// until the nightly run writes a curve block, with a plain note.
const TrackRecord = ({ curve }: { curve: DeskCurve | undefined }) => {
  const backtest = curve?.backtest
  const stats = backtest?.stats
  if (!backtest || !stats) {
    return (
      <section className="rounded-2xl border border-black/[0.08] bg-white p-4">
        <h3 className="text-sm font-semibold text-[#1d1d1f]">The desk’s track record</h3>
        <p className="mt-1 text-sm text-[#6e6e73]">
          {curve?.backtest_unavailable_reason ?? 'The evening run has not written a curve yet; check back after the next close.'}
        </p>
      </section>
    )
  }
  const cells = [
    { label: 'CAGR', value: stats.cagr != null ? `${(stats.cagr * 100).toFixed(1)}%` : '—' },
    { label: 'Volatility', value: stats.volatility != null ? `${(stats.volatility * 100).toFixed(0)}%` : '—' },
    { label: 'Worst drawdown', value: stats.drawdown != null ? `${(stats.drawdown * 100).toFixed(0)}%` : '—' },
    { label: 'Total return', value: stats.total != null ? `${(stats.total * 100).toFixed(0)}%` : '—' },
  ]
  return (
    <section className="rounded-2xl border border-black/[0.08] bg-white p-4">
      <div className="mb-2 flex flex-wrap items-baseline justify-between gap-2">
        <h3 className="text-sm font-semibold text-[#1d1d1f]">The desk’s track record</h3>
        <p className="text-xs text-[#6e6e73]">
          {backtest.label} · as of {shortDate(backtest.asof)} · the practice account is the only live sample
        </p>
      </div>
      <p className="mb-3 text-xs text-amber-800">{backtest.funding_model === 'cash-at-fill-v1'
        ? 'Simulation assumptions: buys fit cash after costs; closing sales cannot fund earlier buys. Fractional fills and immediate use of completed sale proceeds are modeled; settlement delays, bid/ask spreads, market impact and broker rejections are not. Historical inputs and the selected universe can bias results.'
        : 'Legacy simulation under review: borrowing was permitted without financing costs. These results do not establish the performance of a cash-only account or the current FOMC policy.'}</p>
      <div className="mb-3 grid grid-cols-2 gap-2 sm:grid-cols-4">
        {cells.map((c) => (
          <div key={c.label} className="rounded-xl bg-[#f5f5f7] px-3 py-2">
            <p className="text-xs text-[#6e6e73]">{c.label}</p>
            <p className="text-sm font-semibold text-[#1d1d1f]">{c.value}</p>
          </div>
        ))}
      </div>
      <CurveChart backtest={backtest} paper={curve?.paper} />
      {backtest.evaluation_periods?.map((period) => (
        <p key={period.label} className="mt-3 text-xs text-[#6e6e73]">
          <b>{period.label}</b> · {period.since} to {period.through}: return {(period.total_return * 100).toFixed(2)}%,
          maximum drawdown {(period.drawdown * 100).toFixed(2)}% · {period.sessions} sessions,
          {' '}{period.completed_meetings.length} completed FOMC {period.completed_meetings.length === 1 ? 'meeting' : 'meetings'}. {period.basis}.
        </p>
      ))}
    </section>
  )
}

// The one-screen explanation for someone who has never seen the page, used
// both as the help popover and the empty-state guide.
const HowToUse = ({ onClose, compact = false }: { onClose?: () => void; compact?: boolean }) => (
  <div className={`rounded-xl border border-black/[0.08] bg-[#f5f5f7] p-4 text-sm text-[#1d1d1f] ${compact ? '' : 'my-2 max-w-2xl'}`}>
    <p className="font-medium">Reading this page</p>
    <p className="mt-1 text-[#6e6e73]">
      The board combines the published evening decision with available intraday readings.
      Personal guidance uses your recorded positions and confirmed cash. Nothing here submits
      an order to your brokerage account.
    </p>
    <dl className="mt-3 space-y-2">
      <div>
        <dt className="font-medium">Grade</dt>
        <dd className="text-[#6e6e73]">
          A+ down to C is the combined grade from analyst votes: growth &amp; margins, price trend, earnings-release
          tone, relative valuation (not intrinsic fair value), and which group is leading. Evening votes use persistence rules;
          intraday readings can update price-sensitive inputs. One bearish core analyst caps a name at B.
        </dd>
      </div>
      <div>
        <dt className="font-medium">Opportunity</dt>
        <dd className="text-[#6e6e73]">
          Combined analyst evidence on a zero-to-ten scale, not a return forecast.
          Check the reading timestamp and any missing analyst inputs.
        </dd>
      </div>
      <div>
        <dt className="font-medium">Strategy intent</dt>
        <dd className="text-[#6e6e73]">
          BUY is the strategy&apos;s intent to add; SELL is its intent to reduce; HOLD means it proposes no trade.
          “Blocked now” means the intent is visible but is not executable with the current market evidence,
          allocation, recorded positions, or confirmed cash.
          Size is the currently executable change in your account allocation, not a return since the signal.
          A dash means no trade size is available now. Open a row for the intended change and strategy target.
          Nothing here submits an order.
        </dd>
      </div>
      <div>
        <dt className="font-medium">Selling</dt>
        <dd className="text-[#6e6e73]">
          A covered holding downgraded below A can receive a sell recommendation.
          Sale proceeds are not assumed available before execution. Historical
          comparisons use today's stock universe and do not establish future profitability.
        </dd>
      </div>
      <div>
        <dt className="font-medium">Allocation %</dt>
        <dd className="text-[#6e6e73]">
          Row details include the experimental allocation calculated from the displayed completed bar
          and the adopted strategy&apos;s allocation for its next weight reset. Neither is your
          current position, an order quantity, or a profit target. A grade alone does not guarantee
          an allocation; selection and sizing also apply.
        </dd>
      </div>
      <div>
        <dt className="font-medium">Prices</dt>
        <dd className="text-[#6e6e73]">
          Fifteen-minute IEX bars while the market is open, and the last completed bar once it closes. They are
          bar prices, not executable bid and ask. Check the displayed bar timestamp before acting;
          refreshing the page does not guarantee a newer market observation.
        </dd>
      </div>
      <div>
        <dt className="font-medium">What is real</dt>
        <dd className="text-[#6e6e73]">
          One paper account at the broker, shown as the practice account. It places real paper orders and its
          fills are simulated broker fills. Research comparisons do not submit personal orders.
          Your own brokerage account is never touched: after you trade it
          yourself, use Record to tell this page what filled.
        </dd>
      </div>
    </dl>
    <p className="mt-3 text-xs text-[#6e6e73]">
      Click a sortable column heading to sort, click a name for its history, or click the arrow beside a
      row to see why the desk grades it that way without leaving the board.
    </p>
    {onClose && (
      <button type="button" onClick={onClose} className="mt-3 text-xs text-[#0071e3] hover:underline">
        Close
      </button>
    )}
  </div>
)

// Keep missing account context visible without repeating the page's help guide.
const GettingStarted = ({ hasRecord, hasPositions, onEnterPositions }: { hasRecord: boolean; hasPositions: boolean; onEnterPositions: () => void }) => {
  if (hasRecord && hasPositions) return null
  return (
    <section className="flex flex-wrap items-center gap-2 py-2 text-xs text-[#6e6e73]">
      {!hasRecord ? (
        <p>No evening decision is available yet. Check after the next trading session.</p>
      ) : (
        <p>No personal positions recorded. The separate paper-brokerage positions are shown separately.</p>
      )}
      {hasRecord && (
        <button type="button" onClick={onEnterPositions} className="mt-2 rounded-full bg-[#1d1d1f] px-3 py-1.5 text-sm text-white">
          Add positions
        </button>
      )}
    </section>
  )
}

// The desk's day for a person trading their own account: one board of
// what to do at the next open, computed against the positions they
// entered, with the live candle beside each name; the warnings; and the
// record's detail folded away. Everything shown is read from the record
// the desk wrote and the positions the person saved.
const DeskPanel = ({ userId, canWrite }: DeskPanelProps) => {
  const [payload, setPayload] = useState<DeskPayload | null>(null)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)
  const [live, setLive] = useState<DeskLive>({ as_of: null, quotes: {} })
  const [paperLive, setPaperLive] = useState<DeskPaperLive | null>(null)
  const [holdings, setHoldings] = useState<DeskHolding[]>([])
  const [holdingsReady, setHoldingsReady] = useState(false)
  const [holdingsError, setHoldingsError] = useState('')
  const [storedRows, setRows] = useState<DeskMineRow[]>([])
  const [decisions, setDecisions] = useState<DeskDecisions | undefined>()
  const [storedGrades, setLiveGrades] = useState<Record<string, DeskLiveGrade>>({})
  const [gradeContext, setGradeContext] = useState<{session?: string | null; until: Record<string, string>}>({until: {}})
  const [mineError, setMineError] = useState('')
  const [now, setNow] = useState(Date.now)
  const [intraday, setIntraday] = useState<DeskIntraday | null>(null)
  // The confirmed personal account figures the board is computed against.
  // Equity starts from the per-browser convenience value (legacy default
  // $100,000) and becomes editable; cash is session-memory only - never
  // localStorage and never a URL - and null means "unknown", which keeps
  // buys gated rather than funding them from equity or the paper account.
  const [equity, setEquity] = useState<number>(() => Number(readStored(EQUITY_KEY)) || 100000)
  const [cash, setCash] = useState<number | null>(null)
  const [riskBudgetPct, setRiskBudgetPct] = useState<number | null>(null)
  const [cashStatus, setCashStatus] = useState('')
  // A monotonic context generation. Every desk/mine request captures it before
  // awaiting; when the response returns, if the generation has moved on the
  // caller's cash/equity/user/holdings context changed meanwhile, so the old
  // response is dropped instead of painting stale actions over the new one.
  const accountGen = useRef(0)
  // A later request in the same account context supersedes an earlier one;
  // generation alone cannot distinguish overlapping poll and quote refreshes.
  const mineRequestSeq = useRef(0)
  const acceptedMineRequest = useRef(0)
  const [historyContext, setHistoryContext] = useState<PersonalHistoryContext | null>(null)
  const [help, setHelp] = useState(false)
  const [details, setDetails] = useState(false)
  // Legacy detail links open the guide; stocks remain in the single main list.
  const detailsOpen = new URLSearchParams(window.location.search).get('deskDetails') === '1'
  // Details is two views. Plan is what the desk will do and why: rankings,
  // the plan rows, FOMC, changes, execution. Research is measurement on a
  // slower clock: the gate, execution quality, forward evidence, the ML
  // shadow, the practice account. Mixing them made one long scroll.
  const [research, setResearch] = useState(() => new URLSearchParams(window.location.search).get('deskView') === 'research')
  const historyCapture = useRef(false)
  historyCapture.current = canWrite && !research
  const [editing, setEditing] = useState(false)
  const [saveError, setSaveError] = useState('')
  const [openName, setOpenName] = useState<string | null>(null)
  const [autopsy, setAutopsy] = useState(false)
  const [marking, setMarking] = useState<string | null>(null)

  // Save a confirmed position change and retain the form when persistence fails.
  const save = async (next: DeskHolding[]) => {
    try {
      setHoldings(await putDeskHoldings(userId, next))
      setSaveError('')
      // A recorded fill or a changed positions list is a new holdings
      // context: confirmed cash no longer describes it, so it is cleared
      // (with a reason) rather than silently funding later buys.
      accountGen.current += 1
      setCash(null)
      setCashStatus('Available cash was reset because your positions changed. Confirm it again to fund new buys.')
      setDecisions(undefined)
      return true
    } catch (err) {
      setSaveError(err instanceof Error ? err.message : 'The positions were not saved.')
      return false
    }
  }

  // Persist an actual personal-account fill through the existing position tracker.
  const recordBuy = async (ticker: string, price: number, qty: number, fillDate: string) => {
    setMarking(ticker)
    try {
      return await save(afterTrade(holdings, {ticker, action: 'buy'}, price, qty, fillDate))
    } catch (err) {
      setSaveError(err instanceof Error ? err.message : 'The buy was not recorded.')
      return false
    } finally { setMarking(null) }
  }

  const load = async () => {
    try {
      setPayload(await getDesk(userId))
      setError('')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'The desk could not be loaded.')
    } finally {
      setLoading(false)
    }
  }

  // Apply every field from one personal-guidance response atomically, and
  // ignore any response or error superseded by a newer request or context.
  const refreshMine = async (active: () => boolean = () => true) => {
    const gen = accountGen.current
    const request = ++mineRequestSeq.current
    try {
      const recordHistory = historyCapture.current && !document.hidden
      const mine = await getDeskMine(userId, equity, cash, recordHistory, riskBudgetPct)
      if (!active() || gen !== accountGen.current || request !== mineRequestSeq.current) return
      acceptedMineRequest.current = request
      setRows(mine.rows)
      setDecisions(mine.decisions)
      setHistoryContext(recordHistory ? {
        userId, generation: gen, request, decisions: mine.decisions,
        receipt: mine.history_receipt ?? {status: 'unavailable', reason: 'The server returned no decision receipt.'},
      } : null)
      setLiveGrades(mine.grades_live)
      setGradeContext({session: mine.session, until: mine.grade_valid_until ?? {}})
      if (mine.market_status) setLive((previous) => ({...previous, market_status: mine.market_status}))
      setMineError('')
      setNow(Date.now())
    } catch (err) {
      if (!active() || gen !== accountGen.current || request !== mineRequestSeq.current) return
      setMineError(err instanceof Error ? err.message : 'Personal guidance is unavailable. No trade is executable until it refreshes.')
      // On failure the actions stay unavailable; the previous BUY values are
      // never restored, because they may belong to stale account evidence.
      setLiveGrades({})
      setDecisions(undefined)
      setHistoryContext(null)
      setRows((previous) => previous.map((row) => ({
        ...row, grade_live: row.grade, grade_source: 'evening', stances_live: row.stances, ranks_live: row.ranks,
        score_live: null, grade_margin_live: null, technical_now: null, technical_close: null, value_now: null, value_close: null,
      })))
    }
  }

  // The board, the candle, and the practice account together; the practice
  // account's day P/L feeds the summary strip. Shared by the polling loop
  // and the Refresh button, so a manual refresh re-reads the live layer
  // too rather than only the evening payload.
  const poll = async () => {
    setNow(Date.now())
    try {
      setLive(await getDeskLive(userId))
    } catch {
      setLive((previous) => ({ ...previous, stale: true, reason: 'Market-data refresh failed; showing last known data.' }))
    }
    await refreshMine()
    try {
      setIntraday(await getDeskIntraday(userId))
    } catch {
      // the persisted plan is a convenience; the live board stands
    }
    try {
      setPaperLive(await getDeskPaper(userId))
    } catch {
      setPaperLive({ reason: 'unreachable' })
    }
  }

  // Confirm the personal account figures the board should be computed
  // against. The context changes the moment they are applied: any in-flight
  // response from the previous context is invalidated, the previous decisions
  // are cleared so no stale BUY from a higher-cash context lingers, and the
  // polling effect re-runs on the new equity/cash. Cash is session-memory
  // only; an unknown (null) cash keeps buys gated.
  const applyAccount = (equityValue: number, cashValue: number | null, riskValue: number | null) => {
    accountGen.current += 1
    setEquity(equityValue)
    setCash(cashValue)
    setRiskBudgetPct(riskValue)
    setDecisions(undefined)
    setCashStatus(cashValue === null
      ? 'Available cash unknown; buys stay unfunded until you confirm it.'
      : cashValue === 0
        ? 'Available cash confirmed at $0; no funded buys.'
        : `Available cash confirmed at ${money(cashValue)}; buys can be funded up to this budget.`)
  }

  useEffect(() => {
    void load()
    const timer = window.setInterval(() => void load(), REFRESH_MS)
    return () => window.clearInterval(timer)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [userId])

  useEffect(() => {
    let alive = true
    setHoldingsReady(false)
    void (async () => {
      try {
        const result = await getDeskHoldings(userId)
        if (alive) {
          setHoldings(result)
          setHoldingsReady(true)
          setHoldingsError('')
        }
      } catch {
        if (alive) setHoldingsError('Your positions could not be loaded. Reload the page to retry; position editing is unavailable until they load.')
      }
    })()
    return () => { alive = false }
  }, [userId])

  useEffect(() => {
    void poll()
    const timer = window.setInterval(() => void poll(), POLL_MS)
    // Recheck immediately when a background tab returns to the foreground.
    const resume = () => { if (!document.hidden) void poll() }
    document.addEventListener('visibilitychange', resume)
    return () => {
      window.clearInterval(timer)
      document.removeEventListener('visibilitychange', resume)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [userId, equity, cash, riskBudgetPct, holdings, payload?.latest?.session])

  useEffect(() => {
    // A different account is a different context: confirmed cash never
    // follows the user across the switch, and an in-flight response from the
    // previous account's context is invalidated.
    accountGen.current += 1
    setCash(null)
    setRiskBudgetPct(null)
    setCashStatus('')
    setDecisions(undefined)
  }, [userId])

  useEffect(() => {
    const deadlines = [...Object.values(gradeContext.until), payload?.intraday_research?.valid_until ?? '', ...Object.values(decisions?.rows ?? {}).map(row => row.valid_until ?? '')].map(Date.parse).filter(value => value > now)
    if (!deadlines.length) return
    const timer = window.setTimeout(() => setNow(Date.now()), Math.min(...deadlines) - now + 1)
    return () => window.clearTimeout(timer)
  }, [gradeContext, now, payload?.intraday_research?.valid_until, decisions])

  // Refresh quote eligibility between candle updates and ignore obsolete account requests.
  useEffect(() => {
    let stopped = false
    let busy = false
    // Keep only one quote refresh in flight and fail closed on a provider/API error.
    const refresh = async () => {
      if (busy || document.hidden) return
      busy = true
      try {
        await refreshMine(() => !stopped)
      } catch {
        // refreshMine exposes and fails closed on request errors.
      } finally { busy = false }
    }
    const timer = window.setInterval(() => void refresh(), 15_000)
    return () => { stopped = true; window.clearInterval(timer) }
  }, [userId, equity, cash, riskBudgetPct, holdings, payload?.latest?.session])

  if (loading) {
    return <div className="flex flex-1 items-center justify-center text-sm text-[#6e6e73]">Loading the desk…</div>
  }
  if (error) {
    return <div className="flex flex-1 items-center justify-center text-sm text-[#b42318]">{error}</div>
  }
  if (!payload) {
    return <div className="flex flex-1 items-center justify-center text-sm text-[#6e6e73]">Loading the desk…</div>
  }

  const { latest } = payload
  // A grade needs both the current decision and an unexpired evidence deadline.
  const gradeCurrent = (ticker: string) => gradeContext.session === latest?.session
    && Date.parse(gradeContext.until[ticker] ?? '') > now
  const liveGrades = Object.fromEntries(Object.entries(storedGrades).filter(([ticker]) => gradeCurrent(ticker)))
  const rows = gradeContext.session && gradeContext.session !== latest?.session ? []
    : storedRows.map(row => gradeCurrent(row.ticker) ? row : eveningRow(row)).sort((a, b) =>
      Number(b.in_book) - Number(a.in_book)
      || (GRADE_ORDER[b.grade_live] ?? -1) - (GRADE_ORDER[a.grade_live] ?? -1)
      || (b.score_live ?? latest?.grades[b.ticker]?.score ?? -1e9) - (a.score_live ?? latest?.grades[a.ticker]?.score ?? -1e9)
      || a.ticker.localeCompare(b.ticker))
  const curve = payload.curve ?? latest?.curve
  const warnings = latest?.regime.flags ?? []
  // Whether the paper book's next session is a rebalance: only then are the
  // board's target-vs-held changes executable at the next open. Otherwise
  // they are targets for the next rebalance, and the page says so instead
  // of teaching a daily trading cadence the backtest does not use.
  const countdown = rows.find((r) => r.until_rebalance !== null)?.until_rebalance ?? latest?.paper?.until_rebalance ?? null
  const rebalanceDue = rows.length > 0 ? rows[0].rebalance_due : countdown !== null && countdown <= 1
  const eventLive = payload.event_status
  const event = (!eventLive?.stale && eventLive?.policy) || latest?.event_risk
  // Planning is paused only on the live event state: an active cycle or a
  // policy still in force. A stale observation is not a pause, and the
  // nightly record's frozen execution_pending flag never is.
  const eventPaused = eventLive?.planning_paused === true
  const exchange = exchangeState(live.market_status)
  // The board keeps its sizes during a cycle, at the exposure the desk holds.
  // The exposure is unknown when the calendar is missing or when an active
  // cycle's current policy status has not been read.
  // Count only decisions the backend marks executable while XNYS is open;
  // blocked strategy intent remains visible in the board but never inflates
  // the number described as actionable now.
  const eligibleNow = decisions && decisions.session === latest?.session && decisions.written === latest?.written && !eventPaused && exchange.open
    ? Object.values(decisions.rows).filter(row => {
      const intent = row.strategy_action ?? row.action
      const deadline = row.valid_until ? Date.parse(row.valid_until) : Number.NaN
      return (intent === 'Buy' || intent === 'Sell')
        && row.executable !== false
        && Number.isFinite(deadline)
        && deadline > now
    }).length : 0
  const todayLine = latest ? <TodayLine exchange={exchange} event={event} boardEvent={eventPaused ? {
    exposure: event?.calendar_known === false || typeof event?.factor !== 'number' || !(event.factor > 0) ? null : event.factor,
    decisionDate: event?.decision_date ?? null, calendarUnknown: event?.calendar_known === false,
  } : null} orders={paperLive?.orders?.length ?? eventLive?.pending_orders ?? 0}
    holdings={holdingsReady ? holdings.length : null} eligible={eligibleNow} /> : null
  // Keep a stock's diagnostics and confirmed-fill controls in its existing board expansion.
  const expandRow = (ticker: string) => {
    const g = latest?.grades?.[ticker]
    if (!latest || !g) return null
    const r = rows.find(row => row.ticker === ticker)
    const fresh = liveGrades[ticker]
    const ranks = fresh?.ranks_live ?? r?.ranks_live ?? g.ranks
    const stances = fresh?.stances_live ?? r?.stances_live ?? g.stances ?? {}
    const intradayGrade = Boolean(fresh) || r?.grade_source === 'intraday'
    const currentStances = fresh?.stances_live ?? (r?.grade_source === 'intraday' ? r.stances_live : undefined)
    const quote = live.quotes[ticker]
    return <section aria-label={`${ticker} decision details`} className="grid gap-3 whitespace-normal text-xs sm:grid-cols-[minmax(0,1fr)_auto]">
      <div className="min-w-0">
        <section aria-label="Latest available grade" className="mb-3">
          <h4 className="font-medium text-[#6e6e73]">Latest available grade</h4>
          <p className="font-medium text-[#1d1d1f]"><span aria-label="Latest grade value">{fresh?.grade_live ?? r?.grade_live ?? g.grade}</span> · {intradayGrade ? 'intraday grade' : `at the ${latest.session} close`}</p>
          <AnalystRatings ranks={ranks} stances={stances} session={latest.session} />
          {currentStances && <VoteChanges evening={g.stances ?? {}} current={currentStances} />}
          <p className="mt-2 text-[#6e6e73]">{quote ? <>Bar price {priceMoney(quote.last)} · interval start {marketTime(quote.bar)}{now - Date.parse(quote.bar) >= 30 * 60 * 1000 ? ' · last known bar' : ''}</> : 'Bar price unavailable'}. A bar price is not an executable quote.</p>
          <div className="mt-2 text-[#6e6e73]"><DecisionCell ticker={ticker} decisions={decisions} latest={latest} now={now} /></div>
        </section>
        <EveningAnalysis grade={g} session={latest.session} written={latest.written} fundamental={latest.fundamental} ticker={ticker} />
        {(latest.briefs?.[ticker] || g.read) && <ArchivedCommentary brief={latest.briefs?.[ticker]} read={g.read} written={latest.written} />}
      </div>
      <div className="flex flex-col items-start gap-2">
        <button type="button" className="text-[#0071e3] hover:underline" onClick={() => setOpenName(ticker)}>Open the full panel</button>
        {canWrite && holdingsReady && <ConfirmedBuy ticker={ticker} disabled={marking !== null} onSave={recordBuy} error={saveError} />}
      </div>
    </section>
  }
  // The account's controls sit above the list: the plan is a column of it.
  const planToolbar = latest ? <div className="shrink-0 border-b border-black/[0.06] px-3 py-2">
          <div className="mb-2 flex flex-wrap items-baseline justify-between gap-x-4 gap-y-2">
            {live.reason && <p className="text-xs text-amber-800">{live.reason}</p>}
            <div className="flex flex-wrap items-center gap-4 text-xs text-[#6e6e73]">
              {canWrite && holdingsReady ? (
                <button type="button" onClick={() => setEditing(!editing)} className="text-[#0071e3] hover:underline">
                  {editing ? 'Done' : holdings.length > 0 ? 'Edit positions' : 'Add positions'}
                </button>
              ) : (
                <span className="text-[#6e6e73]">read-only: the operator's book</span>
              )}
            </div>
          </div>
          <AccountInputs equity={equity} cash={cash} riskBudgetPct={riskBudgetPct} cashStatus={cashStatus} onApply={applyAccount} />
          {intraday && intraday.session === latest.session && now - Date.parse(intraday.as_of) <= CANDLE_MS && intraday.changed && intraday.changed.length > 0 && (
            <p className="mb-2 text-xs text-[#9a6200]">
              Since the last plan: {intraday.changed.join(' · ')}
            </p>
          )}
          {holdingsError && <p role="alert" className="mb-2 text-xs text-[#b42318]">{holdingsError}</p>}
          {canWrite && holdingsReady && editing && (
            <Positions
              holdings={holdings}
              error={saveError}
              onSave={async (next) => {
                if (await save(next)) setEditing(false)
              }}
            />
          )}

  </div> : null
  // The plan for a name on the board: the trade against the recorded position.
  const tradeCell = (ticker: string) => {
    const r = rows.find(row => row.ticker === ticker)
    if (!r || !latest) return null
    return <TradeCell r={r} quote={live.quotes[ticker]} equity={equity} marking={marking !== null}
      scheduleLabel={eventPaused ? 'held for the FOMC cycle' : !r.rebalance_due ? 'at the weight reset' : 'at the next open'}
      onDone={canWrite && holdingsReady && rebalanceDue && !eventPaused ? async (price, qty) => {
        setMarking(r.ticker)
        try { return await save(afterTrade(holdings, r, price, qty)) }
        catch (err) { setSaveError(err instanceof Error ? err.message : 'The fill was not recorded.'); return false }
        finally { setMarking(null) }
      } : undefined}
      eligibility={eventPaused
        ? <span>{holdingsReady && holdings.some(h => h.ticker === ticker) ? 'Held through the FOMC cycle' : 'No new buys during the FOMC cycle'}</span>
        : <DecisionCell compact ticker={ticker} decisions={decisions} latest={latest} now={now} />} />
  }
  const boardEvent: BoardEvent | null = eventPaused ? {
    exposure: event?.calendar_known === false || typeof event?.factor !== 'number' || !(event.factor > 0) ? null : event.factor,
    decisionDate: event?.decision_date ?? null,
    calendarUnknown: event?.calendar_known === false,
  } : null

  return (
    <div className="flex flex-1 flex-col gap-3 overflow-y-auto p-4 [&>section]:shrink-0 [&>details]:shrink-0">
      {todayLine}
      <RecordStatus status={payload.record_status} prose={latest ? {state: latest.prose_state, status: latest.prose_status} : undefined} session={latest?.session} />
      <header className="flex flex-wrap items-baseline justify-between gap-3">
        <div>
          <div className="flex items-center gap-2">
            <h2 className="text-xl font-semibold text-[#1d1d1f]">Desk</h2>
            {latest && !research && <button disabled={!canWrite || !holdingsReady} title={holdingsError || undefined} onClick={() => setEditing(true)} className="text-xs text-[#0071e3] disabled:opacity-40">Positions</button>}
            {latest && <button type="button" onClick={() => setResearch(!research)} className="text-xs text-[#0071e3]">{research ? 'Back to the desk' : 'Research'}</button>}
            <button
              type="button"
              onClick={() => setHelp(!help)}
              aria-label="How to use this page"
              title="How to use this page"
              className="flex h-5 w-5 items-center justify-center rounded-full border border-black/[0.2] text-xs font-semibold text-[#6e6e73] hover:bg-black/[0.05]"
            >
              i
            </button>
            <button
              type="button"
              onClick={() => setAutopsy(!autopsy)}
              className="rounded-full border border-black/[0.08] bg-white px-2.5 py-0.5 text-xs font-medium text-[#1d1d1f] hover:bg-[#f5f5f7]"
            >
              {autopsy ? 'Hide the review' : 'Analyze my trading'}
            </button>
          </div>
          {help && <HowToUse onClose={() => setHelp(false)} />}
          <p className="text-sm text-[#6e6e73]">
            {latest ? `Decision session ${latest.session} · published ${marketTime(latest.written)}` : 'No decision on file yet'}
          </p>
        </div>
        <button
          type="button"
          onClick={() => {
            void load()
            void poll()
          }}
          className="flex items-center gap-2 rounded-full border border-black/[0.08] bg-white px-3 py-1.5 text-sm text-[#1d1d1f] hover:bg-[#f5f5f7]"
        >
          <RefreshCw size={14} /> Refresh
        </button>
      </header>

      {canWrite && <PersonalDecisionHistory key={userId} userId={userId} context={historyContext} decisions={decisions}
        session={latest?.session} written={latest?.written} active={!research && !!latest}
        displayPaused={eventPaused}
        isCurrent={context => context.userId === userId && context.generation === accountGen.current && context.request === acceptedMineRequest.current} />}

      {autopsy && <AutopsyView userId={userId} onClose={() => setAutopsy(false)} />}

      {!latest && <GettingStarted hasRecord={false} hasPositions={holdings.length > 0} onEnterPositions={() => setEditing(true)} />}

      {latest && <RegimeBanner regime={latest.regime} session={latest.session} />}

      {!research && <>
      {/* On phones, diagnostics use page scrolling instead of a tiny nested viewport. */}
      {latest && <div className="flex flex-col sm:max-h-[75vh]">
      {mineError && <p role="alert" className="border-b border-black/[0.06] bg-red-50 px-3 py-2 text-xs text-[#b42318]">Personal guidance unavailable: {mineError} No trade is shown as executable.</p>}

      <StockBoard latest={latest} live={live} grades={liveGrades} research={payload.intraday_research} coverage={payload.coverage} decisions={decisions}
      holdings={holdingsReady ? holdings : null} broker={paperLive} event={boardEvent} now={now}
      holdingsError={holdingsError}
      planAction={(ticker) => planFor(ticker, decisions, latest, now).action}
      expand={expandRow} extraNames={rows.filter(r => r.action === 'uncovered').map(r => r.ticker)} toolbar={planToolbar} trade={tradeCell} closes={Object.fromEntries(rows.map(r => [r.ticker, r.last_close]))} footer={<p className="border-t border-black/[0.05] px-3 py-2 text-[11px] text-[#6e6e73]">{saveError && !editing ? <span className="text-[#b42318]">{saveError} · </span> : null}Record confirmed broker fills only. No automatic price stops.</p>} onOpen={setOpenName} />
      </div>}
      {latest && <details aria-label="Strategy details" className="rounded-xl border border-black/[0.08] bg-white p-3 text-xs"><summary className="cursor-pointer font-medium">Strategy details</summary>
      <p aria-label="Fundamental data source" className="border-b border-black/[0.06] px-3 py-1.5 text-[11px] text-[#6e6e73]">
        {latest.provenance?.data?.fundamentals === 'fundamentals-features/1'
          ? 'Fundamentals: stored point-in-time filing versions.'
          : latest.provenance?.data?.fundamentals
            ? 'Fundamentals: frozen EDGAR snapshot (legacy).'
            : 'Fundamentals: data source not tagged.'}
      </p>
            <h3 aria-label="Plan status" className="text-xs font-medium text-[#1d1d1f]">
              {eventPaused ? 'The FOMC cycle takes priority over the scheduled plan.'
                : rebalanceDue ? 'Paper weight reset due at the next open; personal signals use their own execution checks.'
                : countdown !== null ? `Paper weights reset in ${countdown} session${countdown === 1 ? '' : 's'}.`
                : 'No paper weight reset scheduled.'}
              {live.as_of && (
                <span className="ml-2 font-normal text-[#6e6e73]">
                  {exchange.open
                    ? `Prices from the ${marketTime(live.data_at)} bar.`
                    : `${exchange.label}; prices are from the ${marketTime(live.data_at)} bar.`}
                  {exchange.open && (live.stale || Date.now() - Date.parse(live.as_of) > CANDLE_MS) && (
                    <span className="ml-2 rounded bg-amber-100 px-1.5 py-0.5 font-medium text-amber-800">
                      not updating
                    </span>
                  )}
                </span>
              )}
              {live.reason && <span className="ml-2 font-normal text-amber-800">{live.reason}</span>}
            </h3>
{latest && <DeskGuide latest={latest} open={detailsOpen} />}


      {/* Amber only when the gate is actually doing something. It is a
          provisional policy that spends most of its life monitoring - on the
          live record factor 1.0, nothing pending, the decision 28 sessions
          away - and rendering it as a standing warning put the reader's eye
          on a rule that was idle while the rule halving his book sat
          collapsed above it. */}
      {payload.event_policy?.enabled && (
        <section aria-label="FOMC exposure policy" className={eventPaused || event?.factor === 0.5 || eventLive?.active
          ? "rounded-2xl border border-amber-200 bg-amber-50 p-4 text-sm text-[#5c4300]"
          : "rounded-2xl border border-black/[0.08] bg-white p-4 text-sm text-[#6e6e73]"}>
          <h3 className="font-semibold">FOMC · {!eventLive?.stale && eventLive?.status ? eventLive.status : eventPaused ? 'portfolio adjustments paused' : !event ? 'decision missing' : 'monitoring'} <span className="text-xs font-normal">· provisional policy</span></h3>
          {eventLive?.as_of && <p className="mt-1 text-xs">Checked {marketTime(eventLive.as_of)}{eventLive.stale ? ' · last known status' : ''}</p>}
          <details className="mt-1 text-xs"><summary className="cursor-pointer">Policy & execution</summary>
          <p className="mt-1">A negative five-session SPY return can trigger a one-time 50% reduction in held shares during the three sessions before the decision.
            The reduction lasts through decision day. Nightly paper orders are queued for the next open, even on a green day.
            Missed reductions are recovered during market hours using the same share baseline; recovery does not place buys.
            Actual fill times and prices can differ.
            Restoration is limited to confirmed reductions and available cash. Regular rebalances wait until the event cycle ends.
            Restoration follows the calendar and cash availability; it is not a fresh market-risk all-clear.
            If the remaining shares are unaffordable, the cycle ends with those shares left unbought.</p>
          </details>
          <p className="mt-2 text-xs">{event
            ? `Using the ${event.session} close: ${!event.calendar_known ? 'calendar unavailable; exposure changes paused' : event.factor === 0.5 ? 'reduction triggered or still in force' : eventLive?.active && !eventLive.stale ? `the reduction is done${eventLive.sold ? ` (${Object.keys(eventLive.sold).length} names sold)` : ''}; restoration is queued for the open after the decision` : eventLive?.active ? `the reduction is done; ${paperLive?.orders?.length ? `${paperLive.orders.length} restoration orders are` : 'restoration is'} queued for the open after the decision` : 'no pre-meeting reduction requested'}. FOMC decision: ${event.decision_date ?? 'unavailable'}.`
            : eventLive?.active ? 'An event cycle is recorded; the current policy observation is unavailable.'
            : 'Enabled for the next nightly run. The stored decision predates this policy; it does not confirm any reduction.'}</p>
          {event?.outcome?.status === 'cash-limited' && <p className="mt-2">Cash-limited restoration recorded {event.outcome.session}:
            {' '}{Object.entries(event.outcome.unrestored).map(([symbol, qty]) => `${symbol} ${qty} shares unbought`).join(' · ')}.
            These are unfilled quantities, not restored positions.</p>}
          <p className="mt-1 text-xs">{eventLive?.active
            ? 'The reduction runs in the practice account below; your own book is unchanged until you act at your broker.'
            : 'Nothing is being traded for this policy right now. Any reduction would run in the practice account below, never in your own book.'}</p>
        </section>
      )}


      {latest && payload.changes && <WhatChanged changes={payload.changes} />}
      {latest && <section aria-label="Your planned cash" className="flex flex-wrap gap-x-5 gap-y-1 rounded-xl border border-black/[0.08] bg-white px-3 py-2 text-xs">
        <span title="Cash implied by the plan's target weights, before fees; not actual holdings">Planned cash <b>{(100 * Math.max(0, 1 - latest.book.reduce((sum, row) => sum + row.weight, 0))).toFixed(1)}%</b></span>
        <span className="text-[#6e6e73]">{eventPaused ? 'FOMC overrides the scheduled plan' : 'Weights apply at the reset'}</span>
      </section>}
      </details>}


      {latest && (
        <details className="rounded-2xl border border-black/[0.08] bg-white" aria-label="Practice account">
          <summary className="cursor-pointer px-4 py-3 text-sm font-semibold text-[#1d1d1f]">
            Practice account
            <span className="ml-2 text-xs font-normal text-[#6e6e73]">simulated funds · the desk's paper book, not your money</span>
          </summary>
          <div className="space-y-3 px-4 pb-4">
            <SummaryStrip latest={latest} paperLive={paperLive} curve={curve} currentPolicyVersion={payload.current_policy} />
            {paperLive && paperLive.reason === undefined && paperLive.equity !== undefined && <LivePositions paper={paperLive} equity={paperLive.equity} />}
            <section aria-label="Paper execution" className="rounded-xl border border-black/[0.08] p-3 text-xs">
              <h3 className="font-semibold">Paper execution {paperLive?.as_of ? `· fetched ${marketTime(paperLive.as_of)}` : ''}</h3>
              <p>{paperLive?.orders ? `${paperLive.orders.length} open orders` : 'Open orders unavailable'}</p>
              {paperLive?.orders?.map((order, i) => <p key={i}>{order.side} {order.qty} {order.symbol} · {order.status}</p>)}
              <p>{paperLive?.activity?.fills ? `${paperLive.activity.fills.length === 0 && paperLive.activity.complete ? 'No fills' : `${paperLive.activity.fills.length}${paperLive.activity.complete ? '' : '+'} fills`} · ${paperLive.activity.session}` : 'Today’s fill history unavailable'}</p>
              {paperLive?.activity?.fills?.map((fill, i) => <p key={i}>{fill.side} {fill.qty} {fill.symbol} at {priceMoney(fill.price)} · {executionTime(fill.filled_at)}</p>)}
            </section>
            <TrackRecord curve={curve} />
          </div>
        </details>
      )}

      </>}

      {research && <>
      <section aria-label="What the research accounts are" className="rounded-xl border border-black/[0.08] bg-white px-3 py-2 text-xs text-[#6e6e73]">
        <p><span className="font-medium text-[#1d1d1f]">Simulated accounts, separate from your portfolio.</span> The practice account shows paper-broker orders and fills. The board simulation and frozen ML comparison are research. Personal guidance uses your recorded positions and confirmed cash.</p>
      </section>
      {latest && <details className="rounded-xl border border-black/[0.08] px-3 py-2 text-xs">
        <summary className="cursor-pointer font-medium">Inflation · {payload.economics?.assessment?.status === 'model_assessment' && !payload.economics.collection_stale && Date.now() - Date.parse(payload.economics.observed_at) < 36 * 3600000 ? payload.economics.assessment.pressure : 'unavailable'} · research</summary>
        <EconomicContext data={payload.economics} />
      </details>}

      <ForwardEvidence evidence={payload.forward_evidence} />
      <NeuralStudy study={payload.neural_study} />
      <StrategyBench bench={payload.strategy_bench} />
      <FomcGate gate={payload.fomc_gate} />
      <ExecutionQuality quality={payload.execution_quality} />
      <MlComparison ml={payload.ml_forward} />
      <section className="rounded-xl border border-black/[0.08] bg-white"><BoardSimulation paper={payload.board_paper} now={now} /></section>

      {latest && (
        <button
          type="button"
          onClick={() => setDetails(!details)}
          className="self-start text-sm text-[#0071e3] hover:underline"
        >
          {details ? 'Hide the details' : 'Show practice account details'}
        </button>
      )}

      {latest && details && <PracticeAccount record={latest.paper} paperLive={paperLive} />}
      </>}


      {/* With a decision on file the positions editor is the inline form in the
          board's plan toolbar; this modal is only for the no-record case, where
          there is no board to edit against. The two never appear together. */}
      {editing && !latest && <div role="dialog" aria-modal="true" aria-label="Your positions" className="fixed inset-0 z-50 flex items-center justify-center bg-black/30 p-4">
        <div className="max-h-[85vh] w-full max-w-2xl overflow-auto rounded-2xl bg-white p-4">
          <div className="mb-3 flex justify-between"><h3 className="font-semibold">Your positions</h3><button onClick={() => setEditing(false)} aria-label="Close positions"><X size={18} /></button></div>

          <Positions holdings={holdings} error={saveError} onSave={async next => {if (await save(next)) setEditing(false)}} />
        </div>
      </div>}
      {openName && latest && (
        <NameDetail
          compact
          userId={userId}
          ticker={openName}
          paused={Boolean(eventPaused)}
          holdings={holdingsReady ? holdings : null}
          equity={equity}
          latest={latest}
          row={rows.find((r) => r.ticker === openName) ?? null}
          live={live}
          liveGrades={liveGrades}
          decisions={decisions}
          now={now}
          onClose={() => setOpenName(null)}
        />
      )}
    </div>
  )
}

// The practice account as the broker reports it this minute: every position
// with its price, cost and what it is worth now, so the desk page shows the
// live book and its P/L in dollars, not only the plan beside the person's
// own notes.
const LivePositions = ({ paper, equity }: { paper: DeskPaperLive; equity: number }) => {
  const positions = paper.positions ?? []
  const rows = positions.map((p) => {
    const pl = p.unrealized_pl ?? (p.current_price - p.avg_entry_price) * p.qty
    const plPct = p.avg_entry_price > 0 ? (p.current_price / p.avg_entry_price - 1) * 100 : 0
    return { ...p, pl, plPct }
  })
  const totalPl = rows.reduce((s, r) => s + r.pl, 0)
  const totalValue = rows.reduce((s, r) => s + r.market_value, 0)
  return (
    <section className="rounded-2xl border border-black/[0.08] bg-white p-4">
      <div className="mb-2 flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
        <h3 className="text-sm font-semibold text-[#1d1d1f]">
          Practice positions
          {paper.as_of && (
            <span className="ml-2 text-xs font-normal text-[#6e6e73]">
              broker snapshot fetched {marketTime(paper.as_of)}
            </span>
          )}
        </h3>
        <span className="text-xs text-[#6e6e73]">
          {money(equity)} in the account · day P/L{' '}
          {paper.day_pl !== undefined ? <TrendUsd value={paper.day_pl} /> : '—'}
        </span>
      </div>
      <p className="mb-2 text-xs text-[#6e6e73]">Broker marks can differ from IEX bars. The fetch time is not the time of the last trade.</p>
      <table className="w-full text-sm">
        <thead className="text-left text-xs text-[#6e6e73]">
          <tr>
            <th className="py-1">position</th>
            <th className="py-1 text-right">shares</th>
            <th className="py-1 text-right">broker mark</th>
            <th className="py-1 text-right">avg cost</th>
            <th className="py-1 text-right">value</th>
            <th className="py-1 text-right">P/L</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((p) => (
            <tr key={p.symbol} className="border-t border-black/[0.05]">
              <td className="py-1.5 font-medium text-[#1d1d1f]">{p.symbol}</td>
              <td className="py-1.5 text-right text-[#6e6e73]">{p.qty.toLocaleString()}</td>
              <td className="py-1.5 text-right">{priceMoney(p.current_price)}</td>
              <td className="py-1.5 text-right text-[#6e6e73]">{priceMoney(p.avg_entry_price)}</td>
              <td className="py-1.5 text-right">{money(p.market_value)}</td>
              <td className="whitespace-nowrap py-1.5 text-right">
                <TrendUsd value={p.pl} />
                <span className="ml-1 text-xs text-[#6e6e73]">
                  ({p.plPct >= 0 ? '+' : ''}
                  {p.plPct.toFixed(1)}%)
                </span>
              </td>
            </tr>
          ))}
        </tbody>
        <tfoot>
          <tr className="border-t border-black/[0.08]">
            <td className="py-1.5 text-xs text-[#6e6e73]">{rows.length} open positions</td>
            <td />
            <td />
            <td />
            <td className="py-1.5 text-right text-xs text-[#6e6e73]">{money(totalValue)}</td>
            <td className="py-1.5 text-right text-xs">
              <TrendUsd value={totalPl} />
            </td>
          </tr>
        </tfoot>
      </table>
    </section>
  )
}

// The trader's own recorded book at live prices: each position's value and
// P/L against its entry, and the total, so the live view leads with the
// person's money rather than the practice account's. Priced from the live
// candle, then the plan's recorded price, then its last close.
const YourPositions = ({ holdings, live, rows }: {
  holdings: DeskHolding[]
  live: DeskLive
  rows: DeskMineRow[]
}) => {
  const priced = holdings.map((h) => {
    const quote = live.quotes[h.ticker]?.last
    const row = rows.find((r) => r.ticker === h.ticker)
    const last = quote ?? row?.last ?? row?.last_close ?? null
    const value = last !== null ? last * h.shares : null
    const pl = last !== null ? (last - h.entry_price) * h.shares : null
    const plPct = last !== null && h.entry_price > 0 ? (last / h.entry_price - 1) * 100 : null
    return { ...h, last, value, pl, plPct }
  })
  const totalValue = priced.reduce((s, p) => s + (p.value ?? 0), 0)
  const totalPl = priced.reduce((s, p) => s + (p.pl ?? 0), 0)
  const cost = priced.reduce((s, p) => s + p.shares * p.entry_price, 0)
  const totalPlPct = cost > 0 ? (totalPl / cost) * 100 : null
  return (
    <section aria-label="Your positions" className="rounded-2xl border border-black/[0.08] bg-white p-4">
      <div className="mb-2 flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
        <h3 className="text-sm font-semibold text-[#1d1d1f]">
          Your positions
          <span className="ml-2 text-xs font-normal text-[#6e6e73]">{priced.length} recorded {priced.length === 1 ? 'holding' : 'holdings'} · P/L against your recorded entry</span>
        </h3>
        <span className="text-xs text-[#6e6e73]">
          Value {money(totalValue)} · P/L <TrendUsd value={totalPl} />
          {totalPlPct !== null && <span className="ml-1">(<Trend value={totalPlPct} />)</span>}
        </span>
      </div>
      <table className="w-full text-sm">
        <thead className="text-left text-xs text-[#6e6e73]">
          <tr>
            <th className="py-1">position</th>
            <th className="py-1 text-right">shares</th>
            <th className="py-1 text-right">entry</th>
            <th className="py-1 text-right">last</th>
            <th className="py-1 text-right">value</th>
            <th className="py-1 text-right">P/L</th>
          </tr>
        </thead>
        <tbody>
          {priced.map((p) => (
            <tr key={p.ticker} className="border-t border-black/[0.05]">
              <td className="py-1.5 font-medium text-[#1d1d1f]">{p.ticker}</td>
              <td className="py-1.5 text-right text-[#6e6e73]">{p.shares.toLocaleString()}</td>
              <td className="py-1.5 text-right text-[#6e6e73]">{priceMoney(p.entry_price)}</td>
              <td className="py-1.5 text-right">{p.last !== null ? priceMoney(p.last) : <span className="text-[#9ca3af]">—</span>}</td>
              <td className="py-1.5 text-right">{p.value !== null ? money(p.value) : '—'}</td>
              <td className="whitespace-nowrap py-1.5 text-right">
                {p.pl !== null ? (
                  <>
                    <TrendUsd value={p.pl} />
                    {p.plPct !== null && <span className="ml-1 text-xs text-[#6e6e73]">(<Trend value={p.plPct} />)</span>}
                  </>
                ) : '—'}
              </td>
            </tr>
          ))}
        </tbody>
        <tfoot>
          <tr className="border-t border-black/[0.08]">
            <td className="py-1.5 text-xs text-[#6e6e73]">{priced.length} open positions</td>
            <td />
            <td />
            <td />
            <td className="py-1.5 text-right text-xs text-[#6e6e73]">{money(totalValue)}</td>
            <td className="py-1.5 text-right text-xs"><TrendUsd value={totalPl} /></td>
          </tr>
        </tfoot>
      </table>
    </section>
  )
}

// The practice account: the broker's live money, positions and waiting
// orders, refreshed with the candle; the evening record when the broker
// cannot be reached. The live state is shared with the summary strip so
// both read the same number.
const PracticeAccount = ({
  record,
  paperLive,
}: {
  record: DeskRecord['paper']
  paperLive: DeskPaperLive | null
}) => {
  const live = paperLive
  const fromBroker = live !== null && live.reason === undefined
  const positions = fromBroker ? (live.positions ?? []) : (record?.positions ?? [])
  const orders = fromBroker ? (live.orders ?? []) : (record?.orders ?? [])
  const equityValue = fromBroker ? live.equity : record?.equity
  const cash = fromBroker ? live.cash : record?.cash
  if (equityValue === undefined || cash === undefined) return null
  return (
    <section className="rounded-2xl border border-black/[0.08] bg-white p-4">
      <h3 className="mb-1 text-sm font-semibold text-[#1d1d1f]">
        Practice account
        <span className="ml-2 text-xs font-normal text-[#6e6e73]">
          {fromBroker && live.as_of
            ? `broker snapshot fetched ${marketTime(live.as_of)}`
            : fromBroker ? 'broker snapshot · fetch time unavailable'
              : `saved paper snapshot · ${record?.session ?? 'session unavailable'} · broker refresh ${live === null ? 'pending' : 'unavailable'}`}
        </span>
      </h3>
      <p className="mb-2 text-xs text-[#6e6e73]">
        A paper account that follows the desk with market data and simulated execution.
        Its results include missed and delayed fills and can differ from the strategy simulation.
      </p>
      <p className="text-sm text-[#1d1d1f]">
        Worth {money(equityValue)} · cash {money(cash)}
        {fromBroker && live.day_pl !== undefined && (
          <>
            {' '}· broker day P/L <TrendUsd value={live.day_pl} />
          </>
        )}
        {!fromBroker && record && (
          <>
            {' '}·{' '}
            Recorded plan: {record.plan}
          </>
        )}
      </p>
      {orders.length > 0 && (
        <p className="mt-2 text-sm text-[#6e6e73]">
          {fromBroker ? 'Open broker orders' : 'Submissions in the evening record'}:
          {' '}{orders.map((o) => `${o.side} ${o.qty} ${o.symbol}`).join(', ')}.
          {' '}{fromBroker
            ? 'Open orders may still fill, expire or be canceled.'
            : 'These submissions do not confirm current order status or fills.'}
        </p>
      )}
      {(record?.settled?.length ?? 0) > 0 && (
        <details className="mt-3 text-xs text-[#6e6e73]">
          <summary className="cursor-pointer font-medium text-[#1d1d1f]">Execution receipts · {record?.session}</summary>
          <p className="mt-2">Archived outcomes. Completion is for the whole order. Drift compares average fill with decision price; positive is worse.</p>
          <ul className="mt-2 space-y-3">
            {record?.settled?.map((fill, index) => (
              <li key={fill.client_order_id ?? `${fill.symbol}-${index}`} className="border-t border-black/[0.05] pt-2">
                <p className="font-medium text-[#1d1d1f]">{fill.side} {fill.symbol} · {fill.filled} of {fill.qty} shares filled
                  {fill.filled > 0 && fill.filled_price > 0 ? ` at ${priceMoney(fill.filled_price)} average` : ''}
                  {' '}· {fill.status === 'dead' ? 'closed without a fill'
                    : fill.status === 'missing' ? 'not found in broker response'
                      : fill.status === 'skipped' ? 'remaining shares deliberately held'
                        : fill.status === 'partial' && fill.terminal ? 'partially filled; remainder closed'
                          : fill.status}</p>
                {fill.execution?.decision_at && <p>Decision: {executionTime(fill.execution.decision_at)}</p>}
                {fill.execution?.submitted_at && <p>Broker submission: {executionTime(fill.execution.submitted_at)}</p>}
                {fill.execution?.filled_at && <p>Order completion time: {executionTime(fill.execution.filled_at)}</p>}
                {fill.execution?.reference_price != null && (
                  <p>Reference: {priceMoney(fill.execution.reference_price)} · {fill.execution.reference_session}
                    {' '}· {fill.execution.reference_source}</p>
                )}
                {fill.decision_shortfall_bps != null && Number.isFinite(fill.decision_shortfall_bps) && <p>Decision-price drift: {`${fill.decision_shortfall_bps > 0 ? '+' : ''}${fill.decision_shortfall_bps.toFixed(1)} bp`}</p>}
              </li>
            ))}
          </ul>
        </details>
      )}
      {/* The broker's live book is already shown in its own section above the
          board; only the evening record's positions are repeated here, when the
          broker is away and there is no live table to see. */}
      {!fromBroker && positions.length > 0 ? (
        <table className="mt-2 w-full text-sm">
          <thead className="text-left text-[#6e6e73]">
            <tr>
              <th className="py-1">Name</th>
              <th>Shares</th>
              <th>Worth now</th>
              <th>Bought at</th>
              <th>Price now</th>
              <th>Gain so far</th>
            </tr>
          </thead>
          <tbody>
            {positions.map((p) => (
              <tr key={p.symbol} className="border-t border-black/[0.05]">
                <td className="py-1 font-medium">{p.symbol}</td>
                <td>{p.qty}</td>
                <td>{money(p.market_value)}</td>
                <td>{priceMoney(p.avg_entry_price)}</td>
                <td>{priceMoney(p.current_price)}</td>
                <td className={p.unrealized_pl >= 0 ? 'text-[#1e7a3a]' : 'text-[#b42318]'}>
                  <TrendUsd value={p.unrealized_pl} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : (
        !fromBroker && <p className="mt-2 text-sm text-[#6e6e73]">No positions held.</p>
      )}
    </section>
  )
}

// The desk's plan for one name against the person's recorded position: the
// move, the share count for this account, when it is due, the record-fill
// control, the position held, the grade's caveats and whether it is
// eligible to buy right now. This is the column that used to be a table.
const TradeCell = ({ r, quote, equity, marking, scheduleLabel, onDone, eligibility }: {
  r: DeskMineRow
  quote?: DeskQuote
  equity: number
  marking: boolean
  scheduleLabel: string
  onDone?: (price: number, qty: number) => Promise<boolean>
  eligibility: ReactNode
}) => {
  const [recording, setRecording] = useState(false)
  const [filledShares, setFilledShares] = useState('')
  const [fillPrice, setFillPrice] = useState('')
  const { price, qty } = sizing(r, quote, equity)
  const liveDrop = r.in_book && r.grade_live === 'C' && (r.action === 'buy' || r.action === 'add')
  // A share count is an order or it is noise. Between resets the target-minus-
  // current delta is neither: the reset is up to six months out and the number
  // will be recomputed before it ever becomes a trade, so rendering it as
  // "BUY 32 shares at the weight reset" put an instruction in front of the
  // operator for an event he cannot act on. It shows only on the session the
  // reset is due. What to do in between is the live signal, which is the
  // eligibility line below.
  // The live signal leads the cell. `r.action` is the rebalance delta from
  // holdings.board - target minus current - and it answers the calendar, not
  // the operator. It used to be the cell's headline, so a name the desk was
  // buying on a breakout read "BUY 32 shares at the weight reset" while the
  // signal sat underneath as grey text. Clamping the word to "hold" between
  // resets made it worse, because the pill's colour still keyed off the
  // ungated action: a buy delta rendered a green badge reading HOLD.
  //
  // So the badge is gone. `eligibility` carries Buy, Sell or Hold and the
  // shares to trade at the live price, and what remains here is the position
  // itself and the affordances for recording a fill.
  const moving = r.rebalance_due && ['buy', 'add', 'trim', 'sell'].includes(r.action)
  return (
    <div className="text-xs">
      <div>{eligibility}</div>
      <div className="mt-0.5 flex flex-wrap items-center gap-x-2 gap-y-0.5 text-[#6e6e73]">
        {r.action === 'uncovered' && <span className="font-medium">uncovered</span>}
        {r.action === 'uncovered' && <span>{r.shares.toLocaleString()} shares held</span>}
        {r.action !== 'hold' && r.action !== 'uncovered' && r.action !== 'blocked' && onDone && (
          <button type="button" onClick={() => setRecording(!recording)} disabled={marking} title="Record actual filled shares and average price confirmed by your broker" className="text-[#0071e3] hover:underline disabled:text-[#6e6e73]">
            {recording ? 'cancel fill' : 'record fill'}
          </button>
        )}
      </div>
      {recording && onDone && (
        <form aria-label={`Record ${r.ticker} fill`} className="mt-2 space-y-2" onSubmit={async (event) => {
          event.preventDefault()
          if (marking) return
          if (await onDone(Number(fillPrice), Number(filledShares))) { setRecording(false); setFillPrice(''); setFilledShares('') }
        }}>
          <label className="block">Filled shares
            <input aria-label="Filled shares" className="block w-28 rounded border p-1" type="number" min="0.000001" step="any" required value={filledShares} onChange={event => setFilledShares(event.target.value)} />
          </label>
          <label className="block">Average fill price ($)
            <input aria-label="Average fill price" className="block w-28 rounded border p-1" type="number" min="0.000001" step="any" required value={fillPrice} onChange={event => setFillPrice(event.target.value)} />
          </label>
          <button type="submit" disabled={marking} className="text-[#0071e3] disabled:text-[#6e6e73]">{marking ? 'saving' : 'Save confirmed fill'}</button>
        </form>
      )}

      {r.shares > 0 && r.entry_price !== null && (
        <div className="text-[#6e6e73]">
          recorded position: {r.shares} shares at {priceMoney(r.entry_price)}
          {r.pl_pct !== null && r.last !== null && (
            <span className={r.pl_pct >= 0 ? ' text-[#1e7a3a]' : ' text-[#b42318]'}>
              {' '}<TrendUsd value={r.shares * (r.last - r.entry_price)} /><span className="ml-1">(<Trend value={r.pl_pct * 100} />)</span>
            </span>
          )}
        </div>
      )}
    </div>
  )
}

// Paste from a broker page: one position per line, ticker, shares, cost
// and an optional date, in whatever separators came with it. Lines that
// do not parse are named, not dropped in silence.
const parsePasted = (text: string): { rows: DeskHolding[]; skipped: string[] } => {
  const today = new Date().toISOString().slice(0, 10)
  const rows: DeskHolding[] = []
  const skipped: string[] = []
  for (const raw of text.split(/\r?\n/)) {
    const line = raw.trim()
    if (!line) continue
    const parts = line.split(/[\s,;\t]+/).map((p) => p.replace(/[$"]/g, ''))
    const ticker = (parts[0] ?? '').toUpperCase()
    const numbers = parts.slice(1).filter((p) => /^-?\d+(\.\d+)?$/.test(p)).map(Number)
    const date = parts.slice(1).find((p) => /^\d{4}-\d{2}-\d{2}$/.test(p))
    if (!/^[A-Z][A-Z0-9.-]{0,7}$/.test(ticker) || numbers.length < 2 || numbers[0] <= 0 || numbers[1] <= 0) {
      skipped.push(line)
      continue
    }
    rows.push({ ticker, shares: numbers[0], entry_price: numbers[1], entry_date: date ?? today })
  }
  return { rows, skipped }
}

interface PositionsProps {
  holdings: DeskHolding[]
  error: string
  onSave: (rows: DeskHolding[]) => Promise<void>
}

interface AccountInputsProps {
  equity: number
  cash: number | null
  riskBudgetPct: number | null
  cashStatus: string
  onApply: (equity: number, cash: number | null, riskBudgetPct: number | null) => void
}

// The personal account figures the board is computed against: small equity
// and available-cash fields with an explicit Apply/confirm. Cash is
// session-memory only (never localStorage, never a URL). An empty cash field
// means unknown and keeps buys gated; an invalid figure is treated as unknown
// too, never fabricated; zero is a valid known figure. Invalid equity is
// refused so the board is never sized against a nonsense account. A risk
// budget is optional, explicitly confirmed, and kept only for this session.
const AccountInputs = ({ equity, cash, riskBudgetPct, cashStatus, onApply }: AccountInputsProps) => {
  const [equityDraft, setEquityDraft] = useState(String(equity))
  const [cashDraft, setCashDraft] = useState(cash === null ? '' : String(cash))
  const [riskDraft, setRiskDraft] = useState(riskBudgetPct === null ? '' : String(riskBudgetPct))
  const [error, setError] = useState('')
  useEffect(() => setEquityDraft(String(equity)), [equity])
  useEffect(() => setCashDraft(cash === null ? '' : String(cash)), [cash])
  useEffect(() => setRiskDraft(riskBudgetPct === null ? '' : String(riskBudgetPct)), [riskBudgetPct])
  // Validate the drafts before applying a new personal account context.
  const apply = () => {
    const equityValue = Number(equityDraft)
    if (equityDraft.trim() === '' || !Number.isFinite(equityValue) || equityValue <= 0) {
      setError('Enter a positive account equity to size the board.')
      return
    }
    const riskValue = riskDraft.trim() === '' ? null : Number(riskDraft)
    if (riskValue !== null && (!Number.isFinite(riskValue) || riskValue <= 0 || riskValue > 100)) {
      setError('Risk per position must be greater than 0 and no more than 100%, or blank to leave it unset.')
      return
    }
    // An invalid cash figure (negative, non-finite, or beyond equity) still
    // applies the account as "unknown" - buys stay gated - but the reason is
    // left on the page so the person can see why their figure was not kept.
    let cashError = ''
    let cashValue: number | null = null
    if (cashDraft.trim() !== '') {
      const parsed = Number(cashDraft)
      if (!Number.isFinite(parsed) || parsed < 0) {
        cashError = 'That cash figure is not a finite, nonnegative number. Available cash is now unknown and buys stay unfunded.'
      } else if (parsed > equityValue) {
        cashError = 'Available cash cannot exceed account equity. Available cash is now unknown and buys stay unfunded.'
      } else {
        cashValue = parsed
      }
    }
    setError(cashError)
    // An unknown cash result leaves the field empty so the page does not keep
    // showing the figure that was just refused: clearing the draft here is
    // what actually resets it, because applying null over an already-null cash
    // bails out of the state update and never re-runs the sync effect below.
    if (cashValue === null) setCashDraft('')
    onApply(equityValue, cashValue, riskValue)
  }
  const field = 'rounded-md border border-black/[0.12] px-2 py-1 w-28'
  return (
    <div className="mb-3 flex flex-wrap items-center gap-2 rounded-xl bg-[#f5f5f7] p-3 text-sm">
      <label className="flex items-center gap-1 text-[#6e6e73]">
        Planning equity $
        <input aria-label="Personal account equity" type="number" min="0" step="any"
          value={equityDraft} onChange={(e) => setEquityDraft(e.target.value)} className={field} />
      </label>
      <label className="flex items-center gap-1 text-[#6e6e73]">
        Cash $
        <input aria-label="Personal available cash" type="number" min="0" step="any"
          value={cashDraft} placeholder="unknown" onChange={(e) => setCashDraft(e.target.value)} className={field} />
      </label>
      <label className="flex items-center gap-1 text-[#6e6e73]" title="Optional percentage of account equity at risk at the support reference, including the existing holding. It is not a guaranteed maximum loss.">
        Risk per position %
        <input aria-label="Risk per position (%)" type="number" min="0" max="100" step="any"
          value={riskDraft} placeholder="optional" onChange={(e) => setRiskDraft(e.target.value)} className={field} />
      </label>
      <button type="button" onClick={apply} className="rounded-full bg-[#1d1d1f] px-3 py-1 text-white">
        Apply
      </button>
      {error ? <p role="alert" className="text-xs text-[#b42318]">{error}</p> : cashStatus
        ? <p className="text-xs text-[#6e6e73]" aria-label="Available cash status">{cashStatus}</p>
        : <p className="text-xs text-[#6e6e73]">Cash unknown; buys stay unfunded until you confirm it.</p>}
      <p className="w-full text-[11px] text-[#6e6e73]">Planning equity is a browser input for sizing, not a broker-verified balance. The initial $100,000 is only a placeholder until you replace it.</p>
    </div>
  )
}

// The person's positions: a row each, or pasted in bulk, then saved.
const Positions = ({ holdings, error, onSave }: PositionsProps) => {
  const [draft, setDraft] = useState<DeskHolding[]>(holdings)
  const [pasted, setPasted] = useState('')
  const [skipped, setSkipped] = useState<string[]>([])
  useEffect(() => setDraft(holdings), [holdings])
  const update = (i: number, key: keyof DeskHolding, value: string) =>
    setDraft(draft.map((h, j) => (j === i ? { ...h, [key]: key === 'ticker' || key === 'entry_date' ? value : Number(value) } : h)))
  const field = 'rounded-md border border-black/[0.12] px-2 py-1'
  return (
    <div className="mb-3 space-y-2 rounded-xl bg-[#f5f5f7] p-3 text-sm">
      {draft.map((h, i) => (
        <div key={i} className="flex flex-wrap items-center gap-2">
          <input value={h.ticker} onChange={(e) => update(i, 'ticker', e.target.value)} placeholder="ticker" className={`w-20 ${field}`} />
          <input type="number" value={h.shares} onChange={(e) => update(i, 'shares', e.target.value)} placeholder="shares" className={`w-24 ${field}`} />
          <input type="number" value={h.entry_price} onChange={(e) => update(i, 'entry_price', e.target.value)} placeholder="cost per share" className={`w-32 ${field}`} />
          <input type="date" value={h.entry_date} onChange={(e) => update(i, 'entry_date', e.target.value)} className={field} />
          <button type="button" onClick={() => setDraft(draft.filter((_, j) => j !== i))} className="text-xs text-[#b42318] hover:underline">
            remove
          </button>
        </div>
      ))}
      <textarea
        value={pasted}
        onChange={(e) => setPasted(e.target.value)}
        placeholder={'paste one line per position: ticker, shares, cost per share, date bought (optional)\nIREN 100 35.20 2026-08-28'}
        rows={2}
        className={`w-full font-mono text-xs ${field}`}
      />
      {skipped.length > 0 && <p className="text-xs text-[#b42318]">could not read these lines: {skipped.join(' | ')}</p>}
      {error && <p className="text-xs text-[#b42318]">{error}</p>}
      <div className="flex flex-wrap items-center gap-4 text-xs">
        <button
          type="button"
          onClick={() => {
            const parsed = parsePasted(pasted)
            const kept = draft.filter((h) => !parsed.rows.some((r) => r.ticker === h.ticker.toUpperCase()))
            setDraft([...kept, ...parsed.rows])
            setSkipped(parsed.skipped)
            if (parsed.rows.length > 0) setPasted('')
          }}
          className="text-[#0071e3] hover:underline"
        >
          add pasted lines
        </button>
        <button
          type="button"
          onClick={() => setDraft([...draft, { ticker: '', shares: 0, entry_price: 0, entry_date: new Date().toISOString().slice(0, 10) }])}
          className="text-[#0071e3] hover:underline"
        >
          add a row
        </button>
        <button type="button" onClick={() => void onSave(draft)} className="rounded-full bg-[#1d1d1f] px-3 py-1 text-white">
          save
        </button>
      </div>
    </div>
  )
}

// Keep a tiny positive allocation visibly distinct from an explicit zero.
const allocationPercent = (weight: number) => weight > 0 && weight < 0.001
  ? '<0.1%' : `${(100 * weight).toFixed(1)}%`

// Withhold actions whose price, decision or account context no longer matches the page.
// A quote guard is real-time information, and the board was printing it as
// a refusal. "Wait · Spread exceeds 25 bp" tells a trader nothing they can
// act on; the same fact, said as what to do about it, does. The backend's
// own wording stays in the tooltip, because it is what the guard is called.
const actOnIt = (reason?: string | null): string | null => {
  if (!reason) return null
  if (/unverified/i.test(reason)) return 'Only one venue is quoting here, so the spread is unknown; check your broker before crossing'
  if (/spread exceeds/i.test(reason)) return 'Spread exceeds the execution limit'
  if (/market closed/i.test(reason)) return 'Market closed; no executable quote until the open'
  if (/invalid or empty|unavailable/i.test(reason)) return 'Quote unavailable; execution blocked'
  if (/refresh price evidence/i.test(reason)) return 'Price evidence has expired; reload for a current quote'
  return reason
}

// The plan as the column shows it. The filter and the cell beneath it have to
// agree, so both read this rather than each deciding for itself.
//
// This does NOT reduce a Buy or a Sell to a Hold because the price evidence
// has expired, and that is the whole point of it. The backend stopped doing
// exactly that in c2b0735e - "a closed market is not an opinion about a
// stock" - because a stale quote is a fact about EXECUTION, not a change of
// view about the name, and the page is read outside market hours more often
// than inside them. The page then re-imposed it here, one layer up: with the
// market closed there is no quote deadline at all, every row's `valid_until`
// comes back null, and all ninety-three actions were overwritten to Hold.
// The desk's three Sells were invisible every evening and all weekend.
//
// The reason already carries the annotation - the backend appends "(quote
// unavailable)" or "(no current price reading)" itself - so the row says what
// is in the way without pretending the desk has no view.
//
// Whether a decision is readable at all used to depend on the operator's
// recorded positions: the board was only accepted if his holdings file and
// his account value matched the ones it had been built from, so recording
// nothing - or recording anything slightly out of date - dropped all
// ninety-three rows to Hold at once. The board is a statement about the
// desk's own book and reads neither, so the only question left is whether
// the decision belongs to the record on screen.
const planFor = (
  ticker: string,
  decisions: DeskDecisions | undefined,
  latest: DeskRecord,
  now: number,
): {row?: DeskDecisions['rows'][string]; action: PlanAction; reason: string; blocked: boolean; blocker: string | null} => {
  const current = decisions && decisions.session === latest.session && decisions.written === latest.written
  const row = current ? decisions.rows[ticker] : undefined
  // No readable decision, so there is nothing to do: Hold, and say why on
  // hover. "Wait" was a fourth action pretending the page knew something.
  if (!row) return {action: 'Hold', reason: 'No current decision for this account. Refresh to re-read it.', blocked: false, blocker: null}
  const intent = row.strategy_action ?? row.action
  if (!PLAN_ACTIONS.includes(intent as PlanAction)) return {action: 'Hold', reason: 'Unrecognized decision; refresh before acting.', blocked: false, blocker: null}
  const deadline = row.valid_until ? Date.parse(row.valid_until) : Number.NaN
  const deadlineMissing = !Number.isFinite(deadline)
  const expired = !deadlineMissing && deadline <= now
  const blocked = intent !== 'Hold' && (row.executable === false || deadlineMissing || expired)
  const blocker = !blocked ? null
    : row.executable === false ? row.blocker ?? 'execution evidence is unavailable'
    : deadlineMissing ? 'current price evidence is unavailable'
    : 'price evidence has expired'
  return {
    row,
    action: intent as PlanAction,
    reason: row.reason,
    blocked,
    blocker,
  }
}

// Show the recommendation and separately identify whether it can currently be acted on.
const DecisionCell = ({ticker, decisions, latest, now, compact = false, terse = false}: {
  ticker: string; decisions?: DeskDecisions; latest: DeskRecord; now: number
  compact?: boolean; terse?: boolean
}) => {
  const {row, action, reason, blocked, blocker} = planFor(ticker, decisions, latest, now)
  if (!row) return <span title={reason} className="text-[#6e6e73]" aria-label={`${ticker} strategy intent`}>Hold</span>
  const expired = !!row.valid_until && Number.isFinite(Date.parse(row.valid_until)) && Date.parse(row.valid_until) <= now
  const executionStatus = blocked ? <span className="block font-normal text-[#b42318]">Blocked now{blocker ? ` · ${blocker}` : ''}</span> : null
  if (compact) {
    // Inside a trade row the badge above already carries the action, so this
    // line adds only the count when there is something to trade.
    if (action === 'Hold') return <span title={actOnIt(reason) ?? reason} aria-label={`${ticker} strategy intent`}>Hold</span>
    // "Sell 1.9%" beside a Target column reading 0.8% reads as a
    // contradiction. A sell is always the whole position, so it says so, and
    // a buy carries a + because it is an addition rather than a level.
    return <span title={actOnIt(blocker ?? reason) ?? blocker ?? reason} aria-label={`${ticker} strategy intent`}>{action.toUpperCase()}{executionStatus}</span>
  }
  // A Plan column is a signal, not a sentence. The allocation has its own
  // column and the reasoning is a hover: a trader scanning ninety-four rows
  // reads the word, and asks why only for the one row he stops on.
  return <div className="min-w-24" aria-label={`${ticker} strategy intent`} title={actOnIt(blocker ?? reason) ?? blocker ?? reason}>
    <div className="font-medium">{action.toUpperCase()}</div>
    {executionStatus}
    {terse && !blocked && <p aria-label={`${ticker} decision reason`} className="text-xs font-normal text-[#6e6e73]">{action === 'Hold' && row.entry_status === 'unavailable' ? row.entry_reason ?? 'Entry data unavailable' : reason}</p>}
    {!terse && <details className="mt-1 text-[#6e6e73]"><summary className="cursor-pointer">Recorded allocation & execution quote</summary>
      <div>Recorded personal allocation {allocationPercent(row.current_weight)} · strategy target {allocationPercent(row.target_weight)} at the next reset</div>
      {row.quote ? <>
        <div>{row.quote.feed?.toUpperCase() ?? 'No feed'} · {row.quote.bid && row.quote.ask ? `${priceMoney(row.quote.bid)} bid / ${priceMoney(row.quote.ask)} ask` : 'quote unavailable'}</div>
        <div>{row.quote.at ? executionTime(row.quote.at) : 'No quote time'}{expired ? ' · expired' : ''}</div>
        <div>{actOnIt(row.quote.reason) ?? row.quote.reason}{row.quote.spread_bps !== undefined && ` · ${row.quote.spread_bps.toFixed(1)} bp spread`}</div>
      </> : <div>Quote unavailable for this record.</div>}
      {row.valid_until && <div>Expires {executionTime(row.valid_until)}</div>}
    </details>}
  </div>
}

// Explain the single board's ranking, sizing and evidence clocks without repeating its stocks.
const DeskGuide = ({latest, open}: {latest: DeskRecord; open: boolean}) => {
  return (
    <section aria-label="Desk guide" className="rounded-xl border border-black/[0.08] bg-white p-3 text-xs text-[#6e6e73]">
      <details open={open}>
        <summary className="cursor-pointer font-medium">Desk guide · ranking and timing</summary>
      <details className="mt-3">
        <summary className="cursor-pointer text-[#0071e3]">How ranking and sizing work</summary>
        <p className="mt-2">{TRIGGER_LEGEND} Numbers beside these letters are rounded cross-sectional percentiles, not individual letter grades or probabilities of profit. A+/A/B/C is the combined grade. The default stock order puts positive displayed allocations first, largest to smallest, then grade, opportunity and conviction. Column headings can change the order. Intraday inputs update where available; other votes and theses remain from the evening decision.</p>
        <p className="mt-2">Current voting rules: growth &amp; margins, price trend, earnings-release tone and relative valuation each carry one vote;
          rotation carries half a vote. A bearish core analyst caps the grade at B.
          Position sizes also depend on volatility, grade multipliers, concentration limits and market exposure.</p>
        <p className="mt-2">{latest.provenance?.rule?.inputs?.includes('expectations-gap')
          ? 'This evening decision includes the LightGBM expectations gap: model-estimated revenue growth minus a relative-P/S valuation proxy, blended with relative valuation.'
          : latest.provenance?.rule?.inputs
            ? 'This evening decision does not include the LightGBM expectations gap.'
            : 'This record does not identify whether the LightGBM expectations gap was used.'}
          {' '}This is not a forecast of a future share price. Intraday updates do not retrain the learner or refresh company filings.</p>
        {latest.provenance?.rule?.inputs?.includes('expectations-gap') && <p className="mt-2">
          The proxy uses quarterly revenue × 4, not trailing-twelve-month revenue. It is a transformation of relative price/sales, not a measured market growth expectation or intrinsic fair value.</p>}
        {latest.provenance?.rule?.inputs?.includes('expectations-gap') && <p className="mt-2">
          Valuation stays at the evening reading: the intraday reader does not yet reproduce the growth-model blend.
          Only eligible technical readings refresh this decision's intraday grades.</p>}
        <p className="mt-2">Research target is an experimental percentage of total portfolio value, recalculated from completed 15-minute bars. A dash means sizing is unavailable or paused; 0% is an explicit zero target. These targets do not submit orders or confirm an entry.
          Record buy saves a purchase you already executed, including discretionary purchases outside the desk schedule.</p>
      </details>
      <details aria-label="Reading the current picks" className="mt-3">
        <summary className="cursor-pointer">Data & timing · bar prices and quote checks</summary>
        <p className="mt-1">A+ is the highest grade under the current voting rules, not a probability of profit.
          Intraday grades update technical and eligible price-sensitive value inputs; other votes and strategy target weights use the evening decision.
          Prices, available cash and execution conditions can change before an order fills.</p>
        <p className="mt-2">Intraday calculations are scheduled every 15 minutes on weekdays during market hours.
          This page checks for updates every minute. A scheduled run may be late or missing; expired intraday grades revert to the evening decision.
          Bar times identify the start of the 15-minute interval, not a current executable price.</p>
      </details>
      </details>
    </section>
  )
}

// Keep historical model interpretations accessible without presenting them as verified strategy rules.
const ArchivedCommentary = ({brief, read, written}: {brief?: DeskBrief; read?: string | null; written: string}) => (
  <details className="mt-2 rounded border border-black/[0.08] p-2 text-xs">
    <summary className="cursor-pointer text-[#0071e3]">Archived model commentary · unverified</summary>
    <p className="my-2 text-[#6e6e73]">Record written {marketTime(written)}. This saved interpretation can contain errors,
      including claims about sizing or grade changes. It does not calculate the displayed grade or allocation.</p>
    {read && <p className="mb-2 whitespace-pre-line">{read}</p>}
    {brief && <div className="space-y-1">
      <p>{brief.verdict}</p>
      <p>{looksLikeRawDump(brief.reasoning) ? '' : brief.reasoning}</p>
      <p><span className="font-medium">Model's risks:</span> {brief.risks}</p>
      <p><span className="font-medium">Model's watch points:</span> {brief.watch}</p>
    </div>}
  </details>
)

// Save only a user-confirmed brokerage purchase; viewing or cancelling the form never writes positions.
const ConfirmedBuy = ({ticker, disabled, onSave, error}: {
  ticker: string
  disabled: boolean
  onSave: (ticker: string, price: number, qty: number, fillDate: string) => Promise<boolean>
  error: string
}) => {
  const [open, setOpen] = useState(false)
  const [shares, setShares] = useState('')
  const [price, setPrice] = useState('')
  const [date, setDate] = useState(today)
  return <>
    <button type="button" disabled={disabled} className="mt-1 text-[#0071e3] disabled:text-[#6e6e73]"
      onClick={() => setOpen(!open)}>{open ? 'Cancel buy record' : 'Record buy'}</button>
    {open && <form aria-label={`Record ${ticker} buy`} className="mt-2 space-y-2" onSubmit={async event => {
      event.preventDefault()
      if (disabled) return
      if (await onSave(ticker, Number(price), Number(shares), date)) {
        setOpen(false)
        setShares('')
        setPrice('')
      }
    }}>
      <p>After your brokerage confirms the fill. This updates your manual tracker; it does not place an order or sync your brokerage.</p>
      <label className="block">Filled shares<input aria-label="Filled shares" type="number" min="0.000001" step="any" required
        className="block w-28 rounded border p-1" value={shares} onChange={event => setShares(event.target.value)} /></label>
      <label className="block">Average fill price ($)<input aria-label="Average fill price" type="number" min="0.000001" step="any" required
        className="block w-28 rounded border p-1" value={price} onChange={event => setPrice(event.target.value)} /></label>
      <label className="block">Fill date<input aria-label="Fill date" type="date" required max={today()}
        className="block rounded border p-1" value={date} onChange={event => setDate(event.target.value)} /></label>
      {error && <p role="alert" className="text-[#b42318]">{error}</p>}
      <button type="submit" disabled={disabled} className="text-[#0071e3] disabled:text-[#6e6e73]">{disabled ? 'Saving…' : 'Save confirmed buy'}</button>
    </form>}
  </>
}

// Explain observed vote changes without treating a missing reading as neutral.
const VoteChanges = ({ evening, current }: { evening: Record<string, number>; current: Record<string, number> }) => {
  const words: Record<number, string> = { 1: 'for', 0: 'no view', [-1]: 'against' }
  const changes = TRIGGER_ORDER.filter(([key]) => key in evening && key in current && evening[key] !== current[key])
  if (!changes.length) return null
  return (
    <p className="mb-1 text-[#1d1d1f]">
      Since evening: {changes.map(([key, letter]) => `${letter} ${words[evening[key]]} → ${words[current[key]]}`).join('; ')}.
    </p>
  )
}

// Render the available analyst votes in the desk's fixed order.
const triggers = (stances: Record<string, number>) =>
  TRIGGER_ORDER.filter(([k]) => k in stances)
    .map(([k, letter]) => `${letter}${STANCE_MARK[stances[k] ?? 0]}`)
    .join(' ')

// The option walls read off the stored chain at the live price, with the
// put and call walls as distances from it (negative below, positive above).
type DeskWalls = {
  expiry: string | null
  through?: string | null
  fetched_at?: string | null
  put_wall: number | null
  call_wall: number | null
  put_wall_oi: number
  call_wall_oi: number
  net_gamma: number
  put_wall_distance?: number
  call_wall_distance?: number
}

// The live technical read for one name, split by how far ahead each fact
// looks. Short term is where price is this candle; medium term is the daily
// timeframes; long term is the weekly and 52-week picture. Every number is
// a real feature the analyst's playbook was measured on, given a plain word
// beside it rather than left to stand alone.
const LiveTechnical = ({
  userId,
  ticker,
  detail,
  quote,
  row,
}: {
  userId: string
  ticker: string
  detail:
    | {
        now: number | null
        short: Record<string, number>
        medium: Record<string, number>
        long: Record<string, number>
        walls?: DeskWalls
      }
    | undefined
  quote: DeskQuote | undefined
  row: DeskMineRow | null
}) => {
  // The live read is the model's plain words over the analyst's live
  // readings, fetched once per name per candle. The fetch is keyed on the
  // candle's bar — the same identifier the backend's per-candle cache uses
  // — so a new bar re-reads the analysis, and an unchanged bar never does.
  // A name outside the candle's snapshot has no bar and reads once on open,
  // because there is no candle to refresh against. Until the read arrives,
  // and whenever the model is away, the same readings render as the
  // deterministic lines the backend returns beside it.
  const [liveRead, setLiveRead] = useState<DeskLiveRead | null>(null)
  const [readUnavailable, setReadUnavailable] = useState(false)
  const bar = quote?.bar ?? ''
  useEffect(() => {
    let alive = true
    setLiveRead(null)
    setReadUnavailable(false)
    void getDeskLiveRead(userId, ticker)
      .then((r) => { if (alive) { setLiveRead(r); setReadUnavailable(r === null) } })
      .catch(() => { if (alive) { setLiveRead(null); setReadUnavailable(true) } })
    return () => {
      alive = false
    }
  }, [userId, ticker, bar])
  const last = quote?.last ?? row?.last ?? null
  const change = last != null && row?.last_close ? last - row.last_close : null
  const changePct = last != null && row?.last_close ? last / row.last_close - 1 : null
  const lines = (items: string[] | undefined) => (items ?? []).filter((i): i is string => i.length > 0)
  const read = liveRead?.read
  const fl = liveRead?.lines
  const tech = liveRead?.now ?? detail?.now ?? null
  const readAt = liveRead?.read_at ?? null
  const column = (title: string, items: string[] | undefined) => (
    <div>
      <p className="text-xs font-medium text-[#1d1d1f]">{title}</p>
      <ul className="mt-1 space-y-1 text-xs text-[#6e6e73]">
        {lines(items).map((t) => (
          <li key={t}>· {t}</li>
        ))}
        {lines(items).length === 0 && <li>no readings yet</li>}
      </ul>
    </div>
  )
  return (
    <section className="rounded-xl border border-black/[0.08] bg-white p-3">
      <div className="mb-2 flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
        <h4 className="text-sm font-semibold text-[#1d1d1f]">
          Technical read
          {(liveRead?.data_at || readAt) && (
            <span className="ml-2 text-xs font-normal text-[#6e6e73]">
              candle from {marketTime(liveRead?.data_at)} (15-minute interval start)
              {liveRead?.stale || Date.now() - Date.parse(liveRead?.data_at ?? '') >= 30 * 60 * 1000 ? ' · last known data' : ''}
              {readAt ? ` · explanation generated ${marketTime(readAt)}` : ''}
            </span>
          )}
        </h4>
        <span className="text-xs text-[#6e6e73]">
          {last != null && priceMoney(last)}
          {change != null && changePct != null && (
            <span className="ml-1">
              <TrendUsd value={change} />
              <span className="ml-1">(<Trend value={changePct * 100} />)</span>
            </span>
          )}
        </span>
      </div>
      <p className="mb-2 text-xs text-[#6e6e73]">Price basis: {quote?.bar ? `IEX bar starting ${marketTime(quote.bar)}` : 'evening close; no intraday quote available'}.
        {change != null ? ' Change is measured from the stored evening close.' : ''} Commentary interprets the dated evidence; it is not a verified forecast.</p>
      {/* The model's plain words lead, and the short/medium/long readings
          sit beside them: the prose says what it means, the columns say the
          numbers behind it. */}
      {fl ? (
        <>
          {read && <p className="whitespace-pre-line text-sm leading-relaxed text-[#1d1d1f]">{read}</p>}
          {/* The readings behind the prose, folded: the paragraph and the
              evening analysis already carry them in words. */}
          <details className="mt-2">
            <summary className="cursor-pointer text-xs text-[#0071e3]">All readings, by timeframe</summary>
            <div className="mt-2 grid gap-3 sm:grid-cols-3">
              {column('Daily chart', fl.short)}
              {column('Weekly chart', fl.medium)}
              {column('Longer-term reference levels', fl.long)}
            </div>
          </details>
        </>
      ) : read ? (
        <p className="whitespace-pre-line text-sm leading-relaxed text-[#1d1d1f]">{read}</p>
      ) : (
        <p className="text-xs text-[#6e6e73]">{readUnavailable ? 'Technical read unavailable. Try Refresh.' : 'Reading the available price data…'}</p>
      )}
      {tech != null && (
        <p className="mt-2 text-xs text-[#1d1d1f]">
          Technical rank at the available candle:{' '}
          <span className="font-medium">{(tech * 100).toFixed(0)}</span> out of 100. Higher means a higher technical score among covered names with data.
        </p>
      )}
      {detail?.walls && (detail.walls.put_wall != null || detail.walls.call_wall != null) && (
        <p className="mt-2 text-xs text-[#6e6e73]">
          Option walls{detail.walls.expiry ? ` (expiries ${detail.walls.expiry.slice(5)}${detail.walls.through && detail.walls.through !== detail.walls.expiry ? ` to ${detail.walls.through.slice(5)}` : ''}` : ''}{detail.walls.fetched_at ? `${detail.walls.expiry ? ', ' : ' ('}open interest fetched ${marketTime(detail.walls.fetched_at)} ET)` : detail.walls.expiry ? ')' : ''}:{' '}
          {detail.walls.put_wall != null ? (
            <>
              put{' '}
              <span className="text-[#1d1d1f]">
                {priceMoney(detail.walls.put_wall)}
                {detail.walls.put_wall_distance != null && (
                  <span className="ml-1">(<Trend value={detail.walls.put_wall_distance * 100} /> below)</span>
                )}
              </span>
            </>
          ) : (
            'no put wall in range'
          )}{' '}
          ·{' '}
          {detail.walls.call_wall != null ? (
            <>
              call{' '}
              <span className="text-[#1d1d1f]">
                {priceMoney(detail.walls.call_wall)}
                {detail.walls.call_wall_distance != null && (
                  <span className="ml-1">(<Trend value={detail.walls.call_wall_distance * 100} /> above)</span>
                )}
              </span>
            </>
          ) : (
            'no call wall in range'
          )}
        </p>
      )}
    </section>
  )
}

// The sessions where the grade moved, with the analysts whose stance
// changed and how: "technical turned against", "value no longer for".
const STANCE_WORD: Record<number, string> = { 1: 'for', 0: 'neutral', [-1]: 'against' }
// The grade one vote down from each grade.
const GRADE_BELOW: Record<string, string> = { 'A+': 'A', A: 'B', B: 'C' }
const gradeChanges = (rows: DeskHistoryRow[]) => {
  const out: { date: string; from: string; to: string; moved: string[]; said?: boolean }[] = []
  for (let i = 1; i < rows.length; i += 1) {
    const prev = rows[i - 1]
    const row = rows[i]
    if (row.grade === prev.grade) continue
    const moved: string[] = []
    for (const [analyst, now] of Object.entries(row.stances ?? {})) {
      const before = prev.stances?.[analyst] ?? 0
      if (before !== now) moved.push(`${analyst} ${STANCE_WORD[before] ?? before} → ${STANCE_WORD[now] ?? now}`)
    }
    out.push({ date: row.date, from: prev.grade, to: row.grade, moved, said: row.said })
  }
  return out
}

// A stale brief dumps the desk's raw evidence ("revenue_yoy +0.262") in
// place of the plain words the prompt now demands. The shape — a field
// identifier followed by a signed decimal — is enough to hide it rather
// than trust the text.
const looksLikeRawDump = (text: string) =>
  /\b[a-zA-Z]+\d*_[a-zA-Z]+(?:_[a-zA-Z]+)*\b\s*[+-]?\d+(?:\.\d+)?/.test(text)

// Format stored dollar figures without losing a loss sign or rounding millions to whole units.
const earningsDollars = (value: number | null, suffix = '') =>
  value == null ? null : `${value < 0 ? '−' : ''}$${Math.abs(value).toLocaleString('en-US', { maximumFractionDigits: 6, minimumFractionDigits: suffix ? 0 : 2 })}${suffix}`

// Date-only evidence retains its full day and year without a UTC timezone shift.
const evidenceDate = (value: string) =>
  new Date(`${value}T00:00:00`).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })

// Present the stored extraction's timing, meaning and known limitations beside its figures.
const EarningsRead = ({ read }: { read: NonNullable<DeskEarnings['read']> }) => {
  // Zero combines neutral and unstated evidence in the stored schema.
  const tone = (value: number) => (value > 0 ? 'positive' : value < 0 ? 'negative' : 'neutral or not stated')
  const dims = ['guidance', 'demand', 'pricing', 'capex'] as const
  // v2 has confirmed positive-as-loss defects; only the corrected reader is qualified here.
  const signedFinancials = read.prompt_version === 'release_tone/3'
  const facts = [
    ['Revenue', earningsDollars(read.revenue_usd_m, 'M')],
    ['EPS', earningsDollars(read.eps_usd)],
    ['Net income', earningsDollars(read.net_income_usd_m, 'M')],
    ['Gross margin', read.gross_margin_pct != null ? `${read.gross_margin_pct.toFixed(1)}%` : null],
    [
      'Quarter',
      read.quarter_end
        ? `ending ${evidenceDate(read.quarter_end)}`
        : null,
    ],
  ].filter(([, v]) => v != null) as [string, string][]
  return (
    <div className="mt-3 rounded-xl border border-black/[0.08] bg-white p-3">
      <div className="flex flex-wrap items-center justify-between gap-x-2">
        <h4 className="text-sm font-semibold text-[#1d1d1f]">Latest stored earnings read</h4>
        <span className="text-xs text-[#6e6e73]">
          Market reaction on or after {evidenceDate(read.reaction_date)}
        </span>
      </div>
      <p className="mt-1 text-xs text-[#6e6e73]">Model-extracted outlook tone; positive capex means increased spending. These are not analyst estimate comparisons.</p>
      <p className="mt-1 text-sm text-[#1d1d1f]">{dims.map(k => `${k} ${tone(read[k])}`).join(' · ')}</p>
      {read.summary && <p className="mt-1 text-sm leading-relaxed text-[#1d1d1f]">{read.summary}</p>}
      {signedFinancials && facts.length > 0 && (
        <p className="mt-1 text-xs text-[#6e6e73]">{facts.map(([k, v]) => `${k} ${v}`).join(' · ')}</p>
      )}
      {!signedFinancials && <p className="mt-1 text-xs text-amber-800">Financial figures withheld: this older extraction may misreport losses.</p>}
      <p className="mt-1 text-xs text-[#6e6e73]">Reader {read.prompt_version || 'unknown'}. A new read does not confirm that the displayed grade includes it.</p>
    </div>
  )
}

// Refresh stored earnings while open and make absence, loading and retryable failures explicit.
const EarningsPanel = ({ userId, ticker }: { userId: string; ticker: string }) => {
  const [earnings, setEarnings] = useState<DeskEarnings | null>(null)
  const [failed, setFailed] = useState(false)
  const [attempt, setAttempt] = useState(0)
  useEffect(() => {
    let alive = true
    // Clear previous evidence until this request establishes the current stored state.
    const load = async () => {
      setEarnings(null)
      setFailed(false)
      try {
        const result = await getDeskEarnings(userId, ticker)
        if (alive) setEarnings(result)
      } catch {
        if (alive) setFailed(true)
      }
    }
    void load()
    const timer = window.setInterval(() => { void load() }, 15 * 60 * 1000)
    return () => { alive = false; window.clearInterval(timer) }
  }, [userId, ticker, attempt])
  return (
    <section aria-label="Earnings evidence" className="mt-3">
      {earnings?.read && <EarningsRead read={earnings.read} />}
      {!earnings?.read && <p role="status" className="text-xs text-[#6e6e73]">
        {failed ? 'Earnings read unavailable.' : earnings ? 'No earnings read stored for this name.' : 'Loading earnings read…'}
      </p>}
      <button type="button" onClick={() => setAttempt(value => value + 1)} className="mt-1 text-xs text-[#0b5cad] underline">
        {failed ? 'Retry earnings' : 'Refresh earnings'}
      </button>
    </section>
  )
}

// Show recorded grade and vote changes without inventing a cause or treating current readings as prior inputs.
const GradeMove = ({changes, session, reads, revision}: {
  changes: {date: string; from: string; to: string; moved: string[]; said?: boolean}[]
  session: string
  reads?: Record<string, string[]>
  revision?: NonNullable<DeskPayload['latest']>['grades'][string]['revision']
}) => {
  const latest = changes[0]
  // A re-read of the same release is named even when the grade did not
  // move: the vote it feeds may move on the next sessions.
  const revised = revision ? `Recorded re-read marker: market reaction on or after ${revision.reaction_date}${revision.prompt_version[1] ? `; reader ${revision.prompt_version[1]}` : ''}${Object.keys(revision.fields).length ? `: ${Object.entries(revision.fields).map(([field, [from, to]]) => `${field.replace('_', ' ')} ${from ?? '—'} → ${to ?? '—'}`).join(' · ')}` : ''}. This is not the publication date or re-read time. A vote can move on a re-read without a new release.` : null
  if (!latest) return revised ? <section aria-label="Why the grade moved" className="mb-4 rounded-xl border border-black/[0.08] bg-white p-3 text-sm"><p className="text-[11px] text-[#9a6200]">{revised}</p></section> : null
  const tonight = latest.date === session
  const moved = latest.moved.map((text) => {
    const analyst = text.split(' ')[0]
    const readings = tonight ? (reads?.[analyst] ?? []).slice(0, 2) : []
    return {text: `${analystLabel(analyst)}${text.slice(analyst.length)}`, readings}
  })
  const flipped = latest.moved.some((text) => / (for|against)$/.test(text))
  return (
    <section aria-label="Why the grade moved" className="mb-4 rounded-xl border border-black/[0.08] bg-white p-3 text-sm">
      <p>
        <span className="font-semibold">{tonight ? 'Moved in tonight\u2019s decision' : `Last moved ${shortDate(latest.date)}`}:</span>{' '}
        <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${GRADE_STYLE[latest.from] ?? ''}`}>{latest.from}</span>
        <span className="mx-1 text-[#6e6e73]">→</span>
        <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${GRADE_STYLE[latest.to] ?? ''}`}>{latest.to}</span>
        {!tonight && <span className="ml-1 text-xs text-[#6e6e73]">· unchanged since then</span>}
      </p>
      {moved.length > 0 ? (
        <ul className="mt-1 space-y-0.5 text-xs">
          {moved.map((m) => <li key={m.text}>· {m.text.replace(/^(\w)/, (c) => c.toUpperCase())}{m.readings.length > 0 ? `: ${m.readings.join('; ')}` : ''}</li>)}
        </ul>
      ) : (
        <p className="mt-1 text-xs text-[#6e6e73]">No analyst vote change is recorded in this comparison; cause not recorded.</p>
      )}
      {moved.length > 0 && <p className="mt-1 text-[11px] text-[#6e6e73]">Recorded vote changes do not establish what caused a price move.</p>}
      {flipped && <p className="mt-1 text-[11px] text-[#6e6e73]">{EVENING_VOTE_CONTEXT}</p>}
      {revised && <p className="mt-1 text-[11px] text-[#9a6200]">{revised}</p>}
    </section>
  )
}

// Summarize exchange status, active restrictions and executable personal signals.
const TodayLine = ({exchange, event, boardEvent, orders, holdings, eligible}: {
  exchange: ReturnType<typeof exchangeState>
  event?: {decision_date: string | null} | null
  boardEvent: BoardEvent | null
  orders: number
  holdings: number | null
  eligible: number
}) => {
  const parts: string[] = [exchange.label]
  if (boardEvent && boardEvent.exposure !== null && boardEvent.exposure < 1) parts.push(`paper FOMC target exposure ${Math.round(boardEvent.exposure * 100)}% through the ${event?.decision_date ?? 'FOMC'} decision`)
  else if (boardEvent) parts.push(boardEvent.exposure === null
    ? 'paper FOMC target exposure unavailable'
    : orders > 0 ? `${orders} pending paper order${orders === 1 ? '' : 's'} during FOMC recovery`
      : 'paper FOMC cycle active')
  let action: string
  if (eligible > 0) action = `${eligible} executable signal${eligible === 1 ? '' : 's'}.`
  else if (holdings !== null && holdings === 0) action = 'Personal positions not recorded.'
  else action = exchange.known ? 'No executable signals.' : 'Exchange status unavailable.'
  return <section aria-label="Today" className="shrink-0 rounded-xl border border-black/[0.08] bg-white px-3 py-2 text-sm">
    <span className="font-medium">{parts.join(' · ')}.</span> <span className="text-[#6e6e73]">{action}</span>
  </section>
}

// Separate the latest accepted grade and personal decision from the dated evening evidence and history.
const NameDetail = ({
  userId,
  ticker,
  latest,
  row,
  live,
  liveGrades,
  onClose,
  compact = false,
  decisions,
  now = Date.now(),
  paused = false,
  holdings = null,
  equity = 0,
}: {
  userId: string
  ticker: string
  latest: NonNullable<DeskPayload['latest']>
  row: DeskMineRow | null
  live: DeskLive
  liveGrades: Record<string, DeskLiveGrade>
  onClose: () => void
  compact?: boolean
  decisions?: DeskDecisions
  now?: number
  paused?: boolean
  holdings?: DeskHolding[] | null
  equity?: number
}) => {
  const [history, setHistory] = useState<DeskHistory | null>(null)
  const [error, setError] = useState('')
  useEffect(() => {
    let alive = true
    void getDeskHistory(userId, ticker)
      .then((h) => alive && setHistory(h))
      .catch((err) => alive && setError(err instanceof Error ? err.message : 'no history'))
    return () => {
      alive = false
    }
  }, [userId, ticker])
  const brief = latest.briefs?.[ticker]
  const walls = (live.technical_detail?.[ticker] as {walls?: DeskWalls} | undefined)?.walls
  const gradeRead = latest.grades?.[ticker]?.read ?? null
  const gradeReads = latest.grades?.[ticker]?.reads
  const currentStances = row
    ? row.grade_source === 'intraday' ? row.stances_live ?? liveGrades[ticker]?.stances_live : undefined
    : liveGrades[ticker]?.stances_live
  const bt = history?.backtest
  const recent = history?.rows.slice(-12) ?? []
  // The sessions where the grade actually moved, newest first, each with
  // the analysts whose stance changed: a list of twelve identical rows says
  // nothing, and "what changed and who moved it" is the question a person
  // opens this panel with.
  const changes = gradeChanges(history?.rows ?? []).slice(-8).reverse()
  const cells = [
    // What the grade earned on this name: the days it was graded A or
    // better against the days it was not, both annualized from the mean of
    // the name's own daily returns on those days. The number is a
    // log-return annualization, not a compounded return, and it says
    // nothing about how the days were arranged.
    { label: 'Annualized mean while an A', value: bt?.in_annualised != null ? `${(bt.in_annualised * 100).toFixed(0)}% a year` : '—', note: 'mean of its daily log returns on days graded A or better, × 252' },
    { label: 'Annualized mean while not', value: bt?.out_annualised != null ? `${(bt.out_annualised * 100).toFixed(0)}% a year` : '—', note: 'mean of its daily log returns on days it was not an A, × 252' },
    { label: 'Sessions it was an A', value: bt ? `${bt.sessions_in} of ${bt.sessions}` : '—', note: 'of all sessions since the history starts' },
    { label: 'Position changes', value: bt ? `${bt.switches}` : '—', note: 'times the position size changed — grade moves and regime exposure — each paying the trade cost' },
  ]
  return (
    <div className="fixed inset-0 z-50 flex justify-end bg-black/25" onClick={onClose} role="dialog" aria-label={`${ticker} history`}>
      <div className="h-full w-full overflow-y-auto bg-[#f5f5f7] p-5 shadow-xl lg:w-[78vw] 2xl:w-[1600px]" onClick={(e) => e.stopPropagation()}>
        <div className="mb-3 flex items-center justify-between">
          <h3 className="text-lg font-semibold text-[#1d1d1f]">
            {ticker}
          </h3>
          <button type="button" onClick={onClose} aria-label="Close" className="flex h-8 w-8 items-center justify-center rounded-full border border-black/[0.1] text-[#6e6e73] hover:bg-white">
            <X size={16} />
          </button>
        </div>
        <div className="lg:flex lg:flex-row-reverse lg:items-start lg:gap-6">
        {/* The picture before the prose. A trader looks at the chart first,
            so it leads on a phone and holds the right two-fifths of a wide
            window, staying in place while the reasoning scrolls beside it. */}
        <div className="mb-4 lg:sticky lg:top-0 lg:w-[40vw] lg:max-w-[54rem] lg:shrink-0">
          <TickerChart key={ticker} userId={userId} ticker={ticker} history={history ?? undefined} quote={live.quotes[ticker]} tall />
        </div>
        <div className="lg:min-w-0 lg:flex-1">
        {history && <GradeMove changes={changes} session={latest.session} reads={gradeReads} revision={latest.grades?.[ticker]?.revision ?? null} />}
        <section aria-label="Latest available grade" className="mb-3 rounded-xl border border-black/[0.08] bg-white p-3 text-sm">
        <h4 className="mb-1 font-medium text-[#6e6e73]">Latest available grade</h4>
        {row && (
          <div className="mb-3 flex flex-wrap items-center gap-x-3 gap-y-1 text-sm">
            <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${GRADE_STYLE[row.grade_live] ?? ''}`}>
              <span aria-label="Latest grade value">{row.grade_live}</span>
              <span className="ml-1 font-normal text-[#6e6e73]">{row.grade_source === 'intraday' ? `intraday · ${row.grade} at the ${latest.session} close` : `at the ${latest.session} close`}</span>
            </span>
          </div>
        )}
        {!row && latest.grades?.[ticker] && (
          <div className="mb-3 flex flex-wrap items-center gap-x-3 gap-y-1 text-sm">
            {/* The list reads the live grade, so the detail must too: a
                name outside the board's rows would otherwise show the
                evening grade while the list beside it shows the candle's. */}
            <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${GRADE_STYLE[(liveGrades[ticker]?.grade_live ?? latest.grades[ticker].grade) as keyof typeof GRADE_STYLE] ?? ''}`}>
              <span aria-label="Latest grade value">{liveGrades[ticker]?.grade_live ?? latest.grades[ticker].grade}</span>
              <span className="ml-1 font-normal">{liveGrades[ticker] ? 'intraday grade' : `at the ${latest.session} close`}</span>
            </span>
          </div>
        )}
          <AnalystRatings ranks={row ? row.ranks_live ?? row.ranks : liveGrades[ticker]?.ranks_live ?? latest.grades?.[ticker]?.ranks}
            stances={(row ? row.stances_live ?? row.stances : liveGrades[ticker]?.stances_live ?? latest.grades?.[ticker]?.stances) ?? {}} session={latest.session} />
          {currentStances && <VoteChanges evening={latest.grades?.[ticker]?.stances ?? {}} current={currentStances} />}
          <div className="mt-2 text-xs text-[#6e6e73]">
            <DecisionCell terse ticker={ticker} decisions={decisions} latest={latest} now={now} />
          </div>
          <p className="mt-2 text-xs text-[#6e6e73]">
            {live.quotes[ticker]?.last != null ? `${priceMoney(live.quotes[ticker].last)} at the ${live.quotes[ticker].bar ? marketTime(live.quotes[ticker].bar) : 'last'} bar` : 'No live price'}
            {live.technical?.[ticker]?.now != null ? ` · technical rank ${Math.round((live.technical[ticker].now ?? 0) * 100)} of 100` : ''}
            {walls && (walls.put_wall != null || walls.call_wall != null) ? ` · option walls ${walls.put_wall != null ? priceMoney(walls.put_wall) : '—'} / ${walls.call_wall != null ? priceMoney(walls.call_wall) : '—'}` : ''}
          </p>
        </section>
        {/* Recorded reasons retain their original scope even when a newer grade or price is available. */}
        {latest.grades?.[ticker] && <section aria-label="In short" className="mb-3 rounded-xl border border-black/[0.08] bg-white p-3 text-sm">
          <EveningAnalysis grade={latest.grades[ticker]} session={latest.session} written={latest.written} fundamental={latest.fundamental} ticker={ticker} />
        </section>}
        <details aria-label="All the evidence" className="mb-3">
          <summary className="cursor-pointer text-xs text-[#0071e3]">All the evidence</summary>
        {/* Recorded descriptive readings, not a causal breakdown of the persisted votes. */}
        {gradeReads && (
          <div className="mt-3 rounded-xl border border-black/[0.08] bg-white p-3">
            <h4 className="text-sm font-semibold text-[#1d1d1f]">Evening analysis · {latest.session}</h4>
            {/* One block per analyst with the vote it cast, so fifty readings
                read as five arguments rather than one list. */}
            {Object.entries(gradeReads ?? {}).map(([analyst, lines]) => {
              const vote = latest.grades?.[ticker]?.stances?.[analyst]
              const mark = vote === 1 ? '+ for' : vote === -1 ? '− against' : vote === 0 ? '· neutral or unavailable' : 'vote missing or invalid'
              return (
                <div key={analyst} className="mt-2">
                  <p className="text-xs font-semibold text-[#1d1d1f]">{analystLabel(analyst)} <span className="font-normal text-[#6e6e73]">{mark}</span></p>
                  <ul className="mt-0.5 space-y-0.5 text-sm text-[#1d1d1f]">
                    {lines.map((line) => (
                      <li key={`${analyst}-${line}`}>· {line}</li>
                    ))}
                  </ul>
                </div>
              )
            })}
          </div>
        )}
        {(brief || gradeRead) && <ArchivedCommentary brief={brief ?? undefined} read={gradeRead} written={latest.written} />}
        {/* The live technical read renders for any covered name, even one
            the board does not carry: the backend computes it on demand from
            a fresh quote, so a name outside the candle's snapshot (not in
            the book, not held) still gets its short/medium/long read. */}
        <LiveTechnical
          userId={userId}
          ticker={ticker}
          detail={live.technical_detail?.[ticker]}
          quote={live.quotes[ticker]}
          row={row ?? null}
        />
        <EarningsPanel key={ticker} userId={userId} ticker={ticker} />
        </details>
        {/* Everything derived or historical sits under one fold: the
            continuous score, the fifteen-minute log, the grade changes and
            the backtest. A person opens the panel to ask why, not to scroll. */}
        <details open={!compact} aria-label="Score, log and backtest">
          <summary className="cursor-pointer text-xs text-[#0071e3]">Score, log & backtest</summary>
          <div className="mt-3">
          <OpportunityCard reading={decisions?.session === latest.session ? decisions.rows[ticker]?.opportunity : undefined} now={now} />
          {history && <RecommendationTimeline history={history.recommendations} />}
          {!history && !error && <p className="mb-3 text-xs">Loading recommendations…</p>}
          {error && <p role="alert" className="mb-3 text-xs text-[#b42318]">{error}</p>}
          {error ? (
            <p className="text-sm text-[#6e6e73]">{error}. The nightly run writes this after the next close.</p>
          ) : !history ? (
            <p className="text-sm text-[#6e6e73]">Loading the history…</p>
          ) : (
            <>
            <h4 className="mt-4 text-sm font-semibold text-[#1d1d1f]">Grade changes</h4>
            {changes.length === 0 ? (
              <p className="mt-1 text-xs text-[#6e6e73]">No grade change in the history on file.</p>
            ) : (
              <ul className="mt-1 space-y-1 text-sm text-[#1d1d1f]">
                {changes.map((c) => (
                  <li key={c.date} className="flex flex-wrap items-center gap-x-2">
                    <span className="text-[#6e6e73]">{shortDate(c.date)}</span>
                    <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${GRADE_STYLE[c.from] ?? ''}`}>{c.from}</span>
                    <span className="text-[#6e6e73]">→</span>
                    <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${GRADE_STYLE[c.to] ?? ''}`}>{c.to}</span>
                    <span className="text-xs text-[#6e6e73]">{c.moved.length > 0 ? c.moved.join(', ') : 'no change in recorded votes; cause not recorded'}</span>
                    {c.said && <span title="The desk published this grade that night; a row without the mark is today's rules replayed over past prices" className="text-[10px] tracking-wide text-[#0b5cad]">published</span>}
                  </li>
                ))}
              </ul>
            )}
            <p className="mb-2 text-xs leading-relaxed text-[#6e6e73]">
              Historical returns grouped by grade: sessions graded A or better against the other sessions.
              Annualized daily log-return means are conditional statistics, not funded portfolio returns or forecasts.
            </p>
            <div className="grid grid-cols-2 gap-2">
              {cells.map((c) => (
                <div key={c.label} className="rounded-xl border border-black/[0.08] bg-white p-3">
                  <p className="text-xs text-[#6e6e73]">{c.label}</p>
                  <p className="text-base font-semibold text-[#1d1d1f]">{c.value}</p>
                  <p className="mt-0.5 text-xs text-[#6e6e73]">{c.note}</p>
                </div>
              ))}
            </div>
            <h4 className="mt-4 text-sm font-semibold text-[#1d1d1f]">The last {recent.length} sessions</h4>
            <p className="mt-0.5 text-xs text-[#6e6e73]">
              Each night&rsquo;s grade with the analysts that voted for (+) or against (−) it, so a grade change shows
              which analyst moved. A row marked &ldquo;published&rdquo; is the grade the desk actually wrote that
              night. The rest are today&rsquo;s rules replayed over past prices, so they show what the desk
              would say now rather than what it said then.
            </p>
            <table className="mt-1 w-full text-sm">
              <thead className="text-left text-[#6e6e73]">
                <tr>
                  <th className="py-1">Date</th>
                  <th>Grade</th>
                  <th title={TRIGGER_LEGEND}>Analysts</th>
                  <th>Next {history.horizon} sessions</th>
                </tr>
              </thead>
              <tbody>
                {recent.map((row) => (
                  <tr key={row.date} className="border-t border-black/[0.05]">
                    <td className="py-1 text-[#6e6e73]">
                      {shortDate(row.date)}
                      {row.said && <span title="The desk published this grade that night" className="ml-1 text-[10px] tracking-wide text-[#0b5cad]">published</span>}
                    </td>
                    <td><span className={`rounded-full px-2 py-0.5 text-xs font-medium ${GRADE_STYLE[row.grade] ?? ''}`}>{row.grade}</span></td>
                    <td className="whitespace-nowrap font-mono text-xs text-[#1d1d1f]">
                      {row.stances && Object.keys(row.stances).length > 0
                        ? triggers(row.stances)
                        : `${row.votes > 0 ? '+' : ''}${row.votes.toFixed(1)} votes`}
                    </td>
                    <td>{row.forward != null ? <Trend value={row.forward * 100} /> : <span className="text-[#9ca3af]">—</span>}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            </>
          )}
          </div>
        </details>
        </div>
        </div>
      </div>
    </div>
  )
}

// The autopsy: what the person's own trading keeps doing, read from their
// own documents. Three sections plus what is unknown, and the sources it
// read, so the person can check the reading.
const AutopsyView = ({ userId, onClose }: { userId: string; onClose: () => void }) => {
  const [autopsy, setAutopsy] = useState<TradingAutopsy | null>(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(true)
  const [attempt, setAttempt] = useState(0)
  useEffect(() => {
    let alive = true
    const controller = new AbortController()
    setBusy(true)
    setError('')
    const deadline = window.setTimeout(() => controller.abort(), 120_000)
    // Defer until React's development effect replay has finished to avoid duplicate reviews.
    void Promise.resolve().then(() => alive ? getTradingAutopsy(userId, controller.signal) : null)
      .then((a) => alive && a && setAutopsy(a))
      .catch((err) => alive && setError(controller.signal.aborted ? 'The review timed out. Please retry.' : err instanceof Error ? err.message : 'The analysis could not run.'))
      .finally(() => { window.clearTimeout(deadline); if (alive) setBusy(false) })
    return () => {
      alive = false
      window.clearTimeout(deadline)
      controller.abort()
    }
  }, [userId, attempt])
  if (busy) {
    return (
      <section role="status" className="rounded-2xl border border-black/[0.08] bg-white p-4 text-sm text-[#6e6e73]">
        Reading the trading documents available for this review…
        <button type="button" onClick={onClose} className="ml-3 text-[#0071e3]">Cancel</button>
      </section>
    )
  }
  if (error) {
    return (
      <section role="alert" className="rounded-2xl border border-black/[0.08] bg-white p-4 text-sm text-[#b42318]">
        {error}
        <button type="button" onClick={() => setAttempt(a => a + 1)} className="ml-3 text-[#0071e3]">Retry review</button>
      </section>
    )
  }
  const result = autopsy?.result
  if (!result) {
    return (
      <section className="rounded-2xl border border-black/[0.08] bg-white p-4">
        <div className="flex items-center justify-between gap-3">
          <h3 className="text-sm font-semibold text-[#1d1d1f]">Your trading, in review</h3>
          <button type="button" onClick={onClose} className="text-xs text-[#0071e3] hover:underline">
            close
          </button>
        </div>
        <p className="mt-1 text-sm text-[#6e6e73]">
          {autopsy?.reason ?? 'Share a statement or trading journal in chat, then retry this review.'}
        </p>
      </section>
    )
  }
  return (
    <section className="rounded-2xl border border-black/[0.08] bg-white p-4">
      <div className="flex items-center justify-between gap-3">
        <h3 className="text-sm font-semibold text-[#1d1d1f]">Your trading, in review</h3>
        <button type="button" onClick={onClose} className="text-xs text-[#0071e3] hover:underline">
          close
        </button>
      </div>
      <p className="mb-2 mt-1 text-xs text-[#6e6e73]">
        Read from {autopsy?.passages_used ?? 0} passage{autopsy?.passages_used === 1 ? '' : 's'}
        {autopsy?.sources?.length ? ` of ${autopsy.sources.join(', ')}` : ''}. The analysis names what repeats; a single
        trade proves nothing.
      </p>
      <div className="space-y-3">
        <div>
          <h4 className="text-sm font-semibold text-[#1d1d1f]">Patterns</h4>
          <ul className="mt-1 space-y-1.5 text-sm text-[#1d1d1f]">
            {result.patterns.map((p, i) => (
              <li key={i}>
                <span className="font-medium">{p.behaviour}</span>
                <span className="text-[#6e6e73]"> — {p.evidence}</span>
              </li>
            ))}
            {result.patterns.length === 0 && <li className="text-[#6e6e73]">No repeated pattern found in the documents read.</li>}
          </ul>
        </div>
        <div>
          <h4 className="text-sm font-semibold text-[#1d1d1f]">What it has cost</h4>
          <ul className="mt-1 space-y-1.5 text-sm text-[#1d1d1f]">
            {result.costs.map((c, i) => (
              <li key={i}>
                <span className="font-medium">{c.what}</span>{' '}
                <span className="text-[#9a6200]">({c.amount})</span>
                <span className="text-[#6e6e73]"> — {c.source}</span>
              </li>
            ))}
            {result.costs.length === 0 && <li className="text-[#6e6e73]">No stated costs in what was read.</li>}
          </ul>
        </div>
        <div className="grid gap-2 sm:grid-cols-3">
          {(['stop', 'start', 'keep'] as const).map((kind) => (
            <div key={kind} className="rounded-xl bg-[#f5f5f7] p-3">
              <h4 className="text-xs font-semibold uppercase tracking-wide text-[#6e6e73]">{kind}</h4>
              <ul className="mt-1 space-y-1 text-sm text-[#1d1d1f]">
                {result.plan[kind].map((item) => (
                  <li key={item}>· {item}</li>
                ))}
                {result.plan[kind].length === 0 && <li className="text-[#6e6e73]">—</li>}
              </ul>
            </div>
          ))}
        </div>
        {result.unknowns.length > 0 && (
          <div>
            <h4 className="text-sm font-semibold text-[#1d1d1f]">Not clear from what you shared</h4>
            <ul className="mt-1 list-disc space-y-0.5 pl-5 text-sm text-[#6e6e73]">
              {result.unknowns.map((u) => (
                <li key={u}>{u}</li>
              ))}
            </ul>
          </div>
        )}
      </div>
    </section>
  )
}

export default DeskPanel
