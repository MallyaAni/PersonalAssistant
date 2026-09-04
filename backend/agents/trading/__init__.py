"""The trading analyst agent.

A personal analyst that reads a person's own trading history and names what
repeats. Deliberately not imported: `backend/agents/__init__.py` must not
re-export from here, because that makes importing the prompts pull the agent,
which pulls the provider that imports the prompts (the cycle that broke this
repository once). Import `backend.agents.trading.autopsy` and
`backend.agents.trading.card` directly.
"""
