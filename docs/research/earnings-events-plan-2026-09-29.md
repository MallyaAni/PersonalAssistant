# Filing expectations: bounded research registration

Written before constructing labels or fitting models. Base: GitHub main
`511297fc0ff12594ebba7d797ed7b613b701eece`. The live desk, `/4`, its execution,
the scheduled laggard shadow and all existing financial loaders stay unchanged.

## Question and limits

Can a model of the **next reported quarter's revenue growth** beat persistence
on source-qualified financial data? If so, does its realised forecast error
contain incremental post-filing return information? This is the first gate for
an earnings/expectations strategy, not another chart-timing grid.

The retained September 25 original-byte archive covers 94 currently selected
companies. This is an exploratory, survivor-selected cohort, not a pristine
historical universe. It is not analyst consensus. A 10-Q/10-K filing is not
necessarily the first earnings disclosure. Filing-date plus one calendar day
is the conservative information date where exact acceptance is absent; trades
in any diagnostic start at the next observed session's open after that date.
No overnight or intraday freshness is inferred. Archive capture dates and
source-reported historical filing dates remain distinct.

No raw source acquisition, account access, live record rewrite, new scheduled
job, GPU service changes or deployment is part of this experiment. New source
coverage, consensus, options and guidance extraction are separate work, not
fabricated columns here.

## Data and features, frozen before the run

Reuse `fundamental_source_store` and `qualified_fundamentals`: literal USD,
customer-contract revenue excluding assessed tax, complete quarterly intervals,
same-concept lags, and refusal of ambiguous/disputed derivations. No unitless
fallback, automatic revenue-tag stitching or older-quarter substitution.

An event is the first valid disclosure of a new frontier quarter. Features
come from the snapshot **one calendar day before** that information date. The
prior quarter end must be 70–115 days earlier. Revisions cannot create a second
training example for the same quarter. Unsupported events are counted, not
silently repaired. Inputs are the existing seven qualified financial features:
year-on-year and quarter-on-quarter log revenue growth, growth acceleration,
gross/net margins, operating cash flow/revenue and PPE capex/revenue. Include
missingness indicators and the age of the prior revenue period. No prices,
future quarter facts or retrospective tone enter the fundamental predictor.

Target: newly disclosed same-concept year-on-year **log revenue growth**. Baseline:
the last known quarter's log year-on-year growth, on identical eligible rows.
Two candidates predict the residual to that baseline:

1. Ridge, fixed alpha 10; fit-only median/IQR scaling and missing indicators.
2. LightGBM, fixed 7 leaves, learning rate 0.03, minimum 30 rows/leaf,
   L2 10, seed 7, at most 500 trees, 40-round early stopping.

Missing financial features stay missing until fit-only preprocessing; they do
not become asserted economic zeroes. Feature winsorisation uses training-only
0.5/99.5 percentiles. Targets and test errors are not winsorised. Record raw
outlier counts and baseline errors so an apparent improvement cannot come only
from hiding unusual quarters.

## Chronology and acceptance

Score calendar years 2019–2026 separately. At January 1, train only on targets
already available before the fit cutoff. LightGBM's validation is the preceding
calendar year; its training ends before that year. Select tree count there,
then refit on all prior eligible events. Require 300 fit events spanning three
years and 40 validation events; otherwise omit that model/year explicitly.
No shuffled K-fold, future-fitted scaling, test-selected epochs or retuning.
The forecast belongs to its feature-date year: a January 1 disclosure uses
the prior year's model, since its inputs were fixed on December 31. This
clarification is written during implementation, before the real export or fit.

Report common-row MSE, MAE, median absolute error and each annual difference
versus persistence, with issuer counts and calendar coverage. Date-block
bootstrap confidence intervals use fixed 63-calendar-day blocks, 2,000 draws,
seed 7; issuer dependence and cohort bias remain limitations. Both candidates
are counted trials. No broad model-family sweep follows a failure.

A candidate warrants the next **funded experiment**, not promotion, only with
at least 2% lower pooled MSE and MAE, improvement in a majority of scored years,
and a positive lower 95% block-bootstrap bound on mean squared-error benefit.
Require at least 500 shared test events. These gates cannot be loosened after
results. Accuracy alone is not investment alpha.

Post-filing diagnostics use source-qualified actual-minus-predicted growth;
returns start only after information availability and use adjusted next opens
over 20 sessions, with SPY and QQQ over exactly the same interval. Missing
prices and immature endpoints are excluded explicitly, never zero-filled.
This is a gross event study, **not** funded strategy performance. Return
diagnostics are descriptive; no threshold is selected from them.

Only a surviving economic hypothesis proceeds to a separately frozen `/4`
funded comparison, preserving its cap, cash constraints and execution. All
reused 2016–2026 history is development evidence. Neither this test nor a
strong nightly week can authorise live promotion.

## Required proof

Test future-filing invariance; missing/ambiguous/currency/period exclusions;
no duplicate quarter labels; exact feature, target and fit cutoffs; fit-only
preprocessing; chronological early stopping; index horizon alignment; actual
model fitting and immutable report readback. Retain source hashes, event
identities, per-year predictions and model settings outside the public app.
