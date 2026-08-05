export function parseCpValue(text) {
  const s = String(text ?? "").trim();
  if (!s) return null;

  // 1) JSON（数组/对象/数字/true/false/null）
  try {
    return JSON.parse(s);
  } catch {}

  // 2) 数字
  if (/^[+-]?\d+(\.\d+)?([eE][+-]?\d+)?$/.test(s)) {
    const n = Number(s);
    if (Number.isFinite(n)) return n;
  }

  // 3) 纯字符串
  return s;
}

export function flattenObjectToPairs(obj, prefix = "", out = []) {
  if (obj === null || obj === undefined) return out;

  if (Array.isArray(obj)) {
    out.push({ k: prefix || "(array)", v: JSON.stringify(obj) });
    return out;
  }

  if (typeof obj !== "object") {
    out.push({ k: prefix || "(value)", v: String(obj) });
    return out;
  }

  const keys = Object.keys(obj).sort();
  for (const key of keys) {
    const val = obj[key];
    const nextPrefix = prefix ? `${prefix}.${key}` : key;

    if (val && typeof val === "object" && !Array.isArray(val)) {
      flattenObjectToPairs(val, nextPrefix, out);
    } else if (Array.isArray(val)) {
      out.push({ k: nextPrefix, v: JSON.stringify(val) });
    } else {
      out.push({ k: nextPrefix, v: String(val) });
    }
  }
  return out;
}
