import { Fragment, useRef, useState, type ReactNode } from 'react'
import type { DeskDecisions, DeskHolding, DeskLive, DeskLiveGrade, DeskPayload, DeskRecord } from '../../services/api'

const ORDER: Record<string, number> = {'A+': 3, A: 2, B: 1, C: 0}

// Format a portfolio weight without rounding a small positive allocation to zero.
const percentage = (weight: number) => weight > 0 && weight < .001 ? '<0.1%' : `${(weight * 100).toFixed(1)}%`

// Whether the exchange is open at `now`, on New York time.
export const marketOpenAt = (now: number) => {
  const parts = new Intl.DateTimeFormat('en-US', {timeZone: 'America/New_York', weekday: 'short', hour: 'numeric', minute: 'numeric', hour12: false}).formatToParts(new Date(now))
  const get = (type: string) => parts.find(p => p.type === type)?.value ?? ''
  const minutes = Number(get('hour')) * 60 + Number(get('minute'))
  return !['Sat', 'Sun'].includes(get('weekday')) && minutes >= 9 * 60 + 30 && minutes < 16 * 60
}

// Keep the confirmed fill date on the exchange's calendar.
const today = () => new Intl.DateTimeFormat('en-CA', {timeZone: 'America/New_York', year: 'numeric', month: '2-digit', day: '2-digit'}).format(new Date())

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
      <summary className="cursor-pointer">ML paper comparison · {ml.session ?? 'awaiting first close'}</summary>
      <p className="my-2 text-[#6e6e73]">Separate simulated accounts starting at $100,000 each. Frozen model; no real orders. Updated nightly. Costs of 10 or 30 basis points per traded dollar are included. This research portfolio does not follow the live desk’s FOMC policy.</p>
      <p>{ml.status}</p>
      {ml.observed_at && <p>Last observed {new Date(ml.observed_at).toLocaleString('en-US', {timeZone: 'America/New_York'})} ET</p>}
      <table aria-label="ML paper returns" className="mt-2 w-full tabular-nums"><thead><tr><th className="text-left">Policy / cost</th><th>Account</th><th>Return</th></tr></thead>
        <tbody>{Object.entries(ml.accounts).map(([name, account]) => <tr key={name}><td>{name}</td><td className="text-center">{account.equity.toLocaleString('en-US', {style: 'currency', currency: 'USD'})}</td><td className="text-center">{(account.total_return * 100).toFixed(2)}%</td></tr>)}</tbody>
      </table>
    </details>
}

// Present stocks and cash together, with details deferred until a person asks.
export const StockBoard = ({latest, live, grades, research, paper, ml, coverage, decisions, holdings, event, now, action, onOpen, onBuy, saving, error, holdingsError, expand}: {
  latest: DeskRecord; live: DeskLive; grades: Record<string, DeskLiveGrade>;
  research: DeskPayload['intraday_research']; holdings: DeskHolding[] | null;
  paper?: DeskPayload['board_paper'];
  ml?: DeskPayload['ml_forward'];
  decisions?: DeskDecisions;
  coverage?: DeskPayload['coverage'];
  event: BoardEvent | null; now: number; action: (ticker: string, allocation: number | null) => ReactNode;
  onOpen: (ticker: string) => void;
  onBuy?: (ticker: string, price: number, shares: number, date: string) => Promise<boolean>;
  saving: boolean; error: string; holdingsError?: string;
  // What a row shows when opened in place: the plan for that name, its
  // reasons and a way to the full panel.
  expand?: (ticker: string) => ReactNode;
}) => {
  const [buy, setBuy] = useState<string | null>(null)
  const [shares, setShares] = useState('')
  const [price, setPrice] = useState('')
  const [date, setDate] = useState(today)
  const [showAvoid, setShowAvoid] = useState(false)
  const [opened, setOpened] = useState<string | null>(null)
  const pending = useRef(false)
  // A research size is shown only while it is current for that one name: the
  // allocation was built on a single bar, so a name whose own live quote does
  // not share that bar gets a dash instead of turning the whole board off.
  // The cash row and the weight ranking still need the complete, synchronized
  // set, so those stay all-or-nothing.
  // During an FOMC cycle the sizes stay on the board at the exposure the
  // desk holds - half while reduced, full once restoration is queued - so a
  // 20% target reads 10% and cash carries the rest. They are hidden only
  // while that exposure is unknown: a missing calendar, or an active cycle
  // whose current policy status has not been read.
  const paused = event !== null
  const hidden = paused && (event.calendarUnknown || event.exposure === null)
  const exposure = paused && event.exposure !== null ? event.exposure : 1
  const researchCurrent = research?.status === 'available' && research.session === latest.session
    && !!research.valid_until && Date.parse(research.valid_until) > now
  const weightOf = (ticker: string) => {
    if (!researchCurrent || hidden) return null
    if (research!.bar !== live.quotes[ticker]?.bar) return null
    const weight = research!.targets?.[ticker]
    return Number.isFinite(weight) && (weight as number) >= 0 ? (weight as number) * exposure : null
  }
  const graded = Object.keys(latest.grades)
  const sizedNames = researchCurrent && !hidden ? graded.filter(ticker => weightOf(ticker) !== null) : []
  const fullCoverage = sizedNames.length === graded.length && graded.length > 0
  const gross = fullCoverage ? Object.values(research!.targets ?? {}).reduce((sum, weight) => sum + weight, 0) * exposure : null
  const sized = fullCoverage && gross !== null && gross <= 1.000001
  const marketClosed = !marketOpenAt(now)
  const fomcLine = !paused ? null
    : event.calendarUnknown ? 'FOMC calendar unavailable · exposure changes and sizing paused'
    : event.exposure === null ? 'FOMC cycle in progress · sizes paused until the policy status is current'
    : event.exposure < 1 ? `FOMC · sizes at ${event.exposure === 0.5 ? 'half' : `${Math.round(event.exposure * 100)}%`} exposure · restores at the open after the ${event.decisionDate ?? 'FOMC'} decision`
    : 'FOMC · restoration queued for the next open'
  const sizingLine = sized ? '15-minute model allocations · experimental'
    : researchCurrent && sizedNames.length > 0 ? `Research sizes for ${sizedNames.length} of ${graded.length} names`
    : marketClosed ? 'Sizes return with the first completed bar after the open' : 'Sizing unavailable · waiting for fresh data'
  // Compare only current scores tied to this exact nightly basis and completed price.
  const opportunity = (ticker: string) => {
    const value = decisions?.rows[ticker]?.opportunity
    return decisions?.session === latest.session && decisions.written === latest.written
      && value?.bar === live.quotes[ticker]?.bar && Date.parse(value?.valid_until ?? '') > now
      && Number.isFinite(value?.score) ? value!.score : null
  }
  const stocks = Object.entries(latest.grades).map(([ticker, grade]) => ({
    ticker, grade: grades[ticker]?.grade_live ?? grade.grade,
    score: grades[ticker]?.score_live ?? grade.score,
    opportunity: opportunity(ticker),
    weight: weightOf(ticker),
  })).sort((a, b) => (b.opportunity ?? -1) - (a.opportunity ?? -1)
    || (sized ? (b.weight ?? 0) - (a.weight ?? 0) : 0)
    || (ORDER[b.grade] ?? -1) - (ORDER[a.grade] ?? -1)
    || b.score - a.score || a.ticker.localeCompare(b.ticker))
  const emptyAccount = holdings !== null && holdings.length === 0
  const cash = {ticker: '__cash__', grade: '', score: 0, opportunity: null, weight: sized ? Math.max(0, 1 - gross!) : paused && emptyAccount ? 1 : null}
  const cashIndex = hidden || (paused && !sized) ? 0 : sized ? stocks.findIndex(stock => stock.weight! <= cash.weight!) : stocks.length
  // A grade C is "avoid it"; on a ninety-name board those rows are two
  // thirds of the page and say the same thing. They fold unless the account
  // holds the name. Small boards show everything.
  const foldAvoid = stocks.length > 20 && !showAvoid
  const avoided = foldAvoid ? stocks.filter(stock => stock.grade === 'C' && !holdings?.some(position => position.ticker === stock.ticker)) : []
  const shown = foldAvoid ? stocks.filter(stock => !avoided.includes(stock)) : stocks
  const ranked = [...shown]
  ranked.splice(cashIndex < 0 ? ranked.length : Math.min(cashIndex, ranked.length), 0, cash)
  const bar = researchCurrent ? research!.bar : live.data_at
  const time = bar ? new Date(bar).toLocaleString('en-US', {timeZone: 'America/New_York', month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit'}) : null
  return <section aria-label="Stocks and cash" className="flex min-h-0 flex-1 flex-col overflow-hidden rounded-2xl border border-black/[0.08] bg-white">
    <div className="shrink-0 border-b border-black/[0.06] px-3 py-2 text-xs text-[#6e6e73]">
      <p>{fomcLine ?? sizingLine}</p>
      {fomcLine && !hidden && <p className="mt-0.5">{sizingLine}</p>}
      <p className="mt-0.5" title="Fundamental analysis is nightly; prices and technical grades use completed intraday bars.">{time ? `Bar ${time} ET` : 'No current bar'} · 15-minute updates during market hours{live.stale && !marketClosed ? ' · market data stale' : ''}</p>
      {coverage && <p className="mt-0.5" title="The tracked universe spans sectors. Only names with a desk grade are ranked here; broader grading is not yet validated.">{coverage.graded} graded · {coverage.tracked} tracked</p>}
    </div>
    <div className="min-h-0 flex-1 overflow-auto">
      <table className="w-full text-left text-sm tabular-nums [&_td]:px-2 [&_th]:px-2" aria-label="Ranked stocks and cash">
        <thead className="sticky top-0 z-10 bg-[#f5f5f7] text-xs text-[#6e6e73]"><tr><th className="py-2">#</th><th>Stock</th><th>Action</th><th title="Percentage of total portfolio value, not an order quantity">Size %</th><th><span className="sr-only">Record purchase</span></th></tr></thead>
        <tbody>{ranked.map((row, index) => {
          const held = holdings?.find(position => position.ticker === row.ticker)
          const quote = live.quotes[row.ticker]
          const isCash = row.ticker === '__cash__'
          const open = opened === row.ticker
          return <Fragment key={row.ticker}><tr className={`border-t border-black/[0.05] ${isCash ? 'bg-[#0071e3]/10' : ''}`}>
            <td className="w-7 text-xs text-[#6e6e73]">{isCash || !expand ? index + 1 : <button type="button" aria-label={`details for ${row.ticker}`} aria-expanded={open} className="w-5 text-[#0071e3]" onClick={() => setOpened(open ? null : row.ticker)}>{open ? '▾' : '▸'}</button>}</td>
            <td className="py-2">
              {isCash ? <span className="font-semibold">USD</span> : <button className="font-semibold hover:text-[#0071e3]" onClick={() => onOpen(row.ticker)}>{row.ticker}<span title={grades[row.ticker] ? 'Intraday grade' : `Grade at ${latest.session} close`} className="ml-1.5 text-[10px] font-normal text-[#6e6e73]">{row.grade}</span>{row.opportunity !== null && <span title="Opportunity evidence index; open for inputs and dates" className="ml-1 text-[10px] font-normal text-[#6e6e73]">· {row.opportunity!.toFixed(1)}/10</span>}</button>}
              <div className="text-[11px] text-[#6e6e73]">{isCash ? emptyAccount ? 'Cash · 100% recorded' : paused ? hidden ? 'Hold available cash' : 'Cash held through FOMC' : 'Uninvested allocation' : <>{quote && Number.isFinite(quote.last) ? quote.last.toLocaleString('en-US', {style: 'currency', currency: 'USD'}) : 'Price unavailable'}{held ? ` · ${held.shares.toLocaleString()} held` : ''}</>}</div>
            </td>
            <td className="text-xs">{isCash ? 'Hold'
              : paused ? <span title={held ? exposure < 1 ? 'Held at reduced size through the decision; the rest restores at the next open' : 'Restoration queued for the next open' : 'No new buys during the FOMC cycle'}>{held ? 'Hold · FOMC' : 'Wait · FOMC'}</span>
              : action(row.ticker, row.weight)}</td>
            <td className="text-xs">{row.weight === null ? '—' : percentage(row.weight)}</td>
            <td className="text-right">{!isCash && <button disabled={!onBuy || saving} aria-label={`Record purchase of ${row.ticker}`} className="text-xs text-[#0071e3] disabled:opacity-40 hover:underline" onClick={() => {setBuy(row.ticker);setShares('');setPrice('');setDate(today())}}>Record</button>}</td>
          </tr>
          {open && expand && <tr><td colSpan={5} className="border-t border-black/[0.05] bg-[#0071e3]/5 px-3 py-2">{expand(row.ticker)}</td></tr>}
          </Fragment>
        })}</tbody>
      </table>
      {(avoided.length > 0 || (showAvoid && stocks.length > 20)) && <button type="button" className="w-full border-t border-black/[0.05] px-3 py-2 text-left text-xs text-[#0071e3]" onClick={() => setShowAvoid(!showAvoid)}>
        {showAvoid ? 'Hide the grade C names' : `Show ${avoided.length} more · grade C, avoid`}
      </button>}
    </div>
    <BoardSimulation paper={paper} now={now} />
    {holdings === null && <p role="alert" className="px-3 py-2 text-xs text-[#b42318]">{holdingsError ?? 'Positions unavailable. Recording is disabled.'}</p>}
    <MlComparison ml={ml} />
    {buy && <div role="dialog" aria-modal="true" aria-label={`Record ${buy} buy`} className="fixed inset-0 z-50 flex items-center justify-center bg-black/30 p-4">
      <form className="w-full max-w-sm space-y-3 rounded-2xl bg-white p-5 text-sm shadow-xl" onSubmit={async event => {
        event.preventDefault()
        if (saving || pending.current || !onBuy) return
        pending.current = true
        try {
          if (await onBuy(buy, Number(price), Number(shares), date)) setBuy(null)
        } finally { pending.current = false }
      }}>
        <h3 className="font-semibold">Record {buy} buy</h3>
        <p className="text-xs text-[#6e6e73]">Enter your confirmed brokerage fill. This tracks your position; it does not place an order.</p>
        <label className="block">Shares<input autoFocus aria-label="Filled shares" className="mt-1 block w-full rounded-lg border p-2" type="number" min="0.000001" step="any" required value={shares} onChange={event => setShares(event.target.value)} /></label>
        <label className="block">Fill price $<input aria-label="Average fill price" className="mt-1 block w-full rounded-lg border p-2" type="number" min="0.000001" step="any" required value={price} onChange={event => setPrice(event.target.value)} /></label>
        <label className="block">Date<input aria-label="Fill date" className="mt-1 block w-full rounded-lg border p-2" type="date" required max={today()} value={date} onChange={event => setDate(event.target.value)} /></label>
        {error && <p role="alert" className="text-xs text-[#b42318]">{error}</p>}
        <div className="flex justify-end gap-4"><button type="button" disabled={saving} onClick={() => setBuy(null)}>Cancel</button><button className="rounded-full bg-[#0071e3] px-4 py-2 text-white disabled:opacity-40" disabled={saving} type="submit">{saving ? 'Saving…' : 'Save position'}</button></div>
      </form>
    </div>}
  </section>
}
