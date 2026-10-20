import {useMemo, useState} from 'react'
import type {DeskCurrentSetup, DeskLive, DeskModelAllocation, DeskRecord, DeskStrategyDecision, DeskStrategyStock} from '../../services/api'
import {currentSetup, confirmationText, invalidationText} from './currentRanking'
import {currentAssessments} from './liveAssessment'
import {displayedBoardPrice, SessionPrice} from './StockBoard'

type Side = 'all' | 'buy' | 'sell'
type Signal = {word: string; ready: boolean; priority: string; rank: number; reason: string}
type Signals = {ticker: string; grade: string; setup: DeskCurrentSetup | null; buy: Signal; sell: Signal; plan?: {session: string; published: string; validUntil: string; calculated?: string}}
const PRIORITY: Record<string, number> = {high: 3, medium: 2, low: 1}

export type StrategyChartTarget = {ticker: string; date: string; at: string; validUntil: string | null; action: 'Buy' | 'Sell' | null; weight: number; record: string; strategyIdentity?: string; evidence?: DeskStrategyDecision['evidence']; entry?: {at: string; validUntil: string}; entryReason?: string}

// Recognize the independently authenticated publication formats without consulting an account.
const independentAllocation = (allocation?: DeskModelAllocation): boolean => allocation?.version === 'strategy-model-allocation/1' || allocation?.version === 'strategy-model-allocation/2'

// Require a complete internally consistent publication before using its own stock universe or percentages.
const publicationValid = (allocation: DeskModelAllocation | undefined, now: number): boolean => {
  if (allocation?.version !== 'strategy-model-allocation/2' || allocation.status !== 'available'
      || allocation.policy !== 'grade-led-learned-sizing/1' || allocation.basis !== 'account_independent_unit_capital_targets'
      || allocation.account_basis !== 'no_account_inputs' || allocation.timing_basis !== 'nightly_position_size_not_immediate_trade_size'
      || allocation.identity?.schema !== 'strategy-recommendation-publication/1'
      || allocation.identity.strategy_identity !== allocation.strategy_identity || allocation.identity.session !== allocation.session
      || allocation.identity.policy !== allocation.policy || allocation.identity.basis !== allocation.basis
      || ![allocation.strategy_identity, allocation.snapshot_id, allocation.receipt_sha256].every(value => /^[a-f0-9]{64}$/.test(value ?? ''))
      || allocation.as_of !== allocation.published_at || !(Date.parse(allocation.observed_at ?? '') <= Date.parse(allocation.as_of)
        && Date.parse(allocation.as_of) <= now && now < Date.parse(allocation.valid_until ?? ''))) return false
  const names = Object.keys(allocation.rows ?? {})
  if (!names.length || names.length !== Object.keys(allocation.grade_signals ?? {}).length) return false
  let total = 0
  for (const name of names) {
    const row = allocation.rows[name], grade = allocation.grade_signals?.[name], evidence = row.evidence
    if (!grade || grade.session !== allocation.session || grade.basis !== 'observed_close_grade'
        || !['buy', 'hold', 'sell', 'avoid', 'unavailable'].includes(grade.action)
        || !['A+', 'A', 'B', 'C'].includes(grade.grade ?? '') || evidence?.grade !== grade.grade
        || evidence?.inputs_as_of !== allocation.session || evidence?.model_position_size !== row.target_weight
        || typeof row.target_weight !== 'number' || !Number.isFinite(row.target_weight) || row.target_weight < 0 || row.target_weight > 1
        || (row.target_weight > 0 && (!['A+', 'A'].includes(grade.grade!) || !['buy', 'hold'].includes(grade.action)))) return false
    total += row.target_weight
  }
  return total <= 1 + 1e-12
}

// Use only the exact current numerical candle and its own still-fresh quote for immediate entry permission.
const numericalEntry = (allocation: DeskModelAllocation, ticker: string, now: number) => {
  const entry = allocation.entry_assessment, row = entry?.rows?.[ticker]
  const completed = Date.parse(entry?.completed_at ?? ''), generated = Date.parse(entry?.generated_at ?? '')
  const quoted = Date.parse(row?.quote_at ?? ''), until = Date.parse(row?.valid_until ?? '')
  if (entry?.version !== 'strategy-numerical-entries/1' || entry.status !== 'available'
      || entry.snapshot_id !== allocation.snapshot_id || entry.publication_receipt_sha256 !== allocation.receipt_sha256
      || entry.strategy_identity !== allocation.strategy_identity || !/^[a-f0-9]{64}$/.test(entry.receipt_sha256 ?? '')
      || entry.feed !== 'iex' || entry.account_inputs !== false || entry.sizing_basis !== 'fresh_unit_capital_allocation_not_account_trade_quantity'
      || !row || row.size_weight !== allocation.rows[ticker]?.target_weight || !['execute','wait'].includes(row.state)
      || row.action !== 'Buy' || !(row.size_weight > 0) || row.evidence?.model_position_size !== row.size_weight
      || row.evidence?.grade !== allocation.grade_signals?.[ticker]?.grade || row.evidence?.inputs_as_of !== allocation.session
      || row.evidence?.completed_candle_at !== entry.completed_at
      || !(completed <= generated && generated <= now && now < completed + 900000)
      || Date.parse(entry.valid_until ?? '') !== completed + 900000
      || !(completed <= quoted && quoted <= generated && now < until && until <= quoted + 30000)) return null
  return {row, at: entry.generated_at!, validUntil: row.valid_until}
}

// Match authenticated history by its validated economics contract while retaining legacy exact-record checks.
export const strategyHistoryMatches = (simulation: DeskStrategyStock | null | undefined, current: StrategyChartTarget | null | undefined): boolean => {
  if (!simulation || simulation.policy !== 'grade-led-learned-sizing/1' || simulation.provenance.basis !== 'account_independent_unit_capital_targets') return false
  if (current && !current.strategyIdentity) return simulation.provenance.source_record_sha256 === current.record
  const expected = current?.strategyIdentity ?? (simulation.provenance.verified_against_installed_strategy === true ? simulation.provenance.strategy_identity : null)
  if (!expected || !/^[a-f0-9]{64}$/.test(expected)) return false
  const contract = simulation.provenance.strategy_contract
  return contract?.schema === 'strategy-history-economics-binding/1'
    && contract.strategy_identity === expected && simulation.provenance.strategy_identity === expected
    && contract.source_record_sha256 === simulation.provenance.source_record_sha256
    && contract.config_sha256 === simulation.provenance.config_sha256
    && [contract.history_sha256, contract.audit_sha256, contract.source_record_sha256, contract.config_sha256].every(value => /^[a-f0-9]{64}$/.test(value))
}

// Require a dated authenticated strategy target, with an explicit independent or legacy published basis.
export const modelWeight = (latest: DeskRecord, allocation: DeskModelAllocation | undefined, ticker: string, now: number): number | null => {
  const weight = allocation?.rows?.[ticker]?.target_weight
  if (allocation?.version === 'strategy-model-allocation/2') return publicationValid(allocation, now) && typeof weight === 'number' ? weight : null
  const basis = allocation?.version === 'published-model-allocation/1'
    ? allocation.basis === 'original_published_strategy_allocation_not_trade_quantity'
    : allocation?.version === 'strategy-model-allocation/1' && allocation.basis === 'account_independent_unit_capital_targets'
  const reading = allocation?.grade_signals?.[ticker]
  const readingMatches = allocation?.version !== 'strategy-model-allocation/1' || (reading
    && reading.grade === latest.grades?.[ticker]?.grade && reading.session === latest.session
    && reading.basis === 'observed_close_grade' && ['buy', 'hold', 'sell', 'avoid', 'unavailable'].includes(reading.action))
  if (!basis || !readingMatches || allocation?.status !== 'available'
      || allocation.policy !== 'grade-led-learned-sizing/1' || allocation.policy !== latest.targets?.policy
      || allocation.session !== latest.session || allocation.observed_at !== latest.written
      || !/^[a-f0-9]{64}$/.test(allocation.record_sha256 ?? '') || !/^[a-f0-9]{64}$/.test(allocation.receipt_sha256 ?? '')
      || !(Date.parse(allocation.observed_at ?? '') <= Date.parse(allocation.as_of) && Date.parse(allocation.as_of) <= now)
      || !(Date.parse(allocation.valid_until ?? '') > now)
      || typeof weight !== 'number' || !Number.isFinite(weight) || weight < 0 || weight > 1) return null
  return weight
}

// Bind model size and separately confirmed candle timing to the same live evidence used by the board.
export const strategyChartTarget = (latest: DeskRecord, allocation: DeskModelAllocation | undefined, ticker: string, now: number, live: DeskLive): StrategyChartTarget | null => {
  const weight = modelWeight(latest, allocation, ticker, now)
  if (!independentAllocation(allocation) || weight === null || !allocation) return null
  if (allocation.version === 'strategy-model-allocation/2') {
    const action = allocation.grade_signals?.[ticker]?.action
    const current = live.market_status?.phase === 'open' ? numericalEntry(allocation,ticker,now) : null
    return {ticker, date: current ? allocation.entry_assessment!.session! : allocation.session!, at: current?.at ?? allocation.as_of, validUntil: allocation.valid_until,
      action: weight > 0 && ['buy', 'hold'].includes(action ?? '') ? 'Buy' : action === 'sell' ? 'Sell' : null,
      weight, record: allocation.snapshot_id!, strategyIdentity: allocation.strategy_identity,
      evidence: current?.row.evidence ?? allocation.rows[ticker].evidence,
      entry: current?.row.state === 'execute' ? {at:current.at,validUntil:current.validUntil} : undefined}
  }
  const action = allocation.grade_signals?.[ticker]?.action
  if (weight > 0 && (action === 'buy' || action === 'hold')) {
    const signal = signalsFor(latest, live, ticker, now, allocation)
    const at = Math.max(Date.parse(allocation.as_of), Date.parse(signal.setup?.generated_at ?? ''))
    const until = Math.min(Date.parse(allocation.valid_until ?? ''), Date.parse(signal.setup?.valid_until ?? ''))
    const entry = signal.buy.ready && !signal.sell.ready && at <= now && now < until
      ? {at: new Date(at).toISOString(), validUntil: new Date(until).toISOString()} : undefined
    return {ticker, date: allocation.session!, at: allocation.as_of, validUntil: allocation.valid_until, action: 'Buy', weight, record: allocation.record_sha256!, entry, entryReason: signal.sell.ready ? signal.sell.reason : signal.buy.reason}
  }
  if (weight === 0 && action === 'sell')
    return {ticker, date: allocation.session!, at: allocation.as_of, validUntil: allocation.valid_until, action: 'Sell', weight, record: allocation.record_sha256!}
  if (weight === 0)
    return {ticker, date: allocation.session!, at: allocation.as_of, validUntil: allocation.valid_until, action: null, weight, record: allocation.record_sha256!}
  return null
}

// Keep model allocation percentages distinct from trade sizes and the current chart's direction.
export const ModelSize = ({latest, allocation, ticker, now}: {latest: DeskRecord; allocation?: DeskModelAllocation; ticker: string; now: number}) => {
  const weight = modelWeight(latest, allocation, ticker, now)
  const independent = independentAllocation(allocation)
  const unknownExit = independent && allocation?.grade_signals?.[ticker]?.action === 'sell' && weight === 0
  return <div aria-label={`${ticker} model size`}>
    <span className="font-medium" title={unknownExit ? 'Sell size requires the strategy position history' : independent ? `Strategy position size · ${allocation?.session}` : undefined}>{unknownExit ? '—' : weight === null ? 'Unavailable' : `${(weight * 100).toFixed(1)}%${independent ? '' : ' target'}`}</span>
    {!independent && <p className="text-[10px] text-[#6e6e73]">{weight === null ? allocation?.reason ?? 'Verified current model allocation required' : `Strategy allocation · ${allocation!.session}`}</p>}
  </div>
}

// Preserve model priorities while keeping immediate, waiting and unavailable evidence distinct.
const signal = (word: string, ready: boolean, priority: string, reason: string, tier: number): Signal =>
  ({word, ready, priority, reason, rank: tier * 10 - (PRIORITY[priority] ?? 0)})

// Preserve an authenticated nightly direction outside regular hours without inventing current chart confirmation.
const publishedPlanFor = (latest: DeskRecord, live: DeskLive, allocation: DeskModelAllocation | undefined, ticker: string, now: number): Signals | null => {
  const v2 = allocation?.version === 'strategy-model-allocation/2'
  if (!v2 && !['post-market', 'pre-market', 'closed'].includes(live.market_status?.phase ?? '')) return null
  const weight = modelWeight(latest, allocation, ticker, now)
  const grade = v2 ? allocation.grade_signals?.[ticker]?.grade : latest.grades?.[ticker]?.grade
  const session = v2 ? allocation.session : latest.session
  if (weight === null || !grade || !['A+', 'A', 'B', 'C'].includes(grade)) return null
  const independent = independentAllocation(allocation)
  const originalSignal = independent ? allocation?.grade_signals?.[ticker] : null
  const actions = independent ? originalSignal ? [{
    grade: originalSignal.grade, signal_session: originalSignal.session,
    signal_basis: originalSignal.basis, grade_signal: originalSignal.action,
  }] : [] : latest.actions?.filter(row => row.ticker === ticker) ?? []
  const action = actions[0]
  if (actions.length !== 1 || action.grade !== grade || action.signal_session !== session
      || action.signal_basis !== 'observed_close_grade'
      || !['buy', 'hold', 'sell', 'avoid'].includes(action.grade_signal ?? '')) return null
  const eligible = action.grade_signal === 'buy' || action.grade_signal === 'hold'
  const exiting = action.grade_signal === 'sell'
  const hasExit = !eligible && (!independent || exiting)
  if (!eligible && weight > 0) return null
  const waiting = v2 && live.market_status?.phase === 'open'
  const timing = v2 ? 'Await the numerical 15-minute entry assessment and a fresh regular-session quote; this is not an immediate action.' : 'Await a fresh regular-session candle and quote; this is not an immediate action.'
  const reason = `${independent ? 'Strategy model' : 'Published'} ${session} grade signal ${action.grade_signal}, grade ${grade}, ${(weight * 100).toFixed(1)}% ${independent ? 'position size' : 'target'}. ${timing}`
  return {
    ticker, grade: independent ? grade : `${grade} · plan`, setup: null,
    buy: signal(eligible && weight > 0 ? waiting ? 'Wait' : independent ? 'Buy setup' : 'Buy plan' : eligible ? independent ? 'Wait' : 'No buy allocation' : independent ? 'Avoid' : 'Avoid new entry', false, '', reason, eligible && weight > 0 ? 1 : 2),
    sell: signal(hasExit ? waiting ? 'Wait' : independent ? 'Exit' : 'Exit if held' : independent ? '—' : 'No grade exit', false, '', hasExit
      ? `The published grade-led policy exits below A if held; this viewer's holdings are unknown. ${timing}`
      : `${eligible ? 'Grade retains entry permission' : 'No new entry or model sell action'}. ${timing}`, hasExit ? 1 : 2),
    plan: {session: session!, published: allocation!.observed_at!, validUntil: allocation!.valid_until!, calculated: independent ? allocation!.as_of : undefined},
  }
}

// Build independent entry and downside-review signals without reading any account or funded order.
export const signalsFor = (latest: DeskRecord, live: DeskLive, ticker: string, now: number, allocation?: DeskModelAllocation): Signals => {
  if (allocation?.version === 'strategy-model-allocation/2') {
    const unavailable = signal('Unavailable', false, '', 'Verified current strategy publication required.', 3)
    const plan = publishedPlanFor(latest, live, allocation, ticker, now)
    const entry = publicationValid(allocation,now) && live.market_status?.phase === 'open' ? numericalEntry(allocation,ticker,now) : null
    const quote = displayedBoardPrice(live,ticker,now)
    if (plan && allocation.grade_signals?.[ticker]?.action === 'sell' && live.market_status?.phase === 'open'
        && quote?.current && quote.kind === 'midpoint' && quote.word === 'regular')
      return {...plan,sell:signal('Sell review now',true,'','The model grade dropped below A: exit an existing position. This is not a short sale; no holding amount is assumed.',0)}
    if (plan && entry) {
      const ready = entry.row.state === 'execute'
      return {...plan,buy:signal(ready ? 'Buy now' : 'Wait',ready,'',ready
        ? 'The numerical model favors acting now over waiting one 15-minute candle. Size % is the model position, not an additional purchase amount.'
        : 'The numerical model favors waiting one 15-minute candle at the current price.',ready ? 0 : 1)}
    }
    return plan ?? {ticker, grade: '—', setup: null, buy: unavailable, sell: unavailable}
  }
  const setup = currentSetup(live, latest.session, ticker, now)
  const original = live.opportunities?.rows?.[ticker]
  const grade = currentAssessments(live, latest.session, now)[ticker]?.grade_live ?? '—'
  const missing = live.opportunities?.unavailable?.[ticker] ?? (live.market_status?.phase && live.market_status.phase !== 'open'
    ? 'Regular-session assessment expired or unavailable. Extended-hours prices do not supply a new strategy assessment.'
    : 'Fresh chart assessment unavailable; no immediate signal is inferred.')
  const unavailable = signal('Unavailable', false, '', missing, 3)
  if (!setup || setup.entry === 'unavailable' || !Number.isFinite(Date.parse(setup.bar))
      || Date.parse(setup.bar) + 900_000 > Date.parse(setup.generated_at)
      || !['high', 'medium', 'low'].includes(setup.entry_priority)
      || !['high', 'medium', 'low'].includes(setup.exit_priority))
    return publishedPlanFor(latest, live, allocation, ticker, now) ?? {ticker, grade, setup: null, buy: unavailable, sell: unavailable}
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

// Show the strongest supported action, preferring a downside review when both directions are immediately ready.
const actionFor = (row: Signals): Signal => row.sell.ready || row.sell.rank < row.buy.rank ? row.sell : row.buy

// Use direct trading labels while keeping confirmation and timing requirements in the supporting details.
const actionLabel = (word: string): string => ['Buy now', 'Buy plan', 'Buy setup'].includes(word) ? 'Buy'
  : ['Sell review now', 'Exit if held', 'Exit'].includes(word) ? 'Sell' : word

// Show the same directional reasons and evidence in row expansion and the full stock chart.
export const SignalDetail = ({signals}: {signals: Signals}) => <section aria-label={`${signals.ticker} signal details`} className="space-y-1 text-xs">
  <p><b>{actionLabel(signals.buy.word)}</b> · {signals.buy.reason}</p>
  <p><b>{actionLabel(signals.sell.word)}</b> · {signals.sell.reason}</p>
  {signals.setup && <>
    <p>{confirmationText(signals.setup)} {invalidationText(signals.setup)}</p>
    <p>Completed candle {evidenceTime(signals.setup.bar)} · assessed {evidenceTime(signals.setup.generated_at)} · Valid until {evidenceTime(signals.setup.valid_until)}.</p>
  </>}
  {signals.plan && <p>{signals.plan.calculated ? 'Strategy model' : 'Published plan'} {signals.plan.session} · inputs published {evidenceTime(signals.plan.published)}{signals.plan.calculated ? ` · calculated ${evidenceTime(signals.plan.calculated)}` : ''} · Valid until {evidenceTime(signals.plan.validUntil)}. Grade and {signals.plan.calculated ? 'size' : 'target'} are not a current candle assessment.</p>}
  <p className="text-[#6e6e73]">Sell review means reassess or reduce an existing holding. Not a short-sale signal. Strength is the model’s qualitative priority, not a return probability or funded size.</p>
</section>

// Rank all covered names by fresh directional actionability, independent of the paper account.
export const SignalBoard = ({latest, live, allocation, now, onOpen, closes}: {latest: DeskRecord; live: DeskLive; allocation?: DeskModelAllocation; now: number; onOpen: (ticker: string) => void; closes?: Record<string, number | null>}) => {
  const [side, setSide] = useState<Side>('all')
  const [query, setQuery] = useState('')
  const [opened, setOpened] = useState<string | null>(null)
  const [visible, setVisible] = useState(25)
  const rows = useMemo(() => Object.keys(allocation?.version === 'strategy-model-allocation/2' ? allocation.grade_signals ?? {} : latest.grades ?? {}).map(ticker => signalsFor(latest, live, ticker, now, allocation)), [latest, live, now, allocation])
  const independent = independentAllocation(allocation)
  const showPriority = !independent || rows.some(row => row.setup)
  // Date fresh numerical signals to their own session rather than the nightly input close.
  const currentSession = allocation?.version === 'strategy-model-allocation/2' && publicationValid(allocation, now)
    && rows.some(row => numericalEntry(allocation, row.ticker, now))
    ? new Date(allocation.entry_assessment!.completed_at!).toLocaleDateString('en-CA', {timeZone: 'America/New_York'}) : null
  // Use directional evidence first, then actual target size for model buy setups, without calling size confidence.
  const selected = (row: Signals) => side === 'buy' ? row.buy : side === 'sell' ? row.sell : row.buy.rank <= row.sell.rank ? row.buy : row.sell
  const ranked = rows.filter(row => row.ticker.toLowerCase().includes(query.trim().toLowerCase()))
    .sort((a, b) => selected(a).rank - selected(b).rank
      || (independent && side !== 'sell' && a.plan && b.plan
        ? (modelWeight(latest, allocation, b.ticker, now) ?? 0) - (modelWeight(latest, allocation, a.ticker, now) ?? 0) : 0)
      || a.ticker.localeCompare(b.ticker))
  return <section aria-label="All names signals" className="min-h-0 overflow-auto rounded-xl border border-black/[0.08] bg-white">
    <div className="space-y-2 p-3">
      <h3 className="text-sm font-semibold">All names · {rows.length}</h3>
      <p className="text-xs text-[#6e6e73]">{independent
        ? `${live.market_status?.phase === 'open' ? allocation?.version === 'strategy-model-allocation/2' && !currentSession ? 'Awaiting 15-minute entries' : '15-minute signals' : 'Regular market closed · Next-session actions'} · ${currentSession ?? allocation?.session ?? latest.session}`
        : 'Regular-session signals and published strategy plans · no paper account or portfolio inputs required. Immediate signals first, then waiting, plans and unavailable; High → Medium → Low within each group. Equal priorities sort alphabetically.'}</p>
      <div className="flex flex-wrap items-center gap-2" role="group" aria-label="Signal ranking">
        {(['all', 'buy', 'sell'] as const).map(value => <button key={value} type="button" aria-pressed={side === value} className={`rounded-full border px-3 py-1 text-xs ${side === value ? 'bg-[#e8f2ff] text-[#0071e3]' : ''}`} onClick={() => {setSide(value); setVisible(25)}}>{value === 'all' ? 'All names' : value === 'buy' ? 'Best buys' : 'Best sells'}</button>)}
        <input aria-label="Find a stock" placeholder="Find a stock" value={query} onChange={event => {setQuery(event.target.value); setVisible(25)}} className="rounded border px-2 py-1 text-xs" />
      </div>
      <p aria-label="Signal coverage" className="text-xs text-[#6e6e73]">{independent
        ? `${rows.filter(row => row.buy.word === 'Buy setup' || row.buy.ready).length} buys · ${rows.filter(row => row.sell.word === 'Exit' || row.sell.ready).length} sells`
        : `${rows.filter(row => row.setup).length} of ${rows.length} current assessments · ${rows.filter(row => row.buy.ready).length} buy now · ${rows.filter(row => row.sell.ready).length} sell reviews now · ${rows.filter(row => row.plan).length} published plan rows${live.market_status?.phase !== 'open' ? ' · regular session closed or unavailable' : ''}.`}</p>
      {!independent && <p className="text-xs text-[#6e6e73]">Model size is the published strategy target percentage, not shares or an instruction to buy that percentage now. Entry and exit reviews use fresh chart assessments; they do not recalculate the model’s allocation.</p>}
    </div>
    <table aria-label="Ranked stock signals" className="w-full text-left text-xs">
      <thead className="border-y bg-[#f5f5f7]"><tr><th className="p-2">Stock / price</th><th className="p-2">Grade</th><th className="p-2">Action</th><th className="p-2" title="Model position size as a percentage of portfolio capital">{independent ? 'Size %' : 'Position size %'}</th>{showPriority && <th className="p-2">Strength</th>}<th className="p-2">{independent ? '' : 'Reason / timing'}</th></tr></thead>
      <tbody>{ranked.slice(0, visible).map(row => {
        const action = actionFor(row)
        const label = actionLabel(action.word)
        return <tr key={row.ticker} data-ticker={row.ticker} className="border-t align-top">
        <td className="p-2"><button type="button" className="font-semibold text-[#0071e3]" onClick={() => onOpen(row.ticker)}>{row.ticker}</button><SessionPrice live={live} ticker={row.ticker} now={now} compact close={closes?.[row.ticker]} closeSession={latest.session} /></td>
        <td aria-label={`${row.ticker} displayed grade`} className="p-2">{row.grade}</td>
        <td aria-label={`${row.ticker} action`} title={action.reason} className={`p-2 font-semibold ${label === 'Sell' ? 'text-[#b42318]' : label === 'Buy' ? 'text-[#248a3d]' : 'text-[#6e6e73]'}`}>{label}</td>
        <td className="p-2"><ModelSize latest={latest} allocation={allocation} ticker={row.ticker} now={now} /></td>
        {showPriority && <td aria-label={`${row.ticker} signal strength`} className="p-2">{selected(row).priority ? selected(row).priority[0].toUpperCase() + selected(row).priority.slice(1) : '—'}</td>}
        <td className="max-w-sm p-2">{!independent && <p>{selected(row).reason}</p>}<button type="button" aria-label={`details for ${row.ticker}`} aria-expanded={opened === row.ticker} className="text-[#0071e3]" onClick={() => setOpened(opened === row.ticker ? null : row.ticker)}>Details</button>{opened === row.ticker && <SignalDetail signals={row} />}</td>
      </tr>})}</tbody>
    </table>
    {!ranked.length && <p className="p-3 text-xs">No matching stocks.</p>}
    {independent && <p className="px-3 py-2 text-[11px] text-[#6e6e73]">Size % is the strategy position size, not a profit target.</p>}
    {ranked.length > visible && <button type="button" className="p-3 text-xs text-[#0071e3]" onClick={() => setVisible(value => value + 25)}>Show more · {visible} of {ranked.length}</button>}
  </section>
}
