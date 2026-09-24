import { useState } from 'react'
import type { NeuralStudyEvidence } from '../../services/api'

const ROWS = [
  ['candidate', 'Neural ranking candidate'],
  ['incumbent', 'Incumbent rule'],
  ['equal_weight', 'Equal weight'],
  ['SPY', 'SPY'],
  ['QQQ', 'QQQ'],
] as const

// Preserve a measured zero and distinguish it from an unavailable value.
const number = (value: number | null | undefined, digits = 2) =>
  value == null || !Number.isFinite(value) ? '—' : value.toFixed(digits)

// Display signed returns and drawdowns without treating missing evidence as zero.
const percent = (value: number | null | undefined) =>
  value == null || !Number.isFinite(value) ? '—' : `${value < 0 ? '−' : ''}${Math.abs(value * 100).toFixed(1)}%`

// Show one completed, cost-matched research comparison without changing live guidance.
export const NeuralStudy = ({ study }: { study?: NeuralStudyEvidence | null }) => {
  const [cost, setCost] = useState<'10' | '25'>('10')
  const [period, setPeriod] = useState('full')
  if (!study) return null
  const full = study.tables?.[cost]
  const scorecard = period === 'full' ? full : full?.calendar_years?.[period]
  const years = Object.keys(full?.calendar_years ?? {}).sort()

  return (
    <section aria-label="Price-only neural ranking test" className="rounded-2xl border border-black/[0.08] bg-white p-4 text-xs text-[#6e6e73]">
      <h3 className="text-sm font-semibold text-[#1d1d1f]">Price-only neural ranking test</h3>
      <p className="mt-1">Research only · separate from the frozen nightly neural model · not adopted.</p>
      <p className="mt-2 font-medium text-[#1d1d1f]" aria-label="Neural study decision">{study.decision}</p>
      <div className="mt-3 flex flex-wrap items-center gap-4">
        <label className="flex items-center gap-2">Assumed trading cost
          <select aria-label="Neural study trading cost" value={cost} onChange={event => { setCost(event.target.value as '10' | '25'); setPeriod('full') }} className="rounded border border-black/[0.15] bg-white p-1">
            <option value="10">10 bp</option>
            <option value="25">25 bp</option>
          </select>
        </label>
        <label className="flex items-center gap-2">Period
          <select aria-label="Neural study period" value={period} onChange={event => setPeriod(event.target.value)} className="rounded border border-black/[0.15] bg-white p-1">
            <option value="full">Full study</option>
            {years.map(year => <option key={year} value={year}>{year}</option>)}
          </select>
        </label>
      </div>
      {scorecard ? <>
        <p className="mt-2">{scorecard.first_session} to {scorecard.last_session} · {scorecard.cost_bps} bp per traded dollar</p>
        <div className="mt-2 overflow-x-auto">
          <table aria-label="Neural ranking study results" className="w-full text-left tabular-nums [&_th]:pr-4 [&_td]:pr-4">
            <thead><tr>
              <th scope="col">Policy</th><th scope="col">Total return</th><th scope="col">CAGR</th>
              <th scope="col">Max drawdown</th><th scope="col" title="Zero risk-free rate">Sharpe</th>
              <th scope="col" title="Annual traded notional divided by mean account value; purchases and sales count">Turnover / year</th>
            </tr></thead>
            <tbody>{ROWS.map(([key, label]) => {
              const row = scorecard.rows[key]
              const turnover = number(row?.annual_traded_notional_over_mean_nav)
              return <tr key={key} className="border-t border-black/[0.06]">
                <th scope="row" className="py-2 font-medium text-[#1d1d1f]">{label}</th>
                <td>{percent(row?.total_return)}</td><td>{percent(row?.cagr)}</td>
                <td>{percent(row?.max_drawdown)}</td><td>{number(row?.sharpe_zero_risk_free)}</td>
                <td>{turnover === '—' ? turnover : `${turnover}×`}</td>
              </tr>
            })}</tbody>
          </table>
        </div>
      </> : <p className="mt-3">Results unavailable for this cost and period.</p>}
      {study.limitations.length > 0 && <ul aria-label="Neural study limitations" className="mt-3 list-disc space-y-1 pl-4">
        {study.limitations.map((limitation, index) => <li key={index}>{limitation}</li>)}
      </ul>}
      <p className="mt-2">This comparison does not change live recommendations or submit orders. A dash means unavailable.</p>
    </section>
  )
}
