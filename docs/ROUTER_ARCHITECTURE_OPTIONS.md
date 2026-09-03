# The router: why it keeps flaking, and what would change that

Written 2026-09-03 for a decision the operator has not made yet. Nothing
here is built. The facts are from this repository and this week's logs; the
outside sources are linked at the end.

## What the router is today

- **One model call per turn, on the main model.** `MainActionSelector.select`
  sends the message, recent history, a clock line and ~15-20 tool
  definitions (the built-ins, web search, the person's skills, any MCP
  aliases) to the reply model itself - DeepSeek V4 Flash on spark1, through
  the reasoning injector - with `tool_choice: "auto"`, and reads back a
  native tool call or none. There is no separate routing model in the live
  environment (`ROUTING_LLM_MODEL` is unset, so it falls through to the main
  model).
- **A dozen more judgements per turn, on the same model.** Readiness of a
  texting burst, the follow-up referent, the memory proposal, the check-in
  judgement, the search query, the second search angle, result ranking,
  event extraction, event descriptions, image intent. Each is one call at
  temperature 0 with a JSON schema.
- **Code rules where a judgement proved unreliable.** The repository's
  doctrine, applied a dozen times today alone: a bare "yes" with no
  conversation takes no tool; the check-in tool acts only on an ask; a
  tapback is complete by its nature; a search about "here" carries the
  place; the listing keeps to the asked window.
- **A measured gate.** 114 labelled selection cases with per-tool floors
  (0.60-0.80, each set below a measured rate), plus 86 functional test
  files on the real models, 44 of which contain single-shot assertions on a
  judgement.

## What goes wrong, with this week's numbers

| Symptom | Measured | Where it bit |
| --- | --- | --- |
| A judgement flips between runs | bare "yes" -> history search 1 in 4; a heart tapback "ambiguous" 1 in 3; the reply not naming the document 1 in 3 | three deploy gates refused on flakes today; each cost ~45 minutes |
| A tool grabs what is not a request | the check-in tool took "I put an offer in on a car" 3 in 3 after the person had opted in, and still 3 in 3 after the description said not to | fixed only by a code rule |
| A model-written query drops what matters | the router wrote "local events this week 2026-09-03" with no place for a Raleigh account; a second round drifted to New York pages | fixed only by code rules |
| Routing is slow | 5-10 s on a quiet system, 33-52 s while the deploy's sweep shares the model | the operator's events question took 92 s end to end |

Two things stand out. Every fix that held was a rule in code, never a
sentence in a prompt. And the router runs on the largest, slowest model we
have, sharing it with the reply and with every other judgement, so a busy
minute degrades both its speed and its steadiness.

## What the field does

- **Deterministic first layers.** Rule-based and embedding-based routing
  decide most traffic in milliseconds; an "index query instead of a model
  call" is typically 50x faster and, on intent classification with a
  labelled set, more accurate than prompting (semantic-router; vLLM Semantic
  Router; the 5G-core intent study). Their weakness is context: a follow-up
  that only makes sense with the last two turns.
- **Fewer tools per call.** Each related tool offered costs 1-8% selection
  accuracy; retrieving only the relevant tools for a turn recovers most of it
  (tool-calling best-practice write-ups, 2026).
- **Constrained decoding.** vLLM's structured outputs (`guided_choice`,
  `guided_json`, `tool_choice: required`) make the *format* of a decision
  certain and cheaper to generate, and expose the choice as a short,
  scoreable token sequence. They do not make the *judgement* steadier.
- **Confidence, then voting only when needed.** Self-certainty (how peaked
  the next-token distribution is) predicts whether an answer is right better
  than perplexity; adaptive self-consistency samples more only when the first
  samples disagree (NeurIPS 2025; "Reliability-Aware Adaptive
  Self-Consistency", 2026). For a router this means: read the log-probability
  of the chosen tool; when it is not decisive, sample three and vote.
- **A trained classifier in front, not just nearest neighbours.** SetFit
  (contrastive fine-tuning of a sentence-transformer) reaches competitive
  accuracy with about eight labelled examples per class, trains in minutes
  on a CPU, and classifies in under a millisecond - 67x faster than a
  zero-shot transformer pipeline and more accurate. The 114 selection cases
  are roughly eight per tool already. Production intent layers then cascade
  on confidence: route on a high score, confirm with the model in the middle
  band, hand the low band to the model outright (FrugalGPT-style cascades;
  "the intent classification layer most agent routers skip").
- **Optimizers, not hand-written prompt sentences, for the judgements that
  stay on the model.** DSPy's MIPROv2 tunes instructions and few-shot
  demonstrations against a labelled metric; on a detection task it reached
  ~86% without manual prompt engineering. This repository already has the
  labelled sets and the measured floors such an optimizer needs.
- **Small models fine-tuned for the job.** Sub-7B general models fail tool
  calling outright, but small models trained on it (Hammer 0.5-7B, xLAM 1B,
  Granite) match larger ones on selection when the schemas are explicit and a
  validator repairs arguments (BFCL; the Docker and TMLS evaluations). The
  114 cases and thousands of traced turns here are exactly the training set
  such a model needs. On a front-door routing benchmark (2026), Qwen2.5-0.5B
  went from 24.8% to 83% routing accuracy with fine-tuning, and Qwen2.5-1.5B
  reached 94.6% with no invalid outputs - so the data bar is lower than
  "thousands" once the tool set holds still.

## The options

**A. Keep the LLM router, make each decision cheap, scored and rare.**
1. Decide in two steps: a `guided_choice` over the tool *names* (one short
   constrained call), then arguments only for the chosen tool. Cheaper,
   parse-proof, and the choice has a log-probability.
2. Confidence-gated voting: when the chosen name's probability is below a
   measured threshold, sample three and take the majority. Costs nothing on
   the easy 90%.
3. Offer fewer tools per turn: withhold tools the turn cannot need
   (no image in view, no document, no skill named) - the registry already
   knows how to withhold sets.
Effort: days. Risk: low; measured with the existing 114 cases and floors.

**B. A trained classifier in front of the LLM, with a confidence cascade.**
Train a SetFit classifier on the 114 selection cases (plus traced turns as
they are corrected) to answer "which tool, or none" for a message with a
compact form of the last turn; classify in under a millisecond; route on a
high score, ask the LLM to confirm in the middle band, and hand the low
band to the LLM outright. Retrain in minutes whenever a tool or a case
changes; the same floors measure it. Every code rule written this week is
this path in miniature. It must never override a follow-up that depends on
the last turn (the "which one did you mean" cases) - those go to the model.
Effort: a few days. Risk: low-medium - a corpus that grows from traces, and
a threshold that has to be measured, not guessed.

**F. Optimize the remaining judgement prompts against their labelled sets.**
Readiness, ranking, the check-in judgement and event extraction each have
a measured floor and a labelled set. Run an optimizer (DSPy MIPROv2 or
GEPA) over instructions and demonstrations against those sets instead of
adding sentences by hand, and keep the winner only when the floor rises.
Effort: days per judgement. Risk: low - the floors gate it.

**C. A fine-tuned small router.**
Train a 0.5-4B model (Hammer/xLAM recipe, LoRA) on the cases plus traced
turns labelled by the current router and corrected by hand; run it greedily
on a dedicated endpoint (spark2 has room beside the vision model). 100-300
ms, deterministic, and the gate floors apply unchanged.
Effort: weeks, and it needs a few thousand labelled turns. Risk: medium -
the model is only as good as the corpus, and every new tool needs new
examples.

**D. Separate serving and hard timeouts for judgements.**
Give the router and the small judgements their own endpoint and strict
timeouts with deterministic fallbacks, so a busy minute cannot make routing
take 37 s or time out into a fail-open default. Infra, not code: a small
model on spark2, or a second vLLM instance with its own budget.

**E. Stop paying for flakes in the gate.**
Turn single-shot judgement assertions into rate assertions (N samples, a
floor below the measured rate - the pattern `test_the_whole_run_holds_a_floor`
already uses), and run a nightly judgement-rate report so a drift is seen as
a number rather than as a refused deploy. Keep code rules for anything that
must be true regardless of wording.

## Recommendation

Do E now (a day; it ends the flaky-gate tax without changing behaviour).
Then B: a SetFit classifier trained on the cases, in front of the router,
with a measured confidence cascade - it is the cheapest deterministic layer
on offer, and it turns the corpus we already keep into a decision in under
a millisecond. Then A for what falls through: guided choice, scored, voted
on only when the score is low, with fewer tools offered. Add D when routing
still shares a busy model. Use F for the judgements that stay on the model.
Consider C once the tool set has stopped changing weekly; the data bar is a
few hundred corrected turns per tool, not thousands.

What not to do: more prompt sentences. Three times today a sentence in a
description changed nothing that a ten-line rule then settled.

## Sources

- semantic-router and embedding routing: https://www.getmaxim.ai/articles/top-5-llm-routing-techniques/ , https://vllm-semantic-router.com/ , https://arxiv.org/pdf/2404.15869 , https://arxiv.org/pdf/2605.25701
- self-certainty and adaptive self-consistency: https://proceedings.neurips.cc/paper_files/paper/2025/file/1c7eff166a8e345f664f0faa8f4e4d2e-Paper-Conference.pdf , https://arxiv.org/html/2601.02970v1
- small-model tool calling and its failure modes: https://www.docker.com/blog/local-llm-tool-calling-a-practical-evaluation/ , https://www.tmls.nyc/research/tool-use-reliability , https://ai-tldr.dev/learn/llm-apis/function-calling/tool-calling-best-practices/ , https://arxiv.org/pdf/2510.03847
- fine-tuned routers and the benchmark: https://github.com/ShishirPatil/gorilla/blob/main/berkeley-function-call-leaderboard/README.md , https://arxiv.org/pdf/2410.04587 (Hammer), https://proceedings.mlr.press/v267/patil25a.html
- SetFit and cascades: https://github.com/huggingface/setfit , https://www.width.ai/post/what-is-setfit , https://tianpan.co/blog/2026-04-16-intent-classification-agent-routers , https://tianpan.co/blog/2025-11-03-llm-routing-model-cascades
- small-model front-door routing benchmark: https://arxiv.org/pdf/2604.02367 ; DSPy optimizers: https://arxiv.org/pdf/2412.15298 , https://thedataquarry.com/blog/learning-dspy-3-working-with-optimizers/
- tool retrieval at scale (not needed at twenty tools): https://next.redhat.com/2025/11/26/tool-rag-the-next-breakthrough-in-scalable-ai-agents/ , https://arxiv.org/html/2605.24660v1
- constrained decoding in vLLM: https://docs.vllm.ai/en/latest/features/structured_outputs/ , https://github.com/vllm-project/vllm/issues/39848
