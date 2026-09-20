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

// The New York session a timestamp belongs to. A bar stamped after
// midnight UTC is still the previous trading day in New York, so the
// session cannot be read off the ISO string.
const sessionOf = (stamp: string): string => {
  const parts = new Intl.DateTimeFormat('en-CA', {
    timeZone: 'America/New_York',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  }).format(new Date(stamp))
  return parts
}

// Fold the live quote into the drawn bars so the newest candle is the one
// moving right now rather than the last completed session. On the daily
// chart today is a new bar; on the weekly chart today extends the week
// still forming. Without this the chart is correct but always behind, and
// a trader reading it during the session is looking at yesterday.
const withLiveBar = (
  bars: DeskChartBar[],
  timeframe: Timeframe,
  lastBarComplete: boolean,
  quote?: LiveQuote,
): { bars: DeskChartBar[]; live: boolean } => {
  if (!quote || !Number.isFinite(quote.last) || !quote.bar || !bars.length) {
    return { bars, live: false }
  }
  const session = sessionOf(quote.bar)
  const newest = bars[bars.length - 1]
  if (session < newest.date) return { bars, live: false }
  const high = Math.max(quote.high ?? quote.last, quote.last)
  const low = Math.min(quote.low ?? quote.last, quote.last)
  // Daily: today is its own bar. Weekly: today belongs to the forming week
  // when there is one, and opens a new week when the last one closed.
  const extend =
    timeframe === 'weekly' ? !lastBarComplete || session <= newest.date : session === newest.date
  if (extend) {
    const merged: DeskChartBar = {
      ...newest,
      high: Math.max(newest.high ?? high, high),
      low: Math.min(newest.low ?? low, low),
      close: quote.last,
      date: timeframe === 'weekly' ? newest.date : session,
    }
    return { bars: [...bars.slice(0, -1), merged], live: true }
  }
  return {
    bars: [
      ...bars,
      {
        date: session,
        open: quote.open ?? newest.close ?? quote.last,
        high,
        low,
        close: quote.last,
        volume: null,
      },
    ],
    live: true,
  }
}

// Grade changes from the replayed history, as one marker per session where
// the letter differs from the session before it. A row the desk actually
// published is marked more strongly than one that is today's rules replayed
// over old prices, because only the first is something the desk said.
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
    // "Buy", not "entry". The board's column says Buy and this marks the same
    // rule firing on the same session; two words for one action is the drift
    // the three-action vocabulary was introduced to end.
    text: 'buy',
    size: 1,
  }))

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
  const wanted = (grade: string) => grade === 'A' || grade === 'A+'
  for (let i = 1; i < rows.length; i += 1) {
    const before = rows[i - 1].grade
    const now = rows[i].grade
    if (!before || !now || before === now) continue
    const up = (rank[now] ?? -1) > (rank[before] ?? -1)
    // Crossing OUT of A is not grade drift, it is the desk's only exit: the
    // rotation that sells the name and puts the money into the ones it still
    // wants. The chart drew every grade change the same way, so the one
    // change that is a trade looked like the four that are not, and the
    // entry circles had no counterpart. B to C is drift - the desk was
    // already out - and so is anything on the way back up.
    const sold = wanted(before) && !wanted(now)
    out.push({
      time: stamp(rows[i].date),
      position: up ? 'belowBar' : 'aboveBar',
      color: sold ? '#b42318' : GRADE_COLOR[now] ?? '#6e6e73',
      shape: up ? 'arrowUp' : 'arrowDown',
      text: sold ? `sell · ${before}→${now}` : `${before}→${now}`,
      size: sold ? 2 : rows[i].said ? 2 : 1,
    })
  }
  return out
}

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
    const read = (first: boolean) => {
      getDeskChart(userId, ticker, timeframe)
        .then((payload) => live && setData(payload))
        .catch((e: Error) => live && first && setError(e.message))
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
  }, [userId, ticker, timeframe])

  // One merged series, so the picture and the readings below it can never
  // disagree about what the newest bar is.
  const merged = useMemo(
    () =>
      data
        ? withLiveBar(data.bars, timeframe, data.last_bar_complete !== false, quote)
        : { bars: [] as DeskChartBar[], live: false },
    [data, timeframe, quote],
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
          merged.bars
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
          merged.bars
            .map((b, i) => ({ time: stamp(b.date), value: values[i] }))
            .filter((p): p is { time: UTCTimestamp; value: number } => p.value !== null),
        ),
      )
      drawn.push(series)
    }

    const markers = ordered([...gradeMarkers(history, merged.bars[0].date), ...entryMarkers(data)])
    if (markers.length) createSeriesMarkers(candles, markers)
    chart.timeScale().fitContent()
    setDrawFailed(false)

    return () => {
      chart.remove()
      chartRef.current = null
      drawn.length = 0
    }
  }, [data, merged, timeframe, history])

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
          Price against the averages the desk scores on, with every grade change marked
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
            {merged.live
              ? `The newest ${timeframe === 'weekly' ? 'week' : 'bar'} is today, still moving, from the latest 15-minute quote.`
              : `The newest bar is the last completed ${timeframe === 'weekly' ? 'week' : 'session'}; the market is closed or no quote has arrived.`}{' '}
            {data.sessions} {timeframe === 'weekly' ? 'weeks' : 'sessions'} shown, {data.basis}. The desk
            reads daily and weekly only, so those are the timeframes offered here.
          </p>
          {/* A mark nobody can read is decoration. Both of the desk's rules are
              on the price now, so the legend has to name both. */}
          <p className="mt-1 text-[11px] text-[#6e6e73]">
            <span className="font-medium text-[#0b5cad]">{'●'} buy</span>{' '}
            marks a session the price closed through the upper edge of its 20-day band, which is
            the desk's buy trigger and the same rule the Plan column reads.{' '}
            <span className="font-medium text-[#b42318]">{'↓'} sell</span>{' '}
            marks a session the grade fell out of A, the desk's only exit: it sells and puts the
            money into the names it still wants. Paler arrows are grade changes that are not
            trades. A signal shown here is the rule replayed over these prices, not a record of
            an order.
          </p>

          {summary && (
            <dl className="mt-2 grid grid-cols-2 gap-x-4 gap-y-1 text-[11px] sm:grid-cols-3">
              <div className="flex justify-between gap-2">
                <dt className="text-[#6e6e73]">{merged.live ? 'Price now' : 'Last close'}</dt>
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
