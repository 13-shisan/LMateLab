// frontend/tools/export_react_routes.mjs
import fs from "fs";
import path from "path";
import { parse } from "@babel/parser";
import traverseModule from "@babel/traverse";
const traverse = traverseModule.default ?? traverseModule;

const FRONTEND_ROOT = process.cwd();
const APP_FILE = path.join(FRONTEND_ROOT, "src", "App.jsx");

function resolveImport(fromFile, importSource) {
  // 只处理相对路径 import
  if (!importSource.startsWith(".")) return null;

  const base = path.resolve(path.dirname(fromFile), importSource);

  // 常见候选后缀
  const candidates = [
    base,
    base + ".js",
    base + ".jsx",
    base + ".ts",
    base + ".tsx",
    path.join(base, "index.js"),
    path.join(base, "index.jsx"),
    path.join(base, "index.ts"),
    path.join(base, "index.tsx"),
  ];

  for (const c of candidates) {
    if (fs.existsSync(c) && fs.statSync(c).isFile()) return c;
  }
  return null;
}

const code = fs.readFileSync(APP_FILE, "utf8");
const ast = parse(code, {
  sourceType: "module",
  plugins: ["jsx"],
});

// 1) 收集 import：ComponentName -> 源文件
const importMap = new Map();

traverse(ast, {
  ImportDeclaration(p) {
    const src = p.node.source.value;
    for (const sp of p.node.specifiers) {
      // import X from '...'
      if (sp.type === "ImportDefaultSpecifier") {
        const local = sp.local.name;
        const resolved = resolveImport(APP_FILE, src);
        if (resolved) importMap.set(local, resolved);
      }
      // import { X } from '...'
      if (sp.type === "ImportSpecifier") {
        const local = sp.local.name;
        const resolved = resolveImport(APP_FILE, src);
        if (resolved) importMap.set(local, resolved);
      }
    }
  },
});

// 2) 收集 <Route path="..." element={<Comp/>} />
const routes = [];

function getJSXAttr(node, name) {
  const attr = node.openingElement.attributes.find(
    (a) => a.type === "JSXAttribute" && a.name?.name === name
  );
  if (!attr) return null;

  // path="/xx"
  if (attr.value?.type === "StringLiteral") return attr.value.value;

  // path={"..."} 这种不处理（可后续增强）
  return null;
}

function getElementComponentName(routeNode) {
  const attr = routeNode.openingElement.attributes.find(
    (a) => a.type === "JSXAttribute" && a.name?.name === "element"
  );
  if (!attr) return null;

  // element={<RequireAuth><Dashboard/></RequireAuth>}
  // element={<Dashboard />}
  const v = attr.value;
  if (!v) return null;

  // JSXAttribute 的 value 在 JSXExpressionContainer 里
  if (v.type !== "JSXExpressionContainer") return null;

  const expr = v.expression;

  // 1) 直接 <Dashboard />
  if (expr?.type === "JSXElement") {
    // 取最内层“页面组件”：如果外层是 RequireAuth，就取其 children 里最后一个 JSXElement
    const stack = [];
    const walk = (el) => {
      stack.push(el);
      const childEls = el.children?.filter((c) => c.type === "JSXElement") || [];
      for (const c of childEls) walk(c);
    };
    walk(expr);

    // 最后一个 JSXElement 通常是页面组件（Dashboard / Issues / ...）
    const last = stack[stack.length - 1];
    const nameNode = last.openingElement.name;
    if (nameNode?.type === "JSXIdentifier") return nameNode.name;
    return null;
  }

  return null;
}

traverse(ast, {
  JSXElement(p) {
    const nameNode = p.node.openingElement.name;
    if (nameNode?.type !== "JSXIdentifier") return;
    if (nameNode.name !== "Route") return;

    const routePath = getJSXAttr(p.node, "path");
    if (!routePath) return;

    const compName = getElementComponentName(p.node);
    const compFile = compName ? importMap.get(compName) : null;

    routes.push({
      route: routePath,
      component: compName,
      componentFile: compFile ? path.relative(FRONTEND_ROOT, compFile) : null,
      definedIn: path.relative(FRONTEND_ROOT, APP_FILE),
    });
  },
});

fs.mkdirSync(path.join(FRONTEND_ROOT, "artifacts"), { recursive: true });
fs.writeFileSync(
  path.join(FRONTEND_ROOT, "artifacts", "frontend_routes.json"),
  JSON.stringify(routes, null, 2),
  "utf8"
);

console.log(`Wrote ${routes.length} routes to artifacts/frontend_routes.json`);
