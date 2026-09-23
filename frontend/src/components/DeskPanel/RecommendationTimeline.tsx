import type { DeskRecommendationHistory } from '../../services/api'

// Preserve the distinction between a small positive size and an explicit zero.
const size = (weight: number) => weight > 0 && weight < .001 ? '<0.1%' : `${(weight * 100).toFixed(1)}%`

// Date each original recommendation to the second in exchange time.
const recorded = (value: string) => new Date(value).toLocaleString('en-US', {
  timeZone: 'America/New_York', month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit', second: '2-digit',
})

// Show every saved desk reading so an unchanged recommendation remains visible at its actual time.
export const RecommendationTimeline = ({history}: {history?: DeskRecommendationHistory}) => (
  <section aria-label="Recorded recommendations" className="mb-4 rounded-xl border border-black/[0.08] bg-white p-3">
    <h4 className="text-sm font-semibold">Recorded recommendations</h4>
    <p className="mt-1 text-xs text-[#6e6e73]">Every saved desk reading · newest first · Eastern time. These are recommendations, not trades in your account.</p>
    {!history?.observations.length ? <p className="mt-2 text-xs text-[#6e6e73]">No recorded recommendations available yet.</p> : <>
      <div className="mt-2 max-h-96 overflow-auto">
        <table className="w-full text-left text-xs tabular-nums [&_td]:px-1 [&_th]:px-1" aria-label="Recommendation timeline">
          <thead className="sticky top-0 bg-white text-[#6e6e73]"><tr><th>Recorded</th><th>Grade</th><th>Suggested allocation</th><th>Entry state</th><th>Price at bar</th><th>Stock since read</th></tr></thead>
          <tbody>{history.observations.map(row => <tr key={row.id} className="border-t border-black/[0.05] align-top">
            <td className="py-2"><span className="whitespace-nowrap">{recorded(row.recorded_at)}</span><div className="text-[9px] text-[#6e6e73]">{row.version} · {row.policy_sha256?.slice(0, 8) ?? 'unidentified'}</div></td>
            <td className="py-2">{row.grade}{row.opportunity_score !== null && row.opportunity_score !== undefined && <div className="text-[10px] text-[#6e6e73]">{row.opportunity_score.toFixed(1)}/10</div>}</td>
            <td className="py-2">{row.allocation === null ? '—' : size(row.allocation)}{row.allocation_change !== null && Math.abs(row.allocation_change) > .00001 && <div className="text-[10px] text-[#6e6e73]">{row.allocation_change > 0 ? '+' : '−'}{Math.abs(row.allocation_change) < .001 ? '<0.1' : (Math.abs(row.allocation_change) * 100).toFixed(1)} pp</div>}</td>
            <td className="py-2">{row.event_paused ? 'Hold · FOMC' : row.entry_state ?? 'Not recorded'}</td>
            <td className="py-2">{row.price.toLocaleString('en-US', {style: 'currency', currency: 'USD'})}</td>
            <td className="py-2">{row.stock_total_return === null ? '—' : `${(row.stock_total_return * 100).toFixed(2)}%`}</td>
          </tr>)}</tbody>
        </table>
      </div>
      <p className="mt-2 text-[11px] text-[#6e6e73]">{history.outcomes?.mark_at ? `Stock changes run from each recorded bar to the latest validated mark at ${recorded(history.outcomes.mark_at)} ET. ` : 'Later stock changes await validated daily data. '}They include recorded splits and dividends. They are hindsight price changes, not a prediction accuracy score, a fill, or your profit. Paused allocations are withheld.</p>
      {(history.invalid_archives > 0 || history.older_records_not_shown) && <p className="mt-1 text-[11px] text-[#6e6e73]">{history.invalid_archives > 0 ? 'Some archive records could not be read. ' : ''}{history.older_records_not_shown ? 'Showing recent observations; older records remain in the archive.' : ''}</p>}
    </>}
  </section>
)
