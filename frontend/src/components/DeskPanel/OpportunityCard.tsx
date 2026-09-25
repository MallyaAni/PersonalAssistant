import type { DeskOpportunity } from '../../services/api'
import { EVENING_VOTE_CONTEXT, analystLabel } from './analystLabels'

// Explain every contribution without presenting analyst conviction as a return forecast.
export const OpportunityCard = ({reading, now}: {reading?: DeskOpportunity; now: number}) => {
  const current = reading?.score !== null && reading?.score !== undefined && Date.parse(reading.valid_until ?? '') > now
  // After the close the candle's deadline has passed, so the score is not
  // current; the evidence still has a reading, shown dated to its bar
  // rather than as "Not scored", which read as if there were no evidence.
  const last = !current && reading?.last_score !== null && reading?.last_score !== undefined ? reading.last_score : null
  const barTime = reading?.bar ? new Date(reading.bar).toLocaleString('en-US', {timeZone: 'America/New_York', month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit'}) : null
  const shown = current || last !== null
  const total = reading?.parts.reduce((sum, part) => sum + part.weight, 0) ?? 0
  return <section aria-label="Opportunity score" className="mb-4 rounded-xl border border-black/[0.08] bg-white p-3">
    <div className="flex items-baseline justify-between gap-2"><h4 className="text-sm font-semibold">Opportunity</h4><strong className={current ? '' : 'text-[#6e6e73]'}>{current ? `${reading!.score!.toFixed(1)}/10` : last !== null ? `${last.toFixed(1)}/10` : 'Not scored'}</strong></div>
    <p className="mt-1 text-xs text-[#6e6e73]">{current ? `Indicative at ${reading!.price!.toLocaleString('en-US', {style: 'currency', currency: 'USD'})}`
      : last !== null ? `Last reading${barTime ? ` at the ${barTime} ET bar` : ''} · refreshes with the next candle`
      : 'Fresh, complete analyst evidence is required.'}</p>
    <p className="mt-1 text-[11px] text-[#6e6e73]">Continuous analyst conviction, not the combined grade. {EVENING_VOTE_CONTEXT}</p>
    {shown && <>
      <p className="mt-1 text-[11px] text-[#6e6e73]">Analyst evidence index · not a return forecast{!reading!.valuation_current ? ' · valuation is nightly' : ''}</p>
      <div className="mt-3 space-y-2">{[...reading!.parts].sort((a, b) => b.weight * (b.score - 5) - a.weight * (a.score - 5)).map(part => <div key={part.analyst} className="text-xs">
        <div className="flex justify-between gap-2"><span>{analystLabel(part.analyst)}</span><span>{part.score.toFixed(1)}/10 · {total > 0 ? `${(part.weight / total * 100).toFixed(0)}% weight` : 'no weight'}</span></div>
        <p className="text-[11px] text-[#6e6e73]">{part.score > 5 ? 'Raises score' : part.score < 5 ? 'Lowers score' : 'Neutral'} · {part.basis === 'intraday' ? 'intraday reading' : `${part.basis} close`}{part.source === 'recorded_vote' ? ' · recorded vote' : ''}</p>
        {part.evidence[0] && <p className="mt-0.5 text-[11px] text-[#6e6e73]">{part.basis === 'intraday' ? 'Prior-close context: ' : ''}{part.evidence[0]}</p>}
      </div>)}</div>
      {!!reading!.missing?.length && <p className="mt-3 rounded bg-[#fff8e6] p-2 text-[11px] text-[#6e6e73]">
        <span className="font-medium text-[#1d1d1f]">{reading!.missing.map(analystLabel).join(' and ')} had no usable percentile or fallback vote for this score.</span>{' '}
        This name is missing the data {reading!.missing.length === 1 ? 'that analyst needs' : 'those analysts need'}, so the score above is the
        remaining {reading!.parts.length} renormalised to full weight, and the weights below are shares of what is left.
        That is not the same as {reading!.missing.length === 1 ? 'a neutral vote' : 'neutral votes'}: a name can rank high here on a
        narrow read. Compare it against names with the full panel carefully.
      </p>}
      <p className="mt-3 text-[11px] text-[#6e6e73]">A high score does not override the plan, FOMC restrictions or position limits.</p>
    </>}
  </section>
}
