"""Deck — the presentation agent (registry id `presentation`).

`PresentationAgent` keeps its name because the domain package it drives is
`backend/presentations/`; the folder is named for what the product calls the
agent.
"""

from backend.agents.deck.agent import PresentationAgent

__all__ = ["PresentationAgent"]
