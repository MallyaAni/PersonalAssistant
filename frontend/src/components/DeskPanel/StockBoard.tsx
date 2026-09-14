import { useRef, useState, type ReactNode } from 'react'
import type { DeskDecisions, DeskHolding, DeskLive, DeskLiveGrade, DeskPayload, DeskRecord } from '../../services/api'

const ORDER: Record<string, number> = {'A+': 3, A: 2, B: 1, C: 0}

// Format a portfolio weight without rounding a small positive allocation to zero.
const percentage = (weight: number) => weight > 0 && weight < .001 ? '<0.1%' : `${(weight * 100).toFixed(1)}%`

// Keep the confirmed fill date on the exchange's calendar.
const today = () => new Intl.DateTimeFormat('en-CA', {timeZone: 'America/New_York', year: 'numeric', month: '2-digit', day: '2-digit'}).format(new Date())

// Present stocks and cash together, with details deferred until a person asks.
export const StockBoard = ({latest, live, grades, research, paper, coverage, decisions, holdings, paused, now, action, onOpen, onBuy, saving, error}: {
  latest: DeskRecord; live: DeskLive; grades: Record<string, DeskLiveGrade>;
  research: DeskPayload['intraday_research']; holdings: DeskHolding[] | null;
  paper?: DeskPayload['board_paper'];
  decisions?: DeskDecisions;
  coverage?: DeskPayload['coverage'];
  paused: boolean; now: number; action: (ticker: string, allocation: number | null) => ReactNode;
  onOpen: (ticker: string) => void;
  onBuy?: (ticker: string, price: number, shares: number, date: string) => Promise<boolean>;
  saving: boolean; error: string;
}) => {
  const [buy, setBuy] = useState<string | null>(null)
  const [shares, setShares] = useState('')
  const [price, setPrice] = useState('')
  const [date, setDate] = useState(today)
  const pending = useRef(false)
  const current = research?.status === 'available' && research.session === latest.session
    && Date.parse(research.valid_until ?? '') > now
    && Object.keys(research.targets ?? {}).every(ticker => ticker in latest.grades)
    && Object.keys(latest.grades).every(ticker => research.bar === live.quotes[ticker]?.bar
      && Number.isFinite(research.targets?.[ticker]) && research.targets![ticker] >= 0)
  const gross = current ? Object.values(research.targets ?? {}).reduce((sum, weight) => sum + weight, 0) : null
  const sized = current && gross !== null && gross <= 1.000001 && !paused && !research.event_paused
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
    weight: sized ? research.targets![ticker] : null,
  })).sort((a, b) => (b.opportunity ?? -1) - (a.opportunity ?? -1)
    || (sized ? (b.weight ?? 0) - (a.weight ?? 0) : 0)
    || (ORDER[b.grade] ?? -1) - (ORDER[a.grade] ?? -1)
    || b.score - a.score || a.ticker.localeCompare(b.ticker))
  const emptyAccount = holdings !== null && holdings.length === 0
  const cash = {ticker: '__cash__', grade: '', score: 0, opportunity: null, weight: sized ? Math.max(0, 1 - gross!) : paused && emptyAccount ? 1 : null}
  const cashIndex = paused ? 0 : sized ? stocks.findIndex(stock => stock.weight! <= cash.weight!) : stocks.length
  const ranked = [...stocks]
  ranked.splice(cashIndex < 0 ? ranked.length : cashIndex, 0, cash)
  const bar = current ? research.bar : live.data_at
  const time = bar ? new Date(bar).toLocaleString('en-US', {timeZone: 'America/New_York', month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit'}) : null
  return <section aria-label="Stocks and cash" className="flex min-h-0 flex-1 flex-col overflow-hidden rounded-2xl border border-black/[0.08] bg-white">
    <div className="shrink-0 border-b border-black/[0.06] px-3 py-2 text-xs text-[#6e6e73]">
      <p>{paused ? 'FOMC · new buys paused' : sized ? '15-minute model allocations · experimental' : 'Sizing unavailable · waiting for fresh data'}</p>
      <p className="mt-0.5">{time ? `Bar ${time} ET` : 'No current bar'} · 15-minute updates during market hours</p>
      <p className="mt-0.5" title="Fundamental analysis is nightly; prices and technical grades use completed intraday bars.">Analysis {latest.session} close{live.stale ? ' · market data stale' : ''}</p>
      {coverage && <p className="mt-0.5" title="The tracked universe spans sectors. Only names with a desk grade are ranked here; broader grading is not yet validated.">{coverage.graded} graded · {coverage.tracked} tracked</p>}
    </div>
    <div className="min-h-0 flex-1 overflow-auto">
      <table className="w-full text-left text-sm tabular-nums [&_td]:px-2 [&_th]:px-2" aria-label="Ranked stocks and cash">
        <thead className="sticky top-0 z-10 bg-[#f5f5f7] text-xs text-[#6e6e73]"><tr><th className="py-2">#</th><th>Stock</th><th>Action</th><th title="Percentage of total portfolio value, not an order quantity">Size %</th><th><span className="sr-only">Record purchase</span></th></tr></thead>
        <tbody>{ranked.map((row, index) => {
          const held = holdings?.find(position => position.ticker === row.ticker)
          const quote = live.quotes[row.ticker]
          const isCash = row.ticker === '__cash__'
          return <tr key={row.ticker} className={`border-t border-black/[0.05] ${isCash ? 'bg-[#f0f5fa]' : ''}`}>
            <td className="w-7 text-xs text-[#6e6e73]">{index + 1}</td>
            <td className="py-2">
              {isCash ? <span className="font-semibold">USD</span> : <button className="font-semibold hover:text-[#0071e3]" onClick={() => onOpen(row.ticker)}>{row.ticker}<span title={grades[row.ticker] ? 'Intraday grade' : `Grade at ${latest.session} close`} className="ml-1.5 text-[10px] font-normal text-[#6e6e73]">{row.grade}</span>{row.opportunity !== null && <span title="Opportunity evidence index; open for inputs and dates" className="ml-1 text-[10px] font-normal text-[#6e6e73]">· {row.opportunity!.toFixed(1)}/10</span>}</button>}
              <div className="text-[11px] text-[#6e6e73]">{isCash ? emptyAccount ? 'Cash · 100% recorded' : paused ? 'Hold available cash' : 'Uninvested allocation' : <>{quote && Number.isFinite(quote.last) ? quote.last.toLocaleString('en-US', {style: 'currency', currency: 'USD'}) : 'Price unavailable'}{held ? ` · ${held.shares.toLocaleString()} held` : ''}</>}</div>
            </td>
            <td className="text-xs">{isCash ? 'Hold' : paused ? <span title="FOMC cycle takes priority">Wait</span> : action(row.ticker, row.weight)}</td>
            <td className="text-xs">{row.weight === null ? '—' : percentage(row.weight)}</td>
            <td className="text-right">{!isCash && <button disabled={!onBuy || saving} aria-label={`Buy ${row.ticker}`} className="rounded-full bg-[#0071e3] px-3 py-1.5 text-xs font-medium text-white disabled:opacity-40" onClick={() => {setBuy(row.ticker);setShares('');setPrice('');setDate(today())}}>Buy</button>}</td>
          </tr>
        })}</tbody>
      </table>
    </div>
    {paper?.equity !== undefined && <p aria-label="Forward paper account" className="border-t px-3 py-2 text-[11px] text-[#6e6e73]" title="Separate local simulation, not a brokerage account. Delayed quotes, spread and 10 bp extra cost per side. No real orders. Overnight marks wait for corporate-action validation.">
      Paper · {paper.equity.toLocaleString('en-US', {style: 'currency', currency: 'USD'})} · USD {percentage(paper.cash / paper.equity)} · {((paper.equity / paper.initial_capital - 1) * 100).toFixed(2)}% since start
      <span className="ml-1">· {new Date(paper.as_of).toLocaleString('en-US', {timeZone: 'America/New_York', month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit'})} ET{now - Date.parse(paper.as_of) >= 900000 ? ' · awaiting update' : ''}</span>
    </p>}
    {holdings === null && <p role="alert" className="px-3 py-2 text-xs text-[#b42318]">Positions unavailable. Recording is disabled.</p>}
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
