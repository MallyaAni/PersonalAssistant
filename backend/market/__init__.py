"""Daily market data and the tensors a model learns stock structure from.

The reproducible daily snapshot (universe, Yahoo fetch, Postgres store,
refresh/status) is the raw material; the window builder turns it into
no-look-ahead tensors the stock-analysis research model will consume. The
model is fed raw normalized price/volume, not hand-coded indicators — a
neural network learns the structure report itself.
"""
