# Completed-prefix technical entry model

Third targeted hypothesis after the rule-relative all-stock and eligible-only
models. Eligible-only preliminary full paired gain is -35.0054pp,4/20 phases;
its independent verifier is still running. Preserve that failed candidate.

The original21features include daily EMA distances but no intraday EMA or
rolling Bollinger-band position; session VWAP and whole-prefix range do not
encode the same information. Add seven fixed causal features: intraday EMA3/9
distances, 8/20-close standardized band positions, RSI6 expressed0..1, and
4/8-bar log returns. No parameter grid. Initial session EMA uses first close;
rolling features remain missing until their full history is available. This
does not fabricate overnight continuity or missing candles. Common per-session
price scaling cancels; future-prefix and price-unit invariance are tested.

Keep the all-stock training population from the first revision (eligible-only
was a separate failed hypothesis), incumbent-relative target, same fixed tree
settings and every original zero-cost comparison. Do not change selection,
sizing, sell timing or horizon. Fit once and retain all20 phases and four
windows. Reused current-vintage history is exploratory, not a fresh holdout.
No live adoption based on a favorable isolated period or start.

## Completed result and next investigation

VERIFIED source1f900b3b:104 monthly numeric models /4,081,392 predictions,
20 accounts /17,448 intents independently checked. Producer and verifier
exit0/OOMfalse on image5c6c5605. Six focused tests pass, including future-bar
invariance, price-unit invariance and real trained-model numeric readback.
Final formatted scripts at e8e8b1a5 pass the same6 tests and scoped Ruff;
original producer scripts remain frozen and authenticated by identity.json.

FAILED advantage: full paired median-3.4657pp,8/20 phases win; early+0.4458pp,
later-6.1126pp, recent-1.2159pp. Receipt contains all phase hashes and ranges.
Private root /home/animallya96/scratch/technical-entry-20261005 on Spark.

The three targeted hypotheses all failed; stop this editing/search sequence
under the repository's three-hypothesis rule. No claim that the current rule
is globally optimal, and no learned replacement or production deployment.

One critical scope limit: all three use the original engine's mandatory final
same-session attempt and20-session planning cycle. They test execution timing
inside a selected trading day, not whether a selected stock should remain
unbought for several sessions. The next investigation should explicitly model
carried pending entry opportunities and their opportunity cost, with original
selection frozen, rather than assume every selected entry must execute today.
It requires a separate registered account contract and comparable control;
simply deleting the terminal rule would silently discard buys in this engine.
Fresh prospective evidence remains necessary: the recent window here has
already been inspected in prior experiments and is not an untouched holdout.
