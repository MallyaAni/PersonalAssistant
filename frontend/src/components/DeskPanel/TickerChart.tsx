import { useEffect, useMemo, useRef, useState } from 'react'
import {
  CandlestickSeries,
  CrosshairMode,
  LineSeries,
  LineStyle,
  TickMarkType,
  createChart,
  createSeriesMarkers,
  type IChartApi,
  type ISeriesApi,
  type ISeriesMarkersPluginApi,
  type Time,
  type UTCTimestamp,
} from 'lightweight-charts'
import { exportDeskPersonalReceipt, getDeskChart, getDeskPersonalHistory, DESK_CHART_DEFAULT_SESSIONS, type DeskPersonalReceipt, type DeskChart, type DeskChartBar, type DeskChartDecision, type DeskChartFill, type DeskChartTimeframe } from '../../services/api'
import type { DeskHistory, DeskHistoryFill, DeskHistoryRow, DeskLive, DeskPaperLive, DeskStructure } from '../../services/api'
import { SessionPrice } from './StockBoard'
import { LEVEL_NAME } from './TradeBoard'

// The picture behind the grade. The board says what the desk concluded; this
// shows adjusted price indicators beside recorded and replayed grade changes.
// Forming-week overlays may differ from the weekly inputs of a saved grade.
//
// Daily and weekly are the two timeframes the desk reads: the 9/21/50/200
// EMAs and the 20-session band are daily, and `weekly_trend` and
// `weekly_stack` come from the 9 and 21 EMAs on weekly closes. A monthly
// view would invite a trader to reason from a bar size no analyst looks at,
// which is the disagreement this chart exists to remove.
//
// The 15m view is not a third analyst timeframe: it is the last few sessions
// of raw fifteen-minute bars, so the operator can see at what time in the
// session a buy, trim or sell is decided (the last bar before the close) and
// at what time it fills (the next session's open for a buy, its close for a
// sell). Nothing the desk grades on is drawn there, only the session VWAP.
//
// Canvas content is mirrored into text for screen readers. Browser tests also
// observe actual drawing calls: a correct caption does not prove marker placement.

type Timeframe = DeskChartTimeframe

// The candle's live quote for this name, as the board already holds it.
export type LiveQuote = {
  last: number
  open?: number | null
  high?: number | null
  low?: number | null
  bar?: string | null
}

// The lines drawn on price, in draw order, with the colour each is given.
// The band edges are dashed because they are a range rather than a trend,
// and the 252-session extremes are dotted because they are a boundary rather
// than a level being traded against. `from` says which block of the
// payload the series comes out of.
type Line = {
  key: string
  label: string
  color: string
  from?: 'overlays' | 'levels'
  dashed?: boolean
  dotted?: boolean
  width?: number
}

const DAILY_LINES: Line[] = [
  { key: 'high_52w', label: '252-session high', color: '#d2d2d7', from: 'levels', dotted: true },
  { key: 'low_52w', label: '252-session low', color: '#d2d2d7', from: 'levels', dotted: true },
  { key: 'band_upper', label: 'Upper Bollinger band', color: '#c7c7cc', dashed: true },
  { key: 'band_lower', label: 'Lower Bollinger band', color: '#c7c7cc', dashed: true },
  { key: 'ema9', label: '9-session EMA', color: '#ff9500' },
  { key: 'ema21', label: '21-session EMA', color: '#0071e3' },
  { key: 'ema50', label: '50-session EMA', color: '#5856d6' },
  { key: 'ema200', label: '200-session EMA', color: '#1d1d1f', width: 2 },
]

const WEEKLY_LINES: Line[] = [
  { key: 'ema9', label: '9-week EMA', color: '#ff9500' },
  { key: 'ema21', label: '21-week EMA', color: '#0071e3', width: 2 },
]

// The one line on the fifteen-minute view: the session's volume-weighted
// average of bar closes, drawn when the payload carries it.
const INTRADAY_LINES: Line[] = [
  { key: 'session_vwap', label: 'Session VWAP', color: '#5856d6' },
]

// How many sessions of fifteen-minute bars the operator can ask for.
const INTRADAY_SESSIONS = [5, 10, 20, 60]

// The board's two levels, drawn as horizontal lines on every timeframe in
// the colours the board's 21-EMA series and the 252-session boundary use,
// so the picture and the row name the same numbers.
const BOARD_LEVEL_COLOR: Record<'ema_21' | 'high_20', string> = { ema_21: '#0071e3', high_20: '#8e8e93' }

// The board levels a structure carries that can be drawn: a finite positive
// price for each, in draw order.
const boardLevels = (structure: Pick<DeskStructure, 'ema_21' | 'high_20'> | null | undefined): Array<{key: 'ema_21' | 'high_20'; price: number}> =>
  (['ema_21', 'high_20'] as const)
    .map(key => ({key, price: structure?.[key]}))
    .filter((level): level is {key: 'ema_21' | 'high_20'; price: number} => typeof level.price === 'number' && Number.isFinite(level.price) && level.price > 0)

// The lines drawn and read out under each timeframe.
const linesFor = (timeframe: Timeframe): Line[] =>
  timeframe === 'weekly' ? WEEKLY_LINES : timeframe === '15m' ? INTRADAY_LINES : DAILY_LINES

const GRADE_COLOR: Record<string, string> = {
  'A+': '#1a7f37',
  A: '#2da44e',
  B: '#9a6700',
  C: '#b42318',
}

// A session string to the seconds-based stamp the chart indexes on. The
// dates are plain sessions with no time, so they are read as UTC midnight
// and the axis shows the session a trader means.
const stamp = (session: string): UTCTimestamp =>
  (Date.parse(`${session}T00:00:00Z`) / 1000) as UTCTimestamp

// An ISO-8601 instant with its offset (a fifteen-minute bar's start, a
// marker's time) to the seconds-based stamp; NaN when it does not parse, which
// `ordered` and the marker filter then drop.
const instantStamp = (iso: string | undefined): UTCTimestamp =>
  Math.floor(Date.parse(iso ?? '') / 1000) as UTCTimestamp

// Where a bar sits on the time axis: its own start on 15m, the session's
// midnight on daily and weekly.
const barStamp = (bar: DeskChartBar, timeframe: Timeframe): UTCTimestamp =>
  timeframe === '15m' ? instantStamp(bar.time) : stamp(bar.date)

// A stamp on the fifteen-minute axis, written in New York time: the clock
// alone within a day, the day too when the axis is at a day boundary or the
// crosshair asks for the whole thing.
const newYorkClock = (seconds: number, withDay: boolean) => new Intl.DateTimeFormat('en-US', {
  timeZone: 'America/New_York', hour: 'numeric', minute: '2-digit',
  ...(withDay ? {month: 'short', day: 'numeric'} : {}),
}).format(new Date(seconds * 1000))

// The axis tick labels on 15m: a day boundary names the day, a tick within
// the day names the New York clock. The library would otherwise write UTC.
const newYorkTick = (time: Time, kind: TickMarkType) => {
  if (typeof time !== 'number') return null
  const day = new Date(time * 1000)
  const zoned = (options: Intl.DateTimeFormatOptions) => new Intl.DateTimeFormat('en-US', {timeZone: 'America/New_York', ...options}).format(day)
  switch (kind) {
    case TickMarkType.Year: return zoned({year: 'numeric'})
    case TickMarkType.Month: return zoned({month: 'short'})
    case TickMarkType.DayOfMonth: return zoned({month: 'short', day: 'numeric'})
    default: return newYorkClock(time, false)
  }
}

// The chart library throws on a series that is unsorted or repeats a
// timestamp, and an exception here would take the whole ticker panel down
// with it rather than losing one picture. The endpoint sorts its bars, so
// this should never fire; it is here so that a malformed payload costs a
// chart and not the reason the trader opened the name.
const ordered = <T extends { time: UTCTimestamp }>(points: T[]): T[] => {
  const byTime = new Map<number, T>()
  for (const point of points) {
    if (!Number.isFinite(point.time)) continue
    byTime.set(point.time as unknown as number, point)
  }
  return [...byTime.values()].sort((a, b) => (a.time as number) - (b.time as number))
}

type RecordedSetup = NonNullable<DeskHistory['recommendations']>['observations'][number]
type ChartReceipt = {
  id: string
  generated_at: string
  action: 'Buy' | 'Sell' | 'Hold' | null
  grade: string | null
}

// Accept only dated instants with an explicit timezone; never guess publication time.
const recordedInstant = (value: unknown) => typeof value === 'string'
  && /(?:Z|[+-]\d{2}:\d{2})$/i.test(value) && Number.isFinite(Date.parse(value))
  ? new Date(value) : null

// Keep the original publication date in the exchange timezone, distinct from its price bar.
const recordedSession = (value: unknown) => {
  const instant = recordedInstant(value)
  if (!instant) return null
  const parts = new Intl.DateTimeFormat('en-US', {timeZone: 'America/New_York', year: 'numeric', month: '2-digit', day: '2-digit'}).formatToParts(instant)
  return ['year', 'month', 'day'].map(kind => parts.find(part => part.type === kind)?.value).join('-')
}

// Identify a calendar week without attaching a later publication to an earlier week's candle.
const weekOf = (session: string) => {
  const day = new Date(`${session}T00:00:00Z`)
  day.setUTCDate(day.getUTCDate() - (day.getUTCDay() + 6) % 7)
  return day.toISOString().slice(0, 10)
}

// Require the same finite price evidence for candles and every attached marker.
const drawableCandle = (bar: DeskChartBar) =>
  [bar.open, bar.high, bar.low, bar.close].every(value => typeof value === 'number' && Number.isFinite(value))

// Match the original day or its own week without letting the library choose a substitute candle.
// On 15m a session is many candles and none of them is "the" one, so the
// session-dated layers (grades, recommendations, history decisions) draw
// nothing there; the intraday markers come timed from the payload instead.
const markerCandle = (session: string, bars: DeskChartBar[], timeframe: Timeframe) => {
  if (timeframe === '15m') return undefined
  const candle = bars.find(bar => timeframe === 'daily' ? bar.date === session
    : weekOf(bar.date) === weekOf(session) && bar.date >= session)
  return candle && drawableCandle(candle) ? candle : undefined
}

// Display unknown setup evidence explicitly instead of inferring a neutral state.
const setupLabel = (row: RecordedSetup) => row.entry_state
  ? row.entry_state[0].toUpperCase() + row.entry_state.slice(1) : 'Not recorded'

// Preserve every original reading while grouping visible markers by publication session or week.
const recordedGroups = (history: DeskHistory | undefined, bars: DeskChartBar[], timeframe: Timeframe) => {
  const groups = new Map<string, RecordedSetup[]>()
  const rows = [...(history?.recommendations?.observations ?? [])].sort((a, b) =>
    (recordedInstant(a.recorded_at)?.getTime() ?? Infinity) - (recordedInstant(b.recorded_at)?.getTime() ?? Infinity) || a.id.localeCompare(b.id))
  for (const row of rows) {
    const session = recordedSession(row.recorded_at)
    if (!session) continue
    // Daily and 15m group by the publication session (15m bars carry their session's date); weekly by its week.
    const candle = bars.find(bar => timeframe !== 'weekly'
      ? bar.date === session : weekOf(bar.date) === weekOf(session) && bar.date >= session)
    if (!candle) continue
    groups.set(candle.date, [...(groups.get(candle.date) ?? []), row])
  }
  return [...groups.entries()].map(([date, readings]) => {
    const states = readings.map(setupLabel).filter((value, index, values) => index === 0 || value !== values[index - 1])
    return {date, readings, label: `${states.slice(0, 3).join('→')}${states.length > 3 ? '…' : ''} · ${readings.length}`}
  })
}

// Date the original publication and reference observation independently in readable exchange time.
const recordedTime = (value: unknown) => {
  const instant = recordedInstant(value)
  return instant ? new Intl.DateTimeFormat('en-US', {timeZone: 'America/New_York', year: 'numeric', month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit', second: '2-digit', timeZoneName: 'short'}).format(instant) : 'Not recorded'
}

// Plot actual saved personal actions once per transition, independently of fills or research setups.
const recommendationEvents = (receipts: ChartReceipt[]) => {
  const events: {id: string; at: string; session: string; action: 'Buy' | 'Sell'; grade: string | null}[] = []
  let previous: string | null = null
  const seen = new Set<string>()
  for (const receipt of [...receipts].sort((a, b) => Date.parse(a.generated_at) - Date.parse(b.generated_at) || a.id.localeCompare(b.id))) {
    if (seen.has(receipt.id)) continue
    seen.add(receipt.id)
    const session = recordedSession(receipt.generated_at)
    if (!session) { previous = null; continue }
    const action = receipt.action
    if (action !== 'Buy' && action !== 'Sell') { previous = null; continue }
    if (previous !== action) events.push({id: receipt.id, at: receipt.generated_at, session, action, grade: receipt.grade})
    previous = action
  }
  return events
}

// Retain only this ticker's chart fields while merging stored identities in generation order.
const mergeReceipts = (current: ChartReceipt[], incoming: DeskPersonalReceipt[], ticker: string) => {
  const byId = new Map(current.map(item => [item.id, item]))
  for (const item of incoming) {
    const row = item.payload?.rows?.[ticker]
    byId.set(item.id, {id: item.id, generated_at: item.generated_at, action: row?.action ?? null, grade: row?.grade ?? null})
  }
  return [...byId.values()].sort((a, b) => Date.parse(b.generated_at) - Date.parse(a.generated_at) || b.id.localeCompare(a.id))
}

// Attach recommendations to their publication candle without inventing prices or backdating a signal.
const recommendationMarkers = (events: ReturnType<typeof recommendationEvents>, bars: DeskChartBar[], timeframe: Timeframe) =>
  events.flatMap(event => {
    const candle = markerCandle(event.session, bars, timeframe)
    return candle ? [{
      time: stamp(candle.date), position: event.action === 'Buy' ? 'belowBar' as const : 'aboveBar' as const,
      color: event.action === 'Buy' ? '#1a7f37' : '#b42318',
      shape: event.action === 'Buy' ? 'arrowUp' as const : 'arrowDown' as const,
      text: event.action, size: 2, event,
    }] : []
  })

// Describe only explicit source flags; missing or malformed provenance proves neither origin.
const gradeSource = (said: unknown) => said === true ? 'Saved' : said === false ? 'Recalculated' : null

// Mark available-candle grade changes with each endpoint's source and original day within weekly groups.
const gradeMarkers = (history: DeskHistory | undefined, bars: DeskChartBar[], timeframe: Timeframe) => {
  const rows = (history?.rows ?? []).filter((r) => r.grade)
  const out: {
    time: UTCTimestamp
    position: 'aboveBar' | 'belowBar'
    color: string
    shape: 'arrowUp' | 'arrowDown'
    text: string
    size: number
  }[] = []
  const rank: Record<string, number> = { 'A+': 3, A: 2, B: 1, C: 0 }
  // Identify the grade boundary used by the exit rule, without assuming a holding.
  const wanted = (grade: string) => grade === 'A' || grade === 'A+'
  for (let i = 1; i < rows.length; i += 1) {
    const before = rows[i - 1].grade
    const now = rows[i].grade
    if (!before || !now || before === now) continue
    const candle = markerCandle(rows[i].date, bars, timeframe)
    if (!candle) continue
    const up = (rank[now] ?? -1) > (rank[before] ?? -1)
    const previousSource = gradeSource(rows[i - 1].said)
    const nextSource = gradeSource(rows[i].said)
    // Crossing below A can inform an exit, but history does not prove a trade.
    const belowA = wanted(before) && !wanted(now)
    out.push({
      time: stamp(candle.date),
      position: up ? 'belowBar' : 'aboveBar',
      color: belowA ? '#b42318' : GRADE_COLOR[now] ?? '#6e6e73',
      shape: up ? 'arrowUp' : 'arrowDown',
      // Missing provenance must not be described as an original saved reading.
      text: previousSource === nextSource
        ? nextSource ? `${nextSource} grade ${before}→${now}` : `Grade ${before}→${now}`
        : `Grade ${before} (${(previousSource ?? 'source unknown').toLowerCase()})→${now} (${(nextSource ?? 'source unknown').toLowerCase()})`,
      size: rows[i].said ? 2 : 1,
    })
  }
  return out
}

// The chart's own marker shape, shared by every layer drawn on the candles.
type ChartMarker = {
  time: UTCTimestamp
  position: 'aboveBar' | 'belowBar'
  color: string
  shape: 'arrowUp' | 'arrowDown' | 'circle'
  text: string
  size: number
}

const DECISION_BUY = '#15803d'
const DECISION_SELL = '#b42318'
// The paper account's trades, in the board's colours: BUY green, SELL red.
const TRADE_BUY = '#248a3d'
const TRADE_SELL = '#b42318'
const DECISION_NOTE = 'Recalculated close decisions; not recorded recommendations or fills. Sizes are portfolio weights.'
// The equal-weight policy, whose add and trim are the reset's rebalance rather
// than a sizing change: a held name's target drifts with the count of A/A+
// names and only the twenty-session reset trades it, so the markers show
// entries, exits and resets, and the drift between resets is not a trade.
// `/4` and `/5` (the account's since 2026-09-29) differ only in the hold cap.
// Named versions, never a prefix: a history of a version the page has not
// seen keeps the sizing reading rather than being guessed into this one.
const EQUAL_WEIGHT_POLICIES: ReadonlySet<string> = new Set([
  'graded-equal-weight/4',
  'graded-equal-weight/5',
])
const EQUAL_WEIGHT_LEGEND = 'Policy replay: BUY enters the A/A+ book; SELL leaves it; RESET rebalances to target. These are simulated decisions.'

// A paper trade as the board writes it: BUY 2 @ $1,752.25.
const tradeText = (side: string, qty: number, price: number) =>
  `${side === 'buy' ? 'BUY' : 'SELL'} ${qty.toLocaleString('en-US')} @ $${price.toLocaleString('en-US', {minimumFractionDigits: 2, maximumFractionDigits: 2})}`

// A target weight as the percent of equity a trader reads it as: whole when it
// is whole ("14%"), else to one decimal ("9.1%"), the way the board writes BUY 9.1%.
const percentText = (weight: number | undefined) => {
  const pct = Math.round((weight ?? 0) * 1000) / 10
  return Number.isInteger(pct) ? `${pct}%` : `${pct.toFixed(1)}%`
}

// Capitalise a policy action for the eye: buy -> Buy.
const titled = (action: string) => action ? action[0].toUpperCase() + action.slice(1) : action

// Whether a history's decisions are an equal-weight policy's (`/4` or `/5`),
// whose add/trim mean a rebalance at the reset.
const isEqualWeight = (policy: string | null | undefined) =>
  typeof policy === 'string' && EQUAL_WEIGHT_POLICIES.has(policy)

// The words on a decision marker: what to do and the size it leads to. Under the
// equal-weight policy an add or a trim is the reset's rebalance and is written
// as the move it places ("Rebalance +2.5%"); under a sizing policy it is the
// level it leads to ("Add →20%"). A hold is no marker at all, so it returns nothing.
const decisionText = (row: DeskHistoryRow, policy?: string | null) => {
  switch (row.action) {
    case 'buy': return `BUY signal ${percentText(row.target_weight)}`
    case 'sell': return 'SELL signal'
    case 'add':
    case 'trim': {
      if (!isEqualWeight(policy)) return `${row.action === 'add' ? 'ADD' : 'TRIM'} signal →${percentText(row.target_weight)}`
      const delta = row.delta_weight
      if (typeof delta !== 'number' || !Number.isFinite(delta)) return `RESET →${percentText(row.target_weight)}`
      return `RESET ${delta >= 0 ? '+' : '−'}${percentText(Math.abs(delta))}`
    }
    default: return null
  }
}

// The rows on which the replayed policy would have traded, oldest first.
const decisionRows = (history: DeskHistory | undefined) =>
  (history?.rows ?? []).filter(row => row.action && row.action !== 'hold')

// Mark the sessions the live policy would have bought, added, trimmed or sold on,
// on the candle of the decision's own session (the close it was made at, not the
// next open it fills at). Buys and adds point up from below in green; trims and
// sells point down from above in red; the label carries the size it leads to.
const decisionMarkers = (history: DeskHistory | undefined, bars: DeskChartBar[], timeframe: Timeframe): ChartMarker[] =>
  decisionRows(history).flatMap(row => {
    const text = decisionText(row, history?.policy)
    const candle = markerCandle(row.date, bars, timeframe)
    if (!text || !candle) return []
    const up = row.action === 'buy' || row.action === 'add'
    return [{
      time: stamp(candle.date),
      position: up ? 'belowBar' as const : 'aboveBar' as const,
      color: up ? DECISION_BUY : DECISION_SELL,
      shape: up ? 'arrowUp' as const : 'arrowDown' as const,
      text, size: 2,
    }]
  })

// Only a fill with a date, a side, a quantity and a price is drawable or listable.
const drawableFill = (fill: DeskHistoryFill) =>
  Boolean(fill) && typeof fill.date === 'string' && (fill.side === 'buy' || fill.side === 'sell')
  && typeof fill.qty === 'number' && Number.isFinite(fill.qty)
  && typeof fill.price === 'number' && Number.isFinite(fill.price)

// The paper account's real fills, oldest first, malformed rows left out.
const fillRows = (history: DeskHistory | undefined): DeskHistoryFill[] => {
  const raw: unknown = history?.fills
  return (Array.isArray(raw) ? raw as DeskHistoryFill[] : []).filter(drawableFill)
    .sort((a, b) => a.date.localeCompare(b.date))
}

// Merge confirmed broker fills with archived fills as a multiset, retaining same-price separate executions.
const currentFillRows = (history: DeskHistory | undefined, activity: DeskPaperLive['activity'], ticker: string, now: number): DeskHistoryFill[] => {
  const archived = fillRows(history)
  const matched = new Set<number>()
  // Match old archive rows without an execution identity conservatively, without deduplicating distinct fills.
  const identity = (fill: DeskHistoryFill) => `${fill.date}:${fill.side}:${fill.qty}:${fill.price}`
  const fresh: DeskHistoryFill[] = []
  for (const fill of activity?.fills ?? []) {
    const instant = recordedInstant(fill.filled_at)
    if (fill.symbol !== ticker || !instant || instant.getTime() > now
      || !['buy', 'sell'].includes(fill.side) || !Number.isFinite(fill.qty) || fill.qty <= 0
      || !Number.isFinite(fill.price) || fill.price <= 0) continue
    const date = recordedSession(fill.filled_at)!
    if (date !== activity?.session) continue
    const row: DeskHistoryFill = {date, side: fill.side as 'buy' | 'sell', qty: fill.qty, price: fill.price, filled_at: fill.filled_at}
    const index = archived.findIndex((saved, i) => !matched.has(i) && identity(saved) === identity(row)
      && (!saved.filled_at || Date.parse(saved.filled_at) === instant.getTime()))
    if (index >= 0) {
      matched.add(index)
      archived[index] = {...archived[index], filled_at: fill.filled_at}
      continue
    }
    fresh.push(row)
  }
  return [...archived, ...fresh].sort((a, b) => a.date.localeCompare(b.date)
    || (Date.parse(a.filled_at ?? '') || 0) - (Date.parse(b.filled_at ?? '') || 0))
}

// Place timestamped fills only on their containing 15-minute candle, never on a nearest substitute.
const currentIntradayMarkers = (fills: DeskHistoryFill[], bars: DeskChartBar[]): ChartMarker[] =>
  fills.flatMap(fill => {
    const at = recordedInstant(fill.filled_at)?.getTime()
    if (at == null) return []
    const candle = bars.find(bar => {
      const start = recordedInstant(bar.time)?.getTime()
      return start != null && bar.date === fill.date && start <= at && at < start + 900_000 && drawableCandle(bar)
    })
    return candle ? [{time: instantStamp(candle.time!), position: fill.side === 'buy' ? 'belowBar' as const : 'aboveBar' as const,
      color: fill.side === 'buy' ? TRADE_BUY : TRADE_SELL, shape: 'circle' as const,
      text: tradeText(fill.side, fill.qty, fill.price), size: 2}] : []
  })

// Whether a fill is the executor's redeploy of idle cash rather than an entry
// or a rotation, as the record names it.
const isRedeploy = (fill: {kind?: string}) => fill.kind === 'redeploy'

// Mark the paper account's real fills as circles on the session they filled,
// below the candle for a buy and above it for a sell, so a decision and the fill
// it led to sit a candle apart on the same picture. A redeploy fill is purple
// and says so; every other fill is blue.
const fillMarkers = (history: DeskHistory | undefined, bars: DeskChartBar[], timeframe: Timeframe): ChartMarker[] =>
  fillRows(history).flatMap(fill => {
    const candle = markerCandle(fill.date, bars, timeframe)
    return candle ? [{
      time: stamp(candle.date),
      position: fill.side === 'buy' ? 'belowBar' as const : 'aboveBar' as const,
      color: fill.side === 'buy' ? TRADE_BUY : TRADE_SELL,
      shape: 'circle' as const,
      text: tradeText(fill.side, fill.qty, fill.price),
      size: 2,
    }] : []
  })

// Only a payload decision with a parseable time, a traded action and a label is drawable.
const drawableDecision = (row: DeskChartDecision) =>
  Boolean(row) && typeof row.time === 'string' && Number.isFinite(Date.parse(row.time))
  && (row.action === 'buy' || row.action === 'add' || row.action === 'sell' || row.action === 'trim')
  && typeof row.label === 'string' && row.label.length > 0

// The policy's decisions on the fifteen-minute bars, timed by the server: on
// the last regular bar of the session they were decided at. Buys and adds
// point up from below in green, trims and sells down from above in red, the
// label saying what and that it was decided at the close.
const intradayDecisionMarkers = (data: DeskChart | null): ChartMarker[] =>
  (data?.timeframe === '15m' && Array.isArray(data.decisions) ? data.decisions : []).filter(drawableDecision).map(row => {
    const up = row.action === 'buy' || row.action === 'add'
    return {
      time: instantStamp(row.time),
      position: up ? 'belowBar' as const : 'aboveBar' as const,
      color: up ? DECISION_BUY : DECISION_SELL,
      shape: up ? 'arrowUp' as const : 'arrowDown' as const,
      text: row.label, size: 2,
    }
  })

// Where each decision fills: a small circle in the decision's colour on the
// next session's opening bar for a buy or an add and its closing bar for a
// sell or a trim, labelled "... fills at the open/close" by the server.
const intradayFillsAtMarkers = (data: DeskChart | null): ChartMarker[] =>
  (data?.timeframe === '15m' && Array.isArray(data.fills_at) ? data.fills_at : []).filter(drawableDecision).map(row => {
    const up = row.action === 'buy' || row.action === 'add'
    return {
      time: instantStamp(row.time),
      position: up ? 'belowBar' as const : 'aboveBar' as const,
      color: up ? DECISION_BUY : DECISION_SELL,
      shape: 'circle' as const,
      text: row.label, size: 1,
    }
  })

// Only a payload fill with a parseable time, a side and a label is drawable.
const drawableTimedFill = (fill: DeskChartFill) =>
  Boolean(fill) && typeof fill.time === 'string' && Number.isFinite(Date.parse(fill.time))
  && (fill.side === 'buy' || fill.side === 'sell')
  && typeof fill.qty === 'number' && Number.isFinite(fill.qty) && typeof fill.price === 'number' && Number.isFinite(fill.price)

// The paper account's real fills on the bar they filled in, as circles (blue,
// or purple for a redeploy), below for a buy and above for a sell, labelled
// "Filled buy 63 @ 224.81" by the server.
const intradayFillMarkers = (data: DeskChart | null): ChartMarker[] =>
  (data?.timeframe === '15m' && Array.isArray(data.fills) ? data.fills : []).filter(drawableTimedFill).map(fill => ({
    time: instantStamp(fill.time),
    position: fill.side === 'buy' ? 'belowBar' as const : 'aboveBar' as const,
    color: fill.side === 'buy' ? TRADE_BUY : TRADE_SELL,
    shape: 'circle' as const,
    text: tradeText(fill.side, fill.qty, fill.price), size: 2,
  }))

// A session as a trader writes it: the month and day, with the year only when
// it is not the year of the newest row, so a list spanning years stays honest.
const sessionLabel = (session: string, currentYear: string) => {
  const day = new Date(`${session}T00:00:00Z`)
  if (!Number.isFinite(day.getTime())) return session
  const sameYear = session.slice(0, 4) === currentYear
  return new Intl.DateTimeFormat('en-US', {timeZone: 'UTC', month: 'short', day: 'numeric', ...(sameYear ? {} : {year: 'numeric'})}).format(day)
}

// The close on the decision's own session, from the loaded daily candles; a
// weekly candle is a week's close and not the decision's, so it is left out.
const closeOn = (session: string, bars: DeskChartBar[], timeframe: Timeframe) => {
  if (timeframe !== 'daily') return null
  const bar = bars.find(candle => candle.date === session)
  return bar && typeof bar.close === 'number' && Number.isFinite(bar.close) ? bar.close : null
}

// Render price indicators and their evidence without implying account execution.
export const TickerChart = ({
  userId,
  ticker,
  history,
  paperActivity,
  quote,
  live,
  now = Date.now(),
  personalHistory = false,
  personalReceiptId,
  tall = false,
  close,
  suggestion,
  levels = null,
}: {
  userId: string
  ticker: string
  history?: DeskHistory
  paperActivity?: DeskPaperLive['activity']
  quote?: LiveQuote
  live?: DeskLive
  now?: number
  personalHistory?: boolean
  personalReceiptId?: string
  tall?: boolean
  // The name's last close, so the session price can fall back to it when no dated quote exists.
  close?: number | null
  // The board's levels for this name (the balancer's structure), drawn as
  // labelled horizontal lines on every timeframe; nothing when absent.
  levels?: DeskStructure | null
  // The live suggestion for this name, worded exactly as the board's Action
  // column words it, so the chart's "Now:" line cannot disagree with the row
  // beside it. When absent the chart falls back to the recorded history's
  // latest decision, which is what the board shows only when no live decision
  // exists for the record on screen.
  suggestion?: { word: string; detail: string } | null
}) => {
  const [timeframe, setTimeframe] = useState<Timeframe>('daily')
  // How many sessions of fifteen-minute bars to load; only 15m reads it.
  const [intradaySessions, setIntradaySessions] = useState(DESK_CHART_DEFAULT_SESSIONS['15m'])
  const [showSignals, setShowSignals] = useState(true)
  const [showRecommendations, setShowRecommendations] = useState(true)
  const [showDecisions, setShowDecisions] = useState(false)
  const [showFills, setShowFills] = useState(true)
  const [receipts, setReceipts] = useState<ChartReceipt[]>([])
  const [receiptCursor, setReceiptCursor] = useState<string | null>(null)
  const [receiptError, setReceiptError] = useState('')
  const [receiptBusy, setReceiptBusy] = useState(false)
  const receiptRequest = useRef(0)
  const receiptScope = useRef(0)
  const pendingReceiptReads = useRef(new Set<string>())
  const [receiptPending, setReceiptPending] = useState<string[]>([])
  const [receiptFailures, setReceiptFailures] = useState<string[]>([])
  const [receiptReload, setReceiptReload] = useState(0)
  const [fullHistory, setFullHistory] = useState(false)
  const [indicatorsOpen, setIndicatorsOpen] = useState(false)
  const [receivedData, setData] = useState<DeskChart | null>(null)
  const [refreshFailed, setRefreshFailed] = useState(false)
  // A timeframe or ticker switch must not reinterpret the previous response while the next loads.
  const data = receivedData?.ticker === ticker && receivedData.timeframe === timeframe ? receivedData : null
  const [error, setError] = useState<string | null>(null)
  // The picture failed to draw but the readings below it are still good.
  const [drawFailed, setDrawFailed] = useState(false)
  const holder = useRef<HTMLDivElement | null>(null)
  const chartRef = useRef<IChartApi | null>(null)
  const savedView = useRef<{scope: string; range: {from: number; to: number} | null} | null>(null)
  const markersRef = useRef<ISeriesMarkersPluginApi<Time> | null>(null)
  // The candle series of the current chart, so the board's level lines can be
  // replaced in place when a candle moves them, without redrawing the chart.
  const candlesRef = useRef<ISeriesApi<'Candlestick'> | null>(null)

  // Read one owner-scoped page; stale responses cannot cross an account or ticker change.
  const loadReceipts = async (before?: string) => {
    const request = ++receiptRequest.current
    setReceiptBusy(true)
    setReceiptError('')
    try {
      const page = await getDeskPersonalHistory(userId, before)
      if (request !== receiptRequest.current) return
      if (!Array.isArray(page.items)) throw new Error('Invalid recommendation history')
      setReceipts(current => mergeReceipts(current, page.items, ticker))
      setReceiptCursor(page.next_cursor && page.next_cursor !== before ? page.next_cursor : null)
    } catch {
      if (request === receiptRequest.current) setReceiptError('Recommendation history unavailable.')
    } finally {
      if (request === receiptRequest.current) setReceiptBusy(false)
    }
  }

  // Read the accepted immutable receipt, independently of pagination and acknowledgement.
  const loadReceipt = async (id: string) => {
    if (!personalHistory || pendingReceiptReads.current.has(id)) return
    const scope = receiptScope.current
    pendingReceiptReads.current.add(id)
    setReceiptPending(current => [...current, id])
    setReceiptFailures(current => current.filter(failed => failed !== id))
    try {
      const item = await exportDeskPersonalReceipt(userId, id)
      if (scope !== receiptScope.current) return
      if (item.id !== id || !recordedInstant(item.generated_at) || !item.payload?.rows
        || typeof item.payload.rows !== 'object' || Array.isArray(item.payload.rows)) {
        throw new Error('Invalid recommendation receipt')
      }
      setReceipts(current => mergeReceipts(current, [item], ticker))
    } catch {
      if (scope === receiptScope.current) setReceiptFailures(current => [...new Set([...current, id])])
    } finally {
      if (scope === receiptScope.current) {
        pendingReceiptReads.current.delete(id)
        setReceiptPending(current => current.filter(pending => pending !== id))
      }
    }
  }

  useEffect(() => {
    receiptScope.current += 1
    pendingReceiptReads.current.clear()
    setReceipts([])
    setReceiptCursor(null)
    setReceiptError('')
    setReceiptBusy(false)
    setReceiptPending([])
    setReceiptFailures([])
    if (personalHistory) void loadReceipts()
    return () => { receiptRequest.current += 1; receiptScope.current += 1 }
  }, [userId, ticker, personalHistory, receiptReload])

  useEffect(() => {
    if (personalHistory && personalReceiptId) void loadReceipt(personalReceiptId)
  }, [userId, ticker, personalHistory, personalReceiptId, receiptReload])

  useEffect(() => {
    setData(null)
    setError(null)
    setRefreshFailed(false)
  }, [userId, ticker, timeframe, intradaySessions])

  useEffect(() => {
    let live = true
    let request = 0
    // Only the newest request may publish its coherent candle/indicator snapshot.
    const read = (first: boolean) => {
      const sequence = ++request
      getDeskChart(userId, ticker, timeframe, timeframe === '15m' ? intradaySessions : DESK_CHART_DEFAULT_SESSIONS[timeframe])
        .then((payload) => {
          if (!live || sequence !== request) return
          setData(payload)
          setError(null)
          setRefreshFailed(false)
        })
        .catch((e: Error) => {
          if (!live || sequence !== request) return
          setRefreshFailed(true)
          if (first) setError(e.message)
        })
    }
    read(true)
    // The averages, bands and levels are computed on the server against the
    // live candle, so they only move if the payload is re-read. Without this
    // the candle walked while every line beside it stayed at the last close.
    const timer = window.setInterval(() => { if (!document.hidden) read(false) }, 20_000)
    // Returning to the chart reads the latest snapshot immediately.
    const resume = () => { if (!document.hidden) read(false) }
    document.addEventListener('visibilitychange', resume)
    return () => {
      live = false
      window.clearInterval(timer)
      document.removeEventListener('visibilitychange', resume)
    }
  }, [userId, ticker, timeframe, intradaySessions, quote?.bar, quote?.last])

  // Candles and indicators share the endpoint's snapshot. The independently
  // polled board quote triggers refresh but must never replace just the candle.
  const merged = useMemo(
    () => ({
      bars: data?.bars ?? [] as DeskChartBar[],
      live: Boolean(data?.quote_bar && Number.isFinite(Date.parse(data.quote_bar))),
    }),
    [data],
  )
  const events = useMemo(() => recommendationEvents(receipts), [receipts])
  const actionMarkers = useMemo(() => recommendationMarkers(events, merged.bars, timeframe), [events, merged, timeframe])
  const changes = useMemo(() => gradeMarkers(history, merged.bars, timeframe), [history, merged, timeframe])
  const decisions = useMemo(() => decisionMarkers(history, merged.bars, timeframe), [history, merged, timeframe])
  const fills = useMemo(() => currentFillRows(history, paperActivity, ticker, now), [history, paperActivity, ticker, now])
  const fillMarks = useMemo(() => fillMarkers({...history, fills} as DeskHistory, merged.bars, timeframe), [history, fills, merged, timeframe])
  // The fifteen-minute layers come timed from the payload rather than dated
  // from the history file, so they are empty on daily and weekly.
  // The 15m view marks the signal on the bar it was made; where a trade fills
  // is the paper account's own fill, drawn from the fills, never projected.
  const timedDecisions = useMemo(() => intradayDecisionMarkers(data), [data])
  const timedFills = useMemo(() => {
    const recorded = intradayFillMarkers(data)
    const current = currentIntradayMarkers(fills, merged.bars)
    const counts = new Map<string, number>()
    // Keep separate identical executions while avoiding the same fill arriving through both sources.
    const key = (marker: ChartMarker) => `${marker.time}:${marker.text}`
    recorded.forEach(marker => counts.set(key(marker), (counts.get(key(marker)) ?? 0) + 1))
    return [...recorded, ...current.filter(marker => {
      const id = key(marker), remaining = counts.get(id) ?? 0
      if (!remaining) return true
      counts.set(id, remaining - 1)
      return false
    })]
  }, [data, fills, merged])

  useEffect(() => {
    if (!holder.current || !data || !merged.bars.length) return
    let chart: IChartApi
    try {
      chart = createChart(holder.current, {
        autoSize: true,
        layout: { background: { color: 'transparent' }, textColor: '#6e6e73', fontSize: 11 },
        grid: {
          horzLines: { color: 'rgba(0,0,0,0.05)' },
          vertLines: { color: 'rgba(0,0,0,0.03)' },
        },
        rightPriceScale: { borderColor: 'rgba(0,0,0,0.1)' },
        // On 15m the axis shows the clock, in New York time: the library
        // would otherwise write the bar starts as UTC.
        timeScale: timeframe === '15m'
          ? { borderColor: 'rgba(0,0,0,0.1)', rightOffset: 4, timeVisible: true, secondsVisible: false, tickMarkFormatter: newYorkTick }
          : { borderColor: 'rgba(0,0,0,0.1)', rightOffset: 4 },
        crosshair: { mode: CrosshairMode.Normal },
        // The chart library otherwise trusts navigator.language, which can
        // be a POSIX tag that Intl rejects when it draws the time axis.
        localization: {
          locale: 'en-US',
          priceFormatter: (v: number) => `$${v.toFixed(2)}`,
          ...(timeframe === '15m' ? { timeFormatter: (time: Time) => typeof time === 'number' ? `${newYorkClock(time, true)} ET` : String(time) } : {}),
        },
      })
    } catch {
      setDrawFailed(true)
      return
    }
    chartRef.current = chart

    const candles = chart.addSeries(CandlestickSeries, {
      upColor: '#2da44e',
      downColor: '#b42318',
      borderUpColor: '#2da44e',
      borderDownColor: '#b42318',
      wickUpColor: '#2da44e',
      wickDownColor: '#b42318',
    })
    try {
      candles.setData(
        ordered(
          merged.bars.map((b) =>
            drawableCandle(b) ? {
              time: barStamp(b, timeframe),
              open: b.open as number,
              high: b.high as number,
              low: b.low as number,
              close: b.close as number,
            } : { time: barStamp(b, timeframe) }),
        ),
      )
    } catch {
      chart.remove()
      chartRef.current = null
      setDrawFailed(true)
      return
    }

    const lines = linesFor(timeframe)
    const drawn: ISeriesApi<'Line'>[] = []
    for (const line of lines) {
      const values = (line.from === 'levels' ? data.levels : data.overlays)[line.key]
      if (!values) continue
      const series = chart.addSeries(LineSeries, {
        color: line.color,
        lineWidth: (line.width ?? 1) as 1 | 2,
        lineStyle: line.dotted
          ? LineStyle.Dotted
          : line.dashed
            ? LineStyle.Dashed
            : LineStyle.Solid,
        priceLineVisible: false,
        lastValueVisible: false,
        crosshairMarkerVisible: false,
        // Distant reference levels remain available without compressing the visible price action.
        autoscaleInfoProvider: line.from === 'levels' ? () => null : undefined,
      })
      series.setData(
        ordered(
          merged.bars.map((b, i) => values[i] !== null && Number.isFinite(values[i])
            ? { time: barStamp(b, timeframe), value: values[i] as number }
            : { time: barStamp(b, timeframe) }),
        ),
      )
      drawn.push(series)
    }

    markersRef.current = createSeriesMarkers(candles, [])
    candlesRef.current = candles
    // Give recent candles enough horizontal space; all loaded bars remain available to pan and zoom.
    // On 15m a session is 27 bars, so the recent view holds about two sessions.
    const frameView = () => {
      if (fullHistory) chart.timeScale().fitContent()
      else {
        const width = (holder.current?.clientWidth ?? 390) - 65
        const count = timeframe === '15m'
          ? Math.max(27, Math.min(108, Math.floor(width / 8)))
          : Math.max(12, Math.min(40, Math.floor(width / 22)))
        chart.timeScale().setVisibleLogicalRange({from: Math.max(0, merged.bars.length - count), to: merged.bars.length + 1})
      }
    }
    const scope = `${userId}:${ticker}:${timeframe}:${fullHistory}:${intradaySessions}`
    if (savedView.current?.scope === scope && savedView.current.range) {
      chart.timeScale().setVisibleLogicalRange(savedView.current.range)
    } else frameView()
    // Auto sizing keeps the canvas responsive without resetting the trader's pan or zoom.
    setDrawFailed(false)

    return () => {
      savedView.current = {scope, range: chart.timeScale().getVisibleLogicalRange()}
      chart.remove()
      chartRef.current = null
      markersRef.current = null
      candlesRef.current = null
      drawn.length = 0
    }
  }, [data, merged, timeframe, fullHistory, userId, ticker, intradaySessions])

  // The board's levels as horizontal lines labelled on the price axis, on
  // every timeframe (the 15m view draws no daily indicator, so this is the
  // only place the operator sees the 21-EMA and the 20-day high against the
  // session's bars). Replaced in place when a candle moves them, so the
  // chart's position and zoom survive; they are shown, never traded on here.
  const ema21Level = levels?.ema_21 ?? null
  const high20Level = levels?.high_20 ?? null
  useEffect(() => {
    const candles = candlesRef.current
    if (!candles) return
    const lines = boardLevels({ema_21: ema21Level, high_20: high20Level}).map(level =>
      candles.createPriceLine({
        price: level.price,
        color: BOARD_LEVEL_COLOR[level.key],
        lineWidth: 1,
        lineStyle: LineStyle.Dashed,
        axisLabelVisible: true,
        title: `${LEVEL_NAME[level.key]} ${level.price.toFixed(1)}`,
      }))
    return () => {
      // The chart may already be gone when its own effect cleaned up first.
      if (candlesRef.current !== candles) return
      for (const line of lines) {
        try { candles.removePriceLine(line) } catch { /* already removed with the chart */ }
      }
    }
  }, [data, merged, timeframe, fullHistory, ema21Level, high20Level])

  // Update markers in place so receipt-only changes preserve the user's chart position and zoom.
  useEffect(() => {
    // Series points require uniqueness, but distinct markers on the same date must survive.
    // Grade changes do not apply on 15m (a grade is a session's reading, not a
    // bar's); the decision and fill layers there are the payload's timed ones.
    const markers = [
      ...(personalHistory && showRecommendations ? actionMarkers : []),
      ...(showSignals ? changes : []),
      ...(showDecisions ? [...decisions, ...timedDecisions] : []),
      ...(showFills ? [...fillMarks, ...timedFills] : []),
    ].filter(marker => Number.isFinite(marker.time)).sort((a, b) => Number(a.time) - Number(b.time))
    markersRef.current?.setMarkers(markers)
  }, [data, merged, timeframe, fullHistory, showSignals, showRecommendations, showDecisions, showFills, actionMarkers, changes, decisions, fillMarks, timedDecisions, timedFills, personalHistory])

  // Everything the canvas shows, in text, for the tests and for anyone not
  // reading pixels. The last drawn bar is the one a trader is looking at.
  const summary = useMemo(() => {
    if (!data || !merged.bars.length) return null
    const last = merged.bars[merged.bars.length - 1]
    const lines = linesFor(timeframe)
    const readings = lines
      .map((line) => {
        const series = (line.from === 'levels' ? data.levels : data.overlays)[line.key]
        const value = series ? series[series.length - 1] : null
        if (value === null || value === undefined || last.close === null) return null
        const away = ((last.close - value) / value) * 100
        return { label: line.label, value, away }
      })
      .filter((r): r is { label: string; value: number; away: number } => r !== null)
    return { last, readings }
  }, [data, merged, timeframe])

  const groups = useMemo(() => recordedGroups(history, merged.bars, timeframe), [history, merged, timeframe])
  const observations = history?.recommendations?.observations ?? []
  // The policy's stance on the newest session that carries one, and the last
  // twelve sessions it would have traded on, newest first.
  const latestDecision = useMemo(() => [...(history?.rows ?? [])].reverse().find(row => row.action), [history])
  const recentDecisions = useMemo(() => decisionRows(history).slice(-12).reverse(), [history])
  const currentYear = (latestDecision?.date ?? history?.asof ?? '').slice(0, 4)

  return (
    <section className="mb-4" aria-label={`${ticker} price chart`}>
      {live && <div className="mb-2 text-xs"><SessionPrice live={live} ticker={ticker} now={now} close={close} /></div>}
      <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
        <h4 className="text-xs font-medium text-[#1d1d1f]">
          Price, indicators and grade history
        </h4>
        <div className="flex flex-wrap gap-1">
          <div className="flex gap-1" role="group" aria-label="Chart range">
          <button type="button" aria-pressed={!fullHistory} className="rounded px-2 py-0.5 text-xs" onClick={() => setFullHistory(false)}>Recent</button>
          <button type="button" aria-pressed={fullHistory} className="rounded px-2 py-0.5 text-xs" onClick={() => setFullHistory(true)}>Full history</button>
          </div>
          {personalHistory && <label className="mr-2 flex items-center gap-1 text-[11px] text-[#6e6e73]" title="Your saved personal Buy and Sell recommendations, recorded at generation time; not fills.">
            <input type="checkbox" checked={showRecommendations} onChange={event => setShowRecommendations(event.target.checked)} />
            Saved recommendations
          </label>}
          <label className="mr-2 flex items-center gap-1 text-[11px] text-[#6e6e73]" title="Saved nightly grades where available; otherwise recalculated grades. Markers identify their source, not a trade.">
            <input type="checkbox" checked={showSignals} onChange={event => setShowSignals(event.target.checked)} />
            Grade changes
          </label>
          <label className="mr-2 flex items-center gap-1 text-[11px] text-[#6e6e73]" title="Historical decisions recalculated under the displayed policy. These are not recorded live recommendations or paper fills.">
            <input type="checkbox" checked={showDecisions} onChange={event => setShowDecisions(event.target.checked)} />
            Policy replay
          </label>
          {fills.length > 0 && <label className="mr-2 flex items-center gap-1 text-[11px] text-[#6e6e73]">
            <input type="checkbox" checked={showFills} onChange={event => setShowFills(event.target.checked)} />
            Paper trades
          </label>}
          {timeframe === '15m' && <div className="flex gap-1" role="group" aria-label="Chart sessions">
          {INTRADAY_SESSIONS.map((count) => (
            <button
              key={count}
              type="button"
              onClick={() => setIntradaySessions(count)}
              aria-pressed={intradaySessions === count}
              title={`Load the last ${count} sessions of fifteen-minute bars`}
              className={`rounded px-2 py-0.5 text-xs ${
                intradaySessions === count
                  ? 'bg-[#1d1d1f] text-white'
                  : 'bg-[#f5f5f7] text-[#6e6e73] hover:text-[#0071e3]'
              }`}
            >
              {count}
            </button>
          ))}
          </div>}
          <div className="flex gap-1" role="group" aria-label="Chart timeframe">
          {(['15m', 'daily', 'weekly'] as Timeframe[]).map((frame) => (
            <button
              key={frame}
              type="button"
              onClick={() => setTimeframe(frame)}
              aria-pressed={timeframe === frame}
              title={frame === '15m' ? 'Fifteen-minute bars of the last sessions' : frame === 'daily' ? 'Daily candles' : 'Weekly candles'}
              className={`rounded px-2 py-0.5 text-xs ${
                timeframe === frame
                  ? 'bg-[#1d1d1f] text-white'
                  : 'bg-[#f5f5f7] text-[#6e6e73] hover:text-[#0071e3]'
              }`}
            >
              {frame === 'daily' ? 'D' : frame === 'weekly' ? 'W' : '15m'}
            </button>
          ))}
          </div>
        </div>
      </div>

      {error && (
        <p role="alert" className="text-xs text-[#b42318]">
          {error}
        </p>
      )}
      {!error && !data && <p className="text-xs text-[#6e6e73]">Loading the chart…</p>}
      {/* The board's level lines are canvas, so the same numbers are written
          out here, worded as the board's Levels column words them, whether or
          not the picture has loaded. */}
      {boardLevels(levels).length > 0 && <p className="text-[11px] text-[#6e6e73]" aria-label={`${ticker} board levels`}>
        Technical references: {boardLevels(levels).map(level => `${LEVEL_NAME[level.key]} ${level.price.toFixed(1)}`).join(' · ')}. Not order triggers.
      </p>}

      {data && (
        <>
          {data.data_status && data.data_status !== 'complete' && (
            <details aria-label="Chart data quality" className="mb-2 text-xs text-[#9a6700]">
              <summary className="cursor-pointer">Chart data {data.data_status}
                {Boolean(data.missing_sessions?.length) && ` · ${data.missing_sessions!.length} missing session${data.missing_sessions!.length === 1 ? '' : 's'}`}
              </summary>
              {data.data_reason && <p>{data.data_reason}</p>}
              {Boolean(data.missing_sessions?.length) && <p>{data.missing_sessions!.join(', ')}</p>}
            </details>
          )}
          <div
            ref={holder}
            className={`w-full ${drawFailed ? 'hidden' : tall ? 'h-[52vh] min-h-80' : 'h-72'}`}
            data-testid="ticker-chart-canvas"
          />
          {drawFailed && (
            <p className="rounded bg-[#f5f5f7] p-2 text-xs text-[#6e6e73]">
              The chart could not be drawn from this data. The readings below are unaffected.
            </p>
          )}
          {timeframe === '15m'
            ? <p className="mt-1 text-[11px] text-[#6e6e73]" aria-label="Fifteen-minute chart caption">
              Latest session: {data.bars[data.bars.length - 1]?.date ?? 'unavailable'}.{' '}
              {data.sessions} {data.live_feed ? '' : 'complete '}session{data.sessions === 1 ? '' : 's'} of fifteen-minute (15m) bars loaded ({merged.bars.length} bars, New York time, closing auction included where stored); pan or zoom for history.
              Paper fills use their recorded time. Policy replay uses the last regular bar of its decision session.
            </p>
            : <p className="mt-1 text-[11px] text-[#6e6e73]">
            {merged.live && summary?.last.close !== null
              ? `Candle includes the 15-minute bar starting ${new Intl.DateTimeFormat('en-US', {
                  timeZone: 'America/New_York', month: 'short', day: 'numeric', year: 'numeric',
                  hour: 'numeric', minute: '2-digit', timeZoneName: 'short',
                }).format(new Date(data.quote_bar!))}.`
              : `Newest stored ${timeframe === 'weekly' ? 'week' : 'session'}: ${data.bars[data.bars.length - 1]?.date ?? 'unavailable'}${data.last_bar_complete === false ? summary?.last.close === null ? ' (incomplete candle)' : ' (forming candle)' : ''}.`}{' '}
            {merged.bars.length} {timeframe === 'weekly' ? 'weeks' : 'sessions'} loaded; pan or zoom for history.
          </p>}
          <p className="mt-1 text-[11px] text-[#6e6e73]" aria-label="Chart legend">
            Circles: paper fills. Arrows: grade changes, labelled Saved or Recalculated when known.{showDecisions ? ' Signal and RESET labels: policy replay, not recorded recommendations.' : ''}
          </p>
          <p aria-label="Chart refresh status" role={refreshFailed ? 'status' : undefined} className="mt-1 text-[11px] text-[#6e6e73]">Regular-session chart · refresh 20s{data.live_feed ? ` · ${data.live_feed.toUpperCase()}` : ''}{data.live_as_of ? ` · checked ${recordedTime(data.live_as_of)}` : ''}{refreshFailed ? ' · Refresh failed; showing last snapshot' : data.live_reason ? ` · ${data.live_reason}` : ''}</p>
          {showDecisions && history?.policy && <p className="mt-1 text-[11px] text-[#6e6e73]" aria-label="Policy decision note">
            {history.policy}: {DECISION_NOTE}
          </p>}
          {/* What the markers mean under the equal-weight policy, and how the
              reset sessions were found: without a clock on file no session is
              a reset, and the chart says so rather than guessing one. */}
          {showDecisions && isEqualWeight(history?.policy) && <p className="mt-1 text-[11px] text-[#6e6e73]" aria-label="Policy marker legend">
            {EQUAL_WEIGHT_LEGEND}{history?.rebalance_note ? ` ${history.rebalance_note[0].toUpperCase()}${history.rebalance_note.slice(1)}.` : ''}
          </p>}

          {/* The markers are canvas, so the same decisions are written out here:
              the policy's stance today, then the sessions it would have traded
              on, newest first. This list is the decisions, not the markers, so
              the marker checkbox leaves it in place. */}
          {(latestDecision || suggestion || fills.length > 0) && <div className="mt-2 text-[11px] text-[#6e6e73]" aria-label={`${ticker} decisions`}>
            <p className="font-medium text-[#1d1d1f]" aria-label={`${ticker} now`}>Now: {suggestion ? `${suggestion.word} · ${suggestion.detail}` : 'no paper order'}</p>
            {fills.length > 0 && <ul className="mt-1" aria-label={`${ticker} paper fills`}>
              {[...fills].reverse().slice(0, 12).map((fill, index) => (
                <li key={`${fill.date}-${fill.side}-${fill.qty}-${index}`}>{sessionLabel(fill.date, currentYear)}{fill.filled_at ? ` · ${newYorkClock(Date.parse(fill.filled_at) / 1000, false)} ET` : ''} · {tradeText(fill.side, fill.qty, fill.price)}{isRedeploy(fill) ? ' · idle cash put to work' : ''}</li>
              ))}
            </ul>}
            {showDecisions && (recentDecisions.length === 0
              ? <p className="mt-1">No policy replay action in the loaded history.</p>
              : <ul className="mt-1" aria-label={`${ticker} strategy signals`}>
                {recentDecisions.map(row => {
                  const price = closeOn(row.date, merged.bars, timeframe)
                  return <li key={row.date}>{sessionLabel(row.date, currentYear)} · {decisionText(row, history?.policy)}{price !== null ? ` · close $${price.toFixed(2)}` : ''}</li>
                })}
              </ul>)}
          </div>}

          {personalHistory && showRecommendations && <div className="mt-2 text-[11px] text-[#6e6e73]" aria-label="Saved recommendation history">
            <p aria-label="Buy and Sell markers">{actionMarkers.length
              ? actionMarkers.map(marker => `${marker.event.action} · ${recordedTime(marker.event.at)}`).join(' · ')
              : receiptBusy || receiptPending.length ? 'Loading recommendations…' : 'No saved Buy/Sell on these candles in the loaded history.'}</p>
            {receiptError && <p role="status">{receiptError}</p>}
            {!!receiptPending.length && <p role="status">Loading newly generated recommendations…</p>}
            {!!receiptFailures.length && <p role="status">Some newly generated recommendation reads failed. Showing the saved records successfully read.</p>}
            <details>
              <summary className="cursor-pointer">Saved recommendations ({receipts.length} saved record{receipts.length === 1 ? '' : 's'})</summary>
              <p>Personal recommendations at generation time, not fills. Repeated unchanged actions are grouped. Research setups are not Buy/Sell instructions.</p>
              <p>Without a price candle, recommendations remain listed here but are not drawn.</p>
              <p>{receiptCursor ? 'Partial history. Load earlier saved records to extend coverage.' : receiptError || receiptBusy ? 'History coverage unconfirmed.' : 'No earlier saved records were reported by the last history page.'} Loaded saved records may omit receipts from other sessions or retain receipts since deleted or expired. Reload to read current stored history. Older unsaved decisions cannot be reconstructed.</p>
              {!!receipts.length && <p>{recordedTime(receipts[receipts.length - 1].generated_at)} – {recordedTime(receipts[0].generated_at)}</p>}
              {receiptCursor && <button type="button" disabled={receiptBusy} onClick={() => void loadReceipts(receiptCursor)} className="text-[#0071e3]">{receiptBusy ? 'Loading…' : 'Load earlier recommendations'}</button>}
              {receiptError && <button type="button" onClick={() => void loadReceipts()} className="text-[#0071e3]">Retry history</button>}
              {!!receiptFailures.length && <button type="button" disabled={receiptPending.length > 0} onClick={() => receiptFailures.forEach(id => void loadReceipt(id))} className="text-[#0071e3]">Retry new recommendations</button>}
              <button type="button" disabled={receiptBusy || receiptPending.length > 0} onClick={() => setReceiptReload(current => current + 1)} className="ml-2 text-[#0071e3]">Reload saved history</button>
              <table className="w-full text-left [&_td]:p-1 [&_th]:p-1" aria-label="Saved Buy and Sell recommendations">
                <thead><tr><th>Generated</th><th>Action</th><th>Grade</th></tr></thead>
                <tbody>{events.map(event => <tr key={event.id}><td>{recordedTime(event.at)}</td><td>{event.action}</td><td>{event.grade || 'Not recorded'}</td></tr>)}</tbody>
              </table>
            </details>
          </div>}

          <div className="mt-2 text-[11px] text-[#6e6e73]" aria-label="Recorded setup history">
            <p className="sr-only" aria-label="Research publication groups">{groups.length ? `${groups.length} recorded ${timeframe === 'weekly' ? 'weeks' : 'sessions'} · ${groups.map(group => `${group.date}: ${group.label}`).join(' · ')}` : 'No recorded setups on the loaded candles.'}</p>
            <details className="mt-1">
              <summary className="cursor-pointer">Original readings ({observations.length})</summary>
              <p>Dip is a pullback setup, not a Buy instruction. Original research observations; not personal actions, fills or an accuracy score. Publication time and reference bar are separate.</p>
              <div className="max-h-64 overflow-auto"><table className="w-full text-left [&_td]:p-1 [&_th]:p-1" aria-label="Original chart setup readings">
                <thead><tr><th>Recorded</th><th>Reference bar</th><th title="Original unadjusted reference price; chart prices are adjusted.">Bar price</th><th>Setup</th><th>Grade</th><th>Policy</th></tr></thead>
                <tbody>{observations.map(row => <tr key={row.id}>
                  <td>{recordedTime(row.recorded_at)}</td><td>{recordedTime(row.bar)}</td>
                  <td>{typeof row.price === 'number' && Number.isFinite(row.price) ? `$${row.price.toFixed(2)}` : 'Unavailable'}</td>
                  <td>{setupLabel(row)}{row.event_paused && ' · entries paused'}</td><td>{row.grade || 'Not recorded'}</td>
                  <td>{row.version || 'Not recorded'} · <span title={row.policy_sha256 ?? undefined}>{row.policy_sha256?.slice(0, 8) ?? 'Unidentified'}</span></td>
                </tr>)}</tbody>
              </table></div>
              {history?.recommendations?.older_records_not_shown && <p>Only recent archives are loaded; older records are not shown.</p>}
              {!!history?.recommendations?.invalid_archives && <p>Some archived records could not be read.</p>}
            </details>
          </div>

          {summary && (
            <details aria-label="Chart indicators" open={indicatorsOpen} onToggle={event => setIndicatorsOpen(event.currentTarget.open)} className="mt-2 text-[11px] text-[#6e6e73]">
            <summary className="cursor-pointer">Indicators &amp; price basis</summary>
            {timeframe === '15m'
              ? <p className="mt-2 text-[11px] text-[#6e6e73]" aria-label="Fifteen-minute price basis">Prices: {data.basis}; not adjusted for splits or dividends, so a fill can be checked against the print it crossed at. The daily averages, bands and levels are not drawn at this resolution.</p>
              : <p className="mt-2 text-[11px] text-[#6e6e73]">Prices: {data.basis}. Indicators can update during a session; weekly overlays include the forming week when present and can differ from a saved grade.</p>}
            {timeframe !== '15m' && <p className="mt-1 text-[11px] text-[#6e6e73]">EMA means exponential moving average of candle closes; recent closes carry more weight.</p>}
            <details className="mt-1 text-[11px] text-[#6e6e73]">
              <summary className="cursor-pointer">Indicator definitions</summary>
              {timeframe === 'daily' ? <>
                <p>Daily EMA spans count trading sessions. Bollinger bands use the mean of 20 session closes, plus or minus 2 population standard deviations of those closes.</p>
                <p>The 252-session high and low use candle highs and lows, including the newest candle, not a calendar-year window.</p>
              </> : timeframe === 'weekly' ? <p>Weekly EMA spans count weeks, including the forming week when present.</p>
              : <p>Session VWAP is the volume-weighted average of fifteen-minute bar closes since that session's open, restarting each session; the closing-auction bar continues the session it closes.</p>}
            </details>
            <p className="mt-1 text-[11px] text-[#6e6e73]">Price distance = (chart price − indicator value) ÷ indicator value × 100, rounded to one decimal; not a return.</p>
            <dl aria-label="Indicator readings" className="mt-2 grid grid-cols-1 gap-x-4 gap-y-2 text-[11px] sm:grid-cols-2 xl:grid-cols-3">
              <div className="flex min-w-0 flex-wrap justify-between gap-x-2 gap-y-0.5">
                <dt className="text-[#6e6e73]">{merged.live && summary.last.close !== null ? '15-minute bar close' : 'Newest stored candle price'}</dt>
                <dd className="tabular-nums font-medium">
                  {summary.last.close === null ? '—' : `$${summary.last.close.toFixed(2)}`}
                </dd>
              </div>
              {summary.readings.map((reading) => (
                <div key={reading.label} className="flex min-w-0 flex-wrap justify-between gap-x-2 gap-y-0.5">
                  <dt className="text-[#6e6e73]">{reading.label}</dt>
                  <dd className="text-right tabular-nums">
                    <span className="block">${reading.value.toFixed(2)}</span>
                    <span className={`block ${Number.isFinite(reading.away) ? reading.away >= 0 ? 'text-[#2da44e]' : 'text-[#b42318]' : 'text-[#6e6e73]'}`}>
                      {Number.isFinite(reading.away)
                        ? `Price distance ${reading.away >= 0 ? '+' : ''}${reading.away.toFixed(1)}%`
                        : 'Distance unavailable'}
                    </span>
                  </dd>
                </div>
              ))}
            </dl>
            </details>
          )}

          {showSignals && <p className="mt-2 text-[11px] text-[#6e6e73]">
            {timeframe === '15m'
              ? 'Grade changes are session readings and are not marked on fifteen-minute bars; switch to D or W to see them.'
              : changes.length === 0
              ? `No grade change marked on these candles.`
              : `${changes.length} grade change${changes.length === 1 ? '' : 's'} marked: ${changes
                  .slice(-6)
                  .map((c) => c.text)
                  .join(', ')}${changes.length > 6 ? ' (most recent six)' : ''}.`}
          </p>}
        </>
      )}
    </section>
  )
}
