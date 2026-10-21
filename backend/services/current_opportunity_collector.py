"""Keep chart judgments current even when no browser is open."""

import base64
import json
import os
import time
from datetime import UTC, datetime, timedelta

from backend.services.session_price_collector import SessionPriceCollector

# The entry engine reads its reference quotes once per 15-minute window, a few
# seconds after the candle completes. An IEX top-of-book that is wider than the
# engine allows at that instant, or a name whose forming bar has not printed
# yet, leaves the name without an entry for the whole window even though both
# conditions usually clear within a minute. The collector therefore asks for a
# fresh observation when a planned name is still waiting for its price and the
# current quote page would now pass, no more often than this.
REACQUIRE_SECONDS = 120
WINDOW_SECONDS = 15 * 60


class CurrentOpportunityCollector(SessionPriceCollector):
    """One shared, bounded display-only inference pass per completed snapshot."""

    # Keep display collection outside account/trading jobs and ordinary tests.
    def __init__(self, root, enabled=True):
        super().__init__(
            root,
            interval_seconds=15,
            enabled=enabled and not os.getenv("ANIOS_TEST_MODE"),
        )
        self._entry_cache = {}
        self._reacquired_at = None
        self._retained = None

    # Prepare the daily objective even while closed, then preserve originals before refreshing numerical permission.
    def _collect_once(self):
        from backend.market import (
            strategy_entries,
            strategy_entry_history,
            strategy_position_view,
            strategy_publication,
            strategy_reference_entries,
        )
        if (self._root / strategy_publication.DIRECTORY).exists():
            history_status='available'
            try:
                if strategy_position_view.configured(self._root):
                    now = datetime.now(UTC)
                    snapshot = strategy_publication.read(self._root, now)
                    strategy_reference_entries.prepare_book(self._root, snapshot, now)
                strategy_entry_history.remember_latest(self._root,datetime.now(UTC))
            except (OSError,ValueError,KeyError,TypeError):
                return {'status':'unavailable','recorded_history':'unavailable'}
            try:
                result=strategy_entries.collect(self._root,self._entry_cache)
            except Exception:
                self._restore_retained()
                raise
            if result.get('status')!='collected':
                self._restore_retained()
            self._retained = None
            if result.get('status')=='collected':
                try:
                    strategy_entry_history.remember_latest(self._root,datetime.now(UTC))
                except (OSError,ValueError,KeyError,TypeError):
                    history_status='unavailable'
                if self._pending_prices_now_quotable(datetime.now(UTC)):
                    # The current observation is kept so a failed fresh one
                    # leaves the window's quote refreshes exactly as they were.
                    self._retained = dict(self._entry_cache)
                    self._entry_cache.clear()
                    self._reacquired_at = time.monotonic()
                    result = {**result, 'reacquire': 'scheduled'}
            return {**result,'recorded_history':history_status}
        from backend.core.dependencies import get_structured_llm_client
        from backend.market import current_opportunities

        return current_opportunities.collect(self._root, get_structured_llm_client())

    # True when a planned name is still waiting for an engine price, time
    # remains in the window, the last fresh observation is old enough, and the
    # latest quote page shows the name would pass the engine's own checks now.
    def _pending_prices_now_quotable(self, now):
        from backend.market import (
            execution_quotes,
            strategy_entries,
            strategy_publication,
        )
        from backend.market import forward_market_evidence as market

        last = self._reacquired_at
        if last is not None and time.monotonic() - last < REACQUIRE_SECONDS:
            return False
        try:
            instant = market._as_of(now)
            _, _, completed = market._window(instant)
            remaining = completed + timedelta(seconds=WINDOW_SECONDS) - instant
            if remaining.total_seconds() < REACQUIRE_SECONDS:
                return False
            snapshot = strategy_publication.read(self._root, now)
            value = strategy_entries.read(self._root, snapshot, now)
            pending = [
                name for name, row in value['rows'].items()
                if row.get('action') in ('Buy', 'Sell')
                and row.get('state') == 'unavailable' and row.get('quote_at') is None
            ]
            if not pending:
                return False
            page = base64.b64decode(value['quote_receipt']['body_base64'])
            quotes = json.loads(page)['quotes']
        except (OSError, ValueError, KeyError, TypeError):
            return False
        for name in pending:
            if not isinstance(quotes.get(name), dict):
                continue
            described = execution_quotes.describe(quotes[name], 'iex', True, instant)
            if described.get('eligible') and described.get('spread_verified') is True:
                return True
        return False

    # Put the observation back when the fresh one could not be acquired.
    def _restore_retained(self):
        if self._retained is not None:
            self._entry_cache.clear()
            self._entry_cache.update(self._retained)
            self._retained = None
