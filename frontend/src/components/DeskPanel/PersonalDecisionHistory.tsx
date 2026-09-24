import { useEffect, useRef, useState } from 'react'
import {
  acknowledgeDeskHistory,
  deleteDeskPersonalReceipt,
  exportDeskPersonalReceipt,
  getDeskPersonalHistory,
  type DeskDecisions,
  type DeskHistoryReceipt,
  type DeskPersonalHistory,
  type DeskPersonalReceipt,
} from '../../services/api'

export interface PersonalHistoryContext {
  userId: string
  generation: number
  request: number
  decisions?: DeskDecisions
  receipt: DeskHistoryReceipt
}

// Date historical evidence to the second, including the year and exchange timezone.
const receiptTime = (value: string | null) => value && Number.isFinite(Date.parse(value))
  ? `${new Date(value).toLocaleString('en-US', {timeZone: 'America/New_York', year: 'numeric', month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit', second: '2-digit'})} ET`
  : 'Unavailable'

// Preserve unavailable prices instead of converting them into zero-dollar marks.
const receiptPrice = (value: number | null | undefined) => typeof value === 'number' && Number.isFinite(value)
  ? value.toLocaleString('en-US', {style: 'currency', currency: 'USD'}) : 'Unavailable'

// Show saved allocations as percentages, preserving the sign of an intended move.
const receiptWeight = (value: number | null) => typeof value === 'number' && Number.isFinite(value) ? `${(value * 100).toFixed(2)}%` : 'Unavailable'

// Explain which generated snapshot reached the live desk and expose its private history.
export const PersonalDecisionHistory = ({userId, context, decisions, session, written, active, displayPaused, isCurrent}: {
  userId: string
  context: PersonalHistoryContext | null
  decisions?: DeskDecisions
  session?: string
  written?: string
  active: boolean
  displayPaused: boolean
  isCurrent: (context: PersonalHistoryContext) => boolean
}) => {
  const [open, setOpen] = useState(false)
  const [history, setHistory] = useState<DeskPersonalHistory | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [ack, setAck] = useState<{id: string; status: 'pending' | 'saved' | 'failed'; message: string} | null>(null)
  const [confirmDelete, setConfirmDelete] = useState<string | null>(null)
  const [notice, setNotice] = useState('')
  const [query, setQuery] = useState('')
  const attempts = useRef(new Set<string>())
  const mounted = useRef(true)
  const listRequest = useRef(0)

  // Ignore completions after the operator changes account or leaves the desk.
  useEffect(() => {
    mounted.current = true
    return () => { mounted.current = false; listRequest.current += 1 }
  }, [])

  // Load a bounded page and reject an obsolete response after a newer refresh.
  const load = async (before?: string) => {
    const request = ++listRequest.current
    setBusy(true)
    setError('')
    try {
      const page = await getDeskPersonalHistory(userId, before)
      if (!mounted.current || request !== listRequest.current) return
      setHistory(previous => before && previous ? {
        ...page, items: [...previous.items, ...page.items.filter(item => !previous.items.some(existing => existing.id === item.id))],
      } : page)
    } catch (failure) {
      if (mounted.current && request === listRequest.current) setError(failure instanceof Error ? failure.message : 'Personal history could not be loaded.')
    } finally {
      if (mounted.current && request === listRequest.current) setBusy(false)
    }
  }

  // Acknowledgement is an effect of a committed, current live-desk snapshot.
  useEffect(() => {
    const receipt = context?.receipt
    if (!active || document.hidden || !context || context.userId !== userId || receipt?.status !== 'generated'
      || !decisions || context.decisions !== decisions || !isCurrent(context)
      || decisions.session !== session || decisions.written !== written || !session || !written
      || attempts.current.has(receipt.id)) return
    if (displayPaused && Object.values(decisions.rows).some(row => (row.strategy_action ?? row.action) !== 'Hold')) return
    attempts.current.add(receipt.id)
    // Keep recent attempts without growing memory for the lifetime of an open desk.
    if (attempts.current.size > 100) attempts.current.delete(attempts.current.values().next().value!)
    const deadline = Date.parse(receipt.acknowledge_before)
    const stamp = Date.now()
    const expiredAction = Object.values(decisions.rows).some(row => row.executable === true
      && (row.action === 'Buy' || row.action === 'Sell')
      && (!Number.isFinite(Date.parse(row.valid_until ?? '')) || Date.parse(row.valid_until!) <= stamp))
    if (!Number.isFinite(deadline) || deadline <= stamp || expiredAction) {
      setAck({id: receipt.id, status: 'failed', message: 'Snapshot generated, but its execution evidence expired before loading could be acknowledged.'})
      return
    }
    setAck({id: receipt.id, status: 'pending', message: 'Snapshot generated; confirming that it loaded into the dashboard.'})
    void acknowledgeDeskHistory(userId, receipt.id, session, written).then(result => {
      if (!mounted.current) return
      setAck(previous => previous?.id === receipt.id ? {id: receipt.id, status: 'saved', message: `Snapshot loaded into dashboard · acknowledged ${receiptTime(result.acknowledged_at)}`} : previous)
      setHistory(previous => previous ? {...previous, items: previous.items.map(item => item.id === receipt.id ? {...item, acknowledged_at: result.acknowledged_at} : item)} : previous)
    }).catch(failure => {
      if (!mounted.current) return
      setAck(previous => previous?.id === receipt.id ? {id: receipt.id, status: 'failed', message: `Snapshot generated; dashboard loading was not confirmed: ${failure instanceof Error ? failure.message : 'acknowledgement failed'}`} : previous)
    })
  }, [active, context, decisions, displayPaused, isCurrent, session, userId, written])

  // Export exactly one stored receipt as JSON, never the current recalculated guidance.
  const exportReceipt = async (id: string) => {
    setError('')
    try {
      const item = await exportDeskPersonalReceipt(userId, id)
      if (!mounted.current) return
      const url = URL.createObjectURL(new Blob([JSON.stringify(item, null, 2)], {type: 'application/json'}))
      const link = document.createElement('a')
      link.href = url
      link.download = `personal-decision-${id}.json`
      link.click()
      window.setTimeout(() => URL.revokeObjectURL(url), 1000)
      setNotice('The selected stored receipt was exported.')
    } catch (failure) {
      if (mounted.current) setError(failure instanceof Error ? failure.message : 'The receipt could not be exported.')
    }
  }

  // Remove one explicitly confirmed receipt and update the view only after persistence.
  const removeReceipt = async (id: string) => {
    setBusy(true)
    setError('')
    try {
      await deleteDeskPersonalReceipt(userId, id)
      if (!mounted.current) return
      // A page read begun before deletion cannot restore the removed receipt.
      listRequest.current += 1
      setHistory(previous => previous ? {...previous, items: previous.items.filter(item => item.id !== id)} : previous)
      setConfirmDelete(null)
      setNotice('The selected receipt was deleted from active history. Holdings and orders were not changed; backup copies follow the backup retention policy.')
    } catch (failure) {
      if (mounted.current) setError(failure instanceof Error ? failure.message : 'The receipt was not deleted.')
    } finally {
      if (mounted.current) setBusy(false)
    }
  }

  const receipt = context?.receipt
  const status = receipt?.status === 'unavailable' ? `History recording unavailable: ${receipt.reason}`
    : receipt?.status === 'generated' && ack?.id === receipt.id ? ack.message
      : receipt?.status === 'generated' ? 'Snapshot generated; loading into the live dashboard has not been confirmed.'
        : 'Personal history is waiting for a new live-desk snapshot.'
  const failed = receipt?.status === 'unavailable' || (receipt?.status === 'generated' && ack?.id === receipt.id && ack.status === 'failed')
  const ticker = query.trim().toUpperCase()
  return <section aria-label="Personal decision history" className="rounded-xl border border-black/[0.08] bg-white p-3 text-xs">
    <div className="flex flex-wrap items-center justify-between gap-x-3 gap-y-2">
      <p aria-label="Personal history recording status" role="status" className={`min-w-0 flex-1 basis-64 ${failed ? 'text-[#b42318]' : 'text-[#6e6e73]'}`}>{status}</p>
      <button type="button" aria-expanded={open} className="shrink-0 font-medium text-[#0071e3]" onClick={() => { setOpen(!open); if (!open) void load() }}>Personal decision history</button>
    </div>
    {open && <div className="mt-2 space-y-3">
      <p>Private snapshots of generated personal guidance. “Loaded into dashboard” records the browser acknowledgement; it does not prove you saw every stock or placed a trade. Historical actions and quotes are not current instructions. Earlier advice that was never recorded cannot be recovered here.</p>
      <div className="flex flex-wrap gap-3">
        <button type="button" disabled={busy} onClick={() => void load()} className="text-[#0071e3] disabled:opacity-40">Refresh personal history</button>
        <label>Find ticker in loaded snapshots <input aria-label="Find ticker in personal snapshots" value={query} onChange={event => setQuery(event.target.value)} className="ml-2 w-28 rounded border px-2 py-1" /></label>
      </div>
      {error && <p role="alert" className="text-[#b42318]">{error}</p>}
      {notice && <p role="status">{notice}</p>}
      {busy && <p role="status">Loading personal history…</p>}
      {history && <>
        <p className="text-[#6e6e73]">{history.items.length} snapshots loaded. Retention: acknowledged snapshots {history.retention.acknowledged_days} days; unacknowledged snapshots {history.retention.unacknowledged_hours} hours.</p>
        {!history.items.length && <p>No personal decision receipts are available.</p>}
        {history.items.map(item => <Receipt key={item.id} item={item} ticker={ticker} busy={busy} confirmDelete={confirmDelete === item.id}
          onExport={() => void exportReceipt(item.id)} onDelete={() => setConfirmDelete(item.id)} onCancelDelete={() => setConfirmDelete(null)} onConfirmDelete={() => void removeReceipt(item.id)} />)}
        {ticker && history.items.length > 0 && !history.items.some(item => Object.keys(item.payload.rows).some(name => name.includes(ticker))) && <p>No matching ticker in these loaded snapshots.</p>}
        {history.next_cursor && <button type="button" disabled={busy} className="text-[#0071e3] disabled:opacity-40" onClick={() => void load(history.next_cursor!)}>Load older personal snapshots</button>}
        {history.limitations.map((limitation, index) => <p key={index} className="text-[#6e6e73]">{limitation}</p>)}
      </>}
    </div>}
  </section>
}

// Display the immutable generated values and their separate dashboard acknowledgement.
const Receipt = ({item, ticker, busy, confirmDelete, onExport, onDelete, onCancelDelete, onConfirmDelete}: {
  item: DeskPersonalReceipt; ticker: string; busy: boolean; confirmDelete: boolean
  onExport: () => void; onDelete: () => void; onCancelDelete: () => void; onConfirmDelete: () => void
}) => {
  const rows = Object.entries(item.payload.rows).filter(([name]) => !ticker || name.includes(ticker))
  if (ticker && !rows.length) return null
  return <details className="rounded-lg border border-black/[0.08] p-2" aria-label={`Personal receipt ${item.id}`}>
    <summary className="cursor-pointer font-medium">{item.acknowledged_at ? 'Loaded into dashboard' : 'Generated only · loading unconfirmed'} · {receiptTime(item.generated_at)}</summary>
    <div className="mt-2 space-y-2">
      <p>Generated {receiptTime(item.generated_at)}. {item.acknowledged_at ? `Dashboard acknowledgement ${receiptTime(item.acknowledged_at)}.` : 'No dashboard acknowledgement was recorded.'}</p>
      <p>Decision session {item.payload.session} · record written {receiptTime(item.payload.written)} · policy {item.payload.policy_version}</p>
      <div className="overflow-x-auto"><table className="w-full text-left tabular-nums [&_td]:p-2 [&_th]:p-2" aria-label={`Generated personal decisions ${item.id}`}>
        <thead><tr><th>Stock</th><th>Intent at generation</th><th>Action at generation</th><th>Evidence at generation</th><th>Intended move</th><th>Bar price</th><th>Reason</th></tr></thead>
        <tbody>{rows.map(([name, row]) => <tr key={name} className="border-t border-black/[0.05] align-top">
          <td>{name}<div>Decision grade {row.grade ?? 'unavailable'}</div></td>
          <td>{row.strategy_action}</td><td>{row.action}</td>
          <td>{row.executable ? 'Execution checks passed then' : 'Blocked then'}{row.blocker && <div>{row.blocker}</div>}<div>Valid until {receiptTime(row.valid_until)}</div></td>
          <td>{receiptWeight(row.strategy_move_weight)}<div>Executable move {receiptWeight(row.move_weight)}</div></td>
          <td>{receiptPrice(row.bar.price)}<div>{receiptTime(row.bar.at)}</div></td>
          <td>{row.reason}<div>Quote: {row.quote.feed?.toUpperCase() ?? 'Unavailable'} · {receiptPrice(row.quote.bid)} bid / {receiptPrice(row.quote.ask)} ask · {receiptTime(row.quote.at)}</div></td>
        </tr>)}</tbody>
      </table></div>
      <div className="flex flex-wrap gap-3">
        <button type="button" className="text-[#0071e3]" onClick={onExport}>Export this receipt</button>
        {!confirmDelete ? <button type="button" disabled={busy} className="text-[#b42318]" onClick={onDelete}>Delete this receipt</button> : <>
          <span>Delete this history receipt? This does not undo a trade.</span>
          <button type="button" disabled={busy} className="text-[#b42318]" onClick={onConfirmDelete}>Confirm receipt deletion</button>
          <button type="button" disabled={busy} onClick={onCancelDelete}>Keep receipt</button>
        </>}
      </div>
    </div>
  </details>
}
