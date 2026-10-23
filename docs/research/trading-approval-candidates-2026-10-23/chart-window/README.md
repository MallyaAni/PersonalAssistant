# Candidate: the chart's daily window reaches the replay's start

Display only. `backend/api/v1/market.py` caps a daily chart request at 4,000 sessions instead of 2,000, so the strategy chart's Full history reaches 2015-01-02, where the policy replay starts. Found by opening every name: 27 names lost every replayed trade and grade change before late 2018. No trading logic changes; the one bound source that changes is market.py.
