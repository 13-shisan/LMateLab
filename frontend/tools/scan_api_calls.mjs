// frontend/tools/scan_api_calls.mjs
import fs from "fs";
import path from "path";
import { parse } from "@babel/parser";

import traverseModule from "@babel/traverse";
const traverse = traverseModule.default ?? traverseModule;

import genModule from "@babel/generator";
const generate = genModule.default ?? genModule;

const ROOT = process.cwd();
const SRC_DIR = path.join(ROOT, "src");
const EXTS = new Set([".js", ".jsx", ".ts", ".tsx"]);

function walk(dir) {
  const out = [];
  for (const name of fs.readdirSync(dir)) {
    const p = path.join(dir, name);
    const st = fs.statSync(p);
    if (st.isDirectory()) out.push(...walk(p));
    else if (st.isFile() && EXTS.has(path.extname(p))) out.push(p);
  }
  return out;
}

function literalString(node) {
  if (!node) return null;
  if (node.type === "StringLiteral") return node.value;
  if (node.type === "TemplateLiteral" && node.expressions.length === 0) {
    return node.quasis.map(q => q.value.cooked).join("");
  }
  return null;
}

function joinUrl(base, p) {
  if (!base || !p) return null;
  const b = base.endsWith("/") ? base.slice(0, -1) : base;
  const q = p.startsWith("/") ? p : "/" + p;
  return b + q;
}

function getMemberCallee(node) {
  // returns { obj: "client", prop: "get" } for client.get(...)
  if (!node) return null;
  if (node.type !== "MemberExpression" || node.computed) return null;
  if (node.object?.type !== "Identifier") return null;
  if (node.property?.type !== "Identifier") return null;
  return { obj: node.object.name, prop: node.property.name };
}

function extractMethodFromProp(prop) {
  const known = ["get", "post", "put", "patch", "delete"];
  if (known.includes(prop)) return prop.toUpperCase();
  return null;
}

function extractBaseURLFromAxiosCreate(callNode) {
  // axios.create({ baseURL: "/api" })
  const args = callNode.arguments || [];
  if (args[0]?.type !== "ObjectExpression") return null;

  const baseProp = args[0].properties.find(p =>
    p.type === "ObjectProperty" &&
    ((p.key.type === "Identifier" && p.key.name === "baseURL") ||
      (p.key.type === "StringLiteral" && p.key.value === "baseURL"))
  );
  if (!baseProp) return null;

  return literalString(baseProp.value);
}

function extractFetchMethod(callNode) {
  const args = callNode.arguments || [];
  if (args[1]?.type !== "ObjectExpression") return "GET";
  const methodProp = args[1].properties.find(p =>
    p.type === "ObjectProperty" &&
    ((p.key.type === "Identifier" && p.key.name === "method") ||
      (p.key.type === "StringLiteral" && p.key.value === "method"))
  );
  const mv = methodProp ? literalString(methodProp.value) : null;
  return (mv ? String(mv).toUpperCase() : "GET");
}

function toPath(u) {
  if (!u) return null;
  const noQuery = String(u).split("?")[0];
  if (noQuery.startsWith("http://") || noQuery.startsWith("https://")) {
    try { return new URL(noQuery).pathname; } catch { return null; }
  }
  return noQuery;
}

const files = walk(SRC_DIR);
const results = [];

for (const file of files) {
  const code = fs.readFileSync(file, "utf8");

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
  } catch (e) {
    results.push({
      file: path.relative(ROOT, file),
      kind: "parse_error",
      error: String(e.message || e),
    });
    continue;
  }

  // 同文件内：axios instance name -> baseURL
  const axiosInstanceBase = new Map();

  traverse(ast, {
    VariableDeclarator(p) {
      // const client = axios.create({ baseURL: "/api" })
      const id = p.node.id;
      const init = p.node.init;
      if (id?.type !== "Identifier") return;
      if (!init || init.type !== "CallExpression") return;

      const mc = getMemberCallee(init.callee); // axios.create
      if (!mc || mc.obj !== "axios" || mc.prop !== "create") return;

      const baseURL = extractBaseURLFromAxiosCreate(init);
      if (baseURL) axiosInstanceBase.set(id.name, baseURL);
    },
  });

  traverse(ast, {
    CallExpression(p) {
      const relFile = path.relative(ROOT, file);

      // --- fetch(url, options) ---
      if (p.node.callee?.type === "Identifier" && p.node.callee.name === "fetch") {
        const args = p.node.arguments || [];
        const urlLit = literalString(args[0]);
        const method = extractFetchMethod(p.node);

        results.push({
          file: relFile,
          callee: "fetch",
          method,
          url: urlLit ? toPath(urlLit) : null,
          urlExpr: urlLit ? null : (args[0] ? generate(args[0]).code : null),
          loc: p.node.loc ? { start: p.node.loc.start, end: p.node.loc.end } : null,
        });
        return;
      }

      // --- axios(...) direct call ---
      if (p.node.callee?.type === "Identifier" && p.node.callee.name === "axios") {
        const args = p.node.arguments || [];
        // axios({url:"/api/xxx", method:"post"}) only; otherwise record expr
        let url = null;
        let method = null;

        if (args[0]?.type === "ObjectExpression") {
          const urlProp = args[0].properties.find(pp =>
            pp.type === "ObjectProperty" &&
            ((pp.key.type === "Identifier" && pp.key.name === "url") ||
              (pp.key.type === "StringLiteral" && pp.key.value === "url"))
          );
          if (urlProp) url = literalString(urlProp.value);

          const methodProp = args[0].properties.find(pp =>
            pp.type === "ObjectProperty" &&
            ((pp.key.type === "Identifier" && pp.key.name === "method") ||
              (pp.key.type === "StringLiteral" && pp.key.value === "method"))
          );
          if (methodProp) {
            const mv = literalString(methodProp.value);
            if (mv) method = String(mv).toUpperCase();
          }
        }

        results.push({
          file: relFile,
          callee: "axios",
          method,
          url: url ? toPath(url) : null,
          urlExpr: url ? null : (args[0] ? generate(args[0]).code : null),
          loc: p.node.loc ? { start: p.node.loc.start, end: p.node.loc.end } : null,
        });
        return;
      }

      // --- member calls: axios.get, client.get, api.post, etc. ---
      const mc = getMemberCallee(p.node.callee);
      if (!mc) return;

      const method = extractMethodFromProp(mc.prop);
      if (!method) return;

      const args = p.node.arguments || [];
      const first = args[0];
      const urlLit = literalString(first);

      // 如果是 axios.get("/api/..")
      if (mc.obj === "axios") {
        results.push({
          file: relFile,
          callee: `axios.${mc.prop}`,
          method,
          url: urlLit ? toPath(urlLit) : null,
          urlExpr: urlLit ? null : (first ? generate(first).code : null),
          loc: p.node.loc ? { start: p.node.loc.start, end: p.node.loc.end } : null,
        });
        return;
      }

      // 如果是实例 client.get("/auth/..")，尝试拼 baseURL
      if (axiosInstanceBase.has(mc.obj)) {
        const base = axiosInstanceBase.get(mc.obj);
        const full = urlLit ? joinUrl(base, urlLit) : null;

        results.push({
          file: relFile,
          callee: `${mc.obj}.${mc.prop}`,
          method,
          url: full ? toPath(full) : null,
          urlExpr: full ? null : (first ? generate(first).code : null),
          inferredBaseURL: base,
          loc: p.node.loc ? { start: p.node.loc.start, end: p.node.loc.end } : null,
        });
        return;
      }

      // 其他对象.get/post：先照样记录（可能是封装 client，后续再增强跨文件推导）
      results.push({
        file: relFile,
        callee: `${mc.obj}.${mc.prop}`,
        method,
        url: urlLit ? toPath(urlLit) : null,
        urlExpr: urlLit ? null : (first ? generate(first).code : null),
        loc: p.node.loc ? { start: p.node.loc.start, end: p.node.loc.end } : null,
      });
    },
  });
}

fs.mkdirSync(path.join(ROOT, "artifacts"), { recursive: true });
fs.writeFileSync(
  path.join(ROOT, "artifacts", "frontend_api_calls.json"),
  JSON.stringify(results, null, 2),
  "utf8"
);

const literal = results.filter(r => r.url && typeof r.url === "string").length;
const apiLike = results.filter(r => r.url && String(r.url).startsWith("/api/")).length;
const dyn = results.filter(r => !r.url && r.urlExpr && r.kind !== "parse_error").length;
const perr = results.filter(r => r.kind === "parse_error").length;

console.log(`Wrote ${results.length} records to artifacts/frontend_api_calls.json`);
console.log(`  literal urls (any): ${literal}`);
console.log(`  urls starting with /api/: ${apiLike}`);
console.log(`  dynamic url expressions: ${dyn}`);
console.log(`  parse errors: ${perr}`);

