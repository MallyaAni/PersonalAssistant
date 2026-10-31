import type { DeskEarningsCalendar, DeskEarningsRelease } from '../../services/api'

const sessions = (value: number | null | undefined) => {
  if (value == null) return 'unknown sessions'
  if (value < 0) return `${Math.abs(value)} session${Math.abs(value) === 1 ? '' : 's'} overdue`
  if (value === 0) return 'due this session'
  return `${value} session${value === 1 ? '' : 's'} away`
}
const weight = (value: number | null | undefined) =>
  value == null || value === 0 ? '—' : `${(value * 100).toFixed(1)}%`
const title = (value: string) => value.charAt(0).toUpperCase() + value.slice(1)

// One predicted release, with the held weight and grade from the same record.
const releaseLine = (row: DeskEarningsRelease) => (
  <li key={row.ticker}>
    <b>{row.ticker}</b> {row.predicted} · {sessions(row.sessions_until)} ·
    {' '}{title(row.confidence)} confidence
    {row.years > 0 ? ` (${row.years} prior year${row.years === 1 ? '' : 's'})` : ''}
    {row.low !== row.high ? ` · band ${row.low} to ${row.high}` : ''}
    {(row.current_weight ?? 0) > 0 ? ` · held ${weight(row.current_weight)}` : ''}
    {row.grade ? ` · grade ${row.grade}` : ''}
    {row.overdue ? ' · overdue, not filed yet' : ''}
  </li>
)

// The nightly forward earnings calendar: predicted next releases from each
// company's own 8-K item 2.02 history. Descriptive alerting, never an action.
export const EarningsCalendar = ({calendar}: {calendar?: DeskEarningsCalendar | null}) => {
  if (!calendar) return (
    <details className="rounded-xl border border-black/[0.08] bg-white p-3 text-xs text-[#6e6e73]" aria-label="Earnings calendar">
      <summary className="cursor-pointer font-medium">Earnings calendar · no scan yet</summary>
      <p className="mt-2">The nightly writes this after the desk record. A missing block means the scan has not run.</p>
    </details>
  )

  const shown = calendar.upcoming.slice(0, 12)
  const rest = calendar.upcoming.length - shown.length
  const label = `${calendar.counts.names} names predicted · ${calendar.counts.held_upcoming} held due in 60 sessions · ${calendar.counts.overdue} overdue`

  return (
    <details className="rounded-xl border border-black/[0.08] bg-white p-3 text-xs text-[#6e6e73]" aria-label="Earnings calendar">
      <summary className="cursor-pointer font-medium">
        Earnings calendar · {calendar.asof}{calendar.stale ? ` · scan is not for ${calendar.session ?? 'the displayed session'}` : ''} · {label}
        <span className="ml-2 font-normal">· descriptive · not a trading rule</span>
      </summary>

      {calendar.stale && <p role="alert" className="mt-2 text-[#b42318]">
        This scan was written for {calendar.asof}, not the session the desk is showing. Treat it as history, not the current book.
      </p>}

      {shown.length > 0 && <>
        <p className="mt-2 font-medium text-[#1d1d1f]">Next predicted releases</p>
        <ul className="mt-1 list-disc space-y-1 pl-4">{shown.map(releaseLine)}</ul>
      </>}

      {rest > 0 && <p className="mt-1">
        {rest} more book names are predicted within 60 sessions; the JSON carries all of them.
      </p>}

      <p className="mt-3">
        Predicted from each company's own 8-K item 2.02 filing history: the median of the same
        fiscal quarter in the prior {calendar.rule.horizon_years} years, matched by date, with the
        band showing those years' spread. The store has no announced forward date until a release
        is filed, so this is an estimate, not a confirmed date. Nothing here changes a grade,
        target or order.
      </p>
    </details>
  )
}
