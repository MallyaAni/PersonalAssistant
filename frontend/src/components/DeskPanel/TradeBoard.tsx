import { Fragment, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import type { DeskCurrentSetup, DeskLevelTag, DeskLive, DeskPaperLive, DeskPaperOrder, DeskPaperPlan, DeskRecord, DeskStructure } from '../../services/api'
import { displayedBoardPrice, SessionPrice } from './StockBoard'
import {currentAssessments, assessmentPermission} from './liveAssessment'
import {rankCurrent, confirmationText, invalidationText, quoteReferenceText} from './currentRanking'

// The Stock rankings board, rebuilt around one question a trader asks of it:
// what is the paper account doing about each name, how big, and when.
//
// Orders come from `/desk/paper` (`plan.orders`). Grade signals are shown
// separately, including when no order can be sized or funded. The paper account
// sends only its recorded orders. Their wording (why, when, what happened) comes
// from the backend in one place, so this board, the ticker panel and the
// chart cannot tell different stories. A name with no order is HOLD when the
// account holds it and a dash when it does not.
//
// Levels shows the account's unsubmitted price triggers. Technical references
// belong in stock details; a reference indicator is never an order price.

// The four words a row can say, and the dash for a name the account neither
// holds nor trades.
export type BoardWord = 'BUY' | 'ADD' | 'SELL' | 'TRIM' | 'HOLD' | 'WAIT' | 'REVIEW' | '—' | 'ORDERS'

const LEARNED_HOLDING_POLICY = 'joint-stock-risk-funded/6-retained-holdings-probability-timing-research'

// Identify the recorded learned allocator without reclassifying older decisions.
export const learnedAllocation = (latest: DeskRecord): boolean => [LEARNED_HOLDING_POLICY, 'grade-led-learned-sizing/1'].includes(latest.targets?.policy ?? '')

// Explain the board's presentation of recorded decisions without inventing a stock score.
export const rankingText = 'Current opportunities rank outstanding orders, exits of remaining below-A holdings, chart exit reviews, then ready entries and waits. Fresh chart judgment, grade and analyst conviction break ties; saved target sizes do not rank opportunities. Prices refresh separately; judgments use completed 15-minute candles. This is an evidence ranking, not a profit forecast.'

// Prefer the executor's recorded rule rather than assigning legacy timing to a new policy.
export const executionRuleText = (plan?: DeskPaperPlan): string => {
  if (plan?.rule_text) return [...new Set(Object.values(plan.rule_text))].join(' · ')
  if (plan?.rule === 'next_open') return 'Recorded timing: next open. Each order states its execution session and timing.'
  if (plan?.rule === 'dip_or_close') return 'Buys wait for a 15-minute close at least 1% under the day’s open; sells wait for one at least 1% over. Otherwise, a market order goes in at 3:45 PM ET, the last 15-minute candle before the regular close.'
  return 'Order timing unavailable; see each order.'
}

// One name on the board, with everything its row and its details show.
export type BoardRow = {
  ticker: string
  grade: string
  word: BoardWord
  done: boolean
  why: string
  orders: DeskPaperOrder[]
  qty: number
  sizeLabel: string
  combined: boolean
  notional: number | null
  weight: number | null
  held: number
  heldValue: number | null
  heldWeight: number | null
  avgCost: number | null
  unrealized: number | null
  target: number | null
  allocation: 'modeled' | 'retained' | 'unavailable' | 'recorded' | 'event'
  allocationNote: string
  status: string
  state: string
  when: string
  signal?: string
  signalReason?: string
  currentSetup?: DeskCurrentSetup | null
  freshGrade?: string
}

// The views a trader switches between: what the account is trading today,
// the whole portfolio (orders and holdings), and every graded name.
type View = 'orders' | 'portfolio' | 'all'
type SortKey = 'ticker' | 'grade' | 'position' | 'size'
const FILTER_ACTIONS = ['BUY', 'ADD', 'SELL', 'TRIM', 'REVIEW', 'WAIT', 'HOLD', '—'] as const
type FilterAction = typeof FILTER_ACTIONS[number]
export type ActionSelection = Record<FilterAction, boolean>
const ALL_ACTIONS: ActionSelection = {BUY: true, ADD: true, SELL: true, TRIM: true, REVIEW: true, WAIT: true, HOLD: true, '—': true}

// Match each recorded leg of mixed orders while keeping non-traded names in their displayed category.
const hasAction = (row: BoardRow, action: FilterAction) => row.orders.length
  ? row.orders.some(order => orderWord(order) === action) : row.word === action

// Date a plan's saved allocation wherever it appears beside live holdings or prices.
export const savedTargetText = (row: BoardRow, session: string) =>
  `Saved target ${row.target === null ? 'unavailable' : percent(row.target)} · ${session}`

const GRADE_RANK: Record<string, number> = { 'A+': 3, A: 2, B: 1, C: 0 }
// Where the viewer's own account size is kept: a per-browser convenience that
// only scales the paper account's sizes, never read by the server.
const MY_ACCOUNT_KEY = 'desk.myAccount'

// Read the viewer's account size, or null when unset or storage is blocked.
const readMyAccount = (): number | null => {
  try {
    const value = Number(window.localStorage.getItem(MY_ACCOUNT_KEY))
    return Number.isFinite(value) && value > 0 ? value : null
  } catch {
    return null
  }
}

// Remember the viewer's account size; a blocked storage just forgets it.
const writeMyAccount = (value: number | null) => {
  try {
    if (value === null) window.localStorage.removeItem(MY_ACCOUNT_KEY)
    else window.localStorage.setItem(MY_ACCOUNT_KEY, String(value))
  } catch {
    // the size still applies for this visit
  }
}

// Whole dollars, the way a size reads: $1,250.
export const dollars = (value: number) => `$${Math.round(value).toLocaleString('en-US')}`

// A price to the cent: $40.51.
export const price = (value: number) => `$${value.toLocaleString('en-US', {minimumFractionDigits: 2, maximumFractionDigits: 2})}`

// A share of the account without rounding a small position to zero: 8.3%.
export const percent = (weight: number) => weight > 0 && weight < 0.001 ? '<0.1%' : `${(weight * 100).toFixed(1)}%`

// Shares, with the unit: 1,250 sh.
export const shares = (qty: number) => `${qty.toLocaleString('en-US', {maximumFractionDigits: 6})} sh`

// The structure the board shows and the desk does not act on: the two levels
// the operator reads, the distance to each, the EMA's slope, a first-bar
// rejection, and the age of the price the row was computed from. Every word
// here describes what happened; none of it says what to do.

// The board's name for each level.
export const LEVEL_NAME: Record<DeskLevelTag['level'], string> = { ema_21: '21-EMA', high_20: '20-day high' }

// A count as an ordinal: 1st, 2nd, 3rd, 4th, 11th, 12th, 13th, 21st.
export const ordinal = (count: number): string => {
  const tens = count % 100
  const suffix = tens >= 11 && tens <= 13 ? 'th' : count % 10 === 1 ? 'st' : count % 10 === 2 ? 'nd' : count % 10 === 3 ? 'rd' : 'th'
  return `${count}${suffix}`
}

// A level's price to a tenth, the way the board names it: 104.4.
const levelPrice = (value: number) => value.toFixed(1)

// The distance from a price to a level as a signed share of the level: one
// decimal under ten percent (−3.1%), whole percent from ten up (−14%).
export const distance = (price: number, level: number): string => {
  const pct = (price / level - 1) * 100
  const size = Math.abs(pct)
  return `${pct < 0 ? '−' : '+'}${size >= 10 ? size.toFixed(0) : size.toFixed(1)}%`
}

// The row's level lines: "21-EMA 104.4 (−3.1%) ↓" and "20-day high 116.9
// (−14%)". The distance is from `price` (the row's last price); the arrow is
// the sign of the EMA's five-session slope. A level the balancer has not
// computed is left out.
export const levelLines = (structure: DeskStructure | undefined, price: number | null): string[] => {
  if (!structure) return []
  const away = (level: number) => price !== null && price > 0 ? ` (${distance(price, level)})` : ''
  const lines: string[] = []
  if (structure.ema_21 !== null && structure.ema_21 > 0) {
    const slope = structure.ema_21_slope_5
    const arrow = slope === null || slope === undefined ? '' : slope > 0 ? ' ↑' : slope < 0 ? ' ↓' : ' →'
    lines.push(`${LEVEL_NAME.ema_21} ${levelPrice(structure.ema_21)}${away(structure.ema_21)}${arrow}`)
  }
  if (structure.high_20 !== null && structure.high_20 > 0) {
    lines.push(`${LEVEL_NAME.high_20} ${levelPrice(structure.high_20)}${away(structure.high_20)}`)
  }
  return lines
}

// Explain this stock's actual level relationships without implying an order or forecast.
export const levelDescription = (ticker: string, structure: DeskStructure | undefined, displayed: ReturnType<typeof displayedBoardPrice>): string => {
  const levels = (['ema_21', 'high_20'] as const).filter(key => typeof structure?.[key] === 'number' && Number.isFinite(structure[key]) && structure[key]! > 0)
  if (!levels.length) return `${ticker}: reference levels unavailable.`
  if (!displayed) return `${ticker}: price unavailable; level distances unavailable. Reference levels only.`
  const relationships = levels.map(key => `${displayed.price > structure![key]! ? 'above' : displayed.price < structure![key]! ? 'below' : 'at'} ${LEVEL_NAME[key]}`).join('; ')
  const slope = structure?.ema_21_slope_5
  const trend = typeof slope === 'number' && Number.isFinite(slope) ? ` EMA ${slope > 0 ? 'rising' : slope < 0 ? 'falling' : 'flat'} over five sessions.` : ''
  return `${ticker}: ${relationships}.${trend} Compared with ${displayed.current ? '' : 'last known '}${displayed.word} price ${price(displayed.price)}. Reference levels only; not order prices.`
}

// The flag for a first bar that reached a level from below and closed back
// under it: "Rejected at 21-EMA 104.4 · 3rd day". Null when the session's
// first bar did not, or did and held.
export const levelFlag = (structure: DeskStructure | undefined): string | null => {
  const tag = structure?.level_tag
  if (!tag || !tag.rejected) return null
  return `Rejected at ${LEVEL_NAME[tag.level]} ${levelPrice(tag.price)} · ${ordinal(tag.consecutive_sessions)} day`
}

// When the row's price is from and how old it is now: "as of 11:30 AM, 12
// min ago". The instant is the balancer's (the bar's end); the age is
// measured against the page's clock so it keeps counting between candles.
// Null without a dated price.
export const priceAge = (structure: DeskStructure | undefined, now: number): string | null => {
  const at = Date.parse(structure?.price_as_of ?? '')
  if (!Number.isFinite(at)) return null
  const clock = new Date(at).toLocaleTimeString('en-US', {timeZone: 'America/New_York', hour: 'numeric', minute: '2-digit'})
  const minutes = Math.max(0, Math.round((now - at) / 60_000))
  const ago = minutes < 1 ? 'under a minute ago' : minutes < 60 ? `${minutes} min ago` : `${Math.floor(minutes / 60)} h ${minutes % 60} min ago`
  return `as of ${clock}, ${ago}`
}

// The colour of each word: green buys, red sells, amber trims, grey holds.
export const WORD_STYLE: Record<BoardWord, string> = {
  BUY: 'text-[#248a3d]',
  ADD: 'text-[#248a3d]',
  WAIT: 'text-[#b25e00]',
  REVIEW: 'text-[#b25e00]',
  SELL: 'text-[#b42318]',
  TRIM: 'text-[#b25e00]',
  HOLD: 'text-[#6e6e73]',
  ORDERS: 'text-[#6e6e73]',
  '—': 'text-[#86868b]',
}

// The dot beside a status, by how far the order has got.
const STATE_DOT: Record<string, string> = {
  planned: 'bg-[#86868b]',
  queued: 'bg-[#86868b]',
  waiting: 'bg-[#ff9f0a]',
  due: 'bg-[#0071e3]',
  sent: 'bg-[#0071e3]',
  filled: 'bg-[#248a3d]',
  partial: 'bg-[#ff9f0a]',
  held: 'bg-[#86868b]',
  cancelled: 'bg-[#b42318]',
  rejected: 'bg-[#b42318]',
  missed: 'bg-[#b42318]',
  problem: 'bg-[#b42318]',
}

// How settled an order is, so a name with several orders reports the one
// still to happen rather than the one already done.
const PROGRESS: Record<string, number> = {
  problem: 0, missed: 0, rejected: 0, due: 1, waiting: 2, planned: 3, queued: 3, sent: 4,
  partial: 5, cancelled: 6, held: 6, filled: 7,
}

// The board's word for an order is the paper account's action (BUY, SELL,
// TRIM; HOLD for a kept position). What has happened to it (sent, filled,
// cancelled) is the status column's job and the size's basis label, so a
// finished order keeps its word, greyed, and never reads as a new instruction.
export const orderWord = (order: DeskPaperOrder): BoardWord => {
  if (order.state === 'held') return 'HOLD'
  return order.action
}

// An order that is over: filled, cancelled, rejected or missed.
export const isDone = (order: DeskPaperOrder): boolean =>
  order.terminal === true || ['filled', 'cancelled', 'rejected', 'missed'].includes(order.state)

// Only unsubmitted plans can have a reference size; this is not a personal trade plan.
const canScale = (order: DeskPaperOrder) =>
  ['planned', 'waiting', 'due'].includes(order.state) && !order.sent_at && order.submitted_qty == null

// Show only outstanding paper price triggers, rounded exactly as the backend's timing text.
const decisionLevels = (row: BoardRow): string[] => [...new Set(row.orders
  .filter(order => !isDone(order) && canScale(order) && order.timing === 'dip_or_close'
    && typeof order.level === 'number' && Number.isFinite(order.level) && order.level > 0)
  .map(order => {
    const cents = order.level! * 100
    const rounded = (order.side === 'buy' ? Math.floor(cents + 1e-6) : Math.ceil(cents - 1e-6)) / 100
    return `${order.side === 'buy' ? 'Buy ≤' : 'Sell ≥'} ${price(rounded)}`
  }))]

// Label the quantity basis, including older API responses without the new field.
export const quantityLabel = (order: DeskPaperOrder): string =>
  order.quantity_basis ?? (order.state === 'filled' ? 'filled' : ['sent', 'queued', 'partial'].includes(order.state) ? 'submitted' : 'planned')

// Aggregate only like order states; mixed outcomes stay visibly separate.
const wordOf = (orders: DeskPaperOrder[]): BoardWord => {
  const words = [...new Set(orders.map(orderWord))]
  if (words.length === 1) return words[0]
  return 'ORDERS'
}

// Several filled orders on one name as one fill: the shares together at their
// average price, at the time of the last one.
const filledTogether = (orders: DeskPaperOrder[]): string => {
  const qty = orders.reduce((sum, o) => sum + (o.filled_qty ?? o.qty), 0)
  const cost = orders.reduce((sum, o) => sum + (o.filled_qty ?? o.qty) * (o.filled_price ?? 0), 0)
  const last = orders.map(o => o.filled_at ?? '').sort().pop()
  const at = last && Number.isFinite(Date.parse(last))
    ? new Date(last).toLocaleTimeString('en-US', {timeZone: 'America/New_York', hour: 'numeric', minute: '2-digit'}) : null
  const verb = orders[0].side === 'buy' ? 'Bought' : 'Sold'
  return `${verb} ${qty.toLocaleString('en-US')}${cost > 0 ? ` @ ${price(cost / qty)} avg` : ''}${at ? ` · ${at}` : ''}`
}

// Compare holdings with saved targets without turning a missing order into a future trade promise.
export const holdReason = (weight: number | null, target: number | null): string => {
  if (target === null) return 'Saved target unavailable · no recorded order'
  if (target <= 0) return 'Saved target 0.0% · no recorded order'
  if (weight === null) return `Saved target ${percent(target)} · no recorded order`
  const gap = weight - target
  if (Math.abs(gap) < 0.01) return `Near its saved ${percent(target)} target · no recorded order`
  return `${gap > 0 ? 'Above' : 'Below'} its saved ${percent(target)} target · no recorded order`
}

// Build recorded account rows, excluding settled orders when the caller needs current actions only.
// Names come from grades, saved targets, current holdings and the retained orders.
export const boardRows = (latest: DeskRecord, paper: DeskPaperLive | null | undefined, currentOnly = false): BoardRow[] => {
  const equity = paper?.equity && paper.equity > 0 ? paper.equity : null
  const orders = (paper?.plan?.orders ?? []).filter(order => !currentOnly || !isDone(order))
  const positions = paper?.positions ?? []
  const targets = latest.targets?.weights ?? {}
  const learned = learnedAllocation(latest)
  const gradeLed = latest.targets?.policy === 'grade-led-learned-sizing/1'
  const evidence = latest.paper?.joint_funded
  const eventAllocation = learned && evidence?.policy === latest.targets?.policy && evidence?.status === 'event_priority'
  const receipt = evidence?.policy === latest.targets?.policy && evidence?.as_of === latest.session ? evidence.receipt : undefined
  const retained = receipt?.transition?.retained_weights ?? {}
  const blocked = new Set((latest.actions ?? []).filter(a => (a as {rejecting_band?: boolean}).rejecting_band).map(a => a.ticker))
  const names = [...new Set([...Object.keys(latest.grades), ...Object.keys(targets), ...positions.map(p => p.symbol), ...orders.map(o => o.symbol)])]
  return names.map(ticker => {
    const mine = orders.filter(o => o.symbol === ticker)
    const position = positions.find(p => p.symbol === ticker)
    const held = position ? position.qty : 0
    const heldValue = position ? position.market_value : null
    const heldWeight = heldValue !== null && equity ? heldValue / equity : null
    const recordedTarget = targets[ticker]
    const target = typeof recordedTarget === 'number' && Number.isFinite(recordedTarget) && recordedTarget >= 0 && recordedTarget <= 1
      ? recordedTarget : !learned && !(ticker in targets) && ticker in latest.grades ? 0 : null
    const allocation = !learned ? 'recorded' : eventAllocation ? 'event' : ticker in retained ? 'retained'
      : receipt?.status === 'available' && target !== null ? 'modeled' : 'unavailable'
    const allocationNote = !learned ? `Recorded target · ${latest.session}`
      : allocation === 'event' ? 'FOMC allocation · recorded event policy takes priority over model targets'
      : allocation === 'retained' ? 'Retained holding · risk unavailable; target preserves existing capital'
      : allocation === 'modeled' ? `${gradeLed ? 'Grade-led allocation' : 'Model allocation'} · ${latest.session}; cash and costs included`
      : 'Model allocation unavailable · recorded target is not a fresh recommendation'
    const grade = latest.grades[ticker]?.grade ?? ''
    const signalRow = latest.actions?.find(row => row.ticker === ticker)
    const signal = currentOnly ? (
      grade === 'A' || grade === 'A+' ? held > 0 ? 'hold' : 'buy'
      : grade === 'B' || grade === 'C' ? held > 0 ? 'sell' : 'avoid' : 'unavailable'
    ) : undefined
    const signalReason = !currentOnly ? undefined : signalRow?.signal_reason ??
      `Grade ${grade || 'unavailable'} · ${latest.session}; ${latest.targets?.policy === 'grade-led-learned-sizing/1' ? 'no executable order' : 'awaiting a fresh grade-led sizing plan'}`
    const lead = [...mine].sort((a, b) => (PROGRESS[a.state] ?? 9) - (PROGRESS[b.state] ?? 9))[0]
    const combined = new Set(mine.map(o => `${o.side}:${o.state}:${quantityLabel(o)}`)).size <= 1
    const status = !lead ? '' : mine.length < 2 ? lead.status
      : combined && mine.every(o => o.state === 'filled') ? filledTogether(mine)
      : mine.every(o => o.state === lead.state) ? lead.status
      : `${lead.status} · ${mine.filter(o => o.state === 'filled').length} of ${mine.length} orders filled`
    const qty = mine.reduce((sum, o) => sum + o.qty, 0)
    const notional = combined && mine.length && mine.every(o => o.notional !== null) ? mine.reduce((sum, o) => sum + (o.notional ?? 0), 0) : null
    const word: BoardWord = mine.length ? wordOf(mine) : signal === 'buy' ? 'BUY' : signal === 'sell' ? 'SELL' : held > 0 ? 'HOLD' : '—'
    const done = mine.length > 0 && mine.every(isDone)
    const why = mine.length
      ? [...new Set(mine.map(o => o.why))].join(' + ')
      : allocation === 'retained' ? allocationNote
      : allocation === 'event' ? `${allocationNote} · no recorded order`
      : learned && allocation === 'unavailable' ? allocationNote
      : learned && target === 0 ? 'Model target 0.0% · no recorded order'
      : held > 0 ? holdReason(heldWeight, target)
      : learned ? target === null ? 'Target unavailable · no recorded order' : `Model target ${percent(target)} · no recorded order`
      : target && target > 0 ? blocked.has(ticker) ? 'In the book · no buy while its daily rejects the upper band' : `In the book at ${percent(target)} · no order tonight`
      : grade ? `Not in the book (grade ${grade})` : 'Not graded'
    return {
      ticker, grade, word, done, why, orders: mine, qty, notional, combined,
      sizeLabel: mine.length && combined ? quantityLabel(mine[0]) : '',
      weight: notional !== null && equity ? notional / equity : null,
      held, heldValue, heldWeight,
      avgCost: position?.avg_entry_price ?? null,
      unrealized: position ? position.unrealized_pl : null,
      target, allocation, allocationNote,
      status: status || (signal === 'buy' || signal === 'sell' ? `Signal only · ${signalReason}` : ''),
      signal, signalReason,
      state: lead?.state ?? '',
      when: lead?.when ?? '',
    }
  })
}

// Find sized, unsubmitted actions; completed fills are never new instructions.
const pendingActions = (row: BoardRow): DeskPaperOrder[] =>
  row.orders.filter(order => !isDone(order) && canScale(order)
      && Number.isFinite(order.qty) && order.qty > 0
      && typeof order.notional === 'number' && Number.isFinite(order.notional) && order.notional > 0)

// Give both sides the same readiness priority, with exceptions ahead of normal actions.
const band = (row: BoardRow): number => {
  if (!row.orders.length && (row.signal === 'buy' || row.signal === 'sell')) return 3
  if (!row.orders.length) return row.held > 0 || (row.target ?? 0) > 0 ? 5 : 6
  if (['problem', 'missed', 'rejected'].includes(row.state)) return 0
  const actions = pendingActions(row)
  if (actions.some(order => order.state === 'due')) return 1
  if (actions.length) return 2
  return row.orders.every(order => isDone(order) || order.state === 'held') ? 4 : 3
}

// Rank order readiness first, then visible grade signals without fabricating their size.
const ranked = (rows: BoardRow[]) => [...rows].sort((a, b) => {
  const stage = band(a), other = band(b)
  if (stage !== other) return stage - other
  if (stage === 1 || stage === 2) {
    const size = pendingActions(b).reduce((sum, order) => sum + order.notional!, 0)
      - pendingActions(a).reduce((sum, order) => sum + order.notional!, 0)
    return size || (b.target ?? -1) - (a.target ?? -1) || a.ticker.localeCompare(b.ticker)
  }
  const support = {modeled: 0, recorded: 0, event: 0, retained: 1, unavailable: 2}
  return support[a.allocation] - support[b.allocation]
    || (b.target ?? -1) - (a.target ?? -1)
    || (b.notional ?? 0) - (a.notional ?? 0)
    || (b.heldWeight ?? 0) - (a.heldWeight ?? 0)
    || a.ticker.localeCompare(b.ticker)
})

// A proportional reference size only; it does not know personal holdings or cash.
const myShares = (weight: number | null, myAccount: number | null, unit: number | null) =>
  weight !== null && myAccount && unit && unit > 0 ? Math.floor(weight * myAccount / unit) : null

// A column heading that sorts, saying which way.
const Head = ({label, column, sort, onSort, title}: {label: string; column?: SortKey; sort: {key: SortKey; down: boolean} | null; onSort: (key: SortKey) => void; title?: string}) => {
  if (!column) return <th className="py-2 font-normal" title={title}>{label}</th>
  const active = sort?.key === column
  return <th className="py-2 font-normal" aria-sort={!active ? 'none' : sort!.down ? 'descending' : 'ascending'}>
    <button type="button" title={title} className="flex items-center gap-1 hover:text-[#0071e3]" onClick={() => onSort(column)}>
      {label}<span aria-hidden="true" className={active ? 'text-[#0071e3]' : 'text-[#c7c7cc]'}>{!active ? '↕' : sort!.down ? '↓' : '↑'}</span>
    </button>
  </th>
}

// Share the Action heading's checkbox, dismissal and recovery workflow across account and simulation views.
export const ActionHead = ({open, onOpen, shown, onShown, rows = [], counts, title}: {open: boolean; onOpen: (value: boolean) => void; shown: ActionSelection; onShown: (value: ActionSelection) => void; rows?: BoardRow[]; counts?: Record<FilterAction, number>; title?: string}) => {
  const box = useRef<HTMLDivElement>(null)
  const button = useRef<HTMLButtonElement>(null)
  const filtered = FILTER_ACTIONS.some(action => !shown[action])
  // Dismiss an open menu without attaching permanent listeners to the page.
  useEffect(() => {
    if (!open) return
    // Close the menu when a reader clicks another part of the page.
    const away = (event: MouseEvent) => {if (box.current && !box.current.contains(event.target as Node)) onOpen(false)}
    // Restore keyboard focus to the heading when dismissing the filter.
    const key = (event: KeyboardEvent) => {if (event.key === 'Escape') {onOpen(false); button.current?.focus()}}
    document.addEventListener('mousedown', away)
    document.addEventListener('keydown', key)
    // Remove the temporary dismissal listeners when the menu closes.
    return () => {document.removeEventListener('mousedown', away); document.removeEventListener('keydown', key)}
  }, [open, onOpen])
  return <th className="py-2 font-normal"><div ref={box} className="relative">
    <button ref={button} type="button" aria-label="Action" aria-expanded={open} aria-haspopup="true"
      title={title ?? 'Click to filter BUY, SELL, TRIM, HOLD or names with no order. Mixed orders match each recorded action; completed orders remain history.'}
      className={filtered ? 'text-[#0071e3]' : 'hover:text-[#0071e3]'} onClick={() => onOpen(!open)}>Action <span aria-hidden="true">{filtered ? '•' : '▾'}</span></button>
    {open && <div role="group" aria-label="Show actions" className="absolute right-0 top-full z-20 mt-1 w-44 rounded-lg border border-black/[0.1] bg-white p-2 shadow-lg">
      {FILTER_ACTIONS.map(action => <label key={action} className="flex cursor-pointer items-center gap-2 rounded px-1 py-1 text-[#1d1d1f] hover:bg-[#f5f5f7]">
        <input type="checkbox" aria-label={`Show ${action === '—' ? 'No order' : action} rows`} checked={shown[action]} onChange={event => onShown({...shown, [action]: event.target.checked})} />
        <span className="flex-1">{action === '—' ? 'No order' : action}</span><span>{counts?.[action] ?? rows.filter(row => hasAction(row, action)).length}</span>
      </label>)}
      <button type="button" className="mt-1 px-1 py-1 text-[#0071e3]" onClick={() => onShown(ALL_ACTIONS)}>Show all</button>
    </div>}
  </div></th>
}

// The account's money and the day's orders in one line above the board.
const AccountStrip = ({paper, orders}: {paper: DeskPaperLive | null | undefined; orders: DeskPaperOrder[]}) => {
  if (!paper || paper.reason !== undefined || paper.equity === undefined) {
    return <p aria-label="Paper account summary" className="text-xs text-[#b25e00]">{paper?.reason ? `Paper account unavailable: ${paper.reason}` : 'Loading the paper account…'}</p>
  }
  const equity = paper.equity
  const cash = paper.cash ?? 0
  const buys = orders.filter(o => o.side === 'buy').length
  const sells = orders.length - buys
  const reset = paper.plan?.until_rebalance
  return <p aria-label="Paper account summary" className="flex flex-wrap gap-x-3 gap-y-1 text-xs text-[#6e6e73]">
    <span><span className="font-semibold text-[#1d1d1f]">{dollars(equity)}</span> paper account</span>
    <span>cash {dollars(cash)} ({percent(equity > 0 ? cash / equity : 0)})</span>
    {typeof paper.day_pl === 'number' && <span className={paper.day_pl >= 0 ? 'text-[#248a3d]' : 'text-[#b42318]'}>today {paper.day_pl >= 0 ? '+' : '−'}{dollars(Math.abs(paper.day_pl))}{typeof paper.day_pl_pct === 'number' ? ` (${paper.day_pl_pct >= 0 ? '+' : '−'}${Math.abs(paper.day_pl_pct * 100).toFixed(2)}%)` : ''}</span>}
    <span>{orders.length === 0 ? 'no orders' : `${orders.length} order${orders.length === 1 ? '' : 's'} (${buys} buy${buys === 1 ? '' : 's'}, ${sells} sell${sells === 1 ? '' : 's'})`}</span>
    {typeof reset === 'number' && <span>recorded reset {reset <= 1 ? 'next session' : `in ${reset} sessions`}</span>}
  </p>
}

// Show the same dated model observation beside an order on every dashboard surface.
export const RecordedModelDecision = ({order}: {order: DeskPaperOrder}) => {
  if (!order.learned_timing) return null
  const reading = order.learned_timing
  const at = Date.parse(reading.observed_at)
  return <p aria-label={`${order.symbol} recorded model decision`} className="text-[#6e6e73]">
    Model: {reading.state} · {Number.isFinite(at) ? `${new Date(at).toLocaleString('en-US', {timeZone: 'America/New_York'})} ET` : 'observation time unavailable'}
    {' · '}{reading.current ? 'current observation' : 'historical observation'}; not a fill
    {reading.reason && <span className="block">{reading.reason}</span>}
  </p>
}

// The details under a row: every order for the name with its own status, the
// position against its target, and why the desk grades it as it does.
const RowDetails = ({row, latest, myAccount, onOpen, extra, structure, displayed}: {row: BoardRow; latest: DeskRecord; myAccount: number | null; onOpen: (ticker: string) => void; extra?: ReactNode; structure?: DeskStructure; displayed: ReturnType<typeof displayedBoardPrice>}) => {
  const grade = latest.grades[row.ticker]
  const references = levelLines(structure, displayed?.price ?? null)
  const flag = levelFlag(structure)
  return <div aria-label={`${row.ticker} details`} className="grid gap-3 text-xs sm:grid-cols-3">
    <section aria-label={`${row.ticker} orders`}>
      <h4 className="font-medium text-[#6e6e73]">{row.orders.length ? `Order${row.orders.length > 1 ? 's' : ''}` : 'No order'}</h4>
      <p aria-label={`${row.ticker} action status`}>{row.why}</p>
      {row.orders.map(order => {
        const mine = canScale(order) ? myShares(order.weight, myAccount, order.price) : null
        const word = orderWord(order)
        return <div key={order.client_order_id} className="mb-2">
          <p><span className={`font-semibold ${isDone(order) ? 'text-[#6e6e73]' : WORD_STYLE[word]}`}>{word}</span> {shares(order.qty)} {quantityLabel(order)}{order.notional !== null ? ` · ${dollars(order.notional)}` : ''}{order.weight !== null ? ` · ${percent(order.weight)} of current equity` : ''}{mine !== null ? ` · ref. ${shares(mine)}` : ''}</p>
          {order.planned_qty !== undefined && order.planned_qty !== order.qty && <p className="text-[#6e6e73]">Originally planned: {shares(order.planned_qty)}</p>}
          {row.orders.length > 1 && <p className="text-[#6e6e73]">{order.why}</p>}
          <p><span className={`mr-1 inline-block h-2 w-2 rounded-full ${STATE_DOT[order.state] ?? 'bg-[#86868b]'}`} aria-hidden="true" />{order.status}</p>
          <p className="text-[#6e6e73]">{order.when}</p>
          <RecordedModelDecision order={order} />
        </div>
      })}
    </section>
    <section aria-label={`${row.ticker} position`}>
      <h4 className="font-medium text-[#6e6e73]">Paper position</h4>
      {row.held > 0 ? <>
        <p>{shares(row.held)}{row.heldValue !== null ? ` · ${dollars(row.heldValue)}` : ''}{row.heldWeight !== null ? ` · ${percent(row.heldWeight)}` : ''}</p>
        {row.avgCost !== null && <p className="text-[#6e6e73]">average cost {price(row.avgCost)}{row.unrealized !== null ? <> · <span className={row.unrealized >= 0 ? 'text-[#248a3d]' : 'text-[#b42318]'}>{row.unrealized >= 0 ? '+' : '−'}{dollars(Math.abs(row.unrealized))}</span> unrealized</> : ''}</p>}
      </> : <p>Not held</p>}
      <p className="text-[#6e6e73]">{savedTargetText(row, latest.session)} ({latest.targets?.policy ?? 'policy not recorded'})</p>
      <p aria-label={`${row.ticker} allocation basis`} className="text-[#6e6e73]">{row.allocationNote}</p>
      <div aria-label={`${row.ticker} reference levels`} title={levelDescription(row.ticker, structure, displayed)} className="mt-2 text-[#6e6e73]">
        <h4 className="font-medium">Technical references</h4>
        {references.length ? references.map(line => <p key={line}>{line}</p>) : <p>—</p>}
        {flag && <p aria-label={`${row.ticker} level flag`}>{flag}</p>}
      </div>
    </section>
    <section aria-label={`${row.ticker} grade`}>
      <h4 className="font-medium text-[#6e6e73]">Grade {row.grade || '—'} <span className="font-normal">· {latest.session} close</span></h4>
      {grade?.headline && <p>{grade.headline}</p>}
      {grade?.reason && <p className="mt-1 whitespace-pre-line text-[#6e6e73]">{grade.reason}</p>}
      <button type="button" className="mt-2 text-[#0071e3] hover:underline" onClick={() => onOpen(row.ticker)}>Chart and full history</button>
      {extra}
    </section>
  </div>
}

// Show current actions on the main stock list, retaining completed orders only in the account view.
export const TradeBoard = ({latest, live, paper, now, onOpen, closes, paused = false, currentOnly = false, extra, footer}: {
  latest: DeskRecord
  live: DeskLive
  paper: DeskPaperLive | null | undefined
  now: number
  onOpen: (ticker: string) => void
  closes?: Record<string, number | null>
  paused?: boolean
  currentOnly?: boolean
  extra?: (ticker: string) => ReactNode
  footer?: ReactNode
}) => {
  // Open the current overview on all stocks; the account view starts with its portfolio.
  const [chosen, setView] = useState<View | null>(null)
  const [query, setQuery] = useState('')
  const [shownActions, setShownActions] = useState<ActionSelection>(ALL_ACTIONS)
  const [actionMenu, setActionMenu] = useState(false)
  const [sort, setSort] = useState<{key: SortKey; down: boolean} | null>(null)
  const [opened, setOpened] = useState<string | null>(null)
  const [visible, setVisible] = useState(25)
  const [myAccount, setMyAccount] = useState<number | null>(readMyAccount)
  const [draft, setDraft] = useState(() => (readMyAccount() ?? '').toString())
  useEffect(() => { setVisible(25) }, [chosen, query, shownActions])
  const rows = useMemo(() => currentOnly
    ? rankCurrent(boardRows(latest, paper, true), live, latest.session, now, paper?.reason === undefined && paper?.equity !== undefined)
    : ranked(boardRows(latest, paper, false)), [latest, paper, currentOnly, live, now])
  const assessments = currentOnly ? currentAssessments(live, latest.session, now) : {}
  const orders = (paper?.plan?.orders ?? []).filter(order => !currentOnly || !isDone(order))
  const counts = {
    orders: rows.filter(r => r.orders.length > 0).length,
    portfolio: rows.filter(r => r.orders.length > 0 || r.held > 0).length,
    all: rows.length,
  }
  const view: View = chosen ?? (currentOnly ? 'all' : counts.portfolio > 0 ? 'portfolio' : 'all')
  const search = query.trim().toUpperCase()
  const inView = rows.filter(r => search ? r.ticker.includes(search)
    : view === 'orders' ? r.orders.length > 0
    : view === 'portfolio' ? r.orders.length > 0 || r.held > 0
    : true)
  const measure = (row: BoardRow, key: SortKey): number | string =>
    key === 'ticker' ? row.ticker
    : key === 'grade' ? GRADE_RANK[assessments[row.ticker]?.grade_live ?? row.grade] ?? -1
    : key === 'position' ? row.heldWeight ?? -1
    : row.notional ?? -1
  const allSelected = FILTER_ACTIONS.every(action => shownActions[action])
  const filtered = allSelected ? inView : inView.filter(row => FILTER_ACTIONS.some(action => shownActions[action] && hasAction(row, action)))
  const shown = !sort ? filtered : [...filtered].sort((a, b) => {
    const left = measure(a, sort.key), right = measure(b, sort.key)
    const order = typeof left === 'string' ? left.localeCompare(right as string) : left - (right as number)
    return sort.down ? -order : order
  })
  const onSort = (key: SortKey) => setSort(current =>
    current?.key !== key ? {key, down: key !== 'ticker'} : current.down === (key !== 'ticker') ? {key, down: !current.down} : null)
  const ruleText = executionRuleText(paper?.plan)
  return <section aria-label="Stocks and cash" className="flex min-h-0 flex-1 flex-col overflow-hidden rounded-2xl border border-black/[0.08] bg-white [container-type:inline-size]">
    <div className="shrink-0 space-y-2 border-b border-black/[0.06] px-3 py-2">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h3 className="text-sm font-semibold text-[#1d1d1f]">Stock rankings <span className="font-normal text-[#6e6e73]">{currentOnly ? '· current opportunities' : '· the paper account’s orders'}</span></h3>
        <label className="flex items-center gap-1 text-xs text-[#6e6e73]" title="Scales unsent plans only. Does not check your holdings or available cash. Kept in this browser only.">
          Reference account $
          <input aria-label="Reference account size" inputMode="decimal" value={draft} placeholder="optional"
            onChange={e => setDraft(e.target.value)}
            onBlur={() => { const value = Number(draft.replace(/[,$\s]/g, '')); const next = Number.isFinite(value) && value > 0 ? value : null; setMyAccount(next); writeMyAccount(next); setDraft(next ? String(next) : '') }}
            onKeyDown={e => { if (e.key === 'Enter') (e.target as HTMLInputElement).blur() }}
            className="w-24 rounded-md border border-black/[0.08] bg-white px-2 py-0.5 text-right text-[#1d1d1f]" />
        </label>
      </div>
      <p aria-label="Allocation record" title={`Saved policy: ${latest.targets?.policy ?? 'not recorded'}`} className="text-[11px] text-[#6e6e73]">{currentOnly ? `Assessments refresh on completed 15-minute candles. Targets and order signals saved ${latest.session}; prices and order status refresh live.` : `Saved allocation · ${latest.session}. These are the saved plan's targets, not new orders. Live holdings can differ.`}</p>
      {currentOnly && <p aria-label="Chart judgment coverage" className="text-[11px] text-[#6e6e73]">Current chart judgments: {rows.filter(row => row.currentSetup).length} of {rows.length} names{live.opportunities?.unavailable && Object.keys(live.opportunities.unavailable).length > 0 ? ` · ${Object.keys(live.opportunities.unavailable).length} missing complete candle evidence` : ''}{live.opportunities?.status === 'building' || live.opportunities?.status === 'pending' ? ' · updating' : ''}. Expired evidence cannot produce a buy signal.</p>}
      <AccountStrip paper={paper} orders={orders} />
      {paused && <p role="status" aria-label="Trading restriction" className="text-xs text-[#b25e00]">FOMC cycle: the paper account follows the FOMC risk rule; its orders say when.</p>}
      <details aria-label="Order rules" className="text-xs text-[#6e6e73]">
        <summary className="cursor-pointer">Order rules</summary>
        <p aria-label="Execution rule">{paused ? 'FOMC cycle: the paper account follows the FOMC risk rule; its orders say when. ' : ''}{ruleText} Paper order status is shown below; submitted or completed orders are not new trade instructions.</p>
        <p aria-label="Ranking basis">{rankingText}</p>
      </details>
      {myAccount !== null && <p className="text-xs text-[#6e6e73]">Reference sizes are proportional examples for unsent plans, not adjusted for your holdings or cash.</p>}
      {paper?.plan?.reason && <p className="text-xs text-[#b25e00]">{paper.plan.reason}; statuses may lag.</p>}
      <div className="flex flex-wrap items-center gap-2">
        <div role="group" aria-label="Board view" className="flex gap-1 text-xs">
          {([['orders', 'Orders'], ['portfolio', 'Portfolio'], ['all', 'All names']] as const).map(([value, label]) =>
            <button key={value} type="button" aria-pressed={view === value} onClick={() => setView(value)}
              className={`rounded-full px-2.5 py-0.5 ${view === value ? 'bg-[#1d1d1f] text-white' : 'bg-[#f5f5f7] text-[#6e6e73] hover:text-[#0071e3]'}`}>
              {label} <span className="tabular-nums">{counts[value]}</span>
            </button>)}
        </div>
        <button type="button" aria-pressed={sort === null} onClick={() => setSort(null)}
          title={`Restores automatic ranking after column sorting. ${rankingText}${currentOnly ? '' : ' Filled orders are history.'}`}
          className={`rounded-md px-2 py-0.5 text-xs ${sort === null ? 'bg-[#e8f2ff] text-[#0071e3]' : 'text-[#6e6e73] hover:text-[#0071e3]'}`}>Reset ranking</button>
        {FILTER_ACTIONS.some(action => !shownActions[action]) && <button type="button" className="px-2 py-0.5 text-xs text-[#0071e3]" onClick={() => setShownActions(ALL_ACTIONS)}>Show all actions</button>}
        <input type="search" value={query} onChange={e => setQuery(e.target.value)} placeholder="Search a ticker" aria-label="Search the stock list"
          className="w-full max-w-44 rounded-md border border-black/[0.08] bg-white px-2 py-0.5 text-sm text-[#1d1d1f]" />
      </div>
    </div>
    <div className={`min-h-0 flex-1 overflow-auto ${actionMenu ? 'min-h-64' : ''}`}>
      <table className="w-full min-w-max text-left text-sm tabular-nums [&_td]:px-2 [&_th]:px-2" aria-label="Ranked stocks and cash">
        <thead className="sticky top-0 z-10 bg-[#f5f5f7] text-xs text-[#6e6e73]">
          <tr>
            <th className="w-7 py-2"><span className="sr-only">Details</span></th>
            <Head label="Stock" column="ticker" sort={sort} onSort={onSort} />
            <Head label="Grade" column="grade" sort={sort} onSort={onSort} title="The recorded analyst grade; allocation and orders come from the selected policy. Click to sort by grade." />
            <Head label="Position" column="position" sort={sort} onSort={onSort} title="Live paper holdings and share of the account. Saved targets belong to the dated allocation record; they are not new orders." />
            <Head label="Levels" sort={sort} onSort={onSort} title="Outstanding paper order triggers, tested on completed 15-minute closes. Technical references are in stock details. Not guaranteed fill prices." />
            <ActionHead open={actionMenu} onOpen={setActionMenu} shown={shownActions} onShown={setShownActions} rows={inView} title={currentOnly ? 'Current recorded paper-account actions. HOLD means no current order; No order means the account does not hold or trade the stock.' : undefined} />
            <Head label="Size" column="size" sort={sort} onSort={onSort} title={currentOnly ? 'Current planned or submitted shares. Dollars use the recorded price estimate; percentages use current paper equity.' : 'Planned or submitted sizes use a price estimate; filled sizes use execution prices. Percentages use current paper equity.'} />
            <Head label="When / status" sort={sort} onSort={onSort} title="The order's rule for its session and what has happened to it." />
          </tr>
        </thead>
        <tbody>{shown.slice(0, visible).map(row => {
          const open = opened === row.ticker
          const unit = row.orders[0]?.price ?? live.quotes[row.ticker]?.last ?? null
          const mine = row.orders.length && row.orders.every(canScale) ? myShares(row.weight, myAccount, unit) : null
          const structure = live.structure?.[row.ticker]
          const displayed = displayedBoardPrice(live, row.ticker, now, closes?.[row.ticker], latest.session)
          const levels = decisionLevels(row)
          const age = priceAge(structure, now)
          const assessedGrade = assessments[row.ticker]?.grade_live ?? row.grade
          return <Fragment key={row.ticker}>
            <tr className="border-t border-black/[0.05] align-top">
              <td className="py-2 text-xs"><button type="button" aria-label={`details for ${row.ticker}`} aria-expanded={open} className="w-5 text-[#0071e3]" onClick={() => setOpened(open ? null : row.ticker)}>{open ? '▾' : '▸'}</button></td>
              <td className="py-2">
                <button type="button" className="font-semibold text-[#1d1d1f] hover:text-[#0071e3]" onClick={() => onOpen(row.ticker)}>{row.ticker}</button>
                <div className="text-[11px] text-[#6e6e73]"><SessionPrice live={live} ticker={row.ticker} now={now} compact close={closes?.[row.ticker]} closeSession={latest.session} /></div>
                {age && <div aria-label={`${row.ticker} price age`} title="Completed regular-session bar used by the strategy; the displayed quote has its own timestamp." className="whitespace-nowrap text-[10px] text-[#86868b]">{age}</div>}
              </td>
              <td className="py-2 text-xs" aria-label={`${row.ticker} displayed grade`}>
                <span className={`font-semibold ${assessedGrade === 'A+' || assessedGrade === 'A' ? 'text-[#248a3d]' : assessedGrade === 'C' ? 'text-[#b42318]' : 'text-[#6e6e73]'}`}>{assessedGrade || '—'}</span>
                {currentOnly && <div className="text-[10px] text-[#6e6e73]">{assessments[row.ticker] ? 'intraday assessment' : `${latest.session} close · fresh assessment unavailable`}</div>}
              </td>
              <td className="py-2 text-xs" aria-label={`${row.ticker} position`}>
                {row.held > 0 ? <>{shares(row.held)}{row.heldWeight !== null ? ` · ${percent(row.heldWeight)}` : ''}</> : <span className="text-[#86868b]">none</span>}
                {row.target !== null && <div className="text-[10px] text-[#6e6e73]" title={latest.targets?.policy ?? 'Policy not recorded'}>{savedTargetText(row, latest.session)}</div>}
              </td>
              <td className="py-2 text-[11px]" aria-label={`${row.ticker} levels`} title={levels.length ? `${row.ticker}: outstanding paper trigger on a completed 15-minute close; not a limit order or predicted support. ${row.when}` : `${row.ticker}: no outstanding price trigger. Technical references are in details.`}>
                {levels.length ? levels.map(line => <div key={line} className="whitespace-nowrap text-[#6e6e73]">{line}</div>) : <span className="text-[#86868b]">—</span>}
              </td>
              <td className="py-2 text-xs" title={row.why}>
                <span aria-label={`${row.ticker} strategy intent`} className={`font-semibold ${row.done ? 'text-[#6e6e73]' : WORD_STYLE[row.word]}`}>{row.word}</span>
                {row.signal && <div aria-label={`${row.ticker} grade signal`} className="text-[10px] text-[#6e6e73]">{currentOnly ? row.orders.length ? 'Outstanding paper order' : 'Current signal' : 'Grade signal'}: {row.signal.toUpperCase()}{currentOnly ? '' : ` · ${latest.session}`}{row.orders.length ? '' : ' · no order'}</div>}
                {assessments[row.ticker] && <div aria-label={`${row.ticker} current assessment`} className="text-[10px] text-[#6e6e73]">Now: {assessmentPermission(assessments[row.ticker].grade_live)}</div>}
                {currentOnly && row.currentSetup && <div aria-label={`${row.ticker} chart judgment`} className="mt-1 max-w-64 text-[11px] text-[#1d1d1f]">Completed candle: {row.currentSetup.reason}<div aria-label={`${row.ticker} latest quote check`} className="text-[#0071e3]">{quoteReferenceText(live, row.ticker, row.currentSetup, now)}</div><div className="text-[#6e6e73]">{confirmationText(row.currentSetup)}</div><div className="text-[#6e6e73]">{invalidationText(row.currentSetup)}</div><div className="text-[10px] text-[#6e6e73]">Candle {new Date(row.currentSetup.bar).toLocaleTimeString('en-US', {timeZone: 'America/New_York', hour: 'numeric', minute: '2-digit'})} ET · model judgment</div></div>}
              </td>
              <td className="py-2 text-xs" aria-label={`${row.ticker} size`}>
                {row.orders.length ? <>
                  <span className="font-medium text-[#1d1d1f]">{row.combined ? `${shares(row.qty)} ${row.sizeLabel}` : `${row.orders.length} orders · see details`}</span>
                  <div className="text-[10px] text-[#6e6e73]">{row.notional !== null ? dollars(row.notional) : ''}{row.weight !== null ? ` · ${percent(row.weight)}` : ''}</div>
                  {mine !== null && <div className="text-[10px] text-[#0071e3]">ref. {shares(mine)}</div>}
                </> : '—'}
              </td>
              <td className="max-w-72 whitespace-normal py-2 text-xs" aria-label={`${row.ticker} order status`}>
                {row.status ? <>
                  <span className={`mr-1 inline-block h-2 w-2 rounded-full ${STATE_DOT[row.state] ?? 'bg-[#86868b]'}`} aria-hidden="true" />{row.status}
                  <div className="text-[10px] text-[#6e6e73]">{row.when}</div>
                </> : <span className="text-[#86868b]">—</span>}
              </td>
            </tr>
            {open && <tr><td colSpan={8} className="border-t border-black/[0.05] bg-[#f0f7ff] px-3 py-2"><div className="w-[calc(100cqw-1.5rem)] whitespace-normal">
              <RowDetails row={row} latest={latest} myAccount={myAccount} onOpen={onOpen} extra={extra?.(row.ticker)} structure={structure} displayed={displayed} />
            </div></td></tr>}
          </Fragment>
        })}</tbody>
      </table>
      {shown.length === 0 && <p role="status" className="border-t border-black/[0.05] px-3 py-2 text-xs text-[#6e6e73]">{!allSelected ? 'No stocks match this view and the selected actions.' : search ? `No name matches “${query}”.` : view === 'orders' ? 'No orders for the paper account right now.' : 'Nothing to show.'}</p>}
      {shown.length > visible && <button type="button" className="w-full border-t border-black/[0.05] px-3 py-2 text-left text-xs text-[#0071e3]" onClick={() => setVisible(v => v + 25)}>Show more · {Math.min(shown.length, visible + 25)} of {shown.length} names</button>}
      {footer}
    </div>
  </section>
}
