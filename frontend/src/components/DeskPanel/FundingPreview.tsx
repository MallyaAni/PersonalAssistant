import { useEffect, useState } from 'react'
import { getDeskFundingPreview, type DeskFundingPreview } from '../../services/api'

// Keep a confirmed cash preview local to this account/holdings version and expire it.
export const FundingPreview = ({ userId, equity }: { userId: string; equity: number }) => {
  const [cash, setCash] = useState('')
  const [preview, setPreview] = useState<DeskFundingPreview | null>(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  useEffect(() => {
    if (!preview) return
    const timeout = window.setTimeout(() => {
      setPreview(null)
      setError('Preview expired. Reconfirm cash to calculate again.')
    }, Math.max(0, Date.parse(preview.calculated_at) + 900000 - Date.now()))
    return () => window.clearTimeout(timeout)
  }, [preview])
  return <div className="my-4 rounded-lg border border-black/10 p-3 text-sm">
    <h4 className="font-medium">Cash-limited target preview</h4>
    <p className="my-2 text-xs text-[#6e6e73]">Uses the evening target weights and last known prices. This is planning arithmetic, not a buy-now signal or an executable quote. No proceeds from planned sells are included. Reserve fees and any cash you want to keep before entering your budget.</p>
    <form className="flex flex-wrap items-end gap-3" onSubmit={async event => {
      event.preventDefault()
      if (busy) return
      setPreview(null); setError(''); setBusy(true)
      try { setPreview(await getDeskFundingPreview(userId, equity, Number(cash))) }
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
      <p className="text-xs">Targets from {preview.session}. Estimated additions ${preview.estimated_cost.toFixed(2)} · cash left ${preview.unallocated_cash.toFixed(2)}.{preview.cash_limited ? ' Additions reduced together to fit cash.' : ''}</p>
      {preview.rows.length ? <table className="mt-2 w-full text-left text-xs">
        <thead><tr><th>Name</th><th>Reference price</th><th>Held</th><th>Target total</th><th>Additional shares</th></tr></thead>
        <tbody>{preview.rows.map(row => <tr key={row.ticker}>
          <td className="py-2">{row.ticker}</td><td>${row.reference_price.toFixed(2)}<div className="text-[#6e6e73]">{preview.price_times[row.ticker] ? `Bar starts ${preview.price_times[row.ticker]}` : 'Reference time unavailable'}</div></td>
          <td>{row.held_shares}</td><td>{row.target_total_shares}</td><td>{row.additional_shares}</td>
        </tr>)}</tbody>
      </table> : <p className="mt-2 text-xs">No eligible additions under the current targets and event controls.</p>}
      <p className="mt-2 text-xs text-[#6e6e73]">Whole shares, before execution costs. Cash is not saved. Reconfirm after a recorded fill, position edit, account-size change or page reload. Check your broker’s current quote and available funds before execution.</p>
    </div>}
  </div>
}
