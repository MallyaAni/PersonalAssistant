import type {DeskCurrentSetup, DeskLive} from '../../services/api'
import type {BoardRow} from './TradeBoard'
import {currentAssessments} from './liveAssessment'
import {displayedBoardPrice} from './StockBoard'

const gradeOrder: Record<string, number> = {'A+': 3, A: 2, B: 1, C: 0}
const priorityOrder = {high: 3, medium: 2, low: 1}

// Withhold a judgment as soon as its own evidence expires or the candle changes.
export const currentSetup = (live: DeskLive, session: string, ticker: string, now: number): DeskCurrentSetup | null => {
  const row = live.opportunities?.rows?.[ticker]
  const grade = currentAssessments(live, session, now)[ticker]
  if (!grade || !row || row.status !== 'model_assessment' || row.bar !== live.quotes[ticker]?.bar
      || !Number.isFinite(row.price) || row.price <= 0
      || Date.parse(row.generated_at) > now || !(Date.parse(row.valid_until) > now)) return null
  if (row.entry === 'ready' && grade.grade_live !== 'A' && grade.grade_live !== 'A+')
    return {...row, entry: 'avoid', reason: 'The current grade no longer permits a new entry.'}
  if (row.entry === 'ready' && live.market_status?.phase && live.market_status.phase !== 'open')
    return {...row, entry: 'wait', reason: 'Regular-session entry review is waiting for the next open session.'}
  const displayed = displayedBoardPrice(live, ticker, now)
  const latest = displayed?.current && displayed.kind === 'midpoint' && displayed.word === 'regular' ? displayed.price : null
  if (row.entry === 'ready' && latest == null)
    return {...row, entry: 'wait', reason: 'A fresh regular-session quote is required before reviewing this entry.'}
  const invalidation = row.levels[row.invalidation_ref]?.price
  const confirmation = row.levels[row.confirmation_ref]?.price
  if (row.entry === 'ready' && latest != null && (
      invalidation != null && latest <= invalidation
      || confirmation != null && latest < confirmation))
    return {...row, entry: 'wait', reason: 'The latest quote lost the setup’s required level; wait for reassessment.'}
  return row
}

// Render only a model-selected reference's measured price and confirmation relation.
export const confirmationText = (setup: DeskCurrentSetup): string => {
  const reference = setup.levels[setup.confirmation_ref]
  if (!reference || setup.confirmation === 'none') return 'Entry confirmation not established.'
  const verbs = {hold_above: 'Hold above', reclaim_above: 'Reclaim and hold above'}
  return `${verbs[setup.confirmation]} ${reference.label} at $${reference.price.toFixed(2)}.`
}

// Distinguish a ready entry's loss level from references for an unconfirmed setup.
export const invalidationText = (setup: DeskCurrentSetup): string => {
  const reference = setup.levels[setup.invalidation_ref]
  if (!reference) return 'Reassessment level unavailable.'
  return setup.entry === 'ready'
    ? `Reassess if price loses ${reference.label} at $${reference.price.toFixed(2)}.`
    : `Reassessment reference: ${reference.label} at $${reference.price.toFixed(2)}.`
}

// Compare the fresh quote with the model-selected reference without creating a new verdict.
export const quoteReferenceText = (live: DeskLive, ticker: string, setup: DeskCurrentSetup, now: number): string => {
  const quote = displayedBoardPrice(live, ticker, now)
  if (!quote?.current || quote.kind !== 'midpoint' || quote.word !== 'regular')
    return 'Latest regular-session quote unavailable; wait for a fresh price.'
  const reference = setup.levels[setup.confirmation_ref]
  if (!reference) return `Latest quote $${quote.price.toFixed(2)}; entry confirmation is not established.`
  const relation = quote.price >= reference.price ? 'above' : 'below'
  return `Latest quote $${quote.price.toFixed(2)} is ${relation} the $${reference.price.toFixed(2)} confirmation reference; ${setup.entry === 'ready' ? 'setup remains ready for review' : `entry remains ${setup.entry.toUpperCase()} until reassessed`}.`
}

// Rank fresh opportunity judgments and actual holdings without borrowing saved targets.
export const rankCurrent = (rows: BoardRow[], live: DeskLive, session: string, now: number, accountAvailable: boolean): BoardRow[] => {
  const assessments = currentAssessments(live, session, now)
  const projected = rows.map(row => {
    const grade = assessments[row.ticker]?.grade_live
    const setup = currentSetup(live, session, row.ticker, now)
    const eligible = grade === 'A' || grade === 'A+'
    const exit = accountAvailable && row.held > 0 && (grade === 'B' || grade === 'C')
    const review = accountAvailable && row.held > 0 && eligible && setup?.exit === 'review'
    const ready = eligible && setup?.entry === 'ready'
    const category = row.orders.length ? 0 : exit ? 1 : review ? 2 : ready ? 3 : eligible ? 4 : grade ? 5 : 6
    const word: BoardRow['word'] = row.orders.length ? row.word : exit ? 'SELL' : review ? 'HOLD' : ready ? 'BUY'
      : eligible ? 'WAIT' : row.held > 0 ? 'HOLD' : '—'
    const signal = row.orders.length ? row.signal : exit ? 'sell' : review ? 'hold' : ready ? 'buy'
      : eligible ? 'wait' : grade ? row.held > 0 ? 'hold' : 'avoid' : 'unavailable'
    const why = row.orders.length ? row.why : exit ? 'Current grade below A; remaining holding requires an exit plan.'
      : setup?.reason ?? live.opportunities?.unavailable?.[row.ticker] ?? (grade ? eligible ? 'Chart judgment updating; entry permission alone is not an entry decision.'
        : 'Current grade does not permit a new entry.' : 'Fresh assessment unavailable; current opportunity is not ranked.')
    return {...row, word, signal, why, status: row.orders.length ? row.status : why,
      currentSetup: setup, opportunityBand: category, freshGrade: grade,
      opportunityScore: assessments[row.ticker]?.score_live ?? -Infinity,
      judgmentPriority: priorityOrder[(exit || review ? setup?.exit_priority : setup?.entry_priority) ?? 'low']}
  })
  return projected.sort((a, b) => a.opportunityBand - b.opportunityBand
    || b.judgmentPriority - a.judgmentPriority
    || (a.opportunityBand <= 2 ? 1 : -1) * ((gradeOrder[a.freshGrade ?? ''] ?? -1) - (gradeOrder[b.freshGrade ?? ''] ?? -1))
    || (a.opportunityBand <= 2 ? a.opportunityScore - b.opportunityScore : b.opportunityScore - a.opportunityScore)
    || a.ticker.localeCompare(b.ticker)) as BoardRow[]
}
