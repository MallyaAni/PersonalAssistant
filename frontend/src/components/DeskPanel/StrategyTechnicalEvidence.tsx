import type {DeskStrategyDecision} from '../../services/api'

const LABELS: Record<string,string> = {ema_21_distance:'Price vs 21-session EMA',ema_63_distance:'Price vs 63-session EMA',
  return_20:'20-session return',volatility_20:'Daily volatility · 20 sessions',drawdown_252:'From 252-session high'}

// Display recorded numerical inputs consistently without inventing feature attribution or missing values.
export const StrategyTechnicalEvidence = ({evidence}: {evidence?: DeskStrategyDecision['evidence']}) => {
  const rows=Object.entries(evidence?.features ?? {}).filter(([key,value])=>key in LABELS && Number.isFinite(value))
  if(!rows.length) return null
  return <dl className="mt-2 grid grid-cols-2 gap-x-4 gap-y-1 text-xs">{rows.map(([key,value])=><div key={key}>
    <dt className="text-[#6e6e73]">{LABELS[key]}</dt>
    <dd>{((key==='return_20' ? Math.expm1(value) : value)*100).toFixed(2)}%</dd>
  </div>)}</dl>
}
