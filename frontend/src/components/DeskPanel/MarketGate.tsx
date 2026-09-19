import type { DeskRecord } from '../../services/api'

const money = (value: number | null | undefined) =>
  value == null || !Number.isFinite(value)
    ? '—'
    : value.toLocaleString('en-US', { style: 'currency', currency: 'USD' })

// The lead risk control: SPY relative to its own 50-day average decides how
// much of the book is at work, before a lagging grade could react. A grade
// is read off the close after the move happened, so the exposure decision
// cannot wait for one. Shown only as a status the record actually wrote.
export const MarketGate = ({ gate, session }: { gate: DeskRecord['market_gate']; session: string }) => {
  if (!gate || typeof gate.below !== 'boolean' || typeof gate.exposure !== 'number') return null
  const halved = gate.below || (gate.factor ?? 1) < 1
  const exposure = gate.exposure ?? 1
  return (
    <section
      aria-label="Market gate"
      className={`rounded-xl border px-3 py-2 ${
        halved
          ? 'border-amber-200 bg-amber-50 text-[#5c4300]'
          : 'border-black/[0.08] bg-white text-[#6e6e73]'
      }`}
    >
      <details open={halved}>
        <summary className="cursor-pointer text-xs font-medium">
          Market gate · {halved ? 'exposure reduced' : 'full exposure'}
        </summary>
        <p className="mt-1 text-xs">
          {halved ? (
            <>
              SPY closed at {money(gate.spy)}, below its 50-day average of {money(gate.ema50)}.
              The book is held at {Math.round(exposure * 100)}% of target and the remainder is
              retained in cash. Full exposure resumes when SPY closes above its 50-day average.
            </>
          ) : (
            <>
              SPY closed at {money(gate.spy)}, above its 50-day average of {money(gate.ema50)}.
              The book is held at {Math.round(exposure * 100)}% of target.
            </>
          )}
        </p>
        <p className="mt-1 text-[11px] opacity-70">
          Assessed at the {session} close. It acts on the price before a grade can be read, so it
          leads rather than lags the move.
        </p>
      </details>
    </section>
  )
}
