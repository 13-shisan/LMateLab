import { getAuthHeaders } from "./auth";

export function getPostJsonErrorDetail(resp, data) {
  return typeof data?.detail === "string"
    ? data.detail
    : data?.detail
      ? JSON.stringify(data.detail)
      : String(data || resp.status);
}

export async function postJson(url, body) {
  const resp = await fetch(url, {
    method: "POST",
    headers: getAuthHeaders(),
    body: JSON.stringify(body),
  });

  const ct = resp.headers.get("content-type") || "";
  const data = ct.includes("application/json") ? await resp.json() : await resp.text();

  return { resp, data };
}
