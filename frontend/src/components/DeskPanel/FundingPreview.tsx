import { useEffect, useState } from 'react'
import { getDeskFundingPreview, type DeskFundingPreview, type DeskPayload } from '../../services/api'

// Keep a confirmed cash preview local to this account/holdings version and expire it.
export const FundingPreview = ({ userId, equity, research }: { userId: string; equity: number; research?: DeskPayload['intraday_research'] }) => {
  const [mode, setMode] = useState('evening')
  const [cash, setCash] = useState('')
  const [preview, setPreview] = useState<DeskFundingPreview | null>(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  useEffect(() => {
    if (!preview) return
    const timeout = window.setTimeout(() => {
      setPreview(null)
      setError('Preview expired. Reconfirm cash to calculate again.')
    }, Math.max(0, Math.min(Date.parse(preview.calculated_at) + 900000, preview.valid_until ? Date.parse(preview.valid_until) : Infinity) - Date.now()))
    return () => window.clearTimeout(timeout)
  }, [preview])
  return <div className="my-4 rounded-lg border border-black/10 p-3 text-sm">
    <h4 className="font-medium">Share sizing</h4>
    <label className="my-2 block text-xs">Sizing policy
      <select aria-label="Sizing policy" value={mode} disabled={busy} className="ml-2 rounded border p-1" onChange={event => { setMode(event.target.value); setPreview(null); setError('') }}>
        <option value="evening">Evening targets</option>
        <option value="intraday_research">Intraday + macro research</option>
      </select>
    </label>
    <p className="my-2 text-xs text-[#6e6e73]">{mode === 'evening' ? 'Scheduled targets · reference prices' : 'Research only · current technical sizing'} · no orders placed.</p>
    <details className="my-2 text-xs text-[#6e6e73]"><summary className="cursor-pointer">Sizing details</summary>
      <p className="mt-1">Cash excludes pending sales. Reserve fees before entering your budget. Whole shares; cash is not saved. Reconfirm after any fill or account change.</p>
      {mode === 'intraday_research' && <p className="mt-1">Current technical grades; evening growth-model valuation retained. Building inflation plus negative daily and weekly benchmark trends tightens the exposure ceiling without compounding cuts. Experimental; scheduled policy unchanged.</p>}
    </details>
    {mode === 'intraday_research' && research?.status !== 'available' && <p className="my-2 text-xs text-amber-800">{research?.reason ?? 'Waiting for a complete fresh research allocation.'}</p>}
    <form className="flex flex-wrap items-end gap-3" onSubmit={async event => {
      event.preventDefault()
      if (busy) return
      setPreview(null); setError(''); setBusy(true)
      try { setPreview(await getDeskFundingPreview(userId, equity, Number(cash), mode)) }
      catch (err) { setError(err instanceof Error ? err.message : 'Preview unavailable.') }
      finally { setBusy(false) }
    }}>
      <label className="text-xs">Available cash to allocate ($)
        <input className="ml-2 w-28 rounded border p-1" required type="number" min="0" max={equity} step="0.01" value={cash} disabled={busy}
          onChange={event => { setCash(event.target.value); setPreview(null) }} />
      </label>
      <button className="text-xs text-[#0071e3]" type="submit" disabled={busy}>{busy ? 'Calculating…' : 'Confirm cash and preview'}</button>
    </form>
    {error && <p role="alert" className="mt-2 text-xs text-[#b42318]">{error}</p>}
    {preview && <div className="mt-3 overflow-x-auto">
      {preview.mode === 'intraday_research' && <p className="mb-2 text-xs">Research allocation · valid until {preview.valid_until}. Exposure multiplier {((preview.macro?.exposure ?? 0) * 100).toFixed(0)}%{preview.macro?.defensive ? ' · defensive macro condition active' : ' · no additional macro reduction'}.</p>}
      <p className="text-xs">{preview.mode === 'intraday_research' ? 'Evening context from' : 'Targets from'} {preview.session}. Estimated additions ${preview.estimated_cost.toFixed(2)} · cash left ${preview.unallocated_cash.toFixed(2)}.{preview.cash_limited ? ' Additions reduced together to fit cash.' : ''}</p>
      {preview.rows.length ? <table className="mt-2 w-full text-left text-xs">
        <thead><tr><th>Name</th><th>Reference price</th><th>Held</th><th>Target total</th><th>Additional shares</th></tr></thead>
        <tbody>{preview.rows.map(row => <tr key={row.ticker}>
          <td className="py-2">{row.ticker}</td><td>${row.reference_price.toFixed(2)}<div className="text-[#6e6e73]">{preview.price_times[row.ticker] ? `Bar starts ${preview.price_times[row.ticker]}` : 'Reference time unavailable'}</div></td>
          <td>{row.held_shares}</td><td>{row.target_total_shares}</td><td>{row.additional_shares}</td>
        </tr>)}</tbody>
      </table> : <p className="mt-2 text-xs">No eligible additions under the current targets and event controls.</p>}
      {!!preview.reductions?.length && <div className="mt-3 text-xs">
        <p>Research target reductions · no sale proceeds included in this budget</p>
        {preview.reductions.map(row => <p key={row.ticker} className="mt-1">{row.ticker}: {row.held_shares} held → {row.target_total_shares} target shares · reduction {row.reduction_shares}</p>)}
      </div>}
      <p className="mt-2 text-xs text-[#6e6e73]">Before fees · verify broker price and cash.</p>
    </div>}
  </div>
}
