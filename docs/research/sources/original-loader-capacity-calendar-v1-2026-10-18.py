"""UNEXECUTED separately named reviewed-session reader; no Panel/store/provider imports."""
import json
from functools import lru_cache
from pathlib import Path

import numpy as np

HOLIDAYS_PATH = Path(__file__).parent / "data" / "nyse_holidays.json"
EARLY_CLOSES_PATH = Path(__file__).parent / "data" / "nyse_early_closes.json"
HISTORICAL_SESSIONS_PATH = (
    Path(__file__).parent / "data" / "nyse_historical_sessions.json"
)


# Share the reviewed historical and current session calendar without guessing years.
@lru_cache(maxsize=1)
def reviewed_sessions() -> tuple[set[int], np.busdaycalendar]:
    historical = json.loads(HISTORICAL_SESSIONS_PATH.read_text(encoding="utf-8"))[
        "years"
    ]
    current = json.loads(HOLIDAYS_PATH.read_text(encoding="utf-8"))["years"]
    years = {int(year) for year in historical} | {int(year) for year in current}
    closures = [
        day for record in historical.values() for day in record["full_closures"]
    ]
    closures.extend(day for days in current.values() for day in days)
    return years, np.busdaycalendar(holidays=closures)
