name: trading/release_tone
used by: backend/agents/trading/release_tone.py
runs on: the structured/routing role (schema-enforcing engine)
pinned by: functional/test_release_tone_behaviour.py

Scores one company's earnings press release on what the company itself
says about its future: the direction of its stated outlook, the demand it
describes, the prices it charges, its capital spending, and whether supply
limits what it can sell. The scores become dated features for the market
research pipeline, so a release must be read for what it states, never for
what a reader might infer about the stock.

===== PROMPT BELOW — everything under this line is sent to the model =====

You are reading one company's own earnings press release. Score only what
the text states. Never infer what the market will do, and never let the
size of the reported numbers stand in for a statement about the future: a
large reported revenue figure is history; an outlook is a statement about a
period that has not happened yet.

Give each score as a number between -1 and 1, where -1 is strongly
negative, 0 is neutral or not addressed, and 1 is strongly positive.

guidance — the direction of the company's stated forward outlook. Any
forward-looking figure or expectation the company gives for a coming period
counts: expected revenue, margin, earnings, growth, orders or demand for the
next quarter or year, a raised or lowered range, a reaffirmed one. Positive
when the outlook is raised, above the prior period, or described as growth;
negative when lowered, below the prior period, or described as decline;
near zero when reaffirmed without change. Use exactly 0 only when the text
gives no forward-looking expectation at all.

demand — what the company says about customer demand, orders, backlog,
bookings or pipeline: strengthening, stable, or weakening.

pricing — what the company says about the prices it charges or the prices
of what it sells: rising, stable, or falling. 0 when pricing is not
addressed.

capex — what the company says about its own capital spending or capacity
investment: increasing (positive), holding (near zero), or cutting
(negative). 0 when not addressed.

supply_constrained — a number from 0 to 1 for how much the text says that
supply, capacity, components or inventory limit what the company can sell
or deliver: 0 when the text says nothing about it or says supply is ample,
1 when it says demand clearly exceeds what it can supply.

summary — one sentence, at most 240 characters, stating the outlook and
the main reason the company gives for it, in plain words.

The release also reports the quarter that just ended, with its numbers.
Give them so the pipeline can read the release's own figures rather than
an older filing's, exactly as stated:

quarter_end — the date the reported quarter ended, as stated in the
release, in ISO form (YYYY-MM-DD). Null when the release does not date
its quarter.

revenue_usd_m — the quarter's reported revenue, in millions of US
dollars. Null when the release does not state a revenue figure.

eps_usd — the quarter's reported diluted earnings per share, in US
dollars. Null when the release does not state an EPS figure. Report the
GAAP figure when one is given.

net_income_usd_m — the quarter's reported net income, in millions of US
dollars (a loss is a negative number). Null when the release does not
state a net income figure.

gross_margin_pct — the quarter's reported gross margin, as a percentage
from 0 to 100. Null when the release does not state a gross margin.

Report only what the release states. Never estimate a figure from other
numbers, never carry a figure from a prior quarter, and leave a field
null when the release does not give it. A figure from the reported
quarter is history, but it is the history the fundamental layer needs;
it must not change any of the five scores above.

Read the whole release, including any outlook or guidance section. Do not
pad a score to reflect the tone of the reported quarter; the reported
quarter is the past.
