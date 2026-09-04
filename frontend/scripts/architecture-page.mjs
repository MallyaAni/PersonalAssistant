import { createHash } from "node:crypto";
import { existsSync, readdirSync, readFileSync, writeFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const scriptDirectory = path.dirname(fileURLToPath(import.meta.url));
const frontendDirectory = path.resolve(scriptDirectory, "..");
const repositoryDirectory = path.resolve(frontendDirectory, "..");
const diagramDirectory = path.join(repositoryDirectory, "docs", "diagrams");
const pagePath = path.join(repositoryDirectory, "docs", "architecture.html");
const pageHashPrefix = "<!-- Page-Inputs-SHA256: ";
// Matches the stamp architecture-diagram.mjs writes into each rendered SVG.
const renderStampPrefix = "<!-- Render-Inputs-SHA256: ";
// The ML systems design document is published on the page as a section, so
// the serving decisions and their measurements live beside the diagrams they
// explain. It is an input to the page hash: editing it makes the page stale.
const mlDesignPath = path.join(repositoryDirectory, "docs", "ML_SYSTEM_DESIGN.md");

// Read the design document with normalized line endings.
function readMlDesign() {
  return readFileSync(mlDesignPath, "utf8").replace(/\r\n/g, "\n");
}

// Render the Markdown subset the design document uses - headings, paragraphs,
// bullet lists, pipe tables, fenced code, bold, italics, code spans, links -
// into HTML with everything escaped first. Deliberately small and
// dependency-free: no HTML pass-through, so a stray angle bracket in a table
// cell cannot become markup on the published page.
function renderMarkdown(markdown) {
  const inline = (text) =>
    escapeHtml(text)
      .replace(/`([^`]+)`/g, "<code>$1</code>")
      .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
      .replace(/(^|[\s(])\*([^*\s][^*]*)\*/g, "$1<em>$2</em>")
      .replace(/\[([^\]]+)\]\(([^)\s]+)\)/g, '<a href="$2">$1</a>');
  const out = [];
  let paragraph = [];
  let list = null;
  let table = null;
  let code = null;
  const flushParagraph = () => {
    if (paragraph.length) {
      out.push(`<p>${inline(paragraph.join(" "))}</p>`);
      paragraph = [];
    }
  };
  const flushList = () => {
    if (list) {
      out.push(`<ul>${list.map((item) => `<li>${inline(item)}</li>`).join("")}</ul>`);
      list = null;
    }
  };
  const flushTable = () => {
    if (table) {
      const [head, ...rows] = table;
      out.push(
        `<div class="scroll"><table><thead><tr>${head
          .map((cell) => `<th>${inline(cell)}</th>`)
          .join("")}</tr></thead><tbody>${rows
          .map((row) => `<tr>${row.map((cell) => `<td>${inline(cell)}</td>`).join("")}</tr>`)
          .join("")}</tbody></table></div>`,
      );
      table = null;
    }
  };
  const flushAll = () => {
    flushParagraph();
    flushList();
    flushTable();
  };
  for (const raw of markdown.split("\n")) {
    const line = raw.trimEnd();
    if (code !== null) {
      if (line.startsWith("```")) {
        out.push(`<pre><code>${escapeHtml(code.join("\n"))}</code></pre>`);
        code = null;
      } else {
        code.push(line);
      }
      continue;
    }
    if (line.startsWith("```")) {
      flushAll();
      code = [];
      continue;
    }
    const heading = /^(#{1,6})\s+(.*)$/.exec(line);
    if (heading) {
      flushAll();
      // The document's own title is the section header on the page.
      if (heading[1].length === 1) continue;
      const level = Math.min(heading[1].length + 1, 6);
      out.push(`<h${level}>${inline(heading[2])}</h${level}>`);
      continue;
    }
    if (line.startsWith("|")) {
      flushParagraph();
      flushList();
      const cells = line.replace(/^\||\|$/g, "").split("|").map((cell) => cell.trim());
      if (cells.every((cell) => /^:?-{3,}:?$/.test(cell))) continue;
      (table ??= []).push(cells);
      continue;
    }
    if (/^- /.test(line)) {
      flushParagraph();
      flushTable();
      (list ??= []).push(line.slice(2));
      continue;
    }
    if (list && /^\s+\S/.test(raw)) {
      list[list.length - 1] += ` ${line.trim()}`;
      continue;
    }
    if (line === "" || line === "---") {
      flushAll();
      continue;
    }
    flushList();
    flushTable();
    paragraph.push(line);
  }
  flushAll();
  return out.join("\n");
}

const proseStyles = `
.prose .prose-body{padding:.6rem 1.25rem 1.4rem}
.prose-body h3{margin:1.7rem 0 .45rem;font-size:1.18rem;line-height:1.3}
.prose-body h4{margin:1.2rem 0 .3rem;font-size:1rem}
.prose-body p,.prose-body li{max-width:78ch}
.prose-body ul{padding-left:1.2rem}
.prose-body table{border-collapse:collapse;width:100%;font-size:.88rem;margin:.6rem 0 1rem}
.prose-body th,.prose-body td{border:1px solid var(--rule);padding:.42rem .6rem;vertical-align:top;text-align:left}
.prose-body th{background:var(--accent-soft)}
.prose-body .scroll{overflow-x:auto}
.prose-body code{font-family:var(--mono);font-size:.85em;background:var(--accent-soft);padding:.05em .3em;border-radius:3px}
.prose-body pre{overflow-x:auto;background:var(--panel);border:1px solid var(--rule);padding:.8rem;font-size:.85rem}
.prose-body a{color:var(--accent)}
`;

// Diagrams published on the page, in reading order, each with the scope it owns
// and the single engineering question it answers.
const publishedDiagrams = [
  {
    name: "anios-system",
    title: "Full system",
    scope: "Major components, ownership, and external boundaries",
    change: "How a user request moves through AniOS at a glance.",
  },
  {
    name: "runtime-deployment",
    title: "Runtime & deployment",
    scope: "Processes, ports, stores, and host services",
    change: "What runs in Docker Compose and what runs on the host.",
  },
  {
    name: "inference-scaling-target",
    title: "Inference scaling target",
    scope: "Role routing, serving pools, placement, and operations",
    change: "How the local profile can scale without changing agent authority.",
  },
  {
    name: "ml-serving-design",
    title: "ML serving design",
    scope: "Models, quantisation, KV cache, memory, retrieval gates, decoding",
    change: "Which model runs where at what precision, and every serving knob that was measured.",
  },
  {
    name: "chat-orchestration",
    title: "Chat orchestration",
    scope: "Routing, delegation, tools, and streaming",
    change: "How one chat request becomes a visible result: the turn's single action decision, delegation, tools, and streaming.",
  },
  {
    name: "search-research-subsystem",
    title: "Search & research",
    scope: "Privacy, providers, quota, and source handling",
    change: "How a safe public query becomes a cited answer.",
  },
  {
    name: "memory-overview",
    title: "Memory overview",
    scope: "Short- and long-term types, lifecycle, and user control",
    change: "How each memory category helps a turn and remains controllable.",
  },
  {
    name: "document-knowledge",
    title: "Document knowledge",
    scope: "Uploads, parsing, chunks, retrieval, and quoted answers",
    change: "How a shared PDF or Word file becomes cited answers and attributed memory.",
  },
  {
    name: "context-management",
    title: "Context management",
    scope: "Token accounting, dedup, cache-aware ordering, and the bounded digest",
    change: "How a turn's material becomes a bounded prompt, and what makes turn two fast.",
  },
  {
    name: "memory-subsystem",
    title: "Memory subsystem",
    scope: "Short- and long-term types, write policy, retrieval, and storage",
    change: "How implemented memory forms become bounded assistant context.",
  },
  {
    name: "authentication-subsystem",
    title: "Authentication & ownership",
    scope: "Invite accounts, sessions, and stable data ownership",
    change: "How a login becomes one server-derived owner across every request.",
  },
  {
    name: "discovery-subsystem",
    title: "Scout discovery",
    scope: "Profile facts, travel, ranking, familiarity, and durable sweeps",
    change: "How approved preferences become local findings without losing user control.",
  },
  {
    name: "imessage-bridge",
    title: "iMessage bridge",
    scope: "Allowlisting, message ingress, turn execution, and delivery",
    change: "How an allowed text becomes a full AniOS turn and returns through the Mac.",
  },
  {
    name: "group-chats-subsystem",
    title: "Group chats — a room is an account",
    scope: "Addressed-only reads, the membership wall, tastes, attribution, delivery to the chat",
    change: "How a message in an iMessage group reaches the assistant only when it was meant for it, what the room may know about each member, and whose memory a fact lands in.",
  },
  {
    name: "scheduled-tasks-subsystem",
    title: "Tasks & skills",
    scope: "Scheduling, learned workflows, unattended turns, and delivery",
    change: "How a request becomes a durable task or reusable skill and later runs safely.",
  },
  {
    name: "agent-scout",
    title: "Scout — what the model decides",
    scope: "Aiming, ranking, and description against deterministic qualification",
    change: "Which judgements in a sweep are the model's and which are the code's.",
  },
  {
    name: "agent-deck",
    title: "Deck — what the model decides",
    scope: "Content and slide shape against fixed geometry and promotion",
    change: "Why a generated deck cannot invent a figure or promote itself.",
  },
  {
    name: "agent-diagram",
    title: "Diagram — what the model decides",
    scope: "Mermaid source against a validator that can refuse it",
    change: "How a diagram that will not render is stopped before it is stored.",
  },
  {
    name: "agent-memory",
    title: "Memory capture — what the model decides",
    scope: "Typed candidates against visible approval and no persistence authority",
    change: "Why nothing is remembered until a person approves it.",
  },
  {
    name: "agent-trading",
    title: "Trading — the personal autopsy",
    scope: "A person's own history read as repeated behaviours, costs, and a plan",
    change: "What their own trading record keeps doing, and what to stop, start, and keep.",
  },
  {
    name: "tool-memory-subsystem",
    title: "Tool memory & MCP",
    scope: "Discovery, semantic selection, and safe invocation",
    change: "How AniOS finds and invokes one eligible MCP tool.",
  },
  {
    name: "visual-artifact-subsystem",
    title: "Visual artifacts",
    scope: "Diagrams, images, vision, and private storage",
    change: "How visual requests become owned, reusable artifacts.",
  },
  {
    name: "visual-memory-editing-target",
    title: "Visual memory & editing target",
    scope: "Implemented editing and planned semantic memory",
    change: "What works today and what remains planned for reliable visual recall.",
  },
  {
    name: "presentation-subsystem",
    title: "Presentations",
    scope: "Durable jobs, specialist generation, and editable output",
    change: "How a background job produces a validated editable PowerPoint.",
  },
  {
    name: "architecture-maintenance-subsystem",
    title: "Architecture maintenance",
    scope: "Evidence, LLM candidates, review, and publication",
    change: "How diagrams change without giving an LLM overwrite authority.",
  },
  {
    name: "frontend-subsystem",
    title: "Frontend",
    scope: "Session state, views, actions, and API boundary",
    change: "How browser state and backend results reach each product view.",
  },
];

// Host-specific values generalized for publication. Canonical sources keep the
// real values; only the published copy is rewritten.
const publicationRedactions = [
  { find: "E:/AI/ComfyUI", replaceWith: "host ComfyUI install" },
];

// Count the canonical Mermaid sources on disk, which is the denominator the
// "synchronized" claim depends on. Reading the directory rather than trusting
// the list above is the point: four agent views were added to the renderer and
// the catalog and never published here, while a hardcoded "15 / 15" went on
// claiming the page was complete.
function countCanonicalSources() {
  return readdirSync(diagramDirectory).filter((entry) => entry.endsWith(".mmd"))
    .length;
}

const metrics = [
  {
    label: "Turn routing",
    value: "Native tool call",
    note: "MainActionSelector &middot; one model decision, all options",
    good: false,
  },
  {
    label: "Generation",
    value: "DeepSeek V4 Flash",
    note: "official FP8 &middot; tensor-parallel across both Sparks &middot; 1M context",
    good: false,
  },
  {
    label: "Vision",
    value: "Qwen3-VL-8B",
    note: "AWQ on spark2 &middot; NVFP4 emits wrong output on sm_121",
    good: false,
  },
  {
    label: "Embeddings",
    value: "Nomic v1.5, aligned",
    note: "768-dim text and image in one space, one index",
    good: false,
  },
  {
    label: "Image generation",
    value: "Not deployed",
    note: "ComfyUI left with the desktop &middot; fails loudly, not silently",
    good: false,
  },
  {
    label: "Canonical views",
    value: `${publishedDiagrams.length} / ${countCanonicalSources()}`,
    note: "Mermaid, SVG, and page synchronized",
    good: publishedDiagrams.length === countCanonicalSources(),
  },
  {
    label: "Backend suite",
    value: "2052 collected",
    note: "collected, not asserted passing &mdash; DB-backed tests need a host",
    good: true,
  },
  {
    label: "Deploy gate",
    value: "7 pass, 0 skip",
    note: "routing matrix against the real router &middot; a skip counts as a failure",
    good: true,
  },
];

const pageStyles = `:root{
  --ground:#fbfcfd; --panel:#ffffff; --ink:#0f161d; --muted:#5b6b7a;
  --rule:#dde5ec; --accent:#1b6d88; --accent-soft:#e6f1f5; --good:#2c7a53;
  --mono:ui-monospace,SFMono-Regular,"SF Mono",Menlo,Consolas,monospace;
  --sans:system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;
}
@media (prefers-color-scheme:dark){
  :root{--ground:#0d1319;--panel:#141c24;--ink:#dde6ee;--muted:#8697a7;
        --rule:#24303b;--accent:#5fb3cf;--accent-soft:#162934;--good:#5cc48d;}
}
*{box-sizing:border-box}
body{margin:0;background:var(--ground);color:var(--ink);font-family:var(--sans);
     line-height:1.6;-webkit-font-smoothing:antialiased}
.wrap{max-width:1120px;margin:0 auto;
      padding:clamp(1.5rem,4vw,3.5rem) clamp(1rem,3vw,2rem) 5rem}
.eyebrow{font-family:var(--mono);font-size:.7rem;letter-spacing:.09em;
         text-transform:uppercase;color:var(--muted);margin:0}
h1{font-size:clamp(1.9rem,4.4vw,2.9rem);line-height:1.12;margin:.5rem 0 0;
   letter-spacing:-.022em;text-wrap:balance;font-weight:640}
.lede{color:var(--muted);max-width:62ch;margin:.9rem 0 0;font-size:1.03rem}
.contract{margin:1.35rem 0 0;padding:1rem 1.1rem;border:1px solid var(--rule);
          border-left:3px solid var(--accent);border-radius:8px;background:var(--panel);
          max-width:78ch;font-size:.94rem}
.contract strong{color:var(--accent)}
.strip{display:grid;gap:1px;background:var(--rule);border:1px solid var(--rule);
       border-radius:10px;overflow:hidden;margin:2.4rem 0 0;
       grid-template-columns:repeat(auto-fit,minmax(158px,1fr))}
.cell{background:var(--panel);padding:.95rem 1.05rem}
.cell dt{font-family:var(--mono);font-size:.66rem;letter-spacing:.08em;
         text-transform:uppercase;color:var(--muted);margin:0}
.cell dd{margin:.35rem 0 0;font-size:1.32rem;font-weight:620;
         font-variant-numeric:tabular-nums;letter-spacing:-.015em}
.cell dd small{display:block;font-size:.74rem;font-weight:450;color:var(--muted);
               letter-spacing:0;margin-top:.15rem}
.ok{color:var(--good)}
nav.jump{position:sticky;top:0;z-index:5;
     background:color-mix(in srgb,var(--ground) 92%,transparent);
     backdrop-filter:blur(8px);border-bottom:1px solid var(--rule);
     margin:2.6rem 0 0;display:flex;gap:.35rem;overflow-x:auto;padding:.55rem 0}
nav.jump a{flex:none;font-family:var(--mono);font-size:.72rem;color:var(--muted);
       text-decoration:none;padding:.35rem .6rem;border-radius:6px;white-space:nowrap}
nav.jump a:hover,nav.jump a:focus-visible{color:var(--accent);
       background:var(--accent-soft);outline:none}
.d{margin:3.4rem 0 0;scroll-margin-top:4rem}
.dh{border-left:2px solid var(--accent);padding-left:.95rem}
.d h2{font-size:1.32rem;margin:.2rem 0 0;letter-spacing:-.015em;font-weight:620}
.change{margin:.5rem 0 0;color:var(--muted);font-size:.9rem;max-width:70ch}
.tag{font-family:var(--mono);font-size:.62rem;text-transform:uppercase;
     letter-spacing:.08em;color:var(--accent);background:var(--accent-soft);
     padding:.15rem .42rem;border-radius:4px;margin-right:.5rem;vertical-align:.06em}
.diagram-tools{display:flex;align-items:center;gap:.5rem;flex-wrap:wrap;margin-top:.8rem}
.diagram-tools a,.diagram-tools button{font:inherit;font-family:var(--mono);font-size:.68rem;
       color:var(--accent);background:var(--panel);border:1px solid var(--rule);
       border-radius:6px;padding:.32rem .55rem;text-decoration:none;cursor:pointer}
.diagram-tools a:hover,.diagram-tools a:focus-visible,
.diagram-tools button:hover,.diagram-tools button:focus-visible{
       background:var(--accent-soft);outline:2px solid transparent}
.zoom-output{font-family:var(--mono);font-size:.68rem;color:var(--muted);
       min-width:3.3rem;text-align:center}
.canvas{margin-top:1.1rem;background:var(--panel);border:1px solid var(--rule);
        border-radius:12px;padding:1.1rem;overflow-x:auto}
.canvas svg{display:block;width:calc(100% * var(--diagram-scale,1));height:auto;
        max-width:none;min-width:860px;margin:0 auto;transform-origin:top left}
footer{margin-top:4rem;padding-top:1.4rem;border-top:1px solid var(--rule);
       color:var(--muted);font-size:.86rem;max-width:70ch}
code{font-family:var(--mono);font-size:.88em;background:var(--accent-soft);
     padding:.1rem .32rem;border-radius:4px}
a{color:var(--accent)}
@media (prefers-reduced-motion:reduce){*{animation:none!important;transition:none!important}}`;

// Escape text taken from diagram metadata before placing it in markup.
function escapeHtml(value) {
  return value
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

// Read one rendered diagram, isolate its style scope, and apply redactions.
function inlineDiagram(diagramName, index) {
  const svgPath = path.join(diagramDirectory, `${diagramName}.svg`);
  if (!existsSync(svgPath)) {
    throw new Error(`Render ${diagramName}.svg before building the page.`);
  }
  const rendered = readFileSync(svgPath, "utf8");
  const markup = rendered.slice(rendered.indexOf("<svg"));
  // Every render uses id="my-svg" and scopes its whole stylesheet to it, so
  // inlining several copies would share one namespace and overwrite each other.
  let isolated = markup.replaceAll("my-svg", `diagram${index}`);
  for (const { find, replaceWith } of publicationRedactions) {
    isolated = isolated.replaceAll(find, replaceWith);
  }
  return isolated;
}

// Read the render fingerprint each SVG carries, which encodes its Mermaid
// source, the shared config, and the pinned renderer version.
function readRenderFingerprint(diagramName) {
  const svgPath = path.join(diagramDirectory, `${diagramName}.svg`);
  if (!existsSync(svgPath)) {
    throw new Error(`Render ${diagramName}.svg before building the page.`);
  }
  const rendered = readFileSync(svgPath, "utf8");
  const start = rendered.indexOf(renderStampPrefix);
  if (start === -1) {
    throw new Error(
      `${diagramName}.svg has no render fingerprint. Run docs:diagram first.`,
    );
  }
  return rendered.slice(start + renderStampPrefix.length).split(" ")[0].trim();
}

// Fingerprint every input so the check can detect a stale published page.
//
// This deliberately hashes each diagram's stamped source fingerprint rather
// than its SVG bytes. Mermaid emits fresh element identifiers on every render,
// so hashing the markup would report the page as stale after a re-render that
// changed nothing. Hashing the stamps means the page is stale only when a
// diagram's source, the render config, the renderer version, the published
// selection, or this module's layout actually changed.
function calculatePageInputsHash() {
  const digest = createHash("sha256");
  for (const diagram of publishedDiagrams) {
    digest.update(diagram.name);
    digest.update("\0");
    digest.update(readRenderFingerprint(diagram.name));
    digest.update("\0");
  }
  // The canonical count is an input because the page prints it. Without this a
  // diagram added to the catalog but never published would leave the stored
  // page saying one thing and a fresh build saying another, with the check
  // reporting neither.
  digest.update(String(countCanonicalSources()));
  digest.update("\0");
  // The published ML design section is rendered from the document, so an
  // edited document must read as a stale page until it is rebuilt.
  digest.update(readMlDesign());
  digest.update("\0");
  const moduleSource = readFileSync(fileURLToPath(import.meta.url), "utf8")
    .replace(/\r\n/g, "\n");
  digest.update(moduleSource);
  return digest.digest("hex");
}

// Compose the complete self-contained page.
function renderPageMarkup() {
  const navigation = [
    `<a href="#ml-system-design">ML system design</a>`,
    ...publishedDiagrams.map((d) => `<a href="#${d.name}">${escapeHtml(d.title)}</a>`),
  ].join("\n");

  const mlDesignSection = [
    `<section class="d prose" id="ml-system-design">`,
    `<header class="dh">`,
    `<p class="eyebrow">ML systems engineering</p>`,
    `<h2>ML system design: what was measured, chosen, and rejected</h2>`,
    `<p class="change"><span class="tag">source</span>docs/ML_SYSTEM_DESIGN.md - quantisation, KV cache, parallelism, context against memory, retrieval thresholds, and decoding, each with the options considered, the measurements, the choice, and what would change it. Maintained in the same change as any serving flag, model, cache, threshold, or budget change.</p>`,
    `</header>`,
    `<div class="prose-body">${renderMarkdown(readMlDesign())}</div>`,
    `</section>`,
  ].join("\n");

  const sections = publishedDiagrams
    .map((diagram, index) =>
      [
        `<section class="d" id="${diagram.name}" data-diagram>`,
        `<header class="dh">`,
        `<p class="eyebrow">${escapeHtml(diagram.scope)}</p>`,
        `<h2>${escapeHtml(diagram.title)}</h2>`,
        `<p class="change"><span class="tag">focus</span>${escapeHtml(diagram.change)}</p>`,
        `<div class="diagram-tools">`,
        `<a href="diagrams/${diagram.name}.svg" target="_blank" rel="noreferrer">Open full-size SVG</a>`,
        `<a href="diagrams/${diagram.name}.mmd">View Mermaid source</a>`,
        `<button type="button" data-zoom-delta="-0.25" aria-label="Zoom out ${escapeHtml(diagram.title)}">&minus;</button>`,
        `<button type="button" data-zoom-reset>Reset</button>`,
        `<button type="button" data-zoom-delta="0.25" aria-label="Zoom in ${escapeHtml(diagram.title)}">+</button>`,
        `<span class="zoom-output" aria-live="polite">100%</span>`,
        `</div>`,
        `</header>`,
        `<div class="canvas">${inlineDiagram(diagram.name, index)}</div>`,
        `</section>`,
      ].join("\n"),
    )
    .join("\n");

  const cells = metrics
    .map(
      (m) =>
        `<div class="cell"><dt>${m.label}</dt>` +
        `<dd${m.good ? ' class="ok"' : ""}>${m.value}` +
        `<small>${m.note}</small></dd></div>`,
    )
    .join("\n");

  return `<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>AniOS architecture &mdash; current diagrams</title>
<meta name="description" content="Canonical architecture diagrams for AniOS, a local-first personal AI system.">
${pageHashPrefix}${calculatePageInputsHash()} -->
<style>
${pageStyles}
${proseStyles}
</style>
</head>
<body>
<div class="wrap">
<p class="eyebrow">AniOS &middot; canonical suite &middot; ${publishedDiagrams.length} diagrams synchronized</p>
<h1>How AniOS routes work, assigns models, and preserves authority</h1>
<p class="lede">A manager-facing map of the implemented local-first system. Start with the
full-system view, then use each subsystem diagram to trace ownership, model calls, persistence,
trust boundaries, and user-visible lifecycle from entry point to result. Model choices here are
decided by measurement, not model cards: the <a href="evals/index.html">evaluation record</a>
holds the blind-judged comparisons, verbatim answers, and serving numbers behind each decision.</p>
<p class="contract"><strong>Current orchestration contract:</strong>
<code>MainActionSelector</code> offers live search, image generation/edit, diagrams, presentation
delegation, and the user's own registered MCP tools to the main model as one native tool-calling
decision per turn, made from genuine understanding rather than a regex or a narrow bounded
classifier judging the question alone. Ordinary responses, the routing decision itself, presentation
plans, diagram specifications, memory proposals and Scout's judgement calls all run on
DeepSeek-V4-Flash at official FP8, served tensor-parallel across two DGX Sparks; the engine enforces
JSON schemas, which is what allowed those callers to stop being pinned to a smaller grammar model.
Vision is the one remaining Qwen role. Nomic supplies text embeddings through a separate vLLM
service. Application code &mdash; never the models &mdash; owns
authorization, persistence, provider policy, and execution.</p>

<dl class="strip">
${cells}
</dl>

<nav class="jump">${navigation}</nav>

${mlDesignSection}

${sections}

<footer>Sources live in <code>docs/diagrams/*.mmd</code> and are the authority; the checked-in
SVGs and this page are both renderings of them. <code>npm run docs:diagram:check</code> verifies
every registered pair.</footer>
</div>
<script>
// Apply a bounded visual scale to one diagram without changing its source.
function setDiagramZoom(section, requestedZoom) {
  const zoom = Math.min(3, Math.max(0.75, requestedZoom));
  section.dataset.zoom = String(zoom);
  section.querySelector(".canvas").style.setProperty("--diagram-scale", zoom);
  section.querySelector(".zoom-output").textContent = \`\${Math.round(zoom * 100)}%\`;
}

// Handle one zoom control while keeping each subsystem view independent.
function handleDiagramZoom(event) {
  const section = event.currentTarget.closest("[data-diagram]");
  const currentZoom = Number(section.dataset.zoom || "1");
  const nextZoom = event.currentTarget.hasAttribute("data-zoom-reset")
    ? 1
    : currentZoom + Number(event.currentTarget.dataset.zoomDelta);
  setDiagramZoom(section, nextZoom);
}

for (const control of document.querySelectorAll(
  "[data-zoom-delta], [data-zoom-reset]",
)) {
  control.addEventListener("click", handleDiagramZoom);
}
</script>
</body>
</html>`;
}

// Rebuild the published page from the current renders.
export function buildArchitecturePage() {
  writeFileSync(pagePath, renderPageMarkup(), "utf8");
  console.log("Rendered docs\\architecture.html");
}

// Fail when the published page omits a canonical view or trails current renders.
export function checkArchitecturePage() {
  const canonicalSourceCount = countCanonicalSources();
  if (publishedDiagrams.length !== canonicalSourceCount) {
    throw new Error(
      `docs/architecture.html publishes ${publishedDiagrams.length} of ${canonicalSourceCount} canonical diagrams.`,
    );
  }
  if (!existsSync(pagePath)) {
    throw new Error(
      "docs/architecture.html is missing. Run npm.cmd run docs:diagram from frontend/.",
    );
  }
  const published = readFileSync(pagePath, "utf8");
  const start = published.indexOf(pageHashPrefix);
  if (start === -1) {
    throw new Error(
      "docs/architecture.html has no render fingerprint. Run npm.cmd run docs:diagram from frontend/.",
    );
  }
  const recorded = published
    .slice(start + pageHashPrefix.length)
    .split(" ")[0]
    .trim();
  if (recorded !== calculatePageInputsHash()) {
    throw new Error(
      "docs/architecture.html is stale. Run npm.cmd run docs:diagram from frontend/.",
    );
  }
  console.log("Published architecture page is synchronized.");
}
