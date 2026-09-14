import type { DeskForwardEvidence } from '../../services/api'

const ARMS: Record<string, string> = {baseline_targets: 'Scheduled targets', technical_targets: 'Technical targets', targets: 'Technical + macro', correlation_targets: 'Correlation cap'}

// Format observed returns without turning missing observations into zero performance.
const percent = (value: number | null) => value === null ? '—' : `${(value * 100).toFixed(2)}%`

// Keep experimental performance and sample limitations outside the live action table.
export const ForwardEvidence = ({evidence}: {evidence?: DeskForwardEvidence}) => (
  <details className="rounded-2xl border border-black/[0.08] bg-white p-4 text-xs text-[#6e6e73]">
    <summary className="cursor-pointer font-medium">Forward evidence · research</summary>
    <p className="mt-2">Observed outcomes from immutable decisions. Research does not change orders. Grade outcomes use later bar prices, subtract SPY and modeled costs, and include wait signals. They are not profit probabilities.</p>
    {!evidence?.versions?.length && <p className="mt-2">{evidence?.reason ?? 'Collecting forward records; performance unavailable.'}</p>}
    {evidence?.versions?.map(version => <div key={version.version} className="mt-3">
      <p>{version.version} · {version.decision_count} recorded decisions · {version.outcomes[0]?.decision_days ?? 0} validated days</p>
      {version.corporate_actions_through && <p>Daily validation through {version.corporate_actions_through} · {version.pending_daily_validation ?? 0} decisions awaiting validation</p>}
      <p className="mt-1">First daily signal only. Means use non-overlapping date cohorts; approximate 95% intervals require 20 cohorts. No interval means insufficient evidence for that estimate.</p>
      {version.outcomes.map(outcome => <div key={outcome.cost_bps_per_side} className="mt-2 overflow-x-auto">
        <p>{outcome.cost_bps_per_side} bp per side · {outcome.signal_count} stock observations tracked</p>
        {!!Object.keys(outcome.missing_or_immature ?? {}).length && <p>Missing or immature: {Object.entries(outcome.missing_or_immature ?? {}).map(([horizon, count]) => `${count} at ${horizon} sessions`).join(' · ')}</p>}
        {!outcome.grades.length ? <p>No matured 5/20-session grade outcomes yet.</p> : <table className="mt-1 w-full text-left [&_td]:pr-3 [&_th]:pr-3">
          <thead><tr><th>Grade</th><th>Sessions</th><th>Observations</th><th>Non-overlapping cohorts</th><th>Cohort mean vs SPY</th><th>Approx. 95% interval</th></tr></thead>
          <tbody>{outcome.grades.map(row => <tr key={`${row.grade}-${row.horizon_sessions}`}><td>{row.grade}</td><td>{row.horizon_sessions}</td><td>{row.observations}</td><td>{row.nonoverlapping_cohorts}</td><td>{percent(row.mean_excess_return)}</td><td>{row.approximate_95_interval ? row.approximate_95_interval.map(percent).join(' to ') : 'Insufficient evidence'}</td></tr>)}</tbody>
        </table>}
        {!!outcome.entry_states?.length && <table className="mt-2 w-full text-left [&_td]:pr-3 [&_th]:pr-3">
          <thead><tr><th>Entry state</th><th>Sessions</th><th>Observations</th><th>Cohort mean vs SPY</th></tr></thead>
          <tbody>{outcome.entry_states.map(row => <tr key={`${row.state}-${row.horizon_sessions}`}><td>{row.state}</td><td>{row.horizon_sessions}</td><td>{row.observations}</td><td>{percent(row.mean_excess_return)}</td></tr>)}</tbody>
        </table>}
      </div>)}
      <p className="mt-3">Funded target trackers below are separate from the complete scheduled strategy and actual paper fills. Costs are assumptions; modeled fills use later observed closes. Recorded splits adjust shares; dividends accrue as receivables and cannot fund buys because pay dates are unavailable. Other corporate actions are not modeled.</p>
      {version.portfolios.map(portfolio => <div key={portfolio.cost_bps} className="mt-2 overflow-x-auto">
        <p>{portfolio.cost_bps} bp costs · {portfolio.fill_intervals} eligible intervals</p>
        {portfolio.status === 'insufficient_forward_data' ? <p>Insufficient forward portfolio observations.</p> : <table className="mt-1 w-full text-left [&_td]:pr-3 [&_th]:pr-3">
          <thead><tr><th>Candidate</th><th>Return</th><th>Drawdown</th><th>Traded / initial equity</th></tr></thead>
          <tbody>{Object.entries(portfolio.arms).map(([name, arm]) => <tr key={name}><td>{ARMS[name] ?? name}</td><td>{percent(arm.return)}</td><td>{percent(arm.drawdown)}</td><td>{(arm.traded_dollars / 100000).toFixed(2)}×</td></tr>)}</tbody>
        </table>}
      </div>)}
    </div>)}
    <p className="mt-3">Candidates require separate validation before changing the adopted strategy. These trackers do not establish optimal entry, exit or FOMC re-entry timing.</p>
  </details>
)
