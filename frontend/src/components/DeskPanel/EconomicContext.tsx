import type { DeskEconomics } from '../../services/api'

// Display measured inflation separately from the model's research interpretation.
export const EconomicContext = ({ data }: { data?: DeskEconomics | null }) => {
  // Preserve missing values and percentage-point signs without inventing precision.
  const change = (value?: number | null) => typeof value === 'number' && Number.isFinite(value) ? `${value.toFixed(2)}%` : 'Unavailable'
  const stale = !data || data.collection_stale || Date.now() - Date.parse(data.observed_at) >= 36 * 3600000
  return <section aria-label="Economic context" className="rounded-xl border border-black/10 bg-white p-4 text-sm">
    <h3 className="font-medium">Inflation evidence · research context</h3>
    {!data ? <p className="mt-2 text-xs text-[#6e6e73]">Economic evidence has not been collected. Missing data is not a benign-market signal.</p> : <>
      <p className="mt-2 text-xs">Collected {data.observed_at}{stale ? ' · collection stale' : ''}. Monthly observations; collection time is not release time.</p>
      <div className="mt-3 overflow-x-auto"><table className="w-full text-left text-xs">
        <thead><tr><th>Measure</th><th>Observation month</th><th>Month over month</th><th>Year over year</th><th>Prior month’s year over year</th></tr></thead>
        <tbody>{data.facts.map(fact => <tr key={fact.id} className="border-t border-black/5">
          <td className="py-2">{fact.source ? <a href={fact.source} target="_blank" rel="noreferrer" className="text-[#0071e3]">{fact.label}</a> : fact.label}{fact.status !== 'available' && <span> · {fact.status}</span>}</td>
          <td>{fact.period?.slice(0, 7) ?? 'Unavailable'}</td><td>{change(fact.month_change_pct)}</td><td>{change(fact.year_change_pct)}</td><td>{change(fact.previous_year_change_pct)}</td>
        </tr>)}</tbody>
      </table></div>
      {data.assessment?.status === 'model_assessment' && !stale
        ? <p className="mt-2 text-xs">{data.model ?? 'Model'} assessment: {data.assessment.pressure} inflation pressure. Evidence: {data.assessment.evidence_ids.join(', ') || 'insufficient available observations'}.</p>
        : <p className="mt-2 text-xs">{stale ? 'Model assessment withheld because collection is stale.' : 'Model assessment unavailable; no model conclusion is shown.'}</p>}
    </>}
    <p className="mt-2 text-xs text-[#6e6e73]">Changes use seasonally adjusted indexes and current revisions. Release timestamps and consensus expectations are unavailable, so this does not measure a release surprise. Observation months older than 75 days and collections older than 36 hours are flagged. This assessment informs the separate intraday research preview; it does not change the scheduled trading policy or submit orders.</p>
  </section>
}
