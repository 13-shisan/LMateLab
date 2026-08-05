import { getAuthHeaders } from "./auth";

export async function downloadAuthedFile(url, fallbackFilename) {
  const resp = await fetch(url, { method: "GET", headers: getAuthHeaders() });

  const ct = resp.headers.get("content-type") || "";
  if (ct.includes("application/json")) {
    const j = await resp.json().catch(() => ({}));
    const msg = typeof j?.detail === "string" ? j.detail : JSON.stringify(j);
    throw new Error(msg || "导出失败（JSON）");
  }
  if (!resp.ok) {
    const txt = await resp.text().catch(() => "");
    throw new Error(txt || `导出失败（${resp.status}）`);
  }

  const blob = await resp.blob();
  const cd = resp.headers.get("content-disposition") || "";
  const match = cd.match(/filename="?([^"]+)"?/i);
  const filename = match?.[1] || fallbackFilename;

  const link = document.createElement("a");
  link.href = URL.createObjectURL(blob);
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(link.href);
}
