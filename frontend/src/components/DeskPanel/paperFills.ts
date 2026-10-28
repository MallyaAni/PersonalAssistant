import type {DeskPaperLive, DeskRecordedPaperFill} from '../../services/api'
import {isLabel, ORDER_SIDES} from '../../services/labels'

// Keep a confirmed fill's original clock; malformed, undated or future rows cannot become executions.
const validFill = (fill: unknown, now: number): fill is DeskRecordedPaperFill => {
  if (!fill || typeof fill !== 'object') return false
  const row = fill as DeskRecordedPaperFill
  const at = Date.parse(row.filled_at ?? '')
  return typeof row.symbol === 'string' && row.symbol.length > 0
    && isLabel(ORDER_SIDES, row.side)
    && Number.isFinite(row.qty) && row.qty > 0 && Number.isFinite(row.price) && row.price > 0
    && typeof row.filled_at === 'string' && /(?:Z|[+-]\d{2}:\d{2})$/.test(row.filled_at)
    && Number.isFinite(at) && at <= now
}

// Date an actual execution in the exchange timezone instead of borrowing its decision session.
export const paperFillSession = (at: string): string => new Intl.DateTimeFormat('en-CA', {timeZone: 'America/New_York'}).format(new Date(at))

// Identify an explicit broker activity day even when its read is incomplete or contains no fills.
export const paperActivitySession = (activity: DeskPaperLive['activity']): string | null => {
  const session = activity?.session
  if (!Array.isArray(activity?.fills) || typeof session !== 'string') return null
  const at = Date.parse(`${session}T00:00:00Z`)
  return Number.isFinite(at) && new Date(at).toISOString().slice(0, 10) === session ? session : null
}

// Use broker events exclusively for their dated read and journal totals on other days, never summing both.
export const confirmedPaperFills = (recorded: DeskPaperLive['recorded_fills'], activity: DeskPaperLive['activity'], now: number): DeskRecordedPaperFill[] => {
  const activitySession = paperActivitySession(activity)
  const rows: DeskRecordedPaperFill[] = []
  for (const fill of recorded ?? []) {
    if (!validFill(fill, now) || paperFillSession(fill.filled_at) === activitySession) continue
    const index = fill.client_order_id ? rows.findIndex(row => row.client_order_id === fill.client_order_id) : -1
    if (index < 0) rows.push({...fill})
    else if (Date.parse(fill.reconciled_at ?? fill.filled_at) > Date.parse(rows[index].reconciled_at ?? rows[index].filled_at)) rows[index] = {...fill}
  }
  for (const fill of activity?.fills ?? []) {
    if (!validFill(fill, now) || paperFillSession(fill.filled_at) !== activitySession) continue
    // Separate broker events may share an order ID or tuple; only the broker can identify an event duplicate.
    rows.push({...fill})
  }
  return rows.sort((a, b) => Date.parse(a.filled_at) - Date.parse(b.filled_at) || (a.client_order_id ?? '').localeCompare(b.client_order_id ?? ''))
}
