import type {DeskStrategyDecision} from '../../services/api'

const LABELS: Record<string,string> = {ema_21_distance:'Price vs 21-session EMA',ema_63_distance:'Price vs 63-session EMA',
  return_20:'20-session return',volatility_20:'Daily volatility · 20 sessions',drawdown_252:'From 252-session high'}

// Explain recorded model-position changes alongside saved inputs, without implying viewer holdings or causal feature attribution.
export const StrategyTechnicalEvidence = ({evidence}: {evidence?: DeskStrategyDecision['evidence']}) => {
  const rows=Object.entries(evidence?.features ?? {}).filter(([key,value])=>key in LABELS && Number.isFinite(value))
  const before=evidence?.reference_position_size,after=evidence?.model_position_size
  const position=typeof before==='number' && Number.isFinite(before) && typeof after==='number' && Number.isFinite(after)
  if(!rows.length && !position) return null
  return <div className="mt-2 space-y-1 text-xs">
    {position && <p>Model position {(before*100).toFixed(1)}% → {(after*100).toFixed(1)}%</p>}
    <dl className="grid grid-cols-2 gap-x-4 gap-y-1">{rows.map(([key,value])=><div key={key}>
    <dt className="text-[#6e6e73]">{LABELS[key]}</dt>
    <dd>{((key==='return_20' ? Math.expm1(value) : value)*100).toFixed(2)}%</dd>
  </div>)}</dl></div>
}
