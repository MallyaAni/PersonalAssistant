# Browser tests (Playwright)

## The decisive gate

A frontend change is judged by one number: the full suite, run in the spark1
harness, reports **0 failed**. Every test either passes or is skipped by a
condition read from the environment, with a reason that names what it is
waiting for. There is no baseline of known failures to compare titles
against: a red test is a regression or a product defect, never "the usual".

Run it on spark1, outside 19:20-19:55 ET (the live nightly uses the machine):

```bash
WT=~/scratch/<worktree> PORT=<free port, 5181-5195> TAG=<name> \
  nohup ~/scratch/run_int_e2e.sh > ~/scratch/<name>_e2e.log 2>&1 &
```

`run_int_e2e.sh` serves `<worktree>/frontend` with vite inside
`mcr.microsoft.com/playwright:v1.61.1-noble` with `VITE_API_URL=` empty, so the
app calls same-origin `/api`, where the specs' mocks answer and nothing reaches
the live backend on port 8000. It runs `tsc`, then the whole suite with 10
workers (about 40 minutes), and writes
`<worktree>/frontend/test-results/<TAG>.json`. Read the verdict from the
report, not the log:

```bash
jq '.stats' <report>    # "unexpected" must be 0
# anything that did not pass or skip, by file and line
jq -r '.. | .specs? // empty | .[] | select(.ok | not) | "\(.file):\(.line) \(.title)"' <report>
# each skipped test's reason, once per test
jq -r '.. | .specs? // empty | .[] | .tests[] | .annotations[] | select(.type == "skip") | .description' <report> | sort | uniq -c
```

A targeted run of a few files is the same container pair: vite with
`-e VITE_API_URL=` on a free port, then
`npx playwright test e2e/<spec> --workers=4` with
`ANIOS_FRONTEND_URL=http://127.0.0.1:<port>`. On a workstation,
`npm run test:e2e` runs the suite minus `@live` against `npm run dev`, where
`VITE_API_URL` is unset and the app calls `http://localhost:8000`.

## Keeping a spec green in both setups

- **Mock the API by path**: `page.route('**/api/v1/...')`, never
  `http://localhost:8000/...`. The app calls `${VITE_API_URL}/api`, which is
  absolute under `npm run dev` and same-origin in the harness; an absolute
  pattern silently stops matching in one of them and the page gets vite's
  `index.html` instead of JSON. Compare a request's URL by its pathname for
  the same reason.
- **Pin what the page reads from the environment.** The automatic theme follows
  the browser's clock and is dark from 19:00 to 07:00 (the harness browser runs
  in UTC), so set `localStorage['anios.theme']` before asserting a colour, and
  install `page.clock` for anything dated.
- **The dev server runs React StrictMode**, which mounts effects twice: after a
  reload the chat's conversation-restore GET is sent twice and the first is
  cancelled (`net::ERR_ABORTED`). A spec that fails on any failed request
  accepts that one cancellation only when the same URL then completed (see
  `fundamental-source-versions.spec.ts`); every other failed request stays
  fatal.
- **A test that needs a live service** is tagged `@live` and its first line is
  `test.skip(<environment condition>, '<what to set, and what it contacts>')`.
  Never skip unconditionally, and never skip or loosen a test because the
  product is wrong: a real defect stays red and is reported with its evidence.

## What each conditional skip waits for

None of these variables is set in the harness, so a gate run reports these
27 tests as skipped and nothing else.

| Spec | Tests | Run when |
|---|---|---|
| `chat.spec.ts` | 12 `@live` turns: diagram artifact, provider reply, presentation hand-off, image generate/edit/analyse, image conversation routing, cancelled generation, entity/procedure/knowledge memory, prior-turn recall, response style, preferred name, personal memory, Scout memory | `ANIOS_E2E_LIVE=1`, against a live backend and models (the image tests also need ComfyUI) |
| `chat.spec.ts` | delete-all memory; future-safe Scout wording | `ANIOS_E2E_LIVE=1`, `ANIOS_E2E_USERNAME`, `ANIOS_E2E_BEARER_TOKEN` |
| `chat.spec.ts` | semantic Scout interests | `ANIOS_E2E_LIVE=1`, `ANIOS_E2E_USERNAME`, `ANIOS_E2E_PASSWORD` |
| `chat.spec.ts` | MCP tool in chat; hybrid internet MCP | `RUN_LIVE_TOOL_TESTS=1`, with the MCP servers running |
| `chat.spec.ts` | uncertain image analysis | `ANIOS_E2E_BEARER_TOKEN`, `ANIOS_E2E_VISION_IMAGE` (a real photo) |
| `chat.spec.ts` | password login keeps one conversation private | `ANIOS_E2E_AUTH_USER`, `ANIOS_E2E_AUTH_PASSWORD`, `ANIOS_E2E_AUTH_OTHER_USER`, `ANIOS_E2E_AUTH_OTHER_PASSWORD` |
| `chat.spec.ts` | invited profiles keep semantic context private | `ANIOS_E2E_REGISTER_{USER,PASSWORD,INVITE}_{A,B}`. Stale: it drives the invite-code form that `1fc0e4de` replaced with an access request, so it fails if run; rewrite it before relying on it |
| `presentations.spec.ts` | background deck, cancelled-deck cleanup, in-flight cancellation | `ANIOS_E2E_LIVE=1`, with the presentation worker |
| `presentations.spec.ts` | revises and downloads a persisted presentation | `ANIOS_E2E_LIVE=1`, `ANIOS_PRESENTATION_ID` |
| `visual-memory.live.spec.ts` | active uploaded image grounds a style question | `LIVE_AUTH_TOKEN`, `LIVE_CONVERSATION_ID`, `LIVE_IMAGE_ARTIFACT_ID` |
| `visual-memory.live.spec.ts` | historical image memory; Scout schedule confirmation | `LIVE_AUTH_TOKEN` |

The live tests that read the backend directly (`page.request`) expect it at
`http://localhost:8000`, so run them against `npm run dev` with
`VITE_API_URL` unset, not against the harness.
