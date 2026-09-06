# AniOS

AniOS is a personal assistant that runs on hardware in one house. Two DGX
Sparks serve every model it uses, and the database sits beside them, so your
conversations and everything it remembers about you stay on those machines.
Only two kinds of traffic leave: web searches, screened first so personal
facts are not sent out, and the messages it sends you.

You use it in a browser at [deep-matter.com](https://deep-matter.com), or by
text message, one to one or in a group.

It is a real system in daily use rather than a finished product. Anything that
is planned rather than working is labelled as such; see
[the roadmap](docs/ROADMAP.md) for what is next and
[the handoff](docs/NEXT_SESSION.md) for the state of the running system today.

## What it does

- **Remembers you.** What you like, where you live, what you cannot eat. It
  saves those itself as you talk, uses them when the question calls for it,
  and shows them to you so you can correct or delete any of them. A hard limit
  like an allergy removes a suggestion outright rather than ranking it lower.
- **Searches when it needs to.** It decides for itself whether a question needs
  the internet, then answers from what it found and names the sources. When a
  search finds nothing, it says so instead of filling the gap.
- **Handles pictures.** It draws and edits images locally, reads photos you
  send it, and can find an old picture again from a description of it.
- **Makes things you can keep.** A chat can become an editable diagram, a Word
  or PDF document, or a slide deck built from real Office objects.
- **Does things later.** Reminders, recurring messages, and a weekly sweep for
  events near you, on a queue that survives a restart.
- **Works in a group chat.** It reads the whole room for context but answers
  only when spoken to, and keeps each person's private facts to themselves.
- **Runs agents on its own.** A code reviewer and a security reviewer read one
  commit through a read-only window and report only findings whose evidence
  they can point to in the code. A daily reviewer reads your own conversations
  for places the assistant let you down, and asks before it changes anything.

## How it is put together

- **The models.** DeepSeek-V4-Flash spans both Sparks and does all the text
  work: replying, choosing tools, writing decks. Qwen3-VL reads images on the
  second Spark, and Nomic turns text into vectors for retrieval. Pictures are
  drawn by FLUX.2 Klein on a Windows desktop with a consumer GPU, the one part
  of the system that is not always on; when it is off, an image request says so
  rather than hanging. Each role is configured
  separately behind one OpenAI-compatible boundary, so a role can move to a
  different model without touching the code that calls it.
- **The backend.** FastAPI, with PostgreSQL and pgvector holding memory,
  conversations and artifacts, and Redis holding queues and short-lived state.
- **Choosing tools.** The model picks from a shortlist assembled per turn.
  Every tool carries a contract saying what it changes, whether it is safe to
  retry, and whether it needs your permission first, and the loop that runs
  them is bounded by a clock, a step count and a repeat guard.
- **Accounts.** Invitation only, with one-time expiring codes, Argon2id
  password hashes, revocable browser sessions, and every record owned by a user
  id the server derives rather than one the browser claims.
- **The front.** A React and Vite console for development, and the public site
  served through a local Nginx gateway and a Cloudflare tunnel. The database,
  the model servers and the workers are not reachable from outside.

## Running it

The supported paths and the environment variables they need are in
[the development guide](docs/DEVELOPMENT_GUIDE.md). Do not run the Compose
backend and a host Uvicorn process on port 8000 at the same time.

Start everything, including the image backend:

```bash
bash scripts/start-anios.sh
```

`docker compose up` on its own starts the core services but not the image
backend, so treat it as an incomplete start whenever pictures are part of what
you are testing.

Deploy a change with `bash scripts/deploy.sh`. It runs the unit suite and the
routing gate first, backs the database up, migrates, restarts, and then runs
the live checks in the background; nothing ships if a gate is red.

On the machine running the stack:

```text
Public UI:        https://deep-matter.com
Backend health:   http://localhost:8000/health
OpenAPI UI:       http://localhost:8000/docs
Frontend:         http://localhost:5173
Local gateway:    http://localhost:8080
Capability MCP:   http://localhost:8001/mcp
PPTX renderer:    http://localhost:8002/health
```

Reaching those addresses does not prove chat or persistence works. Two rules
decide what counts as working, and both are older than any of this code:

- Anything a person sees is verified only when a browser exercises it, in an
  automated test or a written-down manual session. An API answering is not the
  page working.
- Anything a model decides is verified only when a functional test sends the
  real prompt to the real model and checks the answer
  (`backend/tests/functional/`). A structural test proves the call happened,
  never that the answer was any good.

## Documentation

- [Agent instructions](AGENTS.md)
- [Architecture](docs/ARCHITECTURE.md): start with Part I if you are new (what it is, the machines, a message's path, every subsystem step by step), Part II for every engineering decision and why, Part III for the implementation reference.
- [ML system design](docs/ML_SYSTEM_DESIGN.md): the serving decisions - quantisation, KV cache, parallelism, context against memory, retrieval thresholds, decoding - each with what was measured, why, and what was tried and rejected.
- [Agent catalog](docs/AGENT_CATALOG.md): every specialized agent, what its model decides, and where its prompt, card and diagram live - and which of them run an agentic loop.
- [Tool catalog](docs/TOOL_CATALOG.md): every tool the router may call, what it does, what the model fills in, and when its definition is put in front of the router. Generated from the rows by `python -m backend.cli.generate_tool_catalog`; a test fails when the page and the code disagree.
- [Canonical system diagram](docs/diagrams/anios-system.svg)
- [Scalable inference target](docs/diagrams/inference-scaling-target.svg)
- [Authentication and ownership](docs/diagrams/authentication-subsystem.svg)
- [Detailed subsystem diagram catalog](docs/diagrams/README.md)
- [Development and validation](docs/DEVELOPMENT_GUIDE.md)
- [Roadmap](docs/ROADMAP.md)
- [Next session handoff](docs/NEXT_SESSION.md)
- [Changelog](docs/CHANGELOG.md)
- [Security](docs/SECURITY.md)
- [Architecture decisions](docs/adr/0001-clean-architecture-and-modular-structure.md), including [local visual artifacts and resource-aware orchestration](docs/adr/0003-local-visual-artifacts-and-resource-aware-orchestration.md), [hybrid free-tier web research](docs/adr/0004-hybrid-free-tier-web-research.md), [typed editable presentation generation](docs/adr/0005-typed-editable-presentation-generation.md), [versioned visual semantics, memory references, and editing](docs/adr/0007-versioned-visual-semantics-memory-and-editing.md), the [default vLLM runtime](docs/adr/0009-vllm-default-local-inference-runtime.md), and [DeepSeek on two DGX Sparks](docs/adr/0015-deepseek-on-two-sparks-text-roles-consolidated.md); every record is catalogued with its reasoning in the architecture document's Part II

## Status language

- `VERIFIED`: directly observed through an applicable runtime or functional check.
- `FAILED`: an attempted check did not meet its acceptance criteria.
- `UNVERIFIED`: no adequate check has been completed.
- `SCAFFOLDED`: structure exists, but complete behavior is not implemented or demonstrated.
- `MOCKED`: behavior is supplied by a placeholder or fixed test implementation.
- `PLANNED`: future capability; it must not be described as current behavior.
