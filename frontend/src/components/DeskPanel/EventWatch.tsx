import type { DeskEventShock, DeskEventWatch } from '../../services/api'

const change = (value: number | null | undefined) =>
  value == null ? '—' : `${value < 0 ? '−' : '+'}${(Math.abs(value) * 100).toFixed(1)}%`
const volume = (value: number | null | undefined) =>
  value == null ? '—' : `${value.toFixed(1)}×`
const sessions = (value: number | null | undefined) =>
  value == null ? 'unknown sessions' : `${value} session${value === 1 ? '' : 's'}`

// One flagged release, with the grade and action on the same nightly record.
const shockLine = (row: DeskEventShock) => (
  <li key={`${row.ticker}-${row.reaction_date}`}>
    <b>{row.ticker}</b> {row.reaction_date} ({row.age_sessions} session{row.age_sessions === 1 ? '' : 's'} ago) ·
    {' '}EPS {change(row.eps_qoq)} QoQ / {change(row.eps_yoy)} YoY ·
    {' '}revenue {change(row.revenue_yoy)} YoY ·
    {' '}reaction {change(row.reaction_return)} on {volume(row.volume_ratio)} volume ·
    {' '}grade {row.grade}{row.grade_headline ? ` (${row.grade_headline})` : ''} ·
    {' '}{row.action ?? 'no action'}{row.target_weight == null ? '' : ` · target ${(row.target_weight * 100).toFixed(1)}%`}
  </li>
)

// The nightly mechanical event scan: earnings shocks, adverse price moves and
// the reviewed event calendar. Descriptive alerting, never an action.
export const EventWatch = ({watch}: {watch?: DeskEventWatch | null}) => {
  if (!watch) return (
    <details className="rounded-xl border border-black/[0.08] bg-white p-3 text-xs text-[#6e6e73]" aria-label="Event watch">
      <summary className="cursor-pointer font-medium">Event watch · no scan yet</summary>
      <p className="mt-2">The nightly writes this after the desk record. A missing block means the scan has not run.</p>
    </details>
  )

  const recent = watch.shocks.filter(row => row.age_sessions <= 10)
  const older = watch.shocks.filter(row => row.age_sessions > 10)
  const label = `${recent.length} earnings shock${recent.length === 1 ? '' : 's'} in 10 sessions · ${watch.price_shocks.length} price shock${watch.price_shocks.length === 1 ? '' : 's'} in ${watch.rule.price_window} sessions`

  return (
    <details className="rounded-xl border border-black/[0.08] bg-white p-3 text-xs text-[#6e6e73]" aria-label="Event watch">
      <summary className="cursor-pointer font-medium">
        Event watch · {watch.asof}{watch.stale ? ` · scan is not for ${watch.session ?? 'the displayed session'}` : ''} · {label}
        <span className="ml-2 font-normal">· descriptive · not a trading rule</span>
      </summary>

      {watch.stale && <p role="alert" className="mt-2 text-[#b42318]">
        This scan was written for {watch.asof}, not the session the desk is showing. Treat it as history, not the current book.
      </p>}

      <p className="mt-2">
        Calendar: next FOMC {watch.calendar.next_fomc ?? 'unavailable'} ({sessions(watch.calendar.sessions_to_fomc)}) ·
        {' '}next election {watch.calendar.next_election} ({watch.calendar.next_election_midterm ? 'midterm' : 'presidential'}, {sessions(watch.calendar.sessions_to_election)}).
      </p>

      {recent.length > 0 && <>
        <p className="mt-2 font-medium text-[#1d1d1f]">Earnings shocks in the latest release</p>
        <ul className="mt-1 list-disc space-y-1 pl-4">{recent.map(shockLine)}</ul>
      </>}

      {older.length > 0 && <>
        <p className="mt-2 font-medium text-[#1d1d1f]">Older latest releases still flagged</p>
        <ul className="mt-1 list-disc space-y-1 pl-4">{older.map(shockLine)}</ul>
      </>}

      {watch.price_shocks.length > 0 && <>
        <p className="mt-2 font-medium text-[#1d1d1f]">Large adverse price moves in the last {watch.rule.price_window} sessions</p>
        <ul className="mt-1 list-disc space-y-1 pl-4">{watch.price_shocks.map(row => (
          <li key={`${row.ticker}-${row.date}`}><b>{row.ticker}</b> {row.date}: {change(row.return)} on {volume(row.volume_ratio)} volume</li>
        ))}</ul>
      </>}

      {watch.contagion.map(item => <p key={`${item.trigger.ticker}-${item.trigger.reaction_date}`} className="mt-2">
        Book since the {item.trigger.ticker} shock {item.trigger.reaction_date}: mean {change(item.mean)} across {item.members} names
        {item.worst.length > 0 ? ` · worst ${item.worst.map(row => `${row.ticker} ${change(row.return_since)}`).join(', ')}` : ''}.
      </p>)}

      <p className="mt-3">
        Mechanical rule: EPS {change(watch.rule.qoq_drop)} quarter over quarter or {change(watch.rule.yoy_drop)} year over year,
        confirmed by a reaction of {change(watch.rule.reaction_drop)} or worse; a one-session price drop of
        {' '}{change(watch.rule.price_drop)} or worse on {volume(watch.rule.price_volume)} volume or more.
        The grade and action are the nightly record, not this scan. Nothing here changes an order.
      </p>
    </details>
  )
}
