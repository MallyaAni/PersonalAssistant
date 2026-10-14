"""Keep chart judgments current even when no browser is open."""

import os

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

    # Invoke the installed model over public chart facts, without account access.
    def _collect_once(self):
        from backend.core.dependencies import get_structured_llm_client
        from backend.market import current_opportunities

        return current_opportunities.collect(self._root, get_structured_llm_client())
