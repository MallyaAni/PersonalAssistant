import {useEffect, useState} from 'react'
import {getDeskStrategySimulation, type DeskLive, type DeskStrategySummary} from '../../services/api'
import {ActionHead, percent, shares, type ActionSelection} from './TradeBoard'

const ALL_ACTIONS: ActionSelection = {BUY: true, SELL: true, TRIM: true, HOLD: true, '—': true}

// Keep the latest-strategy hypothetical portfolio separate from real paper-account state.
export const StrategySimulationBoard = ({userId, names, live, onOpen}: {userId: string; names: string[]; live: DeskLive; onOpen: (ticker: string) => void}) => {
  const [value, setValue] = useState<DeskStrategySummary | null>(null)
  const [error, setError] = useState('')
  const [query, setQuery] = useState('')
  const [shown, setShown] = useState<ActionSelection>(ALL_ACTIONS)
  const [filterOpen, setFilterOpen] = useState(false)
  const [refresh, setRefresh] = useState(0)
  const [sort, setSort] = useState<'ticker' | 'target' | 'holding'>('target')
  const [ascending, setAscending] = useState(false)
  // Preserve direct column sorting without changing the simulation's recorded values.
  const orderBy = (key: typeof sort) => {
    setAscending(key === sort ? !ascending : key === 'ticker')
    setSort(key)
  }
  useEffect(() => {
    let alive = true
    setValue(null)
    setError('')
    getDeskStrategySimulation(userId).then(result => {if (alive) setValue(result)}).catch(reason => {if (alive) setError(reason.message)})
    return () => {alive = false}
  }, [userId, refresh])
  const allRows = names.map(ticker => {
    const stock = value?.stock_overview[ticker]
    const decisions = value?.latest_decisions.filter(row => row.ticker === ticker && row.date === value.through) ?? []
    const action = !stock || stock.target == null ? 'Unavailable' : decisions.length ? decisions.map(row => row.action).join(' / ') : stock.holding > 0 ? 'HOLD' : 'No order'
    return {ticker, stock, action, decisions}
  })
  const counts = Object.fromEntries(Object.keys(ALL_ACTIONS).map(action => [action, allRows.filter(row => row.action === 'No order' || row.action === 'Unavailable' ? action === '—' : row.action.split(' / ').includes(action)).length])) as Record<keyof ActionSelection, number>
  const rows = allRows.filter(row => row.ticker.includes(query.trim().toUpperCase()) && (row.action === 'No order' || row.action === 'Unavailable' ? shown['—'] : row.action.split(' / ').some(action => shown[action as keyof ActionSelection])))
    .sort((a, b) => {
      const difference = sort === 'ticker' ? a.ticker.localeCompare(b.ticker) : sort === 'target' ? (a.stock?.target ?? -1) - (b.stock?.target ?? -1) : (a.stock?.holding ?? -1) - (b.stock?.holding ?? -1)
      return difference * (ascending ? 1 : -1) || a.ticker.localeCompare(b.ticker)
    })
  return <section aria-label="Latest-strategy simulation" className="rounded-xl border border-black/10 bg-white p-3 text-sm">
    <div className="flex flex-wrap items-center justify-between gap-2">
      <h3 className="font-semibold">Latest strategy · simulation</h3>
      <button type="button" className="text-xs text-[#0071e3]" onClick={() => setRefresh(count => count + 1)}>Refresh simulation</button>
    </div>
    {error ? <p role="alert" className="mt-2 text-[#b42318]">{error}</p> : !value ? <p className="mt-2">Loading strategy simulation…</p> : <>
      <p className="mt-1 text-xs text-[#6e6e73]">Through {value.through} · {value.provenance.cost_bps} bp per side · hypothetical, not broker trades.</p>
      <p className="mt-1 text-xs">Simulated value {value.ending_equity == null ? 'unavailable' : `$${value.ending_equity.toLocaleString(undefined, {maximumFractionDigits: 0})}`} · cash ${value.ending_cash.toLocaleString(undefined, {maximumFractionDigits: 0})} · {Object.keys(value.ending_holdings).length} positions.</p>
      <div className="my-2 flex flex-wrap items-center gap-2">
        <input type="search" aria-label="Search strategy stocks" placeholder="Search a ticker" value={query} onChange={event => setQuery(event.target.value)} className="rounded border px-2 py-1 text-xs" />
      </div>
      <div className="overflow-x-auto" style={{minHeight: filterOpen ? '14rem' : undefined}}><table aria-label="Latest-strategy stocks" className="w-full text-left text-xs">
        <thead><tr className="text-[#6e6e73]"><th aria-sort={sort === 'ticker' ? ascending ? 'ascending' : 'descending' : 'none'}><button type="button" onClick={() => orderBy('ticker')}>Stock</button></th><th>Last regular price</th><th aria-sort={sort === 'holding' ? ascending ? 'ascending' : 'descending' : 'none'}><button type="button" onClick={() => orderBy('holding')}>Simulated holding</button></th><th aria-sort={sort === 'target' ? ascending ? 'ascending' : 'descending' : 'none'}><button type="button" onClick={() => orderBy('target')}>Target · {value.through}</button></th><ActionHead open={filterOpen} onOpen={setFilterOpen} shown={shown} onShown={setShown} counts={counts} title={`Filter simulated actions for ${value.through}. Historical trades remain separately dated.`} /><th>Last simulated trade</th></tr></thead>
        <tbody>{rows.map(row => <tr key={row.ticker} className="border-t border-black/5">
          <td className="py-2"><button type="button" className="font-semibold text-[#0071e3]" onClick={() => onOpen(row.ticker)}>{row.ticker}</button></td>
          <td>{live.quotes[row.ticker]?.last == null ? '—' : `$${live.quotes[row.ticker].last.toFixed(2)}`}</td>
          <td>{row.stock ? shares(row.stock.holding) : 'Unavailable'}</td>
          <td>{row.stock?.target == null ? '—' : percent(row.stock.target)}</td>
          <td>{row.action}{row.decisions.length > 0 && ` · ${row.decisions.map(row => `${row.qty} sh planned`).join(' / ')}`}</td>
          <td>{row.stock?.last_trade ? `${row.stock.last_trade.action} ${shares(row.stock.last_trade.qty)} · ${row.stock.last_trade.date}` : 'None in replay'}</td>
        </tr>)}</tbody>
      </table></div>
      {rows.length === 0 && <p className="mt-2">No matching stocks. <button type="button" className="text-[#0071e3]" onClick={() => {setQuery(''); setShown(ALL_ACTIONS)}}>Show all</button></p>}
      <details className="mt-2 text-xs text-[#6e6e73]"><summary className="cursor-pointer">Simulation basis</summary>
        <p>One portfolio from {value.start}, starting with the carried holdings and ${value.starting_equity.toLocaleString(undefined, {maximumFractionDigits: 0})} value. Value includes accrued unpaid entitlements; cash and order sizes do not spend them. Model/data coverage ends {value.through}; current prices are separate. No real orders.</p>
      </details>
    </>}
  </section>
}
