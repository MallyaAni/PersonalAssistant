import {useEffect, useMemo, useRef, useState} from 'react'
import type {DeskCurrentSetup, DeskEntryReasonCode, DeskEntryVerdict, DeskLive, DeskModelAllocation, DeskRecord, DeskStrategyDecision, DeskStrategyStock} from '../../services/api'
import {currentSetup, confirmationText, invalidationText} from './currentRanking'
import {currentAssessments} from './liveAssessment'
import {displayedBoardPrice, SessionPrice} from './StockBoard'
import {StrategyTechnicalEvidence} from './StrategyTechnicalEvidence'

type Side = 'all' | 'buy' | 'sell'
type Signal = {word: string; ready: boolean; priority: string; rank: number; reason: string}
// The row's existing signals plus the backend's one-word verdict when it supplies one.
export type Signals = {ticker: string; grade: string; setup: DeskCurrentSetup | null; buy: Signal; sell: Signal; evidence?: DeskStrategyDecision['evidence']; current?: {completed: string; quote: string; until: string}; plan?: {session: string; published: string; validUntil: string; calculated?: string}; nextSession?: boolean; lastPlan?: boolean;
  verdict?: 'buy' | 'sell' | 'nothing'; reason_code?: string; size_weight?: number; verdict_reason?: string}
const PRIORITY: Record<string, number> = {high: 3, medium: 2, low: 1}

// Read the backend's closed verdict vocabulary in plain words; the same words
// are used when an older publication carries no verdict and the row falls back.
const REASON_WORDS: Record<DeskEntryReasonCode, string> = {
  execute_now: 'Act now at the current price',
  waiting_better_price: 'Wait one candle for a better price',
  at_target: 'The model position is already at target',
  no_allocation: 'No model allocation for this name',
  grade_below_a: 'The grade is below A',
  awaiting_candle: 'Awaiting a completed 15-minute candle',
  publication_expired: 'The published assessment has expired',
  quote_stale: 'A fresh compatible quote is required',
  price_unavailable: 'No compatible execution price is available',
  entry_pending: 'Entry price not yet confirmed this candle',
}

// `state` is the one structured qualifier the verdict cell shows beside the word.
type VerdictView = {verdict: DeskEntryVerdict; reason: string; size: number | null; nextSession: boolean; lastPlan: boolean; observedAt: string | null; validUntil: number; sourceAt: number; state?: 'pending' | 'unavailable'}

export type StrategyChartTarget = {ticker: string; date: string; at: string; validUntil: string | null; action: 'Buy' | 'Sell' | null; weight: number; record: string; strategyIdentity?: string; evidence?: DeskStrategyDecision['evidence']; entry?: {at: string; validUntil: string}; entryReason?: string; recordedHistoryAvailable?: boolean; nextSessionPlan?: boolean; displayAction?: string; referenceTransition?: boolean; positionWeight?: number; tradeWeight?: number | null}

// Recognize the independently authenticated publication formats without consulting an account.
const independentAllocation = (allocation?: DeskModelAllocation): boolean => allocation?.version === 'strategy-model-allocation/1' || allocation?.version === 'strategy-model-allocation/2'


// Admit only the separately declared standing or observed-hypothetical reference formats.
const referenceEntryFormat = (entry: DeskModelAllocation['entry_assessment']): boolean => entry?.recommendation_not_fill===true
  && (entry.version==='strategy-numerical-entries/2'
    ? entry.sizing_basis==='standing_counterfactual_reference_transition_not_viewer_order' && entry.reference_progression==='standing_no_fills_assumed'
    : entry.version==='strategy-numerical-entries/3' && entry.sizing_basis==='observed_hypothetical_reference_not_viewer_order'
      && entry.reference_progression==='later_observed_hypothetical_quote_proxy' && entry.execution_basis==='later_observed_IEX_bid_ask_proxy_not_actual_fill'
      && [entry.day_id,entry.book_sha256].every(value=>/^[a-f0-9]{64}$/.test(value ?? '')))

// Require a complete internally consistent publication before using its own stock universe or percentages.
const publicationValid = (allocation: DeskModelAllocation | undefined, now: number): boolean => {
  if (allocation?.version !== 'strategy-model-allocation/2' || allocation.status !== 'available'
      || allocation.policy !== 'grade-led-learned-sizing/1' || allocation.basis !== 'account_independent_unit_capital_targets'
      || allocation.account_basis !== 'no_account_inputs' || allocation.timing_basis !== 'nightly_position_size_not_immediate_trade_size'
      || allocation.identity?.schema !== 'strategy-recommendation-publication/1'
      || allocation.identity.strategy_identity !== allocation.strategy_identity || allocation.identity.session !== allocation.session
      || allocation.identity.policy !== allocation.policy || allocation.identity.basis !== allocation.basis
      || ![allocation.strategy_identity, allocation.snapshot_id, allocation.receipt_sha256].every(value => /^[a-f0-9]{64}$/.test(value ?? ''))
      || allocation.as_of !== allocation.published_at || !(Date.parse(allocation.observed_at ?? '') <= Date.parse(allocation.as_of)
        && Date.parse(allocation.as_of) <= now && now < Date.parse(allocation.valid_until ?? ''))) return false
  const names = Object.keys(allocation.rows ?? {})
  if (!names.length || names.length !== Object.keys(allocation.grade_signals ?? {}).length) return false
  let total = 0
  for (const name of names) {
    const row = allocation.rows[name], grade = allocation.grade_signals?.[name], evidence = row.evidence
    if (!grade || grade.session !== allocation.session || grade.basis !== 'observed_close_grade'
        || !['buy', 'hold', 'sell', 'avoid', 'unavailable'].includes(grade.action)
        || !(grade.grade===null && grade.action==='unavailable' || ['A+', 'A', 'B', 'C'].includes(grade.grade ?? '')) || evidence?.grade !== grade.grade
        || evidence?.inputs_as_of !== allocation.session || evidence?.model_position_size !== row.target_weight
        || typeof row.target_weight !== 'number' || !Number.isFinite(row.target_weight) || row.target_weight < 0 || row.target_weight > 1
        || (row.target_weight > 0 && (!['A+', 'A'].includes(grade.grade!) || !['buy', 'hold'].includes(grade.action)))) return false
    total += row.target_weight
  }
  return total <= 1 + 1e-12
}

type EntryEvidence = {
  entry: NonNullable<DeskModelAllocation['entry_assessment']>
  row: NonNullable<NonNullable<DeskModelAllocation['entry_assessment']>['rows'][string]>
  completed: number
  generated: number
  quoted: number
  until: number
}

// Bind a numerical entry row to its own publication without requiring its
// short quote window to still be open. The board uses that binding to keep the
// last answer visible after the window closes but before the next poll arrives.
const entryEvidence = (allocation: DeskModelAllocation, ticker: string, now: number): EntryEvidence | null => {
  if (!publicationValid(allocation,now)) return null
  const entry = allocation.entry_assessment, row = entry?.rows?.[ticker]
  const completed = Date.parse(entry?.completed_at ?? ''), generated = Date.parse(entry?.generated_at ?? '')
  const quoted = Date.parse(row?.quote_at ?? ''), until = Date.parse(row?.valid_until ?? '')
  const reference = ['strategy-numerical-entries/2','strategy-numerical-entries/3'].includes(entry?.version ?? '')
  const referenceSize = reference && row && typeof row.model_position_weight === 'number' && Number.isFinite(row.model_position_weight)
    && row.model_position_weight >= 0 && row.model_position_weight <= 1 && row.evidence?.model_position_size === row.model_position_weight
    && row.evidence?.trade_size === row.size_weight && row.evidence?.sizing_basis === entry.sizing_basis
    && ['Buy','Sell'].includes(row.action ?? '') && (row.action !== 'Sell' || typeof row.reference_units === 'number'
      && typeof row.proposed_units === 'number' && row.proposed_units > 0 && row.proposed_units <= row.reference_units)
  if (!['strategy-numerical-entries/1','strategy-numerical-entries/2','strategy-numerical-entries/3'].includes(entry?.version ?? '') || entry?.status !== 'available'
      || entry.snapshot_id !== allocation.snapshot_id || entry.publication_receipt_sha256 !== allocation.receipt_sha256
      || entry.strategy_identity !== allocation.strategy_identity || !/^[a-f0-9]{64}$/.test(entry.receipt_sha256 ?? '')
      || entry.feed !== 'iex' || entry.account_inputs !== false
      || (allocation.reference_positions !== undefined && (!persistedPositionView(allocation,now)
        || entry.version!=='strategy-numerical-entries/3' || entry.book_sha256!==allocation.reference_positions.book_sha256
        || entry.day_id!==allocation.reference_positions.day_id || row?.model_position_weight!==allocation.reference_positions.rows[ticker]?.target_weight))
      || (reference ? !referenceEntryFormat(entry) || !referenceSize
        || entry.version === 'strategy-numerical-entries/3' && !/^[a-f0-9]{64}$/.test(entry.book_sha256 ?? '')
        : entry.sizing_basis !== 'fresh_unit_capital_allocation_not_account_trade_quantity'
          || row?.size_weight !== allocation.rows[ticker]?.target_weight || row?.action !== 'Buy' || row.evidence?.model_position_size !== row.size_weight)
      || !row || !row.evidence || row.evidence.grade !== allocation.grade_signals?.[ticker]?.grade
      || row.evidence.inputs_as_of !== allocation.session
      || row.evidence.completed_candle_at !== entry.completed_at
      || !Number.isFinite(completed) || !Number.isFinite(generated) || !Number.isFinite(until)
      || !(completed <= generated && generated <= now)
      || Date.parse(entry.valid_until ?? '') !== completed + 900000
      || (Number.isFinite(quoted) && !(completed <= quoted && quoted <= generated && until <= quoted + 30000))) return null
  return {entry, row, completed, generated, quoted, until}
}

// Use only the exact current numerical candle and its own still-fresh quote for immediate entry permission.
const numericalEntry = (allocation: DeskModelAllocation, ticker: string, now: number) => {
  const bound = entryEvidence(allocation,ticker,now)
  if (!bound) return null
  const {entry,row,completed,quoted,until} = bound
  if (!['execute','wait'].includes(row.state) || !(row.size_weight > 0 && row.size_weight <= 1)
      || !Number.isFinite(quoted) || !(now < completed + 900000) || !(now < until)) return null
  return {row, at: entry.generated_at!, validUntil: row.valid_until}
}

// Admit a detached persisted daily objective through its own publication lifetime, independent of candle and quote expiry.
const persistedPositionView = (allocation: DeskModelAllocation, now: number): boolean => {
  const view=allocation.reference_positions
  if (!publicationValid(allocation,now) || view?.version!=='strategy-reference-positions/1' || view.status!=='available'
      || view.basis!=='original_persisted_daily_reference_targets_not_viewer_holdings'
      || view.snapshot_id!==allocation.snapshot_id || view.publication_receipt_sha256!==allocation.receipt_sha256
      || view.strategy_identity!==allocation.strategy_identity || view.session!==allocation.session
      || view.valid_until!==allocation.valid_until || !Number.isInteger(view.generation) || view.generation!<0
      || ![view.day_id,view.book_sha256,view.reader_sha256,view.receipt_sha256].every(value=>/^[a-f0-9]{64}$/.test(value ?? ''))
      || Object.keys(view.rows).length!==Object.keys(allocation.rows).length) return false
  let total=0
  for (const name of Object.keys(allocation.rows)) {
    const row=view.rows[name]
    if (!row || typeof row.target_weight!=='number' || !Number.isFinite(row.target_weight) || row.target_weight<0 || row.target_weight>1
        || row.evidence?.model_position_size!==row.target_weight || row.evidence?.inputs_as_of!==allocation.session
        || row.evidence?.grade!==allocation.grade_signals?.[name]?.grade || row.evidence?.sizing_basis!==view.basis) return false
    total+=row.target_weight
  }
  return total<=1+1e-10
}

// Keep a persisted daily position objective after short-lived trade permission expires; retain strict legacy entry binding.
const referencePosition = (allocation: DeskModelAllocation, ticker: string, now: number): number | null => {
  if (allocation.reference_positions!==undefined)
    return persistedPositionView(allocation,now) ? allocation.reference_positions.rows[ticker]?.target_weight ?? null : null
  const entry = allocation.entry_assessment, row = entry?.rows?.[ticker]
  const completed = Date.parse(entry?.completed_at ?? ''), generated = Date.parse(entry?.generated_at ?? '')
  return publicationValid(allocation,now) && referenceEntryFormat(entry) && entry?.status==='available'
    && entry.snapshot_id===allocation.snapshot_id && entry.publication_receipt_sha256===allocation.receipt_sha256
    && entry.strategy_identity===allocation.strategy_identity && /^[a-f0-9]{64}$/.test(entry.receipt_sha256 ?? '')
    && completed<=generated && generated<=now && now<completed+900000
    && typeof row?.model_position_weight==='number' && Number.isFinite(row.model_position_weight)
    && row.model_position_weight>=0 && row.model_position_weight<=1 && row.evidence?.model_position_size===row.model_position_weight
    && row.evidence?.grade===allocation.grade_signals?.[ticker]?.grade && row.evidence?.inputs_as_of===allocation.session
    && row.evidence?.completed_candle_at===entry.completed_at
    ? row.model_position_weight : null
}

// Match authenticated history by its validated economics contract while retaining legacy exact-record checks.
export const strategyHistoryMatches = (simulation: DeskStrategyStock | null | undefined, current: StrategyChartTarget | null | undefined): boolean => {
  if (!simulation || simulation.policy !== 'grade-led-learned-sizing/1' || simulation.provenance.basis !== 'account_independent_unit_capital_targets') return false
  // An audited history whose sources the current release has since replaced is still the audited
  // replay of the policy it names; the chart shows it under that policy until a new one is installed.
  if (simulation.provenance.strategy_binding === 'superseded' && simulation.provenance.verified_against_installed_strategy === false
    && simulation.provenance.strategy_contract?.schema === 'strategy-history-economics-binding/1') return true
  if (current && !current.strategyIdentity) return simulation.provenance.source_record_sha256 === current.record
  const expected = current?.strategyIdentity ?? (simulation.provenance.verified_against_installed_strategy === true ? simulation.provenance.strategy_identity : null)
  if (!expected || !/^[a-f0-9]{64}$/.test(expected)) return false
  const contract = simulation.provenance.strategy_contract
  return contract?.schema === 'strategy-history-economics-binding/1'
    && contract.strategy_identity === expected && simulation.provenance.strategy_identity === expected
    && contract.source_record_sha256 === simulation.provenance.source_record_sha256
    && contract.config_sha256 === simulation.provenance.config_sha256
    && [contract.history_sha256, contract.audit_sha256, contract.source_record_sha256, contract.config_sha256].every(value => /^[a-f0-9]{64}$/.test(value))
}

// Require a dated authenticated strategy target, with an explicit independent or legacy published basis.
export const modelWeight = (latest: DeskRecord, allocation: DeskModelAllocation | undefined, ticker: string, now: number): number | null => {
  const weight = allocation?.rows?.[ticker]?.target_weight
  if (allocation?.version === 'strategy-model-allocation/2') {
    const reference=referencePosition(allocation,ticker,now)
    return allocation.reference_positions!==undefined ? reference : reference ?? (publicationValid(allocation, now) && typeof weight === 'number' ? weight : null)
  }
  const basis = allocation?.version === 'published-model-allocation/1'
    ? allocation.basis === 'original_published_strategy_allocation_not_trade_quantity'
    : allocation?.version === 'strategy-model-allocation/1' && allocation.basis === 'account_independent_unit_capital_targets'
  const reading = allocation?.grade_signals?.[ticker]
  const readingMatches = allocation?.version !== 'strategy-model-allocation/1' || (reading
    && reading.grade === latest.grades?.[ticker]?.grade && reading.session === latest.session
    && reading.basis === 'observed_close_grade' && ['buy', 'hold', 'sell', 'avoid', 'unavailable'].includes(reading.action))
  if (!basis || !readingMatches || allocation?.status !== 'available'
      || allocation.policy !== 'grade-led-learned-sizing/1' || allocation.policy !== latest.targets?.policy
      || allocation.session !== latest.session || allocation.observed_at !== latest.written
      || !/^[a-f0-9]{64}$/.test(allocation.record_sha256 ?? '') || !/^[a-f0-9]{64}$/.test(allocation.receipt_sha256 ?? '')
      || !(Date.parse(allocation.observed_at ?? '') <= Date.parse(allocation.as_of) && Date.parse(allocation.as_of) <= now)
      || !(Date.parse(allocation.valid_until ?? '') > now)
      || typeof weight !== 'number' || !Number.isFinite(weight) || weight < 0 || weight > 1) return null
  return weight
}

// Bind model size and separately confirmed candle timing to the same live evidence used by the board.
export const strategyChartTarget = (latest: DeskRecord, allocation: DeskModelAllocation | undefined, ticker: string, now: number, live: DeskLive): StrategyChartTarget | null => {
  const weight = modelWeight(latest, allocation, ticker, now)
  if (!independentAllocation(allocation) || weight === null || !allocation) return null
  if (allocation.version === 'strategy-model-allocation/2') {
    const action = allocation.grade_signals?.[ticker]?.action
    const current = sessionOpen(live, allocation) ? numericalEntry(allocation,ticker,now) : null
    const displayed = signalsFor(latest,live,ticker,now,allocation)
    const reference = (allocation.reference_positions!==undefined || referenceEntryFormat(allocation.entry_assessment)) && referencePosition(allocation,ticker,now)!==null
    return {ticker, date: current ? allocation.entry_assessment!.session! : allocation.session!, at: current?.at ?? allocation.as_of, validUntil: allocation.valid_until,
      action: reference ? current?.row.action ?? null : weight > 0 && ['buy', 'hold'].includes(action ?? '') ? 'Buy' : action === 'sell' ? 'Sell' : null,
      weight:reference ? current?.row.size_weight ?? 0 : weight, positionWeight:weight, tradeWeight:current?.row.size_weight ?? null, referenceTransition:reference,
      record: allocation.snapshot_id!, strategyIdentity: allocation.strategy_identity,
      recordedHistoryAvailable:allocation.recorded_history_version==='strategy-recorded-entries/1',
      nextSessionPlan:displayed.buy.word==='Buy setup' || displayed.sell.word==='Exit',entryReason:actionFor(displayed).reason,
      displayAction:actionLabel(actionFor(displayed).word),
      evidence: current?.row.evidence ?? allocation.reference_positions?.rows[ticker]?.evidence ?? allocation.rows[ticker].evidence,
      entry: !reference && current?.row.state === 'execute' ? {at:current.at,validUntil:current.validUntil} : undefined}
  }
  const action = allocation.grade_signals?.[ticker]?.action
  if (weight > 0 && (action === 'buy' || action === 'hold')) {
    const signal = signalsFor(latest, live, ticker, now, allocation)
    const at = Math.max(Date.parse(allocation.as_of), Date.parse(signal.setup?.generated_at ?? ''))
    const until = Math.min(Date.parse(allocation.valid_until ?? ''), Date.parse(signal.setup?.valid_until ?? ''))
    const entry = signal.buy.ready && !signal.sell.ready && at <= now && now < until
      ? {at: new Date(at).toISOString(), validUntil: new Date(until).toISOString()} : undefined
    return {ticker, date: allocation.session!, at: allocation.as_of, validUntil: allocation.valid_until, action: 'Buy', weight, record: allocation.record_sha256!, entry, entryReason: signal.sell.ready ? signal.sell.reason : signal.buy.reason}
  }
  if (weight === 0 && action === 'sell')
    return {ticker, date: allocation.session!, at: allocation.as_of, validUntil: allocation.valid_until, action: 'Sell', weight, record: allocation.record_sha256!}
  if (weight === 0)
    return {ticker, date: allocation.session!, at: allocation.as_of, validUntil: allocation.valid_until, action: null, weight, record: allocation.record_sha256!}
  return null
}

// Keep model allocation percentages distinct from trade sizes and the current chart's direction.
export const ModelSize = ({latest, allocation, ticker, now}: {latest: DeskRecord; allocation?: DeskModelAllocation; ticker: string; now: number}) => {
  // An expired verified publication carries the last plan separately; it is
  // still the model's last known position, not a fresh allocation.
  const lastPlanWeight = allocation?.status === 'awaiting_nightly' ? allocation.last_rows?.[ticker]?.target_weight : undefined
  const weight = typeof lastPlanWeight === 'number' && Number.isFinite(lastPlanWeight) ? lastPlanWeight : modelWeight(latest, allocation, ticker, now)
  const independent = independentAllocation(allocation)
  const session = allocation?.status === 'awaiting_nightly' ? allocation.last_session ?? allocation.session : allocation?.session
  return <div aria-label={`${ticker} model size`}>
    <span className="font-medium" title={independent ? `Strategy position size · ${session}` : undefined}>{weight === null ? 'Unavailable' : `${(weight * 100).toFixed(1)}%${independent ? '' : ' target'}`}</span>
    {!independent && <p className="text-[10px] text-[#6e6e73]">{weight === null ? allocation?.reason ?? 'Verified current model allocation required' : `Strategy allocation · ${allocation!.session}`}</p>}
  </div>
}

// Preserve model priorities while keeping immediate, waiting and unavailable evidence distinct.
const signal = (word: string, ready: boolean, priority: string, reason: string, tier: number): Signal =>
  ({word, ready, priority, reason, rank: tier * 10 - (PRIORITY[priority] ?? 0)})

// Write an exchange instant in New York time, with the weekday only when the
// line needs to name a different day.
const phaseClock = (value: string | null | undefined, withDay: boolean): string | null => {
  const parsed = Date.parse(value ?? '')
  if (!Number.isFinite(parsed)) return null
  const at = new Date(parsed)
  const clock = new Intl.DateTimeFormat('en-US', {
    timeZone: 'America/New_York', hour: '2-digit', minute: '2-digit', hourCycle: 'h23',
  }).format(at)
  const day = withDay
    ? new Intl.DateTimeFormat('en-US', {timeZone: 'America/New_York', weekday: 'short'}).format(at)
    : null
  return `${day ? `${day} ` : ''}${clock} ET`
}

// State which market phase it is and when the desk acts next, using only the
// clocks the backend supplied. An absent phase keeps the old board behaviour.
export const marketPhaseLine = (allocation?: DeskModelAllocation): string | null => {
  const phase = allocation?.market_phase
  if (!phase) return null
  if (phase.calendar_known !== true || phase.phase === 'unknown') return 'Exchange calendar not reviewed for this date'
  const actionClock = phaseClock(phase.next_action_at, false)
  const actionDay = phaseClock(phase.next_action_at, true)
  const publicationClock = phaseClock(phase.next_publication_at, false)
  const publicationDay = phaseClock(phase.next_publication_at, true)
  switch (phase.phase) {
    case 'regular': {
      const close = phaseClock(phase.closes_at, false)
      return `Regular session${close ? ` · until ${close}` : ''}`
    }
    case 'pre_market':
      return `Pre-market${actionClock ? ` · opens ${actionClock}` : ''}`
    case 'after_hours':
      return `After-hours${actionDay ? ` · next session ${actionDay}` : ''}${publicationClock ? ` · tonight's plan ${publicationClock}` : ''}`
    case 'overnight':
      return `Overnight${actionDay ? ` · next session ${actionDay}` : ''}${publicationDay ? ` · next plan ${publicationDay}` : ''}`
    case 'closed':
      return `Closed${actionDay ? ` · next session ${actionDay}` : ''}${publicationDay ? ` · next plan ${publicationDay}` : ''}`
    default:
      return 'Exchange calendar not reviewed for this date'
  }
}

// Treat a phase the backend did not send as the old behaviour, so an older
// allocation still uses the live market status rather than inventing a state.
const outsideRegularSession = (allocation?: DeskModelAllocation): boolean => {
  const phase = allocation?.market_phase
  if (!phase) return false
  return phase.calendar_known !== true || phase.phase !== 'regular'
}

// Prefer the reviewed phase over the live snapshot's phase when both exist,
// because only the phase object knows the desk's regular-session rule.
const sessionOpen = (live: DeskLive, allocation?: DeskModelAllocation): boolean => {
  const phase = allocation?.market_phase
  if (phase) return phase.calendar_known === true && phase.phase === 'regular'
  return live.market_status?.phase === 'open'
}

// Preserve an authenticated nightly direction outside regular hours without inventing current chart confirmation.
const publishedPlanFor = (latest: DeskRecord, live: DeskLive, allocation: DeskModelAllocation | undefined, ticker: string, now: number): Signals | null => {
  const v2 = allocation?.version === 'strategy-model-allocation/2'
  const outside = allocation?.market_phase
    ? !sessionOpen(live, allocation)
    : ['post-market', 'pre-market', 'closed'].includes(live.market_status?.phase ?? '')
  if (!v2 && !outside) return null
  const weight = modelWeight(latest, allocation, ticker, now)
  const grade = v2 ? allocation.grade_signals?.[ticker]?.grade : latest.grades?.[ticker]?.grade
  const session = v2 ? allocation.session : latest.session
  if (weight === null || !grade || !['A+', 'A', 'B', 'C'].includes(grade)) return null
  const independent = independentAllocation(allocation)
  const originalSignal = independent ? allocation?.grade_signals?.[ticker] : null
  const actions = independent ? originalSignal ? [{
    grade: originalSignal.grade, signal_session: originalSignal.session,
    signal_basis: originalSignal.basis, grade_signal: originalSignal.action,
  }] : [] : latest.actions?.filter(row => row.ticker === ticker) ?? []
  const action = actions[0]
  if (actions.length !== 1 || action.grade !== grade || action.signal_session !== session
      || action.signal_basis !== 'observed_close_grade'
      || !['buy', 'hold', 'sell', 'avoid'].includes(action.grade_signal ?? '')) return null
  const eligible = action.grade_signal === 'buy' || action.grade_signal === 'hold'
  const exiting = action.grade_signal === 'sell'
  const hasExit = !eligible && (!independent || exiting)
  if (!eligible && weight > 0) return null
  const waiting = v2 && sessionOpen(live, allocation)
  const timing = v2 ? 'Await the numerical 15-minute entry assessment and a fresh regular-session quote; this is not an immediate action.' : 'Await a fresh regular-session candle and quote; this is not an immediate action.'
  const reason = `${independent ? 'Strategy model' : 'Published'} ${session} grade signal ${action.grade_signal}, grade ${grade}, ${(weight * 100).toFixed(1)}% ${independent ? 'position size' : 'target'}. ${timing}`
  return {
    ticker, grade: independent ? grade : `${grade} · plan`, setup: null, evidence:v2 ? allocation.rows[ticker].evidence : undefined,
    buy: signal(eligible && weight > 0 ? waiting ? 'Wait' : independent ? 'Buy setup' : 'Buy plan' : eligible ? independent ? 'Wait' : 'No buy allocation' : independent ? 'Avoid' : 'Avoid new entry', false, '', reason, eligible && weight > 0 ? 1 : 2),
    sell: signal(hasExit ? waiting ? 'Wait' : independent ? 'Exit' : 'Exit if held' : independent ? '—' : 'No grade exit', false, '', hasExit
      ? `The published grade-led policy exits below A if held; this viewer's holdings are unknown. ${timing}`
      : `${eligible ? 'Grade retains entry permission' : 'No new entry or model sell action'}. ${timing}`, hasExit ? 1 : 2),
    plan: {session: session!, published: allocation!.observed_at!, validUntil: allocation!.valid_until!, calculated: independent ? allocation!.as_of : undefined},
    nextSession: true,
  }
}

// Build independent entry and downside-review signals without reading any account or funded order.
const signalsForBase = (latest: DeskRecord, live: DeskLive, ticker: string, now: number, allocation?: DeskModelAllocation): Signals => {
  if (allocation?.version === 'strategy-model-allocation/2') {
    const unavailable = signal('Unavailable', false, '', 'Verified current strategy publication required.', 3)
    const open = sessionOpen(live, allocation)
    const plan = publishedPlanFor(latest, live, allocation, ticker, now)
    const entry = publicationValid(allocation,now) && open ? numericalEntry(allocation,ticker,now) : null
    if (allocation.reference_positions!==undefined || open && ['strategy-numerical-entries/2','strategy-numerical-entries/3'].includes(allocation.entry_assessment?.version ?? '')) {
      const position = referencePosition(allocation,ticker,now)
      const assessment=allocation.entry_assessment
      const currentReference=referenceEntryFormat(assessment) && assessment?.status==='available'
        && assessment.snapshot_id===allocation.snapshot_id && assessment.publication_receipt_sha256===allocation.receipt_sha256
        && assessment.strategy_identity===allocation.strategy_identity
        && Date.parse(assessment.generated_at ?? '')<=now && now<Date.parse(assessment.valid_until ?? '')
        && (allocation.reference_positions===undefined
          ? assessment.version!=='strategy-numerical-entries/3' || /^[a-f0-9]{64}$/.test(assessment.book_sha256 ?? '')
          : assessment.book_sha256===allocation.reference_positions.book_sha256 && assessment.day_id===allocation.reference_positions.day_id)
      const row=currentReference ? assessment?.rows[ticker] : undefined
      const evidence=row?.evidence ?? allocation.reference_positions?.rows[ticker]?.evidence
      if (position===null || !row && allocation.reference_positions===undefined) return {ticker,grade:'—',setup:null,buy:unavailable,sell:unavailable}
      const grade = allocation.grade_signals?.[ticker]?.grade ?? '—'
      if (grade==='—' && position===0) return {ticker,grade,setup:null,buy:unavailable,sell:unavailable,evidence}
      const inactive = signal('—',false,'','',2)
      // Before the open (and after the close) there is no 15-minute entry to wait for, but the
      // reference book already names the model position for the next regular session. That is the
      // plan a person wants to see pre-market: what the desk buys or exits at 09:30 and how much,
      // with "Do nothing" reserved for names the model truly allocates nothing to.
      if (!open) {
        const direction = allocation.grade_signals?.[ticker]?.action
        if (direction === 'sell')
          return {ticker,grade,setup:null,evidence,nextSession:true,buy:inactive,
            sell:signal('Exit if held',false,'','',1)}
        // A target the size column prints as 0.0% buys no shares, so it is no plan.
        if (position >= 0.0005)
          return {ticker,grade,setup:null,evidence,nextSession:true,size_weight:position,sell:inactive,
            buy:signal('Buy plan',false,'','',1)}
        return {ticker,grade,setup:null,evidence,nextSession:false,sell:inactive,buy:signal('Do nothing',false,'','',2)}
      }
      const side = open ? row?.action : null
      const ready = entry?.row.state==='execute'
      const reason = side ? `${side} ${(row!.size_weight*100).toFixed(3)}% of model reference capital toward a ${(position*100).toFixed(1)}% position. ${entry?.row.evidence?.timing_reason ?? 'Await a fresh compatible regular-session quote.'} This is a standing model reference, not your holdings or a recorded fill.`
        : !row ? 'The daily model position is retained. Await a current 15-minute assessment and fresh compatible regular-session quote for a trade amount.'
          : row.attempt_resolved ? 'The original daily hypothetical attempt is resolved. No repeated trade is recommended; view its saved recommendation for the original evidence.'
          : row.objective_pending ? 'The original daily cash budget cannot fund another model purchase.'
            : position>0 ? grade==='—' ? 'Grade unavailable; preserve the existing model reference without initiating a new trade.' : 'The reference position already meets the model objective; no additional trade is recommended.' : 'The model has no position to sell and no new allocation.'
      const selected = signal(side ? ready ? side==='Buy' ? 'Buy now' : 'Sell review now' : side==='Buy' ? 'Buy pending' : 'Sell pending' : !row || row.attempt_resolved || row.objective_pending ? 'Wait' : position>0 ? 'Hold' : 'Avoid',ready,'',reason,ready?0:1)
      return {ticker,grade,setup:null,buy:side==='Sell'?inactive:selected,sell:side==='Sell'?selected:inactive,evidence,nextSession:false,
        current:entry ? {completed:allocation.entry_assessment!.completed_at!,quote:entry.row.quote_at!,until:entry.validUntil} : undefined}
    }
    const quote = displayedBoardPrice(live,ticker,now)
    if (plan && allocation.grade_signals?.[ticker]?.action === 'sell' && open
        && quote?.current && quote.kind === 'midpoint' && quote.word === 'regular')
      return {...plan,nextSession:false,sell:signal('Sell review now',true,'','The model grade dropped below A: exit an existing position. This is not a short sale; no holding amount is assumed.',0)}
    if (plan && entry) {
      const ready = entry.row.state === 'execute'
      return {...plan,nextSession:false,buy:signal(ready ? 'Buy now' : 'Wait',ready,'',ready
        ? 'The numerical model favors acting now over waiting one 15-minute candle. Size % is the model position, not an additional purchase amount.'
        : 'The numerical model favors waiting one 15-minute candle at the current price.',ready ? 0 : 1)}
    }
    return plan ?? {ticker, grade: '—', setup: null, buy: unavailable, sell: unavailable}
  }
  const setup = currentSetup(live, latest.session, ticker, now)
  const original = live.opportunities?.rows?.[ticker]
  const grade = currentAssessments(live, latest.session, now)[ticker]?.grade_live ?? '—'
  const open = sessionOpen(live, allocation)
  const missing = live.opportunities?.unavailable?.[ticker] ?? (!open && live.market_status?.phase
    ? 'Regular-session assessment expired or unavailable. Extended-hours prices do not supply a new strategy assessment.'
    : 'Fresh chart assessment unavailable; no immediate signal is inferred.')
  const unavailable = signal('Unavailable', false, '', missing, 3)
  if (!setup || setup.entry === 'unavailable' || !Number.isFinite(Date.parse(setup.bar))
      || Date.parse(setup.bar) + 900_000 > Date.parse(setup.generated_at)
      || !['high', 'medium', 'low'].includes(setup.entry_priority)
      || !['high', 'medium', 'low'].includes(setup.exit_priority))
    return publishedPlanFor(latest, live, allocation, ticker, now) ?? {ticker, grade, setup: null, buy: unavailable, sell: unavailable}
  const quote = displayedBoardPrice(live, ticker, now)
  const quoted = quote?.current && quote.kind === 'midpoint' && quote.word === 'regular'
  const gate = !open ? 'Wait for the regular session; this is not an immediate action.'
    : !quoted ? 'Wait for a fresh regular-session bid/ask quote.' : null
  const buy = gate && (setup.entry === 'ready' || original?.entry === 'ready')
    ? signal('Wait', false, setup.entry_priority, gate, 1)
    : setup.entry === 'ready' ? signal('Buy now', true, setup.entry_priority, setup.reason, 0)
    : signal(setup.entry === 'wait' ? 'Wait' : 'Avoid entry', false, setup.entry_priority, setup.reason, setup.entry === 'wait' ? 1 : 2)
  const sell = setup.exit === 'review'
    ? signal(gate ? 'Wait' : 'Sell review now', !gate, setup.exit_priority, gate ?? original!.reason, gate ? 1 : 0)
    : signal('No sell signal', false, '', original!.reason, 2)
  return {ticker, grade, setup, buy, sell}
}

// Attach the backend verdict only while the row that produced it is still current.
const verdictFields = (allocation: DeskModelAllocation | undefined, ticker: string, now: number): Pick<Signals, 'verdict' | 'reason_code' | 'size_weight' | 'verdict_reason'> => {
  const entry = allocation?.entry_assessment, row = entry?.rows?.[ticker]
  if (row?.verdict && entry?.status === 'available'
      && Date.parse(entry.generated_at ?? '') <= now && Date.parse(entry.valid_until ?? '') > now)
    return {verdict: row.verdict, reason_code: row.reason_code, size_weight: row.size_weight, verdict_reason: row.verdict_reason ?? row.reason}
  const reference = allocation?.reference_positions, position = reference?.rows?.[ticker]
  if (position?.verdict && reference?.status === 'available' && Date.parse(reference.valid_until ?? '') > now)
    return {verdict: position.verdict, reason_code: position.reason_code, size_weight: position.size_weight, verdict_reason: position.verdict_reason ?? position.reason}
  return {}
}

// Keep the board's signal wording and the backend's one-word verdict in one object.
// Outside the regular session a non-plan row has no action to wait for: the desk
// acts only in regular hours, so "Wait" would imply a session decision that is
// not coming. The next-session plan keeps its own wording and badge.
export const signalsFor = (latest: DeskRecord, live: DeskLive, ticker: string, now: number, allocation?: DeskModelAllocation): Signals => {
  const base = signalsForBase(latest, live, ticker, now, allocation)
  // A next-session plan carries its own size and direction; the backend's live verdict fields
  // describe the current session and would overwrite them with "nothing".
  const signals = base.nextSession ? base : {...base, ...verdictFields(allocation, ticker, now)}
  if (outsideRegularSession(allocation) && signals.nextSession !== true && signals.lastPlan !== true && signals.buy.word !== 'Do nothing')
    return {ticker: signals.ticker, grade: signals.grade, setup: null, evidence: signals.evidence, nextSession: false,
      buy: signal('Do nothing', false, '', '', 2),
      sell: signal('—', false, '', '', 2)}
  return signals
}

// Display exact model evidence times in the market's timezone.
// A clock the reader can take in at a glance: the time alone when it is today in New York, the day before it otherwise.
const evidenceTime = (at: string) => {
  const instant = new Date(at)
  if (!Number.isFinite(instant.getTime())) return 'unknown time'
  const day = (value: Date) => value.toLocaleDateString('en-CA', {timeZone: 'America/New_York'})
  const clock = instant.toLocaleTimeString('en-US', {timeZone: 'America/New_York', hour12: false, hour: '2-digit', minute: '2-digit'})
  return (day(instant) === day(new Date()) ? '' : instant.toLocaleDateString('en-US', {timeZone: 'America/New_York', month: 'short', day: 'numeric'}) + ' ') + clock + ' ET'
}

// Show the strongest supported action, preferring a downside review when both directions are immediately ready.
const actionFor = (row: Signals): Signal => row.sell.ready || row.sell.rank < row.buy.rank ? row.sell : row.buy

// Use direct trading labels while keeping confirmation and timing requirements in the supporting details.
const actionLabel = (word: string): string => ['Buy now', 'Buy plan', 'Buy setup', 'Buy pending'].includes(word) ? 'Buy'
  : ['Sell review now', 'Exit if held', 'Exit', 'Sell pending'].includes(word) ? 'Sell' : word

// Collapse every waiting, avoided and unavailable path into the one word the
// board promises, while leaving the original detail as the supporting reason.
const verdictFor = (word: string): DeskEntryVerdict => {
  const label = actionLabel(word)
  return label === 'Buy' ? 'buy' : label === 'Sell' ? 'sell' : 'nothing'
}

// Render the size column's one-decimal convention, including a positive trade
// too small to round to 0.1%.
const sizeText = (size: number | null): string => size === null ? '—' : size < .001 ? '<0.1%' : `${(size * 100).toFixed(1)}%`

// Accept only the closed verdict vocabulary a current backend publication can
// supply; an older or malformed row falls back to the board's own derivation.
const backendVerdict = (row: EntryEvidence['row']): DeskEntryVerdict | null =>
  row.verdict === 'buy' || row.verdict === 'sell' || row.verdict === 'nothing' ? row.verdict : null

// Turn a bound entry row into the one verdict the board shows, keeping the
// backend's own reason and trade size rather than reinterpreting its state.
const boundView = (bound: EntryEvidence): VerdictView => {
  const raw = backendVerdict(bound.row) ?? 'nothing'
  // While the engine's price is pending its own size is a placeholder; the plan's trade is the size.
  const sized = bound.row.reason_code === 'entry_pending' ? bound.row.plan_weight : bound.row.size_weight
  const size = raw === 'nothing' ? null
    : typeof sized === 'number' && Number.isFinite(sized) && sized > 0 ? sized : null
  // A Buy with no positive trade amount is not a buy the person can act on.
  const verdict = raw === 'buy' && size === null ? 'nothing' : raw
  const reason = typeof bound.row.reason === 'string' && bound.row.reason.trim() ? bound.row.reason
    : bound.row.reason_code ? REASON_WORDS[bound.row.reason_code] : ''
  const sourceAt = Number.isFinite(bound.quoted) ? bound.quoted : bound.generated
  return {verdict, reason, size, nextSession:false, lastPlan:false,
    observedAt: bound.row.quote_at ?? bound.entry.generated_at ?? null, validUntil: bound.until, sourceAt,
    state: bound.row.reason_code === 'entry_pending' && verdict !== 'nothing' ? 'pending' : undefined}
}

// Derive the same verdict from the board's existing signal words when an older
// publication has no verdict fields.
const signalsView = (signals: Signals, selected: Signal, allocation: DeskModelAllocation | undefined, ticker: string, now: number): VerdictView => {
  const verdict = verdictFor(selected.word)
  const entry = allocation ? numericalEntry(allocation, ticker, now) : null
  const size = verdict === 'nothing' ? null
    : entry && Number.isFinite(entry.row.size_weight) && entry.row.size_weight > 0 ? entry.row.size_weight
    : typeof signals.size_weight === 'number' && Number.isFinite(signals.size_weight) && signals.size_weight > 0 ? signals.size_weight : null
  const observedAt = signals.current?.quote ?? entry?.row.quote_at ?? null
  const until = Date.parse(signals.current?.until ?? entry?.validUntil ?? '')
  const sourceAt = Date.parse(observedAt ?? '') || Date.parse(signals.plan?.published ?? '') || now
  return {verdict, reason: selected.reason, size, nextSession: signals.nextSession === true && verdict !== 'nothing',
    lastPlan: signals.lastPlan === true, observedAt, validUntil: Number.isFinite(until) ? until : 0, sourceAt,
    state: selected.word === 'Unavailable' ? 'unavailable' : selected.word.endsWith(' pending') && verdict !== 'nothing' ? 'pending' : undefined}
}

// Carry the expired plan's own rows without presenting them as fresh advice.
const lastPlanSignals = (allocation: DeskModelAllocation, ticker: string): Signals => {
  const row = allocation.last_rows?.[ticker]
  const reason = outsideRegularSession(allocation) || allocation.superseded_at ? ''
    : allocation.expired_at && allocation.next_publication_at
      ? `Last plan expired at ${evidenceTime(allocation.expired_at)}; tonight's plan publishes at ${evidenceTime(allocation.next_publication_at)}.`
      : 'Last plan expired; awaiting the next publication.'
  return {ticker, grade: row?.evidence?.grade ?? '—', setup: null, evidence: row?.evidence, lastPlan: true,
    buy: signal('Do nothing', false, '', reason, 2), sell: signal('—', false, '', '', 2)}
}

// Date the freshest quote observation the board is actually showing.
const latestQuoteTime = (live: DeskLive): string | null => {
  const values = [
    live.extended_hours?.as_of,
    ...Object.values(live.extended_hours?.quotes ?? {}).map(quote => quote.at),
    ...Object.values(live.quotes ?? {}).map(quote => quote.as_of),
  ].map(value => Date.parse(value ?? '')).filter(Number.isFinite)
  return values.length ? new Date(Math.max(...values)).toISOString() : live.as_of
}

// Date the completed candle from the numerical assessment, or the last regular
// bar when the current assessment is unavailable.
const completedCandleTime = (live: DeskLive, allocation?: DeskModelAllocation): string | null => {
  const assessment = allocation?.entry_assessment?.completed_at
  if (assessment && Number.isFinite(Date.parse(assessment))) return assessment
  if (live.data_at && Number.isFinite(Date.parse(live.data_at))) return live.data_at
  const bars = Object.values(live.quotes ?? {}).map(quote => Date.parse(quote.bar ?? '')).filter(Number.isFinite)
  return bars.length ? new Date(Math.max(...bars)).toISOString() : null
}

// The trade size in the owner's own money: the model's percentage applied to
// the planning equity entered on this page, at the price the board shows.
// Shares are rounded down to whole ones, as the planner buys them; the
// percentage stays the authority and this line never replaces it.
const sizedAmount = (ticker: string, size: number | null, equity: number | undefined, price: number | undefined) => {
  if (size === null || !equity || !(equity > 0) || !price || !(price > 0)) return null
  const dollars = size * equity
  const shares = Math.floor(dollars / price)
  return <p aria-label={`${ticker} sized amount`} className="text-[10px] text-[#6e6e73]">≈ ${dollars.toLocaleString('en-US', {maximumFractionDigits: 0})} · {shares} sh at ${price.toFixed(2)}</p>
}

// Show only the clock time in a retained row; the strip above the table carries the date.
const clockTime = (value: string | null): string => {
  const parsed = Date.parse(value ?? '')
  return Number.isFinite(parsed)
    ? new Date(parsed).toLocaleTimeString('en-US', {timeZone: 'America/New_York', hour: '2-digit', minute: '2-digit', second: '2-digit'})
    : 'unknown time'
}

// Resolve the row's displayed call once for the board and the chart's current marker.
export const boardAction = (row: Signals): {word: string; action: 'Buy' | 'Sell' | null; reason: string; sizeWeight: number | null} => {
  const selected = actionFor(row)
  const word = actionLabel(selected.word)
  const action = word === 'Buy' ? 'Buy' : word === 'Sell' ? 'Sell' : null
  const sizeWeight = action && typeof row.size_weight === 'number' && Number.isFinite(row.size_weight) ? row.size_weight : null
  return {word, action, reason: selected.reason, sizeWeight}
}

// Show the same directional reasons and evidence in row expansion and the full stock chart.
export const SignalDetail = ({signals}: {signals: Signals}) => <section aria-label={`${signals.ticker} signal details`} className="space-y-1 text-xs">
  {signals.buy.word!=='—' && <p><b>{actionLabel(signals.buy.word)}</b>{signals.buy.reason && ` · ${signals.buy.reason}`}</p>}
  {signals.sell.word !== '—' && <p><b>{actionLabel(signals.sell.word)}</b>{signals.sell.reason && ` · ${signals.sell.reason}`}</p>}
  {signals.verdict_reason && <p>{signals.verdict_reason}</p>}
  {signals.setup && <>
    <p>{confirmationText(signals.setup)} {invalidationText(signals.setup)}</p>
    <p>Completed candle {evidenceTime(signals.setup.bar)} · assessed {evidenceTime(signals.setup.generated_at)} · Valid until {evidenceTime(signals.setup.valid_until)}.</p>
  </>}
  {signals.current && <p>15m {evidenceTime(signals.current.completed)} · Quote {evidenceTime(signals.current.quote)} · Valid until {evidenceTime(signals.current.until)}.</p>}
  {signals.plan && <p>{signals.plan.calculated ? 'Strategy model' : 'Published plan'} {signals.plan.session} · inputs published {evidenceTime(signals.plan.published)}{signals.plan.calculated ? ` · calculated ${evidenceTime(signals.plan.calculated)}` : ''} · Valid until {evidenceTime(signals.plan.validUntil)}. Grade and {signals.plan.calculated ? 'size' : 'target'} are not a current candle assessment.</p>}
  {signals.evidence && <div><p>Prior-close technicals · {signals.evidence.inputs_as_of}</p><StrategyTechnicalEvidence evidence={signals.evidence} /></div>}
  {!signals.evidence && <p className="text-[#6e6e73]">Sell review means reassess or reduce an existing holding. Not a short-sale signal. Strength is the model’s qualitative priority, not a return probability or funded size.</p>}
</section>

// Keep saved stocks navigable without unavailable advice, and rank covered names independently of accounts, each directional tab restricted to its matching verdict.
export const SignalBoard = ({latest, live, allocation, now, onOpen, closes, refreshMs = 20_000, refreshedAt, planningEquity}: {latest: DeskRecord; live: DeskLive; allocation?: DeskModelAllocation; now: number; onOpen: (ticker: string) => void; closes?: Record<string, number | null>; refreshMs?: number; refreshedAt?: number; planningEquity?: number}) => {
  const [side, setSide] = useState<Side>('all')
  const [query, setQuery] = useState('')
  const [opened, setOpened] = useState<string | null>(null)
  const [visible, setVisible] = useState(25)
  const [clock, setClock] = useState(Date.now)
  // The countdown is display-only; it never extends an evidence deadline.
  useEffect(() => {
    const timer = window.setInterval(() => setClock(Date.now()), 1000)
    return () => window.clearInterval(timer)
  }, [])
  const tick = Math.max(now, clock)
  const awaitingNightly = allocation?.status === 'awaiting_nightly'
  const lastRows = awaitingNightly ? allocation?.last_rows : undefined
  // An unavailable publication with no grade signals still lists the saved names, so their charts stay reachable.
  const savedNamesOnly = allocation?.version === 'strategy-model-allocation/2' && allocation.status === 'unavailable'
    && !Object.keys(allocation.grade_signals ?? {}).length
  const rows = useMemo(() => awaitingNightly
    ? lastRows ? Object.keys(lastRows).map(ticker => lastPlanSignals(allocation!, ticker)) : []
    : Object.keys(allocation?.version === 'strategy-model-allocation/2' && !savedNamesOnly ? allocation.grade_signals ?? {} : latest.grades ?? {})
      .map(ticker => signalsFor(latest, live, ticker, now, allocation)),
    [latest, live, now, allocation, awaitingNightly, lastRows, savedNamesOnly])
  const independent = independentAllocation(allocation)
  const unavailableRows = rows.length > 0 && rows.every(row => row.buy.word === 'Unavailable' && row.sell.word === 'Unavailable')
  // An awaiting-nightly publication is a verified expiry, not an integrity
  // failure, so it must not borrow the red "unavailable" message.
  const recommendationsUnavailable = !awaitingNightly && (!rows.length || unavailableRows)
  const showPriority = !independent || rows.some(row => row.setup)
  // Date a completed authenticated assessment even when it produces no immediately executable trade.
  const assessment=allocation?.entry_assessment
  const completed=Date.parse(assessment?.completed_at ?? ''),generated=Date.parse(assessment?.generated_at ?? '')
  const currentSession = allocation?.version === 'strategy-model-allocation/2' && publicationValid(allocation, now)
    && assessment?.status==='available' && assessment.snapshot_id===allocation.snapshot_id
    && assessment.publication_receipt_sha256===allocation.receipt_sha256 && assessment.strategy_identity===allocation.strategy_identity
    && /^[a-f0-9]{64}$/.test(assessment.receipt_sha256 ?? '') && assessment.feed==='iex' && assessment.account_inputs===false
    && (assessment.version==='strategy-numerical-entries/1'
      ? assessment.sizing_basis==='fresh_unit_capital_allocation_not_account_trade_quantity' : referenceEntryFormat(assessment))
    && completed<=generated && generated<=now && now<completed+900000
    && Date.parse(assessment.valid_until ?? '')===completed+900000
    ? new Date(assessment.completed_at!).toLocaleDateString('en-CA', {timeZone: 'America/New_York'}) : null
  // Use directional evidence first, then actual target size for model buy setups, without calling size confidence.
  const selected = (row: Signals) => side === 'buy' ? row.buy : side === 'sell' ? row.sell : row.buy.rank <= row.sell.rank ? row.buy : row.sell
  // The retained view is the last answer observed while its own quote window
  // was open. It survives the window's deadline but never beyond one poll.
  const held = useRef<Record<string, VerdictView>>({})
  const displayed = useMemo(() => rows.map(row => {
    const derived = signalsView(row, selected(row), allocation, row.ticker, now)
    if (row.lastPlan) return {row, view: derived, refreshing: false}
    const open = sessionOpen(live, allocation)
    const bound = allocation ? entryEvidence(allocation, row.ticker, now) : null
    const backend = bound ? backendVerdict(bound.row) : null
    const backendView = open && bound && backend ? boundView(bound) : null
    const fresh = open && allocation ? numericalEntry(allocation, row.ticker, now) : null
    const freshView = fresh ? backendView ?? derived : null
    if (backendView) {
      const previous = held.current[row.ticker]
      const newer = !previous || backendView.sourceAt > previous.sourceAt
        || backendView.sourceAt === previous.sourceAt && (backendView.verdict !== previous.verdict || backendView.size !== previous.size)
      // An already-expired row on first sight was never observed fresh, so it
      // cannot become a retained action; a previously retained row may be
      // replaced by a newer backend answer, including one that says nothing.
      if (tick < backendView.validUntil + refreshMs && (fresh || previous) && newer) held.current[row.ticker] = backendView
    }
    if (freshView) {
      held.current[row.ticker] = freshView
      return {row, view: freshView, refreshing: false}
    }
    const previous = held.current[row.ticker]
    if (open && previous && tick < previous.validUntil + refreshMs)
      return {row, view: previous, refreshing: tick >= previous.validUntil}
    if (previous) delete held.current[row.ticker]
    return {row, view: derived, refreshing: false}
  }), [rows, side, allocation, live, now, tick, refreshMs])
  const views = new Map(displayed.map(item => [item.row.ticker, item]))
  const ranked = rows.filter(row => row.ticker.toLowerCase().includes(query.trim().toLowerCase())
      && (side === 'all' || views.get(row.ticker)!.view.verdict === side))
    .sort((a, b) => selected(a).rank - selected(b).rank
      || (independent && side !== 'sell' && a.plan && b.plan
        ? (modelWeight(latest, allocation, b.ticker, now) ?? 0) - (modelWeight(latest, allocation, a.ticker, now) ?? 0) : 0)
      || a.ticker.localeCompare(b.ticker))
  const quoteAt = latestQuoteTime(live)
  const candleAt = completedCandleTime(live, allocation)
  const publicationSession = awaitingNightly ? allocation?.last_session ?? allocation?.session ?? latest.session : allocation?.session ?? latest.session
  const refreshIn = refreshedAt === undefined ? null : Math.max(0, Math.ceil((refreshMs - Math.max(0, tick - refreshedAt)) / 1000))
  const phaseLine = marketPhaseLine(allocation)
  return <section aria-label="All names signals" className="min-h-0 overflow-auto rounded-xl border border-black/[0.08] bg-white">
    <div className="space-y-2 p-3">
      <h3 className="text-sm font-semibold">All names · {rows.length}</h3>
      <p className="text-xs text-[#6e6e73]">{independent
        ? savedNamesOnly ? `Saved stocks · ${latest.session} · current strategy unavailable` : awaitingNightly
          ? `Last plan · ${publicationSession ?? 'unavailable'}`
          : `${sessionOpen(live, allocation) ? allocation?.version === 'strategy-model-allocation/2' && !currentSession ? 'Awaiting 15-minute entries' : '15-minute signals' : 'Next-session actions'} · ${currentSession ?? allocation?.session ?? latest.session}`
        : 'Regular-session signals and published strategy plans · no paper account or portfolio inputs required. Immediate signals first, then waiting, plans and unavailable; High → Medium → Low within each group. Equal priorities sort alphabetically.'}</p>
      <div className="flex flex-wrap items-center gap-2" role="group" aria-label="Signal ranking">
        {(['all', 'buy', 'sell'] as const).map(value => <button key={value} type="button" aria-pressed={side === value} className={`rounded-full border px-3 py-1 text-xs ${side === value ? 'bg-[#e8f2ff] text-[#0071e3]' : ''}`} onClick={() => {setSide(value); setVisible(25)}}>{value === 'all' ? 'All names' : value === 'buy' ? 'Best buys' : 'Best sells'}</button>)}
        <input aria-label="Find a stock" placeholder="Find a stock" value={query} onChange={event => {setQuery(event.target.value); setVisible(25)}} className="rounded border px-2 py-1 text-xs" />
      </div>
      {awaitingNightly && <p role="status" aria-label="Plan status" className="text-xs text-[#6e6e73]">Last plan · next plan {allocation?.next_publication_at ? evidenceTime(allocation.next_publication_at) : 'not yet scheduled'}</p>}
      <p aria-label="Signal coverage" className="text-xs text-[#6e6e73]">{independent
        ? recommendationsUnavailable ? 'Recommendations unavailable' : awaitingNightly ? `${rows.length} last-plan rows` : `${displayed.filter(item => item.view.verdict === 'buy').length} buys · ${displayed.filter(item => item.view.verdict === 'sell').length} sells`
        : `${rows.filter(row => row.setup).length} of ${rows.length} current assessments · ${rows.filter(row => row.buy.ready).length} buy now · ${rows.filter(row => row.sell.ready).length} sell reviews now · ${rows.filter(row => row.plan).length} published plan rows${!sessionOpen(live, allocation) ? ' · regular session closed or unavailable' : ''}.`}</p>
      {!independent && <p className="text-xs text-[#6e6e73]">Model size is the published strategy target percentage, not shares or an instruction to buy that percentage now. Entry and exit reviews use fresh chart assessments; they do not recalculate the model’s allocation.</p>}
    </div>
    <section aria-label="Data as of" data-market-phase={allocation?.market_phase?.phase} className="flex flex-wrap gap-x-4 gap-y-1 border-t bg-[#f5f5f7] px-3 py-2 text-[11px] text-[#6e6e73]">
      {phaseLine && <span aria-label="Market phase">{phaseLine}</span>}
      <span>Quote {quoteAt ? evidenceTime(quoteAt) : 'unavailable'}</span>
      <span>Completed candle {candleAt ? evidenceTime(candleAt) : 'unavailable'}</span>
      <span>Plan {publicationSession ?? 'unavailable'}{awaitingNightly ? ' (last plan)' : ''}</span>
      <span>{refreshIn === null ? `Refreshes every ${Math.round(refreshMs / 1000)}s` : refreshIn > 0 ? `Refreshing in ${refreshIn}s` : 'Refreshing now'}</span>
    </section>
    <table aria-label="Ranked stock signals" className="w-full text-left text-xs">
      <thead className="border-y bg-[#f5f5f7]"><tr><th className="p-2">Stock / price</th><th className="p-2">Grade</th><th className="p-2">Verdict</th>{independent && <th className="p-2" title="Buy or sell amount as a percentage of model capital">Size %</th>}<th className="p-2" title="Model position size as a percentage of portfolio capital">{independent ? 'Position %' : 'Position size %'}</th>{showPriority && <th className="p-2">Strength</th>}<th className="p-2">Details</th></tr></thead>
      <tbody>{ranked.slice(0, visible).map(row => {
        const {view, refreshing} = views.get(row.ticker)!
        // Only an action is a word; a name with nothing to do shows an empty cell.
        const label = view.verdict === 'buy' ? 'Buy' : view.verdict === 'sell' ? 'Sell' : ''
        const tone = row.lastPlan ? 'text-[#6e6e73]' : view.verdict === 'sell' ? 'text-[#b42318]' : view.verdict === 'buy' ? 'text-[#248a3d]' : 'text-[#6e6e73]'
        return <tr key={row.ticker} data-ticker={row.ticker} className={`border-t align-top${row.lastPlan ? ' text-[#6e6e73] opacity-70' : ''}`}>
        <td className="p-2"><button type="button" className="font-semibold text-[#0071e3]" onClick={() => onOpen(row.ticker)}>{row.ticker}</button>{row.lastPlan && <span className="ml-1 rounded bg-[#eef1f6] px-1 text-[10px] font-medium">last plan</span>}<SessionPrice live={live} ticker={row.ticker} now={now} compact close={closes?.[row.ticker]} closeSession={latest.session} /></td>
        <td aria-label={`${row.ticker} displayed grade`} className="p-2">{row.grade}</td>
        <td aria-label={`${row.ticker} verdict cell`} className="max-w-sm p-2">
          <p aria-label={`${row.ticker} verdict`} className={`font-semibold ${tone}`}>{label}</p>
          {(view.nextSession || view.state) && <span className="mt-1 inline-block rounded bg-[#eef1f6] px-1.5 py-0.5 text-[10px] font-medium text-[#3a3a3c]">{view.nextSession ? 'next session' : view.state}</span>}
          {refreshing && <span className="mt-1 ml-1 inline-block rounded bg-[#fff4d6] px-1.5 py-0.5 text-[10px] font-medium text-[#9a6700]">refreshing</span>}
        </td>
        {independent && <td className="p-2"><span aria-label={`${row.ticker} trade size`}>{sizeText(view.size)}</span>{sizedAmount(row.ticker, view.size, planningEquity, displayedBoardPrice(live, row.ticker, now, closes?.[row.ticker], latest.session)?.price)}</td>}
        <td className="p-2"><ModelSize latest={latest} allocation={allocation} ticker={row.ticker} now={now} /></td>
        {showPriority && <td aria-label={`${row.ticker} signal strength`} className="p-2">{selected(row).priority ? selected(row).priority[0].toUpperCase() + selected(row).priority.slice(1) : '—'}</td>}
        <td className="max-w-sm p-2"><button type="button" aria-label={`details for ${row.ticker}`} aria-expanded={opened === row.ticker} className="text-[#0071e3]" onClick={() => setOpened(opened === row.ticker ? null : row.ticker)}>Details</button>{opened === row.ticker && <SignalDetail signals={row} />}</td>
      </tr>})}</tbody>
    </table>
    {recommendationsUnavailable && ranked.length > 0 && <p role="status" className="p-3 text-xs">Current recommendations unavailable. Saved stock charts remain available.</p>}
    {!ranked.length && <p role="status" className="p-3 text-xs">{query.trim() ? 'No matching stocks.' : recommendationsUnavailable ? 'Strategy recommendations unavailable. Refresh to retry.' : awaitingNightly ? allocation?.next_publication_at ? `Awaiting tonight's plan at ${evidenceTime(allocation.next_publication_at)}.` : "Awaiting tonight's plan." : side === 'sell' ? rows.some(row=>row.sell.word==='Wait') ? 'No confirmed sell signals yet.' : 'No sell signals in the current strategy publication.' : side === 'buy' ? rows.some(row=>row.buy.word==='Wait') ? 'No confirmed buy signals yet.' : 'No buy signals in the current strategy publication.' : 'No matching stocks.'}</p>}
    {independent && <p className="px-3 py-2 text-[11px] text-[#6e6e73]">Size % is the buy or sell amount. Position % is the model’s desired total position. Do nothing means no trade is recommended now. — means no confirmed trade size.{planningEquity ? ` The ≈ line applies Size % to the planning equity ($${planningEquity.toLocaleString('en-US', {maximumFractionDigits: 0})}) at the shown price; whole shares, rounded down.` : ''}</p>}
    {ranked.length > visible && <button type="button" className="p-3 text-xs text-[#0071e3]" onClick={() => setVisible(value => value + 25)}>Show more · {visible} of {ranked.length}</button>}
  </section>
}
