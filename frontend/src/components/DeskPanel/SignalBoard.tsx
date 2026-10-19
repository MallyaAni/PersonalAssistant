import {useMemo, useState} from 'react'
import type {DeskCurrentSetup, DeskLive, DeskRecord} from '../../services/api'
import {currentSetup, confirmationText, invalidationText} from './currentRanking'
import {currentAssessments} from './liveAssessment'
import {displayedBoardPrice, SessionPrice} from './StockBoard'

type Side = 'all' | 'buy' | 'sell'
type Signal = {word: string; ready: boolean; priority: string; rank: number; reason: string}
type Signals = {ticker: string; grade: string; setup: DeskCurrentSetup | null; buy: Signal; sell: Signal}
const PRIORITY: Record<string, number> = {high: 3, medium: 2, low: 1}

// Preserve model priorities while keeping immediate, waiting and unavailable evidence distinct.
const signal = (word: string, ready: boolean, priority: string, reason: string, tier: number): Signal =>
  ({word, ready, priority, reason, rank: tier * 10 - (PRIORITY[priority] ?? 0)})

// Build independent entry and downside-review signals without reading any account or funded order.
export const signalsFor = (latest: DeskRecord, live: DeskLive, ticker: string, now: number): Signals => {
  const setup = currentSetup(live, latest.session, ticker, now)
  const original = live.opportunities?.rows?.[ticker]
  const grade = currentAssessments(live, latest.session, now)[ticker]?.grade_live ?? '—'
  const missing = live.opportunities?.unavailable?.[ticker] ?? 'Fresh chart assessment unavailable; no immediate signal is inferred.'
  const unavailable = signal('Unavailable', false, '', missing, 3)
  if (!setup || setup.entry === 'unavailable' || !Number.isFinite(Date.parse(setup.bar))
      || Date.parse(setup.bar) + 900_000 > Date.parse(setup.generated_at)
      || !['high', 'medium', 'low'].includes(setup.entry_priority)
      || !['high', 'medium', 'low'].includes(setup.exit_priority))
    return {ticker, grade, setup: null, buy: unavailable, sell: unavailable}
  const quote = displayedBoardPrice(live, ticker, now)
  const open = live.market_status?.phase === 'open'
  const quoted = quote?.current && quote.kind === 'midpoint' && quote.word === 'regular'
  const gate = !open ? 'Wait for the regular session; this is not an immediate action.'
    : !quoted ? 'Wait for a fresh regular-session bid/ask quote.' : null
  const buy = gate && (setup.entry === 'ready' || original?.entry === 'ready')
    ? signal('Wait', false, setup.entry_priority, gate, 1)
    : setup.entry === 'ready' ? signal('Buy now', true, setup.entry_priority, setup.reason, 0)
    : signal(setup.entry === 'wait' ? 'Wait' : 'Avoid entry', false, setup.entry_priority, setup.reason, setup.entry === 'wait' ? 1 : 2)
  const sell = setup.exit === 'review'
    ? signal(gate ? 'Wait' : 'Sell review now', !gate, setup.exit_priority, gate ?? original!.reason, gate ? 1 : 0)
    : signal('No sell signal', false, '', original!.reason, 2)
  return {ticker, grade, setup, buy, sell}
}

// Display exact model evidence times in the market's timezone.
const evidenceTime = (at: string) => new Date(at).toLocaleString('en-US', {timeZone: 'America/New_York', month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit', second: '2-digit'}) + ' ET'

// Show the same directional reasons and evidence in row expansion and the full stock chart.
export const SignalDetail = ({signals}: {signals: Signals}) => <section aria-label={`${signals.ticker} signal details`} className="space-y-1 text-xs">
  <p><b>{signals.buy.word}</b> · {signals.buy.reason}</p>
  <p><b>{signals.sell.word}</b> · {signals.sell.reason}</p>
  {signals.setup && <>
    <p>{confirmationText(signals.setup)} {invalidationText(signals.setup)}</p>
    <p>Completed candle {evidenceTime(signals.setup.bar)} · assessed {evidenceTime(signals.setup.generated_at)} · Valid until {evidenceTime(signals.setup.valid_until)}.</p>
  </>}
  <p className="text-[#6e6e73]">Sell review means reassess or reduce an existing holding. Not a short-sale signal. Strength is the model’s qualitative priority, not a return probability or funded size.</p>
</section>

// Rank all covered names by fresh directional actionability, independent of the paper account.
export const SignalBoard = ({latest, live, now, onOpen, closes}: {latest: DeskRecord; live: DeskLive; now: number; onOpen: (ticker: string) => void; closes?: Record<string, number | null>}) => {
  const [side, setSide] = useState<Side>('all')
  const [query, setQuery] = useState('')
  const [opened, setOpened] = useState<string | null>(null)
  const [visible, setVisible] = useState(25)
  const rows = useMemo(() => Object.keys(latest.grades ?? {}).map(ticker => signalsFor(latest, live, ticker, now)), [latest, live, now])
  // Use only the selected direction's evidence; ties remain alphabetical rather than inventing a score.
  const selected = (row: Signals) => side === 'buy' ? row.buy : side === 'sell' ? row.sell : row.buy.rank <= row.sell.rank ? row.buy : row.sell
  const ranked = rows.filter(row => row.ticker.toLowerCase().includes(query.trim().toLowerCase()))
    .sort((a, b) => selected(a).rank - selected(b).rank || a.ticker.localeCompare(b.ticker))
  return <section aria-label="All names signals" className="min-h-0 overflow-auto rounded-xl border border-black/[0.08] bg-white">
    <div className="space-y-2 p-3">
      <h3 className="text-sm font-semibold">All names · {rows.length}</h3>
      <p className="text-xs text-[#6e6e73]">Current chart signals · no paper account or portfolio inputs required. Immediate signals first, then waiting and unavailable; High → Medium → Low within each group. Equal priorities sort alphabetically.</p>
      <div className="flex flex-wrap items-center gap-2" role="group" aria-label="Signal ranking">
        {(['all', 'buy', 'sell'] as const).map(value => <button key={value} type="button" aria-pressed={side === value} className={`rounded-full border px-3 py-1 text-xs ${side === value ? 'bg-[#e8f2ff] text-[#0071e3]' : ''}`} onClick={() => {setSide(value); setVisible(25)}}>{value === 'all' ? 'All names' : value === 'buy' ? 'Best buys' : 'Best sells'}</button>)}
        <input aria-label="Find a stock" placeholder="Find a stock" value={query} onChange={event => {setQuery(event.target.value); setVisible(25)}} className="rounded border px-2 py-1 text-xs" />
      </div>
      <p aria-label="Signal coverage" className="text-xs text-[#6e6e73]">{rows.filter(row => row.setup).length} of {rows.length} current assessments · {rows.filter(row => row.buy.ready).length} buy now · {rows.filter(row => row.sell.ready).length} sell reviews now{live.market_status?.phase !== 'open' ? ' · regular session closed or unavailable' : ''}.</p>
      <p className="text-xs text-[#6e6e73]">Buy signals use the current grade’s entry permission and model chart confirmation. Sell reviews use the model’s independent downside assessment, even for names absent from the paper account. These are manual review signals, not the funded allocator’s orders.</p>
    </div>
    <table aria-label="Ranked stock signals" className="w-full text-left text-xs">
      <thead className="border-y bg-[#f5f5f7]"><tr><th className="p-2">Stock / price</th><th className="p-2">Grade</th><th className="p-2">Buy signal</th><th className="p-2">Sell signal</th><th className="p-2">Strength</th><th className="p-2">Reason / timing</th></tr></thead>
      <tbody>{ranked.slice(0, visible).map(row => <tr key={row.ticker} data-ticker={row.ticker} className="border-t align-top">
        <td className="p-2"><button type="button" className="font-semibold text-[#0071e3]" onClick={() => onOpen(row.ticker)}>{row.ticker}</button><SessionPrice live={live} ticker={row.ticker} now={now} compact close={closes?.[row.ticker]} closeSession={latest.session} /></td>
        <td aria-label={`${row.ticker} displayed grade`} className="p-2">{row.grade}</td>
        <td aria-label={`${row.ticker} buy signal`} className={`p-2 font-medium ${row.buy.ready ? 'text-[#248a3d]' : 'text-[#6e6e73]'}`}>{row.buy.word}</td>
        <td aria-label={`${row.ticker} sell signal`} className={`p-2 font-medium ${row.sell.ready ? 'text-[#b42318]' : 'text-[#6e6e73]'}`}>{row.sell.word}</td>
        <td aria-label={`${row.ticker} signal strength`} className="p-2">{selected(row).priority ? selected(row).priority[0].toUpperCase() + selected(row).priority.slice(1) : '—'}</td>
        <td className="max-w-sm p-2"><p>{selected(row).reason}</p><button type="button" aria-label={`details for ${row.ticker}`} aria-expanded={opened === row.ticker} className="text-[#0071e3]" onClick={() => setOpened(opened === row.ticker ? null : row.ticker)}>Details</button>{opened === row.ticker && <SignalDetail signals={row} />}</td>
      </tr>)}</tbody>
    </table>
    {!ranked.length && <p className="p-3 text-xs">No matching stocks.</p>}
    {ranked.length > visible && <button type="button" className="p-3 text-xs text-[#0071e3]" onClick={() => setVisible(value => value + 25)}>Show more · {visible} of {ranked.length}</button>}
  </section>
}
