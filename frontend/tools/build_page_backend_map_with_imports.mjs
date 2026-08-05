import fs from "fs";
import path from "path";
import { parse } from "@babel/parser";

import traverseModule from "@babel/traverse";
const traverse = traverseModule.default ?? traverseModule;

const FRONTEND_ROOT = process.cwd(); // 运行位置：.../frontend
const REPO_ROOT = path.resolve(FRONTEND_ROOT, "..");

const SRC_ROOT = path.join(FRONTEND_ROOT, "src");

const FE_ROUTES = path.join(FRONTEND_ROOT, "var", "artifacts", "frontend_routes.json");
const FE_CALLS = path.join(FRONTEND_ROOT, "var", "artifacts", "frontend_api_calls.json");
const BE_ROUTES = path.join(REPO_ROOT, "backend", "artifacts", "backend_routes.json");

const OUT_DIR = path.join(REPO_ROOT, "var", "artifacts");
const OUT_PAGE_TO_BACKEND = path.join(OUT_DIR, "page_to_backend.json");
const OUT_BACKEND_TO_PAGES = path.join(OUT_DIR, "backend_to_pages.json");
const OUT_GRAPH = path.join(OUT_DIR, "graph.mmd");

// ---------- utils ----------
function readJson(p) {
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
function uniq(arr) {
  return [...new Set(arr)];
}
function toPosix(p) {
  return p.split(path.sep).join("/");
}
function existsAny(pList) {
  for (const p of pList) if (fs.existsSync(p)) return p;
  return null;
}

// FastAPI path: /api/items/{id} -> regex ^/api/items/[^/]+$
function fastapiPathToRegex(p) {
  const escaped = p.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const re = escaped.replace(/\\\{[^}]+\\\}/g, "[^/]+");
  return new RegExp("^" + re + "$");
}

// Normalize URL to pathname without query/host
function toPath(u) {
  if (!u) return null;
  const noQuery = String(u).split("?")[0];
  if (noQuery.startsWith("http://") || noQuery.startsWith("https://")) {
    try { return new URL(noQuery).pathname; } catch { return null; }
  }
  return noQuery;
}

// Build candidate URL paths to match backend.
// Key trick: if frontend uses baseURL "/api" and then calls "/auth/login",
// we try both "/auth/login" and "/api/auth/login".
function urlCandidates(urlPath) {
  if (!urlPath) return [];
  const p = toPath(urlPath);
  if (!p) return [];
  const out = [p];

  if (p.startsWith("/") && !p.startsWith("/api/")) {
    out.push("/api" + (p === "/" ? "" : p));
  }
  return uniq(out);
}

function extractPathFromTemplateExpr(expr) {
  // expr 是像 `...` 生成出来的字符串（包含反引号）
  // 我们只处理两类：
  // 1) 以 `/${...}` 这类“路径模板”开头的
  // 2) 以 `${API_BASE}/api/...` 这类“带 host 的模板”包含 "/api/"
  if (typeof expr !== "string") return null;

  // 去掉首尾反引号（如果有）
  let s = expr.trim();
  if (s.startsWith("`") && s.endsWith("`")) s = s.slice(1, -1);

  // 情况2：包含 /api/，取从 /api 起的部分
  const idx = s.indexOf("/api/");
  if (idx >= 0) return s.slice(idx); // "/api/xxx/${id}"

  // 情况1：以 / 开头就当路径模板
  if (s.startsWith("/")) return s;

  return null;
}

function templatePathToRegex(pathTemplate) {
  // 把 "/api/issues/${id}/comments/${commentId}" 变成 regex
  // ${...} 替换成 [^/]+
  const escaped = pathTemplate.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const re = escaped.replace(/\\\$\{[^}]+\\\}/g, "[^/]+");
  return new RegExp("^" + re + "$");
}

// ---------- import resolution ----------
// Handles:
//  - relative imports: ./x, ../y
//  - Vite-style alias: @/xxx -> src/xxx
//  - "src/xxx" absolute-from-src style (some projects do this)
function resolveImport(fromFileAbs, spec) {
  if (!spec || typeof spec !== "string") return null;

  let target;
  if (spec.startsWith(".")) {
    target = path.resolve(path.dirname(fromFileAbs), spec);
  } else if (spec.startsWith("@/")) {
    target = path.join(SRC_ROOT, spec.slice(2));
  } else if (spec.startsWith("src/")) {
    target = path.join(FRONTEND_ROOT, spec);
  } else {
    // node_modules or unhandled alias: ignore
    return null;
  }

  // Try as file with extensions
  const exts = [".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs"];
  const direct = existsAny([target, ...exts.map(e => target + e)]);
  if (direct && fs.statSync(direct).isFile()) return direct;

  // Try as directory with index.*
  if (fs.existsSync(target) && fs.statSync(target).isDirectory()) {
    const idx = existsAny(exts.map(e => path.join(target, "index" + e)));
    if (idx) return idx;
  }

  return null;
}

function parseImports(fileAbs) {
  const code = fs.readFileSync(fileAbs, "utf8");
  let ast;
  try {
    ast = parse(code, {
      sourceType: "module",
      plugins: [
        "jsx",
        "typescript",
        "importMeta",
        "classProperties",
        "optionalChaining",
        "nullishCoalescingOperator",
        "topLevelAwait",
      ],
    });
  } catch {
    return []; // parse fail => treat as no imports
  }

  const specs = [];
  traverse(ast, {
    ImportDeclaration(p) {
      if (p.node.source?.value) specs.push(p.node.source.value);
    },
    // 兼容 require("...")（有些代码会混用）
    CallExpression(p) {
      if (p.node.callee?.type === "Identifier" && p.node.callee.name === "require") {
        const a0 = p.node.arguments?.[0];
        if (a0?.type === "StringLiteral") specs.push(a0.value);
      }
    }
  });

  return uniq(specs);
}

// BFS: page file -> imported files (depth limited)
function collectDeps(entryAbs, maxDepth = 3) {
  const seen = new Set();
  const q = [{ f: entryAbs, d: 0 }];

  while (q.length) {
    const { f, d } = q.shift();
    if (!f || seen.has(f)) continue;
    seen.add(f);
    if (d >= maxDepth) continue;

    const specs = parseImports(f);
    for (const s of specs) {
      const r = resolveImport(f, s);
      if (r && !seen.has(r)) q.push({ f: r, d: d + 1 });
    }
  }

  return [...seen];
}

// ---------- load artifacts ----------
if (!fs.existsSync(FE_ROUTES)) throw new Error("Missing " + FE_ROUTES);
if (!fs.existsSync(FE_CALLS)) throw new Error("Missing " + FE_CALLS);
if (!fs.existsSync(BE_ROUTES)) throw new Error("Missing " + BE_ROUTES);

const feRoutes = readJson(FE_ROUTES);
const feCalls = readJson(FE_CALLS);
const backend = readJson(BE_ROUTES);

// index api calls by file (relative to frontend root, like "src/api/client.js")
const callsByFile = new Map();
for (const c of feCalls) {
  if (!c || !c.file) continue;
  if (!callsByFile.has(c.file)) callsByFile.set(c.file, []);
  callsByFile.get(c.file).push(c);
}

// compile backend matchers
const backendCompiled = backend
  .filter(r => typeof r.path === "string" && r.path.startsWith("/"))
  .map(r => ({ ...r, _re: fastapiPathToRegex(r.path) }));

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
  const pageRel = r.componentFile;

    // componentFile 可能为 null（例如 "*" -> Navigate），这种页面就不做依赖解析
    const depAbsList =
    (typeof pageRel === "string" && pageRel.length > 0)
        ? (() => {
            const pageAbs = path.join(FRONTEND_ROOT, pageRel);
            return fs.existsSync(pageAbs) ? collectDeps(pageAbs, 6) : [];
        })()
        : [];

    const depRelList = depAbsList.map(a => toPosix(path.relative(FRONTEND_ROOT, a)));

    // gather calls from all deps
    const depCalls = [];
    for (const fRel of depRelList) {
        const arr = callsByFile.get(fRel);
        if (arr && arr.length) depCalls.push(...arr);
    }

    // Convert calls to url candidates & match backend
    const apiMatches = [];
    for (const call of depCalls) {
        // 1) 先收集“可用于匹配”的路径候选：来自 url 或 urlExpr(模板)
        let basePath = null;

        if (typeof call.url === "string" && call.url.startsWith("/")) {
        basePath = call.url;
        } else if (call.url == null && typeof call.urlExpr === "string") {
        // 只处理模板字符串这种（我们能提取出 /api/... 或 /...）
        const p = extractPathFromTemplateExpr(call.urlExpr);
        if (p && p.startsWith("/")) basePath = p;
        }

        // 如果两者都拿不到可匹配路径，就跳过
        if (!basePath) continue;

        const cands = urlCandidates(basePath);

        // 2) 常规：用 candidate 字符串去匹配 FastAPI 路由
        const matched = [];
        for (const cand of cands) {
        const hits = matchBackend(cand);
        for (const h of hits) {
            matched.push({
            path: h.path,
            methods: h.methods,
            endpoint: h.endpoint,
            source_file: h.source_file,
            source_line: h.source_line,
            matched_by: cand,
            });
        }
        }

        // 3) 如果还是没命中，并且 basePath 含 ${}，用 regex 再试一次（动态段）
        if (matched.length === 0 && typeof basePath === "string" && basePath.includes("${")) {
        const re = templatePathToRegex(basePath);
        for (const br of backendCompiled) {
            if (re.test(br.path)) {
            matched.push({
                path: br.path,
                methods: br.methods,
                endpoint: br.endpoint,
                source_file: br.source_file,
                source_line: br.source_line,
                matched_by: `TEMPLATE:${basePath}`,
            });
            }
        }
        }

        apiMatches.push({
        fromFile: call.file,
        callee: call.callee ?? null,
        method: call.method ?? null,
        url: (typeof call.url === "string" ? toPath(call.url) : null),
        urlExpr: call.urlExpr ?? null,
        urlCandidates: cands,
        matched_backend: matched,
        loc: call.loc ?? null,
        });
    }

    pageToBackend.push({
        route: r.route,
        component: r.component,
        componentFile: r.componentFile,
        deps: depRelList.sort(),
        apis: apiMatches,
    });
}

// ---------- backend_to_pages ----------
const backendToPagesMap = new Map(); // key -> {backend..., pages:Set()}
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

// ---------- mermaid graph ----------
let mmd = "graph LR\n";
mmd += "  %% Pages -> API -> Backend handler\n";

for (const p of pageToBackend) {
  const pageId = ("P_" + p.route).replace(/[^a-zA-Z0-9_]/g, "_");
  mmd += `  ${pageId}["${p.route}\\n(${p.component})"]\n`;

  for (const a of p.apis) {
    if (!a.matched_backend?.length) continue;

    const apiLabel = a.urlCandidates?.[0] ?? a.url ?? "api";
    const apiId = ("A_" + pageId + "_" + apiLabel).replace(/[^a-zA-Z0-9_]/g, "_");
    mmd += `  ${apiId}["${apiLabel}"]\n`;
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
writeJson(OUT_PAGE_TO_BACKEND, pageToBackend);
writeJson(OUT_BACKEND_TO_PAGES, backendToPages);
writeText(OUT_GRAPH, mmd);

const pageApiEdges = pageToBackend.reduce((acc, p) => acc + (p.apis?.length || 0), 0);
const matchedEdges = pageToBackend.reduce(
  (acc, p) => acc + (p.apis || []).reduce((x, a) => x + (a.matched_backend?.length || 0), 0),
  0
);

console.log("Wrote:");
console.log(" ", path.relative(REPO_ROOT, OUT_PAGE_TO_BACKEND));
console.log(" ", path.relative(REPO_ROOT, OUT_BACKEND_TO_PAGES));
console.log(" ", path.relative(REPO_ROOT, OUT_GRAPH));
console.log(`Stats: page->api records=${pageApiEdges}, api->backend matches=${matchedEdges}, backend_to_pages=${backendToPages.length}`);
