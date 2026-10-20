"""Keep chart judgments current even when no browser is open."""

import os
from datetime import UTC, datetime

from backend.services.session_price_collector import SessionPriceCollector


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

    # Complete original recording metadata before another numerical view can replace its discovery source.
    def _collect_once(self):
        from backend.market import strategy_publication, strategy_entries, strategy_entry_history
        if (self._root / strategy_publication.DIRECTORY).exists():
            history_status='available'
            try:
                strategy_entry_history.remember_latest(self._root,datetime.now(UTC))
            except (OSError,ValueError,KeyError,TypeError):
                return {'status':'unavailable','recorded_history':'unavailable'}
            result=strategy_entries.collect(self._root,self._entry_cache)
            if result.get('status')=='collected':
                try:
                    strategy_entry_history.remember_latest(self._root,datetime.now(UTC))
                except (OSError,ValueError,KeyError,TypeError):
                    history_status='unavailable'
            return {**result,'recorded_history':history_status}
        from backend.core.dependencies import get_structured_llm_client
        from backend.market import current_opportunities

        return current_opportunities.collect(self._root, get_structured_llm_client())
