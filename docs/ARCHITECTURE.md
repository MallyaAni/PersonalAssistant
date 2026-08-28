# AniOS Architecture

This document has three parts. **Part I** is for someone who has never seen
this project: what AniOS is, what runs where, and what happens when you send
it a message. **Part II** is the catalogue of engineering decisions and the
reasons behind them - the formal decision records plus the decisions that were
made while running the system, which are the ones a newcomer would otherwise
have to rediscover the hard way. **Part III** is the implementation reference
that engineers working in the code use day to day.

Runtime results and active blockers belong in [NEXT_SESSION.md](NEXT_SESSION.md);
future sequencing belongs in [ROADMAP.md](ROADMAP.md); the rules for working
in this repository are in [AGENTS.md](../AGENTS.md). This document records what
is built and why. Where something is not built, it is labelled `PLANNED`.

---

# Part I - Start here

## What AniOS is

AniOS is a private personal assistant that runs entirely on hardware its owner
controls. You talk to it in a browser (`deep-matter.com`, through a Cloudflare
tunnel) or by texting it over iMessage (alone, or in a group with friends who are approved users). It remembers what you tell it, can find
anything either of you has ever said, searches the web when a question needs
it, makes pictures and edits them, draws diagrams, builds slide decks, runs
scheduled tasks ("remind me every weekday at 7"), and - through an agent called
Scout - handles anything you want done later or on a schedule, from "remind
me every weekday at 7" to its own standing sweep for things happening near
you that match what you care about.

Nothing about a conversation leaves the owner's machines except a deliberately
minimised web-search query, and only when the assistant decides a search is
needed. Every model that reads your words runs locally. That constraint shapes
most of the architecture below.

## The machines

| Machine | Address | What it holds | When it is on |
| --- | --- | --- | --- |
| **spark1** (NVIDIA DGX Spark) | `172.16.8.3` | Every application container, PostgreSQL (+pgvector), Redis, the Cloudflare tunnel, the text-embedding service, the reranker service, and half of the main language model | Always |
| **spark2** (NVIDIA DGX Spark) | `172.16.8.5` | The other half of the main language model, the vision model, and the first backup mirror | Always |
| **Mac** (MacBook Pro) | `172.16.8.2` | The iMessage bridge - the only thing that can send or read texts - and the second backup mirror (ciphertext only) | Always |
| **Desktop** (Windows, RTX 5080, 16 GB) | `172.16.8.6` | ComfyUI running FLUX.2 Klein for image generation and editing | Sometimes; when it is off, image requests get an honest "try again later" |

Each Spark is a GB10 with 121.7 GiB of unified memory. The main model needs
roughly 97 GiB on *each* of them, which is why it is split across the two
(tensor-parallel 2) and why the vision model lives on spark2 rather than
alongside it. The Sparks have no remote management controller and no
wake-on-LAN: a Spark that is powered off needs a person to press its button.
Over-allocating GPU memory hangs a Spark outright, so memory headroom is
treated as a hard safety margin rather than an optimisation.

## What happens when you send a message

1. **A channel receives it.** The browser posts to the backend API; a text
   arrives on the Mac, where the bridge only accepts senders who have been
   allowlisted, and a worker on spark1 polls for it (every 3 s, tightening to
   1.5 s while a conversation is active). Images travel both ways.
2. **One model call decides what kind of turn it is.** The router
   (`MainActionSelector`) shows the main model a menu of tools - search the
   web, generate or edit an image, draw a diagram, make a deck, search past
   conversations, schedule a task, a taught skill, or one of the user's
   connected MCP tools - and the model picks at most one with a native tool
   call. There is no regex and no keyword list anywhere on this path; a rule of
   this repository is that *intent is decided by a model, never by pattern
   matching*.
3. **Context is assembled.** The recent conversation window, a rolling digest
   of older turns, the typed long-term memories that match, images in view,
   and - if the router chose it - evidence found by searching every past
   conversation. Each piece has a token budget and a priority, so the prompt
   is bounded and cache-friendly rather than "everything we have".
4. **The reply model answers.** DeepSeek-V4-Flash streams the answer; a
   selected action (a search, a recall, a tool result) runs first and its
   result is placed in the prompt as *untrusted evidence* - it can inform the
   answer but can never grant permissions or issue instructions.
5. **The turn is remembered.** The exchange is stored encrypted, embedded
   (both what you said and what it answered) so it can be found later, and a
   classifier decides whether the message stated a fact worth keeping as
   long-term memory - a name, an interest, where you live, an allergy. That
   save happens automatically; the classifier is deliberately conservative
   about what counts.
6. **The reply is delivered** - streamed to the browser, or sent back through
   the Mac as a text pinned to the message it answers.

A plain message costs about three model calls (routing, one embedding, the
reply). The whole path is drawn in
[chat-orchestration.svg](diagrams/chat-orchestration.svg).

## The models, and why each is where it is

| Role | Model | Where | Why this one, here |
| --- | --- | --- | --- |
| Conversation, routing, structured output, diagrams, decks, memory classification | **DeepSeek-V4-Flash** (vLLM, tensor-parallel across spark1+spark2, 1M-token context with an NVFP4 KV cache) | Sparks | Chosen by a blind read-off against Qwen and Nemotron, then kept after a measured comparison (see `MODEL_EVALUATION.md`). Routing and classification decode at temperature 0 so the same question always routes the same way. |
| Vision (looking at photos) | **Qwen3-VL-8B** | spark2 `:8001` | DeepSeek is text-only, so a second model must stay resident to read pixels. It sits on spark2 because that node has the headroom. |
| Text embeddings | **nomic-embed-text-v1.5** (768-d) | spark1 `vllm-embedding` | Shares one vector space with the image embedder below, so a sentence can find a picture. That alignment is why the text embedder cannot be swapped alone. |
| Image embeddings | **nomic-embed-vision-v1.5** (ONNX, CPU) | spark1, in-process | Aligned to the text model above; small enough to run without a GPU. |
| Reranking (second opinion on retrieved candidates) | **Qwen3-Reranker-0.6B** | spark1 `vllm-reranker` | A cross-encoder reads query and candidate *together*, which is where retrieval precision comes from. Fail-soft: if it is down, the first-pass order stands. |
| Image generation and editing | **FLUX.2 Klein 9B** via ComfyUI (FLUX.1 Kontext for instruction edits) | Desktop | The only machine with a discrete GPU that is not full. Image work is available while the desktop is on, and honestly unavailable when it is not. |
| Web search | Gemini grounding or Tavily | External | The one outbound boundary; queries are minimised and screened before they leave. |

Everything is served through an OpenAI-compatible boundary, so the application
never knows which runtime is behind a role; roles are configured
independently (`MAIN_LLM_*`, `ROUTING_LLM_*`, `VISION_*`, `EMBEDDING_*`,
`RERANKER_*`) and an unset role inherits the next broader one.

## How memory works, in plain words

- **Short term** is the recent window of the conversation plus a rolling
  digest of what came before it, so a long chat stays coherent without
  re-sending everything.
- **Long term** is a set of typed stores in PostgreSQL: your profile,
  episodic events, semantic facts, entities and relationships, procedures,
  knowledge documents, and Scout's interests and home locality. Facts get in
  by being stated plainly in conversation and passing the memory classifier,
  or by being saved explicitly. You can see, correct, export, and delete all
  of it.
- **Total recall.** Every exchange is embedded and indexed (pgvector, HNSW),
  so the assistant can search everything either of you has ever said - by
  meaning, not keywords, because the text itself is encrypted and cannot be
  grepped. The router chooses this when you refer to something not in view
  ("what was that restaurant you mentioned in March?"); the search fetches
  the top 40 by vector distance, the reranker cuts them to the 12 that
  actually answer, and the model reads those as evidence. A separate,
  quieter path also injects the three most similar past remarks on every
  turn.
- **Space migrations are one command.** Each stored vector records which
  model and scheme produced it; retrieval matches only the current signature,
  and a backfill command re-embeds whatever does not match. Changing the
  embedding model therefore degrades to "not yet rebuilt", never to wrong
  answers.

## Safety and privacy in one screen

- Free-text columns are **encrypted at rest**; the key is escrowed off the
  machine that holds the data. Phone numbers and addresses are looked up by a
  **keyed HMAC digest**, so a database dump alone cannot enumerate them.
- **Everything retrieved is untrusted data**: search results, tool output,
  recalled turns, and memories are placed in the prompt as evidence and
  cannot grant permissions or act as instructions.
- **Egress is screened once, centrally**: any text about to leave the machine
  - a search query, an MCP tool argument - passes one screening policy.
- **Who may talk to it is explicit**: web accounts are invite-only with
  Argon2id passwords and revocable sessions; sign-up collects a phone number
  that approval turns into both an AniOS identity and a Mac allowlist entry
  in one decision. A number belongs to one account only.
- **Databases are not on the network**: PostgreSQL and Redis listen on the
  host's loopback; containers reach them by compose-network name.
- **Backups exist in three places** - spark1, spark2, and the Mac - nightly,
  with a proven restore. The Mac copy is ciphertext only.

## How to read the rest

- The [published architecture page](architecture.html) shows all 22 canonical
  diagrams with zoom; [diagrams/README.md](diagrams/README.md) says which
  diagram answers which question. Mermaid sources are authoritative; SVGs are
  generated and fingerprint-checked.
- Part II below explains *why* things are the way they are.
- [ML_SYSTEM_DESIGN.md](ML_SYSTEM_DESIGN.md) is the ML systems engineering:
  quantisation, KV cache, parallelism, context against memory, thresholds,
  decoding - each as the options considered, what was measured, the choice,
  and what would change it, with a ledger of what was tried and rejected.
- Part III is the implementation reference, section by section.
- Sibling documents: [AGENT_CATALOG.md](AGENT_CATALOG.md) (every agent and
  what its model decides), [TASKS_ARCHITECTURE.md](TASKS_ARCHITECTURE.md)
  (scheduled tasks and skills), [MODEL_EVALUATION.md](MODEL_EVALUATION.md)
  (how models are chosen here, with measurements), [SECURITY.md](SECURITY.md),
  [RESTORE.md](RESTORE.md), [DGX_MIGRATION.md](DGX_MIGRATION.md), and the
  decision records in [adr/](adr/).
## Each subsystem, step by step

The memory overview above is the shape every subsystem is described in here:
what happens in order, what gets stored, which decisions a model makes and
which are code, and what you can see and control. Reference detail for each
lives in Part III; the diagrams are linked from each heading.

### Searching the web ([diagram](diagrams/search-research-subsystem.svg))

1. The same routing call that decides everything else about the turn decides
   whether to search, and writes the query itself.
2. Search-control wording ("search online for", "cite the source") is stripped
   so the provider receives the factual subject.
3. The query is screened before it leaves: a secret or account identifier
   blocks the search outright; a sensitive topic is minimised to the topic.
   The screen is deterministic code, "since a model asked to redact its own
   prompt can be argued out of it".
4. A provider is chosen by policy: an isolated Google worker (which receives
   only the minimised query under an anonymous ID - no history, memory, or
   identity) when a key exists, Tavily as the fallback, both only when you ask
   to cross-check. A daily quota protects the free tier.
5. A Google answer without grounding metadata is a failure, not a licence to
   answer; Tavily results below a measured score floor are dropped.
6. Survivors enter the prompt as quoted, untrusted evidence, and the answer
   shows provider-attributed source cards.

*Stored:* only a per-day call count, never a query or result. *The model
decides:* whether to search, and the query. *Code decides:* screening,
provider, quota, score floor. *You control:* keys, provider, the floor; blocked
or rewritten searches are reported, not silent.

### Pictures ([diagram](diagrams/visual-artifact-subsystem.svg))

1. The router decides whether you want a new picture, an edit of the one in
   view, or an answer about it - by meaning, not by the first verb.
2. Generation sends a bounded prompt and an allowlisted size to ComfyUI on the
   desktop (FLUX.2 Klein); an upload is validated as a real PNG/JPEG/WebP
   before any record exists.
3. An edit re-reads the owned original's bytes (integrity-checked) and sends
   *pixels plus your instruction* to the editor; a new revision is written
   beside the original, never over it, with parent, seed, steps, and the exact
   feedback recorded.
4. A question about a picture goes to the vision model on spark2, with the
   bounded prior thread replayed; the answer is stored as a thread on that
   image.
5. Every image gets an aligned embedding, so a sentence can find it later; the
   first analysis of an upload is also indexed as memory, so an ordinary turn
   can recall what the picture showed.
6. Recall by meaning uses a ceiling *and* a margin over the runner-up, because
   with the ceiling alone "every distractor produced a false positive".

*Stored:* artifact records with lineage, the bytes under an opaque root, one
vector column of their own, and the derived description as memory (deleted in
the same commit as the image). *The model decides:* intent, which offered
image "that one" means, the description, prompt merges. *Code decides:*
validation, ownership, retrieval bounds, lineage. *You control:* which image is
the reference, download, delete, cancel mid-generation. When the desktop is
off, you are told so.

### Scout, first shape - things happening near you ([diagram](diagrams/discovery-subsystem.svg))

Scout is the scheduling agent, and it has two shapes that are one job to the
person asking: the ambient sweep below, and anything else wanted on a
schedule (the next section). The agent card, the catalog, and the assistant's
own answers all call both "Scout".

1. Approved facts - where you live, what you are into and how strongly - are
   the whole input; a stated interest is proposed by the classifier and
   written only on approval.
2. A sweep fires on your own cadence, using your current place if you are
   travelling, else home.
3. One model call turns each interest into a search subject and a scoring
   vector; feeds and one bounded web query per interest supply candidates.
4. Novelty is two cheap-first passes: exact identity, then near-duplicate by
   vector; only something already *announced* suppresses a candidate.
5. What qualifies is deterministic - best interest, strength weighting, score
   floor, lead-time window, geography; a cross-encoder re-orders the
   shortlist; at most two "notable" interest-free finds are admitted.
6. The model names and describes each selected find, greedily, inside a
   grammar - no URL from the model survives - and the digest goes to each
   consented subscriber as one message per find with a calendar file attached,
   so a recipient anywhere can act on it without reaching this machine.

*Stored:* interests, localities, sources, seen items, familiarity, schedules,
runs, sent finds, subscribers. *The model decides:* the search subject, the
scoring vector, the order of a qualified shortlist, how a find reads. *Code
decides:* what qualifies. *You control:* interests and strength, home versus
current place, sources, subscribers, thumbs-up/down (recorded, deliberately
not yet fed back into ranking), "already known" dismissals, export and
delete-all.

### Scout, second shape - scheduled tasks and skills ([design](TASKS_ARCHITECTURE.md), [diagram](diagrams/scheduled-tasks-subsystem.svg))

1. You say it - "remind me every weekday at 7 to check the Spark temps" - and
   the router understands it as a `schedule_task` call with instruction,
   cadence, and time as fields. No syntax, no keyword.
2. The task is saved in your time zone (taken from your home locality; with
   none known, the reply asks for the city and saves nothing).
3. A runner in the discovery worker enqueues each due slot exactly once,
   claims it with a lease, and renews the lease while the turn runs.
4. The firing posts the instruction through the ordinary chat path on the
   task's own conversation, so it can search, draw, or recall like any turn.
5. The result is delivered on the task's channel - an iMessage bubble, or the
   run record for the web. A conditional check - "message me each morning if
   search credits are below 100" - whose condition does not hold answers
   `NOTHING_TO_REPORT`, and the run finishes `quiet` with nothing sent.
6. A fired turn is walled off from changing automation ("a reminder once
   spawned four copies of itself") and exempt from memory capture ("the same
   fact 365 times a year, unattended").

*Stored:* tasks, runs, taught skills. *The model decides:* that this is a
scheduling request, the self-contained instruction, cadence fields, which
existing task "the weather one" means. *Code decides:* cadence math and DST,
exactly-once slots, leases, the walls above, and that a reply of exactly
`NOTHING_TO_REPORT` is silence. *You control:* create, list,
pause, resume, cancel in plain language; the Automations panel shows every
task and skill.

### Texting it - the iMessage bridge ([diagram](diagrams/imessage-bridge.svg))

1. Someone on the allowlist texts the Mac. The bridge reads the Messages
   database read-only, keeps only allowlisted one-to-one senders, and never
   logs a body.
2. A worker on spark1 polls the bridge with a cursor it owns; nothing is
   processed twice.
3. The sender is matched to an account by the keyed digest of their number;
   an address that is not an active, approved subscriber of some account is
   ignored outright - "the second of two walls".
4. The text runs through exactly the endpoint the browser uses, with a
   short-lived token carrying one scope - the full pipeline, nothing special.
5. A picture in becomes a vision turn - every photo of a burst, in order and
   numbered, after waiting out iCloud's lazy download for about a minute
   (HEIC is converted on the Mac); a picture out goes as an attachment
   under the size margin the bridge enforces (diagrams are rasterised because
   the bridge allows only JPEG, PNG, and calendar files). A picture the
   person already has is sent again the same way when they ask to see it.
6. The reply is pinned to the message it answers, and a long-press reply from
   you pins the assistant to *that* image rather than the newest one.
7. Before answering a text, the worker asks the routing model whether the
   person has finished and whether an answer is wanted, so "ok so" waits for
   the rest, "thai then" gets one answer, and "thanks!" gets none - judged by
   meaning, never by a timer (a pending fragment is answered after 45 s
   regardless).
8. In a group chat the Mac's operator has listed ([design](GROUP_CHATS_ARCHITECTURE.md),
   [ADR 0016](adr/0016-a-group-is-an-account.md), [diagram](diagrams/group-chats-subsystem.svg)),
   only what is addressed to the assistant leaves the Mac - a reply in a
   thread on one of its bubbles, an @mention, or its name. Every member must
   be an approved user or it stays silent and you get one text. The room is
   then an account of its own (`group:<slug>`) with its own session, memory,
   tasks, and Scout; members' names, likes, home area and everyday remembered
   statements are known in the room (what is sensitive is judged by meaning
   and never reaches it); a fact said in the room lands in the
   speaker's memory when it is theirs and in the group's with its source
   otherwise, never in another member's on someone else's word; and the
   answer, digests, and reminders post back into the chat.

*Stored:* durable state only through the normal chat path; the bridge and
worker keep a cursor, seen IDs, pending bursts, parked turns, and
bubble-to-artifact maps in Redis. *Never lost to a restart:* the cursor
moves only after a poll is handled and chat.db is the ledger, so a message
that arrives while the worker or the Mac is down is read when they are
back; one that finds the backend itself away (a deploy's restart, the
database unreachable) is parked and retried every poll for ten minutes -
one "give me a minute" bubble after the first - and only then apologised
for. A turn that genuinely failed is apologised for at once; retrying a
bug helps nobody. *The model decides:* only the answer (and whether one is wanted) -
the recipient is always the bridge's `reply_to` handle, "never anything the
model wrote". *Never leaves the Mac:* bodies from anyone not on the
allowlist, anything in a group chat that is not listed or not addressed to
the assistant, and the text the reaction tools compare. *You control:* five
independent grants on the Mac (send, read reactions, read incoming, read
attachments, read listed groups), which Apple ID sends, the allowlist itself
- which approval on the web can extend - and the group list, which nothing
but the Mac's environment can.

### Slide decks and diagrams ([deck diagram](diagrams/presentation-subsystem.svg), [Deck agent](diagrams/agent-deck.svg), [Diagram agent](diagrams/agent-diagram.svg))

1. A deck request returns a durable job immediately; a worker claims it by
   lease, so the work outlives your browser tab.
2. One privacy-screened web search grounds the outline - at outline time,
   "where a slide is told to carry a statistic; by the slide pass the only way
   to satisfy that instruction is to make one up".
3. The model plans the outline, then writes one slide at a time behind a gate
   that lets your chat go first; it chooses each slide's shape from seven
   layouts as a grammar choice, with that layout's fields required.
4. Deterministic code owns geometry - measured from text length and point size
   - renders with PptxGenJS, and validates the file by inspecting its native
   objects, without PowerPoint.
5. A validated draft becomes an append-only revision; feedback on one slide
   changes only that slide, and edits against a stale base fail rather than
   overwrite newer work.
6. A diagram is one model call for title, type, and Mermaid within strict
   bounds; the validator refuses rather than ships something that will not
   draw, and the browser renders it with HTML labels disabled and lets you
   edit the source.

*Stored:* decks, revisions, jobs, the PPTX bytes, diagram artifacts. *The
model decides:* plan, content, slide shape, revisions, Mermaid. *Code decides:*
geometry, storage, validation, promotion, delete and reorder. *You control:*
the brief, per-slide feedback with its own thread, add/delete/reorder,
revision history, download, cancel; editable Mermaid and SVG download.

### Connected tools - MCP ([diagram](diagrams/tool-memory-subsystem.svg))

1. Each configured server's live catalogue is inspected and embedded; a tool
   description that reads like an instruction is quarantined, not indexed.
2. On a turn, the user-scoped index is searched by meaning and at most five
   schemas are offered - retrieval first, because exposing a hundred tools
   "drops selection accuracy to roughly 13%".
3. The model may pick one and fill its arguments; it never receives an
   invocation handle. Discovery is not authorisation.
4. Seven gates run in order: resolve the server from local config; confirm
   unless the server is `trusted` or `read_only`; re-read the live catalogue;
   compare its fingerprint (which covers the description - "the rug-pull
   window"); re-inspect; validate arguments; screen every string argument
   through the same egress policy as a search query.
5. Retries happen only for safe servers and only on transport failure; a
   refusal is never retried.
6. Results are bounded and inspected; instruction-shaped output is shown to
   the model as quoted data with a note not to follow it.

*Stored:* tool descriptors, approved preferences, sanitised outcomes. *The
model decides:* which shortlisted tool and its arguments. *Code decides:*
everything else. *You control:* server configuration and its risk class,
explicit confirmation for anything consequential; the UI shows each call as
running, succeeded, refused, or failed without exposing arguments or results.
More integrations (Instagram, Google Drive) each arrive with their own
routing floor and provider-contract tests before they are advertised.

### Accounts, sign-up, and approval ([diagram](diagrams/authentication-subsystem.svg))

1. Asking for access takes a display name, a username, a password (hashed on
   arrival), and a phone number in E.164 - "not a contact detail, a
   credential", because the bridge identifies you by it.
2. Uniqueness is checked for the username and the number, against requests
   *and* existing subscribers, and checked again at approval where the race
   lands.
3. The operator approves, and that one decision creates the account, enrols
   the number as a subscriber, and allowlists it on the Mac - "two
   allowlists, one decision", because keeping them by hand drifted.
4. A newly approved person gets an introduction generated from the same
   capability list the router offers as tools, "because a fixed welcome is
   accurate the day it ships and then quietly starts lying".
5. Logging in verifies the password and sets a host-only cookie whose token is
   stored only as a digest; every owned request resolves that session to a
   stable owner ID that never changes, even if the login name does.
6. Sharing between accounts will copy on accept rather than grant access
   into another store (decided, not yet built), because single ownership is
   load-bearing in 133 query sites.

*Stored:* accounts, sessions (digests only), invitations (digests only),
access requests, subscribers, and the Mac's separate grant file. *The model
decides:* only the welcome text. *Code decides:* everything else - parsing,
digests, Argon2id, sessions, rate limits, origin allowlist, scopes ("ownership
answers *who*; scopes answer *what*"). *You control:* asking, polling your
request; the operator sees on approval whether the bridge grant and the
welcome actually happened.

---

# Part II - The engineering decisions, and why

Two kinds of decision shaped this system. The first kind is written down as a
decision record in [adr/](adr/) before or as it was built. The second kind was
made while running the thing - after an outage, a measurement, or a real
failure - and lives in commit messages, `NEXT_SESSION.md`, and
`MODEL_EVALUATION.md`. A newcomer needs both, because the second kind is what
you would otherwise rediscover the hard way. Everything here is dated or
linked so it can be checked.

## The rules that shape everything

These come from [AGENTS.md](../AGENTS.md), which every agent and person working
in the repository follows. They explain more of the code than any diagram.

1. **Running behaviour is the source of truth.** Documentation records intent
   and verified knowledge; a decision record records a decision, not proof it
   was implemented. Evidence counts only when the source revision that
   produced it is known.
2. **Meaning is decided by a model, never by a pattern.** Whether a message
   wants a picture, a search, a diagram, or nothing; which picture "that one"
   means; whether something is worth remembering - every regex, keyword list,
   and bounded classifier written to make these judgements was deleted after
   failing on phrasing its author did not anticipate. Patterns are legitimate
   for *shape* (is this a PNG, does this parse as a UUID), never for intent.
3. **Every prompt is a feature and gets a functional test in the same
   change.** A test that a model was called, or that its reply parsed, does
   not show that it answered well. Tests assert on properties, not wording,
   so a reworded prompt survives and a changed behaviour fails.
4. **A prompt states a principle, never a case.** The incident that prompted
   a change goes in the file's notes or the commit, not in the text sent to
   the model - otherwise prompts become "a list of somebody's bad days" and
   the model learns to match the case instead of reasoning about the shape.
5. **Restrict in code, not in the prompt.** When a model will not follow an
   instruction, make the restriction structural (a schema, a bound, a
   deterministic step) rather than repeating the instruction louder.
6. **Every boundary that parses model output as data sends a JSON Schema**
   the runtime decodes as a grammar, and every decision decodes at
   temperature 0. A malformed reply becomes unrepresentable; the same
   question routes the same way twice.
7. **Everything retrieved is untrusted data.** Search results, tool output,
   recalled turns, and memories are literal evidence in the prompt and can
   never grant a permission or carry an instruction.
8. **Mermaid source is authoritative; SVG is generated.** Every modifying
   change declares its diagram impact, and a fingerprint check fails when a
   diagram and its source diverge.
9. **Measure on this hardware, not from a model card.** Model choices,
   quantisations, and serving flags are decided by numbers produced here
   (`MODEL_EVALUATION.md`), and a repeatable harness is a promotion gate, never
   sufficient proof by itself.
10. **Every new function carries a comment saying why it exists**, commits go
    to `main`, and a commit is a verified checkpoint only when its exact tree
    passed the acceptance path.

## The formal decision records

| ADR | Decision | Why this and not the alternative | Status |
| --- | --- | --- | --- |
| [0001](adr/0001-clean-architecture-and-modular-structure.md) Clean architecture | Routes delegate to services; memory, retrieval, models, tools, and repositories sit behind focused interfaces; LangGraph may orchestrate but "must not own AniOS memory, retrieval, user profiles, or domain policy". | Framework-centric layering couples behaviour to FastAPI/SQLAlchemy; microservices are premature before in-process boundaries are stable. No speculative interfaces: each must map to a real boundary or test need. | Accepted direction; partially conformed |
| [0002](adr/0002-typed-agent-memory-manager-and-pgvector-indexes.md) Typed memory manager, pgvector HNSW | Typed stores behind `AgentMemoryManager`; a coordinator may plan and retrieve but "cannot execute arbitrary SQL or authorize durable writes"; 768-d cosine vectors with HNSW indexes owned by Alembic. | A generic key-value vector store "would erase lifecycle and approval distinctions"; model SQL bypasses least privilege; IVFFlat needs representative data first. | Accepted, implemented |
| [0003](adr/0003-local-visual-artifacts-and-resource-aware-orchestration.md) Local visual artifacts | Mermaid is the diagram source of truth; a deterministic coordinator owns routing, job state, GPU leases, and cancellation - a model "cannot unload models, allocate hardware, authorize storage, or declare a job successful"; free local providers only, no cloud fallback. | Pixel models cannot be reviewed edge by edge; model-resource control is application policy; a paid fallback would quietly change the privacy posture. | Accepted, partially implemented |
| [0004](adr/0004-hybrid-free-tier-web-research.md) Hybrid free-tier research | The local model answers; deterministic policy decides eligibility and screens the query; an isolated Google worker sees "only the minimized public query under a constant anonymous worker ID"; missing grounding is a failure, not a licence to answer; Tavily is the fallback; a local daily quota protects the free tier. | Full context to Google is rejected because unpaid terms allow training on it; letting the model choose providers is rejected because freshness, privacy, quota, and fallback are application policy. | Accepted; Google branch unverified without a key |
| [0005](adr/0005-typed-editable-presentation-generation.md) Typed editable presentations | A focused agent produces a compact outline then one slide at a time; deterministic code expands it into a strict `DeckSpec`; the model has "no database, filesystem, authorization, job, promotion, or renderer-control authority"; stale-base edits fail rather than overwrite; PptxGenJS render, OOXML inspection, and LibreOffice open-check gate promotion. | Model-generated JavaScript would execute untrusted code; whole-slide images lose object-level editability; a cloud API breaks local-first. | Accepted, verified |
| [0006](adr/0006-hybrid-supervisor-and-qualified-model-roles.md) Supervisor and qualified roles | Execution authority stays outside the supervisor; roles are configured independently; "never promote a model from the harness alone". | One model for every role tied chat to the largest model; the smallest model failed a strict typed contract in production. | Superseded in part by 0009 (evidence kept) |
| [0007](adr/0007-versioned-visual-semantics-memory-and-editing.md) Versioned visual semantics | "Pixels remain artifacts, not memories" - memory holds a re-checked handle; image identity and revision identity are distinct (a lineage DAG; a failed candidate never replaces its parent); the editor receives the source pixels; "understanding does not authorize editing". | Prompt-only editing describes intent, not rendered pixels; bytes in memory duplicate sensitive data; in-place overwrite destroys provenance. | Accepted, partially implemented |
| [0008](adr/0008-provider-neutral-inference-boundary.md) Provider-neutral inference | Services depend on neutral text/vision/embedding contracts; an adapter is chosen per role; model loading, residency, and KV placement are deliberately outside the adapter. | "Sending a request should not grant code authority to unload models or alter GPU residency"; OpenAI-compatible syntax does not prove semantic compatibility, so promotion needs real acceptance. | Accepted, verified |
| [0009](adr/0009-vllm-default-local-inference-runtime.md) vLLM as the runtime | Pinned vLLM services by image digest and model revision; GPU-safe startup order; "send a JSON Schema on every request whose reply is parsed as data". | Reproducible by pinned artifacts rather than a GUI profile; FP8 accepted on measured behaviour, "not a free win". | Accepted; its single-RTX-5080 role profile is historical since the Spark move (below) |
| [0010](adr/0010-invite-identity-and-revocable-sessions.md) Invite identity | An immutable `user_id` owns data; the login name is separate and changeable; Argon2id passwords; opaque session tokens stored only as digests; no public sign-up, no destructive delete command. | The browser must never select the owner; a renamed login must not orphan data. | Accepted, implemented |
| [0011](adr/0011-sharing-by-copy-on-accept.md) Sharing by copy | Sharing "copies on accept. It never grants access into someone else's store"; the copy is a snapshot with provenance. | The single-owner invariant is load-bearing in 133 query sites, 33 of them in deletion and export; a grant table means each site missed is a disclosure or an invisible omission. | Accepted, not yet implemented |
| [0012](adr/0012-the-graph-answers-the-turn-it-does-not-run-it.md) The graph answers the turn | The reply is a nine-node LangGraph (`plan_context -> recall -> retrieve -> memory_write -> compose_context -> measure -> enforce? -> assemble -> generate`); the turn itself stays an async generator; persistence stays at its call sites. | Three executed probes: a downstream node does not run once the streaming consumer disconnects, subgraph events vanish, and double writes raise. "The turn IS the graph" designs scored 3.2-4.5/10. | Accepted 2026-08-23, implemented |
| [0013](adr/0013-multimodal-brief-detail.md) Capability registry (brief) | Proposes nodes declaring capabilities and a registry resolving the model; "fall back on reachability, never on quality". | The real failure mode is capability mismatch, never price; per-node model binding meant six edits to move six roles. | Not yet decided |
| [0014](adr/0014-embedding-upgrade-brief-detail.md) Embedding models | Keep the nomic text+vision pair; every vector carries a model+scheme signature and one backfill rebuilds a space; the migration target at the next hardware step is the Qwen3-VL-Embedding + Reranker pair (unified text/image/video, Matryoshka output keeps 768 columns); four mandatory acceptance criteria before any swap. | At ~500 vectors, threshold calibration dominates encoder quality; the alignment trap: "replace the text model alone and nothing raises" - image search becomes noise presented as an answer. | Accepted 2026-08-25 (brief promoted; see below) |
| [0015](adr/0015-deepseek-on-two-sparks-text-roles-consolidated.md) DeepSeek on two Sparks | Every text role on one DeepSeek-V4-Flash deployment, tensor-parallel across spark1 and spark2; vision separate on spark2; the application on spark1; memory headroom as a safety margin; image generation off the Sparks. | A second resident text model costs memory the margin cannot spare, and grammar-constrained decoding removed the structured-output defect that had kept routing on Qwen; over-allocation hangs a node with no remote console. | Accepted 2026-08-23, verified |

There is no `adr/README.md`; this table is the index. The two files numbered
0012 are one decision and its evidence appendix (`0012-plan-detail.md`).

## Decisions made while running it

Dated, newest first within each theme. Each one cost something real.

### Inference and hardware

The serving-level decisions - quantisation, KV cache dtype and pool,
utilisation, speculative decoding, caches, thresholds, decoding policy - are
catalogued with their measurements in [ML_SYSTEM_DESIGN.md](ML_SYSTEM_DESIGN.md);
the bullets here are the architectural consequences.

- **DeepSeek-V4-Flash answers everything textual, on two Sparks (2026-08-14 to
  08-23).** It won a blind six-prompt read-off against Qwen and Nemotron and
  then a measured comparison (`MODEL_EVALUATION.md`, "DeepSeek stays"). It is
  served by vLLM tensor-parallel across spark1 and spark2 with a 1M-token
  context and an NVFP4 KV cache. With the Sparks in place every text role -
  routing, conversation, structured output, diagrams, decks, memory
  classification - moved onto it, and the single-RTX-5080 Qwen 4B profile was
  retired. Vision stays a separate model (Qwen3-VL-8B on spark2) because the
  DeepSeek build cannot read pixels.
- **Memory headroom is a safety margin, not an optimisation.** Over-allocating
  GPU memory hangs a Spark, and a Spark has no remote console - recovery is a
  physical button. Utilisation is pinned at the measured safe value on spark2
  (0.81), `--kv-cache-memory-bytes` is banned after it silently capped the KV
  cache through four restarts, and every new GPU tenant (the reranker, for
  example) is sized against the free number rather than the total.
- **Image work lives on the desktop, and is honestly unavailable when the
  desktop is off (2026-08-25).** FLUX.2 Klein needs 14-18 GB neither Spark has
  spare while DeepSeek holds both. The desktop's 16 GB card runs ComfyUI as
  its only tenant; the assistant's answer when it is unreachable is "the
  machine that runs image generation is off - try again later", never "start
  it". The 9B was chosen over the 4B knowingly (gated, non-commercial
  licence); the FLUX.1 Kontext editor stays selected for edits because the 4B
  measured unable to add anything to a picture; a GGUF quantisation is a
  file-name change, not a code change.
- **Embedding models stay; the migration target is named (2026-08-25).** Text
  and image vectors share one aligned 768-d space, so the text encoder cannot
  move alone (ADR 0014's trap). Every stored vector carries a model+scheme
  signature, retrieval filters on it, and one idempotent backfill rebuilds a
  space - so a future swap degrades to "not yet rebuilt", never to wrong
  answers. The designated target at the next hardware step is the
  Qwen3-VL-Embedding + Qwen3-VL-Reranker pair (one family, one unified
  text/image/video space, Matryoshka output that keeps the 768-wide columns).
- **A reranker, fail-soft, as the second opinion (2026-08-25).** A bi-encoder
  compares two vectors that never met; a cross-encoder reads query and
  candidate together. Qwen3-Reranker-0.6B serves on spark1; history recall
  fetches the top 40 by vector and lets the reranker cut them to 12; any
  failure keeps the cosine order. The same swap was *measured* for Scout's
  shortlist and rejected (attribution 0.25 against the local cross-encoder's
  0.50), so Scout keeps its in-process MiniLM. The stage was also found wired
  into the test container only, for a day - fail-soft had hidden that the live
  backend never had it; the lesson is recorded beside the fix.

### Memory and recall

- **Recall anything, at any time (2026-08-24).** Passive recall (the three most
  similar past remarks) could not reach a detail that was never fact-shaped
  and did not resemble the current wording; the operator's bar was "I should
  be able to recall anything at any point in time". So the model can *search
  its own transcript store* on demand (`search_history`), the way it can
  search the web: every exchange is embedded with both voices, indexed by
  HNSW, gated by cosine distance, time-bounded by dates the model states in
  its tool call (never parsed from prose), excerpted with truncation markers,
  and reranked. Misses log the nearest rejected distance so the thresholds
  become measured rather than assumed. Multi-round search is deliberately
  deferred until that telemetry argues for it.
- **Hard caps are documented by what they affect, and enforcement stays off
  until there is traffic to measure (2026-08-24).** The context budget
  (32,768 tokens across prioritised sections, cache-aware ordering) is
  observed rather than enforced, because with almost no real traffic yet the
  measurements would be about the tests, not the users.
- **Memory saves automatically, and the classifier is the whole defence
  (documented; tightened 2026-08-21 and 08-24).** There is no approval step.
  The classifier sees one message with no history, so its prompt carries the
  principles that keep it honest: an interest is a pursuit enjoyed for its
  own sake, not the work at hand; a statement about how the assistant or any
  system under discussion works is the work at hand; a fact is what the user
  states about themself, and another person's fact stays theirs. Each of
  those sentences was earned by a real over-capture, reproduced at
  temperature 0, fixed once, and pinned by a functional test.
- **A tool's description is written by subject shape, never by adding the
  failing phrasing (2026-08-24/25).** Adding optional fields to a tool schema
  measurably moved the router's decision boundary; the fix was a principle
  ("a short follow-up that continues work in view is part of that work, not a
  reference to the past"), and every schema touch re-runs the behaviour suite.

### Identity, data, and safety

- **A phone number is an identity to the bridge, so it belongs to one account
  (2026-08-24).** Sign-up collects it in E.164, refuses a number already
  claimed, and approval does two things that used to be done by hand and
  drifted: enrol the number as a subscriber in AniOS and allowlist it on the
  Mac, in one decision. A subscriber is not a user - it is "a revocable
  permission to send one person one kind of message". Approved people get an
  introduction generated from the same capability list the router offers.
- **Digests are keyed (2026-08-25).** The lookup digest for numbers and
  addresses was a plain SHA-256 over a ~10^10 keyspace, exhaustible offline
  from a dump; it is now an HMAC keyed from the sealing key, moved in all four
  consumers at once with an idempotent rekey, and a source-inspection test
  forbids the unkeyed path returning.
- **Three backup copies and a restore that has actually been run
  (2026-08-23/25).** Nightly dumps, mirrored to spark2 and to the Mac
  (ciphertext only; the key is escrowed elsewhere), thirty-day retention,
  Redis append-only, and a restore proven end to end including decrypting
  values out of the restored copy. The first three-way run mirrored to nobody
  because the `.env` parser stripped the spaces between hosts - fixed the
  same night. Point-in-time recovery is a recorded gap.
- **Databases listen on loopback; containers use compose-network names
  (2026-08-25).** Applying the loopback binding broke every new container
  connection for an hour while health stayed green, because services dialled
  the host's LAN address; the fix was addressing by service name, and the
  trap is recorded so nobody regresses to host addressing.
- **One egress screen, applied centrally.** A tool argument sent to a
  third-party MCP server carries the same disclosure risk as a search query,
  and "a second implementation is how the first gets bypassed" - so the
  screening policy lives in `core/egress` and a boundary test fails on a
  duplicate.

### Channels, agents, and tools

- **The iMessage bridge became conversational (2026-08-24).** The Mac reads
  incoming texts only from allowlisted senders (the send allowlist is reused
  as the conversation allowlist, by the operator's choice), matches a sender
  to an account by keyed digest, runs the full pipeline, and replies pinned
  to the message it answers. Images travel both ways through a spool. Polling
  is adaptive (3 s idle, 1.5 s while a conversation is active), which took a
  reply from ~6 s to ~1.5 s. What is said to the assistant leaves the Mac;
  what anyone else has said never does.
- **Scheduled tasks reuse the queue that already survived production.**
  Scout's run queue (leases, exactly-once slots, heartbeats, retry with a
  deadline) and cadence math are generic; tasks got a sibling queue rather
  than a second invention, and channels are adapters so WhatsApp or a future
  channel needs nothing new from the scheduler (`TASKS_ARCHITECTURE.md`).
- **Scout qualifies deterministically and lets the model order.** What
  qualifies as a find is code; which qualified find comes first, and how it
  reads, is the model's. Every Scout model call is greedy because "an
  unattended weekly job that sampled differently each run could not be
  compared against itself"; its ranking is judged by a labelled harness with
  floors, never by eye.
- **More integrations are coming, and quality is as important as speed
  (operator direction, 2026-08-24).** Each new MCP integration gets its own
  labelled routing floor so new tools do not dilute selection precision, and
  functional coverage of the real provider contract before it is advertised.
- **Diagrams render on any machine (2026-08-25).** The browser is deliberately
  not part of the render fingerprint, so a host Playwright refuses to
  provision can point the pinned renderer at an installed Chrome and produce
  the identical checked suite.

## Where the decisions still open are recorded

- `NEXT_SESSION.md` carries the current handoff: what is verified, what is
  deferred, and the operational traps (each one cost real time or data).
- `ROADMAP.md` carries milestone status; `SECURITY.md` separates current
  controls from `PLANNED` ones; `MODEL_EVALUATION.md` carries the numbers
  behind every model choice.

---

# Part III - Implementation reference

Everything from here down is the engineering reference, section by section:
exact boundaries, settings, thresholds, and the measurements behind them. It
assumes Parts I and II. Sections that describe the single-RTX-5080 profile
the system ran on until 2026-08-23 are marked historical where they appear.

## Status labels

- `SCAFFOLDED`: structure exists, but complete behavior is not implemented or demonstrated.
- `MOCKED`: a placeholder or fixed implementation supplies the behavior.
- `PLANNED`: the capability is future work.

The absence of one of these labels does not imply runtime verification.

## Canonical system diagram

![AniOS current system architecture](diagrams/anios-system.svg)

The editable source is [anios-system.mmd](diagrams/anios-system.mmd). It describes current implemented and explicitly scaffolded relationships only, including the typed main-supervisor route, editable diagrams, generated and uploaded raster artifacts, local binary storage, Compose-managed vLLM inference, ComfyUI, Qwen vision analysis, their browser integration, and the durable presentation worker. Aligned multimodal image embeddings and hybrid opt-in web research are included. General dynamic agent teams, A2A, and GPU-capacity leases remain outside the current diagram until their runtime boundaries exist. The render/check procedure is documented in [DEVELOPMENT_GUIDE.md](DEVELOPMENT_GUIDE.md#architecture-diagram-maintenance).

The self-contained [manager-facing architecture page](architecture.html) publishes all 22 canonical views — eighteen subsystem views plus one per agent — with a current model-role summary, direct full-size SVG and Mermaid-source links, and independent per-diagram zoom controls. Twenty views describe the current system; the separately labelled visual-memory/editing and inference-scaling targets describe accepted future designs without claiming implementation. Its opening orchestration contract states explicitly that `MainActionSelector` decides every turn's action with one native tool call made by the routing model, not a regex or a narrow bounded classifier.

## Detailed subsystem diagrams

AniOS currently has a modular FastAPI backend rather than independently deployed internal microservices. These concise orientation views show ownership, major components, and primary flows; exact endpoints, schemas, and exception paths remain in this document and the code. The [diagram catalog](diagrams/README.md) explains which view answers each common technical question.

| Current view | Technical scope | Source | SVG |
| --- | --- | --- | --- |
| Runtime and deployment | Processes, ports, protocols, Compose, vLLM, database sessions, migration and maintenance paths | [source](diagrams/runtime-deployment.mmd) | [view](diagrams/runtime-deployment.svg) |
| Inference scaling target | Implemented role/adapter authority plus planned capacity placement, replicated vLLM pools, specialist pools, serving control plane, and model SLOs | [source](diagrams/inference-scaling-target.mmd) | [view](diagrams/inference-scaling-target.svg) |
| Chat orchestration | Request ownership, typed supervisor delegation, semantic artifact-recall gating, owner-scoped referent resolution for unselected image edits, memory planning, history, LangGraph streaming, persistence, proposals, artifact branch, SSE | [source](diagrams/chat-orchestration.mmd) | [view](diagrams/chat-orchestration.svg) |
| Search and research | Query minimization, cloud-worker isolation, Google/Tavily provider policy, quota, MCP serialization, and source provenance | [source](diagrams/search-research-subsystem.mmd) | [view](diagrams/search-research-subsystem.svg) |
| Memory subsystem | All short/long-term forms, write authority, coordinator, typed services, pgvector retrieval, lifecycle and operations | [source](diagrams/memory-subsystem.mmd) | [view](diagrams/memory-subsystem.svg) |
| Memory overview (manager) | Plain-language first-contact walkthrough of a memory turn, auto-save with no approval step, short-term vs long-term stores, and user data control | [source](diagrams/memory-overview.mmd) | [view](diagrams/memory-overview.svg) |
| Scout discovery | Approved home/interest facts, profile projection, travel locality, strength-weighted ranking, familiarity controls, durable sweeps, and outputs | [source](diagrams/discovery-subsystem.mmd) | [view](diagrams/discovery-subsystem.svg) |
| Tool memory and MCP execution | Safe descriptors, approved preferences, sanitized outcomes, semantic tool discovery, main-model selection, policy-gated invocation, and bounded untrusted results | [source](diagrams/tool-memory-subsystem.mmd) | [view](diagrams/tool-memory-subsystem.svg) |
| Visual artifacts | Diagram classification/rendering, FLUX generation and editing, validated uploads, opaque binary storage, integrity/deletion, Qwen vision analysis, threaded followup questions, aligned image embeddings and margin-bounded retrieval | [source](diagrams/visual-artifact-subsystem.mmd) | [view](diagrams/visual-artifact-subsystem.svg) |
| Visual memory and editing | Implemented source-aware immutable revisions and owner-scoped semantic resolution for unselected image edits, plus planned non-blocking generated-image observation, broader artifact sources, post-edit verification, and derived-data lifecycle | [source](diagrams/visual-memory-editing-target.mmd) | [view](diagrams/visual-memory-editing-target.svg) |
| Architecture maintenance | Explicit repository evidence, local Qwen candidate generation, passive/required-label validation, pinned rendering, review, and manual canonical promotion | [source](diagrams/architecture-maintenance-subsystem.mmd) | [view](diagrams/architecture-maintenance-subsystem.svg) |
| Frontend | Identity/conversation state, view lifecycle, chat components, memory management, typed API/SSE client, diagram rendering | [source](diagrams/frontend-subsystem.mmd) | [view](diagrams/frontend-subsystem.svg) |

## Runtime topology

Everything below runs on spark1 under `docker-compose.yml` unless a row says
otherwise. Container-to-container traffic uses compose-network service names;
the two data stores are published on the host's loopback only.

| Service | Implementation | Reachable at | Role |
| --- | --- | --- | --- |
| `backend` | FastAPI/Uvicorn image from the root `Dockerfile` | behind `gateway` | HTTP API, SSE streaming, the iMessage chat worker's pipeline |
| `gateway` | Nginx | host `8080`; public via `cloudflared` | Serves the compiled React app and proxies `/api` on one origin (the only public surface) |
| `cloudflared` | Cloudflare tunnel | - | `deep-matter.com` -> `gateway`; no inbound port is opened on the LAN |
| `frontend` | Vite dev server | host `5173` | Development console only |
| `discovery-worker` | Backend image, worker command | - | Scout sweeps, scheduled tasks, the iMessage polling loop |
| `presentation-worker` / `presentation-renderer` | Backend image / Node PptxGenJS + LibreOffice | `8002` (renderer) | Durable deck jobs and their validated rendering |
| `local-capabilities` | Backend image, FastMCP | `8001` | The local visual/presentation tool facade offered to the model |
| `memory-maintenance` / `storage-collection` | Backend image, timers | - | Retention, stale-vector refresh, unreferenced-byte collection |
| `db` | `pgvector/pgvector:pg16` | `127.0.0.1:5432` | PostgreSQL: every conversation, memory, artifact record, job, and account; pgvector HNSW indexes |
| `redis` | `redis:7-alpine`, append-only | `127.0.0.1:6379` | Model-execution lease, login attempt windows, the iMessage cursor; never prompt or response text |
| `vllm-embedding` | Pinned vLLM, `nomic-embed-text-v1.5` | host `8004` | 768-d text embeddings |
| `vllm-reranker` | Pinned vLLM, `Qwen3-Reranker-0.6B` | host `8006` | `/v2/rerank` cross-encoder scoring for history recall |
| `ds4-head` (systemd, not compose) | vLLM, DeepSeek-V4-Flash, tensor-parallel rank 0 | host `8000` | Every text role; rank 1 is `ds4-worker` on spark2 |
| `anios-vlm` (systemd on **spark2**) | vLLM, Qwen3-VL-8B | spark2 `8001` | Vision |
| ComfyUI (Docker on the **desktop**) | `docker/comfyui/`, host ComfyUI bind-mounted | desktop `8188` | FLUX.2 Klein generation and editing; only while the desktop is on |
| iMessage bridge (**Mac**) | `bridges/imessage_mac`, MCP over HTTP | Mac | `allow_recipient`, `send_imessage`, `read_messages`; the only process that touches Messages |
| image embeddings | `nomic-embed-vision-v1.5` ONNX | in-process, CPU | Aligned 768-d image vectors |
| web research | Built-in stdio MCP server; isolated Gemini/Google worker, Tavily fallback | external | Opt-in; the one outbound boundary |
| `comfyui` / `functional-tests` | Compose profiles | - | Opt-in: a Spark-hosted ComfyUI (not used today), and the deploy gate's test container |

The backend image bakes its source and its migrations, so a code change needs
an image rebuild and `up -d`, and a new migration needs a rebuild before
`alembic upgrade head` can see it; the gate's test container bind-mounts the
working tree instead, which is why it can run unmerged code. After any compose
environment change, compare `docker ps` uptimes against the deploy time - a
plain `up -d` has been seen to leave services running with stale env.

**Historical profile, kept for the measurements.** Until 2026-08-23 the whole
stack ran on one Windows desktop with an RTX 5080: `vllm-main` served
`Qwen/Qwen3.5-4B` in FP8 at `8003` for every model role, with a 16,384-token
context, four sequences, chunked prefill, and prefix caching, beside
`vllm-embedding` at `8004` and host ComfyUI. FP8 halved resident weights
(8.61 -> 5.09 GiB) and lifted free GPU memory with both services resident
from 1,860 to 6,588 MiB; Compose started Qwen to health before Nomic because
concurrent cold initialisation left no KV-cache blocks. That profile is
retired; its serving lessons live on in `MODEL_EVALUATION.md` and
`DGX_MIGRATION.md`. Generated and uploaded bytes still live below the opaque
local artifact root, mounted from the `artifactdata` volume.

### Model calls per stage

A request is not one model call. Several models run at different stages, and
the text roles all share the one DeepSeek deployment, so calls serialize - a
turn's latency is dominated by how many model calls it makes, not by any single
one. Memory retrieval planning remains deterministic.

A chat turn, in order:

| Stage | Model | Runs on | When |
| --- | --- | --- | --- |
| Main supervisor route | `deepseek-v4-flash` (`ROUTING_LLM_MODEL`), native tool calling at temperature 0 | Sparks (`ds4-head`) | every chat turn before retrieval; selects one built-in/MCP action or an ordinary reply |
| Query embedding | `text-embedding-nomic-embed-text-v1.5` (`EMBEDDING_MODEL`) | spark1 (`vllm-embedding`) | when personal semantic or agent-vector retrieval is selected; one vector is reused across stores and image recall |
| Memory retrieval planning | none (deterministic) | CPU | every turn |
| History search (`search_history`) | the embedder, then `qwen3-reranker-0.6b` (`RERANKER_MODEL`) | spark1 (`vllm-embedding`, `vllm-reranker`) | only when the router chose it: top 40 exchanges by vector, reranked to 12, filtered against the visible window; fail-soft to cosine order |
| Artifact modality gate / artifact-recall routing | `deepseek-v4-flash` structured decision | Sparks | once on an unselected turn, before any private pixel-vector or description-vector lookup |
| Tool selection | the same native tool decision as the route | Sparks | every turn, with live MCP candidates included only when semantically shortlisted |
| Response generation | `deepseek-v4-flash` (`MAIN_LLM_MODEL`), streamed | Sparks | ordinary non-delegated turns |
| Typed memory proposal | `deepseek-v4-flash` (`MEMORY_PROPOSAL_LLM_MODEL`), grammar-constrained JSON, temperature 0 | Sparks | every ordinary chat turn; auto-saves what it classifies, with no write authority beyond the typed fields |

A plain message ("my name is Ani") therefore makes about three model calls: one
text embedding plus two main-role calls (the turn's action selection and the
response).

One Scout sweep, in order. This is the densest model path in the system, and
every stage degrades to the one before it rather than failing the sweep:

| Stage | Model | Runs on | When |
| --- | --- | --- | --- |
| Query and vector aiming | `deepseek-v4-flash` (`MAIN_LLM_MODEL`), grammar-constrained, greedy | Sparks | once per sweep; describes each interest so it is more than a two-word string |
| Candidate and interest embedding | `text-embedding-nomic-embed-text-v1.5` (`EMBEDDING_MODEL`) | spark1 (`vllm-embedding`) | one batch per sweep, feeding novelty, familiarity, and recall ranking |
| Precision ranking and attribution | `ms-marco-MiniLM-L6-v2` cross-encoder, ONNX (`DISCOVERY_RERANKER_SOURCE=local`; the served Qwen3 reranker is selectable and measured worse) | CPU, in-process | one forward pass per (interest, candidate) pair over the shortlist; absent weights disable it |
| Shortlist ordering against memory | `deepseek-v4-flash` (`MAIN_LLM_MODEL`), grammar-constrained, greedy | Sparks | once per sweep, and only when approved facts exist |
| Find naming and description | `deepseek-v4-flash` (`MAIN_LLM_MODEL`), grammar-constrained, greedy | Sparks | once per selected find, after selection rather than per candidate |

So a sweep costs about two main-role calls plus one per delivered find, one
embedding batch, and a few hundred CPU cross-encoder passes. Everything is
greedy: an unattended weekly job that sampled differently each run could not be
compared against itself.

Scout also completes a place name while it is being typed - the main model,
grammar-constrained, debounced at 350 ms rather than per keystroke - which is
interactive rather than part of a sweep.

Image and presentation paths:

| Stage | Model | Runs on |
| --- | --- | --- |
| Image generation / slide image | `flux-2-klein-9b-fp8.safetensors` (`IMAGE_MODEL`) via ComfyUI | desktop RTX 5080, only while it is on |
| Image editing by instruction | FLUX.1 Kontext (`IMAGE_EDIT_MODEL`, GGUF) via ComfyUI; Klein when that is unset | desktop |
| Refinement prompt merge, learned-style distillation | `deepseek-v4-flash` (`MAIN_LLM_MODEL`) | Sparks |
| Image vision analysis (ask) | `qwen3-vl-8b` (`VISION_MODEL`) | spark2 (`anios-vlm`) |
| Image vision escalation | optional `VISION_ESCALATION_MODEL`, currently unset | configured OpenAI-compatible endpoint |
| Image embedding (index and reconciler) | `nomic-embed-vision-v1.5` ONNX | spark1, CPU |
| Deck outline, one slide-content microtask per slide, or slide revision | `deepseek-v4-flash` (`PRESENTATION_LLM_MODEL`) | Sparks |
| Diagram generation | `deepseek-v4-flash` (`DIAGRAM_LLM_MODEL`) | Sparks |
| Architecture candidates | legacy `LLM_MODEL` (DeepSeek) unless its CLI environment is overridden | Sparks |
| Google-grounded research, when enabled | `gemini-3.6-flash` (`GOOGLE_SEARCH_MODEL`) | external Google API |

Web research, only when routing decides to search, calls Google Gemini grounding
or Tavily - external/cloud, never local hardware. Role names are independently
configurable. Redis prioritizes chat over presentation microtasks; it does not
provide multi-model capacity accounting, and nothing here moves a model between
hosts at request time - over-allocating a Spark hangs it.

### Aligned image embeddings and web search

Images are embedded locally by `nomic-embed-vision-v1.5`, run in-process through
ONNX Runtime on CPU from `data/models/` (weights are not committed; see the
development guide). The encoder is aligned to the latent space of
`nomic-embed-text-v1.5`, so image vectors share the same 768 dimensions as text
memory and a text query embedded by the ordinary text embedder retrieves images
directly.

Alignment gives comparable *ordering*, not comparable *magnitude*. Measured on
this system, a matching text-to-text pair scores about `0.73` cosine similarity
while a matching text-to-image pair scores about `0.08` - the modality gap. Image
vectors therefore live in their own `visual_artifacts.embedding` column with
their own HNSW index and their own bounds; they are never ranked in one list
against text memory by raw distance, because every unrelated text memory would
outrank every matching image. Generated and uploaded images are embedded once at
store time; a followup question does not re-embed, because the pixels have not
changed. Diagrams hold Mermaid source rather than pixels and are excluded.

Two retrieval paths reach stored images. Vision analysis text is embedded into
`semantic_memory` under the dedicated `visual_artifact_analysis` purpose, which
keeps derived model output separate from the approval-gated path that persists
user-stated facts; that makes an image findable by what was said about it. The
aligned image vector makes it findable by what it actually depicts, including
detail no caption mentioned. Generated images have no analysis text, so the
vector is their only index.

In chat, one structured `ArtifactContextRouter` decides which of the user's
owned artifact modalities, if any, the answer actually depends on. It currently
offers only the implemented image source, while its contract already admits
document, audio, and video sources. Schedules, reminders, settings, general
knowledge, and requests to create a new artifact stop before embeddings or any
private artifact candidates are loaded. For an image-bearing request, the same
decision admits an aligned pixel-vector lookup followed, when needed, by the
semantic-description index; `VisualMemorySelector` chooses only offered IDs
from the latter. The retired regex-plus-classifier image-recall route is no
longer part of the live path. Matches stream as an `image_matches` SSE event
before the answer, and enter the prompt as untrusted quoted data telling the
model the images are already displayed. Uploaded originals and their edited
descendants collapse to the latest selected revision before rendering.

`ImageRetrievalPolicy` decides which ranked hits are real matches, and it needs
two bounds because a distance ceiling alone is provably insufficient. Measured
over an 18-query labelled set against eight generated images, relevant queries
placed the correct image first every time at distances of `0.9090`-`0.9419`,
while unrelated queries returned their nearest image at `0.9518`-`0.9699`. Those
bands look separable, but a genuine weak match measured `0.9531` on other data,
inside the distractor range: no absolute cutoff separates them.

The discriminating signal is the margin between the best hit and the runner up.
A real match pulls clearly ahead (`0.0211` minimum observed) while an unrelated
query leaves every image roughly equidistant (`0.0107` maximum, and exactly
`0.0000` for one query). The policy therefore applies
`VISION_SEARCH_MAX_COSINE_DISTANCE` (`0.96`) as a coarse ceiling and
`VISION_SEARCH_MIN_MARGIN` (`0.015`) as the discriminator. With both bounds the
labelled set scores 14/14 correct top-1 results and 4/4 distractors correctly
returning nothing; with the ceiling alone every distractor produced a false
positive.

Candidates must be fetched **without** a distance pre-filter
(`ImageRetrievalPolicy.CANDIDATE_CEILING`). Filtering in SQL first can discard
the runner up, which leaves a single row that looks like a lone result and
silently bypasses the margin check; that regression is covered by a test.

Because these bounds are calibrated rather than derived, they should be
re-measured as a library grows: more images shrink inter-image margins.

Web research is reached through the built-in read-only
`internet/search_web` stdio MCP server when `SEARCH_PROVIDER_NAME=mcp`; the
legacy direct Tavily adapter remains configurable. `HybridSearchProvider`
prefers an isolated Google ADK worker when `GOOGLE_API_KEY` or
`GEMINI_API_KEY` is configured, falls back to Tavily when Google is disabled,
empty, unavailable, or over its local daily budget, and calls both providers
only when the user explicitly asks to verify or cross-check. `MainActionSelector` offers the live `search_web` schema to the main model as
one native tool alongside every other candidate action (a new or edited
picture, a diagram, a specialist handoff, the user's own registered MCP
tools); the model decides whether to call it and writes the query itself, in
the same call that decides everything else about the turn. The `SearchRoutingPolicy`/`CascadingSearchRouter` regex-plus-classifier
cascade that used to make this call has been deleted; its labelled set
(`backend/search/routing_cases.py`) outlived it and now holds the tool
selector to the same recall and specificity floor. Neither the local model nor
the cloud worker owns outbound eligibility beyond that one decision.

The Google worker is a request-scoped `gemini-3.6-flash` ADK `Agent` with the
native `google_search` tool. Each call creates a random in-memory session,
disables prior contents, and sends only the already normalized and
privacy-screened public query under a constant anonymous worker identity. It
receives no AniOS user/conversation ID, history, personal memory, documents,
image bytes, MCP credentials, or execution authority. AniOS rejects a response
without grounding metadata and attributable web sources so fallback can run.
This is one specialized research agent behind the existing provider contract,
not general LangGraph subagent scheduling or A2A.

`SQLiteDailySearchQuota` reserves Google calls atomically across short-lived
stdio processes. It persists only provider, Pacific calendar day, and count in
the `searchdata` volume; it does not store query or result content. The default
local limit is 450 calls/day. This is a safety ceiling, not proof of provider
quota or free access. Current Gemini 3 Search Grounding availability depends on
the Google API project's plan and billing state; AniOS never enables billing or
switches tiers automatically. The unpaid Gemini service may use submitted
prompts and responses to improve Google products, so the existing minimization
boundary is mandatory and sensitive/private content must not be sent.

The semantic artifact gate also distinguishes historical visual references from
new artifact creation without a trigger-word list. Generated-image metadata
retains a bounded generation prompt, so a later chat turn can answer what was
requested without pretending to inspect absent pixels. Search results and image
descriptions both enter the final main-model prompt as untrusted quoted data.

When the user explicitly requests web search about a matched image, image recall
runs first. AniOS appends at most one bounded stored analysis or generation
prompt to the normalized search subject, screens the combined text with
`OutboundPrivacyPolicy`, and only then calls the internet MCP tool. Image bytes
never cross the outbound-search boundary. A blocked description blocks the
whole provider call rather than falling back to the less useful raw question.

Web-search routing is one branch of the turn's single action decision, not a
stage of its own. The model that reads the conversation decides whether the
answer needs live data and writes the query itself, in the same call that
decides everything else about the turn.

It replaced a cascade: deterministic patterns answering the obvious cases for
free, with a bounded local classifier judging whatever they missed. Both have
been deleted, and what they measured is worth keeping. Against FreshQA, which
labels 600 questions fast-changing, slow-changing or never-changing, patterns
alone recalled 45.6% of questions whose answers move, because volatility is
rarely phrased explicitly - "When did OpenAI release GPT-5?" needs live data
and contains no temporal marker. The cascade raised recall to 86.9% and
accuracy from 62.3% to 81.7%, at the cost of specificity falling to 69.4%.
Smaller classifiers could not do the job at all: against an "always search"
baseline scoring 70.0% by ignoring the question entirely, qwen3-1.7b also
scored 70.0% and qwen3-0.6b 70.8%, both effectively constant-YES answers.

The ceiling was structural rather than a matter of better patterns. A bare
temporal word attaches equally to an information need ("what shipped last
month") and to a statement about the user's own life ("I graduated last
month"); the difference is intent, not vocabulary, and neither a pattern nor a
one-word verdict on the question alone can see it, because the thing that
separates them is the conversation around it. The cascade's own escape hatch
admitted this - a first-person sentence with only a weak signal abstained and
deferred - which is the decision the turn's model now makes with the
conversation in front of it. Its recall and specificity are held to the floor
the cascade reached, over the same labelled set
(`backend/search/routing_cases.py`), by a functional test that runs the real
model.


Search-control wording such as "search online for" and "cite the source" is
removed before provider submission so the selected provider receives the factual subject.
Every query is then screened by `OutboundPrivacyPolicy` before it leaves the machine,
which the roadmap requires and the first implementation omitted: the raw user
query was sent verbatim. Two outcomes exist. A query carrying a secret or an
account identifier is blocked outright and no request is made, because no
rewrite makes an API key, email address or card number safe to send. A query
that merely attaches a sensitive topic to the user is minimized instead: "what
should I do about my psoriasis flare-up" is sent as "psoriasis flare-up",
because the search value lives in the topic rather than in whose topic it is.
Screening is deterministic and runs outside the model, since a model asked to
redact its own prompt can be argued out of it. Only the category and trace ID
are logged, never the text that triggered them, and the interface reports both
outcomes so a withheld or rewritten search is visible rather than silent.

Scored Tavily results are filtered by provider relevance before reaching the prompt.
Measured across 40 real results the score distribution is bimodal: usable hits
scored 0.561-0.923 and dictionary-definition noise scored 0.046-0.346, with an
empty band between, so `SEARCH_MIN_SCORE` sits at `0.4`. Admitting that noise
would be worse than returning nothing, because the prompt instructs the model to
prefer web results over its own recollection for time-sensitive facts.

A searching turn is visible and auditable. `search_started` and
`tool_started` are emitted before an MCP-backed provider call,
the provider call rather than after it, since search is the slowest step, and
`search_results` always follows with the sources consulted - including an empty
list on failure, so the interface retracts its indicator instead of spinning.
The browser renders search and tool lifecycle status, then provider-attributed
cited sources beneath the answer, so a reader can check what grounded it.

### Visual semantics, memory references, and source-aware editing

This subsection and
[visual-memory-editing-target](diagrams/visual-memory-editing-target.svg)
describe a staged architecture. Source-aware editing is implemented and
verified; automatic generated-image observation, visual aliases/reference
resolution, semantic post-edit verification, bounded correction, and derived
data lifecycle remain `PLANNED`.
[ADR 0007](adr/0007-versioned-visual-semantics-memory-and-editing.md) owns the
decision.

The target pipeline does not make generated-image availability wait for a VLM.
After the current generation boundary validates, stores, and displays the
pixels, an application-owned durable observation job reads the exact owned
bytes through the existing integrity boundary. A replaceable
`VisionSemanticsProvider` returns a typed, bounded `VisualObservation` containing
caption, objects, attributes, relationships, OCR, confidence, model, schema,
source hash, and provenance. Observations are append-only and versioned by
artifact revision, plaintext SHA-256, schema, and model; a failed observation
does not invalidate a ready image.

Visual memory stores no duplicate image bytes. It stores user aliases,
collections, derived semantic vectors, and immutable artifact/revision handles.
`VisualReferenceResolver` will fuse exact aliases, semantic-description search,
the existing aligned pixel-vector search, conversation, recency, and lineage
state. Each signal retains its own calibrated scale. A minimum score and
best-to-runner-up margin are required; ambiguous matches produce a visible
clarification. Before any VLM, editor, agent, or MCP tool receives pixels, the
application resolves the handle and rechecks owner, ready status, deletion
state, byte size, and SHA-256.

Editing is a separate provider capability from understanding.
`ImageRefinementService` re-reads owned, integrity-checked generated or
uploaded source bytes,
adds bounded preservation constraints to the exact user feedback, and invokes
`ComfyUIImageEditProvider`. The provider runs the official-style FLUX.2 Klein
4B Distilled FP8 single-reference workflow through ComfyUI with a Qwen 3 4B
encoder, FLUX.2 VAE, four sampling steps, and one-job concurrency. Deterministic
image validation precedes an immutable ready child carrying its parent ID,
source SHA-256, exact feedback, model, seed, steps, and provider latency. The
frontend replaces the active card in place while retaining both database
revisions. Prompt-only HiDream regeneration and the experimental SAM recolor
branch are not fallbacks.

Semantic verification remains a separate planned promotion gate. It will
compare a candidate child with the requested delta and preservation constraints,
permit at most one bounded correction, or retain the parent with a visible
failure. A focused future `VisualAgent` may propose a typed edit plan, but
application code continues to own authorization, limits, provider selection,
resource leases, retries, storage, and promotion.

### Observability

Tracing is OpenTelemetry, off by default and safe to enable without a
collector: an unreachable OTLP endpoint drops spans in the background rather
than failing a request. `configure_telemetry` instruments FastAPI so each
request is a span, and httpx so every outbound call - vLLM, Tavily, an
HTTP MCP server - is an auto-propagated child span carrying W3C trace-context.
That is what turns "the turn was slow" into "the turn spent 1.4s in the Tavily
call", without guessing.

The custom `ConversationTracer` is retained and wrapped rather than replaced.
`OpenTelemetryConversationTracer` never opens or closes a span - the FastAPI
instrumentation owns span lifecycle, so it cannot leak one - and instead stamps
the application trace id onto the active request span and records each domain
step as a span event. Step metadata is stringified and bounded, so a trace
backend receives structure, never query, argument, or result text.

### Module boundaries

Packages are separated by what they own rather than by when they were written,
and the separation is enforced by tests rather than convention:

| Package | Owns |
| --- | --- |
| `backend/mcp` | The protocol: server configuration, stdio/streamable-HTTP sessions, built-in servers, tool metadata, and inspection of untrusted server text |
| `backend/capabilities` | Agent-facing application adapters, including the local visual FastMCP facade over existing services |
| `backend/search` | Web research only: direct/MCP provider adapters, isolated Google ADK worker, hybrid/fallback policy, non-content quota, query normalization, routing patterns, and the classifier cascade |
| `backend/artifacts` | Visual artifacts, lineage, storage, and margin-bounded image retrieval |
| `backend/core/egress` | Screening any text before it leaves the machine |
| `backend/services` | Orchestration that composes the layers above |

`backend/mcp` imports nothing from `backend/services` or `backend/api`, so the
transport can be replaced or exercised without the application around it.
The higher-level `backend/capabilities` package may compose application
services; this keeps the generic protocol package independent while allowing
local capabilities to use the same business logic as browser APIs.

Two placements are deliberate. Image retrieval sits with the artifacts it
serves rather than under `search`, while the modality decision belongs to the
memory agent that protects private artifact indexes. The screening
policy sits in `core/egress` because it governs every outbound request: a tool
argument sent to a third-party MCP server carries the same disclosure risk as a
search query, and a second implementation is how the first gets bypassed.
`test_architecture_boundaries.py` fails on a crossed boundary, a stray module
under `search`, or a duplicate screening policy.

### MCP tool discovery and chat invocation

Configured MCP servers are reached over one of two transports, chosen per
server. `stdio` launches the server as a local subprocess, which is how most
servers are distributed and how local development runs, but requires the
server's runtime to be present. `http` connects to an already-running service
over streamable HTTP, which is what a deployed sibling container or a remote
vendor exposes and needs no extra runtime in this image. The transport is
resolved in one place (`backend/mcp/session.py`); discovery and invocation never
learn which is in use, so adding Google Drive as an HTTP sibling changes
configuration, not code.

Their live catalogues are indexed
into `tool_descriptors`, so a large registry can be narrowed by meaning before
anything reaches the model. Published results make the reason concrete: naive
exposure of 100+ tools drops selection accuracy to roughly 13%, against about
43% when tools are retrieved, and beyond a few hundred tools selection
approaches random. Retrieval returns a handful (`TOOL_SEARCH_MAX_RESULTS`).

Tool descriptors need their own retrieval bound. A natural-language question
sits further from short structured tool text than memory text sits from memory
text: measured against a live catalogue, correct tools landed at 0.295-0.437
while unrelated questions sat at 0.477 and above, so the general memory
threshold of 0.35 silently discarded correct matches. Tool search therefore uses
`TOOL_SEARCH_MAX_COSINE_DISTANCE`, calibrated to 0.45. This is the third store
in the system to need its own bound, after personal memory and image vectors.

For an ordinary chat turn, `MCPToolOrchestrationService` searches that
user-scoped descriptor index, discards consequential servers, re-resolves each
candidate against the live catalogue, and exposes at most five current schemas
to the configured main model through vLLM's native OpenAI-compatible
`tool_calls` contract. The model may select at most one call and supply
schema-shaped arguments; it never
receives an invocation handle. AniOS converts the selected alias into an
application-owned plan and executes it only through the gates below.

Server metadata is untrusted. Three properties follow:

- **Trust is assigned locally.** `risk_classification` comes from the operator's
  configuration, never from the server describing itself.
- **The fingerprint covers the description, not only the schema.** A server that
  keeps its contract but rewrites its description can smuggle instructions to
  the model without changing anything a schema hash would notice - the rug-pull
  window that opens when a server is approved once and trusted afterwards.
- **Instruction-shaped descriptions are quarantined, not indexed.** A tool
  description exists to say what a tool does. One that says what the *model*
  should do is attempting tool poisoning, and indexing it would place that text
  in front of the model during discovery.

Discovery is not authorization. A descriptor narrows candidates; the call
itself passes through gates that treat storage as a hint and the live server as
the truth. Every invocation, in order:

1. Resolves the server from local configuration, never from the request.
2. Requires explicit confirmation unless the operator classified the server
   `trusted` or `read_only`. A wrong read is recoverable; a wrong write is not.
3. Re-reads the live catalogue and refuses a tool that is no longer offered, so
   a stale vector cannot authorize a call.
4. Compares the live fingerprint with the descriptor that was selected and
   refuses a changed contract.
5. Re-inspects the live description, because a server may have rewritten it
   since indexing.
6. Validates arguments against the declared schema. A wrong tool usually cannot
   accept the right tool's arguments, so this is the cheapest signal that
   similarity chose badly.
7. Screens every string argument through `OutboundPrivacyPolicy`, the same gate
   web search uses.

A transient transport failure is retried, but only for a call that can be
replayed without consequence. `MCPRetryPolicy` grants extra attempts solely to
`read_only` and `trusted` servers - the same classifications that skip
confirmation, because a call safe to make unconfirmed is safe to repeat - and
only on genuine transport errors (`ConnectionError`, `TimeoutError`, `OSError`).
A consequential server gets exactly one attempt: a dropped connection does not
prove the write never reached the server, so retrying it risks doing it twice.
A deterministic refusal - a gate rejection, a schema failure, a privacy block -
is never retried, because re-running it would fail identically. The gates above
still run once per call; retry wraps only the transport, never the policy.

Results are bounded and inspected. Instruction-shaped output is flagged and
rendered to the model as quoted, clearly attributed data with an explicit note
not to follow it. Verified against a live server: a valid call returns, while
unknown arguments, wrong types, a credential-bearing argument, a stale
fingerprint, a withdrawn tool and an unconfirmed consequential server are each
refused before any request reaches it.

The built-in `local_utility/current_time` server is the live acceptance fixture
for main-model-selected MCP use. The built-in `internet` server (`search_web` over an ordered provider chain - Brave first since 2026-08-25, held under its free credit by a local monthly counter, then Tavily, each rung answering until its period is spent; `get_weather`; and `search_credits` - both meters, Tavily's from the provider and Brave's counted locally, offered to operators only; the local credit ceiling counts an `advanced` search as the two credits the provider bills and is reconciled with the provider's meter every ten minutes and on any refusal; which allowance is used up - this account's day or month, or the shared monthly pool - is decided *before* routing, so search is simply not offered that turn and the reply opens with a friendly sentence naming the allowance and when it resets, then helps from what it knows without recommending anything already past; an outage, as distinct from a limit, reaches the reply as turn state it must admit rather than as silence; results are ordered by the main model in one constrained call, given the question, the person's place and the date - the 0.6B reranker read that badly - falling back to the providers' order) receives
only an already normalized and privacy-screened query and inherits only
operator-allowlisted search environment names. It emits compact valid JSON
below the generic MCP result cap. Internet eligibility remains deterministic
application policy; it is not delegated to the model.

The Compose `local-capabilities` sidecar exposes visual and presentation
application services as seven streamable-HTTP FastMCP tools:
`generate_diagram`, `generate_image`, `ask_about_image`, `get_artifact`,
`create_presentation`, `revise_presentation_slide`, and `get_presentation`.
Their model-visible schemas contain task arguments only. The backend attaches
user, conversation, and trace ownership as MCP request metadata only because
this locally configured server opts into `forward_context`; other servers
receive no application context by default. Results contain bounded public
artifact or deck metadata, never binary image/PPTX data or private storage keys. The server
is classified `untrusted`, so calls require explicit confirmation and are not
offered to ordinary autonomous chat selection until a browser
proposal/approval/resume lifecycle exists.

## Which model answers what

Roles are wired independently in `docker-compose.yml`'s `backend` service and
resolved by the `get_*_llm_client()` functions in `backend/core/dependencies.py`.
Nothing infers a model from context: each caller asks for a named role, so
changing one role never silently moves another.

| Role | Setting prefix | Model today | What calls it |
| --- | --- | --- | --- |
| Conversational | `MAIN_LLM_*` | DeepSeek-V4-Flash, vLLM tensor-parallel across spark1+spark2 (`animallya-spark1.local:8000`) | `build_assistant_graph` replies, `ConversationService`, visual reasoning, MCP tool orchestration, image style, Scout digests and place suggestions |
| Routing / tool-calling | `ROUTING_LLM_*` | DeepSeek (same deployment), temperature 0 | `MainActionSelector`, `ImageIntentClassifier`, the `VisualSearchGrounding` search decision |
| Vision | `VISION_*` | Qwen3-VL-8B (`anios-vlm` on spark2, `:8001`) | Canonical image observation and question-specific answers |
| Vision escalation | `VISION_ESCALATION_*` | Unconfigured | One specialist retry only when the primary reports visible diagnostic evidence it cannot interpret |
| Presentation | `PRESENTATION_LLM_*` | DeepSeek | Deck outline planning and slide microtasks |
| Diagram | `DIAGRAM_LLM_*` | DeepSeek | Diagram source generation |
| Memory proposal | `MEMORY_PROPOSAL_LLM_*` | DeepSeek, grammar-constrained, temperature 0 | Classifying what a turn is worth remembering |
| Text embedding | `EMBEDDING_*` | Nomic (`vllm-embedding`, spark1) | Semantic memory and retrieval vectors, both voices of every exchange |
| Reranking | `RERANKER_*` | Qwen3-Reranker-0.6B (`vllm-reranker`, spark1, `/v2/rerank`) | History recall's second pass; empty `RERANKER_BASE_URL` switches the stage off |
| Image generation / editing | `IMAGE_*` / `IMAGE_EDIT_*` | FLUX.2 Klein 9B / FLUX.1 Kontext via ComfyUI on the desktop | `generate_image`, `edit_image`, `show_image`, deck image enrichment |

Each role falls back through the next-broader scope when unset
(`ROUTING_LLM_* -> MAIN_LLM_* -> LLM_*`), so an unset role inherits rather than
failing; the roles are still pinned explicitly in compose so that changing one
never silently moves another.

**Why the split is shaped this way.** DeepSeek answers conversationally because
a blind six-prompt read put it ahead of both Qwen and Nemotron with no failures
(2026-08-14; full evidence in `ROADMAP.md` Milestone 9 and
`MODEL_EVALUATION.md`, "DeepSeek stays", 2026-08-20). The DeepSeek build is
text-only and cannot read pixels, which alone keeps a second, vision model
resident. On the single-GPU profile that preceded the Sparks, routing and the
structured roles stayed on Qwen 4B - routing for latency (Qwen returned in
about a second where DeepSeek added five to ten) and structured output because
DeepSeek then returned unparseable JSON for short classifications; with the
Sparks serving DeepSeek under grammar-constrained decoding, every text role
consolidated onto it and the 4B was retired.

An image question therefore touches three roles in order: vision describes the
pixels, routing decides whether the question needs a web search, and the
conversational model reasons over what the first two produced. Only the vision
step blocks the HTTP response; the rest runs after it, per
[the deferred reasoning path](#backend-boundaries).

## Backend boundaries

### Ambient discovery

Milestone 6's ambient discovery runs end to end inside the machine: a sweep
reads feeds, decides what is new, ranks it, and produces calendar files.
Delivering any of that outward remains unbuilt and gated.

`discovery_interests` and `discovery_localities` hold what the user likes and
where they live, behind `/api/v1/discovery/{user_id}`. Labels are sealed with
`EncryptedText` and identified by a SHA-256 digest of their normalized form,
because a sealed column cannot back a unique constraint: each value is encrypted
with a fresh nonce, so equal plaintext does not produce equal ciphertext. Case
and spacing differences therefore resolve to one interest while the readable
copy stays encrypted at rest. Interest provenance is validated against an allowed
set so an inferred value cannot be stored as a user-stated one, and the list is
bounded because every label is eligible to enter a chat prompt. Home coordinates
are deliberately absent: they would be the most sensitive value the application
holds and nothing consumes them yet. The profile is not injected wholesale into
ordinary chat because a standing interest list biased unrelated answers. Scout
sweeps consume it; chat uses the normal relevance-bounded memory path.

Home and interests are approved personal-memory facts, while the typed discovery
rows are the projection Scout needs for deterministic ranking. Chat recognizes
home statements with a narrow deterministic rule and sends the current utterance
to a focused local Qwen classifier for explicit current interests. It returns up
to eight short labels through a JSON grammar and has no persistence capability.
One visible approval writes the full interest batch and its profile projections
in one transaction; rejection or classification failure writes nothing. Editing
the Scout panel takes the reverse path:
the profile edit is immediately usable and records the corresponding approved
fact with profile-edit provenance. Removing either value clears the fact history
that owns the projection. Interest fact keys use a namespace plus the normalized
label digest, so they remain API-safe without exposing the interest in the key.

Operational controls remain typed profile state rather than competing facts.
Interest `strength` is an editable 1â€“3 ranking weight. Being away marks one
non-home locality as active behind a database-enforced partial unique index;
every sweep, preview, source suggestion, worker timezone, and familiarity scope
uses that active locality, then falls back to the approved home, so where Scout
looks changes without rewriting where the user lives.

Where someone *is* and where they *live* are two values, and both are needed:
familiarity is scoped per locality, so collapsing them would either strand what
a user already knew at home or teach Scout that everything ordinary in a city
they are visiting is familiar. What is not needed is a mode. `PUT
/discovery/{user}/current-place` records the current place and never the home
one; a reported place that differs from home is simply being away. Reporting the
home place again ends it, and the first place reported by a profile with no home
becomes the home, since anything else would leave it permanently away from a
home it never had.

Being away carries `travel_expires_at` (`DISCOVERY_TRIP_DAYS`, default 14) and
`active_locality` ignores a lapsed one, so a trip nobody remembered to end
returns to home by itself. A destination recorded before the expiry column
existed has none and stays open-ended. This was a real failure mode rather than
a theoretical one: the earlier design made reporting a location write the
*primary* locality, and `add_locality` records the approved memory fact behind
it, so one press from a hotel rewrote where the user lived, stranded their home
familiarity, and made memory say they had moved — twice, after they came back.
Because a coordinate cannot distinguish visiting from moving, the interface asks
once and defaults to visiting; promoting the place to home is a separate,
explicit action.
Dismissed familiar items can be reviewed and deleted from the Scout panel, which
lets a future similar result appear again in that locality.

Personal-memory export and delete-all cover every discovery-owned table:
interests, localities, sources, seen items, subscribers, familiar items,
schedules, and runs. Deletion orders dependent runs before schedules and is
user-scoped. The public export/delete APIs and live browser workflow exercise
these guarantees rather than inferring them from repository wiring.

`backend/discovery/events.py` defines a provider-neutral `EventSource` returning
typed events with a stable per-source identity, start, place, and link, with
iCalendar and RSS/Atom adapters parsed using the standard library. Discovery
reads structured listings rather than searching: local listings are already
structured, and search is the one part of the loop with a hard monthly ceiling.
Feeds are treated as hostile input — control characters stripped, text bounded,
non-web URL schemes dropped, 200 events per source, and bodies abandoned
mid-stream past 5 MB. A `RequestBudget` fixes how many outbound requests one run
may make, so the free-tier claim is decided in advance rather than emerging from
how many sources happen to be configured. RSS is deliberately weaker than
iCalendar: an item states when it was published, not when the happening occurs,
so items carry no start time unless the publisher supplies an explicit event
date.

`discovery_schedules` and `discovery_runs` hold one user's cadence and each
durable, leased sweep. Leasing reuses the presentation-worker pattern rather than
introducing a second scheduler. Two invariants carry the milestone's
never-double-notify requirement: a unique constraint on
`(schedule_id, scheduled_for)` makes a slot exactly-once, so a restarted producer
cannot queue the same sweep twice, and `delivered_at` is written once, so a
resumed run declines rather than delivering again. Cadence is computed in the
user's own timezone, including the daylight-saving case where a 9am sweep must
stay 9am rather than drift with the old UTC offset.

`discovery_sources` holds the feeds a sweep reads and `discovery_seen_items`
records what it has already accounted for. Both seal the user-supplied value and
identify it by digest, for the same reason the profile does. Novelty is decided
in two passes ordered by cost: exact identity, a SHA-256 over the source and the
source's own external id, catches the ordinary case of a feed relisting the same
event every sweep; then a pgvector near-duplicate check catches the same
happening published under a new identifier or by a second feed. Only an
*announced* item suppresses a candidate, so being ranked out once cannot
permanently mask something the user was never shown, and the check looks back a
bounded horizon so an annual event recurring next year still counts as new.

One ranking path is deliberately not anchored to an interest. Every other part
of selection scores against what the user said they like, which is what keeps a
digest from becoming noise — and also means the loop can only return more of
what it already knew about. `NotableSelector` surfaces at most two finds per
sweep that match no interest and are unlike anything the account has been shown,
under their own heading, fed by one query per sweep that names no interest.
Two criteria must hold, and the first does the work: the matcher must have
scored it below its own floor, and it must sit beyond `MIN_UNLIKENESS` from the
nearest item in the user's history. Distance alone was tried and measured wrong
— against a ten-item history a guided night hike scored `0.362` while a hot air
balloon festival scored `0.328`, so a bar on unlikeness admitted the hiking
event and rejected the balloon festival. Nearest-neighbour is used rather than a
centroid, because the centroid of a varied history resembles nothing and
everything looks far from it. The quota is small and the section is separate
because the subsystem's own rule is that an empty digest beats a padded one.

Ranking is otherwise deterministic and runs outside the model, matching how
search routing already works. A sweep happens while nobody is watching, so a sampled judgement
would make the same feed produce different results on different days, and
scoring in vector space costs one batched embedding call rather than one
generation per candidate. A candidate scores against its best single interest
weighted by that interest's strength — summing across interests would let
something weakly resembling everything outrank something strongly matching one
stated interest — and must clear both a score floor and a lead-time window,
since something happening tonight is not actionable from a weekly digest. The
model still writes the digest a user reads; it does not decide what qualifies.

`backend/discovery/calendar.py` renders selected events as RFC 5545 documents,
served at `/api/v1/discovery/{user_id}/calendar/{item_digest}.ics` from the
stored item rather than by re-fetching the feed. The rules that matter are
ordered escaping, octet-counted folding that never splits a multi-byte
character, refusal of naive timestamps rather than guessing a zone, and UIDs
stable across renders so re-importing updates an appointment instead of
duplicating it. A calendar client that dislikes a file usually declines it
without explaining why, so the format is asserted directly in tests rather than
inferred from an import that appeared to work.

Search enumerates alongside feeds rather than only finding them. iCalendar feeds
cover institutions — venues, museums, universities — and publish nothing for a
trail association's group hike or a pop-up that exists only as a page someone
wrote. For a niche interest that is most of what happens, so `WebEventSource`
queries the configured `SearchProvider` (MCP or Tavily) once per interest, within
the sweep's request budget.

Two rules keep that from undoing the loop's other properties. A start time is
**read, never inferred**: dates come from an explicit deterministic parse of the
result text, and anything requiring a reference point the snippet does not carry
— "this weekend", "next Saturday" — yields no start at all. An undated find is
still surfaced, as a link in a separate section of the digest, and cannot become
a `VEVENT`. An explicit date before the current day is a different state and is
rejected at conversion; collapsing it into the undated state previously let a
finished event back into the digest. The renderer states that an undated find's
date could not be confirmed rather than presenting it as verified upcoming.
And the query count is bounded before the sweep runs, because search is the only
metered component here.

`backend/discovery/summarize.py` makes a find readable enough to decide on. A
scraped page title names the site rather than the happening — "Nature and History
Events – Official Website of Arlington County Virginia Government" — and a
recipient cannot judge that. Cleanup is deterministic and strips a trailing
segment only when it looks like a CMS site name, so a genuinely hyphenated title
survives.

The sweep uses a model only to turn a selected scraped paragraph into a sentence
a person can read. Deciding *what qualifies* stays deterministic because a sweep
runs unattended and must not vary by sampling. The separate chat-time interest
classifier proposes user-authored profile input and never ranks events.
Descriptions answer into a decoding grammar with a bounded field, greedily,
so the same page describes itself the same way each sweep. No URL survives from
model output — links come from the typed record, so a page cannot put a link of
its choosing in front of a recipient — and any failure falls back to a
first-sentence extract that never invents. The grammar constrains shape, not
meaning: a hostile page can still influence the wording of its own description,
exactly as it influences its own title.

Descriptions are written before the selection is persisted, because the stored
payload is what every later preview, digest, and calendar file is built from.

Queries carry the locality's region, not just its label. A bare town name is
ambiguous to a search engine exactly as it is to a person: "hiking near
Arlington" returns Texas and Washington alongside Virginia, which was observed
rather than predicted.

Setup also uses search to find *sources* rather than events. That division is what preserves two
properties the weekly loop depends on: search is the one metered component, so
keeping it off the recurring path keeps the loop inside the free tier; and a
search snippet cannot supply a zone-aware start, so enumerating events that way
would mean inferring dates from prose and producing calendar entries that are
confidently wrong. A suggested feed is offered only after AniOS has fetched it,
parsed it with the same adapter a sweep uses, and seen real typed events come
out. Interests are proposed from already-approved memory, never from inferences,
and a proposal is never a fact — accepting one is the separate call that records
`user_explicit` provenance.

Location is set as a place *label*, typed or resolved. The browser's geolocation
API returns a fix precise enough to identify a building, and for a request made
at home that is the user's address — the most sensitive value this application
could hold, which is why the profile has never stored coordinates. The resolve
path therefore discards precision before it can travel: the coordinate is
rounded to roughly a kilometre in one place that no adapter can bypass, a
`PlaceResolver` provider names the town, and only that label is persisted.
Resolution is off unless an operator configures a provider, so an unconfigured
deployment reaches nobody, and typing the town makes no outbound request at all.

The calendar travels **with** the message rather than being linked from it. One
`.ics` carrying every dated find is attached, so a phone can offer to add them
together and — more importantly — a recipient anywhere with internet can act on
it without reaching the machine that produced it. A link would require AniOS to
be publicly addressable, which is a far larger commitment than sending a file,
and would fail silently for anyone off the sender's network. When the file is
attached the message drops its links, because those links would be exactly the
ones that do not work.

Undated finds keep their own source URL, which points at the third-party page and
is reachable from anywhere regardless.

`discovery_familiar_items` answers a different question from the seen store.
Novelty asks "have I shown you this before"; familiarity asks "did you already
know it". For someone who has lived somewhere a while those diverge sharply — a
trail they walk weekly is new to the database and worthless to them — so a find
can be dismissed as already known, and dismissal suppresses by embedding
proximity rather than identity, because marking one trail directory as known is
only useful if the next four like it are also gone.

Familiarity is scoped **per locality**, which is the design's whole point.
Someone who knows every trail in Arlington knows none in Denver, so the same
happening is noise at home and a genuine find while travelling. A global list
would make the agent progressively useless exactly when travel makes it most
valuable. The scope is a digest of the locality label rather than a foreign key,
so it survives a place being renamed or removed.

Both sides of the comparison clean the title first. The user dismisses the title
they were shown, which has already had its CMS site name stripped, while a
candidate still carries the raw one from search; comparing those directly makes a
dismissal silently do nothing, which is what happened on the first live run.

Notification egress remains `PLANNED` and gated: it is the first outbound path
in AniOS, and every subsystem before it fails closed inside the machine.

### Agent delegation

`backend/agents/delegation.py` holds the routing rules as an ordered, listable
registry rather than a chain of conditionals inside the graph node that uses
them. Each policy names a capability and grants nothing: the caller resolves that
name against what is actually wired up, so a policy for an agent with no handler
falls through to the ordinary assistant instead of dropping the turn. Adding a
specialist is deliberately two steps — a policy and a handler — because routing
to something that cannot run is worse than not routing at all.

Matching is pattern-based and deterministic, for the same reason search routing
is: this runs on every turn, and a sampled judgement would send the same sentence
to different agents on different days. A policy separates the noun from the verb,
which is what keeps "show me the deck" from being read as "build me a deck", and
ties break on declared priority rather than on registration order.

### Agents

`backend/agents/registry.py` describes every specialized agent for one user, and
`GET /api/v1/agents/{user_id}` serves it to the workspace's Agents tab. Two
agents exist today: **Scout**, the ambient discovery loop, and **Deck**, the
presentation specialist.

Each agent owns a folder — `agents/scout/`, `agents/deck/`, `agents/diagram/`,
`agents/memory/` — holding what that agent *decides*: its card, and any prompt
or orchestration specific to it. The last two have no card, because neither is
something a person starts: the diagram agent answers a chat turn, and memory
capture is a step in every one. The shared shapes live in `agents/cards.py` and the registry is
a tuple of describers, so adding an agent is adding a folder rather than editing
the module every other agent lives in.

The dependency runs one way: this layer imports domain packages and none of them
import back. Scout's sweep therefore stays in `backend/discovery/` — moving it
under `agents/scout/` would make `discovery.runner` import from `agents`, which
`agents.registry` already imports from. An agent folder holds what it decides;
its domain package holds the machinery it drives.

The registry stores nothing. Every field is derived from the tables each agent
already writes — schedules, runs, sources, subscribers, presentation jobs — so
the tab cannot drift from reality by being updated in the wrong place, and an
agent that stops working shows as stalled rather than showing whatever it last
claimed about itself. Adding an agent means adding a describer, not a row.

Status is deliberately five-valued rather than a boolean. `needs_setup` is
separated from `idle` because the most common discovery failure is having no
sources or no interests, and reporting that as "idle" hides the one thing the
user needs to do. The detail line names what is missing.

### Presentation

`backend/main.py` constructs the FastAPI application, allows CORS from the local Vite origins, mounts the v1 router at `/api/v1`, and defines `GET /health`.

`backend/api/v1/api.py` defines:

- `GET /api/v1/`;
- `POST /api/v1/chat`, which validates a typed `ChatRequest` and returns Server-Sent Events named `start`, `delta`, optional search/tool/memory/artifact/image lifecycle events, and `done`. A streaming failure is logged server-side and returned as a sanitized `error` event.

`backend/api/v1/memory.py` defines user-scoped profile, generic approved-fact lifecycle, preferred-name approval/deletion, episodic/semantic create-correct-search-delete, export, and delete-all endpoints beneath `/api/v1/memory/{user_id}`. `backend/api/v1/agent_memory.py` adds typed semantic-cache, working-memory, procedure, entity/relation, knowledge-document/chunk, conversation-summary, retention, re-embedding, operations, and per-record deletion routes beneath `/api/v1/memory/{user_id}/agent`. Approved facts carry source conversation/trace provenance; normalization deduplicates equal values, contradictions create a superseding version, and supported `preferred_name`/`response_style` keys project into `user_profiles`. Delete-all covers conversation, personal, tool, agent-memory, discovery, and visual-artifact rows, derived visual semantics, and owned visual binaries. Export covers the memory categories and conversations; binary artifact export remains separate.

`backend/api/v1/artifacts.py` lists recent owned artifacts, returns owned binary content with private/no-store and nosniff headers, and deletes both the database row and binary file. Explicit diagram requests create a pending record before provider work and stream a sanitized terminal success or failure lifecycle. If the client disconnects after pending persistence, the application shields only the terminal cleanup write, marks the record failed with `cancelled`, and re-raises cancellation.

`backend/api/v1/images.py` accepts a bounded prompt and one allowlisted FLUX resolution, then returns a terminal generated-image artifact. Its refinement route reads an owned generated or uploaded parent and passes the integrity-checked source pixels plus exact bounded feedback and preservation constraints to the same configured FLUX.2 Klein provider. It creates a fresh child carrying parent, source-hash, feedback, model, seed, step, and latency provenance. `backend/api/v1/vision.py` streams a bounded multipart upload, validates actual PNG/JPEG/WebP content, rejects animation, MIME mismatch, excess bytes, and excess pixels, persists the owned upload, and sends only the validated image plus bounded prompt to the configured local vision provider. Invalid uploads create no artifact; VLM failure preserves the valid upload with `analysis_status=failed` for later deletion or retry work. `POST /api/v1/vision/artifacts/{artifact_id}/ask` remains an API/MCP boundary for direct grounded questions: it re-reads owned integrity-checked bytes, replays bounded prior context, and persists a size-bounded thread. The browser now uses one main composer instead of a second field per image. It sends an explicitly selected owned image ID when present; otherwise one semantic modality gate admits owner-scoped pixel-vector lookup and the description-vector fallback. Every selected ID is re-read through the owned ready-artifact boundary before its description and lineage reach the answer prompt. Every stored upload and refined child also receives an aligned Nomic pixel embedding, and initial upload analysis is indexed as a provenance-labelled semantic description. Interactive direct-followup thread entries remain un-indexed.

`backend/api/v1/tools.py` exposes explicit policy-gated MCP invocation. For a
configured context-aware local server, it starts a trace and forwards the
authorized path user plus optional conversation ID as hidden request metadata;
those ownership values are not part of the tool arguments selected by a model.

A deck is editable as a structure, not only as content. Beyond slide revision,
`POST .../slides` inserts a slide at a 0-based position, `DELETE .../slides/{id}`
removes one, and `PUT .../slides/order` permutes the deck. Each is an ordinary
linked revision, so every structural change is reviewable and reversible through
the same history as a content edit. Position is an index rather than an "after
this slide" reference, because the first position has no slide before it.
Reordering sends the complete order and refuses anything that is not a
permutation; deletion refuses the last remaining slide; both prevent a partial
request from silently dropping or duplicating a slide. Adding runs the model on
the deck's titles and purposes only, so an addition cannot rewrite slides the
user already accepted, and no model runs for deletion or reordering at all.

Deck content is grounded before any layout is chosen. `DeckResearch` runs one
privacy-screened web search per deck at outline time and quotes bounded,
attributed sources into the outline and into every slide request as untrusted
data, with the rule that a figure the sources do not support must become a
plainer layout rather than an invented number. Outline time is the right moment
because that is where a slide is told to carry a statistic; by the slide pass
the only way to satisfy that instruction is to make one up. The brief is reduced
to its research subject first, since a deck brief is mostly instructions about
the artifact — sent verbatim, one returned a slideware marketing page as a
source. Screening reuses `OutboundPrivacyPolicy`, metering reuses the
per-account search budget, and a disabled, blocked, or failed search leaves the
deck planned ungrounded rather than failing it. `PRESENTATION_RESEARCH_ENABLED`
governs it, and it must reach `presentation-worker`, which is the process that
plans decks. Grounding measurably reduces invented figures but does not remove
them at the current 4B presentation role; see
[NEXT_SESSION.md](NEXT_SESSION.md) for the measured before/after.

A slide takes one of seven shapes: bullets, section, statistic, quote,
comparison, chart, and table. No layout discards planned content: every slide is
planned with two to four points, and the section divider used to render none of
them, which produced slides carrying a title and a purpose and nothing else. It
now keeps its rule and centred title and carries its points beneath them, with
the block centred as a whole so a divider without points is positioned exactly
as before. The model chooses the shape and deterministic code
still owns geometry. The layout is an enum in the decoding grammar, and the
fields a layout needs are promoted to `required` for that call with their null
branch removed, so a chart slide without chart data is not a decodable reply.
Naming the fields in prose was not sufficient in either direction: the model
returned chart layouts with no data, and later a prompt asking to keep the
current shape contradicted a grammar asking for a new one. The compiler still
degrades a layout it cannot render to bullets rather than raising, so a partial
plan produces a usable slide. Charts and tables compile from the plan, which is
what lets a revision edit their data or remove them; only an attached image
survives a revision, because nothing regenerates it.

Geometry is measured rather than fixed. `backend/presentations/layout.py`
estimates rendered line count from text length, box width, and point size, so
the compiler sizes a title to its actual content, stacks bullets at their own
heights, and shrinks the body font within bounds when content is dense instead
of overflowing. Every content layout derives its width from one place and yields
the column a generated image occupies, including the heading band, whose purpose
line sits low enough to reach the picture's top edge.

`backend/api/v1/presentations.py` enqueues creation with HTTP 202 and returns an
owned job handle. Job reads expose queued/running/terminal state and the latest
validated draft; cancellation is cooperative. The legacy creation SSE endpoint
uses the same durable job and polls persisted progress, so a browser disconnect
does not terminate work. The React panel stores the active job ID per user,
polls it across navigation and reload, renders arriving slides, and hydrates the
ready deck after the background worker promotes its revision. The selected-slide
  image endpoint uses FLUX when no image exists; when an `ImageElement` is
already attached, `PresentationImageService` sends that owned source artifact
and explicit image feedback through `ImageRefinementService`, then replaces the
image UUID in a new append-only deck revision. The surrounding native Office
objects remain editable, and the prior deck/image revisions remain intact.

The image-generation handler monitors HTTP disconnects around provider work. A browser cancellation cancels the service task, interrupts the matching ComfyUI prompt, shields the terminal `failed/cancelled` write, and finishes without an application exception. The unified React composer infers new-image generation from bounded natural-language intent and image analysis from an attachment while retaining progress, cancellation, retry input, visible API failures, and bounded file selection. `ImageArtifact` fetches private bytes with the optional auth header, renders a temporary object URL, exposes grounded Qwen text, and supports selection, local download, and owned deletion. The newest visible image is the default composer reference; **Ask or edit** selects any other visible image, a thumbnail chip makes the target explicit, and removing it suppresses explicit image context. The main composer classifies a selected-image instruction as question or refinement. A returned FLUX child replaces its parent in the active card and becomes the selected reference, while persisted lineage keeps history recoverable. Conversation hydration and artifact history restore both diagrams and binary images.

`backend/api/v1/conversations.py` returns a bounded, user-owned conversation snapshot containing persisted turns and their conversation artifacts. The frontend uses that read boundary to reconstruct the active transcript and ready/failed diagram cards after a full reload.

The artifact-reference contract is intentionally broader than images even
though only visual conversational loading is implemented today. The semantic
modality gate already distinguishes image, document, audio, and video without
querying their indexes; a future source then exposes the same owned artifact
handle, provenance, lineage, derived semantic descriptions, and
modality-specific retrieval data.
Explicit selection is an override; semantic resolution remains the default for
natural references. Private source bytes are never substituted for bounded
derived context, and every resolved handle is owner-validated again before use.
Derived visual descriptions enter the bounded semantic shortlist only while
their referenced artifact is still ready and owned by the same user. Artifact
deletion removes the matching derived description in the same PostgreSQL
commit, so a deleted picture cannot remain as recallable semantic evidence and
stale legacy rows cannot crowd live pictures out of the shortlist.
After FLUX creates a ready refinement, the local Qwen vision boundary observes
the child pixels and writes that revision's own analysis and derived semantic
index. If observation fails, the valid edit remains usable and the failure is
logged; lineage is still available as degraded context, but real-model coverage
records that Qwen can prefer an origin detail over a text-only edit delta.

The Memory panel loads only bounded counts and snapshots initially. Every
memory-map card is an accessible detail action; selecting a durable store makes
an explicit owned export request, shows readable records on demand, bounds the
rendered list, and omits embedding vectors and private storage keys.

Every chat, memory, and presentation route applies the optional signed-user ownership boundary. Authentication is disabled by default for trusted-local development; when enabled, the token subject must equal the body or path user ID.

Ownership answers *who*; scopes answer *what*. A token may be narrowed to least-privilege scopes - `chat`, `memory:read`, `memory:write`, `tools:invoke`, `vision`, `presentations`, or the `memory`/`tools` groups - and each route requires the scope matching its action, so a read token satisfies a `GET` but is refused a `DELETE` before the handler runs. A group scope satisfies its children (`memory` covers read and write); a token with no scope claim stays unrestricted, so scopes were adopted without invalidating the tokens or tests that predate them, and an unknown scope is rejected when the token is issued rather than becoming a silently powerless grant. Scopes narrow a valid token; they never replace the ownership check, which still binds the request to the subject.

Sensitive content is optionally encrypted at rest. With `ENCRYPTION_KEY` configured, an `EncryptedText` column type seals conversation turns and episodic/semantic memory content with AES-256-GCM at the persistence boundary - no repository or serialization change - and the binary artifact store seals image bytes on write while recording integrity over the plaintext, so the existing SHA-256 re-check after a read still holds. The sealed form is self-describing (`enc:1:…`) and legacy plaintext reads back unchanged, so enabling encryption needs no migration; each value uses a fresh nonce, which is exactly why the type is applied only to content retrieved by id or vector and never to a deduplication or uniqueness column. This is defence in depth over OS full-disk encryption for data that leaves the process without the key, not a sandbox against a live compromised host, and embedding vectors stay searchable and therefore unencrypted - a documented residual disclosure vector. See docs/SECURITY.md for the threat model.

### Services and dependency assembly

`backend/core/dependencies.py` assembles `ConversationService` and its collaborators through FastAPI dependencies.

The active collaborators are:

| Component | Status | Implemented reality |
| --- | --- | --- |
| `ConversationService` | implemented local boundary | Obtains a memory query plan, loads selected context plus bounded same-user history, streams an injected model through LangGraph, persists the response, and updates memory lifecycle state |
| `PostgresMemoryService` | implemented local boundary | Supports profile upsert, episodic save/read, live embedding generation, pgvector semantic save/search, snapshots, and scoped deletion |
| `AgentMemoryManager` | implemented typed store facade | Owns user-scoped semantic-cache, working, procedure, entity/relation, knowledge, and summary stores without exposing raw tables to the coordinator or model |
| `MemoryCoordinatorAgent` | implemented deterministic policy boundary | Searches every embedded store on each turn, and the user's own past turns beside them so anything relevant can be recalled regardless of phrasing, embeds the query once and reuses that vector across all of them, relies on each store's cosine-distance threshold and one shared cross-store relevance budget (with dedup and item/character caps) to keep only close matches, selects the non-embedded episodic store by explicit keyword intent, writes expiring session state, and periodically rolls conversation digests |
| `ToolMemoryService` | implemented safe metadata boundary | Stores and retrieves user-scoped safe tool descriptors, approved preferences, and sanitized outcomes; invocation and authorization remain owned by the separate orchestration and policy boundaries |
| `MainActionSelector` | implemented unified action-selection boundary | Offers search, image generation/edit, diagram, specialist delegation, and the user's own registered MCP tools to the main model as one native tool-calling decision, resolving live schemas and refusing any name the round did not actually offer; it replaced `MainSupervisorAgent`'s deterministic LangGraph policy node, which has been deleted |
| `MCPToolOrchestrationService` | implemented model-selection boundary | Gives the configured main model a bounded live-validated shortlist, accepts at most one native tool call, and produces an application-owned plan without execution authority |
| `MCPInvocationService` | implemented execution-policy boundary | Re-resolves live contracts, enforces local risk policy, validates and privacy-screens arguments, invokes stdio/HTTP tools, and bounds results as untrusted |
| `MCPWebSearchProvider` | implemented read-only search boundary | Invokes the fixed internet MCP tool after deterministic routing and privacy minimization, then validates and filters compact result JSON |
| `VisualCapabilityRuntime` | implemented local FastMCP adapter | Reuses diagram, image, vision, repository, and binary-store services in a dedicated streamable-HTTP process; validates hidden ownership context and returns metadata-only artifact handles |
| `PresentationAgent` | implemented specialized LangGraph boundary | Runs typed create, progressive-create, or revise operations around the replaceable provider; progressive graph custom events carry validated drafts, and the agent cannot persist, authorize, render, or promote a revision |
| `PresentationJobService` | implemented durable scheduling boundary | Enqueues owned creation jobs, reports persisted progress, and requests cooperative cancellation without running model work in the API process |
| `PresentationWorker` | implemented specialized worker boundary | Claims one leased PostgreSQL job with `SKIP LOCKED`, invokes the presentation LangGraph, checkpoints each draft, renews its lease, and records ready/failed/cancelled terminal state |
| `PresentationService` | implemented presentation lifecycle boundary | Executes claimed creation jobs and synchronous selected-slide revisions, coordinating deterministic compilation, rendering, structural and Office validation, opaque storage, failure recording, and current-revision promotion |
| `PresentationImageService` | implemented slide-image coordination boundary | Uses FLUX for a slide's first image and source-aware feedback, then attaches the immutable child UUID through the normal linked-revision promotion path |
| `SQLAlchemyPresentationRepository` | implemented append-only revision boundary | Stores user-owned presentations and immutable revision lineage, rejects stale-base edits, and promotes a ready revision only after every validation boundary succeeds |
| `SQLAlchemyPresentationJobRepository` | implemented durable job boundary | Atomically creates presentation/revision/job records, leases recoverable work, persists progressive drafts, reconciles completed revisions after worker loss, and scopes reads/cancellation by owner |
| `PptxGenJSRenderer` | implemented renderer adapter | Sends a strict `DeckSpec` to the bounded PptxGenJS worker, validates response headers and OOXML structure, and optionally requires the worker's LibreOffice result |
| `DiagramAgent` | implemented specialized LangGraph boundary | Runs one typed `generate_diagram` node around the replaceable provider; it has no persistence, authorization, or hardware-management authority |
| `DiagramArtifactService` | implemented local artifact boundary | Coordinates pending/ready/failed diagram records, invokes a replaceable bounded diagram provider, and never gives the model persistence authority |
| `ImageArtifactService` | implemented local binary artifact boundary | Coordinates generated/uploaded pending/ready/failed records, source-conditioned immutable refinements with parent/source-hash lineage, opaque atomic file storage, SHA-256/size integrity checks, owned content reads, and file-plus-row deletion |
| `ComfyUIImageProvider` | implemented free local provider | Submits a pinned four-step FLUX.2 Klein text-to-image workflow through ComfyUI, polls terminal history, fetches one output, validates it, and limits concurrent jobs to one |
| `ComfyUIImageEditProvider` | implemented free local editor | Uploads the owned source to ComfyUI and runs a four-step FLUX.2 Klein 4B Distilled single-reference workflow with Qwen 3 4B text encoder and FLUX.2 VAE before bounded output validation |
| `VisionAnalysisService` | implemented local VLM boundary | Persists a validated upload and obtains one schema-constrained primary inspection for routing, durable observation, immediate answer, evidence sufficiency, grounding, and reasoning need. Each relevant visible item carries its own high/medium/low confidence and evidence basis: high-confidence identities may enter derived visual memory, while supported weaker readings remain explicitly unconfirmed and contradicted readings may be omitted. Safety-sensitive identification remains strict; unresolved model uncertainty may retry once through an independently configured specialist VLM. Candidate-free uncertainty does not spend web or main-model reasoning. Followups re-read owned bytes and retain a bounded persisted thread. |
| `ArchitectureCandidateService` | implemented review-only maintenance boundary | Combines registered canonical source with bounded explicit repository evidence, requires selected visible labels, and returns a candidate without canonical write authority |
| `SQLAlchemyArtifactRepository` | implemented user-scoped persistence boundary | Stores diagram source, lifecycle, conversation/trace provenance, provider/model metadata, and supports conversation listing plus individual and forget-me bulk deletion |
| `ArtifactDeletionService` | implemented cross-store lifecycle boundary | Removes one user's visual rows and derived descriptions, then deletes the returned opaque binary keys while surfacing incomplete file cleanup |
| `SQLAlchemyConversationRepository` | implemented local boundary | Saves and counts turns under stable conversation IDs and reads a configured newest-turn window filtered by both conversation ID and user ID, returned in chronological order |
| `LoggingConversationTracer` | implemented local boundary | Generates a new trace UUID for each request and records lifecycle events through application logging |

Notification and external-agent collaborators are not part of current dependency assembly. Internet search and guarded MCP execution are assembled; knowledge ingestion/retrieval is implemented as a local memory store, while a complete RAG pipeline remains `SCAFFOLDED`.

Chat memory capture is auto-saved, with no approval boundary. One local
`MemoryProposalAgent`, backed by Qwen 3.5 4B, semantically interprets the whole
current utterance and returns grammar-constrained candidates for preferred name,
response style, locality, interests, entity relationship, workflow, titled
reference, semantic fact, and episodic event. Phrase matching and regular
expressions do not decide memory meaning. Deterministic application code only
bounds and validates the structured fields, adds ownership provenance, and
routes each candidate directly to its typed store the same turn it was
classified. The agent itself cannot persist, but `ConversationService` writes
on its behalf immediately, with no user approval step; a per-candidate save
failure is dropped and logged rather than raised, so it costs only that one
candidate, never the turn's reply or any other candidate saved alongside it.

The save happens **before** the answer is generated, and the turn's real save state is rendered into the system prompt. The model has no write tool, so a helpful assistant answering "remember this" claims a save that never happened; telling it only that it cannot write to memory proved insufficient, because it re-expressed the same claim passively ("your personal memory has been updated"). Naming what actually just happened, and the value that was written, removes the thing to route around. Emission over SSE still follows the saved turn. Profile facts may coexist in one decision; non-profile memory keeps one best typed candidate to limit noise. The frontend displays what was already saved as a reply-adjacent, read-only notice — visibility for debugging and correction, not a consent step — and never itself calls a write endpoint for a chat-classified candidate. The model never receives a durable-write tool; every write is decided and executed by application code before the reply is generated, and silent, unreported persistence remains unsupported (the notice is always emitted alongside the save).

### Agent orchestration

AniOS routes every turn through one native tool-calling decision before the assistant graph runs. `MainActionSelector` offers the live `search_web` schema, `generate_image`, `edit_image` (only when a picture is in view), `create_diagram`, `delegate_to_presentation_agent`, and the user's own semantically shortlisted MCP tools to the main model in a single call; the model picks at most one, or none, from genuine understanding of the request rather than from a regex or a narrow bounded classifier judging the question alone. `process_request` dispatches on whatever it picked: `create_diagram` and `delegate_to_presentation_agent` short-circuit into their own artifact/job lifecycles exactly as before, `generate_image`/`edit_image` run the same ComfyUI FLUX pipeline the old direct REST endpoints did but now inside the chat stream (so the exchange is visible in conversation history, which it previously was not), and `search_web`/a toolbox tool/no action continue into the ordinary assistant graph with that decision already made. The browser receives `agent_started`/`agent_finished` for a delegated specialist and `artifact_started`/`artifact_ready`/`artifact_error` for a diagram, a new image, or an edit — the same event pair a diagram always used, now shared by pictures too. The ordinary assistant graph contains one streaming main-model node, `DiagramAgent` contains one asynchronous `generate_diagram` node, and `PresentationAgent` contains typed create, progressive-create, and revise operations around `PresentationProvider`. `MainSupervisorAgent`'s deterministic LangGraph policy node, `DelegationRegistry`, `CascadingSearchRouter`, `SearchRoutingPolicy`, and the bounded `QueryFreshnessClassifier` behind them have all been deleted, along with the `SEARCH_CLASSIFIER_*` settings and the classifier LLM role that served them.

This is deliberately narrower than a free-form LLM router. Deterministic registered intents provide a fast, testable first boundary; semantic MCP discovery plus native main-model tool selection handles eligible tools later in the ordinary path. The supervisor cannot invoke services, persist state, grant permissions, or invent capability IDs. The standalone presentation worker invokes the focused graph only after PostgreSQL claims a durable job. Application code owns authorization, scheduling, live contract revalidation, privacy, risk policy, invocation, persistence, and result attribution. Retrieved values and tool results are untrusted literal data and cannot grant permissions. A unified dynamic capability registry, ambiguity clarification/resume, researcher and reflection agents, A2A, and general agent-team scheduling remain `PLANNED`.

### LLM integration

`backend/core/llm.py`, `backend/vision/lm_studio.py`, and
`backend/embeddings/lm_studio.py` expose provider-neutral text, vision, and
embedding contracts plus fail-closed adapter factories. The implemented
`openai_compatible` adapter supports buffered, streamed, structured/native
tool-call, vision, and embedding requests. Dependency assembly independently
selects the adapter, endpoint, model, and reasoning setting for main,
presentation, diagram, vision, and embedding roles; blank role values inherit
the global adapter and established endpoint fallbacks. `INFERENCE_PROVIDER_NAME`
is only a provenance label and does not select transport behavior. Existing
`LLMClient`, `LMStudioLLM`, and LM-Studio-named vision/embedding imports remain
temporary source-compatibility aliases only; runtime assembly depends on the
neutral contracts and the current deployment no longer calls LM Studio.

The text adapter preserves ordered messages, exposes only
application-supplied tool schemas, yields assistant deltas, and requires
terminal `[DONE]` for streams. An in-process lock protects each shared client
instance. Model discovery, loading, unloading, context/KV-cache selection, GPU
offload, residency verification, and restoration are deliberately not part of
the inference adapter. The qualified runtime is vLLM 0.23.0 in two pinned
Compose services. Compose owns their model/revision/startup profile, while the
adapter remains unaware of process lifecycle; another runtime must implement
the same inference contract and pass the owning subsystem acceptance paths
before promotion.

For the Compose runtime, `ModelExecutionGate` adds an expiring Redis lease
shared by backend and presentation-worker processes: a foreground chat
increments a wait counter and holds the lease for its model lifecycle, while
background presentation generation acquires it for one outline or slide
microtask at a time and yields between tasks whenever chat is waiting. Redis
stores only coordination keys and opaque lease tokens. This is bounded priority
scheduling for one local model host, not GPU-capacity accounting or a general
distributed-agent scheduler.

The qualification that established this boundary (historical, single-GPU profile) consolidated main response, native tool selection, diagram, presentation, architecture-candidate, and vision roles on `qwen/qwen3.5-4b`, served in FP8 by `vllm-main`, with `vllm-embedding` serving Nomic text embeddings. Provider-level checks passed streaming termination, native tools, structured output, vision, and embedding dimensions; real acceptance then passed direct chat, live Chromium chat/restoration, uploaded-image analysis, real ComfyUI generation while both vLLM services remained resident, and three consecutive presentation jobs. The same promotion rule carried the text roles onto DeepSeek on the Sparks in 2026-08 (`MODEL_EVALUATION.md`, `DGX_MIGRATION.md`): the repeatable harness remains a promotion gate, not sufficient proof by itself.

### Schema-constrained model boundaries

Every boundary that parses model output as data rather than prose now sends a JSON Schema with the request, which the runtime decodes as a grammar. A reply that violates the schema is unrepresentable rather than detected afterwards, so the correction retries below each boundary became a fallback for semantic errors instead of the primary defence against format drift.

The presentation boundary derives its schema from the same Pydantic model that validates the reply, so the contract and the grammar cannot drift apart; an explicitly requested slide count is compiled into `minItems`/`maxItems` rather than validated and re-prompted. This closed the two observed Qwen output variants directly: `extra="forbid"` becomes `additionalProperties: false`, which forbids invented `optional_` field prefixes, and the typed `notes` string forbids `notes: null`. The diagram boundary constrains its reply envelope, which guarantees the correctly escaped newlines its retry text was written to request.

Routing classifiers decode greedily. At the runtime's default sampling the same freshness question was observed answering both `YES` and `NO` across identical calls, which made a search decision depend on sampling luck; `temperature=0` makes the judgement reproducible.

### Scalable inference target

The current Compose profile is one deployment of stable role-level inference
contracts, not the definition of AniOS scale. Main, presentation, diagram,
vision, and embedding settings already resolve independently through
provider-neutral adapters. The accepted target keeps registered role selection,
authorization, privacy policy, durable job state, and result promotion in AniOS,
then introduces an application-owned capacity/placement policy that resolves a
role to a stable serving endpoint. Behind that endpoint, generation/vision,
embedding, and future specialist models can scale as separate vLLM pools.

Replication and data parallelism are the preferred way to increase independent
request throughput when each model fits one GPU. Tensor or pipeline parallelism
is reserved for a model that cannot fit on one device, because splitting one
request adds communication cost. Ray Serve LLM or Kubernetes may later provide
load balancing, back-pressure, autoscaling, and failure replacement, but neither
is part of the current Compose runtime. A serving control plane does not become
an agent and never receives application authorization, memory-write, tool-risk,
or artifact-promotion authority. Each pool must expose model-labelled vLLM
Prometheus metrics, and promotion requires role correctness plus warm/cold
latency, queueing, saturation, cancellation, and recovery evidence.

The [inference scaling target](diagrams/inference-scaling-target.svg) uses blue
for implemented application boundaries and yellow dashed nodes for this planned
serving infrastructure. Multi-node vLLM traffic must remain on a protected
private network; it is not treated as an authenticated or encrypted application
boundary by default.

Explicit diagram requests bypass ordinary memory retrieval and the assistant graph, then run through the dedicated `DiagramAgent` graph. `LLMDiagramProvider` asks `DIAGRAM_LLM_MODEL` for a bounded JSON/Mermaid specification, performs one correction retry for malformed local-model formatting, and accepts only allowlisted diagram declarations and passive source within size/line limits. The provider is behind `DiagramProvider`; the application owns routing, validation, persistence, and lifecycle events.

Presentation creation and selected-slide feedback run through `PresentationAgent` and `LLMPresentationProvider` using `PRESENTATION_LLM_MODEL`. For creation, the specialist first returns a bounded `DeckOutline`; the provider then asks for one strict `PlannedSlide` at a time, compiles and checkpoints each partial `DeckSpec`, and releases the background model lease between those microtasks. Each planned slide can declare a concrete image brief plus a bounded priority. A deterministic application compiler owns coordinates, theme, editable object construction, stable slide/element IDs, and preservation of those visual briefs. After content planning, the durable worker selects at most `PRESENTATION_AUTO_IMAGE_MAX` highest-priority applicable slides, creates owned FLUX artifacts through the shared `ImageArtifactService`, and checkpoints each enriched specification so the browser can display visuals before final rendering. The current single-RTX-5080 profile defaults to one 1024-by-1024 hero image; operators can change both limits, and users can add or refine imagery per slide afterward. Image-provider failure is best-effort and leaves the editable text deck promotable. This keeps the model focused on content, makes progressive state durable, and gives waiting chat requests a preemption point without interrupting an in-flight generation. For feedback, the specialist receives only the selected slide and returns a strict `SlideEdit`; the application replaces only that stable slide ID and preserves all siblings exactly. Each model contract gets at most one bounded correction attempt.

The browser derives an honest step-weighted completion percentage from the
durable job's expected slide count, partial specification, declared visual
briefs, attached image elements, and configured automatic-image budget. It
shows named outline, slide-planning, visual-generation, and render/validation
stages, survives navigation or reload through the stored job handle, and
disappears only after terminal promotion or failure. This is completed-work
progress rather than a wall-clock estimate. Text planning and FLUX execution
remain serial on the current workstation because vLLM and ComfyUI share
one RTX 5080 and both qualified provider paths have concurrency one; safe
pipeline overlap requires a separate GPU or a capacity-aware resource lease.

The separate port-8002 renderer accepts only a validated `DeckSpec`. PptxGenJS creates native editable text, shape, chart, table, image, and notes objects; a Python OOXML inspector confirms slide count and required native-object kinds; and the worker opens the file through headless LibreOffice Impress and exports a PDF as an Office-readability check. The renderer uses an isolated temporary directory and removes it after each serialized job. The application writes the PPTX through the opaque binary store and promotes the pending revision only after both structural and Office validation succeed. A failure remains terminal on the pending revision and does not replace the prior current revision.

The maintainer-only architecture candidate command uses the same agent/provider boundary but remains outside the HTTP runtime. `ArchitectureCandidateService` reads the registered canonical source plus only explicitly selected, bounded repository text. The CLI requires a loopback model endpoint, currently `vllm-main` on port `8003`; rejects traversal, common secret-bearing names, unsupported types, existing outputs, and canonical output paths; can require implementation-backed visible labels with one bounded semantic correction; and invokes the pinned Mermaid renderer. Output is a new review candidate only. Technical and visual review, followed by an explicit manual canonical edit or promotion, remains mandatory because label presence and syntax cannot prove relationship accuracy.

`backend/embeddings/lm_studio.py` retains its compatibility filename but implements the provider-neutral OpenAI-compatible `/v1/embeddings` boundary used by `vllm-embedding`. Nomic document/query task prefixes are applied and the configured 768-value dimension is validated before persistence or search. The provider also supports a batch `embed_texts` call that embeds many documents in one request with index-ordered reassembly; knowledge ingestion uses it so a multi-chunk document embeds in a single call instead of one request per chunk. A chat turn embeds the query exactly once and reuses that vector across personal semantic, entity, knowledge, procedure, summary, and toolbox retrieval rather than re-embedding the same query per store. The same vector is stored on the turn itself, so what the user said is searchable later without a second embedding call.

Prompts that decide answer quality live in `prompts/` as text files rather than as Python constants, loaded by `backend/core/prompts.py`. Each file is editorial notes, a separator line, then the text sent to the model, so the wording can be tuned and reverted on its own by someone who does not want to open a service module. The file is the only copy: a missing or empty prompt fails at startup rather than falling back to wording nobody is reading, and a placeholder the caller does not supply raises rather than reaching a model as a literal brace. The reply prompt, the routing decision and the three search prompts are there; `prompts/README.md` indexes the rest, which remain module constants. Each tool's own description deliberately stays beside the tool in `MainActionSelector`, because that single wording serves both the routing decision and what the assistant tells the user it can do.

Recall searches the conversation turns beside the promoted memories, and that is a deliberate correction rather than an addition. Only what `MemoryProposalAgent` promoted into semantic memory used to be reachable, and an account with fourteen stored conversations had zero promoted rows: the classifier captures attributes and misses circumstances, so its judgement - made at write time, about unbounded categories - decided permanently what could ever be remembered. Embedding the turn moves that judgement to recall time, where the question is in hand and relevance needs no category to have been anticipated. The classifier still writes the profile; it is no longer the gate on what is rememberable.

Recalled turns are rendered separately from personal memory, because a promoted fact is something the application asserts and a recalled turn is something the user said and may since have stopped meaning. Two filters are applied where the text is readable rather than in SQL, since `conversations.query` is encrypted at rest: a turn that is itself a question is dropped, because it embeds closer to a new question than the statement that answers it, and identical repeats collapse so one interest stated three times cannot spend every slot. The distance is `MEMORY_RECALL_TURNS_MAX_COSINE_DISTANCE`, measured rather than inherited - the 0.35 tuned for short curated facts does not transfer to a spoken sentence - and `MEMORY_RECALL_TURNS_ENABLED` disables the whole path without a redeploy.

### Persistence

SQLAlchemy models exist for conversations, profiles/facts, episodic/semantic memory, safe tool memory, semantic cache, working memory, procedures, entities/relations, knowledge documents/chunks, conversation summaries, visual artifacts, presentations, append-only presentation revisions, and durable presentation jobs. Persistence has the following implemented boundaries:

- all models use `backend.database.session.Base`;
- Alembic targets that metadata; revision `20260802_0024` adds independent unique
  account login names on top of the invite-account and revocable-session tables
  in `0023`; head `20260802_0025` adds one-time registration invitations. Every
  revision is additive across the earlier discovery,
  presentation, artifact, memory, tool-memory, and pgvector history;
- FastAPI, conversation, memory, coordinator, and operational paths use injected SQLAlchemy `AsyncSession` transactions through `asyncpg`;
- runtime uses a bounded async queue pool, while the synchronous psycopg2 engine is retained only for Alembic and explicit inspection/test utilities;
- episodic and semantic writers map caller metadata to the models' `extra_data` columns;
- semantic embedding and cosine-distance retrieval are operational through the injected provider;
- every current user-owned memory table participates in JSON export and delete-all; knowledge documents also have a scoped individual deletion path.

PostgreSQL transaction advisory locks serialize natural-key writes. An async acceptance test runs six real PostgreSQL waits through a two-connection bounded pool while an event-loop heartbeat continues; it verifies a peak of two checked-out connections and complete pool drain. Transaction-abort and pool-timeout tests prove rollback/reuse and checkout recovery. The shared embedding adapter retains a configurable in-process concurrency limit; increase it only after mixed-load acceptance against the deployed vLLM profile.

An opt-in Compose maintenance service applies retention, optionally refreshes stale vectors, performs final inspection, emits non-content JSON monitoring events, and continues after transient interval failures. The operations API also exposes Prometheus-compatible counts, expiry backlog, stale vectors, invariants, database latency, and a binary health gauge. A configurable live soak mixes chat, working-memory reads/writes, and health inspection through the public API and cleans its isolated user afterward.

PostgreSQL and pgvector persist all durable and expiring memory forms. Vector stores use 768-dimensional embeddings with HNSW cosine indexes; retrieval applies user scope, approval/active/expiry filters, cosine-distance thresholds, and result limits before prompt use. Oracle-specific IVF helpers are not used: schema and indexes are owned by SQLAlchemy metadata and Alembic.

Invited authentication keeps a unique login name separate from
the stable `user_id` that owns chats, memory, discovery rows, artifacts, and
jobs. The operator can create an account through a private password prompt or
mint an expiring one-time registration code. Only the invitation digest is
stored. `POST /auth/register` locks and consumes one valid invitation while
creating the normalized account and first session in one transaction; the
browser never supplies a separate owner ID.
`POST /auth/login` verifies the submitted password, creates a random opaque
token, persists only its
SHA-256 digest, and sets a host-only HttpOnly browser cookie. The async auth
dependency resolves unexpired, unrevoked sessions to the stable owner before
any owned handler runs; logout, password replacement, and account disable
revoke sessions. Login and registration admission use shared Redis attempt
windows and fail closed when that protection is unavailable. Unsafe
cookie-authenticated requests additionally require an
allowlisted Origin. Legacy expiring HMAC bearer tokens remain available for
local automation. Trusted-local `AUTH_REQUIRED=false` deliberately returns the
configured local owner and is not suitable for public ingress.

The production-style local web boundary is a loopback-only Nginx container on
port 8080. It serves the compiled React application and proxies `/api` to
FastAPI on the same origin with buffering disabled for SSE and bounded
upload/download timeouts. Vite on port 5173 remains a development path. A
public TLS tunnel is not configured; future ingress must expose only this
gateway and keep every database, model, media, renderer, and MCP port private.

The model vector type follows the validated `EMBEDDING_DIMENSION` setting. Offline dimension changes use resumable `embedding_next` shadow columns across semantic memory, cache, procedures, entities, knowledge chunks, summaries, and tool descriptors. Batches commit without replacing the authoritative old vectors; after all shadow rows validate, one PostgreSQL transaction locks and switches every pending table, updates embedding metadata, and rebuilds each HNSW cosine index. Provider/backfill failure therefore leaves old vectors usable and the shadow work resumable.

## Frontend

The React frontend begins at an invited sign-in/profile-creation screen when
authentication is required and does not mount private product views until
`/auth/session` returns
the server-derived owner. It contains a responsive light-neutral shell with search-first Chat, Personal Memory, Visual Artifacts, and Presentations views. Empty chat centers one dominant query composer; active chat presents each user query and assistant response as a left-aligned result flow rather than opposing message bubbles. Request trace/conversation identifiers remain available through an answer-level three-dot metadata popover instead of the primary answer text. The native font stack selects SF Pro through the Apple system aliases where available and the platform `system-ui` font elsewhere; the composer explicitly inherits that same stack. The memory screen explicitly applies user changes, cancels obsolete reads, edits profile/preferences, lists and deletes records, confirms delete-all, keeps manual event/fact creation behind an advanced plain-language disclosure, and renders live counts for every implemented short- and long-term memory form. Chat validates text, memory, search, MCP tool, image, and artifact SSE lifecycles; each tool shows running, succeeded, refused, or failed state without exposing arguments or results. Assistant text is rendered as styled CommonMark through ReactMarkdown with raw HTML interpretation disabled, while user messages remain literal text. Chat lazily loads Mermaid only for ready diagrams, renders under strict settings with HTML labels disabled, exposes editable source, and shows generation/render failures. The Artifacts view lists recent owned ready diagrams, reuses strict rendering, downloads Mermaid or the locally rendered SVG without another provider call, exposes refresh/load failures, and deletes owned records. The Presentations view lists persisted decks, creates a deck from a brief, shows reconnectable named-stage progress plus the latest partial slide, previews the promoted typed specification in a main canvas and thumbnails, applies feedback only to a selected slide, displays append-only revision history, downloads a named `.pptx`, and exposes loading and failure states. The browser persists only per-owner conversation and presentation job IDs across reloads; it keeps the in-memory transcript mounted across view switches, restores a bounded owned transcript and its diagram artifacts after a full reload, rotates it through `New conversation`, and clears the visible transcript when the authenticated owner or conversation changes.

Trusted-local mode uses configured owner `ani.mallya` without a login. It is a
single-user development convenience, not authentication, and must not be
exposed through a public ingress.

Presentation feedback revisions carry the selected stable slide ID. The browser
uses that public association and encrypted feedback summary to reconstruct a
separate chronological follow-up conversation for each slide, including
pending, ready, and failed outcomes. Switching slides changes the visible
thread; navigating away and back reloads the same persisted conversation.

Conversation selection/history browsing and configuration screens are not implemented; reload restoration currently targets the active locally stored conversation ID.

## Automated validation

Backend tests cover OpenAI-compatible chat/embedding contracts, streaming, bounded same-user chronological history, supervisor routing/delegation, coordinator routing/caching, rolling summaries, every typed memory API, diagram and presentation agent validation/lifecycle/routing, repository candidate boundaries, retention, re-embedding rollback, concurrency, operational inspection, PostgreSQL/pgvector persistence, scoping, export, and deletion. Playwright covers deterministic chat/memory/diagram/presentation workflows and separately gated live local-model/Nomic acceptance, including visible specialist/model activity and persisted real-model Mermaid and PowerPoint artifacts. There is no component-test framework.

The intended validation layers are:

| Layer | Status | Responsibility |
| --- | --- | --- |
| Backend unit and integration tests | `SCAFFOLDED` | Validate service behavior, API boundaries, streaming, and persistence with controlled dependencies |
| Frontend component tests | `PLANNED` | Validate rendering and interaction states in isolated components |
| Automated browser tests | implemented | Playwright covers chat success/failure, safe semantic Markdown rendering, diagram and presentation success/failure, selected-slide revision, download naming, navigation retention, conversation identity, memory management, and loading cleanup |
| Live-provider acceptance | implemented opt-in | Proves main-model streaming, typed presentation delegation with visible model provenance, persisted diagram rendering, and same-conversation recall plus Nomic persistence, reload, recall, and deletion |

Deterministic browser tests should use a controlled backend or fake LLM response for repeatability. That proves application behavior, not live-model connectivity; live-provider verification remains a separate acceptance layer.

## Intended conversation flow

The current scaffold expresses this intended flow:

```text
Frontend -> POST /api/v1/chat -> FastAPI dependency assembly
         -> ConversationService -> follow-up resolver (one reading of "this")
         -> MainActionSelector
         -> (search_web | generate_image | edit_image | show_image | discuss_image | create_diagram
             | delegate_to_presentation_agent | search_history
             | schedule_task / manage_tasks / scout_schedule | a taught skill
             | a toolbox tool | none),
            the main model's own native tool-calling decision

no action / search_web / toolbox tool -> MemoryCoordinatorAgent -> typed stores
         -> curated memory context -> LangGraph
         -> conversation repository -> streamed response

delegate_to_presentation_agent -> agent_started(PresentationAgent, model)
                              -> durable PostgreSQL job -> presentation worker
                              -> agent_finished(queued) -> chat remains available

create_diagram -> ConversationService -> DiagramArtifactService
                         -> pending artifact -> DiagramAgent -> local provider
                         -> validated Mermaid source -> ready/failed artifact SSE
                         -> strict in-browser SVG rendering

generate_image / edit_image -> ImageArtifactService / ImageRefinementService
                         -> pending artifact (artifact_started) -> ComfyUI FLUX
                         -> ready/failed artifact (artifact_ready/artifact_error) SSE
show_image               -> referent resolution over the user's own pictures
                         -> the existing artifact re-streamed as artifact_started
                            + artifact_ready (the web fills the card it opened, the
                            iMessage worker attaches the photo); an ambiguous
                            match asks which, with image_matches to choose from
                         -> conversation turn persisted, unlike the direct REST
                            endpoints these replace for chat-initiated requests

Presentation brief -> PresentationService -> pending revision
                   -> PresentationAgent -> compact semantic plan
                   -> deterministic editable DeckSpec plus ranked visual briefs
                   -> bounded FLUX enrichment of applicable slides
                   -> PptxGenJS -> OOXML and LibreOffice validation
                   -> opaque PPTX write -> ready revision promotion

Selected-slide feedback -> PresentationAgent -> strict SlideSpec
                        -> application-owned sibling-preserving merge
                        -> the same validated render and promotion path

Architecture maintenance -> explicit repository evidence -> ArchitectureCandidateService
                         -> DiagramAgent -> validated candidate Mermaid and SVG
                         -> technical/visual review -> manual canonical update
```

Current runtime validation completes this flow through the qualified main and specialist roles, a bounded same-user history window, and personal memory. Current evidence is recorded in [NEXT_SESSION.md](NEXT_SESSION.md).

## Capability boundaries

- Personal profile, episodic memory, relevance-gated semantic search,
  management/export/correction/deletion UI, and invite-only password
  authentication: functionally implemented; the current local runtime has auth
  enabled and the primary account is provisioned.
- Local knowledge-document ingestion, deterministic chunking, embedding, semantic retrieval, prompt curation, export, and deletion: implemented. Hybrid retrieval, reranking, source-citation policy, file connectors, ingestion jobs, and GraphRAG remain `PLANNED`.
- Server-derived route ownership, one-time invited browser registration,
  Argon2id password login, shared attempt limits, revocable HttpOnly sessions,
  logout, and operator CLI account lifecycle: implemented and API/browser
  verified. Unrestricted public signup, account recovery, MFA, browser
  administration, and external identity providers remain `PLANNED`.
- Deterministic internet routing, outbound privacy minimization/blocking,
  Google-first/Tavily-fallback MCP research policy, request-scoped cloud-worker
  isolation, non-content daily quota, untrusted prompt attribution,
  provider-attributed source cards, visible failure state, and explicit
  referenced-image search enriched only with a screened bounded description:
  implemented. Tavily fallback is direct/live-browser verified; the Google
  branch is deterministically verified but a real Google request is
  `UNVERIFIED` until a key is configured. Sensitive-query review, redacted
  audit storage, and provider hardening remain `PLANNED`.
- Explicit Mermaid diagram generation through a dedicated diagram graph, user-scoped lifecycle/history/deletion, strict rendering, reload restoration, local Mermaid/SVG export, and disconnect recovery: implemented and browser/direct-client verified. Free local raster generation, bounded upload, source-conditioned FLUX editing of generated or uploaded images, opaque binary storage, owned content/deletion, aligned multimodal image embeddings, Qwen image understanding, browser progress/retry/cancel, private rendering, navigation/reload restoration, history, download, and deletion are implemented and direct/live-browser verified. Threaded followup questions on owned generated or uploaded images reuse the stored bytes and the same vision boundary with a bounded, persisted question/answer thread; deterministic browser/backend coverage and a live local VLM call through the visual MCP facade are verified. Indexing the initial upload analysis into semantic memory, so an uploaded image's content is recalled by an ordinary conversation turn, is implemented and live-verified; indexing the interactive follow-up thread remains `PLANNED`. The same diagram, image, followup, and artifact-status services are exposed through a confirmed, metadata-only local FastMCP facade; autonomous consequential-call approval/resume remains `PLANNED`. Review-only local Qwen architecture candidates remain implemented and never update canonical source automatically. Automated binary retention/export, durable diagram/image queues, GPU resource leasing/transitions, and generalized image agents remain `PLANNED`.
- Editable PowerPoint generation through a focused presentation graph, a durable leased worker, PostgreSQL job state, reconnectable progressive drafts, a Redis foreground-chat priority gate, strict typed specifications, model-declared ranked visual briefs, bounded best-effort default FLUX enrichment, persistent per-slide feedback conversations, additional FLUX generation and refinement of an attached slide image, selected-slide-only changes, append-only revision history, PptxGenJS native objects, OOXML inspection, LibreOffice validation, opaque storage, browser previews, named download, deletion, and metadata-only MCP tools: implemented and direct/live-browser verified. Raster images inside a slide remain replaceable image objects rather than decomposed editable pixels. Importing arbitrary existing PPTX files, distributed GPU-capacity scheduling, source-grounded deck research/citations, template/master libraries, automated visual-diff review, and a minimum-readable-font visual quality gate remain `PLANNED`.
- Semantic safe-descriptor discovery, approved preference/sanitized outcome memory, stdio/streamable-HTTP connectivity, native main-model selection, live pre-invocation re-resolution, guarded execution, and UI lifecycle status: implemented. Automatic registry refresh/change notifications, consequential-call approval/resume, per-server user credentials/scopes, durable execution audit, A2A, and general multi-agent scheduling remain `PLANNED`; tool memory never authorizes execution.

## Architectural decision

Every decision record, its reasoning, and its status is catalogued in
[Part II](#part-ii---the-engineering-decisions-and-why) above, including the
reply graph ([ADR 0012](adr/0012-the-graph-answers-the-turn-it-does-not-run-it.md))
and the two open briefs on a capability registry (0013) and the embedding
models (0014). The summary that follows is the original index, kept for its
links. The project has adopted clean-architecture and dependency-inversion principles as a design direction. [ADR 0001](adr/0001-clean-architecture-and-modular-structure.md) records that direction. [ADR 0002](adr/0002-typed-agent-memory-manager-and-pgvector-indexes.md) records the typed store-manager/coordinator boundary and the pgvector HNSW indexing choice. [ADR 0003](adr/0003-local-visual-artifacts-and-resource-aware-orchestration.md) records the local-only visual-artifact, GPU-resource, and scalable orchestration direction; editable diagrams, raster generation and source editing, binary storage, upload validation, VLM analysis, aligned image retrieval, browser integration, and the local visual FastMCP facade are implemented while deterministic resource orchestration remains `PLANNED`. [ADR 0004](adr/0004-hybrid-free-tier-web-research.md) records the isolated Google research worker, Tavily fallback/cross-check, free-tier quota, and data-minimization boundary. [ADR 0005](adr/0005-typed-editable-presentation-generation.md) records the typed editable-presentation, focused-agent, durable-job worker, foreground-priority model gate, renderer, and validated-promotion boundaries. [ADR 0006](adr/0006-hybrid-supervisor-and-qualified-model-roles.md) records the typed hybrid-supervisor boundary, visible delegation provenance, role-specific local-model configuration, and acceptance-path-driven model promotion rule. [ADR 0007](adr/0007-versioned-visual-semantics-memory-and-editing.md) records implemented source-aware immutable editing plus planned generated-image observation, handle-based visual memory, semantic verification, and derived-data lifecycle boundaries. [ADR 0008](adr/0008-provider-neutral-inference-boundary.md) records the provider-neutral inference adapters, role-level configuration, and deliberate separation from runtime lifecycle control. [ADR 0009](adr/0009-vllm-default-local-inference-runtime.md) records the pinned two-service vLLM deployment, consolidated Qwen/Nomic role profile, GPU-safe startup order, and remaining resource-management boundary. [ADR 0010](adr/0010-invite-identity-and-revocable-sessions.md) records the stable-owner/login-name split and revocable server-side browser-session boundary. [ADR 0011](adr/0011-sharing-by-copy-on-accept.md) records the decision that sharing between accounts copies on accept rather than granting access into another owner's store, keeping the single-owner invariant that deletion, export, and every scoped query already depend on.
