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
