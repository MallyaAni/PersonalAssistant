import { useEffect, useRef, useState } from 'react'
import { getDeskPaperHistory, type DeskPaperHistory, type DeskPaperHistoryRow } from '../../services/api'

// Keep absent account values visibly different from a genuine zero balance.
const dollars = (value: number | null) => value !== null && Number.isFinite(value)
  ? value.toLocaleString('en-US', {style: 'currency', currency: 'USD'}) : '—'

// Date the actual saved observation independently of its assigned strategy session.
const recordedTime = (value: string | null) => value && Number.isFinite(Date.parse(value))
  ? `${new Date(value).toLocaleString('en-US', {timeZone: 'America/New_York', month: 'short', day: 'numeric', year: 'numeric', hour: 'numeric', minute: '2-digit'})} ET`
  : 'Time unavailable'

// Show dollar account-value changes without calling unadjusted balance movements trading returns.
const change = (value: number | null) => value === null || !Number.isFinite(value)
  ? '—' : `${value > 0 ? '+' : value < 0 ? '−' : ''}${dollars(Math.abs(value))}`

// Plot saved account values on session dates, breaking lines at missing or unverified intervals.
const AccountValueChart = ({rows}: {rows: DeskPaperHistoryRow[]}) => {
  const points = rows.map(row => ({row, time: Date.parse(`${row.session}T12:00:00Z`)}))
  const valid = points.filter(point => point.row.equity !== null && Number.isFinite(point.row.equity) && Number.isFinite(point.time))
  if (valid.length < 2) return null
  const low = Math.min(...valid.map(point => point.row.equity!))
  const high = Math.max(...valid.map(point => point.row.equity!))
  const spread = high - low || Math.max(1, Math.abs(high) * .01)
  const first = points[0].time
  const last = points[points.length - 1].time
  // Use actual session spacing so missing weekdays and weekends do not collapse into adjacent dates.
  const x = (time: number) => 12 + (time - first) / (last - first || 1) * 680
  // Leave room for dollar labels above and below the observed range.
  const y = (value: number) => 25 + (high - value) / spread * 125
  const segments: string[][] = []
  let previousValid = false
  for (const point of points) {
    if (point.row.equity === null || !Number.isFinite(point.row.equity) || !Number.isFinite(point.time)) {
      previousValid = false
      continue
    }
    if (!previousValid || point.row.missing_sessions !== 0 || point.row.chronology_verified !== true) segments.push([])
    segments[segments.length - 1].push(`${x(point.time)},${y(point.row.equity)}`)
    previousValid = true
  }
  return <svg role="img" aria-label="Paper account value by saved session" viewBox="0 0 780 185" className="my-3 w-full">
    <title>Recorded account values in US dollars. Gaps are not interpolated.</title>
    {[high, low].map((value, index) => <g key={index}>
      <line x1="12" x2="692" y1={y(value)} y2={y(value)} stroke="#e5e7eb" />
      <text x="775" y={y(value) + 4} textAnchor="end" fill="#6e6e73" fontSize="11">{dollars(value)}</text>
    </g>)}
    {segments.filter(segment => segment.length > 1).map((segment, index) => <polyline key={index} points={segment.join(' ')} fill="none" stroke="#0071e3" strokeWidth="2" />)}
    {valid.map(point => <circle key={point.row.session} cx={x(point.time)} cy={y(point.row.equity!)} r="3" fill="#0071e3"><title>{point.row.session}: {dollars(point.row.equity)} · recorded {recordedTime(point.row.recorded_at)}</title></circle>)}
    <text x="12" y="179" fill="#6e6e73" fontSize="11">{rows[0].session}</text>
    <text x="692" y="179" textAnchor="end" fill="#6e6e73" fontSize="11">{rows[rows.length - 1].session}</text>
  </svg>
}

// Load actual saved paper-account history on demand, separate from current quotes and backtests.
export const PaperAccountHistory = ({userId, session}: {userId: string; session?: string}) => {
  const [open, setOpen] = useState(false)
  const [history, setHistory] = useState<DeskPaperHistory | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [limit, setLimit] = useState(90)
  const [refresh, setRefresh] = useState(0)
  const sequence = useRef(0)

  // Ignore late responses after closing, refreshing, or switching the displayed identity.
  useEffect(() => {
    if (!open) return
    let active = true
    const request = ++sequence.current
    setBusy(true)
    setError('')
    void getDeskPaperHistory(userId, limit).then(value => {
      if (active && sequence.current === request) setHistory(value)
    }).catch(() => {
      if (active && sequence.current === request) setError('Account history unavailable. Try refreshing.')
    }).finally(() => {
      if (active && sequence.current === request) setBusy(false)
    })
    return () => { active = false }
  }, [open, userId, session, limit, refresh])

  const current = history?.user_id === userId ? history : null
  return <section aria-label="Paper account history" className="rounded-xl border border-black/[0.08] p-3 text-xs">
    <button type="button" aria-expanded={open} onClick={() => setOpen(!open)} className="font-semibold text-[#1d1d1f]">{open ? '▾' : '▸'} Daily account history</button>
    {open && <div className="mt-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-[#6e6e73]">Saved broker account values · USD</p>
        <button type="button" disabled={busy} className="text-[#0071e3] disabled:opacity-50" onClick={() => setRefresh(value => value + 1)}>{busy ? 'Loading…' : 'Refresh history'}</button>
      </div>
      {error && <p role="alert" className="mt-2 text-[#b42318]">{error}{current ? ' Showing previously loaded records.' : ''}</p>}
      {current && <>
        {current.rows.length === 0 ? <p className="mt-3 text-[#6e6e73]">No saved paper-account values yet.</p> : <>
          <AccountValueChart rows={current.rows} />
          <div className="max-h-80 overflow-auto">
            <table aria-label="Daily paper account values" className="w-full text-right tabular-nums [&_td]:px-2 [&_td]:py-2 [&_th]:px-2 [&_th]:py-2">
              <thead className="sticky top-0 bg-[#f5f5f7]"><tr><th className="text-left">Session</th><th className="text-left">Recorded</th><th>Account value</th><th>Cash</th><th>Change since prior record</th></tr></thead>
              <tbody>{[...current.rows].reverse().map(row => <tr key={row.session} className="border-t border-black/[0.05]">
                <th scope="row" className="whitespace-nowrap text-left font-normal">{row.session}</th>
                <td className="text-left">{recordedTime(row.recorded_at)}</td>
                <td>{dollars(row.equity)}</td><td>{dollars(row.cash)}</td>
                <td title={row.previous_session ? `Compared with the ${row.previous_session} record; not adjusted for deposits, withdrawals or resets.` : 'No previous record in this series.'}>
                  <span className={row.equity_change === null || row.equity_change === 0 ? '' : row.equity_change > 0 ? 'text-[#1e7a3a]' : 'text-[#b42318]'}>{change(row.equity_change)}</span>
                  {row.equity_change_pct !== null && Number.isFinite(row.equity_change_pct) && <span className="ml-1 text-[#6e6e73]">({row.equity_change_pct > 0 ? '+' : ''}{(row.equity_change_pct * 100).toFixed(2)}%)</span>}
                  {row.missing_sessions !== null && row.missing_sessions > 0 && <div className="text-[#9a6200]">{row.missing_sessions} missing session{row.missing_sessions === 1 ? '' : 's'}</div>}
                  {row.previous_session && row.missing_sessions === null && <div className="text-[#6e6e73]">Session coverage unverified</div>}
                  {row.previous_session && row.chronology_verified !== true && <div className="text-[#6e6e73]">Recording times not comparable</div>}
                </td>
              </tr>)}</tbody>
            </table>
          </div>
          <p className="mt-2 text-[#6e6e73]">{current.rows.length} records · newest first{current.truncated ? ` · ${current.total_records} available` : ''}</p>
          {current.truncated && limit < 1000 && <button type="button" className="mt-2 text-[#0071e3]" onClick={() => setLimit(1000)}>Load older records</button>}
        </>}
        {!!current.ignored_records && <p className="mt-2 text-[#9a6200]">{current.ignored_records} unreadable record{current.ignored_records === 1 ? '' : 's'} excluded.</p>}
      </>}
      <p className="mt-3 text-[#6e6e73]">Recorded times may differ from the assigned session. Values are not verified closing balances; changes are not adjusted for deposits, withdrawals or account resets.</p>
      <details className="mt-2 text-[#6e6e73]"><summary className="cursor-pointer">History details</summary><p className="mt-1">Missing values stay blank. Chart lines stop at missing or unverified sessions. These records do not identify which strategy version produced each result.</p></details>
    </div>}
  </section>
}
