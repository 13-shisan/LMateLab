// frontend/src/pages/issues.jsx
// 用于记录用户反馈与建议的页面，未来上线后可能会删除，仅在开发阶段使用
import { useEffect, useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import api from "../api/client";

import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import "../css/Changelog.css"; // 复用 md-body 样式（你已有）

function getUserFromLocalStorage() {
  try {
    const s = localStorage.getItem("user");
    return s ? JSON.parse(s) : null;
  } catch {
    return null;
  }
}

export default function Issues() {
  const navigate = useNavigate();
  const params = useParams();
  const issueId = params?.id ? Number(params.id) : null;
  const [newLabelsText, setNewLabelsText] = useState("");

  const user = useMemo(() => getUserFromLocalStorage(), []);
  const isRoot = user?.role === "root";

  // 列表
  const [tab, setTab] = useState("open"); // open | closed | all
  const [items, setItems] = useState([]);
  const [loadingList, setLoadingList] = useState(true);
  const [errList, setErrList] = useState("");

  // 详情
  const [detail, setDetail] = useState(null);
  const [loadingDetail, setLoadingDetail] = useState(false);
  const [errDetail, setErrDetail] = useState("");

  // 新建 issue 弹窗
  const [createOpen, setCreateOpen] = useState(false);
  const [newTitle, setNewTitle] = useState("");
  const [newBody, setNewBody] = useState("");
  const [creating, setCreating] = useState(false);

  // 评论
  const [commentBody, setCommentBody] = useState("");
  const [commenting, setCommenting] = useState(false);

  async function fetchList() {
    setLoadingList(true);
    setErrList("");
    try {
      const resp = await api.get("/issues", {
        params: { state: tab, page: 1, page_size: 50 },
      });
      setItems(Array.isArray(resp.data) ? resp.data : []);
    } catch (e) {
      setErrList(e?.response?.data?.detail || e.message || String(e));
    } finally {
      setLoadingList(false);
    }
  }

  async function fetchDetail(id) {
    if (!id) return;
    setLoadingDetail(true);
    setErrDetail("");
    try {
      const resp = await api.get(`/issues/${id}`);
      setDetail(resp.data || null);
    } catch (e) {
      setErrDetail(e?.response?.data?.detail || e.message || String(e));
      setDetail(null);
    } finally {
      setLoadingDetail(false);
    }
  }

  useEffect(() => {
    fetchList();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tab]);

  useEffect(() => {
    if (issueId) fetchDetail(issueId);
    else {
      setDetail(null);
      setErrDetail("");
    }
  }, [issueId]);

  function openCreate() {
    setNewTitle("");
    setNewBody("");
    setNewLabelsText("");
    setCreateOpen(true);
  }
  function closeCreate() {
    if (creating) return;
    setCreateOpen(false);
  }

  async function submitCreate() {
    const t = newTitle.trim();
    const b = newBody.trim();

    if (!t) return alert("请填写标题");
    if (!b) return alert("请填写内容");

    const labels = newLabelsText
        .split(",")
        .map((s) => s.trim())
        .filter(Boolean);

    setCreating(true);
    try {
        const resp = await api.post("/issues", { title: t, body: b, labels });
        const id = resp.data?.id;
        setCreateOpen(false);
        await fetchList();
        if (id) navigate(`/dashboard/issues/${id}`);
    } catch (e) {
        alert(e?.response?.data?.detail || e.message || String(e));
    } finally {
        setCreating(false);
    }
    }

  async function submitComment() {
    if (!issueId) return;
    const b = commentBody.trim();
    if (!b) return alert("请填写评论内容");

    setCommenting(true);
    try {
      await api.post(`/issues/${issueId}/comments`, { body: b });
      setCommentBody("");
      await fetchDetail(issueId);
      await fetchList();
    } catch (e) {
      alert(e?.response?.data?.detail || e.message || String(e));
    } finally {
      setCommenting(false);
    }
  }

  async function closeIssue() {
    if (!issueId) return;
    try {
      await api.post(`/issues/${issueId}/close`);
      await fetchDetail(issueId);
      await fetchList();
    } catch (e) {
      alert(e?.response?.data?.detail || e.message || String(e));
    }
  }

  async function reopenIssue() {
    if (!issueId) return;
    try {
      await api.post(`/issues/${issueId}/reopen`);
      await fetchDetail(issueId);
      await fetchList();
    } catch (e) {
      alert(e?.response?.data?.detail || e.message || String(e));
    }
  }

  async function deleteComment(commentId) {
    if (!issueId) return;
    if (!window.confirm("确定删除这条评论吗？")) return;

    try {
        await api.delete(`/issues/${issueId}/comments/${commentId}`);
        await fetchDetail(issueId);
        await fetchList();
    } catch (e) {
        alert(e?.response?.data?.detail || e.message || String(e));
    }
  }

  async function deleteIssue() {
    if (!issueId) return;
    if (!window.confirm(`确定删除 Issue #${issueId} 吗？此操作不可恢复。`)) return;

    try {
        await api.delete(`/issues/${issueId}`);
        await fetchList();
        navigate("/dashboard/issues");
    } catch (e) {
        alert(e?.response?.data?.detail || e.message || String(e));
    }
  }

  const badgeStyle = (state) => ({
    display: "inline-flex",
    alignItems: "center",
    padding: "2px 10px",
    borderRadius: 999,
    fontSize: 12,
    fontWeight: 800,
    border: "1px solid rgba(209,213,219,1)",
    background: state === "open" ? "rgba(16,185,129,.12)" : "rgba(107,114,128,.12)",
    color: state === "open" ? "rgba(5,150,105,1)" : "rgba(55,65,81,1)",
  });

  const btnStyle = {
    height: 34,
    borderRadius: 10,
    padding: "0 12px",
    border: "1px solid rgba(209,213,219,1)",
    background: "white",
    cursor: "pointer",
    fontWeight: 800,
    whiteSpace: "nowrap",
  };

  return (
  <div className="dashboard-shell">
    <main className="portal-main">
      <section
        className="card"
        style={{
          flex: 1,
          width: "100%",
          padding: 16,
          maxWidth: 1200,
          margin: "16px auto",
        }}
      >
        {/* 页面内标题栏（Topbar 统一后，把原来的“顶部栏”挪到这里） */}
        <div
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            gap: 12,
            paddingBottom: 12,
            marginBottom: 12,
            borderBottom: "1px solid rgba(229,231,235,1)",
          }}
        >
          <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
            <button type="button" onClick={() => navigate("/dashboard")} style={btnStyle}>
              ← 返回
            </button>

            <div>
              <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                <h2 style={{ margin: 0 }}>反馈 / Issues</h2>
                {issueId && detail?.state ? (
                  <span style={badgeStyle(detail.state)}>{detail.state}</span>
                ) : null}
              </div>
              <div style={{ marginTop: 6, color: "#6b7280", fontSize: 12 }}>
                所有登录用户都可以提出意见并评论；root 可关闭/重开。
              </div>
            </div>
          </div>

          <div style={{ display: "flex", gap: 10 }}>
            {!issueId ? (
              <button type="button" onClick={openCreate} style={btnStyle}>
                + New issue
              </button>
            ) : (
              <button type="button" onClick={() => navigate("/dashboard/issues")} style={btnStyle}>
                ← 返回列表
              </button>
            )}
          </div>
        </div>

        <div style={{ marginTop: 0, display: "grid", gridTemplateColumns: "380px 1fr", gap: 14, }}>
        {/* 左：列表（在详情页也保留侧边列表，体验像 GitHub） */}
        <div
          style={{
            border: "1px solid rgba(229,231,235,1)",
            borderRadius: 12,
            background: "rgba(255,255,255,.85)",
            overflow: "hidden",
          }}
        >
          <div style={{ padding: 12, borderBottom: "1px solid rgba(229,231,235,1)", display: "flex", gap: 8 }}>
            {["open", "closed", "all"].map((k) => (
              <button
                key={k}
                type="button"
                onClick={() => setTab(k)}
                style={{
                  ...btnStyle,
                  height: 30,
                  fontWeight: 900,
                  borderColor: tab === k ? "rgba(17,24,39,1)" : "rgba(209,213,219,1)",
                  background: tab === k ? "rgba(17,24,39,1)" : "white",
                  color: tab === k ? "white" : "rgba(17,24,39,1)",
                }}
              >
                {k.toUpperCase()}
              </button>
            ))}
          </div>

          {loadingList ? (
            <div style={{ padding: 12, color: "#6b7280" }}>加载中…</div>
          ) : errList ? (
            <div style={{ padding: 12, color: "#991b1b" }}>{errList}</div>
          ) : items.length === 0 ? (
            <div style={{ padding: 12, color: "#6b7280" }}>暂无 Issue</div>
          ) : (
            <div style={{ maxHeight: issueId ? "calc(100vh - 180px)" : "auto", overflow: "auto" }}>
              {items.map((it) => (
                <button
                  key={it.id}
                  type="button"
                  onClick={() => navigate(`/dashboard/issues/${it.id}`)}
                  style={{
                    width: "100%",
                    textAlign: "left",
                    padding: 12,
                    border: "none",
                    borderBottom: "1px solid rgba(229,231,235,1)",
                    background: issueId === it.id ? "rgba(59,130,246,.08)" : "transparent",
                    cursor: "pointer",
                  }}
                >
                  <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 10 }}>
                    <div style={{ fontWeight: 900, color: "rgba(17,24,39,1)" }}>
                      #{it.id} {it.title}
                    </div>
                    <span style={badgeStyle(it.state)}>{it.state}</span>
                  </div>

                  <div style={{ marginTop: 6, fontSize: 12, color: "#6b7280", display: "flex", gap: 10, flexWrap: "wrap" }}>
                    <span>更新：{it.updated_at}</span>
                    <span>评论：{it.comments}</span>
                    <span>
                      作者：{it.author?.alias || it.author?.email || "unknown"}
                    </span>
                  </div>
                  {Array.isArray(it.labels) && it.labels.length > 0 ? (
                    <div style={{ marginTop: 6, display: "flex", gap: 6, flexWrap: "wrap" }}>
                        {it.labels.slice(0, 6).map((lb) => (
                        <span
                            key={lb}
                            style={{
                            fontSize: 12,
                            padding: "2px 8px",
                            borderRadius: 999,
                            border: "1px solid rgba(209,213,219,1)",
                            background: "rgba(249,250,251,1)",
                            color: "rgba(55,65,81,1)",
                            fontWeight: 800,
                            }}
                        >
                            {lb}
                        </span>
                        ))}
                    </div>
                  ) : null}
                </button>
              ))}
            </div>
            
          )}
        </div>

        {/* 右：详情（只有选中 issueId 才显示） */}
        {issueId ? (
          <div
            style={{
              border: "1px solid rgba(229,231,235,1)",
              borderRadius: 12,
              background: "rgba(255,255,255,.85)",
              overflow: "hidden",
            }}
          >
            {loadingDetail ? (
              <div style={{ padding: 12, color: "#6b7280" }}>加载详情…</div>
            ) : errDetail ? (
              <div style={{ padding: 12, color: "#991b1b" }}>{errDetail}</div>
            ) : !detail ? (
              <div style={{ padding: 12, color: "#6b7280" }}>未找到该 Issue</div>
            ) : (
              <>
                {/* 详情头 */}
                <div style={{ padding: 12, borderBottom: "1px solid rgba(229,231,235,1)" }}>
                  <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", gap: 10 }}>
                    <div>
                        <div style={{ fontWeight: 950, fontSize: 16 }}>
                            #{detail.id} {detail.title}
                        </div>

                        <div style={{ marginTop: 6, fontSize: 12, color: "#6b7280", display: "flex", gap: 10, flexWrap: "wrap" }}>
                            <span>创建：{detail.created_at}</span>
                            <span>更新：{detail.updated_at}</span>
                            <span>作者：{detail.author?.alias || detail.author?.email || "unknown"}</span>
                        </div>

                        {Array.isArray(detail.labels) && detail.labels.length > 0 ? (
                            <div style={{ marginTop: 8, display: "flex", gap: 6, flexWrap: "wrap" }}>
                            {detail.labels.map((lb) => (
                                <span
                                key={lb}
                                style={{
                                    fontSize: 12,
                                    padding: "2px 8px",
                                    borderRadius: 999,
                                    border: "1px solid rgba(209,213,219,1)",
                                    background: "rgba(249,250,251,1)",
                                    color: "rgba(55,65,81,1)",
                                    fontWeight: 800,
                                }}
                                >
                                {lb}
                                </span>
                            ))}
                            </div>
                        ) : null}
                    </div>

                    <div style={{ display: "flex", gap: 10 }}>
                        {(isRoot || (detail.author?.email && user?.email === detail.author.email)) ? (
                            <button
                            type="button"
                            style={btnStyle}
                            onClick={async () => {
                                const cur = (detail.labels || []).join(", ");
                                const next = window.prompt("编辑标签（逗号分隔）", cur);
                                if (next === null) return;
                                const labels = next.split(",").map((s) => s.trim()).filter(Boolean);
                                await api.patch(`/issues/${detail.id}/labels`, { labels });
                                await fetchDetail(detail.id);
                                await fetchList();
                            }}
                            >
                            编辑标签
                            </button>
                        ) : null}

                        {(isRoot || (detail.author?.email && user?.email === detail.author.email)) ? (
                            <button
                                type="button"
                                onClick={deleteIssue}
                                style={{
                                ...btnStyle,
                                border: "1px solid rgba(220,38,38,1)",
                                color: "rgba(220,38,38,1)",
                                background: "white",
                                }}
                            >
                                删除 Issue
                            </button>
                        ) : null}

                        {isRoot ? (
                            detail.state === "open" ? (
                            <button type="button" onClick={closeIssue} style={btnStyle}>
                                Close
                            </button>
                            ) : (
                            <button type="button" onClick={reopenIssue} style={btnStyle}>
                                Reopen
                            </button>
                            )
                        ) : null}
                    </div>
                  </div>
                </div>

                {/* 正文 */}
                <div style={{ padding: 14 }}>
                  <div style={{ fontSize: 12, color: "#6b7280", marginBottom: 8 }}>正文</div>
                  <div className="md-body">
                    <ReactMarkdown remarkPlugins={[remarkGfm]}>
                      {detail.body || "（无正文）"}
                    </ReactMarkdown>
                  </div>

                  {/* 评论 */}
                  <div style={{ marginTop: 18 }}>
                    <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
                      <div style={{ fontWeight: 900 }}>评论（{Array.isArray(detail.comments) ? detail.comments.length : 0}）</div>
                    </div>

                    <div style={{ marginTop: 10, display: "grid", gap: 10 }}>
                      {(detail.comments || []).map((c) => (
                        <div
                          key={c.id}
                          style={{
                            border: "1px solid rgba(229,231,235,1)",
                            borderRadius: 12,
                            background: "white",
                            padding: 12,
                          }}
                        >
                          <div
                            style={{
                                display: "flex",
                                justifyContent: "space-between",
                                alignItems: "center",
                                gap: 10,
                                fontSize: 12,
                                color: "#6b7280",
                            }}
                            >
                            <div>{c.author?.alias || c.author?.email || "unknown"}</div>

                            <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                                <div>{c.created_at}</div>

                                {(isRoot || (c.author?.email && user?.email === c.author.email)) ? (
                                <button
                                    type="button"
                                    onClick={() => deleteComment(c.id)}
                                    style={{
                                    height: 26,
                                    borderRadius: 8,
                                    padding: "0 10px",
                                    border: "1px solid rgba(209,213,219,1)",
                                    background: "white",
                                    cursor: "pointer",
                                    fontWeight: 800,
                                    }}
                                >
                                    删除
                                </button>
                                ) : null}
                            </div>
                          </div>
                          <div style={{ marginTop: 8 }} className="md-body">
                            <ReactMarkdown remarkPlugins={[remarkGfm]}>
                              {c.body || ""}
                            </ReactMarkdown>
                          </div>
                        </div>
                      ))}
                    </div>

                    {/* 新评论输入（带预览） */}
                    <div style={{ marginTop: 14, display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
                      <div>
                        <div style={{ fontSize: 12, color: "#6b7280" }}>发表评论（Markdown）</div>
                        <textarea
                          value={commentBody}
                          onChange={(e) => setCommentBody(e.target.value)}
                          placeholder={"例如：\n- 我遇到了 xxx\n- 复现步骤：...\n- 建议：..."}
                          style={{
                            marginTop: 6,
                            width: "100%",
                            minHeight: 140,
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
                        <div style={{ marginTop: 10, display: "flex", justifyContent: "flex-end" }}>
                          <button
                            type="button"
                            onClick={submitComment}
                            disabled={commenting}
                            style={{
                              ...btnStyle,
                              border: "1px solid rgba(17,24,39,1)",
                              background: "rgba(17,24,39,1)",
                              color: "white",
                              cursor: commenting ? "not-allowed" : "pointer",
                            }}
                          >
                            {commenting ? "提交中…" : "Comment"}
                          </button>
                        </div>
                      </div>

                      <div style={{ background: "rgba(249,250,251,1)", borderRadius: 12, padding: 12, border: "1px solid rgba(229,231,235,1)" }}>
                        <div style={{ fontSize: 12, color: "#6b7280" }}>预览</div>
                        <div style={{ marginTop: 8, background: "white", borderRadius: 10, border: "1px solid rgba(229,231,235,1)", padding: 12, maxHeight: 220, overflow: "auto" }}>
                          <div className="md-body">
                            <ReactMarkdown remarkPlugins={[remarkGfm]}>
                              {commentBody.trim() ? commentBody : "（暂无内容）"}
                            </ReactMarkdown>
                          </div>
                        </div>
                      </div>
                    </div>
                  </div>
                </div>
              </>
            )}
          </div>
        ) : (
          // 没选中 issue：右侧给一个提示（在大屏时）
          <div
            style={{
              border: "1px dashed rgba(209,213,219,1)",
              borderRadius: 12,
              padding: 16,
              color: "#6b7280",
              background: "rgba(255,255,255,.6)",
            }}
          >
            从左侧选择一个 Issue 查看详情，或点击右上角 “New issue” 创建。
          </div>
        )}
      </div>

      {/* 新建 issue 弹窗 */}
      {createOpen ? (
        <div
          onMouseDown={(e) => {
            if (e.target === e.currentTarget) closeCreate();
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
              width: "min(980px, 100%)",
              borderRadius: 14,
              background: "white",
              border: "1px solid rgba(229,231,235,1)",
              boxShadow: "0 20px 60px rgba(0,0,0,.25)",
              overflow: "hidden",
            }}
          >
            <div style={{ padding: "14px 16px", borderBottom: "1px solid rgba(229,231,235,1)" }}>
              <div style={{ fontWeight: 900 }}>New issue</div>
              <div style={{ marginTop: 4, color: "#6b7280", fontSize: 12 }}>
                标题 + 正文支持 Markdown。提交后所有人可评论。
              </div>
            </div>

            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 0 }}>
              <div style={{ padding: 16, borderRight: "1px solid rgba(229,231,235,1)" }}>
                <div style={{ fontSize: 12, color: "#6b7280" }}>标题</div>
                <input
                  value={newTitle}
                  onChange={(e) => setNewTitle(e.target.value)}
                  placeholder="例如：任务页面筛选速度慢"
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

                <div style={{ marginTop: 12, fontSize: 12, color: "#6b7280" }}>标签（逗号分隔，可自由填写）</div>
                    <input
                    value={newLabelsText}
                    onChange={(e) => setNewLabelsText(e.target.value)}
                    placeholder='例如：bug, 希望更新, 未解决'
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

                <div style={{ marginTop: 12, fontSize: 12, color: "#6b7280" }}>正文（Markdown）</div>
                <textarea
                  value={newBody}
                  onChange={(e) => setNewBody(e.target.value)}
                  placeholder={"## 复现步骤\n1. ...\n\n## 期望结果\n...\n\n## 实际结果\n..."}
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

              <div style={{ padding: 16, background: "rgba(249,250,251,1)" }}>
                <div style={{ fontSize: 12, color: "#6b7280" }}>预览</div>
                <div
                  style={{
                    marginTop: 10,
                    padding: 12,
                    borderRadius: 10,
                    border: "1px solid rgba(229,231,235,1)",
                    background: "white",
                    maxHeight: 360,
                    overflow: "auto",
                  }}
                >
                  <div className="md-body">
                    <ReactMarkdown remarkPlugins={[remarkGfm]}>
                      {`## ${newTitle || "（未填写标题）"}\n\n${newBody || "（未填写正文）"}`}
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
              <button type="button" onClick={closeCreate} disabled={creating} style={btnStyle}>
                取消
              </button>
              <button
                type="button"
                onClick={submitCreate}
                disabled={creating}
                style={{
                  ...btnStyle,
                  border: "1px solid rgba(17,24,39,1)",
                  background: "rgba(17,24,39,1)",
                  color: "white",
                  cursor: creating ? "not-allowed" : "pointer",
                }}
              >
                {creating ? "提交中…" : "Submit"}
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
