import { readFileSync, statSync } from "node:fs";
import { gzipSync } from "node:zlib";

const manifestPath = new URL("../dist/.vite/manifest.json", import.meta.url);
const distUrl = new URL("../dist/", import.meta.url);
const manifest = JSON.parse(readFileSync(manifestPath, "utf8"));
const sensitivePatterns = JSON.parse(
  readFileSync(new URL("../src/sensitive-content-patterns.json", import.meta.url), "utf8"),
);

const internalEntries = [
  "src/shells/InternalShell.tsx",
  "src/workspaces/InternalLanding.tsx",
  "src/workspaces/SupportWorkspace.tsx",
  "src/workspaces/ApprovalWorkspace.tsx",
];
const customerEntries = ["src/shells/CustomerShell.tsx", "src/workspaces/CustomerWorkspace.tsx"];
const forbiddenProductionContent = sensitivePatterns.modelBoundaryLiterals;

function requireChunk(key) {
  const chunk = manifest[key];
  if (!chunk) throw new Error(`bundle manifest missing ${key}`);
  return chunk;
}

function staticClosure(keys) {
  const visited = new Set();
  const visit = (key) => {
    if (visited.has(key)) return;
    visited.add(key);
    for (const imported of requireChunk(key).imports ?? []) visit(imported);
  };
  for (const key of keys) visit(key);
  return visited;
}

const entry = requireChunk("index.html");
if (!entry.isEntry) throw new Error("index.html is not the production entry");
for (const key of [...customerEntries, ...internalEntries]) {
  const chunk = requireChunk(key);
  if (!chunk.isDynamicEntry || !entry.dynamicImports?.includes(key)) {
    throw new Error(`${key} must remain a production dynamic entry`);
  }
}

const entryClosure = staticClosure(["index.html"]);
const customerFirstScreen = staticClosure(["index.html", ...customerEntries]);
for (const key of internalEntries) {
  if (customerFirstScreen.has(key)) {
    throw new Error(`customer first screen unexpectedly contains ${key}`);
  }
}

function metrics(keys) {
  const files = new Set();
  for (const key of keys) {
    const chunk = requireChunk(key);
    files.add(chunk.file);
    for (const css of chunk.css ?? []) files.add(css);
  }
  let bytes = 0;
  let gzipBytes = 0;
  for (const file of files) {
    const content = readFileSync(new URL(file, distUrl));
    bytes += statSync(new URL(file, distUrl)).size;
    gzipBytes += gzipSync(content).length;
  }
  return { bytes, gzipBytes, files: [...files].sort() };
}

const evidence = {
  generatedFrom: "dist/.vite/manifest.json",
  productionEntry: metrics(entryClosure),
  customerFirstScreen: metrics(customerFirstScreen),
  lazyInternalRoutes: Object.fromEntries(
    internalEntries.map((key) => [key, metrics(staticClosure([key]))]),
  ),
};

const productionFiles = new Set();
for (const chunk of Object.values(manifest)) {
  productionFiles.add(chunk.file);
  for (const css of chunk.css ?? []) productionFiles.add(css);
}
for (const file of productionFiles) {
  const content = readFileSync(new URL(file, distUrl), "utf8");
  for (const forbidden of forbiddenProductionContent) {
    if (content.includes(forbidden)) {
      throw new Error(`production bundle ${file} contains forbidden model-boundary content`);
    }
  }
}

evidence.modelBoundaryLeakage = {
  scannedFiles: productionFiles.size,
  forbiddenMatches: 0,
};

console.log(JSON.stringify(evidence, null, 2));
