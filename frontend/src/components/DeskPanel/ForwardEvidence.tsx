import type { DeskForwardEvidence } from '../../services/api'

const ARMS: Record<string, string> = {
  baseline_targets: 'Saved stock targets',
  technical_targets: 'Updated grades',
  targets: 'Updated grades + economic cap',
  correlation_targets: 'Updated grades + economic + correlation caps',
}

// Format observed returns without turning missing observations into zero performance.
const percent = (value: number | null) => value === null ? '—' : `${(value * 100).toFixed(2)}%`

// Explain saved-signal research without presenting metadata or simulated accounts as verified performance.
export const ForwardEvidence = ({evidence}: {evidence?: DeskForwardEvidence}) => (
  <details className="rounded-2xl border border-black/[0.08] bg-white p-4 text-xs text-[#6e6e73]">
    <summary className="cursor-pointer font-medium">Results from saved signals · research</summary>
    <p className="mt-2">Research does not change orders. These are results from saved signals, not actual trades. They are not profit probabilities.</p>
    <p className="mt-2">Prices and corporate-action adjustments have not been independently verified; reported coverage is only file metadata.</p>
    {!evidence?.versions?.length && <p className="mt-2">{evidence?.reason ?? 'Collecting forward records; performance unavailable.'}</p>}
    {evidence?.versions?.map(version => <div key={version.version} className="mt-3">
      <p>{version.version} · {version.decision_count} recorded decisions · {version.outcomes[0]?.decision_days ?? 0} decision {(version.outcomes[0]?.decision_days ?? 0) === 1 ? 'day' : 'days'}</p>
      {version.corporate_actions_through && <p>Reported daily-data coverage through {version.corporate_actions_through} · {version.pending_daily_validation ?? 0} newer decisions not evaluated</p>}
      {version.outcomes.map(outcome => <div key={outcome.cost_bps_per_side} className="mt-2 overflow-x-auto">
        <p>{outcome.cost_bps_per_side} bp per side · {outcome.signal_count} saved stock signals</p>
        {!!Object.keys(outcome.missing_or_immature ?? {}).length && <p>Missing or unusable outcomes: {Object.entries(outcome.missing_or_immature ?? {}).map(([horizon, count]) => `${count} at ${horizon} sessions`).join(' · ')}</p>}
        {!outcome.grades.length ? <p>No usable 5-/20-session outcomes. Missing prices, unfinished horizons or no valid entry can cause this.</p> : <table className="mt-1 w-full text-left [&_td]:pr-3 [&_th]:pr-3">
          <thead><tr><th>Grade</th><th>Sessions after entry</th><th>Usable outcomes</th><th>Spaced signal days</th><th>Mean vs SPY</th><th>Approx. 95% interval</th></tr></thead>
          <tbody>{outcome.grades.map(row => <tr key={`${row.grade}-${row.horizon_sessions}`}><td>{row.grade}</td><td>{row.horizon_sessions}</td><td>{row.observations}</td><td>{row.nonoverlapping_cohorts}</td><td>{percent(row.mean_excess_return)}</td><td>{row.approximate_95_interval ? row.approximate_95_interval.map(percent).join(' to ') : 'Insufficient evidence'}</td></tr>)}</tbody>
        </table>}
        {!!outcome.entry_states?.length && <table className="mt-2 w-full text-left [&_td]:pr-3 [&_th]:pr-3">
          <thead><tr><th>Entry state</th><th>Sessions after entry</th><th>Usable outcomes</th><th>Mean vs SPY</th></tr></thead>
          <tbody>{outcome.entry_states.map(row => <tr key={`${row.state}-${row.horizon_sessions}`}><td>{row.state}</td><td>{row.horizon_sessions}</td><td>{row.observations}</td><td>{percent(row.mean_excess_return)}</td></tr>)}</tbody>
        </table>}
      </div>)}
      {version.portfolios.map(portfolio => <div key={portfolio.cost_bps} className="mt-2 overflow-x-auto">
        <p>{portfolio.cost_bps} bp costs · {portfolio.fill_intervals} eligible rebalance checks</p>
        {portfolio.status === 'insufficient_forward_data' ? <p>Insufficient eligible rebalance checks for an account comparison.</p> : <table className="mt-1 w-full text-left [&_td]:pr-3 [&_th]:pr-3">
          <thead><tr><th>Candidate</th><th>Simulated return after costs</th><th>Largest drop at observed prices</th><th>Trading / starting balance</th></tr></thead>
          <tbody>{Object.entries(portfolio.arms).map(([name, arm]) => <tr key={name}><td>{ARMS[name] ?? name}</td><td>{percent(arm.return)}</td><td>{percent(arm.drawdown)}</td><td>{(arm.traded_dollars / 100000).toFixed(2)}×</td></tr>)}</tbody>
        </table>}
      </div>)}
    </div>)}
    <details className="mt-3" aria-label="How saved-signal results are calculated">
      <summary className="cursor-pointer font-medium">How these results are calculated</summary>
      <p className="mt-2">First daily signal only: stock signals come from the first saved decision each day. Signal counts include wait signals and signals without usable outcomes. Each usable outcome is one stock over one return period. Grade outcomes use later bar prices and subtract SPY and modeled costs.</p>
      <p className="mt-2">The mean first averages usable stock returns within each day, then gives equal weight to selected days. Selected dates are at least 5 or 20 trading sessions apart, matching the return period. Spacing does not establish independence. Approximate 95% intervals require 20 spaced signal days. No interval means insufficient evidence for that estimate.</p>
      <p className="mt-2">Saved stock targets are the stock weights in the saved book. Updated grades use new technical readings and compatible valuation inputs, while retaining other analyst inputs. The funded target trackers are separate from the complete scheduled strategy and actual paper fills. No passive SPY/QQQ account comparison is shown here.</p>
      <p className="mt-2">Costs are assumptions; modeled fills use later observed prices. Grade outcomes deduct an additive round-trip cost allowance; account costs apply to each dollar bought or sold. A check can produce no trade. Trading is buys plus sells, excluding fees, divided by the $100,000 starting balance.</p>
      <p className="mt-2">Account return is the cumulative change from a $100,000 starting balance; it includes unpaid dividends, is not annualized and assumes no final sale. Drops are from prior peaks at saved prices; losses between observations can be missed.</p>
      <p className="mt-2">Recorded splits adjust shares; dividends accrue as receivables and cannot fund buys because pay dates are unavailable. Other corporate actions are not modeled.</p>
    </details>
    <p className="mt-3">Candidates require separate validation before changing the adopted strategy. These trackers do not establish optimal entry, exit or FOMC re-entry timing.</p>
  </details>
)
