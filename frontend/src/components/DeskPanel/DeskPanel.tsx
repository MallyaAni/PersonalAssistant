import { useEffect, useState } from 'react'
import { RefreshCw } from 'lucide-react'
import { getDesk, getDeskLive, type DeskAction, type DeskLive, type DeskPayload } from '../../services/api'

interface DeskPanelProps {
  userId: string
}

// How often the page asks for a fresh record while open. The desk writes
// one record a session, so a few minutes is plenty and costs nothing.
const REFRESH_MS = 5 * 60 * 1000
// The live layer follows the fifteen-minute candle the board's stops are
// judged against.
const CANDLE_MS = 15 * 60 * 1000

const GRADE_STYLE: Record<string, string> = {
  'A+': 'bg-[#e6f4ea] text-[#1e7a3a]',
  A: 'bg-[#eaf3ff] text-[#0b5cad]',
  B: 'bg-[#fff6e5] text-[#9a6200]',
  C: 'bg-[#f5f5f7] text-[#6e6e73]',
}

const STANCE_MARK: Record<number, string> = { 1: '+', 0: '·', [-1]: '−' }

const ACTION_STYLE: Record<string, string> = {
  buy: 'bg-[#e6f4ea] text-[#1e7a3a]',
  add: 'bg-[#e6f4ea] text-[#1e7a3a]',
  trim: 'bg-[#fff6e5] text-[#9a6200]',
  sell: 'bg-[#fdecea] text-[#b42318]',
  hold: 'bg-[#f5f5f7] text-[#6e6e73]',
}

// The equity the board sizes to. The paper account's by default; the
// person's own once typed, remembered in this browser only.
const EQUITY_KEY = 'desk.equity'
const STOPS_KEY = 'desk.stops'
const readStops = (): boolean => {
  try {
    return window.localStorage.getItem(STOPS_KEY) === 'on'
  } catch {
    return false
  }
}
const writeStops = (on: boolean) => {
  try {
    window.localStorage.setItem(STOPS_KEY, on ? 'on' : 'off')
  } catch {
    // a private window
  }
}
const readEquity = (): number | null => {
  try {
    const raw = window.localStorage.getItem(EQUITY_KEY)
    return raw ? Number(raw) : null
  } catch {
    return null
  }
}
const writeEquity = (value: number) => {
  try {
    window.localStorage.setItem(EQUITY_KEY, String(value))
  } catch {
    // a private window; the value lives for the page only
  }
}

// Shares for a weight at an equity and a price, to the nearest share.
const shares = (weight: number, equity: number, price: number) =>
  price > 0 ? Math.round((weight * equity) / price) : 0

const pct = (value: number) => `${(value * 100).toFixed(1)}%`
const money = (value: number) =>
  value.toLocaleString(undefined, { style: 'currency', currency: 'USD', maximumFractionDigits: 0 })

// The trading desk's day: the regime, what to do at the next open, the book
// to hold, every grade, and the briefs the model wrote. Everything shown is
// read from the record the desk wrote; nothing is computed here.
const DeskPanel = ({ userId }: DeskPanelProps) => {
  const [payload, setPayload] = useState<DeskPayload | null>(null)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)
  const [openBrief, setOpenBrief] = useState<string | null>(null)
  const [equity, setEquity] = useState<number | null>(readEquity())
  const [live, setLive] = useState<DeskLive>({ as_of: null, quotes: {} })
  const [stops, setStops] = useState<boolean>(readStops())
  const [details, setDetails] = useState(false)
  const [openReason, setOpenReason] = useState<string | null>(null)

  const load = async () => {
    try {
      setPayload(await getDesk(userId))
      setError('')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not load the desk.')
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
    const poll = async () => {
      try {
        setLive(await getDeskLive(userId))
      } catch {
        // the board stands without the live layer
      }
    }
    void poll()
    const timer = window.setInterval(() => void poll(), CANDLE_MS)
    return () => window.clearInterval(timer)
  }, [userId])

  if (loading) {
    return <div className="flex flex-1 items-center justify-center text-sm text-[#6e6e73]">Loading the desk…</div>
  }
  if (error) {
    return <div className="flex flex-1 items-center justify-center text-sm text-[#b42318]">{error}</div>
  }
  if (!payload || !payload.latest) {
    return (
      <div className="flex flex-1 items-center justify-center text-sm text-[#6e6e73]">
        No desk record yet. Run the daily pipeline to write one.
      </div>
    )
  }

  const { latest, summary, changes } = payload
  const regime = latest.regime
  const grades = Object.entries(latest.grades).sort(
    (a, b) => b[1].score - a[1].score,
  )
  const briefs = latest.briefs ?? {}

  // Two names a hundredth of a point apart are not first and second, they
  // are tied, and a sorted list says otherwise. The band is 2% of the
  // book's own score range rather than a fixed number, because the score
  // is a sum of convictions with no natural unit and its spread changes
  // with the day. On a recent session the top two were 0.013 apart and
  // the first to fifth were 1.205 apart: one of those gaps means
  // something and the other does not.
  const scores = grades.map(([, g]) => g.score)
  const spread = scores.length > 1 ? scores[0] - scores[scores.length - 1] : 0
  const tieBand = spread * 0.02
  const tiedWithAbove = grades.map(([, g], i) =>
    i > 0 && grades[i - 1][1].score - g.score <= tieBand,
  )
  // Where each held name sits in that ranking, so the book can say why the
  // desk's best-liked name can be its smallest position.
  const rankOf = new Map(grades.map(([ticker], i) => [ticker, i + 1]))

  return (
    <div className="flex flex-1 flex-col gap-6 overflow-y-auto p-6">
      <header className="flex flex-wrap items-baseline justify-between gap-3">
        <div>
          <h2 className="text-xl font-semibold text-[#1d1d1f]">Desk</h2>
          <p className="text-sm text-[#6e6e73]">
            Session {latest.session} · {summary?.counts['A+'] ?? 0} A+, {summary?.counts.A ?? 0} A,{' '}
            {summary?.counts.B ?? 0} B, {summary?.counts.C ?? 0} C · book gross {summary ? pct(summary.gross) : '—'}
            {latest.paper && (
              <>
                {' '}· paper equity {money(latest.paper.equity)},{' '}
                <span className={latest.paper.pl >= 0 ? 'text-[#1e7a3a]' : 'text-[#b42318]'}>
                  P/L {money(latest.paper.pl)} ({(latest.paper.pl_pct * 100).toFixed(1)}%)
                </span>
              </>
            )}
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

      {latest.actions && latest.actions.length > 0 && (
        <ActionBoard
          actions={latest.actions}
          equity={equity ?? latest.paper?.equity ?? 100000}
          onEquity={(value) => {
            setEquity(value)
            writeEquity(value)
          }}
          untilRebalance={latest.paper?.until_rebalance ?? latest.actions[0].until_rebalance}
          live={live}
          stops={stops}
          onStops={(on) => {
            setStops(on)
            writeStops(on)
          }}
          openReason={openReason}
          onReason={(ticker) => setOpenReason(openReason === ticker ? null : ticker)}
        />
      )}

      <section className="rounded-2xl border border-black/[0.08] bg-white p-4">
        <h3 className="mb-2 text-sm font-semibold text-[#1d1d1f]">Regime</h3>
        <p className="text-sm text-[#1d1d1f]">
          Selection confidence {regime.selection_confidence.toFixed(2)} · exposure {regime.exposure.toFixed(2)} ·
          rotation leader {regime.rotation_leader} · AI participation percentile{' '}
          {Number.isFinite(regime.participation_percentile) ? regime.participation_percentile.toFixed(2) : '—'} ·
          AI-vs-software correlation {regime.ai_vs_software_correlation.toFixed(2)} · AI drawdown {pct(regime.ai_drawdown)}
        </p>
        {regime.flags.length > 0 && (
          <ul className="mt-2 space-y-1 text-sm text-[#9a6200]">
            {regime.flags.map((flag) => (
              <li key={flag}>! {flag}</li>
            ))}
          </ul>
        )}
      </section>

      {!(latest.actions && latest.actions.length > 0) && (
      <section className="rounded-2xl border border-black/[0.08] bg-white p-4">
        <h3 className="mb-2 text-sm font-semibold text-[#1d1d1f]">
          At the next open{changes?.since ? ` (since ${changes.since})` : ''}
        </h3>
        {changes && changes.orders.length > 0 ? (
          <table className="w-full text-sm">
            <thead className="text-left text-[#6e6e73]">
              <tr>
                <th className="py-1">Name</th>
                <th>Action</th>
                <th>From</th>
                <th>To</th>
                <th>Why</th>
              </tr>
            </thead>
            <tbody>
              {changes.orders.map((order) => (
                <tr key={order.ticker} className="border-t border-black/[0.05]">
                  <td className="py-1 font-medium">{order.ticker}</td>
                  <td className="capitalize">{order.action}</td>
                  <td>{pct(order.weight_from)}</td>
                  <td>{pct(order.weight_to)}</td>
                  <td className="text-[#6e6e73]">{order.reason}</td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <p className="text-sm text-[#6e6e73]">
            {changes?.since
              ? 'Nothing to trade: the book is unchanged.'
              : 'This is the first session on file, so there is nothing to compare it with. The book below is the desk’s target, not a list of trades. A second session gives this table something to say.'}
          </p>
        )}
        {changes && (changes.upgrades.length > 0 || changes.downgrades.length > 0) && (
          <p className="mt-2 text-sm text-[#6e6e73]">
            {changes.upgrades.length > 0 && (
              <>Upgrades: {changes.upgrades.map((m) => `${m.ticker} ${m.from}→${m.to}`).join(', ')}. </>
            )}
            {changes.downgrades.length > 0 && (
              <>Downgrades: {changes.downgrades.map((m) => `${m.ticker} ${m.from}→${m.to}`).join(', ')}.</>
            )}
          </p>
        )}
      </section>
      )}

      <button
        type="button"
        onClick={() => setDetails(!details)}
        className="self-start text-sm text-[#0071e3] hover:underline"
      >
        {details ? 'Hide the paper account, the book and every grade' : 'Show the paper account, the book and every grade'}
      </button>

      {details && (
      <>

      {latest.paper && (
        <section className="rounded-2xl border border-black/[0.08] bg-white p-4">
          <h3 className="mb-2 text-sm font-semibold text-[#1d1d1f]">Paper account</h3>
          <p className="text-sm text-[#1d1d1f]">
            Equity {money(latest.paper.equity)} · cash {money(latest.paper.cash)} ·{' '}
            <span className={latest.paper.pl >= 0 ? 'text-[#1e7a3a]' : 'text-[#b42318]'}>
              P/L {money(latest.paper.pl)} ({(latest.paper.pl_pct * 100).toFixed(1)}%)
            </span>{' '}
            since the paper book started · {latest.paper.plan} day
          </p>
          {latest.paper.orders.length > 0 && (
            <p className="mt-2 text-sm text-[#6e6e73]">
              Submitted for the next open:{' '}
              {latest.paper.orders.map((o) => `${o.side} ${o.qty} ${o.symbol}`).join(', ')}
            </p>
          )}
          {latest.paper.positions.length > 0 && (
            <table className="mt-2 w-full text-sm">
              <thead className="text-left text-[#6e6e73]">
                <tr>
                  <th className="py-1">Name</th>
                  <th>Shares</th>
                  <th>Value</th>
                  <th>Entry</th>
                  <th>Last</th>
                  <th>Open P/L</th>
                </tr>
              </thead>
              <tbody>
                {latest.paper.positions.map((p) => (
                  <tr key={p.symbol} className="border-t border-black/[0.05]">
                    <td className="py-1 font-medium">{p.symbol}</td>
                    <td>{p.qty}</td>
                    <td>{money(p.market_value)}</td>
                    <td>{money(p.avg_entry_price)}</td>
                    <td>{money(p.current_price)}</td>
                    <td className={p.unrealized_pl >= 0 ? 'text-[#1e7a3a]' : 'text-[#b42318]'}>
                      {money(p.unrealized_pl)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </section>
      )}

      <section className="rounded-2xl border border-black/[0.08] bg-white p-4">
        <h3 className="mb-2 text-sm font-semibold text-[#1d1d1f]">The book</h3>
        <p className="mb-2 text-xs text-[#6e6e73]">
          Rank is where the name sits in the desk&rsquo;s conviction ordering; weight is
          what it actually holds. They disagree on purpose &mdash; a name is sized by the
          inverse of its volatility, so the desk&rsquo;s best-liked name can be its
          smallest position when it is also its wildest.
        </p>
        <table className="w-full text-sm">
          <thead className="text-left text-[#6e6e73]">
            <tr>
              <th className="py-1">Name</th>
              <th>Rank</th>
              <th>Grade</th>
              <th>Weight</th>
              <th>Volatility</th>
            </tr>
          </thead>
          <tbody>
            {latest.book.map((row) => (
              <tr key={row.ticker} className="border-t border-black/[0.05]">
                <td className="py-1 font-medium">{row.ticker}</td>
                <td className="font-mono text-xs text-[#6e6e73]">
                  {rankOf.get(row.ticker) ?? '—'}
                </td>
                <td>
                  <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${GRADE_STYLE[row.grade] ?? ''}`}>
                    {row.grade}
                  </span>
                </td>
                <td>{pct(row.weight)}</td>
                <td className={row.volatility >= 1 ? 'text-[#b42318]' : undefined}>
                  {pct(row.volatility)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>

      <section className="rounded-2xl border border-black/[0.08] bg-white p-4">
        <h3 className="mb-2 text-sm font-semibold text-[#1d1d1f]">Every grade</h3>
        <p className="mb-2 text-xs text-[#6e6e73]">F fundamental · T technical · S sentiment · R rotation; + bullish, · neutral, − bearish</p>
        <table className="w-full text-sm">
          <thead className="text-left text-[#6e6e73]">
            <tr>
              <th className="py-1">Name</th>
              <th>Side</th>
              <th>Grade</th>
              <th>Conviction</th>
              <th>F</th>
              <th>T</th>
              <th>S</th>
              <th>R</th>
              <th>Why</th>
            </tr>
          </thead>
          <tbody>
            {grades.map(([ticker, g], i) => (
              <tr key={ticker} className="border-t border-black/[0.05] align-top">
                <td className="py-1 font-medium">{ticker}</td>
                <td className="text-[#6e6e73]">{g.side}</td>
                <td>
                  <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${GRADE_STYLE[g.grade] ?? ''}`}>{g.grade}</span>
                </td>
                <td className="whitespace-nowrap font-mono text-xs">
                  {g.score.toFixed(2)}
                  {tiedWithAbove[i] && (
                    <span className="ml-1 text-[#6e6e73]" title="too close to the name above to call it a difference">tied</span>
                  )}
                </td>
                {(['fundamental', 'technical', 'sentiment', 'rotation'] as const).map((k) => (
                  <td key={k} className="font-mono">{STANCE_MARK[g.stances[k] ?? 0]}</td>
                ))}
                <td>
                  {briefs[ticker] || g.headline ? (
                    <button
                      type="button"
                      onClick={() => setOpenBrief(openBrief === ticker ? null : ticker)}
                      className="text-left text-[#0071e3] hover:underline"
                    >
                      {openBrief === ticker
                        ? 'hide'
                        : (briefs[ticker]?.verdict ?? g.headline)}
                    </button>
                  ) : (
                    <span className="text-[#6e6e73]">—</span>
                  )}
                  {openBrief === ticker && (
                    <div className="mt-1 space-y-1 text-xs text-[#1d1d1f]">
                      {g.reason && <p>{g.reason}</p>}
                      {briefs[ticker] && (
                        <>
                          <p>{briefs[ticker].reasoning}</p>
                          <p><span className="font-medium">Risks:</span> {briefs[ticker].risks}</p>
                          <p><span className="font-medium">Watch:</span> {briefs[ticker].watch}</p>
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
      </>
      )}
    </div>
  )
}

interface ActionBoardProps {
  actions: DeskAction[]
  equity: number
  onEquity: (value: number) => void
  untilRebalance: number
  live: DeskLive
  stops: boolean
  onStops: (on: boolean) => void
  openReason: string | null
  onReason: (ticker: string) => void
}

const TRIGGER_ORDER: [string, string][] = [
  ['fundamental', 'F'],
  ['technical', 'T'],
  ['sentiment', 'S'],
  ['value', 'V'],
  ['rotation', 'R'],
]

// The analysts behind the grade, as marks: + bullish, · neutral, − bearish.
const triggers = (stances: Record<string, number>) =>
  TRIGGER_ORDER.filter(([k]) => k in stances)
    .map(([k, letter]) => `${letter}${STANCE_MARK[stances[k] ?? 0]}`)
    .join(' ')

// What the measurements say about when to fill: buys at the open, sells at
// the close in four of five years and not in 2026, so the open until the
// paper record says otherwise.
const timing = (a: DeskAction) =>
  a.action === 'sell' || a.action === 'trim'
    ? 'open (close was better 2022–25, not 2026)'
    : 'open'

// The candle's verdict on a row: the last print against the close and,
// for a name held, against its entry. The stop level appears only when the
// person has switched stops on, and is red when crossed.
const liveCell = (a: DeskAction, stops: boolean, quote?: { last: number; open: number; high: number }) => {
  if (!quote) return null
  const versusClose = a.last_close > 0 ? quote.last / a.last_close - 1 : 0
  const sinceOpen = quote.open > 0 ? quote.last / quote.open - 1 : 0
  const versusEntry = a.entry_price && a.entry_price > 0 ? quote.last / a.entry_price - 1 : null
  const trailing = stops && a.stops['12'] !== undefined ? Math.max(a.high_20, quote.high) * 0.88 : undefined
  const hit = trailing !== undefined && quote.last <= trailing
  return (
    <span className={hit ? 'font-medium text-[#b42318]' : undefined}>
      {money(quote.last)} ({sinceOpen >= 0 ? '+' : ''}{(sinceOpen * 100).toFixed(1)}% since the open,{' '}
      {versusClose >= 0 ? '+' : ''}{(versusClose * 100).toFixed(1)}% on the close
      {versusEntry !== null && `, ${versusEntry >= 0 ? '+' : ''}${(versusEntry * 100).toFixed(1)}% on entry`})
      {trailing !== undefined && (
        <span className="text-[#6e6e73]">
          {' '}· {hit ? 'STOP HIT' : `room ${((quote.last / trailing - 1) * 100).toFixed(1)}% to ${money(trailing)}`}
        </span>
      )}
    </span>
  )
}

// What to do at the next open, most urgent first: sells and trims before
// buys and adds, holds last. Every row carries the size at the equity
// typed above, the entry, and the exit plan - the rebalance clock, how far
// the grade sits above the line, and the stop levels off the twenty-session
// high for a person managing their own tail.
const ActionBoard = ({ actions, equity, onEquity, untilRebalance, live, stops, onStops, openReason, onReason }: ActionBoardProps) => {
  const trades = actions.filter((a) => a.action !== 'hold')
  const holds = actions.filter((a) => a.action === 'hold')
  const row = (a: DeskAction) => {
    const qty = shares(Math.abs(a.delta_weight), equity, a.last_close)
    const atRisk = a.grade_margin <= 0 && a.target_weight > 0
    return (
      <tr key={a.ticker} className="border-t border-black/[0.05] align-top">
        <td className="py-1.5 font-medium">{a.ticker}</td>
        <td>
          <span className={`rounded-full px-2 py-0.5 text-xs font-medium uppercase ${ACTION_STYLE[a.action] ?? ''}`}>
            {a.action}
          </span>
        </td>
        <td className="whitespace-nowrap">
          {a.action === 'hold' ? (
            <span>{pct(a.current_weight)}</span>
          ) : (
            <span>
              <span className="font-medium">{qty.toLocaleString()} sh</span>{' '}
              <span className="text-[#6e6e73]">
                {pct(a.current_weight)} → {pct(a.target_weight)}
              </span>
            </span>
          )}
        </td>
        <td className="whitespace-nowrap text-[#6e6e73]">
          {timing(a)} · close {money(a.last_close)}
          {live.quotes[a.ticker] && <div className="text-xs">{liveCell(a, stops, live.quotes[a.ticker])}</div>}
        </td>
        <td className="whitespace-nowrap">
          <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${GRADE_STYLE[a.grade] ?? ''}`}>{a.grade}</span>
          <span className="ml-1 font-mono text-xs text-[#6e6e73]">#{a.rank ?? '—'}</span>
          {atRisk && (
            <span className="ml-1 text-xs text-[#9a6200]" title="one bearish stance from losing its grade">at risk</span>
          )}
        </td>
        <td className="whitespace-nowrap text-xs text-[#6e6e73]">
          {a.target_weight > 0 ? (
            <>
              leaves when the grade falls below A
              <br />
              next rebalance in {untilRebalance}
              {stops && a.stops['12'] !== undefined && (
                <>
                  <br />
                  stop 12% {money(a.stops['12'])}
                  <span title={`8% ${money(a.stops['8'])}, 20% ${money(a.stops['20'])}, off the 20-session high ${money(a.high_20)}`}>
                    {' '}▾
                  </span>
                </>
              )}
            </>
          ) : (
            'out of the book'
          )}
        </td>
        <td className="text-xs text-[#6e6e73]">
          <span className="font-mono text-[#1d1d1f]" title="F fundamental · T technical · S sentiment · V value · R rotation">
            {triggers(a.stances ?? {})}
          </span>
          {' '}
          {a.reason ? (
            <button type="button" onClick={() => onReason(a.ticker)} className="text-left text-[#0071e3] hover:underline">
              {openReason === a.ticker ? 'hide' : a.why || 'why'}
            </button>
          ) : (
            a.why
          )}
          {openReason === a.ticker && <p className="mt-1 text-[#1d1d1f]">{a.reason}</p>}
        </td>
      </tr>
    )
  }
  return (
    <section className="rounded-2xl border border-black/[0.08] bg-white p-4">
      <div className="mb-2 flex flex-wrap items-baseline justify-between gap-3">
        <h3 className="text-sm font-semibold text-[#1d1d1f]">
          Action board · next open
          {live.as_of && (
            <span className="ml-2 text-xs font-normal text-[#6e6e73]">
              live candle {new Date(live.as_of).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
            </span>
          )}
        </h3>
        <label className="flex items-center gap-2 text-xs text-[#6e6e73]">
          <input type="checkbox" checked={stops} onChange={(e) => onStops(e.target.checked)} />
          show stop levels
        </label>
        <label className="flex items-center gap-2 text-xs text-[#6e6e73]">
          size to equity
          <input
            type="number"
            min={0}
            step={1000}
            value={Math.round(equity)}
            onChange={(e) => onEquity(Number(e.target.value) || 0)}
            className="w-28 rounded-md border border-black/[0.12] px-2 py-1 text-right text-sm text-[#1d1d1f]"
          />
        </label>
      </div>
      <table className="w-full text-sm">
        <thead className="text-left text-[#6e6e73]">
          <tr>
            <th className="py-1">Name</th>
            <th>Do</th>
            <th>Size</th>
            <th>Entry</th>
            <th>Grade</th>
            <th>Exit plan</th>
            <th>Triggers · why</th>
          </tr>
        </thead>
        <tbody>
          {trades.map(row)}
          {holds.map(row)}
        </tbody>
      </table>
      <p className="mt-2 text-xs text-[#6e6e73]">
        Sizes are shares at the equity above, entered market-on-open: every later schedule measured
        cost more. The exit is the signal, not a price: a name leaves at a rebalance when it no
        longer earns its grade, because every price-based exit tested in this book cost mean
        return. Stop levels are off by default for that reason. They are not hunted &mdash; a
        wick through a level and a close through it are followed by the same flat ten sessions
        &mdash; they simply cut winners&rsquo; drawdowns along with losers&rsquo;: after a sharp
        rise a 12% stop cut the worst tenth from &minus;25% to &minus;16% and the average from
        +9% to +4%. Switch them on if your size needs the tail cut.
      </p>
    </section>
  )
}

export default DeskPanel
