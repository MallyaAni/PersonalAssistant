import type { DeskFomcGate } from '../../services/api'

const percent = (value: number | null | undefined) => value == null ? '—' : `${(value * 100).toFixed(2)}%`
const dollars = (value: number | null | undefined) => value == null ? '—' : `${value < 0 ? '−' : '+'}$${Math.abs(value).toLocaleString(undefined, {maximumFractionDigits: 0})}`

const STANDING: Record<string, string> = {
  waiting: 'waiting for enough meetings',
  keep: 'keep the overlay',
  retire: 'retire the overlay',
}

// The FOMC overlay against the book that never traded it, and the standing of
// the gate written before the outcomes. Evidence, never an action.
export const FomcGate = ({gate}: {gate?: DeskFomcGate | null}) => (
  <details className="rounded-2xl border border-black/[0.08] bg-white p-4 text-xs text-[#6e6e73]" aria-label="FOMC overlay gate">
    <summary className="cursor-pointer font-medium">FOMC overlay gate · {gate ? `${gate.verdict.completed_meetings} of ${gate.verdict.required} meetings` : 'no block yet'}</summary>
    {!gate ? <p className="mt-2">Written by the nightly after each paper session; meetings appear once a cycle has confirmed fills.</p> : <>
      <p className="mt-2">Standing: <b>{STANDING[gate.verdict.standing] ?? gate.verdict.standing}</b> · effect after costs so far {dollars(gate.verdict.effect_after_costs)} ({percent(gate.verdict.effect_after_costs_pct)}) over {gate.verdict.completed_meetings} completed meetings.</p>
      <p className="mt-1">{gate.verdict.rule}</p>
      <div className="mt-2 overflow-x-auto">
        <table className="w-full text-left [&_td]:pr-3 [&_th]:pr-3" aria-label="FOMC meetings">
          <thead><tr><th>Decision</th><th>Status</th><th>Window</th><th>Effect</th><th>After {gate.cost_bp} bp</th><th>Drawdown, live</th><th>Drawdown, without</th></tr></thead>
          <tbody>{gate.meetings.map(row => <tr key={row.decision_date}>
            <td>{row.decision_date}</td>
            <td>{row.status}</td>
            <td>{row.window ? `${row.window[0]} to ${row.window[1]}` : '—'}</td>
            <td>{row.effect == null ? '—' : `${dollars(row.effect)} (${percent(row.effect_pct)})`}</td>
            <td>{row.effect_after_costs == null ? '—' : `${dollars(row.effect_after_costs)} (${percent(row.effect_after_costs_pct)})`}</td>
            <td>{percent(row.drawdown_live)}</td>
            <td>{percent(row.drawdown_without)}</td>
          </tr>)}</tbody>
        </table>
      </div>
      <p className="mt-3">{gate.basis}. The effect is live equity minus the no-overlay equity at the window's end; an open cycle is marked to the last recorded session. Written {gate.written}.</p>
      {/* The gate decides this policy on its own meetings, which is right.
          But two studies on this book already tested the same shape of
          evidence and both came back against it, and a reader judging the
          gate's running total should know that before it reports. */}
      <p className="mt-2 rounded bg-[#fff8e6] p-2">
        <b className="text-[#1d1d1f]">Prior from related work:</b> cutting exposure on weakness has not paid on
        this book. Six risk-off conditions tested against the forward 20-session return all preceded
        <i> above</i>-average returns, the strongest being a benchmark 5% off its high at +4.77% against a
        +2.71% baseline. Separately, 21 exit triggers were screened and not one was followed by a fall.
        That is 27 tests pointing one way. None of them is this policy, which is why the gate still
        decides it, but the gate is not starting from neutral.
      </p>
    </>}
  </details>
)
