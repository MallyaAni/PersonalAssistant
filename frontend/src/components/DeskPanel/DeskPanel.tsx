import { useEffect, useState } from 'react'
import { RefreshCw } from 'lucide-react'
import {
  getDesk,
  getDeskHoldings,
  getDeskLive,
  getDeskMine,
  putDeskHoldings,
  type DeskAction,
  type DeskHolding,
  type DeskLive,
  type DeskMineRow,
  type DeskPayload,
} from '../../services/api'

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

// The desk's warnings in plain words. Any flag not listed shows as written.
const FLAG_WORDS: Record<string, string> = {
  'not enough history to judge participation': 'too little history to judge how broad the AI rally is',
  'participation below its two-year median': 'fewer AI names are rising than usual: the rally is narrow',
  'participation in its top quintile (hype)': 'almost every AI name is rising at once, which often marks a top',
  'AI-vs-software co-movement far from its history': 'AI and software stocks are moving together unusually, so the usual patterns may not hold',
  'theme co-movement structure has changed shape': 'the way these stocks move together has changed, so the desk trusts its picks less',
  'AI basket more than 25% off its yearly high': 'AI stocks are more than 25% below their high for the year',
  'the ten-year yield is rising sharply': 'interest rates are rising fast, which usually hurts these stocks',
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
  const [holdings, setHoldings] = useState<DeskHolding[]>([])
  const [mine, setMine] = useState<DeskMineRow[]>([])
  const [holdingsError, setHoldingsError] = useState('')
  const [help, setHelp] = useState(false)
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

  // The person's own positions, and the board against them at the equity
  // typed in, refreshed with the candle.
  useEffect(() => {
    void (async () => {
      try {
        setHoldings(await getDeskHoldings(userId))
      } catch {
        // none saved yet
      }
    })()
  }, [userId])
  const equityForMine = equity ?? payload?.latest?.paper?.equity ?? 100000
  useEffect(() => {
    if (holdings.length === 0) {
      setMine([])
      return
    }
    const poll = async () => {
      try {
        setMine(await getDeskMine(userId, equityForMine))
      } catch {
        // the paper board stands
      }
    }
    void poll()
    const timer = window.setInterval(() => void poll(), CANDLE_MS)
    return () => window.clearInterval(timer)
  }, [userId, holdings, equityForMine])

  if (loading) {
    return <div className="flex flex-1 items-center justify-center text-sm text-[#6e6e73]">Loading the desk…</div>
  }
  if (error) {
    return <div className="flex flex-1 items-center justify-center text-sm text-[#b42318]">{error}</div>
  }
  if (!payload || !payload.latest) {
    return (
      <div className="flex flex-1 items-center justify-center text-sm text-[#6e6e73]">
        No decision on file yet. The desk writes one every evening after the close.
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
          </div>
          {help && <HowToUse onClose={() => setHelp(false)} />}
          <p className="text-sm text-[#6e6e73]">
            Decision from the close of {latest.session} · grades: {summary?.counts['A+'] ?? 0} A+,{' '}
            {summary?.counts.A ?? 0} A, {summary?.counts.B ?? 0} B, {summary?.counts.C ?? 0} C · invested{' '}
            {summary ? pct(summary.gross) : '—'} of the account
            {latest.paper && (
              <>
                {' '}· practice account {money(latest.paper.equity)},{' '}
                <span className={latest.paper.pl >= 0 ? 'text-[#1e7a3a]' : 'text-[#b42318]'}>
                  {latest.paper.pl >= 0 ? 'up' : 'down'} {money(Math.abs(latest.paper.pl))} ({(latest.paper.pl_pct * 100).toFixed(1)}%)
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

      <MyAccount
        holdings={holdings}
        rows={mine}
        equity={equityForMine}
        stops={stops}
        error={holdingsError}
        onSave={async (rows) => {
          try {
            setHoldings(await putDeskHoldings(userId, rows))
            setHoldingsError('')
          } catch (err) {
            setHoldingsError(err instanceof Error ? err.message : 'The holdings were not saved.')
          }
        }}
      />

      <section className="rounded-2xl border border-black/[0.08] bg-white p-4">
        <h3 className="mb-2 text-sm font-semibold text-[#1d1d1f]">Market backdrop</h3>
        <p className="text-sm text-[#1d1d1f]">
          Leading group: {regime.rotation_leader === 'ai' ? 'AI' : regime.rotation_leader === 'software' ? 'software' : 'no clear leader'} ·
          the desk is {pct(regime.exposure)} invested ·
          AI names are {pct(regime.ai_drawdown)} below their yearly high ·
          breadth of the AI rally{' '}
          {Number.isFinite(regime.participation_percentile)
            ? `${Math.round(regime.participation_percentile * 100)}th percentile of the last two years`
            : 'unknown'}{' '}
          · AI and software moving together: {regime.ai_vs_software_correlation.toFixed(2)} (1 is lockstep, 0 is unrelated) ·
          confidence in today&rsquo;s picks {Math.round(regime.selection_confidence * 100)}%
        </p>
        {regime.flags.length > 0 && (
          <ul className="mt-2 space-y-1 text-sm text-[#9a6200]">
            {regime.flags.map((flag) => (
              <li key={flag}>Warning: {FLAG_WORDS[flag] ?? flag}</li>
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
                <th>Do</th>
                <th>Now</th>
                <th>Target</th>
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
              ? 'Nothing to trade today: the desk holds the same names as yesterday.'
              : 'This is the first day on file, so there is nothing to compare it with. The list below is what the desk wants to hold, not a list of trades. Tomorrow this table will show the changes.'}
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
        {details ? 'Hide the details' : 'Show the details: practice account, holdings and every grade'}
      </button>

      {details && (
      <>

      {latest.paper && (
        <section className="rounded-2xl border border-black/[0.08] bg-white p-4">
          <h3 className="mb-2 text-sm font-semibold text-[#1d1d1f]">Practice account</h3>
          <p className="mb-1 text-xs text-[#6e6e73]">
            A simulated account that follows the desk&rsquo;s decisions with real market prices and no real money.
          </p>
          <p className="text-sm text-[#1d1d1f]">
            Worth {money(latest.paper.equity)} · cash {money(latest.paper.cash)} ·{' '}
            <span className={latest.paper.pl >= 0 ? 'text-[#1e7a3a]' : 'text-[#b42318]'}>
              {latest.paper.pl >= 0 ? 'up' : 'down'} {money(Math.abs(latest.paper.pl))} ({(latest.paper.pl_pct * 100).toFixed(1)}%)
            </span>{' '}
            since it started ·{' '}
            {latest.paper.plan === 'rebalance'
              ? 'today the desk re-checked every grade and reset the sizes'
              : latest.paper.plan === 'exits'
                ? 'today only names that lost their grade are sold'
                : 'nothing to trade today'}
          </p>
          {latest.paper.orders.length > 0 && (
            <p className="mt-2 text-sm text-[#6e6e73]">
              Orders placed for the next open:{' '}
              {latest.paper.orders.map((o) => `${o.side} ${o.qty} ${o.symbol}`).join(', ')}
            </p>
          )}
          {latest.paper.positions.length > 0 && (
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
        <h3 className="mb-2 text-sm font-semibold text-[#1d1d1f]">What the desk holds</h3>
        <p className="mb-2 text-xs text-[#6e6e73]">
          Rank is how much the desk likes the name (1 is best). Share of account is how much it holds.
          The two differ on purpose: steadier names get more money and wilder names get less, so the
          best-liked name can be the smallest position when it is also the most volatile.
        </p>
        <table className="w-full text-sm">
          <thead className="text-left text-[#6e6e73]">
            <tr>
              <th className="py-1">Name</th>
              <th>Rank</th>
              <th>Grade</th>
              <th>Share of account</th>
              <th>Volatility (a year)</th>
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
        <p className="mb-2 text-xs text-[#6e6e73]">
          Every name the desk follows, best first. The four columns are the analysts: F business fundamentals,
          T price trend, S news and sentiment, R which group is leading. + means for, · no view, − against.
        </p>
        <table className="w-full text-sm">
          <thead className="text-left text-[#6e6e73]">
            <tr>
              <th className="py-1">Name</th>
              <th>Group</th>
              <th>Grade</th>
              <th>Score</th>
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
                <td className="text-[#6e6e73]">{g.side === 'ai' ? 'AI' : g.side}</td>
                <td>
                  <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${GRADE_STYLE[g.grade] ?? ''}`}>{g.grade}</span>
                </td>
                <td className="whitespace-nowrap font-mono text-xs">
                  {g.score.toFixed(2)}
                  {tiedWithAbove[i] && (
                    <span className="ml-1 text-[#6e6e73]" title="so close to the name above that the order means nothing">tied</span>
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
const timing = (_a: DeskAction) => 'at the open'

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
      now {money(quote.last)} · {sinceOpen >= 0 ? '+' : ''}{(sinceOpen * 100).toFixed(1)}% today ·{' '}
      {versusClose >= 0 ? '+' : ''}{(versusClose * 100).toFixed(1)}% vs yesterday&rsquo;s close
      {versusEntry !== null && ` · ${versusEntry >= 0 ? '+' : ''}${(versusEntry * 100).toFixed(1)}% vs what was paid`}
      {trailing !== undefined && (
        <span className="text-[#6e6e73]">
          {' '}· {hit ? 'below the stop: sell' : `stop ${money(trailing)}, ${((quote.last / trailing - 1) * 100).toFixed(1)}% below the price`}
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
            <span>{pct(a.current_weight)} of the account</span>
          ) : (
            <span>
              <span className="font-medium">{qty.toLocaleString()} shares</span>{' '}
              <span className="text-[#6e6e73]">
                ({pct(a.current_weight)} → {pct(a.target_weight)} of the account)
              </span>
            </span>
          )}
        </td>
        <td className="whitespace-nowrap text-[#6e6e73]">
          {timing(a)} · last close {money(a.last_close)}
          {live.quotes[a.ticker] && <div className="text-xs">{liveCell(a, stops, live.quotes[a.ticker])}</div>}
        </td>
        <td className="whitespace-nowrap">
          <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${GRADE_STYLE[a.grade] ?? ''}`}>{a.grade}</span>
          <span className="ml-1 font-mono text-xs text-[#6e6e73]">#{a.rank ?? '—'}</span>
          {atRisk && (
            <span className="ml-1 text-xs text-[#9a6200]" title="one more analyst turning against it would drop the grade below A">at risk</span>
          )}
        </td>
        <td className="whitespace-nowrap text-xs text-[#6e6e73]">
          {a.target_weight > 0 ? (
            <>
              sell when its grade drops below A
              <br />
              next grade check in {untilRebalance} trading day{untilRebalance === 1 ? '' : 's'}
              {stops && a.stops['12'] !== undefined && (
                <>
                  <br />
                  stop {money(a.stops['12'])}
                  <span title={`12% under the 20-day high of ${money(a.high_20)}. Tighter: ${money(a.stops['8'])} (8%). Looser: ${money(a.stops['20'])} (20%).`}>
                    {' '}▾
                  </span>
                </>
              )}
            </>
          ) : (
            'sell everything: it no longer earns an A'
          )}
        </td>
        <td className="text-xs text-[#6e6e73]">
          <span className="font-mono text-[#1d1d1f]" title="The analysts: F business fundamentals, T price trend, S news and sentiment, V price vs value, R which group leads. + for, · no view, − against.">
            {triggers(a.stances ?? {})}
          </span>
          {' '}
          {a.reason ? (
            <button type="button" onClick={() => onReason(a.ticker)} className="text-left text-[#0071e3] hover:underline">
              {openReason === a.ticker ? 'hide' : a.why || 'why?'}
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
          What to do at the next open
          {live.as_of && (
            <span className="ml-2 text-xs font-normal text-[#6e6e73]">
              prices as of {new Date(live.as_of).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}, refreshed every 15 minutes
            </span>
          )}
        </h3>
        <label className="flex items-center gap-2 text-xs text-[#6e6e73]">
          <input type="checkbox" checked={stops} onChange={(e) => onStops(e.target.checked)} />
          show stop levels
        </label>
        <label className="flex items-center gap-2 text-xs text-[#6e6e73]">
          account size $
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
            <th>How much</th>
            <th>When and price</th>
            <th>Grade</th>
            <th>When to sell</th>
            <th>Why</th>
          </tr>
        </thead>
        <tbody>
          {trades.map(row)}
          {holds.map(row)}
        </tbody>
      </table>
      <p className="mt-2 text-xs text-[#6e6e73]">
        Share counts are for the account size above and assume you buy at the open, which was the best time
        we measured. Names are sold on grade, not price: a name leaves when it no longer earns an A at the
        next check. Stops are off by default because in our tests they cut short the winners as often as
        the losers. Switch them on if you need a hard limit on how much one name can lose.
        The letters under Why are the analysts: F business fundamentals, T price trend, S news and sentiment,
        V price vs value, R which group leads. + for, · no view, − against. Click a reason to read it in full.
      </p>
    </section>
  )
}

// The one-screen explanation for someone who has never seen the page.
const HowToUse = ({ onClose }: { onClose: () => void }) => (
  <div className="my-2 max-w-xl rounded-xl border border-black/[0.08] bg-[#f5f5f7] p-4 text-sm text-[#1d1d1f]">
    <ol className="list-decimal space-y-1.5 pl-5">
      <li>
        <b>Every evening</b> the desk grades about ninety AI and software stocks and picks the A-rated ones to
        own. That decision holds for the next trading day.
      </li>
      <li>
        <b>Your account:</b> type or paste what you hold on Schwab. The table then says, name by name,{' '}
        <b>buy, add, trim, sell or hold</b>, and how many shares for your account size.
      </li>
      <li>
        <b>Buy at the open</b> with a market order. Do not chase a name that has already jumped.
      </li>
      <li>
        <b>Selling:</b> a name is sold when its grade drops below A at the next check, about every four weeks.
        Each row says when that check is. Stops are optional: switch them on to see a price under which to sell.
      </li>
      <li>
        <b>Prices</b> refresh every 15 minutes during market hours. Gains are measured from what you paid.
      </li>
      <li>
        <b>Why:</b> the letters are the analysts (F business fundamentals, T price trend, S news and sentiment,
        V price vs value, R which group leads). Click the reason to read it in full.
      </li>
    </ol>
    <button type="button" onClick={onClose} className="mt-3 text-xs text-[#0071e3] hover:underline">
      close
    </button>
  </div>
)

interface MyAccountProps {
  holdings: DeskHolding[]
  rows: DeskMineRow[]
  equity: number
  stops: boolean
  error: string
  onSave: (rows: DeskHolding[]) => Promise<void>
}

// The person's own account: the positions they typed in, and the board
// against them. Sells and trims first, then buys and adds, then holds; a
// name the desk does not rate keeps its row with the risk facts and
// "outside the book", so the exit question is answered for it too.
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

const MyAccount = ({ holdings, rows, equity, stops, error, onSave }: MyAccountProps) => {
  const [draft, setDraft] = useState<DeskHolding[]>(holdings)
  const [editing, setEditing] = useState(holdings.length === 0)
  const [pasted, setPasted] = useState('')
  const [skipped, setSkipped] = useState<string[]>([])
  useEffect(() => {
    setDraft(holdings)
    if (holdings.length > 0) setEditing(false)
  }, [holdings])
  const update = (i: number, key: keyof DeskHolding, value: string) =>
    setDraft(draft.map((h, j) => (j === i ? { ...h, [key]: key === 'ticker' || key === 'entry_date' ? value : Number(value) } : h)))
  return (
    <section className="rounded-2xl border border-black/[0.08] bg-white p-4">
      <div className="mb-2 flex flex-wrap items-baseline justify-between gap-3">
        <h3 className="text-sm font-semibold text-[#1d1d1f]">Your account</h3>
        <button type="button" onClick={() => setEditing(!editing)} className="text-xs text-[#0071e3] hover:underline">
          {editing ? 'done' : 'edit positions'}
        </button>
      </div>
      {editing && (
        <div className="mb-3 space-y-2 text-sm">
          {draft.map((h, i) => (
            <div key={i} className="flex flex-wrap items-center gap-2">
              <input value={h.ticker} onChange={(e) => update(i, 'ticker', e.target.value)} placeholder="ticker" className="w-20 rounded-md border border-black/[0.12] px-2 py-1" />
              <input type="number" value={h.shares} onChange={(e) => update(i, 'shares', e.target.value)} placeholder="shares" className="w-24 rounded-md border border-black/[0.12] px-2 py-1" />
              <input type="number" value={h.entry_price} onChange={(e) => update(i, 'entry_price', e.target.value)} placeholder="cost per share" className="w-28 rounded-md border border-black/[0.12] px-2 py-1" />
              <input type="date" value={h.entry_date} onChange={(e) => update(i, 'entry_date', e.target.value)} className="rounded-md border border-black/[0.12] px-2 py-1" />
              <button type="button" onClick={() => setDraft(draft.filter((_, j) => j !== i))} className="text-xs text-[#b42318] hover:underline">remove</button>
            </div>
          ))}
          <div className="space-y-1">
            <textarea
              value={pasted}
              onChange={(e) => setPasted(e.target.value)}
              placeholder={'or paste one line per position: ticker, shares, cost per share, date bought (optional)\nIREN 100 35.20 2026-08-28'}
              rows={3}
              className="w-full rounded-md border border-black/[0.12] px-2 py-1 font-mono text-xs"
            />
            <div className="flex flex-wrap items-center gap-3">
              <button
                type="button"
                onClick={() => {
                  const parsed = parsePasted(pasted)
                  const kept = draft.filter((h) => !parsed.rows.some((r) => r.ticker === h.ticker.toUpperCase()))
                  setDraft([...kept, ...parsed.rows])
                  setSkipped(parsed.skipped)
                  if (parsed.rows.length > 0) setPasted('')
                }}
                className="text-xs text-[#0071e3] hover:underline"
              >
                add pasted lines
              </button>
              {skipped.length > 0 && <span className="text-xs text-[#b42318]">could not read these lines: {skipped.join(' | ')}</span>}
            </div>
          </div>
          <div className="flex gap-3">
            <button type="button" onClick={() => setDraft([...draft, { ticker: '', shares: 0, entry_price: 0, entry_date: new Date().toISOString().slice(0, 10) }])} className="text-xs text-[#0071e3] hover:underline">add a position</button>
            <button type="button" onClick={() => void onSave(draft)} className="rounded-full bg-[#1d1d1f] px-3 py-1 text-xs text-white">save</button>
          </div>
          {error && <p className="text-xs text-[#b42318]">{error}</p>}
        </div>
      )}
      {holdings.length === 0 && !editing && (
        <p className="text-sm text-[#6e6e73]">No positions yet. Enter what you hold on Schwab and this table will say what to buy and sell.</p>
      )}
      {rows.length > 0 && (
        <table className="w-full text-sm">
          <thead className="text-left text-[#6e6e73]">
            <tr>
              <th className="py-1">Name</th>
              <th>Do</th>
              <th>How much</th>
              <th>You hold</th>
              <th>Grade</th>
              <th>When to sell</th>
              <th>Why</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => {
              const qty = r.last && r.last > 0 ? Math.round((Math.abs(r.delta_weight) * equity) / r.last) : 0
              const trailing = stops && r.high_20 && r.last ? Math.max(r.high_20, r.last) * 0.88 : null
              const hit = trailing !== null && r.last !== null && r.last <= trailing
              return (
                <tr key={r.ticker} className="border-t border-black/[0.05] align-top">
                  <td className="py-1.5 font-medium">{r.ticker}</td>
                  <td>
                    <span className={`rounded-full px-2 py-0.5 text-xs font-medium uppercase ${ACTION_STYLE[r.action] ?? ''}`}>{r.action}</span>
                  </td>
                  <td className="whitespace-nowrap">
                    {r.action === 'hold' ? `${pct(r.current_weight)} of the account` : (
                      <span><span className="font-medium">{qty.toLocaleString()} shares</span> <span className="text-[#6e6e73]">({pct(r.current_weight)} → {pct(r.target_weight)} of the account)</span></span>
                    )}
                  </td>
                  <td className="whitespace-nowrap text-xs text-[#6e6e73]">
                    {r.shares > 0 ? (
                      <>
                        {r.shares} shares at {money(r.entry_price ?? 0)}
                        {r.pl_pct !== null && (
                          <span className={r.pl_pct >= 0 ? ' text-[#1e7a3a]' : ' text-[#b42318]'}> {r.pl_pct >= 0 ? '+' : ''}{(r.pl_pct * 100).toFixed(1)}%</span>
                        )}
                        {r.last !== null && <div className={hit ? 'font-medium text-[#b42318]' : ''}>now {money(r.last)}{hit ? ' · below the stop: sell' : trailing !== null ? ` · stop ${money(trailing)}` : ''}</div>}
                      </>
                    ) : '—'}
                  </td>
                  <td className="whitespace-nowrap">
                    {r.in_book ? (
                      <>
                        <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${GRADE_STYLE[r.grade] ?? ''}`}>{r.grade}</span>
                        <span className="ml-1 font-mono text-xs text-[#6e6e73]">#{r.rank ?? '—'}</span>
                      </>
                    ) : (
                      <span className="text-xs text-[#6e6e73]">not covered</span>
                    )}
                  </td>
                  <td className="whitespace-nowrap text-xs text-[#6e6e73]">
                    {r.leaves_if}
                    {r.until_rebalance !== null && r.target_weight > 0 && <><br />next grade check in {r.until_rebalance} trading day{r.until_rebalance === 1 ? '' : 's'}</>}
                  </td>
                  <td className="text-xs text-[#6e6e73]">
                    {r.in_book && <span className="font-mono text-[#1d1d1f]">{triggers(r.stances ?? {})} </span>}
                    {r.why}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      )}
    </section>
  )
}

export default DeskPanel
