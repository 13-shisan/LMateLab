// frontend/src/pages/papers/library.jsx
import { useEffect, useMemo, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";
import rehypeKatex from "rehype-katex";
import "katex/dist/katex.min.css";
import PapersLayout from "./PapersLayout";
import api from "../../api/client";
import "./library.css";

const sidebarBtnStyle = (active, depth = 0) => ({
  width: "100%",
  textAlign: "left",
  border: active ? "1px solid #bfdbfe" : "1px solid transparent",
  background: active ? "#eff6ff" : "transparent",
  color: active ? "#1d4ed8" : "#334155",
  borderRadius: 10,
  padding: "9px 12px",
  paddingLeft: 12 + depth * 16,
  cursor: "pointer",
  fontSize: 14,
  fontWeight: active ? 700 : 500,
  transition: "all 0.2s ease",
});

const serializeTaxonomyPath = (path) => (Array.isArray(path) ? path.join("/") : "");

function TaxonomyTree({ nodes, activePath, onSelect, depth = 0 }) {
  return (
    <div style={{ display: "grid", gap: 8 }}>
      {nodes.map((node) => {
        const key = serializeTaxonomyPath(node.path);
        const isActive = key === activePath;
        return (
          <div key={key} style={{ display: "grid", gap: 6 }}>
            <button style={sidebarBtnStyle(isActive, depth)} onClick={() => onSelect(node.path)}>
              <span>{node.label}</span>
              <span style={{ color: "#94a3b8", marginLeft: 6 }}>({node.count})</span>
            </button>
            {node.children?.length ? (
              <TaxonomyTree
                nodes={node.children}
                activePath={activePath}
                onSelect={onSelect}
                depth={depth + 1}
              />
            ) : null}
          </div>
        );
      })}
    </div>
  );
}

export default function PapersLibrary() {
  const [taxonomyTree, setTaxonomyTree] = useState([]);
  const [journals, setJournals] = useState([]);
  const [items, setItems] = useState([]);
  const [activeTaxonomyPath, setActiveTaxonomyPath] = useState([]);
  const [activeJournal, setActiveJournal] = useState("");
  const [q, setQ] = useState("");
  const [detail, setDetail] = useState(null);
  const [loading, setLoading] = useState(false);

  const activeTaxonomyParam = useMemo(
    () => serializeTaxonomyPath(activeTaxonomyPath),
    [activeTaxonomyPath]
  );

  useEffect(() => {
    api.get("/papers-library/taxonomy").then((res) => {
      setTaxonomyTree(res.data || []);
    });
  }, []);

  useEffect(() => {
    api
      .get("/papers-library/journals", {
        params: { taxonomy_path: activeTaxonomyParam || undefined },
      })
      .then((res) => {
        const nextJournals = res.data || [];
        setJournals(nextJournals);
        if (activeJournal && !nextJournals.some((j) => j.journal === activeJournal)) {
          setActiveJournal("");
        }
      });
  }, [activeTaxonomyParam, activeJournal]);

  const loadItems = async () => {
    setLoading(true);
    try {
      const res = await api.get("/papers-library/search", {
        params: {
          q: q || undefined,
          taxonomy_path: activeTaxonomyParam || undefined,
          journal: activeJournal || undefined,
          limit: 100,
        },
      });
      setItems(res.data?.items || []);
      setDetail(null);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadItems();
  }, [activeTaxonomyParam, activeJournal]);

  const openDetail = async (id) => {
    if (detail?.item?.id === id) {
      setDetail(null);
      return;
    }
    const res = await api.get(`/papers-library/item/${encodeURIComponent(id)}`);
    setDetail(res.data);
  };

  const activeTaxonomyLabel = activeTaxonomyPath.length
    ? activeTaxonomyPath.join(" / ")
    : "全部标签";
  const activeJournalLabel = activeJournal || "全部期刊";

  return (
    <PapersLayout
      currentSubPath="/dashboard/papers/library"
      currentPapersType="library"
    >
      <div style={{ display: "grid", gap: 20 }}>
        <div
          style={{
            display: "flex",
            justifyContent: "space-between",
            alignItems: "flex-start",
            gap: 16,
            flexWrap: "wrap",
          }}
        >
          <div>
            <div style={{ fontSize: 24, fontWeight: 800, color: "#0f172a" }}>
              研究文献浏览
            </div>
            <div style={{ marginTop: 8, color: "#64748b", fontSize: 14, lineHeight: 1.7 }}>
              基于 papers_index.json 浏览文献，支持树状标签、期刊筛选、关键词检索与正文预览。
            </div>
          </div>

          <div style={{ display: "flex", gap: 10, flexWrap: "wrap", alignItems: "center" }}>
            <span
              style={{
                padding: "6px 10px",
                background: "#f8fafc",
                border: "1px solid #e2e8f0",
                borderRadius: 999,
                color: "#475569",
                fontSize: 13,
              }}
            >
              标签：{activeTaxonomyLabel}
            </span>
            <span
              style={{
                padding: "6px 10px",
                background: "#f8fafc",
                border: "1px solid #e2e8f0",
                borderRadius: 999,
                color: "#475569",
                fontSize: 13,
              }}
            >
              期刊：{activeJournalLabel}
            </span>
            <span
              style={{
                padding: "6px 10px",
                background: "#eff6ff",
                border: "1px solid #bfdbfe",
                borderRadius: 999,
                color: "#1d4ed8",
                fontSize: 13,
                fontWeight: 600,
              }}
            >
              共 {items.length} 篇
            </span>
          </div>
        </div>

        <div style={{ display: "grid", gridTemplateColumns: "300px minmax(0, 1fr)", gap: 24 }}>
          <aside
            style={{
              border: "1px solid #e5e7eb",
              borderRadius: 16,
              padding: 16,
              background: "#fcfcfd",
              height: "fit-content",
              boxShadow: "0 6px 18px rgba(15, 23, 42, 0.04)",
            }}
          >
            <div style={{ fontSize: 15, fontWeight: 800, color: "#0f172a", marginBottom: 12 }}>
              树状标签
            </div>
            <div style={{ display: "grid", gap: 8, marginBottom: 22, maxHeight: 360, overflowY: "auto" }}>
              <button
                style={sidebarBtnStyle(activeTaxonomyPath.length === 0)}
                onClick={() => {
                  setActiveTaxonomyPath([]);
                  setActiveJournal("");
                }}
              >
                全部标签
              </button>
              <TaxonomyTree
                nodes={taxonomyTree}
                activePath={activeTaxonomyParam}
                onSelect={(path) => {
                  setActiveTaxonomyPath(path);
                  setActiveJournal("");
                }}
              />
            </div>

            <div style={{ fontSize: 15, fontWeight: 800, color: "#0f172a", marginBottom: 12 }}>
              期刊
            </div>
            <div
              style={{
                display: "grid",
                gap: 8,
                maxHeight: 360,
                overflowY: "auto",
                paddingRight: 4,
              }}
            >
              <button style={sidebarBtnStyle(activeJournal === "")} onClick={() => setActiveJournal("")}>
                全部期刊
              </button>
              {journals.map((j) => (
                <button
                  key={`${j.slug}:${j.journal}`}
                  style={sidebarBtnStyle(activeJournal === j.journal)}
                  onClick={() => setActiveJournal(j.journal)}
                >
                  <span>{j.journal}</span>
                  <span style={{ color: "#94a3b8", marginLeft: 6 }}>({j.count})</span>
                </button>
              ))}
            </div>
          </aside>

          <section style={{ minWidth: 0 }}>
            <div
              style={{
                display: "flex",
                gap: 12,
                marginBottom: 18,
                alignItems: "center",
                flexWrap: "wrap",
              }}
            >
              <input
                value={q}
                onChange={(e) => setQ(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") loadItems();
                }}
                placeholder="搜索标题、摘要、标签、作者..."
                style={{
                  flex: 1,
                  minWidth: 240,
                  height: 42,
                  borderRadius: 12,
                  border: "1px solid #dbe3ee",
                  padding: "0 14px",
                  fontSize: 14,
                  outline: "none",
                  background: "#fff",
                }}
              />
              <button
                onClick={loadItems}
                style={{
                  height: 42,
                  padding: "0 18px",
                  borderRadius: 12,
                  border: "1px solid #2563eb",
                  background: "#2563eb",
                  color: "#fff",
                  fontWeight: 700,
                  cursor: "pointer",
                  boxShadow: "0 8px 18px rgba(37, 99, 235, 0.18)",
                }}
              >
                检索
              </button>
            </div>

            <div style={{ display: "grid", gridTemplateColumns: detail ? "minmax(0, 0.9fr) minmax(0, 1.1fr)" : "1fr", gap: 18 }}>
              <div style={{ display: "grid", gap: 14, minWidth: 0 }}>
                {loading ? (
                  <div
                    style={{
                      border: "1px dashed #cbd5e1",
                      borderRadius: 14,
                      padding: 20,
                      color: "#64748b",
                      background: "#f8fafc",
                    }}
                  >
                    正在加载文献列表...
                  </div>
                ) : items.length === 0 ? (
                  <div
                    style={{
                      border: "1px dashed #cbd5e1",
                      borderRadius: 14,
                      padding: 24,
                      color: "#64748b",
                      background: "#f8fafc",
                    }}
                  >
                    当前条件下暂无文献结果。
                  </div>
                ) : (
                  items.map((item) => {
                    const active = detail?.item?.id === item.id;
                    return (
                      <button
                        key={item.id}
                        onClick={() => openDetail(item.id)}
                        style={{
                          textAlign: "left",
                          border: active ? "1px solid #bfdbfe" : "1px solid #e5e7eb",
                          borderRadius: 16,
                          padding: 16,
                          background: active ? "#f8fbff" : "#fff",
                          cursor: "pointer",
                          transition: "all 0.2s ease",
                          boxShadow: "0 4px 16px rgba(15, 23, 42, 0.04)",
                        }}
                      >
                        <div style={{ fontSize: 17, fontWeight: 800, color: "#0f172a", lineHeight: 1.5 }}>
                          {item.title}
                        </div>
                        <div style={{ color: "#64748b", marginTop: 6, fontSize: 13 }}>
                          {item.journal || "未知期刊"}
                          {item.year ? ` · ${item.year}` : ""}
                        </div>
                        <div style={{ color: "#475569", marginTop: 8, fontSize: 13 }}>
                          {(item.taxonomy_path || []).join(" / ") || "未分类"}
                        </div>
                        <div
                          style={{
                            color: "#475569",
                            marginTop: 10,
                            lineHeight: 1.7,
                            fontSize: 14,
                            display: "-webkit-box",
                            WebkitLineClamp: 4,
                            WebkitBoxOrient: "vertical",
                            overflow: "hidden",
                          }}
                        >
                          {item.abstract || item.summary || "暂无摘要"}
                        </div>
                      </button>
                    );
                  })
                )}
              </div>

              {detail ? (
                <div
                  style={{
                    border: "1px solid #e5e7eb",
                    borderRadius: 18,
                    background: "#ffffff",
                    overflow: "hidden",
                    boxShadow: "0 10px 24px rgba(15, 23, 42, 0.05)",
                    minWidth: 0,
                  }}
                >
                  <div
                    style={{
                      padding: "18px 20px",
                      borderBottom: "1px solid #eef2f7",
                      background: "#f8fafc",
                      display: "flex",
                      justifyContent: "space-between",
                      alignItems: "flex-start",
                      gap: 16,
                    }}
                  >
                    <div style={{ minWidth: 0 }}>
                      <div style={{ fontSize: 20, fontWeight: 800, color: "#0f172a", lineHeight: 1.5 }}>
                        {detail.item.title}
                      </div>
                      <div style={{ color: "#64748b", marginTop: 8, fontSize: 14 }}>
                        {detail.item.journal || "未知期刊"}
                        {detail.item.year ? ` · ${detail.item.year}` : ""}
                      </div>
                      <div style={{ color: "#475569", marginTop: 8, fontSize: 13 }}>
                        {(detail.item.taxonomy_path || []).join(" / ") || "未分类"}
                      </div>
                    </div>

                    <button
                      onClick={() => setDetail(null)}
                      style={{
                        flexShrink: 0,
                        width: 36,
                        height: 36,
                        borderRadius: 10,
                        border: "1px solid #dbe3ee",
                        background: "#fff",
                        color: "#475569",
                        fontSize: 18,
                        fontWeight: 700,
                        cursor: "pointer",
                        lineHeight: 1,
                      }}
                      title="关闭"
                    >
                      ×
                    </button>
                  </div>

                  <div
                    style={{
                      padding: 20,
                      lineHeight: 1.85,
                      color: "#1f2937",
                      fontSize: 15,
                      maxHeight: 760,
                      overflowY: "auto",
                      background: "#fff",
                    }}
                  >
                    {detail.content ? (
                      <div className="paper-markdown">
                        <ReactMarkdown remarkPlugins={[remarkGfm, remarkMath]} rehypePlugins={[rehypeKatex]}>
                          {detail.content}
                        </ReactMarkdown>
                      </div>
                    ) : (
                      "暂无正文内容"
                    )}
                  </div>
                </div>
              ) : (
                <div
                  style={{
                    border: "1px dashed #cbd5e1",
                    borderRadius: 16,
                    padding: 22,
                    color: "#64748b",
                    background: "#f8fafc",
                  }}
                >
                  从左侧筛选并点击一篇文献，即可在此查看 markdown 正文预览。
                </div>
              )}
            </div>
          </section>
        </div>
      </div>
    </PapersLayout>
  );
}
