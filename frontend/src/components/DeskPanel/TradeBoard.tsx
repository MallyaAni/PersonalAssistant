import { Fragment, useEffect, useMemo, useState, type ReactNode } from 'react'
import type { DeskLevelTag, DeskLive, DeskPaperLive, DeskPaperOrder, DeskRecord, DeskStructure } from '../../services/api'
import { SessionPrice } from './StockBoard'

// The Stock rankings board, rebuilt around one question a trader asks of it:
// what is the paper account doing about each name, how big, and when.
//
// Every action on this board is the paper account's own order, read from
// `/desk/paper` (`plan.orders`), and the paper account sends exactly those
// orders on exactly the rule the board prints: a buy on a 15-minute close 1%
// under the day's open, a sell 1% over it, otherwise market-on-close from the
// 3:30 PM window. The wording of each order (why, when, what happened) comes
// from the backend in one place, so this board, the ticker panel and the
// chart cannot tell different stories. A name with no order is HOLD when the
// account holds it and a dash when it does not.
//
// The Levels column is the structure the desk does not act on (S0 of the
// trading scenarios): the 21-EMA and the 20-day high from the balancer's
// `live.structure`, the distance to each, the EMA's slope, and a plain flag
// when the session's first bar rejected a level. The action cell also says
// how old the price behind the row is.

// The four words a row can say, and the dash for a name the account neither
// holds nor trades.
export type BoardWord = 'BUY' | 'SELL' | 'TRIM' | 'HOLD' | '—' | 'BOUGHT' | 'SOLD' | 'TRIMMED' | 'CANCELLED' | 'REJECTED' | 'MISSED' | 'NOT SENT' | 'BUY SENT' | 'SELL SENT' | 'PART FILLED' | 'ORDERS'

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
  status: string
  state: string
  when: string
}

// The views a trader switches between: what the account is trading today,
// the whole portfolio (orders and holdings), and every graded name.
type View = 'orders' | 'portfolio' | 'all'
type SortKey = 'ticker' | 'grade' | 'position' | 'size'

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
  SELL: 'text-[#b42318]',
  TRIM: 'text-[#b25e00]',
  HOLD: 'text-[#6e6e73]',
  BOUGHT: 'text-[#6e6e73]',
  SOLD: 'text-[#6e6e73]',
  TRIMMED: 'text-[#6e6e73]',
  CANCELLED: 'text-[#6e6e73]',
  REJECTED: 'text-[#b42318]',
  MISSED: 'text-[#b42318]',
  'NOT SENT': 'text-[#b42318]',
  'BUY SENT': 'text-[#0071e3]',
  'SELL SENT': 'text-[#0071e3]',
  'PART FILLED': 'text-[#b25e00]',
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

// Why a held name has no order, against its target: at it, above it (the reset
// trims it), below it (the reset or idle cash tops it up), or out of the book.
export const holdReason = (weight: number | null, target: number | null, untilReset: number | null): string => {
  const reset = untilReset === null ? 'the next reset' : untilReset <= 1 ? 'the next reset (next session)' : `the reset in ${untilReset} sessions`
  if (target === null || target <= 0) return 'Not in the book; no order tonight'
  if (weight === null) return `Target ${percent(target)}`
  const gap = weight - target
  if (Math.abs(gap) < 0.01) return `Near its ${percent(target)} target`
  return gap > 0
    ? `Above its ${percent(target)} target · trimmed at ${reset}`
    : `Below its ${percent(target)} target · topped up at ${reset}`
}

// Build every row the board can show from the record, the paper account and
// its orders. A name is on the board when the desk grades it, the account
// holds it, or an order names it.
export const boardRows = (latest: DeskRecord, paper: DeskPaperLive | null | undefined): BoardRow[] => {
  const equity = paper?.equity && paper.equity > 0 ? paper.equity : null
  const orders = paper?.plan?.orders ?? []
  const positions = paper?.positions ?? []
  const targets = latest.targets?.weights ?? {}
  const untilReset = paper?.plan?.until_rebalance ?? null
  const blocked = new Set((latest.actions ?? []).filter(a => (a as {rejecting_band?: boolean}).rejecting_band).map(a => a.ticker))
  const names = [...new Set([...Object.keys(latest.grades), ...positions.map(p => p.symbol), ...orders.map(o => o.symbol)])]
  return names.map(ticker => {
    const mine = orders.filter(o => o.symbol === ticker)
    const position = positions.find(p => p.symbol === ticker)
    const held = position ? position.qty : 0
    const heldValue = position ? position.market_value : null
    const heldWeight = heldValue !== null && equity ? heldValue / equity : null
    const target = ticker in targets ? targets[ticker] : ticker in latest.grades ? 0 : null
    const grade = latest.grades[ticker]?.grade ?? ''
    const lead = [...mine].sort((a, b) => (PROGRESS[a.state] ?? 9) - (PROGRESS[b.state] ?? 9))[0]
    const combined = new Set(mine.map(o => `${o.side}:${o.state}:${quantityLabel(o)}`)).size <= 1
    const status = !lead ? '' : mine.length < 2 ? lead.status
      : combined && mine.every(o => o.state === 'filled') ? filledTogether(mine)
      : mine.every(o => o.state === lead.state) ? lead.status
      : `${lead.status} · ${mine.filter(o => o.state === 'filled').length} of ${mine.length} orders filled`
    const qty = mine.reduce((sum, o) => sum + o.qty, 0)
    const notional = combined && mine.length && mine.every(o => o.notional !== null) ? mine.reduce((sum, o) => sum + (o.notional ?? 0), 0) : null
    const word: BoardWord = mine.length ? wordOf(mine) : held > 0 ? 'HOLD' : '—'
    const done = mine.length > 0 && mine.every(isDone)
    const why = mine.length
      ? [...new Set(mine.map(o => o.why))].join(' + ')
      : held > 0 ? holdReason(heldWeight, target, untilReset)
      : target && target > 0 ? blocked.has(ticker) ? 'In the book · no buy while its daily rejects the upper band' : `In the book at ${percent(target)} · no order tonight`
      : grade ? `Not in the book (grade ${grade})` : 'Not graded'
    return {
      ticker, grade, word, done, why, orders: mine, qty, notional, combined,
      sizeLabel: mine.length && combined ? quantityLabel(mine[0]) : '',
      weight: notional !== null && equity ? notional / equity : null,
      held, heldValue, heldWeight,
      avgCost: position?.avg_entry_price ?? null,
      unrealized: position ? position.unrealized_pl : null,
      target,
      status,
      state: lead?.state ?? '',
      when: lead?.when ?? '',
    }
  })
}

// Where a row sits in the default ranking: an order that needs attention,
// then orders still to happen, then orders done today, then holdings, then
// names the account neither holds nor trades.
const band = (row: BoardRow): number =>
  !row.orders.length ? row.word === 'HOLD' ? 3 : 4
  : ['problem', 'missed', 'rejected'].includes(row.state) ? 0
  : ['filled', 'held', 'cancelled'].includes(row.state) ? 2
  : 1

// The default ranking: by band, then the biggest order or holding first, then
// the grade and the ticker.
const ranked = (rows: BoardRow[]) => [...rows].sort((a, b) =>
  band(a) - band(b)
  || (b.notional ?? 0) - (a.notional ?? 0)
  || (b.heldWeight ?? 0) - (a.heldWeight ?? 0)
  || (GRADE_RANK[b.grade] ?? -1) - (GRADE_RANK[a.grade] ?? -1)
  || a.ticker.localeCompare(b.ticker))

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
    {typeof reset === 'number' && <span>reset {reset <= 1 ? 'next session' : `in ${reset} sessions`}</span>}
  </p>
}

// The details under a row: every order for the name with its own status, the
// position against its target, and why the desk grades it as it does.
const RowDetails = ({row, latest, myAccount, onOpen, extra}: {row: BoardRow; latest: DeskRecord; myAccount: number | null; onOpen: (ticker: string) => void; extra?: ReactNode}) => {
  const grade = latest.grades[row.ticker]
  return <div aria-label={`${row.ticker} details`} className="grid gap-3 text-xs sm:grid-cols-3">
    <section aria-label={`${row.ticker} orders`}>
      <h4 className="font-medium text-[#6e6e73]">{row.orders.length ? `Order${row.orders.length > 1 ? 's' : ''}` : 'No order'}</h4>
      {row.orders.length === 0 && <p>{row.why}</p>}
      {row.orders.map(order => {
        const mine = canScale(order) ? myShares(order.weight, myAccount, order.price) : null
        const word = orderWord(order)
        return <div key={order.client_order_id} className="mb-2">
          <p><span className={`font-semibold ${isDone(order) ? 'text-[#6e6e73]' : WORD_STYLE[word]}`}>{word}</span> {shares(order.qty)} {quantityLabel(order)}{order.notional !== null ? ` · ${dollars(order.notional)}` : ''}{order.weight !== null ? ` · ${percent(order.weight)} of current equity` : ''}{mine !== null ? ` · ref. ${shares(mine)}` : ''}</p>
          {order.planned_qty !== undefined && order.planned_qty !== order.qty && <p className="text-[#6e6e73]">Originally planned: {shares(order.planned_qty)}</p>}
          <p className="text-[#6e6e73]">{order.why}</p>
          <p><span className={`mr-1 inline-block h-2 w-2 rounded-full ${STATE_DOT[order.state] ?? 'bg-[#86868b]'}`} aria-hidden="true" />{order.status}</p>
          <p className="text-[#6e6e73]">{order.when}</p>
        </div>
      })}
    </section>
    <section aria-label={`${row.ticker} position`}>
      <h4 className="font-medium text-[#6e6e73]">Paper position</h4>
      {row.held > 0 ? <>
        <p>{shares(row.held)}{row.heldValue !== null ? ` · ${dollars(row.heldValue)}` : ''}{row.heldWeight !== null ? ` · ${percent(row.heldWeight)}` : ''}</p>
        {row.avgCost !== null && <p className="text-[#6e6e73]">average cost {price(row.avgCost)}{row.unrealized !== null ? <> · <span className={row.unrealized >= 0 ? 'text-[#248a3d]' : 'text-[#b42318]'}>{row.unrealized >= 0 ? '+' : '−'}{dollars(Math.abs(row.unrealized))}</span> unrealized</> : ''}</p>}
      </> : <p>Not held</p>}
      <p className="text-[#6e6e73]">Target {row.target !== null ? percent(row.target) : '—'} ({latest.targets?.policy ?? 'the active policy'})</p>
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

// The board. `extra` adds per-name content under a row's details (the fill
// recorder when the viewer can write), and `footer` sits under the list.
export const TradeBoard = ({latest, live, paper, now, onOpen, closes, paused = false, extra, footer}: {
  latest: DeskRecord
  live: DeskLive
  paper: DeskPaperLive | null | undefined
  now: number
  onOpen: (ticker: string) => void
  closes?: Record<string, number | null>
  paused?: boolean
  extra?: (ticker: string) => ReactNode
  footer?: ReactNode
}) => {
  // Until the viewer picks one, the board opens on the portfolio, or on every
  // graded name when the paper account holds and trades nothing (or cannot be read).
  const [chosen, setView] = useState<View | null>(null)
  const [query, setQuery] = useState('')
  const [sort, setSort] = useState<{key: SortKey; down: boolean} | null>(null)
  const [opened, setOpened] = useState<string | null>(null)
  const [visible, setVisible] = useState(25)
  const [myAccount, setMyAccount] = useState<number | null>(readMyAccount)
  const [draft, setDraft] = useState(() => (readMyAccount() ?? '').toString())
  useEffect(() => { setVisible(25) }, [chosen, query])
  const rows = useMemo(() => ranked(boardRows(latest, paper)), [latest, paper])
  const orders = paper?.plan?.orders ?? []
  const counts = {
    orders: rows.filter(r => r.orders.length > 0).length,
    portfolio: rows.filter(r => r.orders.length > 0 || r.held > 0).length,
    all: rows.length,
  }
  const view: View = chosen ?? (counts.portfolio > 0 ? 'portfolio' : 'all')
  const search = query.trim().toUpperCase()
  const inView = rows.filter(r => search ? r.ticker.includes(search)
    : view === 'orders' ? r.orders.length > 0
    : view === 'portfolio' ? r.orders.length > 0 || r.held > 0
    : true)
  const measure = (row: BoardRow, key: SortKey): number | string =>
    key === 'ticker' ? row.ticker
    : key === 'grade' ? GRADE_RANK[row.grade] ?? -1
    : key === 'position' ? row.heldWeight ?? -1
    : row.notional ?? -1
  const shown = !sort ? inView : [...inView].sort((a, b) => {
    const left = measure(a, sort.key), right = measure(b, sort.key)
    const order = typeof left === 'string' ? left.localeCompare(right as string) : left - (right as number)
    return sort.down ? -order : order
  })
  const onSort = (key: SortKey) => setSort(current =>
    current?.key !== key ? {key, down: key !== 'ticker'} : current.down === (key !== 'ticker') ? {key, down: !current.down} : null)
  const ruleText = paper?.plan?.rule === 'next_open'
    ? 'Buys go in at the next open and sells at the next close.'
    : 'Buys wait for a 15-minute close at least 1% under the day’s open; sells wait for one at least 1% over. Otherwise, market-on-close orders are due 30 minutes before the regular close; late orders use market execution before the close.'
  return <section aria-label="Stocks and cash" className="flex min-h-0 flex-1 flex-col overflow-hidden rounded-2xl border border-black/[0.08] bg-white [container-type:inline-size]">
    <div className="shrink-0 space-y-2 border-b border-black/[0.06] px-3 py-2">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h3 className="text-sm font-semibold text-[#1d1d1f]">Stock rankings <span className="font-normal text-[#6e6e73]">· the paper account’s orders</span></h3>
        <label className="flex items-center gap-1 text-xs text-[#6e6e73]" title="Scales unsent plans only. Does not check your holdings or available cash. Kept in this browser only.">
          Reference account $
          <input aria-label="Reference account size" inputMode="decimal" value={draft} placeholder="optional"
            onChange={e => setDraft(e.target.value)}
            onBlur={() => { const value = Number(draft.replace(/[,$\s]/g, '')); const next = Number.isFinite(value) && value > 0 ? value : null; setMyAccount(next); writeMyAccount(next); setDraft(next ? String(next) : '') }}
            onKeyDown={e => { if (e.key === 'Enter') (e.target as HTMLInputElement).blur() }}
            className="w-24 rounded-md border border-black/[0.08] bg-white px-2 py-0.5 text-right text-[#1d1d1f]" />
        </label>
      </div>
      <AccountStrip paper={paper} orders={orders} />
      <p aria-label="Execution rule" className="text-xs text-[#6e6e73]">{paused ? 'FOMC cycle: the paper account follows the FOMC risk rule; its orders say when. ' : ''}{ruleText} Paper order status is shown below; submitted or completed orders are not new trade instructions.</p>
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
        <input type="search" value={query} onChange={e => setQuery(e.target.value)} placeholder="Search a ticker" aria-label="Search the stock list"
          className="w-full max-w-44 rounded-md border border-black/[0.08] bg-white px-2 py-0.5 text-sm text-[#1d1d1f]" />
      </div>
    </div>
    <div className="min-h-0 flex-1 overflow-auto">
      <table className="w-full min-w-max text-left text-sm tabular-nums [&_td]:px-2 [&_th]:px-2" aria-label="Ranked stocks and cash">
        <thead className="sticky top-0 z-10 bg-[#f5f5f7] text-xs text-[#6e6e73]">
          <tr>
            <th className="w-7 py-2"><span className="sr-only">Details</span></th>
            <Head label="Stock" column="ticker" sort={sort} onSort={onSort} />
            <Head label="Grade" column="grade" sort={sort} onSort={onSort} title="The desk's grade at the last close; A and A+ are in the book." />
            <Head label="Position" column="position" sort={sort} onSort={onSort} title="Paper-account shares and share of the account, against the policy's target." />
            <Head label="Levels" sort={sort} onSort={onSort} title="The 21-session EMA and the 20-session high, with the distance from the last price and the EMA's five-session slope; a flag when the session's first 15-minute bar reached a level from below and closed back under it. Shown, not acted on." />
            <Head label="Action" sort={sort} onSort={onSort} title="The paper account's order for the name. HOLD: no order, the position stays. A finished order keeps its word, greyed; the status column says what happened to it." />
            <Head label="Size" column="size" sort={sort} onSort={onSort} title="Planned or submitted sizes use a price estimate; filled sizes use execution prices. Percentages use current paper equity." />
            <Head label="When / status" sort={sort} onSort={onSort} title="The order's rule for its session and what has happened to it." />
          </tr>
        </thead>
        <tbody>{shown.slice(0, visible).map(row => {
          const open = opened === row.ticker
          const unit = row.orders[0]?.price ?? live.quotes[row.ticker]?.last ?? null
          const mine = row.orders.length && row.orders.every(canScale) ? myShares(row.weight, myAccount, unit) : null
          const structure = live.structure?.[row.ticker]
          const levels = levelLines(structure, live.quotes[row.ticker]?.last ?? closes?.[row.ticker] ?? null)
          const flag = levelFlag(structure)
          const age = priceAge(structure, now)
          return <Fragment key={row.ticker}>
            <tr className="border-t border-black/[0.05] align-top">
              <td className="py-2 text-xs"><button type="button" aria-label={`details for ${row.ticker}`} aria-expanded={open} className="w-5 text-[#0071e3]" onClick={() => setOpened(open ? null : row.ticker)}>{open ? '▾' : '▸'}</button></td>
              <td className="py-2">
                <button type="button" className="font-semibold text-[#1d1d1f] hover:text-[#0071e3]" onClick={() => onOpen(row.ticker)}>{row.ticker}</button>
                <div className="text-[11px] text-[#6e6e73]"><SessionPrice live={live} ticker={row.ticker} now={now} compact close={closes?.[row.ticker]} closeSession={latest.session} /></div>
              </td>
              <td className="py-2 text-xs" aria-label={`${row.ticker} displayed grade`}><span className={`font-semibold ${row.grade === 'A+' || row.grade === 'A' ? 'text-[#248a3d]' : row.grade === 'C' ? 'text-[#b42318]' : 'text-[#6e6e73]'}`}>{row.grade || '—'}</span></td>
              <td className="py-2 text-xs" aria-label={`${row.ticker} position`}>
                {row.held > 0 ? <>{shares(row.held)}{row.heldWeight !== null ? ` · ${percent(row.heldWeight)}` : ''}</> : <span className="text-[#86868b]">none</span>}
                {row.target !== null && row.target > 0 && <div className="text-[10px] text-[#6e6e73]">target {percent(row.target)}</div>}
              </td>
              <td className="py-2 text-[11px]" aria-label={`${row.ticker} levels`}>
                {levels.length ? levels.map(line => <div key={line} className="whitespace-nowrap text-[#6e6e73]">{line}</div>) : <span className="text-[#86868b]">—</span>}
                {flag && <div aria-label={`${row.ticker} level flag`} className="whitespace-nowrap font-medium text-[#1d1d1f]">{flag}</div>}
              </td>
              <td className="max-w-56 py-2 text-xs">
                <span aria-label={`${row.ticker} strategy intent`} className={`font-semibold ${row.done ? 'text-[#6e6e73]' : WORD_STYLE[row.word]}`}>{row.word}</span>
                <div aria-label={`${row.ticker} action status`} className="whitespace-normal text-[10px] text-[#6e6e73]">{row.why}</div>
                {age && <div aria-label={`${row.ticker} price age`} className="whitespace-nowrap text-[10px] text-[#86868b]">{age}</div>}
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
              <RowDetails row={row} latest={latest} myAccount={myAccount} onOpen={onOpen} extra={extra?.(row.ticker)} />
            </div></td></tr>}
          </Fragment>
        })}</tbody>
      </table>
      {shown.length === 0 && <p className="border-t border-black/[0.05] px-3 py-2 text-xs text-[#6e6e73]">{search ? `No name matches “${query}”.` : view === 'orders' ? 'No orders for the paper account right now.' : 'Nothing to show.'}</p>}
      {shown.length > visible && <button type="button" className="w-full border-t border-black/[0.05] px-3 py-2 text-left text-xs text-[#0071e3]" onClick={() => setVisible(v => v + 25)}>Show more · {Math.min(shown.length, visible + 25)} of {shown.length} names</button>}
      {footer}
    </div>
  </section>
}
