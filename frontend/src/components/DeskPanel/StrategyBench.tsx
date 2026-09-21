import { useState } from 'react'
import type { StrategyBench as Bench, StrategyBenchRow } from '../../services/api'

// Candidate trading rules and the indices on identical numbers, split by
// regime. The point of the split is that one headline return hides where it
// came from: the same rule that doubles the desk over the whole sample makes
// most of it in one two-year window and loses more than the desk in a crash.
//
// Evidence, never an instruction. Only the rule marked as shipping trades.

const pct = (v: number | null | undefined, digits = 1) =>
  v == null ? '—' : `${v >= 0 ? '' : '−'}${Math.abs(v * 100).toFixed(digits)}%`
const num = (v: number | null | undefined) => (v == null ? '—' : v.toFixed(2))

// An index is context rather than a candidate, so it reads differently.
const isIndex = (name: string) => /^[A-Z]{2,4}$/.test(name)

// Show comparison accounting and explicitly explain missing benchmark evidence.
export const StrategyBench = ({ bench }: { bench?: Bench | null }) => {
  const [open, setOpen] = useState<string | null>('Whole sample')
  if (!bench?.blocks?.length) return null

  // Highlight the strongest available metric without treating missing values as zero.
  const best = (rows: StrategyBenchRow[], key: keyof StrategyBenchRow) => {
    const vals = rows.map((r) => r[key]).filter((v): v is number => typeof v === 'number')
    return vals.length ? Math.max(...vals) : null
  }

  return (
    <details className="rounded-2xl border border-black/[0.08] bg-white p-4 text-xs text-[#6e6e73]" aria-label="Strategy benchmarks">
      <summary className="cursor-pointer font-medium">
        Strategy benchmarks · candidates and indices, {bench.sessions.toLocaleString()} sessions
      </summary>

      <p className="mt-2">
        Every candidate priced over identical sessions, split by regime so a headline return cannot
        hide where it came from. {bench.note}
      </p>
      <p className="mt-2" aria-label="Benchmark accounting">
        {bench.version === 'strategy-bench/2'
          ? 'SPY and QQQ: dividend-adjusted, funded next-open entry with trading costs.'
          : 'Older comparison accounting: strict funded SPY and QQQ validation is not recorded.'}
      </p>

      <div className="mt-3 space-y-2">
        {bench.blocks.map((block) => {
          const showing = open === block.regime
          const bestAnnual = best(block.rows, 'annual')
          return (
            <div key={block.regime} className="rounded-lg border border-black/[0.06]">
              <button
                type="button"
                className="flex w-full items-baseline justify-between gap-2 px-3 py-2 text-left hover:bg-[#f5f5f7]"
                onClick={() => setOpen(showing ? null : block.regime)}
                aria-expanded={showing}
              >
                <span className="font-medium text-[#1d1d1f]">{block.regime}</span>
                <span>
                  {block.from} to {block.to} · {block.sessions} sessions
                  {block.share == null ? '' : ` · ${(block.share * 100).toFixed(1)}% of the sample`}
                </span>
              </button>

              {showing && (
                <div className="overflow-x-auto px-3 pb-3">
                  <table className="w-full text-left [&_td]:pr-3 [&_th]:pr-3" aria-label={`${block.regime} candidates`}>
                    <thead>
                      <tr className="text-[#6e6e73]">
                        <th className="font-normal">Rule</th>
                        <th className="font-normal">Total</th>
                        <th className="font-normal">Annual</th>
                        <th className="font-normal">Vol</th>
                        <th className="font-normal">Worst drawdown</th>
                        <th className="font-normal">Sharpe</th>
                      </tr>
                    </thead>
                    <tbody>
                      {block.rows.map((row) => (
                        <tr key={row.name} className="border-t border-black/[0.05]">
                          <td className={`py-1.5 ${isIndex(row.name) ? 'text-[#6e6e73]' : 'font-medium text-[#1d1d1f]'}`}>
                            {row.name}
                            {isIndex(row.name) && <span className="ml-1 text-[10px]">index</span>}
                            {row.unavailable && <span className="block font-normal text-[#b42318]">Unavailable: {row.unavailable}</span>}
                          </td>
                          <td className="tabular-nums">{pct(row.total)}</td>
                          <td className={`tabular-nums ${row.annual != null && row.annual === bestAnnual ? 'font-medium text-[#1a7f37]' : ''}`}>
                            {pct(row.annual)}
                          </td>
                          <td className="tabular-nums">{pct(row.volatility)}</td>
                          <td className="tabular-nums text-[#b42318]">{pct(row.drawdown)}</td>
                          <td className="tabular-nums">{num(row.sharpe)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          )
        })}
      </div>

      {bench.caveat && (
        <p className="mt-3 rounded bg-[#fff8e6] p-2">
          <b className="text-[#1d1d1f]">Read with this:</b> {bench.caveat}
        </p>
      )}
      <p className="mt-2">
        Only the rule marked as shipping is traded. The others are measured alternatives and place no
        orders anywhere.
      </p>
    </details>
  )
}
