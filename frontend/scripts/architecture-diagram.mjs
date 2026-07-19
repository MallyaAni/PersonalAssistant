import { createHash } from "node:crypto";
import { spawnSync } from "node:child_process";
import { existsSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { chromium } from "@playwright/test";

const scriptDirectory = path.dirname(fileURLToPath(import.meta.url));
const frontendDirectory = path.resolve(scriptDirectory, "..");
const repositoryDirectory = path.resolve(frontendDirectory, "..");
const diagramDirectory = path.join(repositoryDirectory, "docs", "diagrams");
const diagramNames = [
  "anios-system",
  "runtime-deployment",
  "chat-orchestration",
  "memory-subsystem",
  "tool-memory-subsystem",
  "visual-artifact-subsystem",
  "architecture-maintenance-subsystem",
  "frontend-subsystem",
];
const mermaidConfigPath = path.join(
  repositoryDirectory,
  "docs",
  "diagrams",
  "mermaid.config.json",
);
const mermaidCliPath = path.join(
  frontendDirectory,
  "node_modules",
  "@mermaid-js",
  "mermaid-cli",
  "src",
  "cli.js",
);
const hashPrefix = "<!-- Render-Inputs-SHA256: ";

// Resolve one canonical source and generated output pair by diagram name.
function diagramPaths(diagramName) {
  return {
    sourcePath: path.join(diagramDirectory, `${diagramName}.mmd`),
    outputPath: path.join(diagramDirectory, `${diagramName}.svg`),
  };
}

// Calculate a cross-platform fingerprint for one diagram's render inputs.
function calculateRenderInputsHash(sourcePath) {
  const rendererPackagePath = path.join(
    frontendDirectory,
    "node_modules",
    "@mermaid-js",
    "mermaid-cli",
    "package.json",
  );
  const rendererVersion = JSON.parse(readFileSync(rendererPackagePath, "utf8"))
    .version;
  const normalizedSource = readFileSync(sourcePath, "utf8").replace(
    /\r\n/g,
    "\n",
  );
  const normalizedConfig = readFileSync(mermaidConfigPath, "utf8").replace(
    /\r\n/g,
    "\n",
  );
  return createHash("sha256")
    .update(normalizedSource)
    .update("\0")
    .update(normalizedConfig)
    .update("\0")
    .update(rendererVersion)
    .digest("hex");
}

// Render one canonical Mermaid source with the installed browser.
function renderDiagram(sourcePath, destinationPath) {
  const browserPath = chromium.executablePath();
  if (!existsSync(browserPath)) {
    throw new Error(
      `Playwright Chromium is required to render diagrams: ${browserPath}`,
    );
  }

  const puppeteerConfigPath = path.join(
    tmpdir(),
    `anios-mermaid-puppeteer-${process.pid}.json`,
  );
  writeFileSync(
    puppeteerConfigPath,
    JSON.stringify({ executablePath: browserPath, headless: true }),
  );

  const result = spawnSync(
    process.execPath,
    [
      mermaidCliPath,
      "--input",
      sourcePath,
      "--output",
      destinationPath,
      "--configFile",
      mermaidConfigPath,
      "--puppeteerConfigFile",
      puppeteerConfigPath,
      "--backgroundColor",
      "transparent",
      "--quiet",
    ],
    { stdio: "inherit" },
  );
  rmSync(puppeteerConfigPath, { force: true });
  if (result.error) {
    throw new Error(`Mermaid rendering could not start: ${result.error.message}`);
  }
  if (result.status !== 0) {
    throw new Error(`Mermaid rendering failed with exit code ${result.status}`);
  }
}

// Stamp one rendered SVG with the source fingerprint used to create it.
function stampRenderedDiagram(sourcePath, outputPath) {
  const svg = readFileSync(outputPath, "utf8").replace(
    /^<!-- (?:Source|Render-Inputs)-SHA256: [a-f0-9]{64} -->\r?\n/,
    "",
  );
  writeFileSync(
    outputPath,
    `${hashPrefix}${calculateRenderInputsHash(sourcePath)} -->\n${svg}`,
  );
}

// Confirm that one generated SVG matches its current canonical source.
function checkRenderedDiagram(diagramName, sourcePath, outputPath) {
  const svg = readFileSync(outputPath, "utf8");
  const expectedMarker = `${hashPrefix}${calculateRenderInputsHash(sourcePath)} -->`;
  if (!svg.startsWith(expectedMarker)) {
    throw new Error(
      `${diagramName}.svg is stale. Run npm.cmd run docs:diagram from frontend/.`,
    );
  }

  const temporarySvgPath = path.join(
    tmpdir(),
    `anios-${diagramName}-validation-${process.pid}.svg`,
  );
  try {
    renderDiagram(sourcePath, temporarySvgPath);
  } finally {
    rmSync(temporarySvgPath, { force: true });
  }
}

// Render and fingerprint every maintained architecture diagram.
function renderAllDiagrams() {
  for (const diagramName of diagramNames) {
    const { sourcePath, outputPath } = diagramPaths(diagramName);
    renderDiagram(sourcePath, outputPath);
    stampRenderedDiagram(sourcePath, outputPath);
    console.log(`Rendered docs\\diagrams\\${diagramName}.svg`);
  }
}

// Check synchronization and Mermaid syntax for the complete diagram suite.
function checkAllDiagrams() {
  for (const diagramName of diagramNames) {
    const { sourcePath, outputPath } = diagramPaths(diagramName);
    checkRenderedDiagram(diagramName, sourcePath, outputPath);
  }
  console.log(`${diagramNames.length} architecture diagrams are synchronized.`);
}

// Render one unregistered review candidate without stamping canonical metadata.
function validateCandidateDiagram(sourceArgument, outputArgument) {
  if (!sourceArgument || !outputArgument) {
    throw new Error(
      "Usage: architecture-diagram.mjs validate <source.mmd> <output.svg>",
    );
  }
  const sourcePath = path.resolve(process.cwd(), sourceArgument);
  const outputPath = path.resolve(process.cwd(), outputArgument);
  for (const diagramName of diagramNames) {
    const canonical = diagramPaths(diagramName);
    if (
      sourcePath === canonical.sourcePath ||
      outputPath === canonical.outputPath
    ) {
      throw new Error("Candidate validation cannot overwrite canonical diagrams.");
    }
  }
  renderDiagram(sourcePath, outputPath);
  console.log(`Rendered review candidate ${outputPath}`);
}

// Runs the requested render or synchronization check command.
function main() {
  const command = process.argv[2];
  if (command === "render") {
    renderAllDiagrams();
    return;
  }
  if (command === "check") {
    checkAllDiagrams();
    return;
  }
  if (command === "validate") {
    validateCandidateDiagram(process.argv[3], process.argv[4]);
    return;
  }
  throw new Error(
    "Usage: architecture-diagram.mjs <render|check|validate>",
  );
}

main();
