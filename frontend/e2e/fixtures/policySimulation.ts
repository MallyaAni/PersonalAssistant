import {readFileSync} from 'node:fs'

// The installed rule's account simulation as the desk serves it for the
// "Historical simulation" box. `policy-replay-2026-10-27-manifest.json` is the
// manifest the 20:40 replay (`market_policy_replay_research`) wrote for the
// 2026-10-27 record, byte for byte from a scratch copy of the store; the book
// sample is every 60th session of the `book.json` beside it, plus the last.
// `POLICY_SIMULATION` is what `/desk` builds from them (`read_book`): the
// manifest's `book` verbatim and the curve.
export const MANIFEST = JSON.parse(readFileSync(new URL('./policy-replay-2026-10-27-manifest.json', import.meta.url), 'utf8'))
const SAMPLE = JSON.parse(readFileSync(new URL('./policy-replay-2026-10-27-book-sample.json', import.meta.url), 'utf8'))

export const POLICY_SIMULATION = {
  status: 'available', policy: MANIFEST.policy, arm: MANIFEST.arm, session: MANIFEST.through,
  generated_at: MANIFEST.generated_at, note: MANIFEST.note, book: MANIFEST.book,
  dates: SAMPLE.dates, equity: SAMPLE.equity, benchmark: SAMPLE.benchmark,
}

// What `/desk` serves when the replay for the record has not been written.
export const missingSimulation = (session: string, policy: string = MANIFEST.policy) => ({
  status: 'missing', policy, session,
  reason: `No replay of ${policy} for the ${session} record has been written yet. The replay runs at 20:40, after the evening record; until it does, no simulation is shown.`,
})

const pct1 = (value: number) => `${(value * 100).toFixed(1)}%`
const usd0 = (value: number) => value.toLocaleString('en-US', {style: 'currency', currency: 'USD', maximumFractionDigits: 0})
const book = MANIFEST.book

// Every figure the box shows, each derived here from the manifest itself.
export const EXPECTED_CELLS: Record<string, string> = {
  'CAGR': pct1(book.all.cagr),
  'Max drawdown': pct1(book.all.max_drawdown),
  'Total return': pct1(book.all.total),
  [`${book.benchmark.symbol} CAGR`]: pct1(book.benchmark.cagr),
  [`${book.benchmark.symbol} max drawdown`]: pct1(book.benchmark.max_drawdown),
  'Trades': book.fills.toLocaleString('en-US'),
  'Costs': usd0(book.costs),
  'Starting capital': usd0(book.capital),
}
export const EXPECTED_PERIOD = `${book.period.start} to ${book.period.through} · ${book.period.sessions.toLocaleString('en-US')} sessions · ${book.rule.cost_bps} bp per fill`
export const EXPECTED_WINDOWS = `2015 to 2022: CAGR ${pct1(book.to_2022.cagr)}, max drawdown ${pct1(book.to_2022.max_drawdown)} · 2023 on: CAGR ${pct1(book.from_2023.cagr)}, max drawdown ${pct1(book.from_2023.max_drawdown)}`
export const CHART_NAME = `${MANIFEST.policy} simulated account against ${book.benchmark.symbol}`
