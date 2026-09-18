import { useEffect, useState } from 'react'
import { getDeskEntries, type DeskEntries, type DeskEntryRow } from '../../services/api'

// Where to start, right now, among the names the desk already wants to hold.
//
// The board answers "what should I hold" and says it once a night. That is
// the wrong question while a price is moving, and the right one was already
// measured: `entry.py` has carried two triggers since it was written and was
// called by nothing but the backtest. This is that read, at the live price.
//
// It is deliberately not a recommendation to trade. It says which of two
// measured setups is present and what that setup was worth when it was
// measured, so a trader can decide. Nothing here places an order.

const marketTime = (stamp?: string | null) =>
  stamp
    ? new Date(stamp).toLocaleString('en-US', {
        timeZone: 'America/New_York',
        hour: 'numeric',
        minute: '2-digit',
      })
    : null

// A blotter label, not a sentence. The detail lives in the tooltip.
const headline = (row: DeskEntryRow): string => {
  if (row.trigger === 'dip') return row.with_the_basket_falling ? 'Dip · group down' : 'Dip'
  if (row.trigger === 'breakout') return 'Breakout'
  return '—'
}

// What the label means, for the hover rather than the row.
const detail = (row: DeskEntryRow): string => {
  if (row.trigger === 'dip') {
    return row.with_the_basket_falling
      ? 'Below its lower band with the AI group falling too. Strongest reading measured: about +2.1% over 5 sessions.'
      : 'Stretched below its 21-day average or its lower band. About +1.2% over 5 sessions.'
  }
  if (row.trigger === 'breakout') {
    return 'Top of its 60-session range with the daily and weekly trends agreeing. About +1.3% over 20 sessions.'
  }
  return 'Neither trigger is firing at this bar.'
}

// Where the price is, said plainly. The band position is the measure the
// desk now scores on, so it is the one worth showing.
const whereItSits = (row: DeskEntryRow): string => {
  const parts: string[] = []
  if (row.band_z !== null) {
    const z = row.band_z
    parts.push(
      z <= -1 ? 'below the lower band'
        : z >= 1 ? 'above the upper band'
        : z < -0.3 ? 'in the lower half of its band'
        : z > 0.3 ? 'in the upper half of its band'
        : 'mid-band',
    )
  }
  if (row.stretch_21 !== null) {
    const pct = row.stretch_21 * 100
    parts.push(`${Math.abs(pct).toFixed(1)}% ${pct < 0 ? 'below' : 'above'} the 21-day average`)
  }
  return parts.join(', ')
}

const TRIGGER_STYLE: Record<string, string> = {
  dip: 'bg-[#e7f5ec] text-[#1a7f37]',
  breakout: 'bg-[#e8f0fe] text-[#0b5cad]',
}

export const EntriesNow = ({ userId, onOpen }: { userId: string; onOpen?: (ticker: string) => void }) => {
  const [data, setData] = useState<DeskEntries | null>(null)
  const [showAll, setShowAll] = useState(false)

  useEffect(() => {
    let live = true
    const read = () => {
      getDeskEntries(userId)
        .then((payload) => live && setData(payload))
        .catch(() => live && setData({ user_id: userId, session: null, rows: [], reason: 'Entries unavailable.' }))
    }
    read()
    // Re-read on the candle, so this tracks the price rather than the page load.
    const timer = window.setInterval(read, 60_000)
    return () => {
      live = false
      window.clearInterval(timer)
    }
  }, [userId])

  if (!data) return null
  const firing = data.rows.filter((r) => r.trigger !== null)
  const shown = showAll ? data.rows : firing

  return (
    <section
      aria-label="Entries now"
      className="mb-4 rounded-xl border border-black/[0.08] bg-white p-3"
    >
      <div className="mb-1 flex flex-wrap items-baseline justify-between gap-2">
        <h3 className="text-sm font-semibold text-[#1d1d1f]">Entries</h3>
        <span className="text-[11px] text-[#6e6e73]">
          {data.bar ? `${marketTime(data.bar)} ET` : 'No live bar'}
        </span>
      </div>
      {/* The reasoning folds away. A trader in front of a moving price wants
          the names, not a paragraph; the paragraph matters once, and then
          only when they want to check what the number rests on. */}
      <details className="mb-2 text-[11px] text-[#6e6e73]">
        <summary className="cursor-pointer text-[#0071e3]">Edge</summary>
        <p className="mt-1">
          The grade says what to hold. This says whether now is a moment to begin, among the names
          already graded A+ or A. Two setups were measured on this book: a dip pays about 1.2% over
          five sessions, and 2.1% when the AI group is falling with it; a breakout pays about 1.3%
          over twenty. Those are averages with plenty of losers inside them, not a promise. Nothing
          here places an order.
        </p>
      </details>

      {data.reason && <p className="text-xs text-[#6e6e73]">{data.reason}</p>}

      {!data.reason && firing.length === 0 && !showAll && (
        <p className="text-xs text-[#6e6e73]">
          No trigger at this bar.{' '}
          <button type="button" className="text-[#0071e3] hover:underline" onClick={() => setShowAll(true)}>
            Show all
          </button>
        </p>
      )}

      {shown.length > 0 && (
        <ul className="divide-y divide-black/[0.05]">
          {shown.map((row) => (
            <li key={row.ticker} className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5 py-1.5 text-xs">
              <button
                type="button"
                className="font-semibold hover:text-[#0071e3]"
                onClick={() => onOpen?.(row.ticker)}
              >
                {row.ticker}
              </button>
              <span className="text-[#6e6e73]">{row.grade}</span>
              {row.trigger && (
                <span title={detail(row)} className={`cursor-help rounded px-1.5 py-0.5 text-[10px] font-medium ${TRIGGER_STYLE[row.trigger] ?? ''}`}>
                  {headline(row)}
                </span>
              )}
              {!row.trigger && <span title={detail(row)} className="cursor-help text-[#6e6e73]">{headline(row)}</span>}
              {row.last !== null && (
                <span className="tabular-nums font-medium">${row.last.toFixed(2)}</span>
              )}
              <span className="text-[#6e6e73]">{whereItSits(row)}</span>
              {row.horizon_sessions !== null && (
                <span className="text-[#6e6e73]">{row.horizon_sessions}d</span>
              )}
            </li>
          ))}
        </ul>
      )}

      {shown.length > 0 && !showAll && data.rows.length > firing.length && (
        <button
          type="button"
          className="mt-2 text-[11px] text-[#0071e3] hover:underline"
          onClick={() => setShowAll(true)}
        >
          Show {data.rows.length - firing.length} without a trigger
        </button>
      )}
    </section>
  )
}
