import { useEffect, useMemo, useRef, useState } from 'react'
import {
  CandlestickSeries,
  CrosshairMode,
  LineSeries,
  LineStyle,
  createChart,
  createSeriesMarkers,
  type IChartApi,
  type ISeriesApi,
  type ISeriesMarkersPluginApi,
  type Time,
  type UTCTimestamp,
} from 'lightweight-charts'
import { exportDeskPersonalReceipt, getDeskChart, getDeskPersonalHistory, type DeskPersonalReceipt, type DeskChart, type DeskChartBar } from '../../services/api'
import type { DeskHistory, DeskLive } from '../../services/api'
import { SessionPrice } from './StockBoard'

// The picture behind the grade. The board says what the desk concluded; this
// shows adjusted price indicators beside recorded and replayed grade changes.
// Forming-week overlays may differ from the weekly inputs of a saved grade.
//
// Only daily and weekly exist here because they are the only two timeframes
// the desk reads: the 9/21/50/200 EMAs and the 20-session band are daily,
// and `weekly_trend` and `weekly_stack` come from the 9 and 21 EMAs on
// weekly closes. A monthly view would invite a trader to reason from a bar
// size no analyst looks at, which is the disagreement this chart exists to
// remove.
//
// Canvas content is mirrored into text for screen readers. Browser tests also
// observe actual drawing calls: a correct caption does not prove marker placement.

type Timeframe = 'daily' | 'weekly'

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
// and the 52-week extremes are dotted because they are a boundary rather
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
  { key: 'high_52w', label: '52-week high', color: '#d2d2d7', from: 'levels', dotted: true },
  { key: 'low_52w', label: '52-week low', color: '#d2d2d7', from: 'levels', dotted: true },
  { key: 'band_upper', label: 'Band upper', color: '#c7c7cc', dashed: true },
  { key: 'band_lower', label: 'Band lower', color: '#c7c7cc', dashed: true },
  { key: 'ema9', label: 'EMA 9', color: '#ff9500' },
  { key: 'ema21', label: 'EMA 21', color: '#0071e3' },
  { key: 'ema50', label: 'EMA 50', color: '#5856d6' },
  { key: 'ema200', label: 'EMA 200', color: '#1d1d1f', width: 2 },
]

const WEEKLY_LINES: Line[] = [
  { key: 'ema9', label: 'Weekly EMA 9', color: '#ff9500' },
  { key: 'ema21', label: 'Weekly EMA 21', color: '#0071e3', width: 2 },
]

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
const markerCandle = (session: string, bars: DeskChartBar[], timeframe: Timeframe) => {
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
    const candle = bars.find(bar => timeframe === 'daily'
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

// Mark grade changes only on available candles, retaining their source day within weekly groups.
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
    // Crossing below A can inform an exit, but history does not prove a trade.
    const belowA = wanted(before) && !wanted(now)
    out.push({
      time: stamp(candle.date),
      position: up ? 'belowBar' : 'aboveBar',
      color: belowA ? '#b42318' : GRADE_COLOR[now] ?? '#6e6e73',
      shape: up ? 'arrowUp' : 'arrowDown',
      text: `${rows[i].said ? 'Saved grade' : 'Recalculated grade'}: ${before}→${now}`,
      size: rows[i].said ? 2 : 1,
    })
  }
  return out
}

// Render price indicators and their evidence without implying account execution.
export const TickerChart = ({
  userId,
  ticker,
  history,
  quote,
  live,
  now = Date.now(),
  personalHistory = false,
  personalReceiptId,
  tall = false,
}: {
  userId: string
  ticker: string
  history?: DeskHistory
  quote?: LiveQuote
  live?: DeskLive
  now?: number
  personalHistory?: boolean
  personalReceiptId?: string
  tall?: boolean
}) => {
  const [timeframe, setTimeframe] = useState<Timeframe>('daily')
  const [showSignals, setShowSignals] = useState(true)
  const [showRecommendations, setShowRecommendations] = useState(true)
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
  const [receivedData, setData] = useState<DeskChart | null>(null)
  // A timeframe or ticker switch must not reinterpret the previous response while the next loads.
  const data = receivedData?.ticker === ticker && receivedData.timeframe === timeframe ? receivedData : null
  const [error, setError] = useState<string | null>(null)
  // The picture failed to draw but the readings below it are still good.
  const [drawFailed, setDrawFailed] = useState(false)
  const holder = useRef<HTMLDivElement | null>(null)
  const chartRef = useRef<IChartApi | null>(null)
  const markersRef = useRef<ISeriesMarkersPluginApi<Time> | null>(null)

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
  }, [userId, ticker, timeframe])

  useEffect(() => {
    let live = true
    let request = 0
    // Only the newest request may publish its coherent candle/indicator snapshot.
    const read = (first: boolean) => {
      const sequence = ++request
      getDeskChart(userId, ticker, timeframe)
        .then((payload) => {
          if (!live || sequence !== request) return
          setData(payload)
          setError(null)
        })
        .catch((e: Error) => live && sequence === request && first && setError(e.message))
    }
    read(true)
    // The averages, bands and levels are computed on the server against the
    // live candle, so they only move if the payload is re-read. Without this
    // the candle walked while every line beside it stayed at the last close.
    const timer = window.setInterval(() => read(false), 60_000)
    return () => {
      live = false
      window.clearInterval(timer)
    }
  }, [userId, ticker, timeframe, quote?.bar, quote?.last])

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
        timeScale: { borderColor: 'rgba(0,0,0,0.1)', rightOffset: 4 },
        crosshair: { mode: CrosshairMode.Normal },
        // The chart library otherwise trusts navigator.language, which can
        // be a POSIX tag that Intl rejects when it draws the time axis.
        localization: { locale: 'en-US', priceFormatter: (v: number) => `$${v.toFixed(2)}` },
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
              time: stamp(b.date),
              open: b.open as number,
              high: b.high as number,
              low: b.low as number,
              close: b.close as number,
            } : { time: stamp(b.date) }),
        ),
      )
    } catch {
      chart.remove()
      chartRef.current = null
      setDrawFailed(true)
      return
    }

    const lines = timeframe === 'weekly' ? WEEKLY_LINES : DAILY_LINES
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
            ? { time: stamp(b.date), value: values[i] as number }
            : { time: stamp(b.date) }),
        ),
      )
      drawn.push(series)
    }

    markersRef.current = createSeriesMarkers(candles, [])
    // Give recent candles enough horizontal space; all loaded bars remain available to pan and zoom.
    const frameView = () => {
      if (fullHistory) chart.timeScale().fitContent()
      else {
        const count = Math.max(12, Math.min(40, Math.floor(((holder.current?.clientWidth ?? 390) - 65) / 22)))
        chart.timeScale().setVisibleLogicalRange({from: Math.max(0, merged.bars.length - count), to: merged.bars.length + 1})
      }
    }
    frameView()
    const resize = new ResizeObserver(frameView)
    resize.observe(holder.current)
    setDrawFailed(false)

    return () => {
      chart.remove()
      resize.disconnect()
      chartRef.current = null
      markersRef.current = null
      drawn.length = 0
    }
  }, [data, merged, timeframe, fullHistory])

  // Update markers in place so receipt-only changes preserve the user's chart position and zoom.
  useEffect(() => {
    // Series points require uniqueness, but distinct markers on the same date must survive.
    const markers = [...(personalHistory && showRecommendations ? actionMarkers : []), ...(showSignals ? changes : [])]
      .filter(marker => Number.isFinite(marker.time)).sort((a, b) => Number(a.time) - Number(b.time))
    markersRef.current?.setMarkers(markers)
  }, [data, merged, timeframe, fullHistory, showSignals, showRecommendations, actionMarkers, changes, personalHistory])

  // Everything the canvas shows, in text, for the tests and for anyone not
  // reading pixels. The last drawn bar is the one a trader is looking at.
  const summary = useMemo(() => {
    if (!data || !merged.bars.length) return null
    const last = merged.bars[merged.bars.length - 1]
    const lines = timeframe === 'weekly' ? WEEKLY_LINES : DAILY_LINES
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

  return (
    <section className="mb-4" aria-label={`${ticker} price chart`}>
      {live && <div className="mb-2 text-xs"><SessionPrice live={live} ticker={ticker} now={now} /></div>}
      <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
        <h4 className="text-xs font-medium text-[#1d1d1f]">
          Price, indicators and grade history
        </h4>
        <div className="flex flex-wrap gap-1">
          <div className="flex gap-1" role="group" aria-label="Chart range">
          <button type="button" aria-pressed={!fullHistory} className="rounded px-2 py-0.5 text-xs" onClick={() => setFullHistory(false)}>Recent</button>
          <button type="button" aria-pressed={fullHistory} className="rounded px-2 py-0.5 text-xs" onClick={() => setFullHistory(true)}>Full history</button>
          </div>
          {personalHistory && <label className="mr-2 flex items-center gap-1 text-[11px] text-[#6e6e73]">
            <input type="checkbox" checked={showRecommendations} onChange={event => setShowRecommendations(event.target.checked)} />
            Buy / Sell
          </label>}
          <label className="mr-2 flex items-center gap-1 text-[11px] text-[#6e6e73]">
            <input type="checkbox" checked={showSignals} onChange={event => setShowSignals(event.target.checked)} />
            Grade changes
          </label>
          <div className="flex gap-1" role="group" aria-label="Chart timeframe">
          {(['daily', 'weekly'] as Timeframe[]).map((frame) => (
            <button
              key={frame}
              type="button"
              onClick={() => setTimeframe(frame)}
              aria-pressed={timeframe === frame}
              className={`rounded px-2 py-0.5 text-xs ${
                timeframe === frame
                  ? 'bg-[#1d1d1f] text-white'
                  : 'bg-[#f5f5f7] text-[#6e6e73] hover:text-[#0071e3]'
              }`}
            >
              {frame === 'daily' ? 'D' : 'W'}
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
          <p className="mt-1 text-[11px] text-[#6e6e73]">
            {merged.live && summary?.last.close !== null
              ? `Candle includes the 15-minute bar starting ${new Intl.DateTimeFormat('en-US', {
                  timeZone: 'America/New_York', month: 'short', day: 'numeric', year: 'numeric',
                  hour: 'numeric', minute: '2-digit', timeZoneName: 'short',
                }).format(new Date(data.quote_bar!))}.`
              : `Newest stored ${timeframe === 'weekly' ? 'week' : 'session'}: ${data.bars[data.bars.length - 1]?.date ?? 'unavailable'}${data.last_bar_complete === false ? summary?.last.close === null ? ' (incomplete candle)' : ' (forming candle)' : ''}.`}{' '}
            {merged.bars.length} {timeframe === 'weekly' ? 'weeks' : 'sessions'} loaded; pan or zoom for history.
          </p>
          {showSignals && <p className="mt-1 text-[11px] text-[#6e6e73]" title="Dates identify trading sessions, not publication times. A or A+ meets only the grade requirement for entry; other checks still apply.">
            Saved grades use nightly records; recalculated grades use historical data. Grade changes are not trades.
          </p>}

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
              <p>Prices: {data.basis}. Indicators can update during a session; weekly overlays include a forming week and can differ from a saved grade.</p>
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
            <dl className="mt-2 grid grid-cols-2 gap-x-4 gap-y-1 text-[11px] sm:grid-cols-3">
              <div className="flex justify-between gap-2">
                <dt className="text-[#6e6e73]">{merged.live && summary.last.close !== null ? 'Quote-bar close' : 'Latest stored close'}</dt>
                <dd className="tabular-nums font-medium">
                  {summary.last.close === null ? '—' : `$${summary.last.close.toFixed(2)}`}
                </dd>
              </div>
              {summary.readings.map((reading) => (
                <div key={reading.label} className="flex justify-between gap-2">
                  <dt className="text-[#6e6e73]">{reading.label}</dt>
                  <dd className="tabular-nums">
                    ${reading.value.toFixed(2)}{' '}
                    <span className={reading.away >= 0 ? 'text-[#2da44e]' : 'text-[#b42318]'}>
                      {reading.away >= 0 ? '+' : ''}
                      {reading.away.toFixed(1)}%
                    </span>
                  </dd>
                </div>
              ))}
            </dl>
          )}

          {showSignals && <p className="mt-2 text-[11px] text-[#6e6e73]">
            {changes.length === 0
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
