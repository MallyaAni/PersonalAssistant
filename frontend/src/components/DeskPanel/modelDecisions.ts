import type {DeskModelDecision, DeskPaperLive, DeskRecord} from '../../services/api'
import {isLabel, MODEL_ACTIONS} from '../../services/labels'

export type ModelDecisionView = {decision: DeskModelDecision | null; status: string; reason: string}

const statusText: Record<DeskModelDecision['status'], string> = {
  planned: 'Planned', blocked: 'Blocked', no_new_order: 'No new order',
  no_position: 'No position', complete: 'Decision complete', unavailable: 'Awaiting model plan',
}

// Accept action, size and timing together only from the same current admitted projection.
export const modelDecisionFor = (latest: DeskRecord, paper: DeskPaperLive | null | undefined, ticker: string, now: number): ModelDecisionView => {
  const absent = {decision: null, status: 'Awaiting model plan', reason: 'A current numeric decision, funded quantity and execution time are not provided. A saved target, chart judgment or existing holding cannot supply a missing model plan.'}
  if (paper?.reason) return {...absent, status: 'Account unavailable', reason: `Account unavailable: ${paper.reason}`}
  const projection = paper?.model_decisions
  if (!projection) return absent
  const reason = typeof projection.reason === 'string' && projection.reason.trim() ? projection.reason : absent.reason
  if (projection.status !== 'available') return {...absent, reason}
  const observed = Date.parse(projection.observed_at ?? ''), until = Date.parse(projection.valid_until ?? '')
  if (projection.version !== 'live-model-decisions/1' || projection.session !== latest.session
      || projection.policy !== latest.targets?.policy
      || !/^[a-f0-9]{64}$/.test(projection.record_sha256 ?? '')
      || !/^[a-f0-9]{64}$/.test(projection.receipt_sha256 ?? '')
      || !Number.isFinite(observed) || observed > now || !(until > now))
    return {...absent, reason: 'The numeric model plan is stale or its recorded source does not match this view.'}
  const decision = projection.rows?.[ticker]
  if (!decision || !Object.prototype.hasOwnProperty.call(statusText, decision.status) || typeof decision.reason !== 'string' || !decision.reason.trim()) return {...absent, reason}
  if (decision.status === 'unavailable') return {...absent, reason: decision.reason}
  if (decision.status === 'complete' || decision.status === 'no_position')
    return {decision: {...decision, action: null, qty: null, when: null}, status: statusText[decision.status], reason: decision.reason}
  if (!isLabel(MODEL_ACTIONS, decision.action)
      || !Number.isInteger(decision.qty) || decision.qty! < 0
      || decision.action === 'hold' && decision.qty !== 0
      || decision.action !== 'hold' && decision.qty === 0 && decision.status !== 'blocked'
      || decision.qty! > 0 && (typeof decision.when !== 'string' || !decision.when.trim()))
    return {...absent, reason: 'The numeric model plan does not provide a consistent action, funded quantity and timing.'}
  return {decision, status: statusText[decision.status], reason: decision.reason}
}
