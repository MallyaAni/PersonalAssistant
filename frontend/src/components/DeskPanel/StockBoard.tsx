import type { DeskDecisions, DeskLive, DeskPayload, DeskRecord, DeskSessionPrices } from '../../services/api'

// Scope known execution-clock reasons to the regular session without changing readiness.
export const executionClockMessage = (reason?: string | null) => {
  if (!['market closed or clock unavailable', 'market closed'].includes(reason?.toLowerCase() ?? '')) return null
  return {short: 'Regular-session execution blocked', full: 'Regular-session execution is blocked; the session is closed or its clock is unavailable'}
}

// Accept only the documented schedule vocabulary; a schedule is never proof of venue availability.
const quoteSchedule = (value: unknown): DeskSessionPrices['session'] | null =>
  typeof value === 'string' && ['pre-market', 'post-market', 'overnight', 'regular', 'closed', 'unknown'].includes(value)
    ? value as DeskSessionPrices['session'] : null

// Validate dated quote evidence independently of regular-session scheduling and execution policy.
const sessionPrice = (live: DeskLive, ticker: string, now: number) => {
  const envelope = live.extended_hours
  const quote = envelope?.quotes[ticker]
  const observed = Date.parse(quote?.at ?? '')
  const captured = Date.parse(envelope?.as_of ?? '')
  const until = Date.parse(quote?.valid_until ?? '')
  const dated = typeof quote?.feed === 'string' && quote.feed.trim().length > 0
    && Number.isFinite(observed) && observed <= captured && captured <= now
    && envelope?.signal_scope === 'regular-session'
  const priced = typeof quote?.price === 'number' && Number.isFinite(quote.price) && quote.price > 0
  const valid = dated && priced && quote?.status === 'fresh'
    && now - captured < 60_000 && now - observed < 60_000
    && Number.isFinite(until) && until > now
  const state = valid ? 'fresh' : dated && (quote?.status === 'stale' || priced && quote?.status === 'fresh'
    && (until <= now || now - observed >= 60_000 || now - captured >= 60_000)) ? 'stale' : 'unavailable'
  const envelopeSchedule = quoteSchedule(envelope?.session)
  const regularSchedule = live.market_status?.phase === 'open' ? 'regular' : quoteSchedule(live.market_status?.phase)
  const regularAt = Date.parse(live.market_status?.as_of ?? '')
  // XNYS pre/post phases include overnight; only its explicit open maps exactly to this finer schedule.
  const currentSchedule = regularSchedule === 'regular' && Number.isFinite(regularAt) && regularAt > captured && regularAt <= now
    ? 'regular' : envelopeSchedule ?? regularSchedule ?? 'unknown'
  // Legacy extension envelopes carried their observation phase; a legacy regular envelope did not.
  const observationSchedule = quoteSchedule(quote?.session)
    ?? (envelopeSchedule && ['pre-market', 'post-market', 'overnight'].includes(envelopeSchedule) ? envelopeSchedule : null)
  const namedSession = observationSchedule && !['closed', 'unknown'].includes(observationSchedule) ? observationSchedule : null
  return {quote, state, observed, session: namedSession, currentSchedule,
    previousSession: namedSession !== null && currentSchedule !== 'unknown' && namedSession !== currentSchedule,
    unrecordedSession: observationSchedule === null}
}

// Include the New York date when a time alone could be mistaken for today's observation.
const quoteTime = (observed: number, now: number): string | null => {
  if (!Number.isFinite(observed)) return null
  const observation = new Date(observed)
  const current = new Date(now)
  const sameDay = observation.toLocaleDateString('en-CA', {timeZone: 'America/New_York'})
    === current.toLocaleDateString('en-CA', {timeZone: 'America/New_York'})
  const sameYear = observation.toLocaleDateString('en-US', {timeZone: 'America/New_York', year: 'numeric'})
    === current.toLocaleDateString('en-US', {timeZone: 'America/New_York', year: 'numeric'})
  return observation.toLocaleString('en-US', {timeZone: 'America/New_York', hour: 'numeric', minute: '2-digit', second: '2-digit',
    ...(!sameDay ? {month: 'short', day: 'numeric', ...(!sameYear ? {year: 'numeric'} : {})} as const : {})})
}

// The UTC instant of a New York wall-clock hour on a given session day
// (16:00 ET is 20:00Z in summer and 21:00Z in winter).
const newYorkHour = (day: string, hour: number): number => {
  const guess = Date.parse(`${day}T${String(hour).padStart(2, '0')}:00:00Z`)
  if (!Number.isFinite(guess)) return NaN
  const seen = Number(new Date(guess).toLocaleString('en-US', {timeZone: 'America/New_York', hour: 'numeric', hourCycle: 'h23'}))
  return guess + (((hour - seen) % 24 + 24) % 24) * 3_600_000
}

// The New York calendar day of an instant, as YYYY-MM-DD.
const newYorkDay = (at: number): string => new Date(at).toLocaleDateString('en-CA', {timeZone: 'America/New_York'})

// The board row's price when no fresh midpoint exists: the freshest dated price
// among the last observed midpoint, the latest completed regular 15-minute bar
// and the recorded close. The close is the official print of its session, so it
// wins over a bar of that same session (its time is that bar's end, which is the
// close even on an early-close day); a bar from a later session wins over it.
export const boardFallback = ({lastPrice, observed, word, regular, lastClose, closeSession}: {
  lastPrice: number | null; observed: number; word: string
  regular?: {last: number; bar: string} | null; lastClose: number | null; closeSession?: string | null
}): {kind: 'midpoint' | 'regular' | 'close'; price: number; at: number; word: string} | null => {
  const barStart = regular && Number.isFinite(regular.last) && regular.last > 0 ? Date.parse(regular.bar) : NaN
  const barEnd = Number.isFinite(barStart) ? barStart + 15 * 60_000 : NaN
  const barDay = Number.isFinite(barStart) ? newYorkDay(barStart) : null
  const closeAt = lastClose === null ? NaN
    : closeSession && barDay === closeSession ? barEnd
    : closeSession ? newYorkHour(closeSession, 16) : -Infinity
  const candidates: {kind: 'midpoint' | 'regular' | 'close'; price: number; at: number; word: string; rank: number}[] = []
  if (lastPrice !== null && Number.isFinite(observed)) candidates.push({kind: 'midpoint', price: lastPrice, at: observed, word, rank: 1})
  if (Number.isFinite(barEnd) && !(lastClose !== null && closeSession && barDay !== null && barDay <= closeSession))
    candidates.push({kind: 'regular', price: regular!.last, at: barEnd, word: 'regular', rank: 0})
  if (lastClose !== null) candidates.push({kind: 'close', price: lastClose, at: closeAt, word: 'close', rank: 2})
  if (!candidates.length) return null
  candidates.sort((a, b) => (b.at - a.at) || (b.rank - a.rank))
  const {kind, price, at, word: label} = candidates[0]
  return {kind, price, at, word: label}
}

// Select the same dated price for the compact quote and its level comparisons.
export const displayedBoardPrice = (live: DeskLive, ticker: string, now: number, close?: number | null, closeSession?: string | null) => {
  const {quote, state, observed, session} = sessionPrice(live, ticker, now)
  if (state === 'fresh') return {kind: 'midpoint' as const, price: quote!.price!, at: observed, word: (session ?? 'quote').toLowerCase(), current: true}
  const lastPrice = state === 'stale' && typeof quote?.price === 'number' && Number.isFinite(quote.price) && quote.price > 0 ? quote.price : null
  const lastClose = typeof close === 'number' && Number.isFinite(close) && close > 0 ? close : null
  const fallback = boardFallback({lastPrice, observed, word: (session ?? 'quote').toLowerCase(), regular: live.quotes[ticker], lastClose, closeSession})
  return fallback ? {...fallback, current: fallback.kind === 'regular' && now - fallback.at < 20 * 60_000} : null
}

// Show the current midpoint, or the last observed one dated by its own time, or the
// last close; never a stale price styled or worded as current, and never nothing when
// a dated price exists. Execution and candle evidence are untouched.
export const SessionPrice = ({live, ticker, now, compact = false, close, closeSession}: {live: DeskLive; ticker: string; now: number; compact?: boolean; close?: number | null; closeSession?: string | null}) => {
  const {quote, state, observed, session, currentSchedule, previousSession, unrecordedSession} = sessionPrice(live, ticker, now)
  const regular = live.quotes[ticker]
  const at = quoteTime(observed, now)
  const source = `${quote?.indicative ? 'Indicative · ' : ''}${quote?.feed?.toUpperCase() || 'Source unavailable'}`
  const regularText = regular && Number.isFinite(regular.last) ? `Regular-session bar $${regular.last.toFixed(2)} · ${regular.bar}` : 'Regular-session bar unavailable'
  const qualification = previousSession ? ' · previous-session observation' : unrecordedSession ? ' · session unrecorded' : ''
  const displayReason = quote?.status === 'unavailable' && quote.reason
    ? quote.reason === 'No fresh quote from available feeds' ? 'No usable bid/ask midpoint was returned for this display.' : `Price-data detail: ${quote.reason}` : null
  // A stale row carries what was last observed; the price is shown only with its own time.
  const lastPrice = state === 'stale' && typeof quote?.price === 'number' && Number.isFinite(quote.price) && quote.price > 0 ? quote.price : null
  const lastClose = typeof close === 'number' && Number.isFinite(close) && close > 0 ? close : null
  const staleCaveat = state === 'stale' ? ' Last observed price; not a current quote.' : ''
  const fallback = compact ? displayedBoardPrice(live, ticker, now, close, closeSession) : null
  const regularCurrent = fallback?.kind === 'regular' && now - fallback.at < 20 * 60_000
  return <div aria-label={`${ticker} session price`} title={`${quote?.at ? `Last observed ${at} ET. ` : ''}${source}. ${regularText}. Signal: regular session. Midpoint is not a trade or guaranteed fill. Reported quote timestamp: ${quote?.at ?? 'unavailable'}. Expected schedule: ${currentSchedule}; not proof of venue availability. For display only; execution checks are separate.${displayReason ? ` ${displayReason}` : ''}${staleCaveat}`}>
    {compact
      // The board row: the price and one word for the session it belongs to;
      // the provenance (feed, time, regular bar, caveats) is the hover text.
      ? state === 'fresh' ? <><span className="font-medium">${quote!.price!.toFixed(2)}</span><span className="ml-1">{" "}{(session ?? "quote").toLowerCase()}</span><ChangeMark last={quote!.price!} close={close} /></>
        : fallback?.kind === 'regular' ? <><span className={regularCurrent ? 'font-medium' : 'text-[#9a6700]'}>${fallback.price.toFixed(2)}</span><span className={`ml-1 ${regularCurrent ? '' : 'text-[#9a6700]'}`}>{" "}regular</span><ChangeMark last={fallback.price} close={close} /></>
        : <span className="text-[#9a6700]">{fallback ? `$${fallback.price.toFixed(2)} ${fallback.word}` : 'No price to display'}</span>
      : state === 'fresh' ? <><span className="font-medium">${quote!.price!.toFixed(2)}</span><span className="ml-1">{session ?? 'Quote'} · {source} · {at} ET{qualification}</span></>
      : <span className="text-[#9a6700]">{lastPrice !== null
          ? `$${lastPrice.toFixed(2)} last ${session ?? 'quote'} · ${source}${at ? ` · ${at} ET` : ''}${qualification}`
          : lastClose !== null ? `$${lastClose.toFixed(2)} last close` : 'No price to display'}</span>}
    {!compact && <p className="text-[11px] text-[#6e6e73]">Price signals use regular-session candles.</p>}
  </div>
}

// The three things the desk can be doing about a name. Declared here because
// this is the board that lists them and DeskPanel already imports from it; the
// other direction would be a cycle.
export const PLAN_ACTIONS = ['Buy', 'Sell', 'Hold'] as const
export type PlanAction = (typeof PLAN_ACTIONS)[number]

// The one word a board row shows for its plan: BUY, SELL, Hold, or TRIM for
// a Sell that keeps a positive target (the decision view writes "Trim to
// <target>" for that case and leaves `target_weight` above zero), so a
// partial reduction never reads as an exit. Casing follows the board's
// convention: the two trading words in capitals, Hold as written.
export const actionWord = (plan: PlanAction, decision?: {strategy_action?: string; target_weight?: number | null; reason?: string | null}): string => {
  if (plan === 'Hold') return 'Hold'
  if (plan === 'Sell' && decision?.strategy_action === 'Sell'
    && ((decision.target_weight ?? 0) > 0 || /^Trim to /.test(decision.reason ?? ''))) return 'TRIM'
  return plan.toUpperCase()
}

// Whether the decisions on screen are the `/4` board's timed ones for the
// record on screen (the backend sends `decisions.timing` only there). Shared
// by the plan column, the size, the grade and the executable-signal count so
// they cannot disagree about which board it is.
export const timedBoard = (decisions: DeskDecisions | undefined, latest: DeskRecord | null | undefined): boolean =>
  !!decisions?.timing && !!latest && decisions.session === latest.session && decisions.written === latest.written

// Separate missing evidence and waiting setups from an actual instruction to keep a position.
export const actionPresentation = (plan: PlanAction, decision: DeskDecisions['rows'][string] | undefined, timed: boolean, now: number, paused = false): {word: string; detail: string | null} => {
  if (paused) return {word: 'Paused', detail: 'FOMC'}
  if (!decision || !PLAN_ACTIONS.includes(decision.action)) return {word: 'Unavailable', detail: 'Refresh guidance'}
  const intent = decision.strategy_action ?? decision.action
  if (!PLAN_ACTIONS.includes(intent)) return {word: 'Unavailable', detail: 'Refresh guidance'}
  if (!timed) return {word: actionWord(plan, decision), detail: null}
  if (intent === 'Hold') return decision.entry_status === 'unavailable'
    ? {word: 'Unavailable', detail: 'Entry data missing'}
    : {word: 'Hold', detail: null}
  const detail = `Strategy: ${actionWord(intent, decision).toLowerCase()}`
  const learned = decision.learned_timing
  if (decision.action === 'Hold' && decision.timing?.rule === 'live-probability-timing/1-research'
    && learned?.policy === decision.timing.rule && learned.state === 'wait') {
    const expiry = Date.parse(decision.valid_until ?? '')
    const observed = Date.parse(learned.at)
    if (!Number.isFinite(expiry) || expiry <= now || !Number.isFinite(observed) || observed > now)
      return {word: 'Unavailable', detail: 'Refresh price check'}
    if (decision.quote.eligible && decision.quote.spread_verified === true)
      return {word: 'Wait', detail}
  }
  if (decision.action === 'Hold' && decision.entry_guard?.allowed === false
    && decision.blocker === decision.entry_guard.reason) {
    const expiry = Date.parse(decision.valid_until ?? '')
    return Number.isFinite(expiry) && expiry > now
      ? {word: 'Hold', detail: 'Entry limit'}
      : {word: 'Unavailable', detail: 'Refresh price check'}
  }
  if (decision.executable === false) return decision.blocker === 'available cash is unknown'
    ? {word: 'Cash needed', detail: 'Confirm available cash'}
    : {word: 'Blocked', detail}
  const deadline = Date.parse(decision.valid_until ?? '')
  if (!Number.isFinite(deadline) || deadline <= now) return {word: 'Unavailable', detail: 'Refresh price check'}
  if (decision.action === 'Hold') return {word: 'Wait', detail}
  return {word: actionWord(plan, decision), detail: null}
}

// The timing states in the operator's words, for the hover.
const TIMING_STATE: Record<string, string> = {
  'pre-open': 'before the level is set',
  waiting: 'waiting for the level',
  triggered: 'level reached today',
  close: 'close window',
  closed: 'session closed',
}

// The lines a timed `/4` row adds to its hover under the word and reason: the
// timing state with its sentence, the executor's band gate, and the grade the
// action is based on beside the candle's re-grade. Everything else about the
// row stays off the cell, which shows only the word and the size.
export const timedHover = (decision: DeskDecisions['rows'][string], session: string): string[] => {
  const lines: string[] = []
  if (decision.timing) lines.push(`Timing · ${TIMING_STATE[decision.timing.state] ?? decision.timing.state}: ${decision.timing.reason}`)
  lines.push(decision.structure_gate === 'rejecting' ? "Structure · rejecting its upper band (executor's gate): no buy today"
    : decision.structure_gate === 'clear' ? "Structure · not rejecting its upper band (executor's gate)"
    : 'Structure · band gate not recorded on this decision; not treated as a block')
  lines.push(`Grade ${decision.grade || '—'} at the ${session} close (the one the action uses)${decision.grade_intraday ? ` · intraday reading ${decision.grade_intraday}` : ' · no intraday reading'}`)
  return lines
}

// Format a portfolio weight without rounding a small positive allocation to zero.
const percentage = (weight: number) => weight > 0 && weight < .001 ? '<0.1%' : `${(weight * 100).toFixed(1)}%`

// A name's move against its last close, in green or red with an arrow so the
// direction reads without colour; nothing when there is no close to compare
// against. This is the row a trader scans for, so it sits beside the price.
const ChangeMark = ({ last, close }: { last: number; close: number | null | undefined }) => {
  if (close == null || close <= 0 || !Number.isFinite(last)) return null
  const raw = (last / close - 1) * 100
  // Below a twentieth of a point the row would print a signed zero, which
  // reads as a move that did not happen.
  const change = Math.abs(raw) < 0.05 ? 0 : raw
  const up = change > 0
  const down = change < 0
  const cls = up ? 'text-[#1e7a3a]' : down ? 'text-[#b42318]' : 'text-[#6e6e73]'
  const mark = up ? '↑' : down ? '↓' : '·'
  const sign = change > 0 ? '+' : ''
  return <span className={`ml-1 ${cls}`} title="vs the last close">{mark} {sign}{change.toFixed(1)}%</span>
}

// What the board shows during an FOMC cycle: the exposure the desk actually
// holds (null while the cycle's current policy status is unknown), the
// decision the cycle belongs to, and whether the calendar itself is missing.
export type BoardEvent = {exposure: number | null; decisionDate: string | null; calendarUnknown: boolean}

// The board's own simulation, read as a footer under the research view:
// measurement, not a decision, so it no longer sits under the stock list.
export const BoardSimulation = ({paper, now}: {paper?: DeskPayload['board_paper']; now: number}) => {
  return paper?.equity === undefined ? null : <p aria-label="Board simulation" className="border-t px-3 py-2 text-[11px] text-[#6e6e73]" title="Separate local simulation, not a brokerage account. Delayed quotes, spread and 10 bp extra cost per side. No real orders. Overnight marks wait for corporate-action validation.">
      Board simulation · research, not the practice account · {paper.equity.toLocaleString('en-US', {style: 'currency', currency: 'USD'})} · USD {percentage(paper.cash / paper.equity)} · {((paper.equity / paper.initial_capital - 1) * 100).toFixed(2)}% since start {new Date(paper.started_at).toLocaleDateString('en-US', {timeZone: 'America/New_York', month: 'short', day: 'numeric'})}
      <span className="ml-1">· {new Date(paper.as_of).toLocaleString('en-US', {timeZone: 'America/New_York', month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit'})} ET{now - Date.parse(paper.as_of) >= 900000 ? ' · awaiting update' : ''}</span>
    </p>
}

// The frozen ML shadow against the desk, research only.
export const MlComparison = ({ml}: {ml?: DeskPayload['ml_forward']}) => {
  return !ml ? null : <details aria-label="ML forward comparison" className="shrink-0 border-t px-3 py-2 text-xs">
      <summary className="cursor-pointer">ML paper comparison · {ml.session ?? 'awaiting first close'} · input validation incomplete</summary>
      <p className="my-2 text-[#9a6700]">Input validation incomplete: known financial/share-unit issues. These frozen accounts do not establish superiority over the live strategy.</p>
      <p className="my-2 text-[#6e6e73]">Separate simulated accounts starting at $100,000 each. Frozen model; no real orders. Updated nightly. Costs of 10 or 30 basis points per traded dollar are included. This research portfolio does not follow the live desk’s FOMC policy.</p>
      <p>{ml.status}</p>
      {ml.observed_at && <p>Last observed {new Date(ml.observed_at).toLocaleString('en-US', {timeZone: 'America/New_York'})} ET</p>}
      <table aria-label="ML paper returns" className="mt-2 w-full tabular-nums"><thead><tr><th className="text-left">Policy / cost</th><th>Account</th><th>Return</th></tr></thead>
        <tbody>{Object.entries(ml.accounts).map(([name, account]) => <tr key={name}><td>{name}</td><td className="text-center">{account.equity.toLocaleString('en-US', {style: 'currency', currency: 'USD'})}</td><td className="text-center">{(account.total_return * 100).toFixed(2)}%</td></tr>)}</tbody>
      </table>
    </details>
}
