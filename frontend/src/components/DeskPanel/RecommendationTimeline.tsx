import type { DeskRecommendationHistory } from '../../services/api'

// Preserve the distinction between a small positive size and an explicit zero.
const size = (weight: number) => weight > 0 && weight < .001 ? '<0.1%' : `${(weight * 100).toFixed(1)}%`

// Date each original recommendation to the second in exchange time.
const recorded = (value: string) => new Date(value).toLocaleString('en-US', {
  timeZone: 'America/New_York', month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit', second: '2-digit',
})

type Observation = DeskRecommendationHistory['observations'][number]

// What a person would act on: the grade, the size and the state. Two
// observations that agree on all three are the same recommendation.
const acted = (row: Observation) => [row.grade, row.allocation === null ? '—' : row.allocation.toFixed(4), row.event_paused ? 'FOMC' : row.entry_state ?? ''].join('|')

// Fold the fifteen-minute log into the recommendations that changed: the
// row is the observation that first said it, with how long it held. A log
// of forty identical rows told the reader nothing about when to act.
export const folded = (observations: Observation[]) => {
  const oldestFirst = [...observations].reverse()
  const runs: {row: Observation; held: number; through: string}[] = []
  for (const row of oldestFirst) {
    const last = runs[runs.length - 1]
    if (last && acted(last.row) === acted(row)) { last.held += 1; last.through = row.recorded_at } else runs.push({row, held: 1, through: row.recorded_at})
  }
  return runs.reverse()
}

// Keep recorded model allocations separate from subsequent stock moves and actual fills.
export const RecommendationTimeline = ({history}: {history?: DeskRecommendationHistory}) => (
  <section aria-label="Recorded recommendations" className="mb-4 rounded-xl border border-black/[0.08] bg-white p-3">
    <h4 className="text-sm font-semibold">Recommendations</h4>
    <p className="mt-1 text-xs text-[#6e6e73]">Original model log · newest first · ET · a row for each change in grade, size or state</p>
    {!history?.observations.length ? <p className="mt-2 text-xs text-[#6e6e73]">No recorded recommendations available yet.</p> : <>
      <div className="mt-2 max-h-96 overflow-auto">
        <table className="w-full text-left text-xs tabular-nums [&_td]:px-1 [&_th]:px-1" aria-label="Recommendation timeline">
          <thead className="sticky top-0 bg-white text-[#6e6e73]"><tr><th>Recorded</th><th>Grade</th><th>Size %</th><th>State</th><th>Bar price</th><th>Stock move</th></tr></thead>
          <tbody>{folded(history.observations).map(({row, held, through}) => <tr key={row.id} className="border-t border-black/[0.05] align-top">
            <td className="py-2"><span className="whitespace-nowrap">{recorded(row.recorded_at)}</span>{held > 1 && <div className="text-[10px] text-[#6e6e73]">held through {recorded(through)} · {held} readings</div>}<div className="text-[9px] text-[#6e6e73]">{row.version} · {row.policy_sha256?.slice(0, 8) ?? 'unidentified'}</div></td>
            <td className="py-2">{row.grade}{row.opportunity_score !== null && row.opportunity_score !== undefined && <div className="text-[10px] text-[#6e6e73]">{row.opportunity_score.toFixed(1)}/10</div>}</td>
            <td className="py-2">{row.allocation === null ? '—' : size(row.allocation)}{row.allocation_change !== null && Math.abs(row.allocation_change) > .00001 && <div className="text-[10px] text-[#6e6e73]">{row.allocation_change > 0 ? '+' : '−'}{Math.abs(row.allocation_change) < .001 ? '<0.1' : (Math.abs(row.allocation_change) * 100).toFixed(1)} pp</div>}</td>
            <td className="py-2">{row.event_paused ? 'Wait · FOMC' : row.entry_state ?? 'Not recorded'}</td>
            <td className="py-2">{row.price.toLocaleString('en-US', {style: 'currency', currency: 'USD'})}</td>
            <td className="py-2">{row.stock_total_return === null ? '—' : `${(row.stock_total_return * 100).toFixed(2)}%`}</td>
          </tr>)}</tbody>
        </table>
      </div>
      <p className="mt-2 text-[11px] text-[#6e6e73]">{history.outcomes?.mark_at ? `Stock moves through ${recorded(history.outcomes.mark_at)} ET. ` : 'Stock outcomes await validated daily data. '}Moves include recorded splits and dividends, exclude trading costs, and are not strategy profit. Paused sizes are withheld.</p>
      {(history.invalid_archives > 0 || history.older_records_not_shown) && <p className="mt-1 text-[11px] text-[#6e6e73]">{history.invalid_archives > 0 ? 'Some archive records could not be read. ' : ''}{history.older_records_not_shown ? 'Showing recent observations; older records remain in the archive.' : ''}</p>}
    </>}
  </section>
)
