import { useEffect, useState } from 'react'
import { RefreshCw } from 'lucide-react'
import {
  getDesk,
  getDeskHoldings,
  getDeskLive,
  getDeskMine,
  putDeskHoldings,
  type DeskHolding,
  type DeskLive,
  type DeskMineRow,
  type DeskPayload,
  type DeskQuote,
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
const triggers = (stances: Record<string, number>) =>
  TRIGGER_ORDER.filter(([k]) => k in stances)
    .map(([k, letter]) => `${letter}${STANCE_MARK[stances[k] ?? 0]}`)
    .join(' ')

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
  const [holdings, setHoldings] = useState<DeskHolding[]>([])
  const [rows, setRows] = useState<DeskMineRow[]>([])
  const [equity, setEquity] = useState<number>(() => Number(readStored(EQUITY_KEY)) || 100000)
  const [stops, setStops] = useState(() => readStored(STOPS_KEY) === 'on')
  const [help, setHelp] = useState(false)
  const [details, setDetails] = useState(false)
  const [editing, setEditing] = useState(false)
  const [saveError, setSaveError] = useState('')
  const [openReason, setOpenReason] = useState<string | null>(null)

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

  // The board and the candle, together, every fifteen minutes.
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
  if (!payload || !payload.latest) {
    return (
      <div className="flex flex-1 items-center justify-center text-sm text-[#6e6e73]">
        No decision on file yet. The desk writes one every evening after the close.
      </div>
    )
  }

  const { latest, summary } = payload
  const paper = latest.paper
  const warnings = latest.regime.flags

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
          </div>
          {help && <HowToUse onClose={() => setHelp(false)} />}
          <p className="text-sm text-[#6e6e73]">
            Decision from the close of {latest.session} · the desk is {summary ? pct(summary.gross) : '—'} invested
            {paper && (
              <>
                {' '}· practice account{' '}
                <span className={paper.pl >= 0 ? 'text-[#1e7a3a]' : 'text-[#b42318]'}>
                  {paper.pl >= 0 ? 'up' : 'down'} {money(Math.abs(paper.pl))} ({(paper.pl_pct * 100).toFixed(1)}%)
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
              try {
                setHoldings(await putDeskHoldings(userId, next))
                setSaveError('')
                setEditing(false)
              } catch (err) {
                setSaveError(err instanceof Error ? err.message : 'The positions were not saved.')
              }
            }}
          />
        )}
        {holdings.length === 0 && !editing && (
          <p className="mb-2 text-xs text-[#6e6e73]">
            No positions entered, so every name below is a buy from nothing. Enter what you hold and the board says what
            to change.
          </p>
        )}
        <table className="w-full text-sm">
          <thead className="text-left text-[#6e6e73]">
            <tr>
              <th className="py-1">Name</th>
              <th>Do</th>
              <th>How much</th>
              <th>Price</th>
              <th>Grade</th>
              <th>When to sell</th>
              <th title={TRIGGER_LEGEND}>Why</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <Row
                key={r.ticker}
                r={r}
                quote={live.quotes[r.ticker]}
                equity={equity}
                stops={stops}
                open={openReason === r.ticker}
                onReason={() => setOpenReason(openReason === r.ticker ? null : r.ticker)}
              />
            ))}
          </tbody>
        </table>
        <p className="mt-2 text-xs text-[#6e6e73]">
          Buy at the open with a market order. A name is sold when it loses its A grade at the next check, not at a
          price; stops are optional because they cut winners as often as losers.
        </p>
        {warnings.length > 0 && (
          <ul className="mt-2 space-y-1 text-xs text-[#9a6200]">
            {warnings.map((flag) => (
              <li key={flag}>Warning: {FLAG_WORDS[flag] ?? flag}</li>
            ))}
          </ul>
        )}
      </section>

      <button
        type="button"
        onClick={() => setDetails(!details)}
        className="self-start text-sm text-[#0071e3] hover:underline"
      >
        {details ? 'Hide the details' : 'Show the details: practice account and every grade'}
      </button>

      {details && paper && (
        <section className="rounded-2xl border border-black/[0.08] bg-white p-4">
          <h3 className="mb-1 text-sm font-semibold text-[#1d1d1f]">Practice account</h3>
          <p className="mb-2 text-xs text-[#6e6e73]">
            A simulated account that follows the desk with real prices and no real money. Its track record is the
            desk&rsquo;s.
          </p>
          <p className="text-sm text-[#1d1d1f]">
            Worth {money(paper.equity)} · cash {money(paper.cash)} ·{' '}
            {paper.plan === 'rebalance'
              ? 'today every grade was re-checked and the sizes reset'
              : paper.plan === 'exits'
                ? 'today only names that lost their grade are sold'
                : 'nothing to trade today'}
          </p>
          {paper.orders.length > 0 && (
            <p className="mt-2 text-sm text-[#6e6e73]">
              Orders placed for the next open: {paper.orders.map((o) => `${o.side} ${o.qty} ${o.symbol}`).join(', ')}
            </p>
          )}
          {paper.positions.length > 0 && (
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
                {paper.positions.map((p) => (
                  <tr key={p.symbol} className="border-t border-black/[0.05]">
                    <td className="py-1 font-medium">{p.symbol}</td>
                    <td>{p.qty}</td>
                    <td>{money(p.market_value)}</td>
                    <td>{money(p.avg_entry_price)}</td>
                    <td>{money(p.current_price)}</td>
                    <td className={p.unrealized_pl >= 0 ? 'text-[#1e7a3a]' : 'text-[#b42318]'}>{money(p.unrealized_pl)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </section>
      )}

      {details && <EveryGrade latest={latest} />}
    </div>
  )
}

interface RowProps {
  r: DeskMineRow
  quote?: DeskQuote
  equity: number
  stops: boolean
  open: boolean
  onReason: () => void
}

// One name: what to do, how much for this account, the price now against
// the close and the person's own cost, the grade, when it leaves, and why.
const Row = ({ r, quote, equity, stops, open, onReason }: RowProps) => {
  const price = quote?.last ?? r.last ?? r.last_close ?? 0
  const qty = price > 0 ? Math.round((Math.abs(r.delta_weight) * equity) / price) : 0
  const high = Math.max(r.high_20 ?? 0, quote?.high ?? 0)
  const trailing = stops && high > 0 ? high * 0.88 : null
  const hit = trailing !== null && price > 0 && price <= trailing
  const atRisk = r.in_book && r.target_weight > 0 && (r.grade_margin ?? 1) <= 0
  return (
    <tr className="border-t border-black/[0.05] align-top">
      <td className="py-1.5 font-medium">{r.ticker}</td>
      <td>
        <span className={`rounded-full px-2 py-0.5 text-xs font-medium uppercase ${ACTION_STYLE[r.action] ?? ''}`}>
          {r.action}
        </span>
      </td>
      <td className="whitespace-nowrap">
        {r.action === 'hold' ? (
          <span>{pct(r.current_weight)} of the account</span>
        ) : (
          <span>
            <span className="font-medium">{qty.toLocaleString()} shares</span>{' '}
            <span className="text-[#6e6e73]">
              ({pct(r.current_weight)} → {pct(r.target_weight)})
            </span>
          </span>
        )}
        {r.shares > 0 && r.entry_price !== null && (
          <div className="text-xs text-[#6e6e73]">
            you hold {r.shares} at {money(r.entry_price)}
            {r.pl_pct !== null && (
              <span className={r.pl_pct >= 0 ? ' text-[#1e7a3a]' : ' text-[#b42318]'}> {signed(r.pl_pct)}</span>
            )}
          </div>
        )}
      </td>
      <td className="whitespace-nowrap text-[#6e6e73]">
        {r.last_close !== null ? `close ${money(r.last_close)}` : '—'}
        {quote && (
          <div className={`text-xs ${hit ? 'font-medium text-[#b42318]' : ''}`}>
            now {money(quote.last)}
            {quote.open > 0 && ` · ${signed(quote.last / quote.open - 1)} today`}
            {trailing !== null && (hit ? ' · below the stop: sell' : ` · stop ${money(trailing)}`)}
          </div>
        )}
      </td>
      <td className="whitespace-nowrap">
        {r.in_book ? (
          <>
            <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${GRADE_STYLE[r.grade] ?? ''}`}>{r.grade}</span>
            <span className="ml-1 font-mono text-xs text-[#6e6e73]">#{r.rank ?? '—'}</span>
            {atRisk && (
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
            next check in {r.until_rebalance} trading day{r.until_rebalance === 1 ? '' : 's'}
          </>
        )}
      </td>
      <td className="text-xs text-[#6e6e73]">
        {r.in_book && (
          <span className="font-mono text-[#1d1d1f]" title={TRIGGER_LEGEND}>
            {triggers(r.stances ?? {})}{' '}
          </span>
        )}
        {r.reason ? (
          <button type="button" onClick={onReason} className="text-left text-[#0071e3] hover:underline">
            {open ? 'hide' : r.why || 'why?'}
          </button>
        ) : (
          r.why
        )}
        {open && <p className="mt-1 text-[#1d1d1f]">{r.reason}</p>}
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
      <p className="mb-2 text-xs text-[#6e6e73]">{TRIGGER_LEGEND}</p>
      <table className="w-full text-sm">
        <thead className="text-left text-[#6e6e73]">
          <tr>
            <th className="py-1">Name</th>
            <th>Group</th>
            <th>Grade</th>
            <th>Analysts</th>
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
              <td className="whitespace-nowrap font-mono text-xs">{triggers(g.stances ?? {})}</td>
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
                    {g.reason && <p>{g.reason}</p>}
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

// The one-screen explanation for someone who has never seen the page.
const HowToUse = ({ onClose }: { onClose: () => void }) => (
  <div className="my-2 max-w-xl rounded-xl border border-black/[0.08] bg-[#f5f5f7] p-4 text-sm text-[#1d1d1f]">
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
        <b>Buy at the open</b> with a market order. Do not chase a name that has already jumped.
      </li>
      <li>
        <b>Selling:</b> a name is sold when its grade drops below A at the next check, about every four weeks. Each
        row says when that is. Stops are optional: switch them on to see a price under which to sell.
      </li>
      <li>
        <b>Prices</b> refresh every 15 minutes during market hours. Gains are measured from what you paid.
      </li>
      <li>
        <b>Why:</b> the letters are the analysts (F business fundamentals, T price trend, S news and sentiment, V price
        vs value, R which group leads). Click the reason to read it in full.
      </li>
    </ol>
    <button type="button" onClick={onClose} className="mt-3 text-xs text-[#0071e3] hover:underline">
      close
    </button>
  </div>
)

export default DeskPanel
