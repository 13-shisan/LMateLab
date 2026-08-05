import fs from "fs";
import path from "path";

const ROOT = process.cwd();

function loadJson(p) {
  return JSON.parse(fs.readFileSync(p, "utf8"));
}

function writeJson(p, obj) {
  fs.mkdirSync(path.dirname(p), { recursive: true });
  fs.writeFileSync(p, JSON.stringify(obj, null, 2), "utf8");
}

function writeText(p, s) {
  fs.mkdirSync(path.dirname(p), { recursive: true });
  fs.writeFileSync(p, s, "utf8");
}

// /api/users/{id} -> ^/api/users/[^/]+$
function fastapiPathToRegex(p) {
  const escaped = p.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const re = escaped.replace(/\\\{[^}]+\\\}/g, "[^/]+");
  return new RegExp("^" + re + "$");
}

function toPath(u) {
  if (!u) return null;
  // 去 query
  const noQuery = String(u).split("?")[0];

  // 处理绝对 URL
  if (noQuery.startsWith("http://") || noQuery.startsWith("https://")) {
    try {
      return new URL(noQuery).pathname;
    } catch {
      return null;
    }
  }
  return noQuery;
}

function uniq(arr) {
  return [...new Set(arr)];
}

// ---------- load artifacts ----------
const backendRoutesPath = path.join(ROOT, "backend", "artifacts", "backend_routes.json");
const frontendRoutesPath = path.join(ROOT, "frontend", "artifacts", "frontend_routes.json");
const frontendCallsPath = path.join(ROOT, "frontend", "artifacts", "frontend_api_calls.json");

if (!fs.existsSync(backendRoutesPath)) throw new Error("Missing " + backendRoutesPath);
if (!fs.existsSync(frontendRoutesPath)) throw new Error("Missing " + frontendRoutesPath);
if (!fs.existsSync(frontendCallsPath)) throw new Error("Missing " + frontendCallsPath);

const backend = loadJson(backendRoutesPath);
const feRoutes = loadJson(frontendRoutesPath);
const feCalls = loadJson(frontendCallsPath);

// ---------- prepare backend matchers ----------
const backendCompiled = backend
  .filter(r => typeof r.path === "string" && r.path.startsWith("/"))
  .map(r => ({ ...r, _re: fastapiPathToRegex(r.path) }));

// ---------- index frontend calls by file ----------
const callsByFile = new Map(); // file -> [urlPath...]
for (const c of feCalls) {
  const f = c.file;
  const p = toPath(c.url);
  if (!f || !p) continue;
  if (!callsByFile.has(f)) callsByFile.set(f, []);
  callsByFile.get(f).push(p);
}
for (const [f, arr] of callsByFile.entries()) {
  callsByFile.set(f, uniq(arr));
}

// ---------- match a urlPath to backend routes ----------
function matchBackend(urlPath) {
  const hits = [];
  for (const br of backendCompiled) {
    if (br._re.test(urlPath)) hits.push(br);
  }
  return hits;
}

// ---------- build page_to_backend ----------
const pageToBackend = [];

for (const r of feRoutes) {
  const pageFile = r.componentFile; // e.g. src/pages/Login.jsx
  const urls = pageFile && callsByFile.has(pageFile) ? callsByFile.get(pageFile) : [];

  // 对每个 url 找后端匹配
  const apiMatches = [];
  for (const u of urls) {
    const hits = matchBackend(u);
    apiMatches.push({
      url: u,
      matched_backend: hits.map(h => ({
        path: h.path,
        methods: h.methods,
        endpoint: h.endpoint,
        source_file: h.source_file,
        source_line: h.source_line,
      })),
    });
  }

  pageToBackend.push({
    route: r.route,
    component: r.component,
    componentFile: r.componentFile,
    apis: apiMatches,
  });
}

// ---------- build backend_to_pages ----------
const backendToPagesMap = new Map(); // backendPath -> {backend..., pages:Set()}
for (const p of pageToBackend) {
  for (const a of p.apis) {
    for (const b of a.matched_backend) {
      const key = `${b.path}__${(b.methods || []).join(",")}`;
      if (!backendToPagesMap.has(key)) {
        backendToPagesMap.set(key, {
          path: b.path,
          methods: b.methods,
          endpoint: b.endpoint,
          source_file: b.source_file,
          source_line: b.source_line,
          pages: new Set(),
        });
      }
      backendToPagesMap.get(key).pages.add(p.route);
    }
  }
}

const backendToPages = [];
for (const v of backendToPagesMap.values()) {
  backendToPages.push({
    path: v.path,
    methods: v.methods,
    endpoint: v.endpoint,
    source_file: v.source_file,
    source_line: v.source_line,
    pages: [...v.pages].sort(),
  });
}
backendToPages.sort((a, b) => (a.path || "").localeCompare(b.path || ""));

// ---------- build mermaid graph ----------
let mmd = "graph LR\n";
mmd += "  %% Pages -> API -> Backend handler\n";
for (const p of pageToBackend) {
  const pageId = ("P_" + p.route).replace(/[^a-zA-Z0-9_]/g, "_");
  mmd += `  ${pageId}["${p.route}\\n(${p.component})"]\n`;

  for (const a of p.apis) {
    if (!a.matched_backend?.length) continue;

    const apiId = ("A_" + a.url).replace(/[^a-zA-Z0-9_]/g, "_");
    mmd += `  ${apiId}["${a.url}"]\n`;
    mmd += `  ${pageId} --> ${apiId}\n`;

    for (const b of a.matched_backend) {
      const hLabel = `${b.endpoint}\\n${path.basename(b.source_file || "")}:${b.source_line || ""}`;
      const hId = ("H_" + (b.endpoint || b.path)).replace(/[^a-zA-Z0-9_]/g, "_");
      mmd += `  ${hId}["${hLabel}"]\n`;
      mmd += `  ${apiId} --> ${hId}\n`;
    }
  }
}

// ---------- write outputs ----------
writeJson(path.join(ROOT, "artifacts", "page_to_backend.json"), pageToBackend);
writeJson(path.join(ROOT, "artifacts", "backend_to_pages.json"), backendToPages);
writeText(path.join(ROOT, "artifacts", "graph.mmd"), mmd);

console.log("Wrote:");
console.log("  artifacts/page_to_backend.json");
console.log("  artifacts/backend_to_pages.json");
console.log("  artifacts/graph.mmd");

