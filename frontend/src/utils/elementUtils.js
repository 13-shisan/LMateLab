export function normalizeElementSymbol(sym) {
  if (!sym) return "";
  const s = String(sym).trim();
  if (!s) return "";
  if (s.length === 1) return s.toUpperCase();
  return s[0].toUpperCase() + s.slice(1).toLowerCase();
}
