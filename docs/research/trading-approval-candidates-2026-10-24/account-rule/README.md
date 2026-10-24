# Candidate: the most profitable rule on the account simulator, made live and drawn on the charts

The owner asked that the most profitable strategy be live, be the one backtested and be the one on the charts, choosing
"highest yearly return after costs, among versions whose worst drop is no deeper than today's and that also win on the
later years they were not tuned on". One engine (`backend/market/policy_book.py`) now does the backtest and draws the
charts, and reproduces the live plan's orders night by night.

Changes to the live rule (contract revisions 5 and 6):

- admit a name at A or better, hold it while it keeps B (was: admit and hold at B);
- do not trade a resize smaller than 1% of equity (an exit always trades);
- tilt each sized name's slot by where its P/E sits in its own three years (0.5x to 1.5x);
- correct the share counts behind every valuation input for later stock splits (a look-ahead that graded later
  winners cheap in advance; live grades on 2026-10-23 differ in one name, CEG B to C).

Results on the simulator: 37.6% a year at worst drawdown -27.7% against 31.5% at -30.0% for the installed rule, ahead
in both windows and at 25 bp. Install before Monday's nightly: the account is mid FOMC cycle (decision 10-28) and the
eve restoration is planned on 10-27.
