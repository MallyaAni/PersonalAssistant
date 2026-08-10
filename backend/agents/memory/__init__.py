"""Memory capture — the agent that proposes what to remember from a chat turn.

It has no registry card: it is not something the workspace lists, it is a step
in every conversation. The folder exists for the same reason the others do — the
prompt is this agent's judgement and belongs with it.

Nothing is re-exported here. A re-export is what made `agents/deck` import its
own provider in a cycle.
"""
