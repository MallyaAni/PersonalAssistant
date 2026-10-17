import type {DeskCurrentSetup, DeskLive} from '../../services/api'
import type {BoardRow} from './TradeBoard'
import {currentAssessments} from './liveAssessment'
import {displayedBoardPrice} from './StockBoard'

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

// Attach chart evidence without replacing the recorded action, quantity, timing or order ranking.
export const rankCurrent = (rows: BoardRow[], live: DeskLive, session: string, now: number): BoardRow[] => {
  const assessments = currentAssessments(live, session, now)
  return rows.map(row => ({...row, currentSetup: currentSetup(live, session, row.ticker, now),
    freshGrade: assessments[row.ticker]?.grade_live}))
}
