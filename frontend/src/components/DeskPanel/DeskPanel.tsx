import { useEffect, useState } from 'react'
import { RefreshCw } from 'lucide-react'
import { getDesk, type DeskPayload } from '../../services/api'

interface DeskPanelProps {
  userId: string
}

// How often the page asks for a fresh record while open. The desk writes
// one record a session, so a few minutes is plenty and costs nothing.
const REFRESH_MS = 5 * 60 * 1000

const GRADE_STYLE: Record<string, string> = {
  'A+': 'bg-[#e6f4ea] text-[#1e7a3a]',
  A: 'bg-[#eaf3ff] text-[#0b5cad]',
  B: 'bg-[#fff6e5] text-[#9a6200]',
  C: 'bg-[#f5f5f7] text-[#6e6e73]',
}

const STANCE_MARK: Record<number, string> = { 1: '+', 0: '·', [-1]: '−' }

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

  return (
    <div className="flex flex-1 flex-col gap-6 overflow-y-auto p-6">
      <header className="flex flex-wrap items-baseline justify-between gap-3">
        <div>
          <h2 className="text-xl font-semibold text-[#1d1d1f]">Desk</h2>
          <p className="text-sm text-[#6e6e73]">
            Session {latest.session} · {summary?.counts['A+'] ?? 0} A+, {summary?.counts.A ?? 0} A,{' '}
            {summary?.counts.B ?? 0} B, {summary?.counts.C ?? 0} C · book gross {summary ? pct(summary.gross) : '—'}
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
        <table className="w-full text-sm">
          <thead className="text-left text-[#6e6e73]">
            <tr>
              <th className="py-1">Name</th>
              <th>Grade</th>
              <th>Weight</th>
              <th>Volatility</th>
            </tr>
          </thead>
          <tbody>
            {latest.book.map((row) => (
              <tr key={row.ticker} className="border-t border-black/[0.05]">
                <td className="py-1 font-medium">{row.ticker}</td>
                <td>
                  <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${GRADE_STYLE[row.grade] ?? ''}`}>
                    {row.grade}
                  </span>
                </td>
                <td>{pct(row.weight)}</td>
                <td>{pct(row.volatility)}</td>
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
              <th>F</th>
              <th>T</th>
              <th>S</th>
              <th>R</th>
              <th>Brief</th>
            </tr>
          </thead>
          <tbody>
            {grades.map(([ticker, g]) => (
              <tr key={ticker} className="border-t border-black/[0.05] align-top">
                <td className="py-1 font-medium">{ticker}</td>
                <td className="text-[#6e6e73]">{g.side}</td>
                <td>
                  <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${GRADE_STYLE[g.grade] ?? ''}`}>{g.grade}</span>
                </td>
                {(['fundamental', 'technical', 'sentiment', 'rotation'] as const).map((k) => (
                  <td key={k} className="font-mono">{STANCE_MARK[g.stances[k] ?? 0]}</td>
                ))}
                <td>
                  {briefs[ticker] ? (
                    <button
                      type="button"
                      onClick={() => setOpenBrief(openBrief === ticker ? null : ticker)}
                      className="text-[#0071e3] hover:underline"
                    >
                      {openBrief === ticker ? 'hide' : briefs[ticker].verdict}
                    </button>
                  ) : (
                    <span className="text-[#6e6e73]">—</span>
                  )}
                  {openBrief === ticker && briefs[ticker] && (
                    <div className="mt-1 space-y-1 text-xs text-[#1d1d1f]">
                      <p>{briefs[ticker].reasoning}</p>
                      <p><span className="font-medium">Risks:</span> {briefs[ticker].risks}</p>
                      <p><span className="font-medium">Watch:</span> {briefs[ticker].watch}</p>
                    </div>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
    </div>
  )
}

export default DeskPanel
