"""Deck — the presentation agent (registry id `presentation`).

`agent.py` is the LangGraph adapter, `card.py` is what the workspace shows, and
`prompts.py` is what Deck asks the model for.

Nothing is re-exported here on purpose. `presentations/provider.py` imports the
prompts, and a re-export would make importing them pull the agent, which pulls
the provider — a cycle. `PresentationAgent` keeps its name because the package
it drives is `backend/presentations/`; the folder is named for what the product
calls the agent.
"""
