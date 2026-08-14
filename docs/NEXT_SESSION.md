# AniOS Current Session Handoff

Frequently rewrite this file from fresh evidence. Verified history belongs in
[CHANGELOG.md](CHANGELOG.md), durable milestone status in
[ROADMAP.md](ROADMAP.md), and stable architecture facts in
[ARCHITECTURE.md](ARCHITECTURE.md).

Last updated: 2026-08-14, America/New_York

## DeepSeek vs Nemotron 3 Super evaluated head-to-head — genuinely mixed, no winner picked — VERIFIED

**Decision still open, deliberately not made this session.** Both models
were run through the identical three-part evaluation (tool-calling battery
x3, search-routing benchmark, real reply latency) with results pointing in
different directions - full numbers in `ROADMAP.md` Milestone 9:

| | DeepSeek-V4-Flash (ds4-server) | Nemotron 3 Super (vLLM) |
| --- | --- | --- |
| Tool-calling (63 cases) | ~90%, real haiku/limerick gap | **98.4% (62/63)**, no bias found |
| Search-routing recall | **0.8519** (passes 0.85 floor) | 0.7931 (fails the floor) |
| Search-routing specificity | 0.9565 | 1.0000 |
| Avg total reply time | **31.9s** | 57.6s |
| Avg time-to-first-token | **~0.4-1.0s** | ~17s (4.5-34s, highly variable) |

Nemotron wins tool-calling clearly; DeepSeek wins both routing recall and
felt responsiveness (its TTFT advantage matters more for perceived
speed than raw decode rate does). Neither clears every bar. **Only one can
run at a time on this Spark** (both need most of its 128 GB) - currently
Nemotron is the one loaded and running; DeepSeek's `ds4-server` was
stopped and its crontab `@reboot` entry removed to avoid a memory conflict
if the Spark reboots while Nemotron's Docker container (which does have
`--restart unless-stopped`, so it survives a reboot on its own) is what
should come back.

Real compatibility finding worth remembering regardless of which model (if
either) is ever promoted: vLLM rejects AniOS's `reasoning_effort="none"`
default outright for Nemotron (`400`, `"Input should be 'low', 'medium' or
'high'"`) - `ROUTING_LLM_REASONING_EFFORT`/`MAIN_LLM_REASONING_EFFORT` would
need an explicit value for this model, not the blank default.

Also from this session: `MainActionSelector`'s tool-calling model and the
conversational-reply model can now be configured independently
(`ROUTING_LLM_BASE_URL` etc., default-unchanged, see the entry below) - so
whichever model (if any) eventually gets promoted for one role does not
have to be promoted for both at once.

## Routing/reply split built and real latency measured: ~5x slower — VERIFIED

**Next planned step, not started:** evaluate NVIDIA's own Nemotron 3 Super
(120B total / 12.7B active) as a DGX Spark candidate instead of continuing
to invest in DeepSeek-V4-Flash specifically. Real search found it officially
supported on Spark with native vLLM + NVFP4 (not a bespoke third-party
engine), right-sized for 128GB, and leading its size class on the
Artificial Analysis Intelligence Index — a lower-risk bet on paper than
DeepSeek's community-maintained `ds4-server`. Not yet installed or tested;
no tool-calling evidence exists for it the way there now does for DeepSeek.

**What shipped this round:** `MainActionSelector`'s tool-calling model can
now be configured independently of the conversational-reply model
(`ROUTING_LLM_BASE_URL`/`MODEL`/`REASONING_EFFORT` in
`backend/config/settings.py`, wired via `get_routing_llm_client()` in
`backend/core/dependencies.py`). Falls back to `MAIN_LLM_*` when unset, so
this changes nothing by default — full 1175-test suite confirms it. Not
deployed to `docker-compose.yml`; this exists so a main-model swap for reply
quality doesn't have to also inherit that model's untested tool-calling
behavior wholesale.

**Real latency measured**, not estimated: sent the same four realistic
conversational prompts through the actual `build_assistant_graph`/
`stream_chat` code path (the literal function that streams a reply to a
user) on both Qwen and DeepSeek-V4-Flash. **Average 6.4s vs 31.9s — roughly
5x slower**, ranging 3-10x by query; full table in `ROADMAP.md` Milestone 9.
Time-to-first-token stays close for both, so DeepSeek doesn't feel stuck at
the start, but the reply visibly crawls in afterward.

Verified DeepSeek's chain-of-thought does not leak into what streams to the
user - read `stream_chat` directly, confirmed it only ever reads
`delta.content`. Chased down an apparently-garbled character in the raw
output to the exact byte and found it was a Windows-console `print()`
encoding artifact in the measurement script itself, not a real defect -
worth remembering so this isn't re-investigated from scratch later.

**Where this leaves the decision**: DeepSeek-V4-Flash's tool-calling is
genuinely decent (prior entry) and the routing risk can now be engineered
around via this split - but a ~5x reply latency cost is a real, separate
problem the split does not solve, since it's the model *generating the
words the user watches stream in*. Whether that tradeoff is worth it is
still an open, undecided call - not resolved by this entry.

## DeepSeek-V4-Flash tool-calling evaluated directly — encouraging, not yet sufficient — VERIFIED

**The actual question behind the whole DGX Spark thread**: is this engine's
native tool-calling reliable enough to ever justify `MAIN_LLM_BASE_URL`?
Answered with real evidence, not inference from the (failed) presentation
attempt: a standalone script built a real `MainActionSelector` pointed
directly at the Spark's `deepseek-v4-flash` endpoint, never touching the
running app's config. Full numbers and reasoning in `ROADMAP.md` Milestone 9
and `CHANGELOG.md`; short version:

- Search-routing benchmark (Qwen's own 52-case, 0.85/0.75 floor): **recall
  0.8519, specificity 0.9565** — passes, recall by under one case's margin.
- Every tool call made was valid JSON, no exceptions — better-behaved than
  the presentation schema failure, which needed a complex nested schema
  rather than tool-calling's flat arguments.
- Found and fixed a real gap: "write a haiku about rain" called
  `generate_image` instead of just writing it. Fixed generically (poem/
  story/description all now correctly stay text), verified against the
  *live* Qwen model too with no regressions — this fix is real and kept
  regardless of what happens with DeepSeek. A more aggressive second attempt
  at the same fix was tried, made things worse elsewhere, and was reverted -
  worth remembering as a concrete example of the overfitting risk, not just
  an abstract warning.
- **Residual, disclosed gap**: haiku and limerick specifically stayed
  materially unreliable even after the fix (4/8 and 2/8), against ~100% for
  every other case. This looks like a strong, specific training-data prior,
  not a general problem — but it is real and unresolved.

**Net position**: more encouraging than the presentation result, on real
numbers rather than optimism, but not enough to promote to
`MAIN_LLM_BASE_URL` yet. The evidence base is single-digit repeats per case.
Next step, not yet started: more repeated runs for a real confidence
interval, and a judgment call on whether the haiku/limerick-class gap is
acceptable for a model that will field creative-writing requests routinely.

Evidence: full backend suite (1175 tests) passes; Ruff passes. New permanent
test (`test_a_request_to_write_about_a_visual_subject_does_not_generate_image`)
covers the reliably-fixed cases only, deliberately not the still-flaky ones.

## Presentation role reverted to Qwen; a real, pre-existing token-budget bug found and fixed — VERIFIED

**Read this first if the entry below (DeepSeek on the Spark) looks stale.**
The user's actual first real request through the DeepSeek-on-Spark setup
failed: `pydantic.ValidationError`, `extra_forbidden` on fields like
`statistic` (schema wants `statistic_value`/`statistic_label`) — the
model's JSON was well-formed, just not in AniOS's exact field names.
`PRESENTATION_LLM_BASE_URL`/`PRESENTATION_LLM_MODEL` are back on
`vllm-main`/`qwen/qwen3.5-4b` in `docker-compose.yml`. `MAIN_LLM_BASE_URL`
was never touched either way.

Regenerating the user's exact prompt against the reverted Qwen config to
confirm the revert worked **also failed, 2 of 3 attempts** — a different
symptom (truncated JSON), a different cause: `PRESENTATION_PLAN_MAX_TOKENS`
defaulted to 2,048, and this prompt's real outline needed close to that.
**This is a real bug that predates any Spark work** — it would have hit
Qwen alone, on the original deployment. Raised the default to 4,096 in
`backend/config/settings.py`; 3 of 3 identical attempts succeeded after.
Both fixes needed a full `docker compose build` (not just `up -d` — this
one is source code, `anios_backend` does not bind-mount) +
`docker restart anios_gateway` (per the stale-DNS trap two entries below),
verified through the actual gateway path each time this time, not a
container-internal shortcut.

Currently evaluating, separately, whether DeepSeek-V4-Flash's native
tool-calling is reliable enough to ever justify promoting it to
`MAIN_LLM_BASE_URL` — the user's own framing was "maximize the intelligence
of the main model and its subagents," and the presentation schema failure
is directly relevant evidence pointing toward caution there, not away from
it. Results not yet in as of this write-up; look for a following entry or
check `git log` if this note is stale.

Evidence: full backend suite (1175 tests) passes; Ruff passes. Verified
through the real `LLMPresentationProvider` code path at production
settings — 3 consecutive real generations of the exact prompt that
originally failed, not a mock or a single lucky run.

## DeepSeek-V4-Flash now serves AniOS's presentation role, on the Spark — VERIFIED

A DGX Spark joined the network (`spark-b524.local`, GB10, 128 GB unified
memory) alongside the RTX 5080 already serving `vllm-main`/`vllm-embedding` —
addition, not replacement. Full access, the dashboard tunnel, and the
DeepSeek-V4-Flash install/serving details (including two real bugs found and
fixed — loopback-only binding, no reboot supervision) are in
[DEVELOPMENT_GUIDE.md](DEVELOPMENT_GUIDE.md#available-hardware-nvidia-dgx-spark).
Full story and evidence in
[ROADMAP.md](ROADMAP.md#milestone-9-local-inference-on-the-dgx-spark--in-progress).

**What actually changed in the repo:** `docker-compose.yml` —
`PRESENTATION_LLM_BASE_URL`/`PRESENTATION_LLM_MODEL` now point at
`http://spark-b524.local:8888` / `deepseek-v4-flash` for the `backend`,
`presentation-worker`, and `local-capabilities` services. `MAIN_LLM_BASE_URL`
and `MainActionSelector` were deliberately left untouched — the risk there is
the routing regressions this session already spent significant effort
chasing on the RTX 5080's model, and that risk was not taken on today.

**Verified how, and how not:** not by checking the endpoint responds — by
running the actual `LLMPresentationProvider` code path
(`get_presentation_llm_client()`) and confirming it returns a real,
non-repeating, ungrounded-statistic-free 3-slide deck. Direct
`/v1/chat/completions` call also checked by hand to confirm no leakage from
an unrelated `base_instructions` field the `/v1/models` endpoint carries (a
Codex-CLI-compatibility feature of the serving engine, confirmed harmless —
detail in `DEVELOPMENT_GUIDE.md`).

**What was not done:** `qualify_models` was not run against this model, and
its tool-calling behavior has never been tested — the presentation role
never calls a tool, so nothing here says anything about whether this model
could ever safely sit behind `MAIN_LLM_BASE_URL`. Sustained/concurrent
throughput was not measured either, only a single cold request
(~5.7 tok/s decode) — real, but not necessarily the number under load.

## edit_image opinion-question fix broadened after a real recurrence — VERIFIED, residual gap disclosed

**Read this if a picture gets edited when the user only asked a question about it.**
The first fix (below) patched the exact reported phrase ("which hat do you
like better") and shipped. The very next report, "do you recommend a straw
hat instead?", was the same underlying bug in different words, and it still
fired `edit_image`. **The lesson, stated plainly because it nearly repeats:**
a functional test that passes on the one phrase from the bug report proves
nothing about the general case — verify a batch of differently-worded
phrasings together, not the reported one in isolation.

Rewrote `edit_image`'s tool description in `main_action_selector.py` around
the actual rule (a question is never an instruction, no matter what
alternative it names) instead of enumerating comparison phrasings, and
added a parametrized test with four different opinion phrasings that must
*all* pass together. Result: 24/24 across six independent runs (up from a
single reported phrase). While iterating, discovered — via `git stash`
against the wording already live, not something this session introduced —
that "let's edit this project plan to push the deadline back a week" was
already misfiring into `edit_image` about half the time, unrelated to the
opinion-question bug. Reduced to roughly 1/6 with an explicit "even when no
other tool fits — answer directly instead of calling any tool" clause, but
**not eliminated**; expect this exact phrasing to resurface. Also: the
search-routing recall floor test failed once mid-iteration, then passed
clean on three immediate reruns with nothing changed — treated as noise
near this benchmark's known floor, not a regression, but flag it if it
recurs since the two look identical in a single run.

Full backend suite (1175 tests) passes; Ruff passes. No frontend change, so
only `docker restart anios_backend` was needed, not a gateway rebuild.

Separately, confirmed (not this session's doing) that the user's own browser
called `DELETE /api/v1/memory/ani.mallya` around 21:10 UTC on 2026-08-13,
wiping that account's full conversation/memory/artifact history — verified
via the gateway's real access log (genuine Chrome UA, real external IP, not
test traffic). Worth knowing if a "wipe memory" UI action is meant to be
scoped to memory only: the endpoint (`DELETE /api/v1/memory/{user_id}`,
`backend/memory/repository.py::delete_all_user_memory`) also deletes the
`conversations` table for that user, i.e. full chat history, not just
recall facts. Not changed this session since it wasn't confirmed to be
unwanted behavior — flagging for a product decision, not filed as a bug.

## An edit no longer echoes an unasked description, and stopped re-editing on an opinion question — VERIFIED (mostly)

**The description leak** was reported live: "can you edit this to a straw
hat?" edited cleanly, but also surfaced an unrequested "Describe this image"
card underneath it. Root cause: `ImageRefinementService.refine` calls
`VisionAnalysisService.observe_artifact` after every edit purely so the
revision stays semantically findable (this was added in an earlier session
to fix edited images being unrecallable) — but that write lands in the same
`metadata.analysis` key the *upload* flow uses when the browser's
caption-less default question is answered, and the frontend's
`readAnalysisThread` legacy fallback (`frontend/src/services/api.ts`) cannot
tell the two apart: `analysis` set with no `analysis_thread` always renders
as a "Describe this image" card. Fixed by marking the reindex-only write
`analysis_user_facing: false` and having the frontend check that flag before
falling back to the legacy display. Confirmed with a real repro: the new
Playwright test fails against the unfixed `api.ts` (analysis text visible)
and passes against the fix; `test_vision_memory_indexing.py` asserts the new
flag directly.

**The re-edit-on-opinion bug**: pulled the actual trace (conversation
`3d463775`, 2026-08-13 19:51–19:54) straight from the database rather than
guessing. After the model described a black cowboy hat and it was edited to
straw, "amazing! which hat do you like better for this outfit?" made
`MainActionSelector` choose `edit_image` again, synthesizing a paraphrased
instruction ("Replace the black cowboy hat with a straw hat") that silently
redid the same edit — the response was "Here's the edited image.", not an
answer to the comparison. The user resent the identical message 8 seconds
later and that time got a real comparative answer, once the botched edit was
sitting in history. **Worth remembering:** my first guess at which tool
misfired was wrong — I assumed `generate_image` from "it starts regenerating
another image," wrote a description fix and a test for that tool, and only
the direct database trace (`extra_data.refinement_feedback` on the two
generated-image rows) showed it was actually `edit_image` re-firing. Reverted
the `generate_image` change before committing. Clarified `edit_image`'s own
tool description (not the shared `_SYSTEM` prompt, per the established
lesson that widening that degrades search-routing recall) to exclude an
opinion/comparison/preference question about the picture, even when it names
the same subject a recent edit changed. **Caveat, same shape as the location
fix below:** a functional test replays the live trace verbatim, but could
not be forced to fail again against the unfixed description (12/12 passed)
— treat as a sound, best-effort guardrail, not a proven fix, if this
recurs. The full `test_main_action_selector_behaviour.py` suite (17 tests,
including the search-routing recall floor) stayed stable across three runs
with the fix in place.

Evidence: full backend suite (1175 tests) passes; Ruff passes on every
changed file.

## The gateway was a day-stale static build; recall showed one photo three times — VERIFIED

**Read this first if a "fixed" frontend change is reported as not working.**
`gateway` (port 8080, what the tunnel/deep-matter.com actually serves) bakes
`frontend/dist` into its nginx image once at Docker *build* time and never
watches the source tree again — `docker restart` or `up -d` alone changes
nothing. It was found a full day stale, meaning an entire session's worth of
frontend fixes had been invisible to the user throughout, and every hard
refresh they tried was correctly fetching fresh bytes of the same stale
build (`Cache-Control: no-store`, so it was never a browser-cache problem).
Redeploy with `docker compose build gateway && docker compose up -d
--no-deps gateway`, and verify with content, not timestamps —
`docker exec anios_gateway grep -l "<string only in new code>"
/usr/share/nginx/html/assets/*.js`. Documented in `AGENTS.md`'s Operational
traps. Separately, even after a real gateway rebuild, one more report turned
out to be a stale open *browser tab* specifically (confirmed by reading the
exact persisted response text back out of the database, which proved the
extra text the user saw was never generated server-side) — a tab keeps
running its already-loaded JS regardless of the server, until it is actually
reloaded.

With the deploy pipeline no longer the confound, a real bug surfaced:
asking a style question recalled the same uploaded photo three times as
three separate "matches." Not a selection bug — the same file had genuinely
been uploaded across three separate conversations while testing, so three
real, independent, `sha256`-identical rows all legitimately matched. Added
`collapse_duplicate_content` in `backend/artifacts/image_lineage.py` (a
sibling to the existing `collapse_revision_chains`, but for independent rows
provably the same file rather than a parent/child edit chain) and wired it
into both image-recall paths. Full backend suite (1175 tests, 5 new) passes;
Ruff passes. No frontend change this round, so no gateway rebuild was
needed — only `docker restart anios_backend`.

## Dark-mode white bar fixed; the model stopped inventing a location — VERIFIED

Two more reports from the same live-testing thread. **The dark-mode bug** was
a real gap in `theme.css`'s hand-maintained `.dark` overrides: an
opacity-suffixed colour (`bg-[#f5f5f7]/90`, the composer bar's blur
background) and a `hover:`-prefixed one each compile to their own distinct
Tailwind class, so mapping the plain colour does not cover them — the
composer bar stayed solid white. Fixed both, swapped two more unmapped
colours for already-covered equivalents, and added a `theme.spec.ts` test
that reads the actual computed `background-color` (confirmed it fails
unfixed first). **Worth remembering:** this hand-maintained file's own header
comment claims "a test reads the palette, scans the components, and fails
when one is unmapped" — that test does not exist anywhere in the repo. Any
new arbitrary-colour Tailwind class, especially with an opacity suffix or a
`hover:`/`focus:` prefix, should be checked against `theme.css` by hand until
that real generator/validator gets built.

**The location hallucination** ("Do you have a preferred proximity to a city
(like Milwaukee, where you seem based)", asked of a freshly wiped account
with zero stored profile/facts/locality and no search having run) was traced
conclusively to the text-generation call itself, not routing — confirmed via
the trace (no search call) and the database (no stored fact named a city).
Added an explicit instruction to `_build_system_prompt` in `graph.py`: never
present a guess about the user's own personal facts as if it were known.
**Caveat, stated plainly:** the new functional test
(`test_it_does_not_invent_the_users_location`) could not be made to
reliably fail against the unmodified prompt (4/4 attempts passed) — this
looks like real-model non-determinism at the edge of a large shared prompt,
not something fully under this repo's control. The instruction is kept
because it is a sound guardrail on its own merits, but treat this fix as
best-effort, not proven, if the report recurs. A genuine side effect:
`test_style_opinion_applies_the_edit_to_the_source_description`, previously
`xfail(strict=True)` for a known Qwen limitation, now XPASSes consistently
(3/3) — the xfail marker was removed.

Also confirmed (no code change) that the earlier `/images/intent` bypass and
stale-`artifact_started`-validation reports are both actually resolved on
current code — a fresh trace for a repeat of the same message went through
`/api/v1/chat` correctly end to end. Remaining sightings of either are a
stale browser tab, not a live bug.

Evidence: full backend suite (1170 tests) passes; Ruff passes on every
changed file; `tsc && vite build` passes; `theme.spec.ts` (6 tests, 1 new)
and a full `chat.spec.ts` run (56/59, same three pre-existing failures
confirmed via `git stash`) both pass.

## Recalled photos display compactly; editing explains a missing target — VERIFIED

Direct follow-up feedback on the same day's "keeps showing the image" fix
below: the dedup was the wrong fix. The user's actual complaint was the
*size* of the card, not the repetition — "is it feasible to have it show 1
matching image every time it references it? the uploaded image card is
huge." Reverted the dedup entirely (`freshly_shown`, `_resolve_display`,
`_render_image_prompt_context`, and their tests all removed) and instead
gave `ImageArtifact` a `compact` prop: a recalled match now renders as a
small thumbnail chip that expands to the full 620px card with its
download/retry/delete toolbar on click, and collapses back on demand. Only
`MessageBubble.tsx`'s `imageMatches` path uses it — a freshly generated,
uploaded, or edited picture still shows full-size immediately, per the
user's own framing ("the image comes with the full llm response on the
first time the image was created").

Two more real bugs surfaced in the same exchange, both fixed:

1. **Deleting an image silently disabled auto-follow for the rest of the
   conversation.** `handleVisualDeleted` reset `selectedImageId` to `null`
   when the deleted image was the active one — the same value a deliberate
   "clear image context" click uses (see the comment at its declaration:
   "null records that the user deliberately cleared image context").
   Deletion is not that choice. Changed to `undefined`, which resumes
   following the newest visible image automatically. Verified end-to-end in
   `chat.spec.ts`'s `keeps auto-following the newest image after deleting
   the active one`: generate, delete, generate a second image, ask a
   followup — the second image's id reaches `active_image_artifact_id`
   without any click.
2. **An edit request with nothing selected answered as if it were never
   asked.** `edit_image` was only ever offered to the model when the
   frontend already had an active image, so a message like "make it black
   and white" with nothing selected fell straight through to an ordinary
   reply that never mentioned a picture — reading as the feature being
   broken. `edit_image` is now offered every turn; `ConversationService`
   checks the real selection itself (the model cannot) and, when the model
   judged this an edit but nothing is active, replies with explicit
   guidance instead of guessing.

That second fix needed two real-model-measured prompt iterations, both
worth remembering for next time:

- A wordy exclusion example added to the *shared* `_SYSTEM` prompt fixed a
  genuine false positive (the real model calling `edit_image` on "edit my
  resume to remove my last job") but measurably dropped the search-routing
  benchmark's recall to 0.79 against its 0.85 floor. Confirmed causally: the
  clean tree passed, restoring the addition reproduced the drop. **Lesson:**
  this selector makes one shared decision from one shared prompt across
  every action; adding text to one tool's guidance can silently degrade an
  unrelated tool's accuracy, even in a short, seemingly-isolated addition.
- Moving the identical clarification into `edit_image`'s own tool
  `description` field (not the shared instructions block) fixed the false
  positive with no measurable effect on search routing — three consecutive
  real-model benchmark runs all passed. Prefer the tool's own description
  field over the shared system prompt when a per-tool correction is needed.

Evidence: full backend suite (1170 tests) passes; Ruff passes on every
changed file; `tsc && vite build` passes; non-live `chat.spec.ts` (59
tests, two new) passes. New real-model functional tests:
`test_an_edit_request_with_a_recent_picture_chooses_edit_image` and
`test_an_unrelated_edit_request_does_not_choose_edit_image` in
`test_main_action_selector_behaviour.py`, run 3x for the search-routing
benchmark specifically to confirm the fix held. Four pre-existing e2e
failures (dark-mode color assertion, diagram-reload timeout, one flaky
`net::ERR_FILE_NOT_FOUND` console error, a "Sign out" click racing a
detached DOM node) confirmed present on unmodified `HEAD` via `git stash`
and unrelated. Diagram impact: NONE — internal refinement to existing
components, no new component/store/boundary.

## Chat memory proposals auto-save; a recalled photo stops repeating — VERIFIED

Two independent requests this session: "automatically save things about a
user in memory without asking them... it may become bothersome" (design
decision: blanket auto-save, chosen over tiered-by-confidence when offered
the choice), and, from a live look at `ani.mallya`'s real conversation
history, "it keeps showing the image every time it says it recalls it" plus
a reported "Artifact start event is invalid" error.

**Auto-save.** Every proposal `MemoryProposalAgent` classifies from a chat
turn is now persisted by `ConversationService._persist_memory_proposals`
immediately, before the reply is generated — no approval round-trip, for any
of the nine kinds the agent actually emits (`preferred_name`,
`response_style`, `discovery_locality`, `discovery_interests`, `entity`,
`procedure`, `knowledge`, `semantic_fact`, `episodic`). A dispatch table
(`self._memory_proposal_savers`) maps each kind to its own `_save_*_proposal`
method, mirroring the exact calls the retired REST approval endpoints used to
make (`approve_preferred_name`, `approve_fact`, `approve_discovery_interests`,
`save_semantic_memory`, `save_episodic_memory` on `MemoryService`;
`entities.upsert`, `procedures.approve`, `knowledge.ingest` on
`AgentMemoryManager` — newly wired into `ConversationService` as
`agent_memory`, since it had no reference to it before and entity/
procedure/knowledge proposals had no persistence path at all). A per-item
save failure is caught, logged, and dropped — it costs only that one
candidate, never the turn's answer or any other candidate saved alongside
it (covered by `test_conversation_service_a_failed_save_does_not_block_the_rest`).
`_render_save_state` in `graph.py` now tells the model "the following was
saved" instead of "a save card is displayed, nothing is stored yet" —
verified against the real model in `test_memory_save_state_behaviour.py`,
which took two prompt revisions: the first "nothing was saved" wording still
produced "I've noted that ..." from the real model despite an explicit ban
on the word, and needed a worked positive/negative example to actually hold.
The frontend's whole approve/reject queue was removed (`ChatWindow.tsx`:
`saveMemoryProposal`, `approveMemoryProposal`, `approveAllMemoryProposals`,
`rejectMemoryProposal`, the turn-based retirement grace period and its
`turnRef`; `api.ts`: the ten `approve*` REST wrapper functions) and replaced
with a read-only "Saved X as Y memory" notice that clears on the next
question — nine `chat.spec.ts` tests were rewritten from
approval-button-click assertions to auto-save display assertions.

**Repeated image display.** Root cause, found by decrypting and reading
`ani.mallya`'s actual conversation rows in the dev DB (read-only, via the
running backend's own `FieldCipher` — see `backend/core/crypto.py`):
`_load_visual_memory_matches` is a real semantic-recall model call (not
regex) that correctly judges relevance on every turn merely *about* what a
stored photo shows — so a multi-turn conversation about one outfit
re-attached the same photo to almost every reply, true in isolation, noisy
in aggregate. Fixed in `_stream_retrieved_context`
(`conversation_service.py`): that semantic-fallback path is now deduplicated
against artifact ids this conversation already displayed, tracked via the
persisted turn's `extra_data.artifact_ids` (a new `context["shown_image_ids"]`
side-channel carries this from retrieval to the persist call). An explicit
recall ("show me that photo again") is never deduplicated — only the
soft/incidental path is. Each prompt image now carries a `freshly_shown`
flag; `_render_image_context` in `graph.py` was updated so the model never
claims a picture "just appeared" when it is a repeat.

**"Artifact start event is invalid".** Already fixed by the prior session's
`d849522` (widened the frontend's `artifact_started` kind validation to
accept `generated_image`, not only `diagram`). Confirmed live in the running
dev container: `docker exec anios_frontend` showed `api.ts`'s mtime already
reflected the fix before the reported chat turns happened. No new code
needed. If it recurs, it is almost certainly a stale browser tab from before
that fix — a hard refresh should clear it.

**Not done, flagged for later:** `backend/artifacts/image_recall_router.py`
(`CascadingImageRecallRouter`) and `image_routing.py`
(`ImageRecallPolicy`) are still regex-plus-narrow-classifier — the same
anti-pattern `MainActionSelector` replaced for search/image-generation/
diagram/delegation routing last session, but this one decides whether to
search the user's *own stored images* and was out of scope for today's two
reported bugs. It was not the cause of either bug (confirmed by tracing the
actual code path), but it is a standing violation of this repo's
"smartness over regex" mandate and a reasonable next target if the user
wants that architecture cleanup finished. See
[[anios-smartness-over-regex]] context in memory if resuming this.

Evidence: full backend suite (1170 tests) passes; Ruff passes on every
changed file; `tsc && vite build` passes; the non-live `chat.spec.ts` suite
passes (57 tests), including the nine rewritten memory-proposal tests and a
new `clears the saved-memory notice on the next question` test; three
pre-existing failures (a dark-mode `shellBackground` color assertion, a
diagram-restore-after-reload timeout, one flaky `net::ERR_FILE_NOT_FOUND`
console error) were confirmed present on unmodified `HEAD` via `git stash`
and are unrelated. `docs:diagram:check` reports all 19 diagrams
synchronized after editing `memory-overview.mmd`, `memory-subsystem.mmd`,
`chat-orchestration.mmd`, and `agent-memory.mmd` to remove the retired
"visible approval"/"Consent" gate nodes. Committed as `660229a` (image
redisplay fix, pushed) plus the auto-save change (commit pending at time of
writing — see git log for the actual SHA once pushed).

## Turn routing became one native tool-calling decision — VERIFIED

Two reports started this: a "suggestions for a bachata event tonight" request
returned results from unrelated cities with no location ever asked for, and a
"can you make me wear a straw hat here?" edit changed the picture with no
reply and no trace in conversation history. Both traced to the same root
cause — search routing, diagram detection, presentation delegation, and image
generation were each decided by a separate deterministic gate (a
regex-plus-classifier cascade, two plain regexes, and a browser-side keyword
regex) running before the model that actually answers the user ever saw the
request, and image generation/editing were client-triggered REST calls
invisible to `conversations`.

`MainActionSelector` (`backend/services/main_action_selector.py`) replaces all
four with one native tool-calling decision made by the main model itself:
`search_web` (live schema, model-authored query), `generate_image`,
`edit_image` (offered only with an image in view), `create_diagram`,
`delegate_to_presentation_agent`, and the user's own semantically shortlisted
MCP tools, offered together in a single `chat_with_tools` call. It refuses to
act on any name that round did not actually offer — defense against a
malformed or unexpected provider response, not just an offline concern.
`ConversationService.process_request` now calls it once and dispatches;
`generate_image`/`edit_image` run inside the chat stream through the same
`ImageArtifactService`/`ImageRefinementService` the retired REST endpoints
used, emitting the same `artifact_started`/`artifact_ready`/`artifact_error`
lifecycle a diagram already used — so the exchange is persisted and an edit
gets a visible reply where it previously got neither.

The routing prompt explicitly tells the model not to guess a missing personal
detail (concretely, location) and call the tool with an assumption; it should
call no tool instead, so the reply can ask. This is model behavior, not a
separate feature — there is no code path that detects "location is missing"
outside the model's own judgement in that one decision.

Evidence: the full backend suite (1166 tests) passes; Ruff passes on every
changed file; `tsc && vite build` passes for the frontend. Thirteen functional
tests (`backend/tests/functional/test_main_action_selector_behaviour.py`) ran
against the real vLLM runtime and the real `internet` MCP server (spawned
live, no mocks) and all thirteen passed, including a labelled-benchmark test
that holds the new decision to the exact recall/specificity floor
`evaluate_search_routing.py` already held the retired cascade to. That test
failed on its first real run — recall 0.759 against a 0.85 floor, missing
implicit-officeholder questions like "who is the prime minister of Canada" —
which is the kind of thing this rule exists to catch; naming that category
explicitly in the prompt and telling the model to prefer calling the tool
when genuinely unsure fixed it. The non-live browser suite (61 tests) passed
against a real Chromium instance and a real frontend dev server, including
every image-generation/edit test rewritten to mock the chat SSE stream
instead of the retired direct REST calls. One of those rewrites caught a real
bug before it shipped: the stream parser rejected any `artifact_started`
`kind` other than `"diagram"`, which would have broken every chat-initiated
image turn in the browser. Five pre-existing browser-suite failures
(a theme/color assertion, a diagram-reload timing test, and three
`presentations.spec.ts` tests) were confirmed present on unmodified `HEAD`
via `git stash` and are unrelated.

Known unverified: the three `@live` image tests that exercise real ComfyUI
generation were mechanically updated to the new event-stream shape but could
not be run in this environment — ComfyUI was not started (GPU-backed, profile
-gated). They are updated in good faith, not exercised. A single combined
real-browser-to-real-backend run (as opposed to a real browser against a
mocked backend, and the real backend against a real model via the functional
suite separately) was not performed either: `AUTH_REQUIRED=true` on the live
account and no credential was available or attempted, correctly.

Retiring the client-side routing surfaced a second gap while adapting its own
test: chat-initiated image generation had no way to be cancelled mid-flight,
because the "Cancel visual request" button and its `AbortController` were
wired only to the retired client-triggered visual paths. Fixed by threading
an `AbortSignal` through `streamChat` and widening the composer's cancel
affordance to any in-flight chat request, not only the old visual ones.

A third fidelity gap surfaced while updating `DEVELOPMENT_GUIDE.md`, not by a
test: chat-initiated generation/edit failures used a generic message instead
of naming an unreachable ComfyUI specifically, which is exactly the failure
this repository's own operational notes warn reads as a declined request
rather than an outage. `_image_provider_failure_message` in
`conversation_service.py` now matches the retired REST endpoints' wording.

`MainSupervisorAgent`, `DelegationRegistry`, `CascadingSearchRouter`, and
`SearchRoutingPolicy` remain in the tree, still tested standalone
(`test_supervisor.py`, `test_search_cascade.py`, `test_search_routing.py`,
`evaluate_search_routing.py`), but none is reachable from a live turn.

Diagrams: `chat-orchestration.mmd` redrawn around `MainActionSelector`, plus
the generated architecture page's metrics strip and orchestration-contract
paragraph. `visual-artifact-subsystem.mmd` deliberately left unchanged — its
"Owned visual API" boundary and internal relationships did not change, only
who calls into it. `npm run docs:diagram` regenerated all 19 SVGs and
`architecture.html`; `npm run docs:diagram:check` confirms the full set and
the published page are synchronized.

## Delete all personal memory now removes visual artifacts — VERIFIED

The reported failure reproduced with a disposable owner and a real stored PNG:
`DELETE /api/v1/memory/{user_id}` returned 200, reported no artifact count, and
left both the `visual_artifacts` row and opaque file reachable. The first
failing boundary was the memory endpoint, which coordinated personal, agent,
tool, conversation, and discovery deletion but never invoked artifact
lifecycle cleanup.

The endpoint now calls a lightweight `ArtifactDeletionService` after its memory
stores are cleared. PostgreSQL deletes and returns every owned visual-artifact
storage key, including rows without files such as diagrams; the service removes
the corresponding opaque files and surfaces incomplete filesystem cleanup
instead of falsely reporting success. Derived visual semantic records are also
removed, and the response names the `artifacts` count. Cross-user tests prove
another profile's artifact row and file remain intact.

Evidence: 24 focused memory, artifact-lifecycle, discovery-coverage,
agent-memory, and authorization tests pass; Ruff passes; the frontend production
build passes. A rebuilt backend (`personalassistant-backend`, manifest
`05c24d1f998e...`) was exercised with one owner and one control user: the owner
changed from one artifact/file/visual memory to zero, while the control stayed
at one artifact and one file. Backend logs show the exact DELETE and follow-up
reads with no exception. A real Chromium run through `https://deep-matter.com`
uploaded a valid PNG, clicked **Delete all personal memory**, received 200 with
an artifact count, rendered the empty memory state, and observed an empty
artifact API with no Console or page errors. All 19 canonical diagrams and the
published architecture page are synchronized.

Known unrelated validation failure: a focused MyPy invocation still reports
the existing Pillow `LANCZOS`, conversation-service `Any`/optional embedder, and
reaction-callback typing errors outside this change. It is not counted as a
passing static gate.

## Visual style memory survives tab and conversation context — VERIFIED

The exact `ani.mallya` question **how do you feel about my dress style?** twice
received a denial even though the uploaded portrait had a stored Qwen analysis.
The first failing boundary was the derived semantic shortlist: eight visual
memories whose artifact rows had already been deleted ranked ahead of the live
portrait. The semantic selector chose a relevant outfit description, but the
required owner/readiness check rejected its missing handle, leaving generation
with no image context.

Visual-memory retrieval now joins each derived description to a ready image
artifact owned by the same user before applying its result limit. Artifact
deletion also removes its matching derived analysis row in the same PostgreSQL
commit. Existing orphan rows are therefore inert without destructively changing
the user's database. The image-memory prompt now answers appearance and style
opinions directly from recalled evidence while treating one outfit as evidence,
not a permanent wardrobe preference.

The same investigation exposed that the straw-hat child had never been observed
after FLUX finished, so its current pixels had no analysis of their own. Image
refinement now sends the ready child to local Qwen vision, stores the child's
analysis, and indexes that current description. A VLM failure preserves the
valid edit and logs the degraded state. The text-lineage fallback remains a
recorded `xfail`: Qwen can still prefer the origin's black-hat description over
an explicit straw-hat delta when no child observation exists.

Evidence: 34 focused repository, indexing, context, refinement, and real-Qwen
tests pass, with one strict `xfail` for the documented no-observation fallback.
The passing real-Qwen coverage includes semantic portrait selection, unrelated
query rejection, lineage, and exact style-opinion behavior. After rebuilding
backend image `9f817189f639...` and restarting the gateway, a direct authenticated
chat request with no active image ID emitted `image_matches`, described the
black cowboy hat, dark blue bomber jacket and white T-shirt, and terminated with
`done`. An authenticated Chromium run through `https://deep-matter.com` restored
the owned edited image, sent its exact artifact ID, rendered a grounded style
answer, cleared loading, and completed without Console or required-Network
failures.

Live refine-observe acceptance then created temporary child
`436002dc-c5aa-4253-b46b-c2cf9b3d4bf0` in 35 seconds. FLUX returned ready
pixels, Qwen stored a current analysis naming the wide-brimmed straw cowboy hat,
dark bomber jacket and white shirt, and direct chat answered from those current
details. The public Chromium path passed with that exact child selected. Deleting
the temporary child returned 200 and atomically changed both its artifact count
and derived semantic-memory count from one to zero.
The user's existing straw-hat child
`24970e16-006f-46a9-b10e-74b891fcbe0f` was then observed once through the same
Qwen boundary so it is no longer a legacy unobserved revision. Its current
analysis names the straw hat, dark bomber jacket, white shirt and waterside
sunset; the exact style question now answers from those details, and the public
Chromium path passes with that artifact selected.

## One image target in the main composer — VERIFIED

The image card's persistent follow-up textarea was removed. The newest visible
image now appears as a removable thumbnail reference above the main composer,
and every visible image exposes **Ask or edit** so the user can explicitly
switch the target when several images exist. Questions stream through `/chat`
with that exact `active_image_artifact_id`; edit-shaped instructions use the
same selected source and replace its visible card with the immutable child.
Clearing the reference sends `active_image_artifact_id = null`.

The explicit selection is an override, not the memory design. When no artifact
is explicitly supplied, owner-scoped semantic visual candidates may be selected
by the bounded Qwen visual-memory policy and are owner/readiness checked again
before their descriptions and lineage enter the answer prompt. The durable
target is type-neutral: generated, uploaded, or discussed artifacts share an
owned handle, provenance and derived semantics; video observation and parsed
PDF/RAG chunks remain planned additions to that contract.

Evidence: five focused Chromium image workflows pass, including two-image
selection/switch/clear, exact request-body IDs, ordinary questions, and
generated/uploaded refinements. The frontend production build passes. A broad
67-test Chromium run produced 61 passes and six unrelated failures in existing
authentication/theme/navigation tests; rerunning those six serially reproduced
them, so the broad suite remains `FAILED` and is not attributed to this image
change. All 19 canonical diagrams and the published architecture page were
rendered and synchronized after updating the three affected views.

The first public deployment check was insufficient: `deep-matter.com` returned
200, but the six-hour-old gateway image still served `index-C6UAPirx.js`, which
contained the removed follow-up box. The Vite frontend container had the new
source, but Cloudflare never points at port 5173; it points through the named
`anios` tunnel to the gateway's compiled bundle on loopback port 8080. The
gateway was rebuilt and recreated. Both published Cloudflare IPv4 addresses now
serve `index-DdjG7VDH.js`; that exact public asset contains **Ask or edit** and
**Using in chat**, does not contain **Ask about or refine this image**, and is
returned with `Cache-Control: no-store` plus Cloudflare `DYNAMIC/BYPASS` status.
An authenticated Chromium session then opened `https://deep-matter.com`,
restored the owned uploaded image, displayed the main-composer image reference,
sent the exact artifact ID to `/api/v1/chat`, received a grounded style answer,
terminated streaming, and cleared loading with no Console, page, or required
Network failures. The test's short-lived bearer is scoped to `/api/` requests
so Cloudflare-injected third-party assets never receive it.

The exact `ani.mallya` refinement **can you make it a straw hat instead?** then
exposed a separate terminal-state defect. Artifact
`24970e16-006f-46a9-b10e-74b891fcbe0f` became ready and replaced parent
`5276e37b-2efc-4203-825b-b78ac8c977db`, and the refine request returned 201,
but the browser retained the independent **Creating your image locally.** /
**Generating image...** placeholder. Refinement completion now removes exactly
the newest matching generation placeholder, and ready image cards replace
transient starting copy with **Image ready.** or **Image updated.** Two focused
Chromium workflows pass for generated and uploaded refinements, including
terminal copy, cleared activity, and an enabled composer. The production build
passes, and both public Cloudflare edges serve the rebuilt bundle containing
those terminal states with `Cache-Control: no-store`.

Next atomic task is to repair the
browser suite's auth/theme isolation before treating its broad result as a
clean regression gate.

## Documentation reconciled with the code — VERIFIED for the docs, INHERITED for the rest

An audit of the agent documentation against `HEAD` found six drifts, all now
repaired. They are listed because most were introduced by the very commit that
changed the thing they describe — the code and one document moved, and the
neighbouring document did not. That is the pattern to watch for:

- `AGENT_CATALOG.md` still called the diagram agent's tests `xfail` and its
  defect "intermittent", in the same file whose later section already recorded
  the fix. The commit that fixed the defect updated the new table and left the
  agent's own section behind.
- The diagram catalog said Scout's model decides "only how a find reads", three
  commits after it started aiming search subjects and reranking shortlists. The
  `.mmd` was updated; the row above it was not.
- Scout's and memory capture's rows omitted
  `test_timezone_prompt_behaviour.py` and `test_interest_capture_behaviour.py`.
  A catalog under-reporting its own functional coverage is the wrong direction
  to be wrong in, given that a prompt without one is an untested feature.
- `ARCHITECTURE.md` listed three agent folders where there are four, and
  described the published page as 15 canonical views when 19 sources exist.
- The four agent diagrams were registered in the renderer and the catalog but
  never added to `architecture-page.mjs`, so no agent view was reachable from
  the manager-facing page while its own metric read `15 / 15 synchronized`.

All 19 views are now published. The count is read from the `.mmd` files on disk
rather than hardcoded, and folded into the page fingerprint, so a diagram added
to the catalog and not published now fails `docs:diagram:check` instead of
leaving the page printing a reassuring number.

Evidence from this session: `npm run docs:diagram` rendered 19 diagrams and the
page; `npm run docs:diagram:check` reports **19 architecture diagrams are
synchronized** and **Published architecture page is synchronized**; the four
`agent-*` sections and the `19 / 19` metric are present in `architecture.html`.

Everything else recorded below and in the changelog for 2026-08-10 is inherited
from the commit record rather than re-verified here — no backend suite, browser
session, or model run was executed in this session. The next task that touches
runtime behavior should re-establish its own evidence rather than trusting this
line.

Known and deliberately unrepaired: asked for a **state machine** the diagram
agent returns `"source": "stateDiagram-v2"` with no body. Flowcharts, which is
nearly every request, run 6/6.

Next atomic Scout task remains the Mac recipient-grant repair described below.

## Memory meaning is selected semantically, not by regex — VERIFIED

The first fix for `hi my name is Jen and i like acting, theater, networking
events` bounded a preferred-name regex. That contradicted the established
requirement that memory understand the user's meaning rather than accumulate
phrase rules. The production regex proposal module and its tests have now been
removed.

One local `MemoryProposalAgent` backed by `qwen/qwen3.5-4b` reads the whole
current utterance and returns grammar-constrained typed candidates for preferred
name, response style, locality, interests, entity relationship, workflow,
titled reference, semantic fact, and episodic event. Application code only
validates bounds and safe field shapes, attaches conversation/trace provenance,
and routes visible user approval; the model still has no persistence authority.
Profile facts may coexist, while general memory keeps one best candidate to
limit noisy proposals. The previous dedicated interest agent was removed.

Real Qwen evidence:

- the exact reported sentence returned `preferred_name = Jen` and `acting`,
  `theater`, `networking events`;
- `Everyone knows me as Jen. Stage performance and professional mixers are my
  thing.` returned the same preferred name and semantically mapped the interests
  onto the existing `testuser` labels instead of creating duplicates;
- `Would someone named Jen enjoy theater?` returned no proposal.
- the first semantic-fact rehearsal exposed an over-conservative/misclassified
  pet fact; after tightening the semantic contract, three different ways of
  saying the dog is called Biscuit all returned `semantic_fact`, `I love
  training dogs` returned only interest `dog training`, and the dog-name
  question still returned nothing.

The rebuilt backend and real authenticated Chromium path as `testuser` showed
both exact proposals, **Approve all 2** issued preferred-name 200 and interests
201, and readback returned `Jen` plus all three interests. Loading cleared, the
composer re-enabled, and browser Console, page, failed-network, and backend
exception checks were empty. The container received the increased 256-token
structured-output budget.

- Regression: 82 focused backend tests pass; Ruff passes; two focused
  Playwright tests and the frontend production build pass; 17 architecture diagrams
  and the published architecture page are synchronized.
- MyPy reached two pre-existing errors in `backend/discovery/link_graph.py`.
- Next atomic Scout task remains the Mac recipient-grant repair described below.

## One introduction now captures name and Scout interests — VERIFIED

The exact `testuser` message `hi my name is Jen and i like acting, theater,
networking events` exposed two boundaries. Preferred-name extraction consumed
the following `and I ...` clause, producing `Jen and i like acting`, and the
conversation service allowed only one memory proposal per turn, so that bad
name proposal suppressed the semantic interest result. The focused Qwen
classifier itself was correct and returned `acting`, `theater`, and `networking
events` before any code changed.

Name extraction now ends before a following `and I` or `but I` clause. A chat
turn may emit every compatible profile proposal (name, response style,
locality, and Scout interests), while general semantic/episodic memory keeps
the existing single-best rule. The frontend queues the streamed proposals so
each remains independently approval-gated rather than the last event replacing
the first.

The backend image was rebuilt from the working tree, `backend` was recreated,
and the gateway restarted. Through the real authenticated HTTP path as
`testuser`, the exact message streamed `preferred_name = Jen` followed by the
three Scout interests; approvals returned 200 and 201. Readback returned
profile name `Jen` and all three interests. A real headless Chromium session as
`testuser` rendered both cards in order, approved them, cleared the queue and
loading state, and recorded no Console, page, or failed-network errors. Backend
logs contain the chat and both approval requests with no exception.

- Regression: 72 focused backend tests pass; Ruff passes; three focused
  Playwright proposal regressions pass; the frontend production build passes.
- `FAILED` validation command: a broad title-based Playwright grep did not
  finish within 180 seconds and emitted no result. This does not invalidate the
  exact deterministic browser test or the real integrated Chromium acceptance,
  both of which passed.
- Next atomic Scout task remains the Mac recipient-grant repair described below;
  after delivery is verified, add deterministic geographic result rejection.

### Follow-up: multi-fact consent is now explicit — VERIFIED

The user then cleared `testuser` memory and repeated the same sentence. Runtime
logs showed the chat completed but the browser submitted only the Scout-interest
approval; no preferred-name request reached the backend. A read-only Chromium
replay proved the name was correctly first in the queue, but the card described
the second fact only as `1 more memory proposal waiting`, making it easy to skip
one fact and assume the other approval covered the sentence.

The approval card now previews every queued value and offers **Approve all 2**
while retaining per-item approval and dismissal. Batch UX saves each typed
endpoint in order; if a later request fails, already saved facts are reported,
the failed and unattempted proposals remain actionable, and the error is shown.
A real Chromium run as `testuser` submitted the exact sentence and used that
single action. Network evidence was preferred name 200 plus Scout interests
201; readback was name `Jen` and all three interests. The card and loading state
cleared, the composer enabled, and Console, page, and network-failure lists were
empty. The focused Playwright regression and production frontend build pass.

## Scout's prompts now live with Scout

Done. `agents/scout/` holds `aiming.py`, `reranking.py`, `describing.py` and
`place_suggest.py` — every prompt Scout injects. `discovery/` keeps the
machinery: the sweep, ranking, novelty, familiarity, delivery, and the
deterministic half of describing (`clean_title`,
`summarize_deterministically`, `text_from_html`), which never invents and which
several modules share.

Three things made it work, and are worth not undoing:

- `TextWriter` moved to `core/interfaces.py`. It had lived inside Scout's
  describe module, so every agent-shaped module imported that module for a type
  unrelated to Scout;
- `InterestAim` and `SweepAim` moved to `discovery/types.py`. They are data, so
  `precision.py` and `runner.py` take them from the domain and no type drags the
  agent layer in behind it;
- `runner.py` imports three classes from `agents/scout/`. That is the one edge
  from domain to agent, and it is deliberate: the runner *is* Scout's sweep
  body. There is no cycle — `agents/registry.py` reaches only
  `discovery/reachability.py`, which imports nothing back.

Deck is done too: `agents/deck/prompts.py` holds all five — the four contract
builders and the preambles that open each call — and `presentations/provider.py`
keeps the machinery, the JSON extraction, the per-layout schema and the view
builders that decide what a slide looks like to the model.

Diagram and memory capture are done too — `agents/diagram/prompts.py` and
`agents/memory/prompts.py`. Memory capture has no registry card because it is
not something the workspace lists; it is a step in every conversation, and the
folder exists only so its prompt sits with it.

Every agent prompt now lives with its agent. `presentations/provider.py` holds
none: the slide-content preamble became `slide_content_preamble(index, total,
deck_title)` in `agents/deck/prompts.py`, parameterised because it is the only
call that tells the model where in the deck it is.

A codebase audit found **no unused modules at all**. Seventeen public
definitions read as unreferenced and all but two were false positives — pydantic
validators, FastAPI routes, MCP tool decorators, protocols used in string
annotations, and one aliased import. `get_owned_record` and `clear_style` were
genuinely dead and are gone. `apply_slide_edit` is still unreferenced and is
deliberately left: the roadmap records slide editing as verified, so it is
either an edit path nothing applies or a gap in that claim, and deleting it
would hide the question.

**Not moved on purpose:** `search/classifier.py` and
`artifacts/image_recall_classifier.py`. Both call a model, and both route rather
than produce work — they decide whether to search or to look for an image.
Treating a routing policy as an agent would put a folder round something the
workspace will never list. Decide that before moving them. Search routing and image recall are in
`search/classifier.py` and `artifacts/image_recall_classifier.py`, and those two
may be policies rather than agents — decide that before moving them.

## Schedules now take their zone from the user's place — half fixed

`PUT /schedule` no longer reads the caller's timezone. It takes the zone from the
user's primary locality, and refuses with 409 when there is no locality yet:
a time means nothing without the zone it is in, so the place has to come first.
The request still accepts a `timezone` field and ignores it, so existing clients
do not break on an unknown key.

**What is still wrong.** The locality's own zone can be wrong, so the schedule
now faithfully inherits a wrong zone. `projection.py` hardcodes
`America/New_York` when a place is created from a chat approval, which is how an
account in Canggu, Bali holds a locality — and therefore now a schedule — in
Virginia time. Existing rows are unchanged: arsalon's schedule still reads
America/New_York and will until his locality does.

The remaining work is resolving a place to a zone: the Nominatim resolver
already returns coordinates that map to one, or a bundled table. Until then the
Scout panel is the only path that stores a true zone, because the browser sends
`Intl.DateTimeFormat().resolvedOptions().timeZone`.

## Original diagnosis

Diagnosed, not fixed. The scheduling mechanism is timezone-aware — each row in
`discovery_schedules` carries a `timezone` and `next_run_at` is computed from
the local hour in it — but the timezone is never derived from where the user is:

| user | locality | schedule tz | correct? |
| --- | --- | --- | --- |
| jenos1 | Alexandria, Virginia | America/New_York | yes |
| ani.mallya | Virginia | America/New_York | yes |
| arsalon | **Canggu, Bali, Indonesia** | **America/New_York** | **no** |

arsalon's schedule reads 11:15. It fires at 11:15 New York, which is 15:15 UTC
and 23:15 in Bali, so a morning digest arrives at eleven at night.

`projection.py` hardcodes `timezone="America/New_York"` when it creates a
locality, and a place approved from chat goes through that path — the label
"Canggu, Bali, Indonesia" is stored while the clock stays in Virginia. The same
default appears in `api/v1/discovery.py`, `delivery.py` and `digest.py`. Each is
reasonable alone; together they mean the system assumes everyone is on the US
East Coast and nothing ever contradicts it.

`PUT /localities` does better: the frontend sends
`Intl.DateTimeFormat().resolvedOptions().timeZone`, so a place typed into the
Scout panel picks up the browser's zone. The chat-approval path has no browser
timezone to pass, which is the path that produced this.

Two parts, and the second is the real one:

1. stop the projection inventing a zone — make the column nullable and resolve
   at read time, so a wrong clock is visible rather than assumed;
2. derive it from the place. "Canggu, Bali, Indonesia" to `Asia/Makassar` needs
   a lookup: either the Nominatim resolver, which already returns coordinates
   that map to a zone, or a bundled place-to-timezone table. The browser zone is
   a fair proxy and is wrong for anyone travelling — which is exactly the case
   Scout already models with travel mode, so it cannot be the whole answer.

Until then, setting a place through the Scout panel from a browser in the right
country stores the real zone, and re-saving the schedule picks it up.

## A functional suite, and what it found immediately

`backend/tests/functional/` sends each prompt to the real model and asserts on
the answer. Fifteen behaviours, chosen from what each prompt claims to do rather
than from past incidents: an interest becomes matchable text, a subject carries
no place or date, personalisation is visible when a fact exists, a finished page
is reported as finished and a weekly class is not, a description never carries a
link, a shared place name completes to more than one region, a nonsense name
completes to nothing, ordering follows the facts, a weak match is not excluded,
and capture ignores a question or another person's preference.

Fourteen pass. One is marked `xfail` and is a **real product defect, not a flaky
test**: asked for a three-step pipeline, the diagram model returned
`<!template>flowchart TD:[order[]((Order Received))]...` — markup the renderer
cannot draw — and on retry failed validation outright, so that request produces
nothing at all. The prompt already forbids HTML and requires the source to start
with its declaration; the model ignores both on this shape of request. The fix
is a worked example in the prompt or a repair pass before validation, and it
needs measuring across several requests rather than the one.

Two things to keep doing here. Assert on properties, not wording, so a reworded
prompt survives and a changed behaviour does not. And write the test from what
the prompt claims, not from what has gone wrong before — this suite was written
that way and found a defect nobody had reported.

## Where the prompts are

Every prompt Scout injects, so they can be read in one place:

| What it decides | File |
| --- | --- |
| Search subject and ranking vector per interest | `backend/discovery/aiming.py:147` |
| Order of the qualified shortlist against memory | `backend/discovery/reranking.py:102` |
| A find's name, its one-line description, and whether the page says it is over | `backend/discovery/summarize.py:183` |
| Place-name completion while typing | `backend/discovery/place_suggest.py:83` |

`docs/ARCHITECTURE.md` has the table of when each runs and what it costs.

Two of these are load-bearing in ways that are not obvious. `aiming.py` runs
even when memory is empty, which is every account today, because a two-word
interest cannot be matched against an event description at all. And
`summarize.py`'s `already_happened` is asked but no longer trusted alone: a
stated deadline is read deterministically in `url_dates.deadline_has_passed`,
after a digest offered a vote that closed a week earlier.

## Scout: where it stands and what is next

`python -m backend.cli.evaluate_discovery_ranking` scores the pipeline against
21 items that reached real digests. Baseline: **listing recall 0.46, happening
retention 1.00**. The seven listings still getting through are named in the
output — that is the work queue, not an aggregate to admire. `--with-model` also
scores attribution through the aiming and cross-encoder stages.

Ranking is a three-stage cascade: embeddings for recall (`relevance.py`), a
local ONNX cross-encoder for precision and attribution (`precision.py`), then
the model for what memory states (`reranking.py`). Only the first decides
eligibility. All of it is deployed; a fresh checkout must fetch the
cross-encoder weights (`DEVELOPMENT_GUIDE.md`) or that stage disables itself.

Queued, in priority order:

1. **Audience restrictions, deterministically.** `summarize.py` already reads
   page text and already drops finds, so add a restricted-audience field there.
   Say it in the digest name first so the user can judge; filter only in code,
   only against an explicitly stated fact. Do not push this into the re-ranker's
   prompt — measured, and it inferred gender from nothing.
2. **Geographic rejection.** Visible in the labelled cases:
   `concertfix.com/concerts/arlington-tx` reached an Arlington, Virginia digest,
   and a chamber-of-commerce index for Alexandria Bay, New York reached an
   Alexandria, Virginia one. Deterministic, cheap, and long overdue.
3. **Route listings to the feed proposer rather than the bin.** `feed_finder`
   and `LinkGraphExpander` already propose sources from discovered pages. "Movie
   showtimes near Alexandria" is a bad digest item and a good source candidate.
4. **A structured event source.** Ticketmaster, Eventbrite, or Songkick return
   events with start times and coordinates, removing the listing/happening
   distinction, the date parsing, and the geography problem at once. Feeds are
   already the design's "source of record"; almost nobody configures one, so web
   search does all the work and fights this fight every sweep.
5. **Earn back or delete `is_a_listing`.** It is computed and unused.

Volatile state: **`DISCOVERY_NOVELTY_ENABLED=false`** in `.env`, so digests
repeat until it is turned back on — it must be on before anything runs
unattended. Seen items were purged for `ani.mallya`. The Mac bridge grants work.
`jenos1` has "Social" and "Network" as separate interests, almost certainly one
phrase split at capture, and it will keep producing odd matches until corrected.

## Scout searches and ranks for the person — VERIFIED in source, NOT DEPLOYED

A sweep used to be handed a two-word interest label and a city, so the query was
`{label} {place} {month year}` and the vector a candidate was scored against was
the embedding of `label`. Approved memory reached neither. Three new modules
close that:

- `discovery/personal_context.py` reads one account's **approved, unexpired**
  facts and remembered sentences, skips the interest and locality projections
  (already typed into the profile), drops `preferred_name` and `response_style`,
  screens every statement through the same `OutboundPrivacyPolicy` that guards
  chat search, and bounds the result to 12 statements of 200 characters;
- `discovery/aiming.py` asks Qwen once per sweep to turn each interest plus
  those facts into a **search subject** and a **ranking profile**. The skeleton
  `{subject} {place} {month year}` and the query budget are unchanged. A subject
  carrying a digit, a month, the place, query syntax, or anything the egress
  screen would rewrite is rejected and the bare label used instead;
- `discovery/reranking.py` ranks a shortlist twice as wide as the digest and has
  Qwen order it against the same facts. It can never admit what deterministic
  ranking rejected, and if it excluded everything the deterministic order ships.

Both stages are behind `DISCOVERY_PERSONAL_QUERIES_ENABLED` and
`DISCOVERY_MEMORY_RERANK_ENABLED` (default true, added to the Compose allowlist
for `backend` and `discovery-worker`, verified present in `docker compose
config`). With either off, or with no model, no memory, or an unparseable reply,
the sweep searches and ranks exactly as it did before.

### Measured against the live runtime, read-only, no search budget spent

Real vLLM (`qwen/qwen3.5-4b`) and the real embedding service, for a person whose
approved facts said they run casually at weekends, are a man, prefer
beginner-friendly things they can attend alone, like live jazz and dislike
stadium shows, and do not drink:

```
Run Clubs    -> casual weekend group runs   Hiking  -> beginner-friendly hikes
Concerts     -> live jazz and blues         Line Dancing / Wine Tasting -> unchanged
```

Best-interest margins, bare label vs aimed vector:

| candidate | bare | aimed |
| --- | --- | --- |
| Saturday Morning Social Run | 0.633, margin 0.071 | 0.757, **margin 0.132** |
| Live Jazz Trio at Blues Alley | 0.644, margin 0.054 | 0.737, **margin 0.118** |
| Beginner Line Dancing Social | 0.768, margin 0.208 | 0.843, margin 0.206 |
| Stadium Tour: Arena Rock | 0.640, margin 0.119 | 0.690, margin 0.159 |

Genuine matches separate roughly twice as far — which is what
`MIN_ATTRIBUTION_MARGIN` (0.035) exists to cope with. **And enrichment cannot
encode exclusion**: the stadium show scored *higher* after enrichment for
someone whose facts say they dislike stadium shows. That is the case for having
both stages rather than either.

The re-ranker put the social run, the jazz trio and the beginner class first and
pushed the stadium show, the wine festival and a women-only race last — correct
for this person, deterministic across repeated greedy runs.

### The women-only defect is mitigated, not fixed

The re-ranker ranked the stated women-only race last and did **not** exclude it,
for a person whose facts state they are a man. Strengthening the wording was
tried and measured, and is recorded in `reranking.py`: with a worked example it
excluded all three restricted-or-disliked items — turning two *preferences* into
eligibility bars — and on a control context with **no fact about gender** it
still excluded the women-only race. That is the inference this must never make.
The conservative wording stayed. Audience restriction still needs the
deterministic route: a restricted-audience field read out of the page in
`summarize.py`, said in the digest, filtered by code against an explicit fact.

### The binding constraint is upstream: memory is empty

`memory_facts` holds exactly three non-projection rows across the whole
database, all `preferred_name` (which this deliberately never reads), and
`semantic_memory` holds one row belonging to a throwaway test account. So for
`ani.mallya` the personal context reads empty, the planner is not called, and
every query is the bare label — verified by running the planner against that
real account. The plumbing is in place and has nothing to carry. Making Scout
personal from here is a memory-capture problem, not a discovery problem.

- Regression: **1020 backend tests pass** with `AUTH_REQUIRED=false`, including
  28 new ones; Ruff and strict MyPy clean on `backend/discovery` (two
  pre-existing `link_graph.py` errors untouched); 17 diagrams synchronized.
- `UNVERIFIED`: no sweep has run through the built containers. The images were
  not rebuilt and `backend`/`discovery-worker` were not recreated, because doing
  so drops live users on the tunnel. Rebuild both, then `docker compose restart
  gateway`, before claiming live behaviour.


## Scout account isolation restored at the live runtime — VERIFIED

A report that a `jenos1` 9:30 PM subscription triggered the primary user's
phone exposed two separate facts. PostgreSQL already held distinct owners:
`ani.mallya` owns the 9:30 PM schedule and five interests, while `jenos1` now
owns a 10:00 PM schedule and twelve different interests. Their subscriber address
digests are also different, and the 9:30 delivery belongs to the
`ani.mallya` run and subscriber. The worker reads the run's `user_id` and uses
that same owner for profile retrieval and subscriber selection.

The first failing boundary was nevertheless security-critical: the live
backend was a stale container with `AUTH_REQUIRED=false`, even though `.env`
and the current Compose rendering both specify `true`. In trusted-local mode
the ownership dependency intentionally accepts caller-supplied user IDs. The
backend was recreated from current Compose configuration and the gateway was
restarted. Direct live bearer requests now prove:

- both owners can read their own profile and schedule (HTTP 200);
- the interest sets are separate and disjoint (five vs. twelve);
- an `ani.mallya` token cannot read `/discovery/jenos1` (HTTP 403);
- an anonymous request cannot read `/discovery/ani.mallya` (HTTP 401);
- backend logs record those 403/401 decisions without an exception.

The phone UI also hid the signed-in identity and represented logout only as an
unlabeled compact-header icon. The mobile navigation drawer now shows
`Signed in as <user>` beside a labeled **Sign out** action. Playwright at
390x844 exercised both the deterministic app and the rebuilt production
gateway: it opened the drawer, confirmed the live authenticated account,
received HTTP 204 from logout, and reached the login screen with no Console or
page errors or failed network requests.

Regression evidence: the auth, delivery, schedule, and worker suites pass 45
tests, including a new two-user delivery assertion that only the requested
owner's approved address is selected; two focused mobile browser tests pass;
and the production frontend build passes.

### `jenos1` phone delivery — FAILED at the Mac grant boundary

The current Mac MCP bridge advertises both `send_imessage` and
`allow_recipient`, but an idempotent grant for the already consented and
operator-approved `jenos1` subscriber returns a tool error that explicitly
identifies bridge grants as disabled. The subscriber remains deliverable in
AniOS but has zero successful deliveries and `recipient_not_allowed`; nothing
was redirected to `ani.mallya`.

The latest 10:00 PM run fetched five candidates and persisted five selected
future/undated items. Its `delivered_at` field is only the claim-before-send
marker and is not evidence of receipt: the subscriber row was not touched and
the user received nothing. A read-only replay of that stored digest through the
current delivery logic selects exactly the one `jenos1` subscriber and would
make one channel call. Do not replay the old message; its durable retry payload
has already been cleared.

The Mac LaunchAgent must persist `IMESSAGE_BRIDGE_ALLOW_GRANTS=true` (and may
set an explicit writable `IMESSAGE_BRIDGE_GRANTS` path), then reload/restart
the bridge. Re-approve the existing subscription or invoke the idempotent grant
again, confirm `granted`, and validate a new owned digest reaches only the
masked `jenos1` destination.

### Next atomic Scout task after delivery is verified

Add and validate geographic result rejection. The live Arlington, Virginia
rehearsal correctly found local basketball/baseball results but also admitted a
college-baseball result explicitly located at Globe Life Field in Arlington,
Texas. Reject an explicit place that contradicts the active locality/region
before it can enter the digest — deterministically, in code: this is a string
comparison against a stated place, not a judgement.

## Scout rejects explicitly past search results — VERIFIED

The live `ani.mallya` rehearsal reproduced two user-visible problems: Scout
returned a prior line-dancing event as an undated possibility, and its message
opened with the mechanical phrase `Worth a look — no date given`. The first
failure was at web-result conversion: an explicit date before today and no
date at all both became `None`, so relevance treated the past event as an
undated mention.

`WebEventSource` now preserves the distinction long enough to reject an
explicit date before today. Current and future explicit dates retain their
typed value; genuinely undated results remain bounded mentions. The fixed
digest renderer now says either `I found this, but couldn't confirm the date`
or the plural equivalent instead of implying an undated result is confirmed
upcoming.

Live authenticated evidence on the rebuilt backend:

- the same non-persisting `ani.mallya` rehearsal exercised four MCP
  `internet/search_web` calls through Tavily, Nomic embedding/ranking, and the
  digest renderer with no backend exception;
- the candidate pool fell from 27 to 26 because the explicitly past result was
  rejected before ranking;
- the returned message used the new uncertainty wording and contained no old
  heading;
- Chromium opened the real signed-in `ani.mallya` Scout panel, ran **Try it**,
  rendered the new wording, and reported no blocking Console or page errors;
- 286 discovery backend tests, Ruff, strict MyPy, five focused Scout browser
  tests (two passed and three correctly skipped without live credentials), the
  separately credentialed live browser acceptance, and the frontend production
  build passed.

At the user's request, all 28 `discovery_seen_items` rows owned by
`ani.mallya` were deleted after validation so another real test starts clean.
The scoped count is now zero; `jenos1` and `del_2a87abb15636` rows were left
unchanged. Interests, locality, schedules, subscriptions, familiar-item
dismissals, memory, and run history were not deleted.

## Semantic chat interests configure Scout — VERIFIED, generalized

The original `testuser` failure was at chat capture, not Scout retrieval. That
focused interest classifier has since been generalized into the typed
`MemoryProposalAgent` described at the top of this handoff. It still sends only
the current utterance and existing interest catalogue to local Qwen, has no
persistence or tool capability, and returns up to eight validated labels.
Approval writes every selected interest fact and Scout projection in one
database transaction; a capacity or projection failure rolls the batch back.

Live authenticated evidence on the rebuilt backend:

- direct `POST /api/v1/chat` returned a complete SSE stream with one
  `discovery_interests` proposal containing basketball, soccer, baseball, and
  hiking;
- direct approval returned 201 and the owned Scout profile contained exactly
  those four `user_explicit` interests;
- Chromium repeated the conversation, approved the card, opened Agents → Scout
  → Configure, and saw all four strength controls; streaming terminated, the
  composer re-enabled, and post-login Console/page errors were empty;
- another profile remained empty in the integration test;
- a live non-persisting Scout rehearsal in Arlington, Virginia spent four MCP
  `internet/search_web` requests, each reached Tavily with HTTP 200, Nomic
  embedded/ranked the candidates, and Qwen produced the visible descriptions.

The browser run also found and fixed an adjacent authenticated Scout UI defect:
subscription read/write/delete used bare `fetch`, omitted the session cookie,
and emitted 401s. They now use the shared authenticated request boundary.

Validation: 127 relevant backend tests passed; Ruff and strict MyPy passed; two
deterministic Scout browser tests passed; the authenticated live Scout browser
test passed; the frontend production build passed; all 17 canonical diagrams
and `architecture.html` are synchronized. A combined full-backend/full-browser
run exceeded its 10-minute orchestration ceiling and ended with a Playwright
EPIPE, so the complete suites are `UNVERIFIED` for this tree rather than failed.

## Scout's iMessage channel — VERIFIED working end to end

The bridge (`bridges/imessage_mac/`) is running on a real Mac (not AniOS's
Windows host) and a message sent through it was confirmed received on the
allowlisted phone. Both the header-auth transport fix (`d3001d9`) and the
backend's own missing `docker-compose.yml` allowlist entries for
`DISCOVERY_IMESSAGE_SERVER_ID`/`DISCOVERY_IMESSAGE_TOOL` (`6e77969` — the
fourth instance of the environment-allowlist trap this session) were needed
before this worked; either alone left it silently broken.

What the Mac side needed, none of which is obvious from the bridge's own code:

- **Python 3.10+, not the system `python3`.** A stock macOS install (and this
  Mac specifically) ships an ancient `python3` (3.7 here) via an old
  python.org installer; `mcp` requires 3.10+ and fails at `pip install` with
  "no matching distribution found for mcp", which names the package rather
  than the interpreter as the cause. Installing a newer Python via Homebrew on
  an unsupported-for-bottles macOS version (this Mac: Ventura 13.7, Intel)
  means several dependencies build from source, and that build fails outright
  if Xcode Command Line Tools are older than Xcode 15.2 — this Mac's shipped
  CLT was from 2019 (`clang 11.0.0`) and needed
  `sudo rm -rf /Library/Developer/CommandLineTools && sudo xcode-select --install`
  before Homebrew's `openssl@3`/`readline` builds would even compile.
- **The Automation permission prompt is silent when nobody can answer it.**
  The first `osascript` call to Messages/System Events from a non-interactive
  or remote-controlled shell hangs for the AppleEvent timeout
  (`-1712`) and never surfaces a clickable dialog. It only works once someone
  runs an AppleScript call to Messages from an interactive Terminal window
  they're physically at, and clicks Allow.
- **The bridge needs the Mac to actually stay up.** `pmset -g` shows battery
  `sleep 1` (one minute); its existing AC settings are `sleep 0` and
  `disksleep 0`. `caffeinate -s` is AC-only, so it cannot keep this laptop awake
  on battery. A separate LaunchAgent at
  `~/Library/LaunchAgents/com.anios.imessage-bridge-awake.plist` now runs
  `caffeinate -i` with `RunAtLoad` + `KeepAlive`. It was verified on 2026-08-08:
  the assertion appeared as `PreventUserIdleSystemSleep`, killing it made
  launchd respawn it with a new PID, and the bridge continued to return its
  expected unauthenticated `401`. A laptop's lid still forces sleep regardless
  of this assertion unless it is in clamshell mode with an external display
  attached.
- **The process itself needs to survive logout/crash, which `nohup` does
  not.** It now runs as a `launchd` LaunchAgent at
  `~/Library/LaunchAgents/com.anios.imessage-bridge.plist`
  (`RunAtLoad` + `KeepAlive`, verified by `kill -9`-ing the process and
  watching it respawn under a new PID within seconds). This only starts once
  the Mac's user account is actually logged into a GUI session — it is a
  LaunchAgent, not a LaunchDaemon, because Messages automation needs a real
  Aqua session, not just a booted machine.

**The Mac's LAN IP is the address in `MCP_SERVERS_JSON`, and it can move.**
Same failure shape as the tunnel hostname below: if this Mac's DHCP lease
changes, the configured `url` silently points at nothing and AniOS-side
delivery starts failing with no signal pointing at the address as the cause.
Consider a static DHCP reservation for this Mac if the bridge is meant to be
depended on rather than just demoed.

**The shared bridge token has already been rotated once** after an earlier
value was pasted into a chat transcript relaying setup instructions between
the two machines. Treat any token that has appeared in a conversation as
burned; regenerate rather than reuse.

## Public access is deep-matter.com — VERIFIED

Live as of 2026-08-11. Tunnel `anios`
(`2a9093ad-4b7a-4fb2-8166-6f8de1eef5a4`), config in the operator's
`.cloudflared/config.yml`, ingress validating `OK`, DNS already routed.

Verified from inside a container rather than the desktop: DNS resolves to two
Cloudflare edge addresses, both complete a TLS handshake, `/healthz` returns 200
`ok`, `/` serves the compiled application, and `/api/v1/agents/{user}` returns
401 from FastAPI — the last of which is what proves the tunnel reaches the app
rather than just the edge.

**Cloudflare answers a non-browser client with error 1010** (browser integrity
check), so a scripted request without an ordinary user agent reports 403 on
every path and looks exactly like a dead site. That cost a round here. Send a
normal `User-Agent` or the check measures the bot rule instead of AniOS.

**The tunnel runs as a Scheduled Task, not a Windows service.** The service was
abandoned after six attempts: it installed, reported `Running`, and registered no
connector, because Windows recorded its ImagePath as the bare executable with no
arguments. With nothing to run it started, exited, and retried — and `sc.exe
config` would not attach arguments, `service install` refused to touch an
existing registration, and `service uninstall` left the key marked for deletion
behind a process that would not die.

The task is `DeepMatter tunnel`, registered to run as SYSTEM at startup and to
restart itself every minute if cloudflared stops.

### ComfyUI does not restart itself either — same reboot, same cause

After the 08:49 reboot nothing was listening on 8188, so every image request
failed while every container reported healthy. ComfyUI is a host process at
`COMFYUI_HOST_PATH`, not a Compose service, so `restart: unless-stopped` never
applied to it.

It now has a `DeepMatter ComfyUI` logon task running the same command
`start-anios.sh` uses. Unlike the tunnel's SYSTEM task, this one is readable
from a non-elevated shell — action, arguments and working directory all verified
— but it has still not survived an actual reboot, and that is the claim that
already failed once here.

The symptom is worth remembering: it presents as the assistant refusing, not as
an outage. An edit typed into the main composer became an ordinary chat turn and
the model answered that it could not edit images. That routing is fixed, and the
first check for any image failure is `http://127.0.0.1:8188`.

### The tunnel now runs from a user logon task — TESTED, not assumed

`DeepMatter tunnel (user)` runs cloudflared at sign-in as the logged-in user.
Registered without elevation, which is the point: it can be read, started and
stopped from an ordinary shell, so it can be *tested*. The SYSTEM task and the
`cloudflared` service could be neither read nor repaired without admin, and both
silently did nothing.

The task now starts `scripts/run-tunnel.ps1`, a small supervisor around
cloudflared. This replaced reliance on Task Scheduler's `RestartCount`: killing
the connector produced result `0xFFFFFFFF`, and Windows left the task stopped
instead of retrying. With the supervisor installed, killing only cloudflared
kept the task running and registered a replacement connector in about 15
seconds.

Proven rather than inferred on 2026-08-12: the task was installed from the
repository, started with `LastTaskResult` 267009, its connector was killed, and
the replacement served both Cloudflare IPv4 addresses. From inside the backend
container, `/healthz` and `/` returned 200 and
`/api/v1/agents/ani.mallya` returned the expected 401 on each address. Docker
Desktop's `AutoStart` setting is also true. An actual Windows reboot after this
supervisor change remains **UNVERIFIED** because verification did not interrupt
the operator's machine.

Signing in at logon rather than at boot is deliberate now, not a compromise.
Docker Desktop starts at sign-in, so a tunnel that starts at boot spends the gap
serving 502s to the world with no origin behind it. Both halves now wake
together.

`LastTaskResult` of `267009` (0x41301) means "currently running" and is the
correct state for this task, not a failure.

Still needing an elevated shell, and now only as tidying: `sc.exe delete
Cloudflared` for the dead service, and removing the old SYSTEM `DeepMatter
tunnel` task. Neither is harmful — both use the same corrected config, so if the
old task ever does fire it registers a second connector, which Cloudflare treats
as ordinary redundancy.

### The earlier attempt, and why it failed

The machine rebooted at 2026-08-11 08:49 and `deep-matter.com` served error
**1033** — no connector registered — with no cloudflared process running at all.
Docker came back correctly; the tunnel did not. The site was restored by hand
with a user-space `cloudflared tunnel run anios`. That failure led to the
user-level supervised task described above.

"The tunnel survives a reboot" was asserted from the task existing, never from a
reboot. The reboot has now happened and disproved it. Nothing about durable
public access should be believed here again without a reboot behind it.

Diagnosing it needs an elevated shell, which was unavailable when this was
found:

```powershell
schtasks /query /tn "DeepMatter tunnel" /v /fo LIST | findstr /i "TaskName Status Last"
```

`Last Result` distinguishes the three cases: `0x0` with nothing running means
cloudflared started and exited cleanly — most likely the boot race, where
networking is not ready, it cannot reach Cloudflare, and quits. `-RestartCount`
does not cover that, because it only fires when a task *fails*. A non-zero result
names the failure. Task-not-found means it needs recreating.

The likely fix is a startup delay plus restarting on any exit rather than only on
failure. The `Cloudflared` service is still registered, `Stopped / Automatic`,
and should be removed with `sc.exe delete Cloudflared` so two mechanisms are not
competing.

Note that a non-elevated shell can read neither `Get-ScheduledTask` nor
`schtasks /query` for a SYSTEM-principal task — both return access denied — so
the task's existence cannot be confirmed without elevation, only its effects.

**One connector is not evidence.** Every check for an hour showed a healthy
connector that was a foreground process started by hand; the service contributed
nothing the entire time. `cloudflared tunnel info anios` must show the connector
whose timestamp matches when the task started, and the only conclusive test is
stopping every other connector and confirming the site still serves.

`deep-matter.com` is registered through Cloudflare, so the zone is already in
the account and DNS can point at a tunnel without moving nameservers.

`scripts/start-tunnel.sh` runs a named tunnel when `ANIOS_TUNNEL_NAME` and
`ANIOS_PUBLIC_HOSTNAME` are set, and falls back to a quick tunnel otherwise. The
one-time setup is in [DEVELOPMENT_GUIDE.md](DEVELOPMENT_GUIDE.md) — it needs a
browser login to the Cloudflare account, so it is done by hand on the serving
machine, and there is no token to configure.

Until that setup is done the address is still a `trycloudflare.com` quick
tunnel, which **does not survive a reboot and takes a new random hostname every
time**. The script rewrites `DISCOVERY_CALENDAR_BASE_URL` to match in that mode;
recreate `backend` and `discovery-worker` afterwards so they read the new value.
A named tunnel rewrites nothing, because nothing changes.

`AUTH_COOKIE_SECURE` becomes true in the same step that makes the HTTPS origin
real, and not before: true over plain HTTP leaves no working login anywhere.

Docker services now carry `restart: unless-stopped`, so the stack itself
returns when Docker Desktop starts. ComfyUI and local-capabilities deliberately
do not — they hold the GPU. Installing the tunnel as a service is what makes the
public address survive a reboot too.

### Verify ingress from outside, never from this desktop

Some ingress resolves its own hostnames back locally, so `curl` from the host
returned 200 in ~14 ms while the public path was dead. That produced a false
"verified working" report that cost several rounds. Use a TLS handshake from
inside a container, which has its own network namespace, and check **every**
published address:

```python
socket.create_connection((ip, 443), 10)
ssl.create_default_context().wrap_socket(raw, server_hostname=HOST)
```

## The three reported defects are fixed; one is only reduced

All three were reproduced, changed, and re-exercised against the running stack.
Details in [CHANGELOG.md](CHANGELOG.md).

### 1. Explicit "remember this" — VERIFIED fixed

Was: the former phrase extractors returned no proposal for "Remember that my
dog is called Biscuit.", and the assistant claimed a save anyway. The current
typed semantic agent selects `semantic_fact` without a phrase rule, while the
pre-answer save-state prompt keeps the reply honest.

Re-run of the original reproduction, through the API with auth on:

```
CHAT 1 >  "...I cannot store this myself, just approve the save card below."
          memory_proposal: kind=semantic_fact "my dog is called Biscuit."
approve -> 201        semantic count 0 -> 1
CHAT 2 (new conversation) >  "Your dog's name is **Biscuit**."
```

The honesty half needed two attempts, which is worth remembering: told only
that it could not write to memory, the model answered "your personal memory has
been updated". A blanket prohibition invites a passive rephrasing. What worked
was deciding the proposal **before** generating the answer and stating the
turn's real save state in the prompt, with the sentence to write.

### 2. Presentation slides render empty — VERIFIED fixed

The mechanism was narrower than recorded. `statistic`, `quote`, `comparison`,
`chart`, and `table` already degraded to bullets through `_effective_layout`,
and the grammar already promotes each layout's fields to required. **`section`
was the only layout still discarding its points**, and it produces exactly the
reported symptom: a rule, a title, a purpose, nothing else. Confirmed by
compiling one directly (3 elements, both points gone) before changing anything.

Section slides now carry their points. Verified on three real generated decks:
12 slides, 0 rendering only a title and a purpose.

### 3. Deck content is ungrounded — reduced, not eliminated

`DeckResearch` runs one privacy-screened search per deck at outline time and
quotes bounded sources into the outline and every slide request. Verified live
inside `presentation-worker`: MCP → Tavily returned NASA and Smithsonian
sources, and the same brief sent verbatim had returned a slideware marketing
page until the brief was reduced to its subject.

Same brief, same model, measured:

| | ungrounded | grounded |
| --- | --- | --- |
| crewed landings | "seven" | "six" (correct) |
| dates | "Apollo 11 December 1969", "285-day intervals", "21-year span" | Apollo 8 December 1968 (correct) |
| crews | Apollo 12 crew wrong | Apollo 12 and 14 crews correct |

Two errors survived: the Apollo 11 module as "Eagles", and Charles Duke placed
on Apollo 15 (he flew Apollo 16). **Do not record this as solved.** Grounding
is wired, screened, metered, and degrades safely, but Qwen 3.5 4B with 1,024
tokens per slide still misreads its sources. The next lever is the slide token
budget or a stronger presentation role, not more prompt wording — that was
already tried here and is what the contract now says.

## Pin `mcp` below 2.0, and know why

`requirements.txt` had `mcp>=1.0.0` open-ended. Rebuilding the image today
resolved **mcp 2.0.0**, which removes `mcp.server.fastmcp` — imported by both
built-in stdio servers and the local-capabilities sidecar. The result: web
search and every MCP server broke in the containers while the host venv stayed
on 1.28.1 and the full test suite still passed. It is the rug-pull the MCP
guidance warns about, arriving through a Python dependency rather than a server.
Now pinned `<2.0.0` in both `requirements.txt` and `pyproject.toml`, verified as
1.29.0 with `fastmcp OK` in backend, presentation-worker, and
local-capabilities.

If MCP or search breaks after a rebuild, check the installed `mcp` version in
the container first.

## Things that look wrong and are not

- **`max_distance=0.96`** for image recall in `conversation_service.py`. It is
  not comparable to discovery's `0.08` novelty or `0.16` familiarity — those
  measure text embeddings, this measures image embeddings, where genuine
  matches sit around 0.90–0.94. Tightening it to 0.45 disabled recall and broke
  three tests. Any change needs the real distance distribution measured first.
- **Memory has no cross-user leakage.** Verified: zero nullable `user_id`
  columns in the schema, every retrieval filters on owner, and a guest asking
  for another account's data gets 403 rather than an empty list.

## Recently landed and verified

- Sign-up records an access request carrying the chosen username and password
  (hashed on arrival); approval creates the account outright. Verified through
  the public URL: request `201 pending` → login `401` → approve → login `200`.
- Accounts can be revoked (sessions destroyed immediately) or deleted. Deletion
  discovers its tables from `information_schema` rather than a hand-written
  list, because a hand-written list already shipped here missing eight
  discovery tables.
- Interactive search is metered per account, with a shared monthly pool sized
  to the real Tavily allowance and reconciled against their usage endpoint
  (which reported 37 credits spent the local counter knew nothing about).
  Usage is visible to the person spending it, not only the operator.
- Conversations are listed and deleted from the server; history no longer lives
  in one browser's `localStorage`.
- The sidebar opens as an overlay below 768px, so history is reachable on a
  phone.
- Scout's discovery profile is no longer injected into ordinary chat turns. A
  standing list of interests in every prompt bent unrelated answers toward
  them. Guarded by a test in `test_architecture_boundaries.py`.
- Image generation sends the subject rather than the sentence, and the global
  style suffix no longer names skin and hair — that wording put a person in
  every image, which is why a request for a car returned a woman leaning out of
  one.
