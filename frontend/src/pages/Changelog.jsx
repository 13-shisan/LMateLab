// frontend/src/pages/Changelog.jsx
import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import api from "../api/client";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import "../css/Changelog.css";

export default function Changelog() {
  const [md, setMd] = useState("");
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState("");
  const navigate = useNavigate();

  // 编辑弹窗状态
  const [open, setOpen] = useState(false);
  const [title, setTitle] = useState("");
  const [body, setBody] = useState("");
  const [saving, setSaving] = useState(false);

  // ✅ root 判定：与你后端一致，只认 role
  const isRoot = useMemo(() => {
    try {
      const s = localStorage.getItem("user");
      const user = s ? JSON.parse(s) : null;
      return user?.role === "root";
    } catch {
      return false;
    }
  }, []);

  async function refresh() {
    setLoading(true);
    setErr("");
    try {
      const resp = await api.get("/changelog");
      setMd(String(resp.data?.content || ""));
    } catch (e) {
      setErr(e?.response?.data?.detail || e.message || String(e));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    refresh();
  }, []);

  function openEditor() {
    setTitle("");
    setBody("");
    setOpen(true);
  }

  function closeEditor() {
    if (saving) return;
    setOpen(false);
  }

  async function submit() {
    const t = title.trim();
    const b = body.trim();
    if (!t) return alert("请填写标题");
    if (!b) return alert("请填写更新内容");

    setSaving(true);
    try {
      await api.post("/changelog", { title: t, body: b });
      setOpen(false);
      await refresh();
    } catch (e) {
      alert(e?.response?.data?.detail || e.message || String(e));
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="dashboard-shell">
        <main className="portal-main">
        <section
            className="card"
            style={{
            flex: 1,
            width: "100%",      // ✅ 防止在 portal-main flex 下变窄
            padding: 16,
            maxWidth: 980,
            margin: "16px auto",
            }}
        >
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 10 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
            <button
            type="button"
            onClick={() => navigate("/dashboard")}
            style={{
                height: 34,
                borderRadius: 10,
                padding: "0 12px",
                border: "1px solid rgba(209,213,219,1)",
                background: "white",
                cursor: "pointer",
                fontWeight: 700,
                whiteSpace: "nowrap",
            }}
            title="返回仪表盘"
            >
            ← 返回
            </button>

            <div>
            <h2 style={{ margin: 0 }}>平台更新日志</h2>
            <div style={{ marginTop: 6, color: "#6b7280", fontSize: 12 }}>
                说明：展示平台更新内容与 Bug 修复记录。
            </div>
            </div>
        </div>

        {isRoot ? (
          <button
            type="button"
            onClick={openEditor}
            style={{
              height: 34,
              borderRadius: 10,
              padding: "0 12px",
              border: "1px solid rgba(209,213,219,1)",
              background: "white",
              cursor: "pointer",
              fontWeight: 700,
              whiteSpace: "nowrap",
            }}
          >
            + 记录更新
          </button>
        ) : null}
      </div>

      {loading ? (
        <div style={{ marginTop: 14, color: "#6b7280" }}>加载中…</div>
      ) : err ? (
        <div style={{ marginTop: 14, color: "#991b1b" }}>{err}</div>
      ) : (
        <div
          style={{
            marginTop: 14,
            padding: 16,
            borderRadius: 12,
            border: "1px solid rgba(229,231,235,1)",
            background: "rgba(255,255,255,.85)",
          }}
        >
          {/* ✅ 直接渲染 Markdown */}
          <div className="md-body">
            <ReactMarkdown remarkPlugins={[remarkGfm]}>
              {md || "（暂无更新日志）"}
            </ReactMarkdown>
          </div>
        </div>
      )}

      {/* ✅ 编辑弹窗（不再用 prompt） */}
      {open ? (
        <div
          onMouseDown={(e) => {
            if (e.target === e.currentTarget) closeEditor();
          }}
          style={{
            position: "fixed",
            inset: 0,
            background: "rgba(0,0,0,.35)",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            padding: 16,
            zIndex: 9999,
          }}
        >
          <div
            style={{
              width: "min(900px, 100%)",
              borderRadius: 14,
              background: "white",
              border: "1px solid rgba(229,231,235,1)",
              boxShadow: "0 20px 60px rgba(0,0,0,.25)",
              overflow: "hidden",
            }}
          >
            <div style={{ padding: "14px 16px", borderBottom: "1px solid rgba(229,231,235,1)" }}>
              <div style={{ fontWeight: 800 }}>记录更新</div>
              <div style={{ marginTop: 4, color: "#6b7280", fontSize: 12 }}>
                支持 Markdown（例如：列表、代码块、链接）。
              </div>
            </div>

            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 0 }}>
              {/* 左：编辑 */}
              <div style={{ padding: 16, borderRight: "1px solid rgba(229,231,235,1)" }}>
                <div style={{ fontSize: 12, color: "#6b7280" }}>标题</div>
                <input
                  value={title}
                  onChange={(e) => setTitle(e.target.value)}
                  placeholder="例如：修复筛选超时问题"
                  style={{
                    marginTop: 6,
                    width: "100%",
                    height: 38,
                    borderRadius: 10,
                    border: "1px solid rgba(209,213,219,1)",
                    padding: "0 12px",
                    outline: "none",
                  }}
                />

                <div style={{ marginTop: 12, fontSize: 12, color: "#6b7280" }}>更新内容（Markdown）</div>
                <textarea
                  value={body}
                  onChange={(e) => setBody(e.target.value)}
                  placeholder={"- 修复：xxx\n- 优化：yyy\n\n```\n可粘贴日志或命令输出\n```"}
                  style={{
                    marginTop: 6,
                    width: "100%",
                    minHeight: 260,
                    resize: "vertical",
                    borderRadius: 10,
                    border: "1px solid rgba(209,213,219,1)",
                    padding: 12,
                    outline: "none",
                    fontFamily:
                      'ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace',
                    fontSize: 12,
                    lineHeight: 1.5,
                  }}
                />
              </div>

              {/* 右：预览 */}
              <div style={{ padding: 16, background: "rgba(249,250,251,1)" }}>
                <div style={{ fontSize: 12, color: "#6b7280" }}>预览</div>
                <div
                  style={{
                    marginTop: 10,
                    padding: 12,
                    borderRadius: 10,
                    border: "1px solid rgba(229,231,235,1)",
                    background: "white",
                    maxHeight: 330,
                    overflow: "auto",
                  }}
                >
                  <div className="md-body">
                    <ReactMarkdown remarkPlugins={[remarkGfm]}>
                      {`## 预览 — ${title || "（未填写标题）"}\n\n${body || "（未填写内容）"}`}
                    </ReactMarkdown>
                  </div>
                </div>
              </div>
            </div>

            <div
              style={{
                padding: 16,
                borderTop: "1px solid rgba(229,231,235,1)",
                display: "flex",
                justifyContent: "flex-end",
                gap: 10,
              }}
            >
              <button
                type="button"
                onClick={closeEditor}
                disabled={saving}
                style={{
                  height: 34,
                  borderRadius: 10,
                  padding: "0 12px",
                  border: "1px solid rgba(209,213,219,1)",
                  background: "white",
                  cursor: saving ? "not-allowed" : "pointer",
                }}
              >
                取消
              </button>
              <button
                type="button"
                onClick={submit}
                disabled={saving}
                style={{
                  height: 34,
                  borderRadius: 10,
                  padding: "0 12px",
                  border: "1px solid rgba(17,24,39,1)",
                  background: "rgba(17,24,39,1)",
                  color: "white",
                  cursor: saving ? "not-allowed" : "pointer",
                  fontWeight: 800,
                }}
              >
                {saving ? "提交中…" : "提交"}
              </button>
            </div>
          </div>
        </div>
      ) : null}
      </section>
    </main>
  </div>
);
}
