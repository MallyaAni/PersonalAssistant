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
  type UTCTimestamp,
} from 'lightweight-charts'
import { getDeskChart, type DeskChart, type DeskChartBar } from '../../services/api'
import type { DeskHistory } from '../../services/api'

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
// The chart itself draws to a canvas, so nothing inside it is readable by a
// test or a screen reader. Every number it shows is therefore mirrored into
// the summary line and the table beneath it, which is what the browser
// tests assert on and what a screen reader announces.

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

// Where price met the desk's entry condition, so the rule can be checked
// against the chart rather than against a table. The grade half is not
// included - these mark a band breakout, and the grade arrows beside them say
// whether the desk wanted the name at the time.
const entryMarkers = (chart: DeskChart | undefined) =>
  (chart?.entries ?? []).map((date) => ({
    time: stamp(date),
    position: 'belowBar' as const,
    color: '#0b5cad',
    shape: 'circle' as const,
    // Price-only evidence cannot claim a funded, grade-qualified buy decision.
    text: 'breakout',
    size: 1,
  }))

// Mark grade changes, with stronger arrows only for recorded desk grades.
const gradeMarkers = (history: DeskHistory | undefined, since: string) => {
  const rows = (history?.rows ?? []).filter((r) => r.date >= since && r.grade)
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
    const up = (rank[now] ?? -1) > (rank[before] ?? -1)
    // Crossing below A can inform an exit, but history does not prove a trade.
    const belowA = wanted(before) && !wanted(now)
    out.push({
      time: stamp(rows[i].date),
      position: up ? 'belowBar' : 'aboveBar',
      color: belowA ? '#b42318' : GRADE_COLOR[now] ?? '#6e6e73',
      shape: up ? 'arrowUp' : 'arrowDown',
      text: belowA ? `below A · ${before}→${now}` : `${before}→${now}`,
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
  tall = false,
}: {
  userId: string
  ticker: string
  history?: DeskHistory
  quote?: LiveQuote
  tall?: boolean
}) => {
  const [timeframe, setTimeframe] = useState<Timeframe>('daily')
  const [showSignals, setShowSignals] = useState(false)
  const [data, setData] = useState<DeskChart | null>(null)
  const [error, setError] = useState<string | null>(null)
  // The picture failed to draw but the readings below it are still good.
  const [drawFailed, setDrawFailed] = useState(false)
  const holder = useRef<HTMLDivElement | null>(null)
  const chartRef = useRef<IChartApi | null>(null)

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
            b.open !== null && b.high !== null && b.low !== null && b.close !== null ? {
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

    const markers = ordered([...gradeMarkers(history, merged.bars[0].date), ...entryMarkers(data)])
    if (showSignals && markers.length) createSeriesMarkers(candles, markers)
    chart.timeScale().fitContent()
    setDrawFailed(false)

    return () => {
      chart.remove()
      chartRef.current = null
      drawn.length = 0
    }
  }, [data, merged, timeframe, history, showSignals])

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

  const changes = useMemo(() => gradeMarkers(history, merged.bars[0]?.date ?? '0000'), [history, merged])

  return (
    <section className="mb-4" aria-label={`${ticker} price chart`}>
      <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
        <h4 className="text-xs font-medium text-[#1d1d1f]">
          Price, indicators and grade history
        </h4>
        <div className="flex gap-1" role="group" aria-label="Chart timeframe">
          <label className="mr-2 flex items-center gap-1 text-[11px] text-[#6e6e73]">
            <input type="checkbox" checked={showSignals} onChange={event => setShowSignals(event.target.checked)} />
            Show signal history
          </label>
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
            {data.sessions} {timeframe === 'weekly' ? 'weeks' : 'sessions'} shown, {data.basis}.
            {' '}Daily and weekly indicator views; observations can update during a session.
            {timeframe === 'weekly' && data.last_bar_complete === false && summary?.last.close !== null &&
              ' Weekly overlays include the forming week and can differ from the weekly inputs of a saved grade.'}
          </p>
          {/* A mark nobody can read is decoration. Both of the desk's rules are
              on the price now, so the legend has to name both. */}
          {showSignals && <p className="mt-1 text-[11px] text-[#6e6e73]">
            <span className="font-medium text-[#0b5cad]">{'●'} breakout</span>{' '}
            marks the incumbent band-breakout price condition, not a Buy instruction.
            Grade, event pauses, cash and position caps also affect the personal plan.{' '}
            <span className="font-medium text-[#b42318]">{'↓'} below A</span>{' '}
            marks a grade crossing below A. Bolder arrows show recorded grades; paler arrows
            show historical grade replays. These markers are not account orders or fills.
          </p>}

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
              ? `No grade change in the drawn window.`
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
