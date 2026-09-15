import type { DeskExecutionQuality } from '../../services/api'

const bp = (value: number | null | undefined) => value == null ? '—' : `${value > 0 ? '+' : ''}${value.toFixed(1)} bp`
const dollars = (value: number | null | undefined) => value == null ? '—' : `${value < 0 ? '−' : '+'}$${Math.abs(value).toLocaleString(undefined, {maximumFractionDigits: 0})}`

// Every paper fill against the price its decision was made at, as a series:
// paying up on a buy or selling down on a sell is a positive cost.
export const ExecutionQuality = ({quality}: {quality?: DeskExecutionQuality | null}) => (
  <details className="rounded-2xl border border-black/[0.08] bg-white p-4 text-xs text-[#6e6e73]" aria-label="Execution quality">
    <summary className="cursor-pointer font-medium">Execution against the decision price · {quality?.all_time.fills ? `${quality.all_time.fills} fills, ${bp(quality.all_time.bps)}` : 'no fills yet'}</summary>
    {!quality ? <p className="mt-2">Written by the nightly once the paper account has fills.</p> : <>
      <p className="mt-2">{quality.basis}.</p>
      <div className="mt-2 overflow-x-auto">
        <table className="w-full text-left [&_td]:pr-3 [&_th]:pr-3" aria-label="Execution summary">
          <thead><tr><th>Scope</th><th>Fills</th><th>Cost</th><th>Dollars</th></tr></thead>
          <tbody>
            <tr><td>All time</td><td>{quality.all_time.fills}</td><td>{bp(quality.all_time.bps)}</td><td>{dollars(quality.all_time.dollars)}</td></tr>
            <tr><td>Last {quality.recent.sessions} sessions</td><td>{quality.recent.fills}</td><td>{bp(quality.recent.bps)}</td><td>{dollars(quality.recent.dollars)}</td></tr>
            <tr><td>Scheduled rebalances</td><td>{quality.by_kind.rebalance.fills}</td><td>{bp(quality.by_kind.rebalance.bps)}</td><td>{dollars(quality.by_kind.rebalance.dollars)}</td></tr>
            <tr><td>FOMC overlay</td><td>{quality.by_kind.fomc.fills}</td><td>{bp(quality.by_kind.fomc.bps)}</td><td>{dollars(quality.by_kind.fomc.dollars)}</td></tr>
            <tr><td>Buys</td><td>{quality.by_side.buy.fills}</td><td>{bp(quality.by_side.buy.bps)}</td><td>{dollars(quality.by_side.buy.dollars)}</td></tr>
            <tr><td>Sells</td><td>{quality.by_side.sell.fills}</td><td>{bp(quality.by_side.sell.bps)}</td><td>{dollars(quality.by_side.sell.dollars)}</td></tr>
          </tbody>
        </table>
      </div>
      {quality.series.length > 0 && <div className="mt-2 overflow-x-auto">
        <table className="w-full text-left [&_td]:pr-3 [&_th]:pr-3" aria-label="Execution by session">
          <thead><tr><th>Session</th><th>Fills</th><th>Cost</th><th>Dollars</th><th>Cumulative</th></tr></thead>
          <tbody>{quality.series.slice(-10).map(row => <tr key={row.session}><td>{row.session}</td><td>{row.fills}</td><td>{bp(row.bps)}</td><td>{dollars(row.dollars)}</td><td>{dollars(row.cumulative_dollars)}</td></tr>)}</tbody>
        </table>
      </div>}
      <p className="mt-3">Written {quality.written}. A rising cumulative line is the desk paying more to reach its positions; it does not say whether the positions were right.</p>
    </>}
  </details>
)
