"""The code-review agent: a read-only review of one commit, run durably.

Its judgement lives in `prompts.py` (which files to read, what is wrong);
its effects are reads through the `repo` MCP server; `world.py` is what the
durable-run controller drives. Nothing is re-exported here on purpose: see
docs/AGENT_CATALOG.md, "Adding an agent".
"""
