# 0023 - The router keeps a catalogue, not a list

Date: 2026-09-03

## Status

Accepted; the mechanism is built and off by default until measured on the
labelled cases (`ROUTING_TOOL_SEARCH_ENABLED`).

## Context

Every turn, `MainActionSelector` sent the full schema of every tool the
person could possibly want: fourteen built-ins, web search, each MCP alias,
and one per skill they have taught. The operator's question was the right
one - "the number of things we route to can change and grow" - and the list
does grow on its own: a skill taught in conversation adds a tool, an MCP
server adds several.

Two things go wrong as it grows, and Anthropic measured both when building
the tool search tool for its own API:

- **Context.** A five-server setup costs about 55k tokens of definitions
  before any work is done; tool search cuts that by over 85%, loading the
  three to five tools a request actually needs.
- **Accuracy.** Selection degrades once a model is choosing among more than
  thirty to fifty tools. Their guidance: standard tool calling below ten
  tools, tool search at ten or more, or whenever the library grows over time.

This week's failures are the same family: the router picked a check-in tool
for a passing remark, chose a history search for a bare "yes", and wrote a
place-less query for a place-bound question. Each was settled by a rule in
code, which is right for a rule that must always hold, but it does not
scale to "the list keeps growing".

## Decision

Adopt the shape Anthropic uses, implemented on our side because AniOS routes
on its own model rather than through the Claude API. Their documentation
describes exactly this client-side form: a custom search tool that returns
tool references, which the caller expands.

- **A catalogue, not a list.** `backend/tools/catalog.py` turns the turn's
  tool definitions into one-line entries: name, first sentence, argument
  names. The index costs one line per tool per turn; the schemas cost
  nothing until they are needed.
- **A core that stays loaded.** `ALWAYS_LOADED` is chosen by seven days of
  live usage, not by taste: past conversations (46 turns), web search (36),
  manage scheduled tasks (25), schedule task. Picture tools load only when a
  picture is in view, because the interface state already decides whether
  they can be used at all.
- **One search round.** The model calls `find_tools` with what it needs in
  plain words; BM25 over names, descriptions and argument names returns up
  to five; those definitions are added and the decision is made again. Never
  a second search: that is the same question asked twice.
- **The system prefix never changes.** The index and the loaded-tools note
  go in the user content, so the cached prompt prefix stays byte-identical -
  the same property Anthropic preserves by keeping deferred tools out of the
  system-prompt prefix.
- **Off until measured.** `ROUTING_TOOL_SEARCH_ENABLED` defaults to false.
  The 108 labelled selection cases are run both ways on the real model; the
  per-tool floors decide whether it ships.

## Consequences

- The tool set can grow without every turn paying for it. A person's skills
  and any MCP server's tools are catalogued rather than pasted.
- One extra model call on the turns that need a tool outside the core. The
  common turns - a question, a search, a reminder, a recall - pay nothing.
- BM25 is written out rather than added as a dependency: twenty short
  documents, forty lines of code, and no wheel to keep current.
- The catalogue makes tool descriptions load-bearing in a new way: the first
  sentence is what the model reads in the index. Anthropic's guidance on
  namespacing (`document_`, `image_`) and on keywords that match how people
  describe tasks now applies to this repository's descriptions too.
- What this does not do: it does not make a judgement steadier. A model that
  picks the wrong tool from five is not helped by having been given five
  instead of twenty. The measured floors and the code rules stay.

## Sources

- Tool search tool, including `defer_loading`, the 30-50 accuracy cliff, the
  55k-token example, and the custom client-side form:
  https://platform.claude.com/docs/en/agents-and-tools/tool-use/tool-search-tool
- Writing tools for agents (consolidation, namespacing, descriptions,
  evaluation-driven iteration):
  https://www.anthropic.com/engineering/writing-tools-for-agents
- The wider argument for just-in-time loading:
  https://www.anthropic.com/engineering/advanced-tool-use
