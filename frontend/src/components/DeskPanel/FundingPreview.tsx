import { useCallback, useEffect, useState } from 'react'
import { getDeskFundingPreview, type DeskFundingPreview, type DeskPayload } from '../../services/api'

// How many shares the desk's targets come to, in this account.
//
// This used to refuse to say anything until a cash figure was typed in. It
// did not need one: the target is a percentage of the account, and the
// account's equity is already known, so the share count exists whether or
// not any cash is free today. Cash only ever answered a second question —
// how much of that target can be reached right now — so it is now an
// optional constraint rather than a gate in front of the answer.
//
// The default policy is the live one where a current bar exists, because a
// trader reading this during the session wants this bar's sizing, not last
// night's. The overnight plan stays available and is what the scheduled
// rebalance will actually use.
export const FundingPreview = ({ userId, equity, research, paused = false }: { userId: string; equity: number; research?: DeskPayload['intraday_research']; paused?: boolean }) => {
  const liveReady = research?.status === 'available'
  const [mode, setMode] = useState(liveReady ? 'intraday_research' : 'evening')
  const [cash, setCash] = useState('')
  const [limiting, setLimiting] = useState(false)
  const [preview, setPreview] = useState<DeskFundingPreview | null>(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  // With no cash limit the whole account is the budget, which is what makes
  // the unconstrained target the default answer rather than a special case.
  const budget = limiting && cash !== '' ? Number(cash) : equity
  // Whether this account holds anything at all. With no recorded position
  // the held and target columns carry no information the last column does
  // not already carry.
  const anyHeld = (preview?.rows ?? []).some(row => row.held_shares > 0)

  const load = useCallback(async (forMode: string, forBudget: number) => {
    setPreview(null)
    setError('')
    setBusy(true)
    try {
      setPreview(await getDeskFundingPreview(userId, equity, forBudget, forMode))
    } catch (err) {
      const text = err instanceof Error ? err.message : 'Preview unavailable.'
      // The live sizing needs a completed bar from today's session; after the
      // close the API refuses, and the reason is the clock, not the account.
      setError(/fresh price|technical coverage|market data/i.test(text)
        ? 'Live sizing needs a completed bar from today’s session. Use it during market hours; the overnight plan works any time.'
        : text)
    } finally {
      setBusy(false)
    }
  }, [userId, equity])

  useEffect(() => { void load(mode, budget) }, [load, mode, budget])

  // A preview is a snapshot of prices, so it expires and reloads rather than
  // blanking and asking to be reconfirmed. Only ever scheduled for a moment
  // still in the future: a preview that arrives already past its expiry
  // would otherwise reload on arrival, and each reload would schedule the
  // next, which is an request loop rather than a refresh.
  useEffect(() => {
    if (!preview) return
    const expires = Math.min(
      Date.parse(preview.calculated_at) + 900000,
      preview.valid_until ? Date.parse(preview.valid_until) : Infinity,
    )
    const delay = expires - Date.now()
    if (!Number.isFinite(delay) || delay <= 0) return
    const timer = window.setTimeout(() => { void load(mode, budget) }, delay)
    return () => window.clearTimeout(timer)
  }, [preview, load, mode, budget])

  return <div className="my-4 rounded-lg border border-black/10 p-3 text-sm">
    <h4 className="font-medium">Share sizing</h4>
    <label className="my-2 block text-xs">Sizing policy
      <select aria-label="Sizing policy" value={mode} disabled={busy} className="ml-2 rounded border p-1" onChange={event => setMode(event.target.value)}>
        <option value="intraday_research">Live sizing · this bar</option>
        <option value="evening">Overnight plan · what the rebalance will use</option>
      </select>
    </label>
    <p className="my-2 text-xs text-[#6e6e73]">
      {mode === 'evening'
        ? 'The scheduled targets, priced at reference prices. This is what the next rebalance acts on.'
        : 'Sized on the current bar’s technical read. Research only; the scheduled plan is unchanged.'}
      {' '}No orders are placed from this page.
    </p>
    <details className="my-2 text-xs text-[#6e6e73]"><summary className="cursor-pointer">Sizing details</summary>
      <p className="mt-1">Target shares come from the account equity and the target percentage, so they do not depend on free cash. A cash limit only reduces how much of the target you reach today. Whole shares, before fees; cash is never saved. Re-read after any fill.</p>
      {mode === 'intraday_research' && <p className="mt-1">Current technical grades; evening growth-model valuation retained. Building inflation plus negative daily and weekly benchmark trends tightens the exposure ceiling without compounding cuts. Experimental; scheduled policy unchanged.</p>}
    </details>
    {mode === 'intraday_research' && !liveReady && <p className="my-2 text-xs text-amber-800">{research?.reason ?? 'Waiting for a complete fresh research allocation.'}</p>}

    <div className="flex flex-wrap items-center gap-3">
      <label className="flex items-center gap-1.5 text-xs">
        <input type="checkbox" checked={limiting} disabled={busy} onChange={event => { setLimiting(event.target.checked); if (!event.target.checked) setCash('') }} />
        Limit to the cash I can deploy
      </label>
      {limiting && (
        <label className="text-xs">Cash ($)
          <input className="ml-2 w-28 rounded border p-1" type="number" min="0" max={equity} step="0.01" value={cash} disabled={busy}
            onChange={event => setCash(event.target.value)} />
        </label>
      )}
      {busy && <span className="text-xs text-[#6e6e73]">Calculating…</span>}
    </div>

    {error && <p role="alert" className="mt-2 text-xs text-[#b42318]">{error}</p>}
    {preview && <div className="mt-3 overflow-x-auto">
      {preview.mode === 'intraday_research' && <p className="mb-2 text-xs">Live allocation · valid until {preview.valid_until}. Exposure multiplier {((preview.macro?.exposure ?? 0) * 100).toFixed(0)}%{preview.macro?.defensive ? ' · defensive macro condition active' : ' · no additional macro reduction'}.</p>}
      <p className="text-xs">{preview.mode === 'intraday_research' ? 'Evening context from' : 'Targets from'} {preview.session}. Buying the whole target costs ${preview.estimated_cost.toFixed(2)}.{limiting ? ` Cash left $${preview.unallocated_cash.toFixed(2)}.` : ''}{preview.cash_limited ? ' Additions reduced together to fit the cash limit.' : ''}</p>
      {preview.rows.length ? <table className="mt-2 w-full text-left text-xs">
        {/* With nothing recorded, "held" is zero on every row and the target
            and the amount still to buy are the same number printed twice.
            Three columns where one is meaningful reads as a mistake, so the
            table only separates them once there is a position to separate. */}
        <thead><tr>
          <th>Name</th><th>Price</th>
          {anyHeld && <th>Held</th>}
          {anyHeld && <th>Target total</th>}
          <th>{anyHeld ? (limiting ? 'Buy now' : 'Still to buy') : (limiting ? 'Buy now' : 'Shares')}</th>
        </tr></thead>
        <tbody>{preview.rows.map(row => <tr key={row.ticker}>
          <td className="py-2">{row.ticker}</td><td>${row.reference_price.toFixed(2)}<div className="text-[#6e6e73]">{preview.price_times[row.ticker] ? `Bar starts ${preview.price_times[row.ticker]}` : 'Reference time unavailable'}</div></td>
          {anyHeld && <td>{row.held_shares}</td>}
          {anyHeld && <td>{row.target_total_shares}</td>}
          <td>{row.additional_shares}</td>
        </tr>)}</tbody>
      </table> : <p className="mt-2 text-xs">{paused ? 'No additions while the FOMC cycle is open; the plan resumes when it closes.' : 'No eligible additions under the current targets.'}</p>}
      {!!preview.reductions?.length && <div className="mt-3 text-xs">
        <p>Target reductions · no sale proceeds included in this budget</p>
        {preview.reductions.map(row => <p key={row.ticker} className="mt-1">{row.ticker}: {row.held_shares} held → {row.target_total_shares} target shares · reduction {row.reduction_shares}</p>)}
      </div>}
      <p className="mt-2 text-xs text-[#6e6e73]">Before fees · verify broker price and cash.</p>
    </div>}
  </div>
}
