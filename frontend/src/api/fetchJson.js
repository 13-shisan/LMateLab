import { getAuthHeaders } from "./auth";

export async function fetchJson(url, { signal } = {}) {
  const resp = await fetch(url, { method: "GET", headers: getAuthHeaders(), signal });
  const ct = resp.headers.get("content-type") || "";
  const data = ct.includes("application/json") ? await resp.json() : null;

  if (!resp.ok) {
    const msg =
      typeof data?.detail === "string"
        ? data.detail
        : data?.detail
          ? JSON.stringify(data.detail)
          : `请求失败（${resp.status}）`;
    throw new Error(msg);
  }
  return data;
}
