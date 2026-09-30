# Adaptive entry: the dip threshold scaled by the name's own volatility. Pre-registration (2026-09-30)

**Status: registered before any code or fill is read.**

## The question

The board buys at the first 15-minute close 1% under the day's open, else
at the close (`dip_or_close`, `fill_timing.DIP = 0.01`). The operator's
objection: "I fail to understand why a hard-coded number like buying the 1%
dip at open would work; stocks can move 5-7% red some days." Is a
same-session threshold scaled by the name's own volatility, or a rule that
does not chase a gap-down, a better fill than the fixed 1%?

## What is known before this note (disclosed)

- **Stage 3, T-I** (`stage3-results-2026-09-29.md`): four model rules
  choosing "now or the close" all lost to `dip_or_close` (−0.1 to −0.6 bp a
  session; the `free` rules −1.5 on 2024-2026).
- **Stage 4** (`stage4-results-2026-09-29.md`): a one-sigma level rested
  for up to five sessions (D0) lost −0.90 bp a session on buys, negative
  at 20 of 20 offsets; the models learn |g| (volatility) at IC 0.2-0.3 and
  not the sign of g.
- **Stage 5** (`stage5-results-2026-09-29.md`): buying at the previous
  close instead is drift, not edge (−2.2 bp a buy drift-adjusted);
  `dip_or_close` fills about 3.4 bp a buy better than the next open
  (+15.1 against +11.7 bp measured from the decision close).
- **Not yet tested:** a *same-session* threshold scaled by volatility (D0
  scaled it but also waited five sessions), and a gap-down guard. The
  fixed 1% was chosen by hand in the board's first design, never swept.
- The sells are not in scope: the pop rule mirrors the dip rule and the
  delay helps sells (stage 4's follow-up).

## The candidates (buys only)

Every candidate is a same-session rule in session t+1 with the official
close as the fallback, on stage 4's machinery (`stage4_labels.name_fills`
conventions, `stage4_orders` control at 20 offsets, executed basis, the
`/5` allocator), priced against the control `dip_or_close`:

- **E1, half-sigma dip:** the first bar close at or below open × (1 − 0.5σ),
  σ the name's standard deviation (ddof 1) of the last 20 daily log
  returns through t (stage 4's σ).
- **E2, one-sigma dip:** the same at open × (1 − σ). This is D0 confined to
  the session.
- **E3, gap guard:** the fixed 1% rule, except that when the open is more
  than 2σ below the previous close (a gap-down), the buy waits for the
  official close. On other sessions it is the control.

Three candidates. Reported beside them, deciding nothing: the fill's bar
distribution, the share of buys the level reaches, the reading by grade
and by leg, and the oracle capture as stage 4 reports it.

## Criteria, fixed now (stage 4's, for one side)

A candidate **REPLACES** the buy rule if, at the median offset: (1) the
model-window (2018-01-02..2023-12-29) mean gain over the control is at
least +2.0 bp of equity a session with a Newey-West t (lag 20) ≥ 2.0;
(2) the next-bar run holds the same floor; (3) 2024-2026 is not negative;
(4) the deflated Sharpe at N = 3 is ≥ 0.95; (5) the drift-adjusted mean is
≥ +1.0 bp at t ≥ 2 (the rule never waits past t+1, so this reduces to (1));
and, added for this study, (6) positive at 15 of 20 offsets. "Real but
immaterial" as stage 4 defines it. Anything else is **RECORD**, and the
board keeps the fixed 1%.

## Trials and prior

Three registered candidates; cumulative 454 → 457 (the universe study,
registered but not run, does not count until it runs). Prior for a REPLACES:
about 15%. The likely finding is that a wider threshold fills fewer buys
early and pays the drift, as D0 did; the gap guard is the one with a
mechanism (not buying into a gap-down's first hour) and the fewest fires.

## Order of work

1. This note is committed and pushed before any code.
2. Build with tests: the three conventions in `stage4_labels` (a `sigma`
   level confined to t+1 and the gap guard), a small CLI reusing
   `stage4_decisions`' statistics, the payload and the verdict.
3. Run on spark1 (CPU). Write-up, independent check, report.
