import { useEffect, useRef, useState } from 'react'
import { RefreshCw, X } from 'lucide-react'
import {
  getDesk,
  getDeskHistory,
  getDeskHoldings,
  getDeskLive,
  getDeskMine,
  getDeskPaper,
  getTradingAutopsy,
  putDeskHoldings,
  type DeskCurve,
  type DeskHolding,
  type DeskHistory,
  type DeskLive,
  type DeskMineRow,
  type DeskPaperLive,
  type DeskPayload,
  type DeskQuote,
  type DeskRecord,
  type TradingAutopsy,
} from '../../services/api'

interface DeskPanelProps {
  userId: string
}

// The page asks for a fresh record every few minutes: the desk writes one
// a session, so that is plenty. Prices follow the fifteen-minute candle.
const REFRESH_MS = 5 * 60 * 1000
const CANDLE_MS = 15 * 60 * 1000

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
  'The analysts: F business fundamentals, T price trend, S news and sentiment, V price vs value, R which group leads. + for, · no view, − against.'

// The desk's warnings in plain words. A flag not listed shows as written.
const FLAG_WORDS: Record<string, string> = {
  'not enough history to judge participation': 'too little history to judge how broad the AI rally is',
  'participation below its two-year median': 'fewer AI names are rising than usual: the rally is narrow',
  'participation in its top quintile (hype)': 'almost every AI name is rising at once, which often marks a top',
  'AI-vs-software co-movement far from its history': 'AI and software stocks are moving together unusually, so the usual patterns may not hold',
  'theme co-movement structure has changed shape': 'the way these stocks move together has changed, so the desk trusts its picks less',
  'AI basket more than 25% off its yearly high': 'AI stocks are more than 25% below their high for the year',
  'the ten-year yield is rising sharply': 'interest rates are rising fast, which usually hurts these stocks',
}

// Per-browser conveniences: the account size typed in, and the stops switch.
const EQUITY_KEY = 'desk.equity'
const STOPS_KEY = 'desk.stops'
const readStored = (key: string): string | null => {
  try {
    return window.localStorage.getItem(key)
  } catch {
    return null
  }
}
const writeStored = (key: string, value: string) => {
  try {
    window.localStorage.setItem(key, value)
  } catch {
    // a private window; the value lives for the page only
  }
}

const pct = (value: number) => `${(value * 100).toFixed(1)}%`
const signed = (value: number) => `${value >= 0 ? '+' : ''}${(value * 100).toFixed(1)}%`
const money = (value: number) =>
  value.toLocaleString(undefined, { style: 'currency', currency: 'USD', maximumFractionDigits: 0 })
const sizing = (r: DeskMineRow, quote: DeskQuote | undefined, equity: number) => {
  const price = quote?.last ?? r.last ?? r.last_close ?? 0
  const qty = price > 0 ? Math.round((Math.abs(r.delta_weight) * equity) / price) : 0
  return { price, qty }
}
const today = () => new Date().toISOString().slice(0, 10)

// A signed value in green or red with an arrow, so the direction reads
// without color (a colour-blind reader sees the arrow, not the shade).
const Trend = ({ value, suffix = '%' }: { value: number; suffix?: string }) => {
  const up = value >= 0
  return (
    <span className={up ? 'text-[#1e7a3a]' : 'text-[#b42318]'} aria-label={`${up ? 'up' : 'down'} ${value.toFixed(1)}${suffix}`}>
      <span aria-hidden="true">{up ? '↑' : '↓'}</span> {up ? '+' : ''}
      {value.toFixed(1)}
      {suffix}
    </span>
  )
}

// The next rebalance as a calendar date: the desk's clock is trading
// sessions, so this projects the `n` sessions from the record's own date,
// skipping weekends. Weekday projection, so a holiday in the window makes
// it a day or two early; the desk's exact clock is the session count.
const projectTradingDate = (fromIso: string, sessions: number): string => {
  const d = new Date(`${fromIso}T12:00:00Z`)
  let added = 0
  while (added < sessions) {
    d.setUTCDate(d.getUTCDate() + 1)
    const dow = d.getUTCDay()
    if (dow !== 0 && dow !== 6) added += 1
  }
  return d.toISOString().slice(0, 10)
}
const shortDate = (iso: string) =>
  new Date(`${iso}T00:00:00Z`).toLocaleDateString(undefined, { month: 'short', day: 'numeric' })

// The positions after the person has done what a row says, at the price
// and size on the row. A buy opens the name, an add averages into it, a
// trim takes shares off, a sell closes it. They edit the price afterward
// if their fill differed.
const afterTrade = (holdings: DeskHolding[], r: DeskMineRow, price: number, qty: number): DeskHolding[] => {
  const rest = holdings.filter((h) => h.ticker !== r.ticker)
  const mine = holdings.find((h) => h.ticker === r.ticker)
  if (r.action === 'sell') return rest
  if (r.action === 'trim') {
    if (!mine || mine.shares - qty <= 0) return rest
    return [...rest, { ...mine, shares: mine.shares - qty }]
  }
  if (r.action === 'add' && mine) {
    const shares = mine.shares + qty
    const entry = (mine.shares * mine.entry_price + qty * price) / shares
    return [...rest, { ...mine, shares, entry_price: Math.round(entry * 100) / 100 }]
  }
  if (qty <= 0) return holdings
  return [...rest, { ticker: r.ticker, shares: qty, entry_price: price, entry_date: today() }]
}

// Each analyst's rating as a 0-100 number with its mark, F T S V R.
const ratings = (ranks: Record<string, number> | undefined, stances: Record<string, number>) =>
  TRIGGER_ORDER.filter(([k]) => ranks && k in ranks)
    .map(([k, letter]) => `${letter}${Math.round((ranks?.[k] ?? 0) * 100)}${STANCE_MARK[stances[k] ?? 0]}`)
    .join(' ')

// A reason is one line per analyst: its mark, its name, its triggers.
const ReasonLines = ({ text }: { text: string }) => (
  <ul className="mt-1 space-y-0.5 text-[#1d1d1f]">
    {text.split('\n').map((line, i) => (
      <li key={i} className="whitespace-nowrap">
        <span className="font-mono">{line.slice(0, 1)}</span> {line.slice(2)}
      </li>
    ))}
  </ul>
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
}: {
  latest: DeskRecord
  paperLive: DeskPaperLive | null
  curve: DeskCurve | undefined
}) => {
  const paper = latest.paper
  const worth = paperLive?.equity ?? paper?.equity
  const since = paper?.pl_pct
  const dayPl = paperLive?.day_pl
  const backtest = curve?.backtest
  const stats = backtest?.stats
  const last = (arr?: number[]) => (arr && arr.length ? arr[arr.length - 1] : null)
  const rulesTotal = last(backtest?.rules)
  const spyTotal = last(backtest?.spy)
  const qqqTotal = last(backtest?.qqq)
  const exposure = latest.regime.exposure ?? 1
  const until = paper?.until_rebalance ?? 20
  const rebalanceDate = projectTradingDate(latest.session, until)
  const cells = [
    {
      label: 'Practice account',
      value:
        worth !== undefined ? (
          <>
            {money(worth)}
            {since !== undefined && (
              <span className="ml-2 text-xs font-normal">
                <Trend value={since * 100} />
              </span>
            )}
          </>
        ) : (
          '—'
        ),
      note: 'the desk\u2019s own money, no real risk',
    },
    {
      label: 'Today',
      value: dayPl !== undefined ? <Trend value={dayPl} suffix="" /> : '—',
      note: 'the paper account\u2019s move so far',
    },
    {
      label: 'The rules, since inception',
      value:
        rulesTotal !== null ? (
          <>
            <Trend value={rulesTotal * 100} />
            <span className="ml-2 text-xs font-normal text-[#6e6e73]">
              vs SPY <Trend value={(spyTotal ?? 0) * 100} />
              {qqqTotal !== null && (
                <>
                  {' '}
                  · QQQ <Trend value={qqqTotal * 100} />
                </>
              )}
            </span>
          </>
        ) : (
          '—'
        ),
      note:
        stats && stats.drawdown !== null
          ? `worst drawdown ${(stats.drawdown * 100).toFixed(0)}%`
          : 'the desk\u2019s rules, measured forward',
    },
    {
      label: 'The desk is',
      value: `${Math.round(exposure * 100)}% invested`,
      note: exposure < 1 ? 'sizing down while conditions are thin' : 'at full book',
    },
    {
      label: 'Next rebalance',
      value: `≈ ${shortDate(rebalanceDate)}`,
      note: `in ${until} trading day${until === 1 ? '' : 's'}`,
    },
  ]
  return (
    <section className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5" aria-label="The desk at a glance">
      {cells.map((c) => (
        <div key={c.label} className="rounded-2xl border border-black/[0.08] bg-white p-3">
          <p className="text-xs text-[#6e6e73]">{c.label}</p>
          <p className="mt-0.5 truncate text-lg font-semibold text-[#1d1d1f]">{c.value}</p>
          <p className="mt-0.5 text-xs text-[#6e6e73]">{c.note}</p>
        </div>
      ))}
    </section>
  )
}

// The regime in front of the board, not at the bottom: the warnings change
// how much of the board to trust, so they lead it. Plain words for each
// flag, and a line when the desk has sized down because of them.
const RegimeBanner = ({ regime }: { regime: DeskRecord['regime'] }) => {
  const flags = regime.flags ?? []
  if (flags.length === 0) return null
  const exposure = regime.exposure ?? 1
  return (
    <section className="rounded-2xl border border-[#9a6200]/30 bg-[#fff6e5] p-4" role="note">
      <h3 className="text-sm font-semibold text-[#9a6200]">The desk is being careful right now</h3>
      <ul className="mt-1 list-disc space-y-0.5 pl-5 text-sm text-[#7a5200]">
        {flags.map((flag) => (
          <li key={flag}>{FLAG_WORDS[flag] ?? flag}</li>
        ))}
      </ul>
      {exposure < 1 && (
        <p className="mt-2 text-sm text-[#7a5200]">
          Because of this, the desk is carrying {Math.round(exposure * 100)}% of its usual book rather than
          the full size. That is the point of the warning, not the sign it is broken.
        </p>
      )}
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
  const moved = rows.length > 0 || changes.orders.length > 0 || changes.flags_raised.length > 0
  if (!moved && !changes.since) return null
  return (
    <section className="rounded-2xl border border-black/[0.08] bg-white p-4">
      <h3 className="mb-1 text-sm font-semibold text-[#1d1d1f]">
        What changed since the last session
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
              Orders at the next open:{' '}
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
        <p className="text-sm text-[#6e6e73]">Nothing moved: same grades, same book, same warnings.</p>
      )}
    </section>
  )
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
  const dates = backtest?.dates ?? []
  const series: { label: string; color: string; values: number[] }[] = []
  if (backtest) {
    series.push({ label: 'the desk\u2019s rules', color: '#1e7a3a', values: backtest.rules })
    series.push({ label: 'SPY', color: '#9ca3af', values: backtest.spy })
    if (backtest.qqq && backtest.qqq.length) series.push({ label: 'QQQ', color: '#0b5cad', values: backtest.qqq })
  }
  if (paper && paper.equity.length > 1) {
    const base = paper.equity[0] || 1
    series.push({
      label: 'paper account (live)',
      color: '#d97706',
      values: paper.equity.map((e) => e / base - 1),
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
  const all = series.flatMap((s) => s.values).concat(0)
  const min = Math.min(...all, 0)
  const max = Math.max(...all, 0)
  const span = max - min || 1
  const x = (i: number) => (dates.length > 1 ? padL + (i / (dates.length - 1)) * innerW : padL + innerW / 2)
  const y = (v: number) => padT + (1 - (v - min) / span) * innerH
  const line = (values: number[]) => values.map((v, i) => `${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(' ')
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
        {series.map((s) => (
          <polyline key={s.label} points={line(s.values)} fill="none" stroke={s.color} strokeWidth={2} strokeLinejoin="round" strokeLinecap="round" />
        ))}
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
          The evening run has not written a curve yet; check back after the next close.
        </p>
      </section>
    )
  }
  const cells = [
    { label: 'CAGR', value: stats.cagr !== null ? `${(stats.cagr * 100).toFixed(1)}%` : '—' },
    { label: 'Volatility', value: stats.volatility !== null ? `${(stats.volatility * 100).toFixed(0)}%` : '—' },
    { label: 'Worst drawdown', value: stats.drawdown !== null ? `${(stats.drawdown * 100).toFixed(0)}%` : '—' },
    { label: 'Total return', value: stats.total !== null ? `${(stats.total * 100).toFixed(0)}%` : '—' },
  ]
  return (
    <section className="rounded-2xl border border-black/[0.08] bg-white p-4">
      <div className="mb-2 flex flex-wrap items-baseline justify-between gap-2">
        <h3 className="text-sm font-semibold text-[#1d1d1f]">The desk’s track record</h3>
        <p className="text-xs text-[#6e6e73]">
          {backtest.label} · as of {shortDate(backtest.asof)} · the paper account is the only truly new sample
        </p>
      </div>
      <div className="mb-3 grid grid-cols-2 gap-2 sm:grid-cols-4">
        {cells.map((c) => (
          <div key={c.label} className="rounded-xl bg-[#f5f5f7] px-3 py-2">
            <p className="text-xs text-[#6e6e73]">{c.label}</p>
            <p className="text-sm font-semibold text-[#1d1d1f]">{c.value}</p>
          </div>
        ))}
      </div>
      <CurveChart backtest={backtest} paper={curve?.paper} />
    </section>
  )
}

// The one-screen explanation for someone who has never seen the page, used
// both as the help popover and the empty-state guide.
const HowToUse = ({ onClose, compact = false }: { onClose?: () => void; compact?: boolean }) => (
  <div className={`rounded-xl border border-black/[0.08] bg-[#f5f5f7] p-4 text-sm text-[#1d1d1f] ${compact ? '' : 'my-2 max-w-xl'}`}>
    <ol className="list-decimal space-y-1.5 pl-5">
      <li>
        <b>Every evening</b> the desk grades about ninety AI and software stocks and picks the A-rated ones to own.
        That decision holds for the next trading day.
      </li>
      <li>
        <b>Enter your positions</b> (type or paste from Schwab) and set your account size. The board then says, name
        by name, <b>buy, add, trim, sell or hold</b>, and how many shares.
      </li>
      <li>
        <b>Buy at the open</b> with a market order. Do not chase a name that has already jumped. When a trade is
        placed, click <b>done</b> on its row and your positions update.
      </li>
      <li>
        <b>Selling:</b> a name is sold when its grade drops below A at the next check, about every four weeks. Each
        row says when that is. Stops are optional: switch them on to see a price under which to sell.
      </li>
      <li>
        <b>Prices</b> refresh every 15 minutes during market hours. Gains are measured from what you paid.
      </li>
      <li>
        <b>Why:</b> click a name or its reason to read the desk’s case for it, and what would change its mind.
      </li>
    </ol>
    {onClose && (
      <button type="button" onClick={onClose} className="mt-3 text-xs text-[#0071e3] hover:underline">
        close
      </button>
    )}
  </div>
)

// The first-time state: the page either has no decision on file yet, or the
// person has not entered positions, and both are where people abandon a
// trading screen. Turn it into the three steps instead of a blank line.
const GettingStarted = ({ hasRecord, hasPositions, onEnterPositions }: { hasRecord: boolean; hasPositions: boolean; onEnterPositions: () => void }) => {
  if (hasRecord && hasPositions) return null
  return (
    <section className="rounded-2xl border border-black/[0.08] bg-white p-4">
      <h3 className="mb-2 text-sm font-semibold text-[#1d1d1f]">
        {hasRecord ? 'Set up the board' : 'The desk starts tonight'}
      </h3>
      {!hasRecord ? (
        <p className="mb-2 text-sm text-[#6e6e73]">
          The desk writes a decision every evening after the close. Tonight it will grade the book, and tomorrow
          this page will tell you what to do at the open.
        </p>
      ) : (
        <p className="mb-2 text-sm text-[#6e6e73]">
          No positions entered, so every name below is a buy from nothing. Enter what you hold and the board says
          what to change.
        </p>
      )}
      <HowToUse compact />
      {hasRecord && (
        <button type="button" onClick={onEnterPositions} className="mt-2 rounded-full bg-[#1d1d1f] px-3 py-1.5 text-sm text-white">
          enter my positions
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
const DeskPanel = ({ userId }: DeskPanelProps) => {
  const [payload, setPayload] = useState<DeskPayload | null>(null)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)
  const [live, setLive] = useState<DeskLive>({ as_of: null, quotes: {} })
  const [paperLive, setPaperLive] = useState<DeskPaperLive | null>(null)
  const [holdings, setHoldings] = useState<DeskHolding[]>([])
  const [rows, setRows] = useState<DeskMineRow[]>([])
  const [equity, setEquity] = useState<number>(() => Number(readStored(EQUITY_KEY)) || 100000)
  const [stops, setStops] = useState(() => readStored(STOPS_KEY) === 'on')
  const [help, setHelp] = useState(false)
  const [details, setDetails] = useState(false)
  const [editing, setEditing] = useState(false)
  const [saveError, setSaveError] = useState('')
  const [openReason, setOpenReason] = useState<string | null>(null)
  const [openName, setOpenName] = useState<string | null>(null)
  const [autopsy, setAutopsy] = useState(false)
  const [marking, setMarking] = useState<string | null>(null)

  const save = async (next: DeskHolding[]) => {
    try {
      setHoldings(await putDeskHoldings(userId, next))
      setSaveError('')
      return true
    } catch (err) {
      setSaveError(err instanceof Error ? err.message : 'The positions were not saved.')
      return false
    }
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
  useEffect(() => {
    void load()
    const timer = window.setInterval(() => void load(), REFRESH_MS)
    return () => window.clearInterval(timer)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [userId])

  useEffect(() => {
    void (async () => {
      try {
        setHoldings(await getDeskHoldings(userId))
      } catch {
        // none saved yet
      }
    })()
  }, [userId])

  // The board, the candle, and the practice account together, every fifteen
  // minutes; the practice account's day P/L feeds the summary strip.
  useEffect(() => {
    const poll = async () => {
      try {
        setLive(await getDeskLive(userId))
      } catch {
        // the board stands without the live layer
      }
      try {
        setRows(await getDeskMine(userId, equity))
      } catch {
        // the last board stands
      }
      try {
        setPaperLive(await getDeskPaper(userId))
      } catch {
        setPaperLive({ reason: 'unreachable' })
      }
    }
    void poll()
    const timer = window.setInterval(() => void poll(), CANDLE_MS)
    return () => window.clearInterval(timer)
  }, [userId, equity, holdings])

  if (loading) {
    return <div className="flex flex-1 items-center justify-center text-sm text-[#6e6e73]">Loading the desk…</div>
  }
  if (error) {
    return <div className="flex flex-1 items-center justify-center text-sm text-[#b42318]">{error}</div>
  }
  if (!payload) {
    return <div className="flex flex-1 items-center justify-center text-sm text-[#6e6e73]">Loading the desk…</div>
  }

  const { latest, summary } = payload
  const curve = payload.curve ?? latest?.curve
  const warnings = latest?.regime.flags ?? []

  return (
    <div className="flex flex-1 flex-col gap-5 overflow-y-auto p-6">
      <header className="flex flex-wrap items-baseline justify-between gap-3">
        <div>
          <div className="flex items-center gap-2">
            <h2 className="text-xl font-semibold text-[#1d1d1f]">Desk</h2>
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
              {autopsy ? 'hide the autopsy' : 'analyze my trading'}
            </button>
          </div>
          {help && <HowToUse onClose={() => setHelp(false)} />}
          <p className="text-sm text-[#6e6e73]">
            {latest
              ? `Decision from the close of ${latest.session} · the desk is ${summary ? pct(summary.gross) : '—'} invested`
              : 'No decision on file yet'}
          </p>
        </div>
        <button
          type="button"
          onClick={() => void load()}
          className="flex items-center gap-2 rounded-full border border-black/[0.08] bg-white px-3 py-1.5 text-sm text-[#1d1d1f] hover:bg-[#f5f5f7]"
        >
          <RefreshCw size={14} /> Refresh
        </button>
      </header>

      {autopsy && <AutopsyView userId={userId} onClose={() => setAutopsy(false)} />}

      {!latest && <GettingStarted hasRecord={false} hasPositions={holdings.length > 0} onEnterPositions={() => setEditing(true)} />}

      {latest && (
        <SummaryStrip latest={latest} paperLive={paperLive} curve={curve} />
      )}

      {latest && <RegimeBanner regime={latest.regime} />}

      {latest && payload.changes && <WhatChanged changes={payload.changes} />}

      {latest && (
        <BestBuys
          rows={rows}
          equity={equity}
          quotes={live.quotes}
          marking={marking}
          onBuy={async (r) => {
            const { price, qty } = sizing(r, live.quotes[r.ticker], equity)
            setMarking(r.ticker)
            await save(afterTrade(holdings, r, price, qty))
            setMarking(null)
          }}
        />
      )}

      {latest && (
        <section className="rounded-2xl border border-black/[0.08] bg-white p-4">
          <div className="mb-2 flex flex-wrap items-baseline justify-between gap-x-4 gap-y-2">
            <h3 className="text-sm font-semibold text-[#1d1d1f]">
              What to do at the next open
              {live.as_of && (
                <span className="ml-2 text-xs font-normal text-[#6e6e73]">
                  prices as of {new Date(live.as_of).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                </span>
              )}
            </h3>
            <div className="flex flex-wrap items-center gap-4 text-xs text-[#6e6e73]">
              <label className="flex items-center gap-2">
                account size $
                <input
                  type="number"
                  min={0}
                  step={1000}
                  value={Math.round(equity)}
                  onChange={(e) => {
                    const value = Number(e.target.value) || 0
                    setEquity(value)
                    writeStored(EQUITY_KEY, String(value))
                  }}
                  className="w-28 rounded-md border border-black/[0.12] px-2 py-1 text-right text-sm text-[#1d1d1f]"
                />
              </label>
              <label className="flex items-center gap-2">
                <input
                  type="checkbox"
                  checked={stops}
                  onChange={(e) => {
                    setStops(e.target.checked)
                    writeStored(STOPS_KEY, e.target.checked ? 'on' : 'off')
                  }}
                />
                show stops
              </label>
              <button type="button" onClick={() => setEditing(!editing)} className="text-[#0071e3] hover:underline">
                {editing ? 'done' : holdings.length > 0 ? 'edit my positions' : 'enter my positions'}
              </button>
            </div>
          </div>
          {editing && (
            <Positions
              holdings={holdings}
              error={saveError}
              onSave={async (next) => {
                if (await save(next)) setEditing(false)
              }}
            />
          )}
          {holdings.length === 0 && !editing && (
            <GettingStarted hasRecord hasPositions={false} onEnterPositions={() => setEditing(true)} />
          )}
          <table className="w-full text-sm">
            <thead className="text-left text-[#6e6e73]">
              <tr>
                <th className="py-1">Name</th>
                <th>Action</th>
                <th>Size</th>
                <th>Grade</th>
                <th>Exit</th>
                <th title={TRIGGER_LEGEND}>Why</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <Row
                  key={r.ticker}
                  r={r}
                  ranks={latest.grades[r.ticker]?.ranks}
                  quote={live.quotes[r.ticker]}
                  equity={equity}
                  stops={stops}
                  open={openReason === r.ticker}
                  onReason={() => setOpenReason(openReason === r.ticker ? null : r.ticker)}
                  onOpenName={() => setOpenName(r.ticker)}
                  marking={marking === r.ticker}
                  onDone={async () => {
                    const { price, qty } = sizing(r, live.quotes[r.ticker], equity)
                    setMarking(r.ticker)
                    await save(afterTrade(holdings, r, price, qty))
                    setMarking(null)
                  }}
                />
              ))}
            </tbody>
          </table>
          {saveError && !editing && <p className="mt-2 text-xs text-[#b42318]">{saveError}</p>}
          <p className="mt-2 text-xs text-[#6e6e73]">
            When you have placed a trade on Schwab, click <b>done</b> on its row and it goes into your positions at the
            price shown; edit the price if your fill differed. Names are in grade order, best first, re-read every 15
            minutes with the technical analyst at the live price. Share counts follow the live price; the weights are
            the evening decision. Buy at the open with a market order. The desk sells when a name loses its A grade at
            the next check, not at a price; stops are optional because they cut winners as often as losers.
          </p>
        </section>
      )}

      {latest && <TrackRecord curve={curve} />}

      {latest && (
        <button
          type="button"
          onClick={() => setDetails(!details)}
          className="self-start text-sm text-[#0071e3] hover:underline"
        >
          {details ? 'Hide the details' : 'Show the details: practice account and every grade'}
        </button>
      )}

      {latest && details && <PracticeAccount record={latest.paper} paperLive={paperLive} />}

      {latest && details && <EveryGrade latest={latest} />}

      {openName && latest && <NameDetail userId={userId} ticker={openName} latest={latest} onClose={() => setOpenName(null)} />}
    </div>
  )
}

// The names worth buying right now, ranked for this moment and sized by the
// grade. The board rows are already ordered best-first by the live score
// (the technical analyst re-read at the live price every fifteen minutes),
// so this keeps that order and filters to what you do not yet hold. A buy
// opens the position at the shown size, so the desk can track it.
const BestBuys = ({
  rows,
  equity,
  quotes,
  marking,
  onBuy,
}: {
  rows: DeskMineRow[]
  equity: number
  quotes: Record<string, DeskQuote>
  marking: string | null
  onBuy: (r: DeskMineRow) => Promise<void>
}) => {
  const buys = rows.filter((r) => r.in_book && r.target_weight > 0 && r.shares === 0)
  if (buys.length === 0) return null
  return (
    <section className="rounded-2xl border border-[#1e7a3a]/25 bg-white p-4">
      <h3 className="text-sm font-semibold text-[#1d1d1f]">Best buys right now</h3>
      <p className="mb-2 text-xs text-[#6e6e73]">
        Ranked best-first for this moment, sized by the grade. Click <b>Buy</b> once you have placed it on Schwab and it
        becomes a tracked position.
      </p>
      <ol className="flex flex-col gap-1">
        {buys.map((r, i) => {
          const { price, qty } = sizing(r, quotes[r.ticker], equity)
          return (
            <li
              key={r.ticker}
              className="flex flex-wrap items-center gap-x-3 gap-y-1 border-t border-black/[0.05] py-1.5 text-sm"
            >
              <span className="w-5 text-right font-mono text-xs text-[#6e6e73]">{i + 1}</span>
              <span className="w-14 font-medium text-[#1d1d1f]">{r.ticker}</span>
              <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${GRADE_STYLE[r.grade_live] ?? ''}`}>
                {r.grade_live}
              </span>
              <span className="min-w-0 flex-1 truncate text-xs text-[#6e6e73]" title={r.why}>
                {r.why}
              </span>
              <span className="whitespace-nowrap text-xs text-[#6e6e73]">
                {qty.toLocaleString()} sh · {money(qty * price)}
              </span>
              <button
                type="button"
                onClick={() => void onBuy(r)}
                disabled={marking === r.ticker}
                className="rounded-full bg-[#1e7a3a] px-3 py-1 text-xs font-medium text-white hover:bg-[#17632e] disabled:bg-[#a3c4ad]"
              >
                {marking === r.ticker ? 'saving…' : 'Buy'}
              </button>
            </li>
          )
        })}
      </ol>
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
            ? `live, as of ${new Date(live.as_of).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}`
            : `as of the last evening record${live?.reason ? ` (broker: ${live.reason})` : ''}`}
        </span>
      </h3>
      <p className="mb-2 text-xs text-[#6e6e73]">
        A simulated account that follows the desk with real prices and no real money. Its track record is the
        desk&rsquo;s.
      </p>
      <p className="text-sm text-[#1d1d1f]">
        Worth {money(equityValue)} · cash {money(cash)}
        {fromBroker && live.day_pl !== undefined && (
          <>
            {' '}· <Trend value={live.day_pl} suffix="" /> today
          </>
        )}
        {!fromBroker && record && (
          <>
            {' '}·{' '}
            {record.plan === 'rebalance'
              ? 'every grade was re-checked and the sizes reset'
              : record.plan === 'exits'
                ? 'only names that lost their grade are sold'
                : 'nothing to trade'}
          </>
        )}
      </p>
      {orders.length > 0 && (
        <p className="mt-2 text-sm text-[#6e6e73]">
          Orders waiting for the open: {orders.map((o) => `${o.side} ${o.qty} ${o.symbol}`).join(', ')}
        </p>
      )}
      {positions.length > 0 ? (
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
                <td>{money(p.avg_entry_price)}</td>
                <td>{money(p.current_price)}</td>
                <td className={p.unrealized_pl >= 0 ? 'text-[#1e7a3a]' : 'text-[#b42318]'}>
                  <Trend value={p.unrealized_pl} suffix="" />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : (
        <p className="mt-2 text-sm text-[#6e6e73]">No positions held.</p>
      )}
    </section>
  )
}

interface RowProps {
  r: DeskMineRow
  ranks?: Record<string, number>
  quote?: DeskQuote
  equity: number
  stops: boolean
  open: boolean
  onReason: () => void
  onOpenName: () => void
  marking: boolean
  onDone: () => Promise<void>
}

// One name: what to do, how much for this account, the price now against
// the close and the person's own cost, the grade, when it leaves, and why.
// The "why" reads in plain words first; the analysts' numbers are inside.
const Row = ({ r, ranks, quote, equity, stops, open, onReason, onOpenName, marking, onDone }: RowProps) => {
  const { price, qty } = sizing(r, quote, equity)
  const high = Math.max(r.high_20 ?? 0, quote?.high ?? 0)
  const trailing = stops && high > 0 ? high * 0.88 : null
  const hit = trailing !== null && price > 0 && price <= trailing
  const atRisk = r.in_book && r.target_weight > 0 && (r.grade_margin ?? 1) <= 0
  return (
    <tr className="border-t border-black/[0.05] align-top">
      <td className="py-1.5">
        <button type="button" onClick={onOpenName} className="font-medium text-[#1d1d1f] hover:text-[#0071e3] hover:underline" title="Open the name's history">
          {r.ticker}
        </button>
      </td>
      <td>
        <span className={`rounded-full px-2 py-0.5 text-xs font-medium uppercase ${ACTION_STYLE[r.action] ?? ''}`}>
          {r.action}
        </span>
        {r.action !== 'hold' && (
          <button
            type="button"
            onClick={() => void onDone()}
            disabled={marking}
            title="I have placed this trade on my broker: record it in my positions at the price shown"
            className="ml-1 text-xs text-[#0071e3] hover:underline disabled:text-[#6e6e73]"
          >
            {marking ? 'saving' : 'done'}
          </button>
        )}
      </td>
      <td className="whitespace-nowrap">
        {r.action === 'hold' ? (
          <span>{pct(r.current_weight)} of the account</span>
        ) : (
          <span className="font-medium">{qty.toLocaleString()} shares</span>
        )}
        {r.shares > 0 && r.entry_price !== null && (
          <div className="text-xs text-[#6e6e73]">
            you hold {r.shares} at {money(r.entry_price)}
            {r.pl_pct !== null && (
              <span className={r.pl_pct >= 0 ? ' text-[#1e7a3a]' : ' text-[#b42318]'}> <Trend value={r.pl_pct * 100} /></span>
            )}
          </div>
        )}
      </td>
      <td className="whitespace-nowrap">
        {r.in_book ? (
          <>
            <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${GRADE_STYLE[r.grade_live] ?? ''}`}>{r.grade_live}</span>
            {r.grade_live !== r.grade && (
              <span className="ml-1 text-xs text-[#6e6e73]" title="the grade with the technical analyst read at the live price; the evening grade stands for the desk's own trades">
                {r.grade} at the close
              </span>
            )}
            {atRisk && r.grade_live === r.grade && (
              <span className="ml-1 text-xs text-[#9a6200]" title="one more analyst turning against it would drop the grade below A">
                at risk
              </span>
            )}
          </>
        ) : (
          <span className="text-xs text-[#6e6e73]">not covered</span>
        )}
      </td>
      <td className="whitespace-nowrap text-xs text-[#6e6e73]">
        {r.leaves_if}
        {r.until_rebalance !== null && r.target_weight > 0 && (
          <>
            <br />
            grade check in {r.until_rebalance} trading day{r.until_rebalance === 1 ? '' : 's'}
          </>
        )}
        {trailing !== null && (
          <>
            <br />
            <span className={hit ? 'font-medium text-[#b42318]' : ''}>
              {hit ? 'below the stop: sell' : `stop ${money(trailing)}`}
            </span>
          </>
        )}
      </td>
      <td className="text-xs text-[#6e6e73]">
        {r.in_book && r.why ? (
          <button type="button" onClick={onReason} className="text-left text-[#1d1d1f] hover:text-[#0071e3] hover:underline" title="why the desk holds this grade">
            {open ? 'hide' : r.why}
          </button>
        ) : (
          r.why
        )}
        {open && (
          <>
            <div className="mt-1 font-mono text-[#1d1d1f]" title={`${TRIGGER_LEGEND} the number is the analyst's rating, 0 to 100`}>
              {r.in_book && ranks ? ratings(ranks, r.stances ?? {}) : null}
            </div>
            {r.technical_now !== null && r.technical_close !== null && (
              <div className="text-[#6e6e73]">
                technical at the live price: {Math.round(r.technical_now * 100)} (was {Math.round(r.technical_close * 100)} at the close)
              </div>
            )}
            {r.reason && <ReasonLines text={r.reason} />}
          </>
        )}
      </td>
    </tr>
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

// Every name the desk follows, best first, with the analysts' marks and
// the reason behind the grade on request.
const EveryGrade = ({ latest }: { latest: NonNullable<DeskPayload['latest']> }) => {
  const [openBrief, setOpenBrief] = useState<string | null>(null)
  const grades = Object.entries(latest.grades).sort((a, b) => b[1].score - a[1].score)
  const briefs = latest.briefs ?? {}
  return (
    <section className="rounded-2xl border border-black/[0.08] bg-white p-4">
      <h3 className="mb-1 text-sm font-semibold text-[#1d1d1f]">Every grade</h3>
      <p className="mb-2 text-xs text-[#6e6e73]">
        {TRIGGER_LEGEND} The number is the analyst&rsquo;s rating, 0 to 100: where the name ranks across the book on
        that analyst&rsquo;s evidence.
      </p>
      <table className="w-full text-sm">
        <thead className="text-left text-[#6e6e73]">
          <tr>
            <th className="py-1">Name</th>
            <th>Group</th>
            <th>Grade</th>
            <th title="each analyst's rating, 0 to 100, its rank across the book; + for, − against">Analysts</th>
            <th>Why</th>
          </tr>
        </thead>
        <tbody>
          {grades.map(([ticker, g]) => (
            <tr key={ticker} className="border-t border-black/[0.05] align-top">
              <td className="py-1 font-medium">{ticker}</td>
              <td className="text-[#6e6e73]">{g.side === 'ai' ? 'AI' : g.side}</td>
              <td>
                <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${GRADE_STYLE[g.grade] ?? ''}`}>{g.grade}</span>
              </td>
              <td className="whitespace-nowrap font-mono text-xs">
                {g.ranks ? ratings(g.ranks, g.stances ?? {}) : triggers(g.stances ?? {})}
              </td>
              <td className="text-xs">
                {briefs[ticker] || g.headline ? (
                  <button
                    type="button"
                    onClick={() => setOpenBrief(openBrief === ticker ? null : ticker)}
                    className="text-left text-[#0071e3] hover:underline"
                  >
                    {openBrief === ticker ? 'hide' : (briefs[ticker]?.verdict ?? g.headline)}
                  </button>
                ) : (
                  <span className="text-[#6e6e73]">—</span>
                )}
                {openBrief === ticker && (
                  <div className="mt-1 space-y-1 text-[#1d1d1f]">
                    {g.reason && <ReasonLines text={g.reason} />}
                    {briefs[ticker] && (
                      <>
                        <p>{briefs[ticker].reasoning}</p>
                        <p>
                          <span className="font-medium">Risks:</span> {briefs[ticker].risks}
                        </p>
                        <p>
                          <span className="font-medium">Watch:</span> {briefs[ticker].watch}
                        </p>
                      </>
                    )}
                  </div>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  )
}

const triggers = (stances: Record<string, number>) =>
  TRIGGER_ORDER.filter(([k]) => k in stances)
    .map(([k, letter]) => `${letter}${STANCE_MARK[stances[k] ?? 0]}`)
    .join(' ')

// One name's drill-down: what the desk said about it over time, what came
// next, and how it did under the desk's own rule versus holding it or the
// benchmark. Read from the file the nightly run wrote.
const NameDetail = ({
  userId,
  ticker,
  latest,
  onClose,
}: {
  userId: string
  ticker: string
  latest: NonNullable<DeskPayload['latest']>
  onClose: () => void
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
  const bt = history?.backtest
  const recent = history?.rows.slice(-12) ?? []
  const cells = [
    { label: 'The desk\u2019s rule', value: bt?.rule_return != null ? `${(bt.rule_return * 100).toFixed(0)}%` : '—', note: 'holding it only while graded A or better' },
    { label: 'Just holding it', value: bt?.hold_return != null ? `${(bt.hold_return * 100).toFixed(0)}%` : '—', note: 'buy and hold over the same span' },
    { label: 'The benchmark', value: bt?.benchmark_return != null ? `${(bt.benchmark_return * 100).toFixed(0)}%` : '—', note: 'SPY over the same sessions' },
    { label: 'In vs out', value: bt?.in_annualised != null ? `${(bt.in_annualised * 100).toFixed(0)}%` : '—', note: bt?.out_annualised != null ? `vs ${(bt.out_annualised * 100).toFixed(0)}% on the days it was not held` : '' },
  ]
  return (
    <div className="fixed inset-0 z-50 flex justify-end bg-black/25" onClick={onClose} role="dialog" aria-label={`${ticker} history`}>
      <div className="h-full w-full max-w-xl overflow-y-auto bg-[#f5f5f7] p-5 shadow-xl" onClick={(e) => e.stopPropagation()}>
        <div className="mb-3 flex items-center justify-between">
          <h3 className="text-lg font-semibold text-[#1d1d1f]">
            {ticker}
            {brief && <span className="ml-2 text-sm font-normal text-[#6e6e73]">{brief.verdict}</span>}
          </h3>
          <button type="button" onClick={onClose} aria-label="Close" className="flex h-8 w-8 items-center justify-center rounded-full border border-black/[0.1] text-[#6e6e73] hover:bg-white">
            <X size={16} />
          </button>
        </div>
        {error ? (
          <p className="text-sm text-[#6e6e73]">{error}. The nightly run writes this after the next close.</p>
        ) : !history ? (
          <p className="text-sm text-[#6e6e73]">Loading the history…</p>
        ) : (
          <>
            <div className="grid grid-cols-2 gap-2">
              {cells.map((c) => (
                <div key={c.label} className="rounded-xl border border-black/[0.08] bg-white p-3">
                  <p className="text-xs text-[#6e6e73]">{c.label}</p>
                  <p className="text-base font-semibold text-[#1d1d1f]">{c.value}</p>
                  <p className="mt-0.5 text-xs text-[#6e6e73]">{c.note}</p>
                </div>
              ))}
            </div>
            {brief && (
              <div className="mt-3 space-y-1 rounded-xl border border-black/[0.08] bg-white p-3 text-sm text-[#1d1d1f]">
                <p>{brief.reasoning}</p>
                <p><span className="font-medium">Risks:</span> {brief.risks}</p>
                <p><span className="font-medium">Watch:</span> {brief.watch}</p>
              </div>
            )}
            <h4 className="mt-4 text-sm font-semibold text-[#1d1d1f]">The last {recent.length} sessions</h4>
            <table className="mt-1 w-full text-sm">
              <thead className="text-left text-[#6e6e73]">
                <tr>
                  <th className="py-1">Date</th>
                  <th>Grade</th>
                  <th>Votes</th>
                  <th>Next {history.horizon} sessions</th>
                </tr>
              </thead>
              <tbody>
                {recent.map((row) => (
                  <tr key={row.date} className="border-t border-black/[0.05]">
                    <td className="py-1 text-[#6e6e73]">{shortDate(row.date)}</td>
                    <td><span className={`rounded-full px-2 py-0.5 text-xs font-medium ${GRADE_STYLE[row.grade] ?? ''}`}>{row.grade}</span></td>
                    <td className="text-[#6e6e73]">{row.votes > 0 ? `+${row.votes.toFixed(1)}` : row.votes.toFixed(1)}</td>
                    <td>{row.forward != null ? <Trend value={row.forward * 100} /> : <span className="text-[#9ca3af]">—</span>}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </>
        )}
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
  useEffect(() => {
    let alive = true
    void getTradingAutopsy(userId)
      .then((a) => alive && setAutopsy(a))
      .catch((err) => alive && setError(err instanceof Error ? err.message : 'The analysis could not run.'))
      .finally(() => alive && setBusy(false))
    return () => {
      alive = false
    }
  }, [userId])
  if (busy) {
    return (
      <section className="rounded-2xl border border-black/[0.08] bg-white p-4 text-sm text-[#6e6e73]">
        Reading your own trading history… this takes a few seconds.
      </section>
    )
  }
  if (error) {
    return (
      <section className="rounded-2xl border border-black/[0.08] bg-white p-4 text-sm text-[#b42318]">
        {error}
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
          {autopsy?.reason ?? 'Nothing to show yet.'} Share a statement, a journal, or notes about your trades and try
          again.
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
            {result.patterns.length === 0 && <li className="text-[#6e6e73]">Nothing repeated yet.</li>}
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
