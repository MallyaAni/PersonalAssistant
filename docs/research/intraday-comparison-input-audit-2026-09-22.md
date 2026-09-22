# Intraday comparison input audit — 2026-09-22

Reviewed by root against source and cached evidence at d8731ea. No candidate
outcomes were scored. The original OpenCode report remains in its isolated
worktree; this integrated report corrects its unsupported conclusions.

## Verified inputs

- `/home/animallya96/anios/data/market/bars_15m/asof=2026-09-20` contains530
  files and19,871,542 rows. Metadata bounds are2019-01-02 through2026-09-18,
  including extended hours. IBKR supplies the2019 lower bound; most names begin
  in2020. These bounds are not common causal coverage. SPY/QQQ intraday files
  are absent. The older intraday partition contains only NVDA.
- Daily bars have session_date, OHLC, adjusted_close and volume, with recent
  as-of partitions containing retrospective history. Daily SPY/QQQ exist.
- Saved desk records cover11 sessions,2026-09-04 through2026-09-21, with93
  grades per record until94 on09-21. The first three lack code_revision.
- There are116 saved decisions from the older intraday research candidate over
  five sessions,09-11 through09-17. They are not observations of the new reclaim
  candidate and cannot validate it. Re-running their prior evaluator is not a
  substitute for this comparison.
- The current constituent universe is survivor-biased and has no historical
  membership or delisted-name coverage (`backend/market/universe.py`).

Root verification script: `/tmp/codex-verify-comparison-evidence-20260922.py`.
Receipt: `/tmp/codex-verify-comparison-evidence-20260922.log`. It reads metadata,
record dates/provenance and two price-basis examples, not portfolio state or returns.

## Price basis: correction required before historical scoring

`backend/market/alpaca.py:154` explicitly requests `adjustment=all` for cached
intraday bars. The saved schema records alpaca-iex but does not itself persist
that adjustment flag, so source inspection and representative rows support the
basis finding; they do not establish exact cross-provider equivalence everywhere.

Independently reproduced examples (last regular intraday close):

| Symbol/date | Intraday close | Daily adjusted close | Daily close |
| --- | ---: | ---: | ---: |
| KO2020-09-30 |41.36|41.3419|49.3700|
| AAPL2020-08-28 |120.98|120.9557|124.8075|

The daily close is split-adjusted and dividend-unadjusted; adjusted_close also
reflects dividends. An interface that expects contemporaneous raw bars must not
silently accept this adjusted cache and apply the dividend conversion twice.
Alpaca/IEX and Yahoo differences remain; matching examples are not proof that
all dates/names share identical corporate-action conventions.

Before scoring, require an explicit input price basis. The frozen raw-input
mapping remains valid for a caller with documented raw observations. For an
adjusted-price component diagnostic, use adjusted levels and adjusted observations
together, without the raw conversion; label all outputs accordingly and test
scale equivalence. This is a units correction before outcomes, not a new trading
threshold. Unknown/mixed basis blocks scoring. No cache should be rewritten.

## Availability must use actual written time

Session labels are not publication times. The09-04 record says written
2026-09-07T23:45:29Z; it was not available on09-04. More subtly, the09-14
record says written2026-09-15T14:18:21Z (10:18:21 New York): it cannot supply
prior-night eligibility for the09-15 open or its09:45/10:00 observations.
Each replay must compare written time with the decision time and preserve older
or unknown eligibility until the newer record became available.

These are recorded availability timestamps, not independent proof of immutable
historical publication. Missing code provenance further limits exact replay.
Hash-stamped old intraday decisions support the recorded inputs at their times;
they do not establish a multi-year history of current-strategy eligibility.

The worker's assertion that grades are DeepSeek outputs is **false**.
`desk.assemble` calls `grading.grade`; `grading.grade_stances` deterministically
combines analyst stances. `market_daily` writes model prose after the decision.
A model name in provenance does not mean the model assigns the grade. Historical
deterministic reconstruction may be possible with sufficiently dated upstream
features, but its complete point-in-time provenance has not been established
here, and `desk.run` was not authorized or executed.

## Calendar and maturity

The existing committed calendar has full closures for2026–2028. Root verified
the exchange's published early closes:2026-11-27 and12-24;2027-11-26;
2028-07-03 and11-24, all13:00 New York. A companion schedule records them.
Source: [NYSE/ICE calendar, published2025-12-23](https://ir.theice.com/press/news-details/2025/NYSE-Group-Announces-2026-2027-and-2028-Holiday-and-Early-Closings-Calendar/).
Earlier years and unexpected closures still require verified coverage before a
multi-year replay; missing bars must not be used to infer an early close.

Earliest recorded eligibility can support a09-08 entry. With outcomes defined
at the close20 trading sessions after entry, its earliest primary exit is
2026-10-06; the5-session secondary exit is09-15. No archived eligibility can
have a mature20-session outcome at cached end09-18. Do not start the outcome
clock on the prior record's session date or shorten the declared horizon.

## Supported next work

**Proceed:** review the causal adapter, add explicit price-basis handling,
availability tests and calendar checks, then build a reviewed replay runner.
A short diagnostic under recorded eligibility can retain immature outcomes as
missing; a price-only historical diagnostic needs explicit limitations and
resolved basis/calendar coverage. Neither is an exact reconstruction of the
full current live strategy.

**Unverified:** cross-provider scale alignment across all inputs; historical
point-in-time grades/membership; exact live reranking; mature primary outcomes;
candidate superiority; midpoint fills. Prospective observations of the new
candidate will be needed alongside retrospective component diagnostics.
