import { createHash } from "node:crypto";
import { existsSync, readFileSync, writeFileSync } from "node:fs";
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

// Diagrams published on the page, in reading order, each with the scope it owns
// and the change that made it worth republishing.
const publishedDiagrams = [
  {
    name: "anios-system",
    title: "Full system",
    scope: "Every implemented component and its trust boundaries",
    change:
      "Added the in-process image encoder and Tavily as an external, untrusted vendor.",
  },
  {
    name: "runtime-deployment",
    title: "Runtime & deployment",
    scope: "Processes, ports, protocols, Compose topology",
    change:
      "Added the ONNX encoder inside the backend; Postgres now holds aligned image vectors alongside text memory.",
  },
  {
    name: "chat-orchestration",
    title: "Chat orchestration",
    scope: "Routing, memory planning, streaming, SSE contract",
    change:
      "Deterministic web-search and image-recall routing now run before the graph; the SSE contract gained image_matches.",
  },
  {
    name: "visual-artifact-subsystem",
    title: "Visual artifacts",
    scope: "Generation, upload, storage, vision analysis, retrieval",
    change:
      "Images are embedded at store time; ImageRetrievalPolicy applies a distance ceiling plus a runner-up margin.",
  },
  {
    name: "memory-subsystem",
    title: "Memory",
    scope: "Every memory form, write authority, retrieval, lifecycle",
    change:
      "Vision analysis text is indexed under its own purpose, kept out of the approval-gated user-fact path.",
  },
  {
    name: "frontend-subsystem",
    title: "Frontend",
    scope: "Client state, components, typed API and SSE client",
    change:
      "The stream client parses image_matches and renders matched images as cards in the transcript.",
  },
];

// Host-specific values generalized for publication. Canonical sources keep the
// real values; only the published copy is rewritten.
const publicationRedactions = [
  { find: "E:/AI/ComfyUI", replaceWith: "host ComfyUI install" },
];

const metrics = [
  { label: "Relevant queries", value: "14 / 14", note: "correct top-1 match", good: true },
  { label: "Distractor queries", value: "4 / 4", note: "correctly returned nothing", good: true },
  { label: "Distance ceiling", value: "0.96", note: "coarse filter", good: false },
  { label: "Runner-up margin", value: "0.015", note: "the real discriminator", good: false },
  { label: "Backend tests", value: "211", note: "ruff &middot; black &middot; mypy strict", good: false },
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
.canvas{margin-top:1.1rem;background:var(--panel);border:1px solid var(--rule);
        border-radius:12px;padding:1.1rem;overflow-x:auto}
.canvas svg{display:block;height:auto;max-width:none;min-width:860px;margin:0 auto}
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
  const moduleSource = readFileSync(fileURLToPath(import.meta.url), "utf8")
    .replace(/\r\n/g, "\n");
  digest.update(moduleSource);
  return digest.digest("hex");
}

// Compose the complete self-contained page.
function renderPageMarkup() {
  const navigation = publishedDiagrams
    .map((d) => `<a href="#${d.name}">${escapeHtml(d.title)}</a>`)
    .join("\n");

  const sections = publishedDiagrams
    .map((diagram, index) =>
      [
        `<section class="d" id="${diagram.name}">`,
        `<header class="dh">`,
        `<p class="eyebrow">${escapeHtml(diagram.scope)}</p>`,
        `<h2>${escapeHtml(diagram.title)}</h2>`,
        `<p class="change"><span class="tag">changed</span>${escapeHtml(diagram.change)}</p>`,
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
</style>
</head>
<body>
<div class="wrap">
<p class="eyebrow">AniOS &middot; canonical suite &middot; 9 diagrams synchronized</p>
<h1>Architecture after multimodal retrieval</h1>
<p class="lede">Six of the nine canonical diagrams changed in this pass. Each is rendered
below from its authoritative <code>.mmd</code> source, with the scope it owns and what moved.
The three unchanged views &mdash; memory overview, tool memory, and architecture maintenance &mdash; were
not touched, so their relationships still hold.</p>

<dl class="strip">
${cells}
</dl>

<nav class="jump">${navigation}</nav>

${sections}

<footer>Sources live in <code>docs/diagrams/*.mmd</code> and are the authority; the checked-in
SVGs and this page are both renderings of them. <code>npm run docs:diagram:check</code> verifies
every registered pair.</footer>
</div>
</body>
</html>`;
}

// Rebuild the published page from the current renders.
export function buildArchitecturePage() {
  writeFileSync(pagePath, renderPageMarkup(), "utf8");
  console.log("Rendered docs\\architecture.html");
}

// Fail when the published page no longer matches the rendered diagrams. Without
// this a diagram change deploys silently with the previous images embedded.
export function checkArchitecturePage() {
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
