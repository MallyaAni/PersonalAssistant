"""UNEXECUTED explicit daily-prefix capacity source; never the original CLI identity."""
import json
from hashlib import sha256

import numpy as np

from backend.market.panel import build_panel
from backend.market.store import MarketStore

SCHEMA = 'capacity-original-daily-inputs/1'
ORIGINAL_FUNCTION_SHA256 = '40d0d7cf482591ba28e6426ca87d23d3ed1b1cf42e31fd74a24a1287129221d9'


# Build the exact original pre-grid daily statements under a distinct source identity.
def daily_prefix(market, original, through):
    store = MarketStore(market)
    panel = build_panel(
        store,
        original.symbols,
        "SPY",
        {},
        asof=through,
        start=original.dates[0].astype(object),
    )
    if panel.tickers != tuple(original.symbols):
        raise ValueError("Complete installed model cohort required")
    grades = np.full(panel.close.shape, -1, dtype=np.int16)
    sources, actions = {}, {}
    factors = np.ones(panel.close.shape)
    labels = {"A+": 3, "A": 2, "B": 1, "C": 0}
    for stock, symbol in enumerate(panel.tickers):
        history = store.read(symbol, through)
        if history.complete_through < through:
            raise ValueError("Completed daily observations required for " + symbol)
        path = (
            market
            / "bars"
            / ("asof=" + store.latest_asof(symbol, through).isoformat())
            / (symbol + ".parquet")
        )
        sources[str(path)] = sha256(path.read_bytes()).hexdigest()
        if symbol not in ("SPY", "QQQ"):
            path = market / "history" / (symbol + ".json")
            raw = path.read_bytes()
            sources[str(path)] = sha256(raw).hexdigest()
            history_rows = json.loads(raw)
            if history_rows["asof"] < through.isoformat():
                raise ValueError("Completed grade history required for " + symbol)
            for row in history_rows["rows"]:
                index = np.searchsorted(panel.dates, np.datetime64(row["date"]))
                if index < len(panel.dates) and panel.dates[index] == np.datetime64(
                    row["date"]
                ):
                    grades[index, stock] = labels.get(row.get("grade"), -1)
        actions[symbol] = []
        for action in history.actions:
            if action.kind == "split":
                factors[panel.dates < np.datetime64(action.action_date), stock] *= (
                    action.value
                )
            actions[symbol].append(
                {
                    "date": action.action_date.isoformat(),
                    "kind": action.kind,
                    "value": action.value,
                }
            )
    eligible = grades >= 0
    return panel, grades, eligible, factors, actions, sources
