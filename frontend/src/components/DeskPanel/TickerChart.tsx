import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
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
  type LogicalRange,
  type Time,
  type UTCTimestamp,
} from 'lightweight-charts'
import { exportDeskPersonalReceipt, getDeskChart, getDeskPersonalHistory, getDeskOriginalStrategyRecommendation, getDeskRecordedStrategyRecommendations, DESK_CHART_DEFAULT_SESSIONS, type DeskRecordedStrategyReference, type DeskOriginalStrategyRecommendation, type DeskPersonalReceipt, type DeskChart, type DeskChartBar, type DeskChartDecision, type DeskChartTimeframe } from '../../services/api'
import type { DeskHistory, DeskHistoryFill, DeskHistoryRow, DeskLive, DeskModelAllocation, DeskPaperLive, DeskPolicyReplay, DeskStructure, DeskStrategyStock, DeskStrategyDecision } from '../../services/api'
import { SessionPrice } from './StockBoard'
import { LEVEL_NAME, percent, shares } from './TradeBoard'
import {confirmedPaperFills, paperActivitySession, paperFillSession} from './paperFills'
import type {Signals, StrategyChartTarget} from './SignalBoard'
import {boardAction, marketPhaseLine, strategyHistoryMatches} from './SignalBoard'
import {StrategyTechnicalEvidence} from './StrategyTechnicalEvidence'

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
// The 15m view places paper fills only from their original execution time.
// Date-only fills remain listed without an assumed open or close marker.
// Optional policy replay shows recalculated close decisions, separate from fills.
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
// Zoomed out past a few sessions, a clock on a tick means nothing (the
// library picks them by UTC hour), so every tick names its day instead.
const newYorkTick = (time: Time, kind: TickMarkType, wide = false) => {
  if (typeof time !== 'number') return null
  const day = new Date(time * 1000)
  const zoned = (options: Intl.DateTimeFormatOptions) => new Intl.DateTimeFormat('en-US', {timeZone: 'America/New_York', ...options}).format(day)
  switch (kind) {
    case TickMarkType.Year: return zoned({year: 'numeric'})
    case TickMarkType.Month: return zoned({month: 'short'})
    case TickMarkType.DayOfMonth: return zoned({month: 'short', day: 'numeric'})
    default: return wide ? zoned({month: 'short', day: 'numeric'}) : newYorkClock(time, false)
  }
}

// More than about three sessions of fifteen-minute bars on screen.
const WIDE_INTRADAY_BARS = 3 * 27

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
  if (!instant) return 'Not recorded'
  // The day is named only when it is not today in New York; the year only when it differs.
  const zone = {timeZone: 'America/New_York'}
  const today = new Date()
  const sameDay = instant.toLocaleDateString('en-CA', zone) === today.toLocaleDateString('en-CA', zone)
  const sameYear = instant.toLocaleDateString('en-US', {...zone, year: 'numeric'}).endsWith(today.toLocaleDateString('en-US', {...zone, year: 'numeric'}).slice(-4))
  const day = sameDay ? '' : instant.toLocaleDateString('en-US', {...zone, month: 'short', day: 'numeric', ...(sameYear ? {} : {year: 'numeric'})}) + ' '
  return day + instant.toLocaleTimeString('en-US', {...zone, hour12: false, hour: '2-digit', minute: '2-digit'}) + ' ET'
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

// Mark dated grade changes; the strategy view never turns a grade change into a simulated order.
const gradeMarkers = (history: {rows: {date: string; at?: string; grade?: string | null; said?: boolean}[]} | undefined, bars: DeskChartBar[], timeframe: Timeframe, gradeOnly = false) => {
  const rows = (history?.rows ?? []).filter((r) => r.grade)
  const out: {
    time: UTCTimestamp
    position: 'aboveBar' | 'belowBar'
    color: string
    shape: 'arrowUp' | 'arrowDown'
    text: string
    detail: string
    size: number
  }[] = []
  const rank: Record<string, number> = { 'A+': 3, A: 2, B: 1, C: 0 }
  // Identify the grade boundary used by the exit rule, without assuming a holding.
  const wanted = (grade: string) => grade === 'A' || grade === 'A+'
  for (let i = 1; i < rows.length; i += 1) {
    const before = rows[i - 1].grade
    const now = rows[i].grade
    if (!before || !now || before === now) continue
    const at = recordedInstant(rows[i].at)?.getTime()
    // A published grade is stamped at the next open, so place it on that session's candle.
    const session = recordedSession(rows[i].at) ?? rows[i].date
    const candle = timeframe === '15m' && gradeOnly ? bars.find(bar => {
      const start = recordedInstant(bar.time)?.getTime()
      return at != null && start != null && start <= at && at < start + 900000 && !bar.auction && drawableCandle(bar)
    }) : markerCandle(session, bars, timeframe)
    if (!candle) continue
    const up = (rank[now] ?? -1) > (rank[before] ?? -1)
    const previousSource = gradeSource(rows[i - 1].said)
    const nextSource = gradeSource(rows[i].said)
    // Crossing below A can inform an exit, but history does not prove a trade.
    const belowA = wanted(before) && !wanted(now)
    const direction = gradeOnly ? 'Grade change' : !wanted(before) && wanted(now) ? 'BUY signal' : belowA ? 'SELL signal' : 'Grade change'
    const provenance = previousSource === nextSource
      ? nextSource ? `${nextSource} grade ${before}→${now}` : `Grade ${before}→${now}`
      : `Grade ${before} (${(previousSource ?? 'source unknown').toLowerCase()})→${now} (${(nextSource ?? 'source unknown').toLowerCase()})`
    out.push({
      time: barStamp(candle, timeframe),
      position: up ? 'belowBar' : 'aboveBar',
      color: belowA ? '#b42318' : GRADE_COLOR[now] ?? '#6e6e73',
      shape: up ? 'arrowUp' : 'arrowDown',
      // Missing provenance must not be described as an original saved reading.
      text: direction === 'Grade change' ? `${before}→${now}` : `${belowA ? 'SELL' : 'BUY'} · ${now}`,
      detail: `${rows[i].date} · ${direction} · ${provenance}`,
      size: 1,
    })
  }
  return out
}

// What the rule's entries in this name did afterwards, against the benchmark, in one line.
const replayOutcomeLine = (replay: DeskPolicyReplay): string => {
  const entry = replay.outcomes?.entry_summary
  if (!entry || !entry.count) return ''
  const pct = (value: number | undefined) => value === undefined ? '—' : `${(value * 100).toFixed(0)}%`
  const signed = (value: number | undefined) => value === undefined ? '—' : `${value >= 0 ? '+' : ''}${(value * 100).toFixed(1)}%`
  return `${entry.count} entr${entry.count === 1 ? 'y' : 'ies'} here · beat QQQ after 20 sessions ${pct(entry.hit_rate_20)} of the time, mean excess ${signed(entry.mean_excess_20)} · after 60: ${pct(entry.hit_rate_60)}, ${signed(entry.mean_excess_60)}.`
}

// The chart's own marker shape, shared by every layer drawn on the candles.
type MarkerKind = 'replay' | 'recorded' | 'current'
type MarkerSample = 'in_sample' | 'out_of_sample' | 'live' | 'unknown'
type ChartMarker = {
  id?: string
  recommendations?: {id: string; at: string; action: string; weight: number; evidence?: DeskStrategyDecision['evidence']; simulated: boolean;
    originalRef?: {snapshot: string; completed: string; strategy: string; at?: string; bytesSha?: string}}[]
  time: UTCTimestamp
  position: 'aboveBar' | 'belowBar'
  color: string
  shape: 'arrowUp' | 'arrowDown' | 'circle' | 'square'
  text: string
  size: number
  kind?: MarkerKind
  // For a replayed trade: whether it opened, closed or resized the position.
  role?: MarkerRole
  sample?: MarkerSample
  policy?: string
}

type MarkerRole = 'entry' | 'exit' | 'resize' | 'fomc'
// Wider than this many bars on screen, the chart draws the replay's entries and exits only:
// the near-daily adds and trims of a held slot otherwise bury them.
const ZOOMED_OUT_BARS = 180

// Label the model's actual action size separately from a profit or remaining-position target.
const targetLabel = (target: Pick<StrategyChartTarget, 'action' | 'weight'>): string => `${target.action} ${sizePercent(target.weight)}%`

// Retain a positive model adjustment without rounding its displayed action to zero.
const sizePercent = (weight: number): string => weight > 0 && weight < .001 ? '<0.1' : (weight * 100).toFixed(1)

// Describe only a sample the payload actually names; absent provenance is unknown.
const markerSample = (value: unknown): MarkerSample => value === 'in_sample' || value === 'out_of_sample' ? value : 'unknown'

// Mute a historical replay that the model saw while fitting, without changing a live record.
const replayColor = (action: string, sample: MarkerSample) => action === 'Buy'
  ? sample === 'in_sample' ? 'rgba(36,138,61,.45)' : '#248a3d'
  : sample === 'in_sample' ? 'rgba(180,35,24,.45)' : '#b42318'

// Mark replayed simulations and recorded live recommendations as distinct layers across every timeframe.
// A replayed trade smaller than this is not something a person would act on; more than half of
// the learned sizing's replay trades were such dust, and drawing them buried the real ones.
const DUST_WEIGHT = 0.005
const dustTrades = (simulation: DeskStrategyStock | null | undefined): number =>
  simulation?.decisions.filter(row => ['BUY', 'SELL', 'TRIM'].includes(row.action) && typeof row.weight === 'number' && row.weight > 0 && row.weight < DUST_WEIGHT).length ?? 0

// An entry or an exit is always drawn; a resize of a held name only when it is a real
// reallocation. The rule nudges a held name's slot most sessions as the tilt and the
// volatility target drift, and drawing every nudge buried the decisions a person reads.
const RESIZE_WEIGHT = 0.02
const drawnReplayTrade = (trade: DeskPolicyReplay['trades'][number]): boolean =>
  Number.isFinite(trade.size) && trade.size >= DUST_WEIGHT
  && (trade.target < DUST_WEIGHT || Math.abs(trade.target - trade.size) < DUST_WEIGHT || trade.size >= RESIZE_WEIGHT)

// The installed policy's own decisions back in time: a target set at a close trades at the
// next open, so the marker sits on that next session's candle (its first bar on 15m; an FOMC
// restoration timed for the decision close sits on that session's 3:45 PM bar). The position
// is walked trade by trade. Every entry and every exit is its own marker, even when one weekly
// candle holds several. Every FOMC-rule cut and restoration is drawn and says so. Any other
// resize is drawn once the position has moved RESIZE_WEIGHT from the size the last marker
// showed, so the sizes read from one marker to the next always add up; resizes on one candle
// merge into one Add or Trim. Buy opens a position, Sell closes it (its whole size at that
// point), Add and Trim say the change since the last marker and where the position stands.
type ReplayTrade = DeskPolicyReplay['trades'][number]
const FOMC_REASON = /^fomc_/
const replayCandle = (trade: ReplayTrade, bars: DeskChartBar[], timeframe: Timeframe) => {
  if (timeframe !== '15m') return markerCandle(trade.date, bars, timeframe)
  const session = bars.filter(bar => bar.date === trade.date && !bar.auction && drawableCandle(bar))
  if (trade.timing === 'decision_close') return session.find(bar => bar.time && /T15:45:00/.test(bar.time)) ?? session[session.length - 1]
  return session[0]
}
const policyReplayMarkers = (replay: DeskPolicyReplay | null | undefined, bars: DeskChartBar[], timeframe: Timeframe, policy?: string): ChartMarker[] => {
  type Group = {time: number; role: MarkerRole; before: number; after: number; cut?: boolean; trades: (ReplayTrade & {before: number})[]}
  const groups: Group[] = []
  let held = 0
  let shown = 0
  let pending: (ReplayTrade & {before: number})[] = []
  for (const trade of replay?.trades ?? []) {
    const before = held
    const after = Number.isFinite(trade.target) ? Math.max(0, trade.target) : held
    held = after
    const step = {...trade, before}
    const candle = replayCandle(trade, bars, timeframe)
    if (!candle) {
      // Outside the drawn bars: the next marker's change is measured from here.
      shown = after
      pending = []
      continue
    }
    pending.push(step)
    const time = Number(barStamp(candle, timeframe))
    const role: MarkerRole = before <= 0 && after > 0 ? 'entry' : after <= 0 && before > 0 ? 'exit'
      : FOMC_REASON.test(trade.reason ?? '') ? 'fomc' : 'resize'
    const last = groups[groups.length - 1]
    if (role === 'resize' || role === 'fomc') {
      // Resizes on the candle the last marker sits on join it, so a candle has one Add or Trim.
      if (last && last.time === time && last.role === role) {
        last.after = after
        last.trades.push(...pending)
        pending = []
        shown = after
        continue
      }
      if (role === 'resize' && Math.abs(after - shown) < RESIZE_WEIGHT) continue
    }
    // An exit and an FOMC step state the real position before them (the FOMC rule cuts half
    // of what is held, not of what the last marker showed); an Add or Trim chains from that marker.
    groups.push({time, role, before: role === 'exit' || role === 'fomc' ? before : shown, after, trades: pending,
      ...(role === 'fomc' ? {cut: trade.reason === 'fomc_reduction'} : {})})
    pending = []
    shown = after
  }
  const markers: ChartMarker[] = []
  groups.forEach((group, index) => {
    const net = group.after - group.before
    const up = group.role === 'entry' || (group.role === 'fomc' ? !group.cut : group.role !== 'exit' && net > 0)
    const action = up ? 'Buy' : 'Sell'
    const change = `${sizePercent(Math.abs(net))}% → ${sizePercent(group.after)}%`
    const text = group.role === 'entry' ? `Buy ${sizePercent(group.after)}%`
      : group.role === 'exit' ? `Sell ${sizePercent(group.before)}% · exit`
      : group.role === 'fomc' ? `FOMC ${up ? 'restore' : 'cut'} ${change}`
      : `${up ? 'Add' : 'Trim'} ${change}`
    markers.push({id: `strategy:replay:${group.time}:${index}`, time: group.time as UTCTimestamp, position: up ? 'belowBar' : 'aboveBar',
      color: replayColor(action, 'out_of_sample'), shape: 'circle', text, size: 1, kind: 'replay', role: group.role, sample: 'out_of_sample', policy,
      recommendations: group.trades.map(trade => {
        const side = trade.action === 'BUY' ? 'Buy' : 'Sell'
        const atClose = trade.timing === 'decision_close'
        const why = trade.reason === 'fomc_reduction' ? ' (FOMC rule: half the position cut before the decision)'
          : FOMC_REASON.test(trade.reason ?? '') ? ' (FOMC rule: position restored after the cut)' : ''
        return {id: `policy-replay:${trade.decided}:${trade.date}:${side}`, at: `${trade.date}T${atClose ? '15:45' : '09:30'}:00-04:00`, action: side, weight: trade.size, simulated: true,
          evidence: {grade: (replay!.grades ?? replay!.rows).filter(row => row.date <= trade.decided).slice(-1)[0]?.grade, inputs_as_of: trade.decided, model_position_size: trade.target,
            reason: `Rule target ${(trade.target * 100).toFixed(1)}% (from ${(trade.before * 100).toFixed(1)}%) set at the ${trade.decided} close; ${side.toLowerCase()} at the ${trade.date} ${atClose ? 'close (3:45 PM)' : 'open'}${why}.`} as DeskStrategyDecision['evidence']}
      })})
  })
  return markers
}

const strategyTargetMarkers = (simulation: DeskStrategyStock | null | undefined, current: StrategyChartTarget | null | undefined, bars: DeskChartBar[], timeframe: Timeframe, recorded: DeskRecordedStrategyReference[] = [], policy?: string): ChartMarker[] => {
  const targets: (StrategyChartTarget & {decision?: DeskStrategyDecision; recorded?: DeskRecordedStrategyReference; kind: MarkerKind; sample: MarkerSample})[] = []
  if (strategyHistoryMatches(simulation, current) && simulation) {
    for (const row of simulation.decisions) {
      if (row.ticker !== (current?.ticker ?? simulation.ticker) || row.date > (current?.date ?? simulation.through) || !['BUY', 'SELL', 'TRIM'].includes(row.action) || typeof row.weight !== 'number'
          || !Number.isFinite(row.weight) || row.weight < DUST_WEIGHT || row.weight > 1
          || !recordedInstant(row.at) || recordedSession(row.at) !== row.date) continue
      const at = Date.parse(row.at)
      // A simulation decision without an expiry still occupies its own fifteen-minute interval.
      const validUntil = recordedInstant(row.valid_until) && Date.parse(row.valid_until!) > at ? row.valid_until!
        : timeframe === '15m' ? new Date(at + 900000).toISOString() : null
      targets.push({ticker: row.ticker, date: row.date, at: row.at, validUntil, action: row.action === 'BUY' ? 'Buy' : 'Sell', weight: row.weight,
        record: current?.record ?? simulation.provenance.strategy_identity!, decision: row, kind: 'replay',
        sample: markerSample(row.sample ?? simulation.provenance.sample)})
    }
  }
  for (const original of recorded) {
    const day=recordedSession(original.at)
    if (!day || original.ticker!==(current?.ticker ?? simulation?.ticker)) continue
    targets.push({ticker:original.ticker,date:day,at:original.at,validUntil:original.valid_until,action:original.action,
      weight:original.size_weight,record:original.snapshot_id,strategyIdentity:original.strategy_identity,
      entry:{at:original.at,validUntil:original.valid_until},recorded:original,kind:'recorded',sample:'live'})
  }
  // The confirmed current entry sits on the candle it was assessed in, with its own recommendation,
  // so the operator can open the original numerical call; a recorded copy of the same entry is drawn once.
  const currentAlreadyRecorded = current && recorded.some(original=>original.snapshot_id===current.record
    && original.completed_at===current.evidence?.completed_candle_at)
  if (current?.action === 'Buy' && current.weight > 0 && current.entry && !currentAlreadyRecorded) {
    const entrySession = recordedSession(current.entry.at)
    if (entrySession) targets.push({...current, date:entrySession, at:current.entry.at, validUntil:current.entry.validUntil, kind:'current', sample:'live'})
  }
  const markers = new Map<string, ChartMarker>()
  for (const target of targets.sort((a, b) => Date.parse(a.at) - Date.parse(b.at))) {
    if (!target.action) continue
    // A live entry belongs to the interval containing its actual assessment, never its earlier evidence candle.
    const candle = timeframe === '15m' ? bars.find(bar => {
      const start = recordedInstant(bar.time)?.getTime()
      const at = Date.parse(target.at)
      return start != null && target.validUntil != null && start <= at && at < start + 900000
        && at < Date.parse(target.validUntil) && !bar.auction && drawableCandle(bar)
    }) : markerCandle(target.date, bars, timeframe)
    if (!candle) continue
    const time = barStamp(candle, timeframe)
    const key = `${target.kind}:${time}:${target.action}`
    const originalRef = target.recorded ? {snapshot:target.recorded.snapshot_id,completed:target.recorded.completed_at,
      strategy:target.recorded.strategy_identity,at:target.recorded.at,bytesSha:target.recorded.original_bytes_sha256}
      : !target.decision && target.entry && target.strategyIdentity && recordedInstant(target.evidence?.completed_candle_at)
      ? {snapshot:target.record,completed:target.evidence!.completed_candle_at!,strategy:target.strategyIdentity} : undefined
    const recommendation = {id: target.decision?.id ?? (target.recorded ? `recorded:${target.recorded.id}` : `current:${target.ticker}:${target.at}`),
      at: target.at, action: target.action, weight: target.weight, evidence: target.decision?.evidence ?? target.evidence,
      simulated: Boolean(target.decision), originalRef}
    markers.set(key, {id: `strategy:${key}`, time, recommendations: [...(markers.get(key)?.recommendations ?? []), recommendation],
      position: target.action === 'Buy' ? 'belowBar' : 'aboveBar',
      color: replayColor(target.action, target.sample), shape: target.kind === 'current' ? 'square' : 'circle',
      text: targetLabel(target), size: 1, kind: target.kind, sample: target.sample, policy})
  }
  return [...markers.values()]
}

// Draw one current call at the newest candle when no confirmed entry marks it, even when no simulation or recorded row exists.
const currentTargetMarker = (signal: Signals | null | undefined, current: StrategyChartTarget | null | undefined, bars: DeskChartBar[], timeframe: Timeframe, tradeWeight: number | null | undefined, policy?: string): ChartMarker | null => {
  if (!bars.length) return null
  const last = bars[bars.length - 1]
  const time = timeframe === '15m' ? instantStamp(last.time) : stamp(last.date)
  if (!Number.isFinite(time)) return null
  const selected = signal ? boardAction(signal) : null
  const verdict = signal?.verdict ?? (selected?.action === 'Buy' ? 'buy' : selected?.action === 'Sell' ? 'sell' : 'nothing')
  const rawSize = verdict === 'nothing' ? null
    : signal?.size_weight ?? (verdict === 'buy' ? tradeWeight : current?.weight)
  const size = typeof rawSize === 'number' && Number.isFinite(rawSize) ? rawSize : null
  if (verdict === 'nothing') return null
  const action = verdict === 'buy' ? 'Buy' : 'Sell'
  return {id: 'current', time, position: verdict === 'sell' ? 'aboveBar' : verdict === 'buy' ? 'belowBar' : 'aboveBar',
    color: verdict === 'buy' ? '#248a3d' : verdict === 'sell' ? '#b42318' : '#6e6e73', shape: 'square',
    text: size === null ? action : `${action} ${sizePercent(size)}%`, size: 1, kind: 'current', sample: 'live', policy}
}

// A recorded marker drawn over the canvas so it can be hollow; the kind and shape fields stay general for the rare current fallback.
type OverlayMarker = {
  key: string
  kind: 'recorded' | 'current'
  sample: MarkerSample
  shape: 'circle' | 'diamond'
  color: string
  left: number
  top: number
  labelLeft: number
  labelTop: number
  text: string
  policy?: string
  time: number
  recommendations?: ChartMarker['recommendations']
}

type FillMarker = ChartMarker & {side: 'buy' | 'sell'; qty: number}

// Show actual shares filled per candle and side while keeping individual records in the history list.
const groupedFillMarkers = (markers: FillMarker[]): ChartMarker[] => {
  const groups = new Map<string, FillMarker>()
  for (const marker of markers) {
    const key = `${marker.time}:${marker.side}`
    const previous = groups.get(key)
    groups.set(key, {...marker, qty: (previous?.qty ?? 0) + marker.qty})
  }
  return [...groups.values()].map(marker => ({...marker, text: `${marker.side === 'buy' ? 'BUY' : 'SELL'} ${shares(marker.qty)}`}))
}

// Draw simulated quantities on their own candles, retaining BUY/SELL/TRIM separately.
const simulatedTradeMarkers = (simulation: DeskStrategyStock | null | undefined, bars: DeskChartBar[], timeframe: Timeframe): ChartMarker[] => {
  const groups = new Map<string, ChartMarker & {action: string; qty: number}>()
  for (const trade of simulation?.trades ?? []) {
    const at = recordedInstant(trade.at)?.getTime()
    if (at == null || !Number.isFinite(trade.qty) || trade.qty <= 0) continue
    const candle = timeframe === '15m' ? bars.find(bar => {
      const start = recordedInstant(bar.time)?.getTime()
      return start != null && bar.date === trade.date && start <= at && at < start + 900_000 && drawableCandle(bar)
    }) : markerCandle(trade.date, bars, timeframe)
    if (!candle) continue
    const time = timeframe === '15m' ? instantStamp(candle.time!) : stamp(candle.date)
    const key = `${time}:${trade.action}`
    const factor = timeframe === 'weekly' ? (simulation?.splits ?? []).filter(event => event.date > trade.date && event.date <= candle.date).reduce((value, event) => value * event.ratio, 1) : 1
    const qty = (groups.get(key)?.qty ?? 0) + trade.qty * factor
    groups.set(key, {time, action: trade.action, qty, position: trade.action === 'BUY' ? 'belowBar' : 'aboveBar',
      color: trade.action === 'BUY' ? TRADE_BUY : TRADE_SELL, shape: 'circle', text: `${trade.action} ${shares(qty)}`, size: 1})
  }
  return [...groups.values()]
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
      if (!isEqualWeight(policy)) return `${row.action === 'add' ? 'BUY' : 'TRIM'} signal →${percentText(row.target_weight)}`
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
  && typeof fill.qty === 'number' && Number.isFinite(fill.qty) && fill.qty > 0
  && typeof fill.price === 'number' && Number.isFinite(fill.price) && fill.price > 0

// Keep real archived fills oldest first, deduplicating known identities while retaining anonymous multiplicity.
const fillRows = (history: DeskHistory | undefined): DeskHistoryFill[] => {
  const raw: unknown = history?.fills
  const seen = new Set<string>()
  return (Array.isArray(raw) ? raw as DeskHistoryFill[] : []).filter(drawableFill).filter(fill => {
    if (!fill.client_order_id) return true
    if (seen.has(fill.client_order_id)) return false
    seen.add(fill.client_order_id)
    return true
  })
    .sort((a, b) => a.date.localeCompare(b.date))
}

// Merge original order identities only; broker events keep their activity-day multiplicity.
const currentFillRows = (history: DeskHistory | undefined, activity: DeskPaperLive['activity'], recorded: DeskPaperLive['recorded_fills'], ticker: string, now: number): DeskHistoryFill[] => {
  const activitySession = paperActivitySession(activity)
  const confirmed = confirmedPaperFills(recorded, activity, now).filter(fill => fill.symbol === ticker)
  const archived = fillRows(history).filter(fill => fill.client_order_id && fill.date !== activitySession)
  const fresh: DeskHistoryFill[] = []
  for (const fill of confirmed) {
    const instant = recordedInstant(fill.filled_at)
    if (fill.symbol !== ticker || !instant || instant.getTime() > now
      || !['buy', 'sell'].includes(fill.side) || !Number.isFinite(fill.qty) || fill.qty <= 0
      || !Number.isFinite(fill.price) || fill.price <= 0) continue
    const date = paperFillSession(fill.filled_at)
    const row: DeskHistoryFill = {date, side: fill.side, qty: fill.qty, price: fill.price, filled_at: fill.filled_at, client_order_id: fill.client_order_id}
    const byId = fill.client_order_id ? archived.findIndex(saved => saved.client_order_id === fill.client_order_id) : -1
    if (byId >= 0) {archived[byId] = {...archived[byId], ...row}; continue}
    fresh.push(row)
  }
  return [...archived, ...fresh].sort((a, b) => a.date.localeCompare(b.date)
    || (Date.parse(a.filled_at ?? '') || 0) - (Date.parse(b.filled_at ?? '') || 0))
}

// Preserve anonymous archive rows separately because their overlap with identified executions is unresolved.
const LegacyPaperFills = ({ticker, fills}: {ticker: string; fills: DeskHistoryFill[]}) => (
  <div className="mt-2 text-xs text-[#6e6e73]" aria-label={`${ticker} legacy paper evidence`}>
    <p role="status">Legacy paper records have no original order identity and may overlap confirmed executions. They are excluded from confirmed quantities and chart markers.</p>
    <details className="mt-1" aria-label={`${ticker} original legacy paper records`}>
      <summary className="cursor-pointer">Original legacy records ({fills.length}) · overlap unresolved</summary>
      <ul>{fills.map((fill, index) => <li key={index}>
        <time dateTime={fill.filled_at} title={fill.filled_at}>{fill.date}{fill.filled_at ? ` · ${fill.filled_at}` : ''}</time>
        {' · '}{fill.side === 'buy' ? 'BUY' : 'SELL'} {String(fill.qty)} @ ${String(fill.price)}{isRedeploy(fill) ? ' · idle cash put to work' : ''}
      </li>)}</ul>
    </details>
  </div>
)

// Place timestamped fills only on their containing 15-minute candle, never on a nearest substitute.
const currentIntradayMarkers = (fills: DeskHistoryFill[], bars: DeskChartBar[]): FillMarker[] =>
  fills.flatMap(fill => {
    const at = recordedInstant(fill.filled_at)?.getTime()
    if (at == null) return []
    const candle = bars.find(bar => {
      const start = recordedInstant(bar.time)?.getTime()
      return start != null && bar.date === fill.date && start <= at && at < start + 900_000 && drawableCandle(bar)
    })
    return candle ? [{time: instantStamp(candle.time!), position: fill.side === 'buy' ? 'belowBar' as const : 'aboveBar' as const,
      color: fill.side === 'buy' ? TRADE_BUY : TRADE_SELL, shape: 'circle' as const,
      text: tradeText(fill.side, fill.qty, fill.price), side: fill.side, qty: fill.qty, size: 1}] : []
  })

// Whether a fill is the executor's redeploy of idle cash rather than an entry
// or a rotation, as the record names it.
const isRedeploy = (fill: {kind?: string}) => fill.kind === 'redeploy'

// Mark the paper account's real fills as circles on the session they filled,
// below the candle for a buy and above it for a sell, so a decision and the fill
// it led to sit a candle apart on the same picture. A redeploy fill is purple
// and says so; every other fill is blue. The selected multiset is already conserved;
// multiple broker events can share an order ID and must not be deduplicated again.
const fillMarkers = (fills: DeskHistoryFill[], bars: DeskChartBar[], timeframe: Timeframe): FillMarker[] =>
  fills.filter(drawableFill).flatMap(fill => {
    const candle = markerCandle(fill.date, bars, timeframe)
    return candle ? [{
      time: stamp(candle.date),
      position: fill.side === 'buy' ? 'belowBar' as const : 'aboveBar' as const,
      color: fill.side === 'buy' ? TRADE_BUY : TRADE_SELL,
      shape: 'circle' as const,
      text: tradeText(fill.side, fill.qty, fill.price),
      side: fill.side, qty: fill.qty,
      size: 1,
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
  currentPolicy,
  paperActivity,
  paperRecordedFills,
  paperRecordedFillsReason,
  paperAccountUnavailable = false,
  quote,
  live,
  now = Date.now(),
  personalHistory = false,
  personalReceiptId,
  tall = false,
  close,
  closeSession,
  suggestion,
  levels = null,
  strategy = false,
  simulation = null,
  policyReplay: servedReplay = null,
  simulationError = '',
  modelTarget = null,
  allocation,
  boardSignal = null,
}: {
  userId: string
  ticker: string
  history?: DeskHistory
  currentPolicy?: string
  paperActivity?: DeskPaperLive['activity']
  paperRecordedFills?: DeskPaperLive['recorded_fills']
  paperRecordedFillsReason?: DeskPaperLive['recorded_fills_reason']
  paperAccountUnavailable?: boolean
  quote?: LiveQuote
  live?: DeskLive
  now?: number
  personalHistory?: boolean
  personalReceiptId?: string
  tall?: boolean
  // The name's last close, so the session price can fall back to it when no dated quote exists.
  close?: number | null
  closeSession?: string | null
  // The board's levels for this name (the balancer's structure), drawn as
  // labelled horizontal lines on every timeframe; nothing when absent.
  levels?: DeskStructure | null
  // The live suggestion for this name, worded exactly as the board's Action
  // column words it, so the chart's "Now:" line cannot disagree with the row
  // beside it. When absent the chart falls back to the recorded history's
  // latest decision, which is what the board shows only when no live decision
  // exists for the record on screen.
  suggestion?: { word: string; detail: string } | null
  strategy?: boolean
  simulation?: DeskStrategyStock | null
  // The installed policy's own replay, served beside the audited history and kept
  // even when that history is another policy's.
  policyReplay?: DeskPolicyReplay | null
  simulationError?: string
  modelTarget?: StrategyChartTarget | null
  allocation?: DeskModelAllocation
  boardSignal?: Signals | null
}) => {
  const [timeframe, setTimeframe] = useState<Timeframe>('daily')
  // How many sessions of fifteen-minute bars to load; only 15m reads it.
  const [intradaySessions, setIntradaySessions] = useState(DESK_CHART_DEFAULT_SESSIONS['15m'])
  const [showSignals, setShowSignals] = useState(strategy)
  const [showRecommendations, setShowRecommendations] = useState(false)
  // The installed policy's own replay is on by default wherever a chart opens; an older
  // history's recalculated decisions stay off until asked for.
  const [decisionsChoice, setDecisionsChoice] = useState<boolean | null>(null)
  const [showFills, setShowFills] = useState(true)
  const [showResearch, setShowResearch] = useState(strategy)
  const [showPaperFills, setShowPaperFills] = useState(false)
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
  const [rangeReset, setRangeReset] = useState(0)
  const [allSimulatedTrades, setAllSimulatedTrades] = useState(false)
  const [indicatorsOpen, setIndicatorsOpen] = useState(false)
  const [receivedData, setData] = useState<DeskChart | null>(null)
  const [refreshFailed, setRefreshFailed] = useState(false)
  // A timeframe or ticker switch must not reinterpret the previous response while the next loads.
  const requestedSessions = strategy && timeframe === '15m' && fullHistory ? 60 : intradaySessions
  const data = receivedData?.ticker === ticker && receivedData.timeframe === timeframe
    && (timeframe !== '15m' || receivedData.sessions_requested == null || receivedData.sessions_requested === requestedSessions) ? receivedData : null
  const [error, setError] = useState<string | null>(null)
  // The picture failed to draw but the readings below it are still good.
  const [drawFailed, setDrawFailed] = useState(false)
  const [selectedRecommendations, setSelectedRecommendations] = useState<NonNullable<ChartMarker['recommendations']>>([])
  const [markerOverlays, setMarkerOverlays] = useState<OverlayMarker[]>([])
  const [originalReads, setOriginalReads] = useState<Record<string,{status:'pending'|'ready'|'failed'; value?:DeskOriginalStrategyRecommendation}>>({})
  // The header and the current marker read one call, so they cannot disagree.
  const chartAction = modelTarget?.displayAction ?? (!modelTarget?.entry && !modelTarget?.nextSessionPlan ? 'Wait' : modelTarget?.action ?? 'Avoid')
  const displayedTradeWeight = modelTarget && 'tradeWeight' in modelTarget ? modelTarget.tradeWeight : modelTarget?.weight
  const chartSize = displayedTradeWeight == null || displayedTradeWeight <= 0 ? '—' : `${sizePercent(displayedTradeWeight)}%`
  // A plan still waiting for its entry is named by the direction the board shows for it, so the
  // chart header and the row never disagree; "pending" is the badge, not a word.
  const headerWord = chartAction === 'Wait' ? (boardSignal ? boardAction(boardSignal).action ?? '' : '') : chartAction
  const phaseLine = marketPhaseLine(allocation)
  const recordedIdentity = modelTarget?.strategyIdentity ?? (strategyHistoryMatches(simulation, null) ? simulation?.provenance.strategy_identity : undefined)
  const recordedAvailable = strategy && (modelTarget?.recordedHistoryAvailable === true || simulation?.recorded_history_version === 'strategy-recorded-entries/1')
  const recordedScope = JSON.stringify([userId,ticker,recordedIdentity,recordedAvailable])
  const [recordedHistory, setRecordedHistory] = useState<{scope:string;rows:DeskRecordedStrategyReference[];cursor:string|null;busy:boolean;error:string}>({scope:'',rows:[],cursor:null,busy:false,error:''})
  const recordedHistoryRef = useRef(recordedHistory)
  const recordedRequest = useRef(0)
  const recordedRows = recordedHistory.scope === recordedScope ? recordedHistory.rows : []

  // Merge authenticated originals without replacing an earlier decision or letting a late response cross sources.
  const loadRecorded = useCallback(async (before?:string) => {
    if (!recordedAvailable || !recordedIdentity) return
    const request=++recordedRequest.current
    const initial=recordedHistoryRef.current.scope===recordedScope ? recordedHistoryRef.current : {scope:recordedScope,rows:[],cursor:null,busy:false,error:''}
    recordedHistoryRef.current={...initial,busy:true,error:''}
    setRecordedHistory(recordedHistoryRef.current)
    try {
      const page=await getDeskRecordedStrategyRecommendations(userId,ticker,recordedIdentity,before)
      if (request!==recordedRequest.current) return
      const previous=recordedHistoryRef.current
      const merged=new Map(previous.rows.map(row=>[row.id,row]))
      // Compare every original field, independent of JSON property order.
      for (const row of page.items) {
        const original=merged.get(row.id)
        if (original && (Object.keys(row) as (keyof DeskRecordedStrategyReference)[]).some(key=>row[key]!==original[key])) throw new Error('Original recommendation changed')
        merged.set(row.id,row)
      }
      const overlap=page.items.some(row=>previous.rows.some(original=>original.id===row.id))
      const cursor=!before && overlap && previous.rows.length>page.items.length ? previous.cursor : page.next_cursor
      recordedHistoryRef.current={scope:recordedScope,rows:[...merged.values()].sort((a,b)=>b.at.localeCompare(a.at)||b.id.localeCompare(a.id)),cursor:cursor===before ? null : cursor,busy:false,error:''}
      setRecordedHistory(recordedHistoryRef.current)
    } catch {
      if (request!==recordedRequest.current) return
      recordedHistoryRef.current={...recordedHistoryRef.current,busy:false,error:'Recorded recommendations unavailable.'}
      setRecordedHistory(recordedHistoryRef.current)
    }
  },[recordedAvailable,recordedIdentity,recordedScope,userId,ticker])

  // Discover the first saved entry on a new candle or confirmation, retaining originals when the quote expires.
  useEffect(()=>{
    void loadRecorded()
    return()=>{recordedRequest.current++}
  },[loadRecorded,modelTarget?.record,modelTarget?.evidence?.completed_candle_at,Boolean(modelTarget?.entry)])
  const [edgeLabels, setEdgeLabels] = useState<{key: string; text: string; left: number; top: number; color: string; kind?: MarkerKind; recommendations: ChartMarker['recommendations']}[]>([])
  const holder = useRef<HTMLDivElement | null>(null)
  const chartRef = useRef<IChartApi | null>(null)
  const savedView = useRef<{scope: string; first: number; range: {from: number; to: number} | null} | null>(null)
  // Whether the 15m axis currently shows more sessions than a clock label can serve.
  const wideIntraday = useRef(false)
  const markersRef = useRef<ISeriesMarkersPluginApi<Time> | null>(null)
  // The candle series of the current chart, so the board's level lines can be
  // replaced in place when a candle moves them, without redrawing the chart.
  const candlesRef = useRef<ISeriesApi<'Candlestick'> | null>(null)
  const originalSelection=JSON.stringify(selectedRecommendations.filter(item=>item.originalRef).map(item=>({id:item.id,weight:item.weight,...item.originalRef})))

  // Resolve selected live markers to their first saved record; late responses cannot cross selections or users.
  useEffect(()=>{
    let active=true
    const selections=JSON.parse(originalSelection) as {id:string;weight:number;snapshot:string;completed:string;strategy:string;at?:string;bytesSha?:string}[]
    for (const selected of selections) {
      const key=`${userId}:${ticker}:${selected.id}:${selected.snapshot}:${selected.completed}:${selected.strategy}:${selected.weight}:${selected.at ?? ''}:${selected.bytesSha ?? ''}`
      if (originalReads[key]?.status==='ready') continue
      setOriginalReads(current=>({...current,[key]:{status:'pending'}}))
      // Preserve the server's original price, observation time and technical reasons rather than the refreshed row.
      const restore=async()=>{
        try {
          const value=await getDeskOriginalStrategyRecommendation(userId,ticker,selected.snapshot,selected.completed,selected.strategy,selected.weight,
            selected.at && selected.bytesSha ? {at:selected.at,bytesSha:selected.bytesSha} : undefined)
          if (active) setOriginalReads(current=>({...current,[key]:{status:'ready',value}}))
        } catch {
          if (active) setOriginalReads(current=>({...current,[key]:{status:'failed'}}))
        }
      }
      void restore()
    }
    return()=>{active=false}
  },[originalSelection,userId,ticker])

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
  }, [userId, ticker, timeframe, requestedSessions])

  useEffect(() => {
    let live = true
    let request = 0
    // Only the newest request may publish its coherent candle/indicator snapshot.
    const read = (first: boolean) => {
      const sequence = ++request
      // The strategy chart loads the whole replay window (from 2015), so Full history shows every replayed trade and grade change.
      getDeskChart(userId, ticker, timeframe, timeframe === '15m' ? requestedSessions : strategy ? 4000 : DESK_CHART_DEFAULT_SESSIONS[timeframe])
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
  }, [userId, ticker, timeframe, requestedSessions, quote?.bar, quote?.last, strategy])

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
  const decisions = useMemo(() => decisionMarkers(history, merged.bars, timeframe), [history, merged, timeframe])
  const paperActivityWarning = paperAccountUnavailable
    ? 'Paper account is unavailable; execution history could not be verified.'
    : paperActivity?.reason || (paperActivity?.complete === false
    ? 'Broker fill history may be incomplete; other fills may be missing.' : '')
  const fills = useMemo(() => currentFillRows(history, paperActivity, paperRecordedFills, ticker, now), [history, paperActivity, paperRecordedFills, ticker, now])
  const legacyFills = useMemo(() => fillRows(history).filter(fill => !fill.client_order_id), [history])
  const fillMarks = useMemo(() => groupedFillMarkers(fillMarkers(fills, merged.bars, timeframe)), [fills, merged, timeframe])
  // The fifteen-minute layers come timed from the payload rather than dated
  // from the history file, so they are empty on daily and weekly.
  // The 15m view marks the signal on the bar it was made; where a trade fills
  // is the paper account's own fill, drawn from the fills, never projected.
  const timedDecisions = useMemo(() => intradayDecisionMarkers(data), [data])
  // The payload's bar time may be an assumed open/close; require the original execution instant instead.
  const timedFills = useMemo(() => timeframe === '15m' ? groupedFillMarkers(currentIntradayMarkers(fills, merged.bars)) : [], [timeframe, fills, merged])
  const simulatedTrades = useMemo(() => simulatedTradeMarkers(simulation, merged.bars, timeframe), [simulation, merged, timeframe])
  // A paper history is only a replay of the policy that wrote it; hide a retired policy's signals instead of mislabelling them as today's.
  const livePolicy = currentPolicy ?? allocation?.policy
  // Every chart shows the installed policy's decisions and no other's: the policy's own
  // replay when it is served, the audited history only while it is that policy's.
  const policyReplay = servedReplay && servedReplay.status === 'available' && (!livePolicy || servedReplay.policy === livePolicy) ? servedReplay : null
  // The grade arrows come from the installed policy's replay when it carries them,
  // so the chart's grades and its trades are one engine's; an older simulation's
  // grades only when no replay is served.
  const replayGrades = policyReplay?.grades?.length ? policyReplay.grades : null
  const changes = useMemo(() => gradeMarkers(
    strategy && replayGrades ? {rows: replayGrades} : strategy && simulation?.grade_rows ? {rows: simulation.grade_rows} : history,
    merged.bars, timeframe, strategy), [history, simulation, replayGrades, merged, timeframe, strategy])
  const replayHidden = !strategy && !policyReplay && Boolean(history?.policy) && Boolean(livePolicy) && history!.policy !== livePolicy
  const showDecisions = decisionsChoice ?? Boolean(policyReplay)
  const setShowDecisions = setDecisionsChoice
  const replayMarkers = useMemo(() => policyReplay ? policyReplayMarkers(policyReplay, merged.bars, timeframe, livePolicy) : [], [policyReplay, merged, timeframe, livePolicy])
  const auditedCurrent = !!simulation && (!livePolicy || simulation.policy === livePolicy)
  const targetMarkers = useMemo(() => [
    ...replayMarkers,
    ...strategyTargetMarkers(policyReplay || !auditedCurrent ? null : simulation, modelTarget, merged.bars, timeframe, recordedRows, livePolicy),
  ], [simulation, policyReplay, replayMarkers, auditedCurrent, modelTarget, merged, timeframe, recordedRows, livePolicy])
  // The confirmed entry already shows the current call on its own candle; the newest-candle square
  // speaks only when there is no such entry, so one call is never drawn twice.
  const currentMarker = useMemo(() => strategy && !targetMarkers.some(marker => marker.kind === 'current')
    ? currentTargetMarker(boardSignal, modelTarget, merged.bars, timeframe, displayedTradeWeight, livePolicy) : null,
    [strategy, boardSignal, modelTarget, merged, timeframe, displayedTradeWeight, livePolicy, targetMarkers])
  // The one current call the chart states, wherever it is drawn.
  const currentCall = currentMarker ?? targetMarkers.find(marker => marker.kind === 'current') ?? null

  // Clear an inspected recommendation when its ticker or source changes.
  useEffect(() => {setSelectedRecommendations([])}, [ticker, simulation, modelTarget?.record])

  useEffect(() => {
    if (!holder.current || !data || !merged.bars.length) return
    let chart: IChartApi
    try {
      chart = createChart(holder.current, {
        autoSize: true,
        layout: { background: { color: 'transparent' }, textColor: '#6e6e73', fontSize: 11, fontFamily: 'Arial, sans-serif' },
        grid: {
          horzLines: { color: 'rgba(0,0,0,0.05)' },
          vertLines: { color: 'rgba(0,0,0,0.03)' },
        },
        // Leave room for both dated grade arrows and simulated-share labels.
        rightPriceScale: { borderColor: 'rgba(0,0,0,0.1)', ...(strategy ? {scaleMargins: {top: .15, bottom: .15}} : {}) },
        // On 15m the axis shows the clock, in New York time: the library
        // would otherwise write the bar starts as UTC.
        timeScale: timeframe === '15m'
          ? { borderColor: 'rgba(0,0,0,0.1)', rightOffset: 4, minBarSpacing: strategy ? .01 : .5, fixLeftEdge: strategy, fixRightEdge: strategy, timeVisible: true, secondsVisible: false, tickMarkFormatter: (time: Time, kind: TickMarkType) => newYorkTick(time, kind, wideIntraday.current) }
          : { borderColor: 'rgba(0,0,0,0.1)', rightOffset: 4, minBarSpacing: strategy ? .01 : .5, fixLeftEdge: strategy, fixRightEdge: strategy },
        crosshair: { mode: CrosshairMode.Normal },
        // The chart library otherwise trusts navigator.language, which can
        // be a POSIX tag that Intl rejects when it draws the time axis.
        localization: {
          locale: 'en-US',
          // Empty space below zero is chart padding, not a possible stock price.
          priceFormatter: (v: number) => v < 0 ? '' : `$${v.toFixed(2)}`,
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

    const lines = strategy ? [] : linesFor(timeframe)
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

    markersRef.current = createSeriesMarkers(candles, [], {autoScale: !strategy})
    candlesRef.current = candles
    // Leave room for edge labels while keeping recent candles readable.
    // The recent window is the same on every name: on 15m about two to three
    // sessions (27 bars each), daily about three months, weekly about a year,
    // narrowing only as far as a phone's width forces.
    const frameView = () => {
      const width = Math.max(100, (holder.current?.clientWidth ?? 390) - 65)
      const margin = Math.min(90, width * .3)
      if (fullHistory) {
        const padding = merged.bars.length * margin / (width - 2 * margin)
        chart.timeScale().setVisibleLogicalRange({from: -padding, to: merged.bars.length - 1 + padding})
      } else {
        const count = timeframe === '15m'
          ? Math.max(54, Math.min(81, Math.floor((width - margin) / 9)))
          : timeframe === 'weekly' ? Math.max(30, Math.min(60, Math.floor((width - margin) / 12)))
          : Math.max(45, Math.min(80, Math.floor((width - margin) / 9)))
        const padding = Math.min(count, merged.bars.length) * margin / (width - margin)
        chart.timeScale().setVisibleLogicalRange({from: merged.bars.length <= count ? -padding : merged.bars.length - count - padding, to: merged.bars.length - 1 + padding})
      }
    }
    const scope = `${userId}:${ticker}:${timeframe}:${fullHistory}:${rangeReset}`
    if (savedView.current?.scope === scope && savedView.current.range) {
      const shifted = merged.bars.findIndex(bar => Number(barStamp(bar, timeframe)) === savedView.current!.first)
      if (shifted >= 0) chart.timeScale().setVisibleLogicalRange({from: savedView.current.range.from + shifted, to: savedView.current.range.to + shifted})
      else frameView()
    } else frameView()
    // Retain the last observed viewport before a refresh tears down the chart, and reveal older sessions at its edge.
    const observeRange = (range: LogicalRange | null) => {
      if (!range || !holder.current) return
      savedView.current = {scope, first: Number(barStamp(merged.bars[0], timeframe)), range: {...range}}
      wideIntraday.current = range.to - range.from > WIDE_INTRADAY_BARS
      holder.current.dataset.chartFrom = String(range.from)
      holder.current.dataset.chartVisibleBars = String(range.to - range.from)
      if (strategy && timeframe === '15m' && !fullHistory && range.from <= 2
          && merged.bars.length >= requestedSessions * 14 && data.sessions >= requestedSessions && requestedSessions < 60)
        setIntradaySessions(current => Math.min(60, current * 2))
    }
    chart.timeScale().subscribeVisibleLogicalRangeChange(observeRange)
    const initialRange = chart.timeScale().getVisibleLogicalRange()
    observeRange(initialRange)
    // Auto sizing keeps the canvas responsive without resetting the trader's pan or zoom.
    setDrawFailed(false)

    return () => {
      chart.timeScale().unsubscribeVisibleLogicalRangeChange(observeRange)
      chart.remove()
      chartRef.current = null
      markersRef.current = null
      candlesRef.current = null
      drawn.length = 0
    }
  }, [data, merged, timeframe, fullHistory, rangeReset, userId, ticker, requestedSessions, strategy])

  // The board's levels as horizontal lines labelled on the price axis, on
  // every timeframe (the 15m view draws no daily indicator, so this is the
  // only place the operator sees the 21-EMA and the 20-day high against the
  // session's bars). Replaced in place when a candle moves them, so the
  // chart's position and zoom survive; they are shown, never traded on here.
  const ema21Level = levels?.ema_21 ?? null
  const high20Level = levels?.high_20 ?? null
  useEffect(() => {
    const candles = candlesRef.current
    if (!candles || strategy) return
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
  }, [data, merged, timeframe, fullHistory, ema21Level, high20Level, strategy])

  // Update markers in place so receipt-only changes preserve the user's chart position and zoom.
  useEffect(() => {
    // Series points require uniqueness, but distinct markers on the same date must survive.
    // Fifteen-minute grade changes use their original next-open clocks;
    // intraday fills require the original recorded execution instant.
    const markers: ChartMarker[] = [
      ...(personalHistory && showRecommendations && !strategy ? actionMarkers : []),
      ...(showSignals ? changes : []),
      // The paper chart draws the installed policy's replay when it is served, and an
      // older history's recalculated decisions only when no replay is.
      ...(!strategy && showDecisions && !replayHidden ? policyReplay ? replayMarkers : [...decisions, ...timedDecisions] : []),
      ...(showFills ? strategy ? [...targetMarkers.filter(marker => marker.kind !== 'recorded'), ...(currentMarker ? [currentMarker] : [])] : [...fillMarks, ...timedFills] : []),
    ].filter(marker => Number.isFinite(marker.time)).sort((a, b) => Number(a.time) - Number(b.time))
    // Recorded live recommendations are drawn over the canvas as hollow circles: the series
    // marker API has no hollow shape. Replay (circle) and the current call (square) stay on the canvas.
    const overlays = showFills && strategy ? targetMarkers.filter(marker => marker.kind === 'recorded') : []
    const chart = chartRef.current, plugin = markersRef.current, element = holder.current
    if (!chart || !plugin || !element) return
    // The paper chart takes the same label pass as the strategy chart: with the replay
    // drawn beside the fills, two labels on one stretch of a candle were unreadable.
    const measure = document.createElement('canvas').getContext('2d')
    if (measure) measure.font = '11px Arial, sans-serif'
    // Keep every clickable marker; label only those that fit at this zoom, prioritizing selected decisions and grades.
    const paint = () => {
      // Markers on one candle stack, text and all, so their labels never collide; only
      // labels from different candles compete for a stretch of one side.
      const visible = chart.timeScale().getVisibleLogicalRange()
      const zoomedOut = !!visible && visible.to - visible.from > ZOOMED_OUT_BARS
      const shown = zoomedOut ? markers.filter(marker => marker.role !== 'resize') : markers
      const occupied: {left: number; right: number; position: string; time?: unknown}[] = []
      const labelled = new Set<ChartMarker>()
      const edges: typeof edgeLabels = []
      const overlay: OverlayMarker[] = []
      const selected = new Set(selectedRecommendations.map(item => item.id))
      const plotWidth = chart.timeScale().width()
      const textWidth = (text: string) => (measure?.measureText(text).width ?? text.length*7)+12
      // Place each overlay marker on its candle and keep its label inside the plot.
      for (const marker of overlays) {
        const x = chart.timeScale().timeToCoordinate(marker.time)
        if (x == null || x < 0 || x > plotWidth) continue
        const shapeX = Math.max(7, Math.min(x, plotWidth - 7))
        const bar = merged.bars.find(row => Number(barStamp(row, timeframe)) === Number(marker.time))
        const price = marker.kind === 'current'
          ? typeof bar?.close === 'number' ? bar.close : marker.position === 'aboveBar' ? bar?.high : bar?.low
          : marker.position === 'aboveBar' ? bar?.high : bar?.low
        const y = typeof price === 'number' ? candlesRef.current?.priceToCoordinate(price) : null
        if (y == null) continue
        const width = textWidth(marker.text)
        const side = shapeX + width + 16 > plotWidth ? 'left' : 'right'
        const labelLeft = Math.max(6, Math.min(side === 'right' ? shapeX + 10 : shapeX - width - 10, plotWidth - width - 6))
        const labelTop = Math.max(4, Math.min(marker.position === 'aboveBar' ? y - 18 : y + 8, element.clientHeight - 24))
        const span = {left: labelLeft, right: labelLeft + width, position: marker.position}
        // Two labels never share one stretch of a side: the shape stays clickable, the later label is dropped.
        const fits = width <= plotWidth - 12 && !occupied.some(other => other.position === span.position && span.left < other.right+8 && span.right > other.left-8)
        if (fits) occupied.push(span)
        overlay.push({key: marker.id ?? `${marker.kind}:${marker.time}`, kind: marker.kind === 'current' ? 'current' : 'recorded',
          sample: marker.sample ?? 'unknown', shape: marker.kind === 'current' ? 'diamond' : 'circle', color: marker.color,
          left: shapeX, top: Math.max(4, Math.min(y, element.clientHeight - 4)), labelLeft, labelTop,
          text: fits ? marker.text : '', policy: marker.policy, time: marker.time, recommendations: marker.recommendations})
      }
      // Retain the selected action label first, then trades and recommendations: when a
      // buy or sell shares a candle with a grade change, the size is what a person acts on.
      const priority = (marker: ChartMarker) => marker.recommendations?.some(item => selected.has(item.id)) ? 0
        : marker.role === 'entry' || marker.role === 'exit' ? 1 : marker.recommendations ? 2 : 3
      for (const marker of [...shown].sort((a,b) => priority(a)-priority(b) || Number(b.time)-Number(a.time))) {
        const x = chart.timeScale().timeToCoordinate(marker.time)
        if (x == null || x < 0 || x > plotWidth) continue
        const width = textWidth(marker.text)
        if (width > plotWidth-12) continue
        const left = Math.max(6,Math.min(x-width/2,plotWidth-width-6))
        const span = {left,right:left+width,position:marker.position,time:marker.time}
        // The paper chart keeps every fill, decision and grade label it always drew; only
        // the replay's labels give way there, so the replay never buries the account's own record.
        const yields = strategy || marker.kind === 'replay'
        if (yields && occupied.some(other => other.position === span.position && other.time !== span.time && span.left < other.right+8 && span.right > other.left-8)) continue
        occupied.push(span)
        if (Math.abs(left-(x-width/2))<1) {labelled.add(marker);continue}
        const bar = merged.bars.find(row=>Number(barStamp(row,timeframe))===Number(marker.time))
        const price = marker.position==='aboveBar' ? bar?.high : bar?.low
        const y = typeof price==='number' ? candlesRef.current?.priceToCoordinate(price) : null
        if (y != null) edges.push({key:marker.id ?? `${marker.time}:${marker.position}`,text:marker.text,left,
          top:Math.max(4,Math.min(y+(marker.position==='aboveBar' ? -30 : 12),element.clientHeight-44)),
          color:marker.color,kind:marker.kind,recommendations:marker.recommendations})
      }
      plugin.setMarkers(shown.map(marker => labelled.has(marker) ? marker : {...marker,text:''}))
      setEdgeLabels(previous=>JSON.stringify(previous)===JSON.stringify(edges) ? previous : edges)
      setMarkerOverlays(previous=>JSON.stringify(previous)===JSON.stringify(overlay) ? previous : overlay)
      element.dataset.markerCount = String(shown.length)
      // What this paint drew and labelled, for an audit to compare with the replay: every
      // shown marker as time|role|text, the labelled times, and the visible time range.
      element.dataset.markerSet = JSON.stringify(shown.map(marker => `${marker.time}|${marker.role ?? marker.kind ?? 'grade'}|${marker.text}`))
      element.dataset.markerLabelled = JSON.stringify([...new Set([...[...labelled].map(marker => Number(marker.time)), ...edges.map(label => {
        const marker = shown.find(item => (item.id ?? `${item.time}:${item.position}`) === label.key)
        return marker ? Number(marker.time) : null
      }).filter(time => time != null)])])
      const range = chart.timeScale().getVisibleRange()
      element.dataset.visibleRange = range ? `${Number(range.from)}-${Number(range.to)}` : ''
      element.dataset.zoomedOut = String(zoomedOut)
      element.dataset.markerLabelCount = String(labelled.size+edges.length+overlay.filter(marker => marker.text).length)
      element.dataset.markerLabelSpans = JSON.stringify(occupied)
      element.dataset.overlayMarkerCount = String(overlay.length)
      element.dataset.currentMarker = currentCall?.text ?? ''
    }
    paint()
    chart.timeScale().subscribeVisibleLogicalRangeChange(paint)
    const observer = new ResizeObserver(paint)
    observer.observe(element)
    return () => {observer.disconnect();chart.timeScale().unsubscribeVisibleLogicalRangeChange(paint)}
  }, [data, merged, timeframe, fullHistory, showSignals, showRecommendations, showDecisions, showFills, showPaperFills, actionMarkers, changes, decisions, fillMarks, timedDecisions, timedFills, personalHistory, strategy, targetMarkers, replayMarkers, policyReplay, currentMarker, currentCall, replayHidden, selectedRecommendations, rangeReset, userId, ticker, requestedSessions])

  // Open the original evidence behind a clicked marker or its corresponding candle.
  useEffect(() => {
    const chart = chartRef.current
    if (!strategy || !chart || !showFills) return
    const select = (event: {time?: Time; hoveredObjectId?: unknown}) => {
      const exact = targetMarkers.find(marker => marker.id === event.hoveredObjectId)
      const matching = exact ? [exact] : targetMarkers.filter(marker => marker.time === event.time)
      setSelectedRecommendations(matching.flatMap(marker => marker.recommendations ?? []))
    }
    chart.subscribeClick(select)
    return () => {chart.unsubscribeClick(select)}
  }, [data, merged, timeframe, fullHistory, rangeReset, requestedSessions, strategy, showFills, targetMarkers])

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
  // Center the latest simulated action without inventing bars outside the loaded window.
  const focusLastTrade = () => {
    const marker = [...simulatedTrades].sort((a, b) => Number(b.time) - Number(a.time))[0]
    if (!marker || !chartRef.current) return
    const index = merged.bars.findIndex(bar => Number(barStamp(bar, timeframe)) === Number(marker.time))
    const half = timeframe === 'weekly' ? 1.5 : 5
    if (index >= 0) chartRef.current.timeScale().setVisibleLogicalRange({from: index - half, to: index + half})
  }

  // Bring a selected historical action and its subsequent candles into view.
  const inspectRecommendation = (item: NonNullable<ChartMarker['recommendations']>[number]) => {
    setSelectedRecommendations([item])
    const marker = targetMarkers.find(point => point.recommendations?.some(row => row.id === item.id))
    const index = marker ? merged.bars.findIndex(bar => Number(barStamp(bar, timeframe)) === Number(marker.time)) : -1
    if (index >= 0) chartRef.current?.timeScale().setVisibleLogicalRange({from: Math.max(0, index - 8), to: Math.min(merged.bars.length - 1, index + (timeframe === '15m' ? 40 : 20))})
  }

  // Reset a range preset even when the trader has manually zoomed within that same preset.
  const resetRange = (full: boolean) => {
    setFullHistory(full)
    setRangeReset(value => value + 1)
  }

  // Offer accessible zoom controls while respecting the loaded candle boundaries.
  const zoomRange = (factor: number) => {
    const scale = chartRef.current?.timeScale(), range = scale?.getVisibleLogicalRange()
    if (!scale || !range || merged.bars.length < 2) return
    const span = Math.max(Math.min(8, merged.bars.length - 1), Math.min(merged.bars.length - 1, (range.to - range.from) * factor))
    const start = Math.max(0, Math.min(merged.bars.length - 1 - span, (range.from + range.to - span) / 2))
    scale.setVisibleLogicalRange({from: start, to: start + span})
  }

  const replayStale = !!(simulation && livePolicy && simulation.policy !== livePolicy) && !policyReplay
  // The pressed timeframe and range read like the board's filter chips.
  const chip = (on: boolean) => `rounded border px-2 py-0.5 text-xs ${on ? 'border-[#0071e3] bg-[#e8f2ff] font-medium text-[#0071e3]' : 'border-black/[0.08] text-[#6e6e73]'}`
  if (strategy) return <section className="mb-4" aria-label={`${ticker} price chart`}>
    {live && <div className="mb-2 text-xs"><SessionPrice live={live} ticker={ticker} now={now} close={close} closeSession={closeSession} compact /></div>}
    <div className="mb-2 flex flex-wrap items-center justify-between gap-2 text-xs">
      {modelTarget ? (modelTarget.action === 'Buy' || modelTarget.displayAction ? <div className="flex items-center gap-2">
        <span title={modelTarget.entry ? `${recordedTime(modelTarget.entry.at)} · Confirmed entry; ${recordedTime(modelTarget.entry.validUntil)} expiry` : modelTarget.entryReason} className={`font-semibold ${headerWord === 'Sell' ? 'text-[#b42318]' : headerWord === 'Buy' ? 'text-[#248a3d]' : 'text-[#6e6e73]'}`} aria-label={`${ticker} current chart target`}>
          {headerWord === 'Buy' || headerWord === 'Sell' ? chartSize === '—' ? headerWord : `${headerWord} ${chartSize}` : ''}
        </span>
        {chartAction === 'Wait' && headerWord && <span className="rounded bg-[#eef1f6] px-1.5 py-0.5 text-[10px] font-medium text-[#3a3a3c]" aria-label={`${ticker} chart entry state`}>pending</span>}
        {modelTarget.positionWeight != null && <span className="text-[#6e6e73]" aria-label={`${ticker} current chart position`}>Position {sizePercent(modelTarget.positionWeight)}%</span>}
        {modelTarget.nextSessionPlan && <span className="text-[#6e6e73]" aria-label={`${ticker} chart plan timing`}>{modelTarget.atOpen ? 'At open' : 'Next session'}</span>}
      </div> : null) : <span className="text-[#6e6e73]" aria-label={`${ticker} current chart target`}></span>}
      <div role="group" aria-label="Chart timeframe" className="flex gap-1">
        {(['15m', 'daily', 'weekly'] as const).map(frame => <button key={frame} type="button" aria-pressed={timeframe === frame} className={chip(timeframe === frame)} onClick={() => setTimeframe(frame)}>{frame === 'daily' ? 'D' : frame === 'weekly' ? 'W' : '15m'}</button>)}
      </div>
      <div role="group" aria-label="Chart range" className="flex gap-1">
        <button type="button" aria-pressed={!fullHistory} className={chip(!fullHistory)} onClick={() => resetRange(false)}>Recent</button>
        <button type="button" aria-pressed={fullHistory} className={chip(fullHistory)} onClick={() => resetRange(true)}>{timeframe === '15m' ? '60 sessions' : 'Full history'}</button>
      </div>
      <div role="group" aria-label="Chart zoom" className="flex gap-1">
        <button type="button" aria-label="Zoom in" title="Zoom in" className={chip(false)} onClick={() => zoomRange(2 / 3)}>+</button>
        <button type="button" aria-label="Zoom out" title="Zoom out" className={chip(false)} onClick={() => zoomRange(1.5)}>−</button>
      </div>
      <label className="flex items-center gap-1"><input type="checkbox" checked={showFills} onChange={event => setShowFills(event.target.checked)} />Buy / Sell</label>
      <label className="flex items-center gap-1"><input type="checkbox" checked={showSignals} onChange={event => setShowSignals(event.target.checked)} />Grades</label>
    </div>
    {/* One line names the replay, and says when it is a policy the desk has since replaced; the
        method and its limits stay a click away. The window stays even when the replay is unavailable. */}
    <div aria-label={`${ticker} strategy chart window`} data-strategy-policy={simulation?.policy ?? livePolicy ?? ''}
      data-model-fit-through={simulation?.provenance.model_fit_through ?? ''}
      data-next-publication={allocation?.status === 'awaiting_nightly' ? allocation.next_publication_at ?? '' : ''}
      className="mb-2 flex flex-wrap items-center gap-x-2 text-[11px] text-[#6e6e73]">
      <span>{policyReplay
        ? `Replay · ${policyReplay.policy} · ${policyReplay.start} → ${policyReplay.through}`
        : simulation && !replayStale ? `Replay · ${simulation.policy}${simulation.provenance.model_fit_through ? ` · fit through ${simulation.provenance.model_fit_through}` : ''}`
        : `Replay · ${livePolicy ?? 'policy'} · not yet generated`}</span>
      {(policyReplay || (simulation && !replayStale)) && <details aria-label={`${ticker} replay basis`} className="inline">
        <summary className="cursor-pointer text-[#0071e3]">about</summary>
        {policyReplay ? <>
          <span className="block">{policyReplay.note}</span>
          {replayOutcomeLine(policyReplay) && <span className="block">{replayOutcomeLine(policyReplay)}</span>}
          <span className="block">Buy opens a position and Sell closes it; Add and Trim show the change since the last marker and the position after it, drawn once the position has moved 2% of the book. FOMC cuts and restorations are always drawn. Zoomed out past {ZOOMED_OUT_BARS} bars, adds and trims are hidden; every entry, exit and FOMC step stays.</span>
        </> : <>
          <span className="block">Historical replay of {simulation!.policy} · {simulation!.start} → {simulation!.through} · models were not refitted at each past date · not out-of-sample validation or advice published at that time.</span>
          {typeof simulation!.in_sample_decisions === 'number' && typeof simulation!.out_of_sample_decisions === 'number'
            && <span className="block">{simulation!.in_sample_decisions} decisions in-sample, {simulation!.out_of_sample_decisions} after the fit date{dustTrades(simulation) > 0 ? ` · ${dustTrades(simulation)} trades under 0.5% not drawn` : ''}.</span>}
        </>}
      </details>}
    </div>
    {/* A name the grades reached but the replay never sized is the most puzzling chart on the desk: say so instead of showing arrows with no circles. */}
    {strategy && policyReplay && !policyReplay.trades.some(trade => trade.target > 0) && <p aria-label={`${ticker} replay without trades`} className="mb-2 text-[11px] text-[#6e6e73]">
      {(policyReplay.grades ?? policyReplay.rows).some(row => row.grade === 'A' || row.grade === 'A+')
        ? `The rule never held ${ticker} in this window: the sessions it graded A or A+ never gave it a slot.`
        : `The rule never held ${ticker}: it never graded A or A+ in this window.`}
    </p>}
    {strategy && !policyReplay && simulation && !replayStale && simulation.decisions.length === 0 && <p aria-label={`${ticker} replay without trades`} className="mb-2 text-[11px] text-[#6e6e73]">
      {!simulation.grade_rows?.some(row => row.grade === 'A' || row.grade === 'A+')
        ? `The replay never bought ${ticker}: it never graded A or A+ in this window, so there was no trade to draw.`
        : simulation.targets.some(row => typeof row.weight === 'number' && row.weight > 0)
          ? `The replay never bought ${ticker}: the sizing model set a target while it graded A or A+, but no trade could be priced or executed in the replay. The grade arrows above are the direction; there was no trade to draw.`
          : `The replay never bought ${ticker}: on every session it graded A or A+, the sizing model's target stayed at zero. The grade arrows above are the direction; there was no sized trade to draw.`}
    </p>}
    {phaseLine && <p aria-label={`${ticker} market phase`} data-market-phase={allocation?.market_phase?.phase} className="mb-2 text-[11px] text-[#6e6e73]">{phaseLine}</p>}
    {error && <p role="alert" className="text-xs text-[#b42318]">{error}</p>}
    {!error && !data && <p className="text-xs text-[#6e6e73]">Loading…</p>}
    {data && <>
      <div className="relative">
        <div ref={holder} title="Click a Buy or Sell marker to inspect the evidence from that decision." className={`w-full ${drawFailed ? 'hidden' : tall ? 'h-[62vh] min-h-80' : 'h-72'}`} data-testid="ticker-chart-canvas" data-chart-timeframe={data.timeframe} data-bar-count={merged.bars.length} />
        {strategy && !drawFailed && edgeLabels.map(label=><button key={label.key} data-marker-edge-id={label.key} data-marker-kind={label.kind} type="button" className="absolute z-10 whitespace-nowrap border-0 bg-transparent p-0 text-[11px]" style={{left:label.left+6,top:label.top,color:label.color,fontFamily:'Arial, sans-serif'}} onClick={()=>setSelectedRecommendations(label.recommendations ?? [])}>{label.text}</button>)}
        {strategy && !drawFailed && markerOverlays.map(marker => <div key={marker.key} className="pointer-events-none absolute inset-0 z-10">
          <button type="button" data-marker-kind={marker.kind} data-marker-sample={marker.sample} data-marker-policy={marker.policy}
            data-marker-time={marker.time} data-marker-shape={marker.shape} data-marker-overlay-id={marker.key}
            aria-label={`${ticker} ${marker.kind} marker ${marker.text}`} title={marker.text}
            className="pointer-events-auto absolute border-0 bg-transparent p-0" style={{left:marker.left-7,top:marker.top-7,width:14,height:14}}
            onClick={()=>setSelectedRecommendations(marker.recommendations ?? [])}>
            <svg width="14" height="14" viewBox="0 0 14 14" aria-hidden="true">
              {marker.shape === 'diamond'
                ? <polygon points="7,1 13,7 7,13 1,7" fill={marker.kind === 'current' && marker.color !== '#6e6e73' ? marker.color : 'none'} stroke={marker.color} strokeWidth="1.5" />
                : <circle cx="7" cy="7" r="5" fill="none" stroke={marker.color} strokeWidth="2" />}
            </svg>
          </button>
          {marker.text && <button type="button" data-marker-kind={marker.kind} data-marker-sample={marker.sample} data-marker-policy={marker.policy}
            data-marker-time={marker.time} data-marker-label={marker.text} aria-label={`${ticker} ${marker.kind} marker label ${marker.text}`}
            className="pointer-events-auto absolute whitespace-nowrap border-0 bg-transparent p-0 text-[11px]"
            style={{left:marker.labelLeft,top:marker.labelTop,color:marker.color,fontFamily:'Arial, sans-serif'}}
            onClick={()=>setSelectedRecommendations(marker.recommendations ?? [])}>{marker.text}</button>}
        </div>)}
      </div>
      {drawFailed && <p role="alert" className="text-xs text-[#b42318]">Chart unavailable</p>}
      {refreshFailed && <p role="status" className="text-xs text-[#9a6700]">Refresh failed · last snapshot</p>}
      {data.data_status && data.data_status !== 'complete' && <p role="status" className="text-xs text-[#9a6700]">Price history {data.data_status}</p>}
      {simulationError && <p role="status" className="text-xs text-[#6e6e73]" title={simulationError}>Size history unavailable</p>}
      {showFills && <p className="sr-only" aria-label={`${ticker} target chart markers`} data-marker-times={targetMarkers.map(marker => marker.time).join(',')}>{targetMarkers.map(marker => marker.text).join(' · ')}</p>}
      {showFills && currentCall && <p className="sr-only" aria-label={`${ticker} current chart marker`} data-current-marker-time={currentCall.time} data-current-marker-label={currentCall.text}>{currentCall.text}</p>}
      {showSignals && <p className="sr-only" aria-label={`${ticker} grade signals`}>{changes.length} grade changes marked.</p>}
      {selectedRecommendations.length > 0 && <section aria-label="Recommendation details" className="mt-3 rounded-lg border border-black/10 p-3 text-sm">
        <button type="button" aria-label="Close recommendation details" className="float-right text-[#6e6e73]" onClick={() => setSelectedRecommendations([])}>×</button>
        {selectedRecommendations.map(selected => {
          const reference=selected.originalRef
          const read=reference ? originalReads[`${userId}:${ticker}:${selected.id}:${reference.snapshot}:${reference.completed}:${reference.strategy}:${selected.weight}:${reference.at ?? ''}:${reference.bytesSha ?? ''}`] : undefined
          const original=selected.originalRef && read?.status==='ready' ? read.value?.original : undefined
          const item=original ? {...selected,at:original.at,weight:original.size_weight,evidence:original.evidence} : selected
          return <article key={item.id} className="mb-3 last:mb-0">
          <h4 title={`Exact action size ${(item.weight * 100).toPrecision(6)}%`} className={`font-semibold ${item.action === 'Buy' ? 'text-[#248a3d]' : 'text-[#b42318]'}`}>{item.action} {sizePercent(item.weight)}%</h4>
          <p className="text-xs text-[#6e6e73]">{item.simulated ? 'Simulation' : original ? 'Recorded recommendation' : 'Model position'} · {recordedTime(item.at)}</p>
          {item.simulated && <p className="text-xs text-[#6e6e73]">Current-model replay; not out-of-sample evidence.</p>}
          {item.simulated && <p className="mt-2 text-xs text-[#6e6e73]">Trade amount as a percentage of the portfolio at that time, not the total position. Buy and sell percentages from different dates cannot be added as share quantities.</p>}
          {selected.originalRef && !original ? <p role="status" className="mt-2">{read?.status==='failed' ? 'Original recommendation unavailable.' : 'Loading original recommendation…'}</p> : item.evidence ? <>
            <p className="mt-2">{item.evidence.reason}</p>
            {item.evidence.grade && <p>Grade {item.evidence.grade}{item.evidence.inputs_as_of ? ` · ${item.evidence.inputs_as_of} close` : ''}</p>}
            {typeof item.evidence.model_position_size === 'number' && <p>Model position size {(item.evidence.model_position_size * 100).toFixed(1)}%</p>}
            {typeof item.evidence.observed_price === 'number' && <p>{item.simulated ? 'Candle close' : 'Observed IEX midpoint'} ${item.evidence.observed_price.toFixed(2)} · {item.simulated ? 'adjusted historical basis' : 'current share basis'}</p>}
            <StrategyTechnicalEvidence evidence={item.evidence} />
            <p className="mt-2">{item.evidence.timing_reason === 'mandatory_grade_exit' ? 'Below-A exit at the next open.' : item.evidence.timing_reason === 'shared_terminal_deadline' ? 'Regular-session execution deadline reached.' : typeof item.evidence.waiting_log_utility === 'number' ? 'Acting now matched or exceeded the model’s expected net growth from waiting one 15-minute candle.' : 'Detailed entry timing was not recorded.'}</p>
          </> : <p className="mt-2 text-xs text-[#6e6e73]">Detailed evidence was not recorded for this marker.</p>}
        </article>})}
      </section>}
      {showFills && (targetMarkers.length > 0 || recordedAvailable) && <details className="mt-2 text-xs">
        <summary className="cursor-pointer text-[#0071e3]">Recommendations</summary>
        {simulation && <p className="pt-2 text-[#6e6e73]">Simulation · {simulation.start}–{simulation.through}</p>}
        <div className="flex flex-wrap gap-2 pt-2">{targetMarkers.flatMap(marker => marker.recommendations ?? []).map(item => <button type="button" key={item.id} data-recommendation-id={item.id} title={`Exact action size ${(item.weight * 100).toPrecision(6)}%`} className="rounded border border-black/10 px-2 py-1" onClick={() => inspectRecommendation(item)}>{item.action} {sizePercent(item.weight)}% · {recordedTime(item.at)}</button>)}</div>
        {recordedHistory.scope===recordedScope && recordedHistory.error && <p role="status" className="pt-2">{recordedHistory.error} <button type="button" className="text-[#0071e3]" disabled={recordedHistory.busy} onClick={()=>void loadRecorded()}>Retry</button></p>}
        {recordedHistory.scope===recordedScope && recordedHistory.cursor && <button type="button" className="pt-2 text-[#0071e3]" disabled={recordedHistory.busy} onClick={()=>void loadRecorded(recordedHistory.cursor!)}>Earlier recorded recommendations</button>}
      </details>}
      <ul className="sr-only" aria-label={`${ticker} historical grade signals`}>{changes.map((marker, index) => <li key={`${marker.time}-${index}`}>{marker.detail}</li>)}</ul>
    </>}
  </section>

  return (
    <section className="mb-4" aria-label={`${ticker} price chart`}>
      {live && <div className="mb-2 text-xs"><SessionPrice live={live} ticker={ticker} now={now} close={close} closeSession={closeSession} /></div>}
      <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
        <h4 className="text-xs font-medium text-[#1d1d1f]">
          {strategy ? 'Price, simulated trades and grade changes' : 'Price, indicators and grade history'}
        </h4>
        <div className="flex flex-wrap gap-1">
          <div className="flex gap-1" role="group" aria-label="Chart range">
          <button type="button" aria-pressed={!fullHistory} className="rounded px-2 py-0.5 text-xs" onClick={() => setFullHistory(false)}>Recent</button>
          <button type="button" aria-pressed={fullHistory} className="rounded px-2 py-0.5 text-xs" onClick={() => setFullHistory(true)}>Full history</button>
          </div>
          {personalHistory && !strategy && <label className="mr-2 flex items-center gap-1 text-[11px] text-[#6e6e73]" title="Your saved personal Buy and Sell recommendations, recorded at generation time; not fills.">
            <input type="checkbox" checked={showRecommendations} onChange={event => setShowRecommendations(event.target.checked)} />
            Saved recommendations
          </label>}
          {<label className="mr-2 flex items-center gap-1 text-[11px] text-[#6e6e73]" title={strategy ? 'Dated grade changes; these do not imply a simulated trade or share size.' : 'Grade-led BUY/SELL signals at the A boundary. Saved nightly grades where available; otherwise recalculated grades. These are signals, not fills.'}>
            <input type="checkbox" checked={showSignals} onChange={event => {setShowSignals(event.target.checked); if (strategy && event.target.checked) setShowPaperFills(false)}} />
            {strategy ? 'Grade changes' : 'Grade signals'}
          </label>}
          {!strategy && !replayHidden && <label className="mr-2 flex items-center gap-1 text-[11px] text-[#6e6e73]" title="Historical decisions recalculated under the displayed policy. These are not recorded live recommendations or paper fills.">
            <input type="checkbox" checked={showDecisions} onChange={event => setShowDecisions(event.target.checked)} />
            Policy replay
          </label>}
          {(strategy || fills.length > 0) && <label className="mr-2 flex items-center gap-1 text-[11px] text-[#6e6e73]">
            <input type="checkbox" checked={showFills} onChange={event => {setShowFills(event.target.checked); if (strategy && event.target.checked) setShowPaperFills(false)}} />
            {strategy ? 'Simulated trades' : 'Paper trades'}
          </label>}
          {strategy && <label className="mr-2 flex items-center gap-1 text-[11px] text-[#6e6e73]">
            <input type="checkbox" checked={showPaperFills} onChange={event => {setShowPaperFills(event.target.checked); if (event.target.checked) {setShowSignals(false); setShowFills(false)}}} />
            Actual paper executions
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

      {!strategy && replayHidden && <p aria-label={`${ticker} hidden policy replay`} className="mb-2 text-[11px] text-[#6e6e73]">
        replay of {history?.policy} hidden: differs from live policy {livePolicy}
      </p>}
      {/* The paper chart names the same replay the strategy chart draws, so the account's
          fills can be read against what the installed rule would have done. */}
      {!strategy && policyReplay && showDecisions && <p aria-label={`${ticker} paper chart replay`} className="mb-2 text-[11px] text-[#6e6e73]">
        Replay · {policyReplay.policy} · {policyReplay.start} → {policyReplay.through} · Buy/Sell circles are the installed rule's own decisions back in time, filled at the next open; they are not this account's fills.
      </p>}
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
            data-chart-timeframe={data.timeframe}
            data-bar-count={merged.bars.length}
          />
          {drawFailed && (
            <p className="rounded bg-[#f5f5f7] p-2 text-xs text-[#6e6e73]">
              The chart could not be drawn from this data. The readings below are unaffected.
            </p>
          )}
          {timeframe === '15m'
            ? <p className="mt-1 text-[11px] text-[#6e6e73]" aria-label="Fifteen-minute chart caption">
              Latest session: {data.bars[data.bars.length - 1]?.date ?? 'unavailable'}.{' '}
              {data.sessions} {data.live_feed ? '' : 'complete '}session{data.sessions === 1 ? '' : 's'} of fifteen-minute (15m) bars loaded ({merged.bars.length} bars, New York time).
              {showDecisions && !replayHidden && (policyReplay ? ' Replay markers sit on the first bar of the session the trade fills at the open.' : ' Policy replay uses the last regular bar of its decision session.')}
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
          <details className="mt-1 text-[11px] text-[#6e6e73]" aria-label="Chart legend">
            <summary className="cursor-pointer">Chart key</summary>
            <p>
            {strategy ? showPaperFills ? 'Circles: confirmed actual paper executions. Original fills and prices are listed below.' : 'Filled circles: replayed BUY/SELL/TRIM sizes, muted when in-sample. Hollow circles: recorded live recommendations. Square: the current call. Arrows: grade changes, not additional trades.' : `Circles: shares filled per ${timeframe === 'weekly' ? 'week' : timeframe === 'daily' ? 'day' : '15-minute bar'}. Individual fills and prices below (unadjusted).`}{showSignals ? ' Grade readings are labelled Saved or Recalculated when known.' : ''}{!strategy && showDecisions && !replayHidden ? policyReplay ? ' Buy/Sell circles: the installed policy replay, not fills.' : ' Signal and RESET labels: policy replay, not trades.' : ''}{!strategy && personalHistory && showRecommendations ? ' Saved Buy/Sell labels: recommendations, not fills.' : ''}
            </p>
          </details>
          {!strategy && timeframe === '15m' && fills.some(fill => !recordedInstant(fill.filled_at)) && <p aria-label="Fill timing" className="mt-1 text-[11px] text-[#6e6e73]">Some fills have no recorded time; listed below, not marked on 15m.</p>}
          <p aria-label="Chart refresh status" role={refreshFailed ? 'status' : undefined} className="mt-1 text-[11px] text-[#6e6e73]">Regular-session chart · refresh 20s{data.live_feed ? ` · ${data.live_feed.toUpperCase()}` : ''}{data.live_as_of ? ` · checked ${recordedTime(data.live_as_of)}` : ''}{refreshFailed ? ' · Refresh failed; showing last snapshot' : data.live_reason ? ` · ${data.live_reason}` : ''}</p>
          {!strategy && showDecisions && !replayHidden && !policyReplay && history?.policy && <p className="mt-1 text-[11px] text-[#6e6e73]" aria-label="Policy decision note">
            {history.policy}: {DECISION_NOTE}
          </p>}
          {!strategy && !replayHidden && !policyReplay && history?.policy && currentPolicy && history.policy !== currentPolicy && <details className="mt-1 text-[11px] text-[#6e6e73]" aria-label="Historical policy comparison">
            <summary className="cursor-pointer">Historical policy</summary>
            <p>History uses {history.policy}; the displayed allocation uses {currentPolicy}. Historical replay signals and grade statistics do not describe the current allocator's decisions or performance.</p>
          </details>}
          {/* What the markers mean under the equal-weight policy, and how the
              reset sessions were found: without a clock on file no session is
              a reset, and the chart says so rather than guessing one. */}
          {!strategy && showDecisions && !replayHidden && !policyReplay && isEqualWeight(history?.policy) && <p className="mt-1 text-[11px] text-[#6e6e73]" aria-label="Policy marker legend">
            {EQUAL_WEIGHT_LEGEND}{history?.rebalance_note ? ` ${history.rebalance_note[0].toUpperCase()}${history.rebalance_note.slice(1)}.` : ''}
          </p>}

          {/* The markers are canvas, so the same decisions are written out here:
              the policy's stance today, then the sessions it would have traded
              on, newest first. This list is the decisions, not the markers, so
              the marker checkbox leaves it in place. */}
          {strategy && <details open={showResearch} onToggle={event => setShowResearch(event.currentTarget.open)} className="mt-2 text-xs text-[#6e6e73]" aria-label={`${ticker} strategy simulation`}>
            <summary className="cursor-pointer">Strategy simulation</summary>
            {simulationError ? <p role="alert">{simulationError}</p> : !simulation ? <p>Loading strategy simulation…</p> : <>
              <p>Historical simulation · {simulation.start}–{simulation.through} · {simulation.provenance.cost_bps} bp per side. Simulated executions, not past broker trades.</p>
              <p>Target {simulation.latest_target == null ? 'unavailable' : percent(simulation.latest_target)} · {shares(simulation.latest_holding)} held · {simulation.through}.</p>
              {simulation.trades.length > 0 && <p>Last simulated trade: {simulation.trades[simulation.trades.length - 1].date}. {simulatedTrades.length > 0 && <button type="button" className="text-[#0071e3]" onClick={focusLastTrade}>Go to last trade</button>}</p>}
              {simulatedTrades.length === 0 && <p aria-label="Strategy marker status">No simulated trades in these loaded bars.</p>}
              {showFills && <p aria-label={`${ticker} simulated chart markers`}>{simulatedTrades.map(marker => marker.text).join(' · ') || 'No simulated trade markers.'}</p>}
              {simulation.trades.length > 0 && <ul className="mt-1" aria-label={`${ticker} simulated trades`}>
                {[...simulation.trades].reverse().slice(0, allSimulatedTrades ? undefined : 12).map((trade, index) => <li key={`${trade.id}-${index}`}>
                  {sessionLabel(trade.date, simulation.through.slice(0, 4))} · {newYorkClock(Date.parse(trade.at) / 1000, false)} ET · {trade.action} {shares(trade.qty)} · ${trade.price.toLocaleString('en-US', {minimumFractionDigits: 2, maximumFractionDigits: 6})}
                </li>)}
              </ul>}
              {simulation.trades.length > 12 && <button type="button" className="mt-1 text-[#0071e3]" onClick={() => setAllSimulatedTrades(value => !value)}>{allSimulatedTrades ? 'Show recent trades' : `Show all ${simulation.trades.length} trades`}</button>}
              {simulation.decisions.filter(decision => decision.date === simulation.through && decision.executed_qty < decision.qty).map(decision => <p key={decision.id}>Planned {decision.action} {shares(decision.qty - decision.executed_qty)} · {decision.date} · awaiting simulated execution.</p>)}
              <details className="mt-1"><summary className="cursor-pointer">Simulation basis</summary>
                <p>Policy: {simulation.policy}. {simulation.provenance.basis} Sizes are simulated and trade prices are unadjusted. Current chart signals have not been historically replayed by this allocator simulation.</p>
              </details>
            </>}
          </details>}
          {strategy && showPaperFills && <div className="mt-2 text-xs text-[#6e6e73]" aria-label={`${ticker} actual paper executions`}>
            <p>Confirmed paper fills at their original date, quantity and price. These are executions, not grade signals or research fills.</p>
            {paperRecordedFillsReason && <p role="alert" className="text-[#b42318]">{paperRecordedFillsReason}</p>}
            {paperActivityWarning && <p role="alert" className="text-[#b42318]">{paperActivityWarning}</p>}
            {fills.length === 0 ? !paperRecordedFillsReason && !paperActivityWarning && <p>No confirmed paper executions in the loaded history.</p> : <ul>{[...fills].reverse().map((fill, index) => <li key={`${fill.client_order_id ?? fill.date}-${index}`} data-client-order-id={fill.client_order_id ?? undefined}><time dateTime={fill.filled_at} title={fill.filled_at}>{fill.date}{fill.filled_at ? ` · ${newYorkClock(Date.parse(fill.filled_at) / 1000, false)} ET` : ''}</time> · {tradeText(fill.side, fill.qty, fill.price)}</li>)}</ul>}
            {timeframe === '15m' && fills.some(fill => !recordedInstant(fill.filled_at)) && <p>Fills without a recorded execution time are listed but not marked on 15m.</p>}
          </div>}
          {!strategy && (latestDecision || suggestion || fills.length > 0 || paperRecordedFillsReason || paperActivityWarning) && <div className="mt-2 text-[11px] text-[#6e6e73]" aria-label={`${ticker} decisions`}>
            <p className="font-medium text-[#1d1d1f]" aria-label={`${ticker} now`}>Now: {suggestion ? `${suggestion.word} · ${suggestion.detail}` : 'no paper order'}</p>
            {paperRecordedFillsReason && <p role="alert" className="text-[#b42318]">{paperRecordedFillsReason}</p>}
            {paperActivityWarning && <p role="alert" className="text-[#b42318]">{paperActivityWarning}</p>}
            {fills.length > 0 && <ul className="mt-1" aria-label={`${ticker} paper fills`}>
              {[...fills].reverse().slice(0, 12).map((fill, index) => (
                <li key={`${fill.date}-${fill.side}-${fill.qty}-${index}`}>{sessionLabel(fill.date, currentYear)}{fill.filled_at ? ` · ${newYorkClock(Date.parse(fill.filled_at) / 1000, false)} ET` : ''} · {tradeText(fill.side, fill.qty, fill.price)}{isRedeploy(fill) ? ' · idle cash put to work' : ''}</li>
              ))}
            </ul>}
            {showDecisions && !replayHidden && policyReplay && (!policyReplay.trades.some(trade => trade.target > 0)
              ? <p className="mt-1">The installed rule never traded {ticker} in its replay.</p>
              : <ul className="mt-1" aria-label={`${ticker} strategy signals`}>
                {policyReplay.trades.filter(drawnReplayTrade).slice(-12).reverse().map(trade => {
                  const price = closeOn(trade.date, merged.bars, timeframe)
                  return <li key={`${trade.date}-${trade.action}`}>{sessionLabel(trade.date, currentYear)} · {trade.action === 'BUY' ? 'Buy' : 'Sell'} {sizePercent(trade.size)}% at the open · target {sizePercent(trade.target)}% set at the {trade.decided} close{price !== null ? ` · close $${price.toFixed(2)}` : ''}</li>
                })}
              </ul>)}
            {showDecisions && !replayHidden && !policyReplay && (recentDecisions.length === 0
              ? <p className="mt-1">No policy replay action in the loaded history.</p>
              : <ul className="mt-1" aria-label={`${ticker} strategy signals`}>
                {recentDecisions.map(row => {
                  const price = closeOn(row.date, merged.bars, timeframe)
                  return <li key={row.date}>{sessionLabel(row.date, currentYear)} · {decisionText(row, history?.policy)}{price !== null ? ` · close $${price.toFixed(2)}` : ''}</li>
                })}
              </ul>)}
          </div>}
          {legacyFills.length > 0 && (!strategy || showPaperFills) && <LegacyPaperFills ticker={ticker} fills={legacyFills} />}

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

          {!strategy && <div className="mt-2 text-[11px] text-[#6e6e73]" aria-label="Recorded setup history">
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
          </div>}

          {summary && (
            <details aria-label="Chart indicators" open={indicatorsOpen} onToggle={event => setIndicatorsOpen(event.currentTarget.open)} className="mt-2 text-[11px] text-[#6e6e73]">
            <summary className="cursor-pointer">Indicators &amp; price basis</summary>
            {timeframe === '15m'
              ? <p className="mt-2 text-[11px] text-[#6e6e73]" aria-label="Fifteen-minute price basis">Prices: {data.basis}{strategy ? '; compare simulated trade prices with these original bars.' : '; not adjusted for splits or dividends, so a fill can be checked against the print it crossed at. The daily averages, bands and levels are not drawn at this resolution.'}</p>
              : <p className="mt-2 text-[11px] text-[#6e6e73]">Prices: {data.basis}. {strategy ? 'Indicators describe prices; they do not set the strategy actions.' : 'Indicators can update during a session; weekly overlays include the forming week when present and can differ from a saved grade.'}</p>}
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

          {showSignals && <p aria-label={`${ticker} grade signals`} className="mt-2 text-[11px] text-[#6e6e73]">
            {timeframe === '15m'
              ? 'Grade changes are session readings and are not marked on fifteen-minute bars; switch to D or W to see them.'
              : changes.length === 0
              ? `No grade change marked on these candles.`
              : `${changes.length} grade change${changes.length === 1 ? '' : 's'} marked.`}
          </p>}
          {strategy && showSignals && timeframe !== '15m' && changes.length > 0 && <details className="mt-2 text-xs text-[#6e6e73]">
            <summary className="cursor-pointer">Grade change history</summary>
            <p>Grades at the close on each stated session. Share counts come only from the matching simulation.</p>
            <ul aria-label={`${ticker} historical grade signals`}>{[...changes].reverse().map((change, index) => <li key={`${change.time}-${index}`}>{change.detail}</li>)}</ul>
          </details>}
        </>
      )}
    </section>
  )
}
