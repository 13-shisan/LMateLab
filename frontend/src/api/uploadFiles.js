import { getAuthHeaders } from "./auth";

export async function uploadFiles(url, files) {
  const headers = getAuthHeaders(null);

  const fd = new FormData();
  for (const f of files) fd.append("files", f);

  const resp = await fetch(url, {
    method: "POST",
    headers,
    body: fd,
  });

  const ct = resp.headers.get("content-type") || "";
  const data = ct.includes("application/json") ? await resp.json() : await resp.text();

  if (!resp.ok) {
    const msg =
      typeof data?.detail === "string"
        ? data.detail
        : data?.detail
          ? JSON.stringify(data.detail)
          : String(data || `上传失败（${resp.status}）`);
    throw new Error(msg);
  }

  return data;
}
