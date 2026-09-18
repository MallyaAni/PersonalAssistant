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
import { getDeskChart, type DeskChart } from '../../services/api'
import type { DeskHistory } from '../../services/api'

// The picture behind the grade. The board says what the desk concluded; this
// says what it was looking at when it concluded it, on the same adjusted
// basis the analysts score from, with the grade changes marked on the bars
// where they happened.
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

// Grade changes from the replayed history, as one marker per session where
// the letter differs from the session before it. A row the desk actually
// published is marked more strongly than one that is today's rules replayed
// over old prices, because only the first is something the desk said.
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
  for (let i = 1; i < rows.length; i += 1) {
    const before = rows[i - 1].grade
    const now = rows[i].grade
    if (!before || !now || before === now) continue
    const up = (rank[now] ?? -1) > (rank[before] ?? -1)
    out.push({
      time: stamp(rows[i].date),
      position: up ? 'belowBar' : 'aboveBar',
      color: GRADE_COLOR[now] ?? '#6e6e73',
      shape: up ? 'arrowUp' : 'arrowDown',
      text: `${before}→${now}`,
      size: rows[i].said ? 2 : 1,
    })
  }
  return out
}

export const TickerChart = ({
  userId,
  ticker,
  history,
}: {
  userId: string
  ticker: string
  history?: DeskHistory
}) => {
  const [timeframe, setTimeframe] = useState<Timeframe>('daily')
  const [data, setData] = useState<DeskChart | null>(null)
  const [error, setError] = useState<string | null>(null)
  // The picture failed to draw but the readings below it are still good.
  const [drawFailed, setDrawFailed] = useState(false)
  const holder = useRef<HTMLDivElement | null>(null)
  const chartRef = useRef<IChartApi | null>(null)

  useEffect(() => {
    let live = true
    setData(null)
    setError(null)
    getDeskChart(userId, ticker, timeframe)
      .then((payload) => live && setData(payload))
      .catch((e: Error) => live && setError(e.message))
    return () => {
      live = false
    }
  }, [userId, ticker, timeframe])

  useEffect(() => {
    if (!holder.current || !data || !data.bars.length) return
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
        localization: { priceFormatter: (v: number) => `$${v.toFixed(2)}` },
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
          data.bars
            .filter((b) => b.open !== null && b.high !== null && b.low !== null && b.close !== null)
            .map((b) => ({
              time: stamp(b.date),
              open: b.open as number,
              high: b.high as number,
              low: b.low as number,
              close: b.close as number,
            })),
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
          data.bars
            .map((b, i) => ({ time: stamp(b.date), value: values[i] }))
            .filter((p): p is { time: UTCTimestamp; value: number } => p.value !== null),
        ),
      )
      drawn.push(series)
    }

    const markers = ordered(gradeMarkers(history, data.bars[0].date))
    if (markers.length) createSeriesMarkers(candles, markers)
    chart.timeScale().fitContent()
    setDrawFailed(false)

    return () => {
      chart.remove()
      chartRef.current = null
      drawn.length = 0
    }
  }, [data, timeframe, history])

  // Everything the canvas shows, in text, for the tests and for anyone not
  // reading pixels. The last drawn bar is the one a trader is looking at.
  const summary = useMemo(() => {
    if (!data || !data.bars.length) return null
    const last = data.bars[data.bars.length - 1]
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
  }, [data, timeframe])

  const changes = useMemo(() => gradeMarkers(history, data?.bars[0]?.date ?? '0000'), [history, data])

  return (
    <section className="mb-4" aria-label={`${ticker} price chart`}>
      <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
        <h4 className="text-xs font-medium text-[#1d1d1f]">
          Price, the averages the desk scores on, and every grade change
        </h4>
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

      {error && (
        <p role="alert" className="text-xs text-[#b42318]">
          {error}
        </p>
      )}
      {!error && !data && <p className="text-xs text-[#6e6e73]">Loading the chart…</p>}

      {data && (
        <>
          <div ref={holder} className={`w-full ${drawFailed ? 'hidden' : 'h-72'}`} data-testid="ticker-chart-canvas" />
          {drawFailed && (
            <p className="rounded bg-[#f5f5f7] p-2 text-xs text-[#6e6e73]">
              The chart could not be drawn from this data. The readings below are unaffected.
            </p>
          )}
          <p className="mt-1 text-[11px] text-[#6e6e73]">
            {data.sessions} {timeframe === 'weekly' ? 'weeks' : 'sessions'}, {data.basis}. The desk reads
            daily and weekly only, so those are the timeframes offered here.
          </p>

          {summary && (
            <dl className="mt-2 grid grid-cols-2 gap-x-4 gap-y-1 text-[11px] sm:grid-cols-3">
              <div className="flex justify-between gap-2">
                <dt className="text-[#6e6e73]">Last close</dt>
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

          <p className="mt-2 text-[11px] text-[#6e6e73]">
            {changes.length === 0
              ? `No grade change in the drawn window.`
              : `${changes.length} grade change${changes.length === 1 ? '' : 's'} marked: ${changes
                  .slice(-6)
                  .map((c) => c.text)
                  .join(', ')}${changes.length > 6 ? ' (most recent six)' : ''}. A bolder arrow is a grade the desk published that night.`}
          </p>
        </>
      )}
    </section>
  )
}
