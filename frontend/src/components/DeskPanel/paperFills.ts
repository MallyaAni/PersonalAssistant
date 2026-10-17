import type {DeskPaperLive, DeskRecordedPaperFill} from '../../services/api'

// Keep a confirmed fill's original clock; malformed, undated or future rows cannot become executions.
const validFill = (fill: unknown, now: number): fill is DeskRecordedPaperFill => {
  if (!fill || typeof fill !== 'object') return false
  const row = fill as DeskRecordedPaperFill
  const at = Date.parse(row.filled_at ?? '')
  return typeof row.symbol === 'string' && row.symbol.length > 0
    && (row.side === 'buy' || row.side === 'sell')
    && Number.isFinite(row.qty) && row.qty > 0 && Number.isFinite(row.price) && row.price > 0
    && typeof row.filled_at === 'string' && /(?:Z|[+-]\d{2}:\d{2})$/.test(row.filled_at)
    && Number.isFinite(at) && at <= now
}

// Date an actual execution in the exchange timezone instead of borrowing its decision session.
export const paperFillSession = (at: string): string => new Intl.DateTimeFormat('en-CA', {timeZone: 'America/New_York'}).format(new Date(at))

// Merge saved terminal fills and today's broker activity as a multiset without changing today's count.
export const confirmedPaperFills = (recorded: DeskPaperLive['recorded_fills'], activity: DeskPaperLive['activity'], now: number): DeskRecordedPaperFill[] => {
  const rows: DeskRecordedPaperFill[] = []
  for (const fill of recorded ?? []) {
    if (!validFill(fill, now)) continue
    const index = fill.client_order_id ? rows.findIndex(row => row.client_order_id === fill.client_order_id) : -1
    if (index < 0) rows.push({...fill})
    else if (Date.parse(fill.reconciled_at ?? fill.filled_at) > Date.parse(rows[index].reconciled_at ?? rows[index].filled_at)) rows[index] = {...fill}
  }
  const matched = new Set<number>()
  for (const fill of activity?.fills ?? []) {
    if (!validFill(fill, now) || paperFillSession(fill.filled_at) !== activity?.session) continue
    const byId = fill.client_order_id ? rows.findIndex(row => row.client_order_id === fill.client_order_id) : -1
    if (byId >= 0) {matched.add(byId); continue}
    const index = rows.findIndex((row, i) => !matched.has(i) && (
      row.client_order_id && fill.client_order_id ? row.client_order_id === fill.client_order_id
        : row.symbol === fill.symbol && row.side === fill.side && row.qty === fill.qty && row.price === fill.price && Date.parse(row.filled_at) === Date.parse(fill.filled_at)))
    if (index >= 0) {matched.add(index); if (!rows[index].client_order_id && fill.client_order_id) rows[index] = {...rows[index], client_order_id: fill.client_order_id}}
    else {matched.add(rows.length); rows.push({...fill})}
  }
  return rows.sort((a, b) => Date.parse(a.filled_at) - Date.parse(b.filled_at) || (a.client_order_id ?? '').localeCompare(b.client_order_id ?? ''))
}
