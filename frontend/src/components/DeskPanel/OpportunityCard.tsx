import type { DeskOpportunity } from '../../services/api'

// Explain every contribution without presenting analyst conviction as a return forecast.
export const OpportunityCard = ({reading, now}: {reading?: DeskOpportunity; now: number}) => {
  const current = reading?.score !== null && reading?.score !== undefined && Date.parse(reading.valid_until ?? '') > now
  const total = reading?.parts.reduce((sum, part) => sum + part.weight, 0) ?? 0
  return <section aria-label="Price-to-opportunity score" className="mb-4 rounded-xl border border-black/[0.08] bg-white p-3">
    <div className="flex items-baseline justify-between gap-2"><h4 className="text-sm font-semibold">Price-to-opportunity</h4><strong>{current ? `${reading!.score!.toFixed(1)}/10` : 'Not scored'}</strong></div>
    <p className="mt-1 text-xs text-[#6e6e73]">{current ? `Indicative at ${reading!.price!.toLocaleString('en-US', {style: 'currency', currency: 'USD'})}` : 'Fresh, complete analyst evidence is required.'}</p>
    {current && <>
      <p className="mt-1 text-[11px] text-[#6e6e73]">Analyst evidence index · not a return forecast{!reading!.valuation_current ? ' · valuation is nightly' : ''}</p>
      <div className="mt-3 space-y-2">{[...reading!.parts].sort((a, b) => b.weight * (b.score - 5) - a.weight * (a.score - 5)).map(part => <div key={part.analyst} className="text-xs">
        <div className="flex justify-between gap-2"><span className="capitalize">{part.analyst}</span><span>{part.score.toFixed(1)}/10 · {total > 0 ? `${(part.weight / total * 100).toFixed(0)}% weight` : 'no weight'}</span></div>
        <p className="text-[11px] text-[#6e6e73]">{part.score > 5 ? 'Raises score' : part.score < 5 ? 'Lowers score' : 'Neutral'} · {part.basis === 'intraday' ? 'current bar' : `${part.basis} close`}{part.source === 'recorded_vote' ? ' · recorded vote' : ''}</p>
        {part.evidence[0] && <p className="mt-0.5 text-[11px] text-[#6e6e73]">{part.basis === 'intraday' ? 'Prior-close context: ' : ''}{part.evidence[0]}</p>}
      </div>)}</div>
      <p className="mt-3 text-[11px] text-[#6e6e73]">A high score does not override Wait, FOMC restrictions or position limits.</p>
    </>}
  </section>
}
