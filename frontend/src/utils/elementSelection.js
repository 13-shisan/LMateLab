export function toggleElementSelection(selected, symbol) {
  return selected.includes(symbol)
    ? selected.filter((value) => value !== symbol)
    : [...selected, symbol];
}

export function matchesElementSelection(recordElements, selected, mode) {
  const record = new Set(recordElements);
  const wanted = [...new Set(selected)];

  if (wanted.length === 0) return true;
  if (!wanted.every((symbol) => record.has(symbol))) return false;
  return mode !== 'only' || record.size === wanted.length;
}
