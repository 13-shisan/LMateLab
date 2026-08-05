// frontend/src/pages/papers/daily.jsx
import { useEffect, useMemo, useState } from "react";
import api from "../../api/client";
import PapersLayout from "./PapersLayout";

function isoToday() {
  const d = new Date();
  const mm = String(d.getMonth() + 1).padStart(2, "0");
  const dd = String(d.getDate()).padStart(2, "0");
  return `${d.getFullYear()}-${mm}-${dd}`;
}

function firstHit(it) {
  const arr = it?.hit_papers || [];
  return arr.length ? arr[0] : null;
}

export default function PapersDaily() {
  const [from, setFrom] = useState("2026-01-02");
  const [to, setTo] = useState(isoToday());
  const [journal, setJournal] = useState("");
  const [category, setCategory] = useState("");
  const [q, setQ] = useState("");

  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);

  const [detailOpen, setDetailOpen] = useState(false);
  const [detail, setDetail] = useState(null);
  const [detailLoading, setDetailLoading] = useState(false);

  const params = useMemo(
    () => ({
      from,
      to,
      journal: journal || undefined,
      category: category || undefined,
      q: q || undefined, // ✅ 新增
    }),
    [from, to, journal, category, q]
  );

  const availableJournals = useMemo(() => {
    const set = new Set();
    (items || []).forEach((it) => {
      if (it?.journal) set.add(it.journal);
    });
    return Array.from(set).sort((a, b) => a.localeCompare(b));
  }, [items]);

  useEffect(() => {
    if (journal && !availableJournals.includes(journal)) {
      setJournal("");
    }
  }, [availableJournals, journal]);


  useEffect(() => {
    let alive = true;
    (async () => {
      setLoading(true);
      try {
        // ✅ 注意：这里要和后端 prefix 对齐（/digests 或 /dailypapers 二选一）
        const res = await api.get("/dailypapers", { params });
        if (!alive) return;
        setItems(res?.data?.items || []);
      } catch (e) {
        console.error("GET /dailypapers failed:", e?.response?.status, e?.response?.data || e);
        if (alive) setItems([]);
      } finally {
        if (alive) setLoading(false);
      }
    })();
    return () => { alive = false; };
  }, [params]);

  const openDetail = async (id) => {
    setDetailOpen(true);
    setDetail(null);
    setDetailLoading(true);
    try {
      const res = await api.get(`/dailypapers/${id}`);
      setDetail(res?.data || null);
    } catch {
      setDetail(null);
    } finally {
      setDetailLoading(false);
    }
  };

  const closeDetail = () => {
    setDetailOpen(false);
    setDetail(null);
    setDetailLoading(false);
  };

  return (
    <PapersLayout currentSubPath="/dashboard/papers/daily" currentPapersType="daily">
      <div className="daily-layout">
        {/* 左：筛选 */}
        <aside className="card daily-filters">
          <div className="section-title">筛选</div>

          <div className="daily-field">
            <div className="form-label">开始日期</div>
            <input className="form-input" type="date" value={from} onChange={(e) => setFrom(e.target.value)} />
          </div>

          <div className="daily-field">
            <div className="form-label">结束日期</div>
            <input className="form-input" type="date" value={to} onChange={(e) => setTo(e.target.value)} />
          </div>

          <div className="daily-field">
            <div className="form-label">期刊</div>
            <select
              className="form-input"
              value={journal}
              onChange={(e) => setJournal(e.target.value)}
            >
              <option value="">全部</option>
              {availableJournals.map((j) => (
                <option key={j} value={j}>{j}</option>
              ))}
            </select>
          </div>

          <div className="daily-field">
            <div className="form-label">分类</div>
            <input
              className="form-input"
              placeholder="如：凝聚态/材料/量子信息…（可选）"
              value={category}
              onChange={(e) => setCategory(e.target.value)}
            />
          </div>

          <div className="daily-field">
            <div className="form-label">关键词</div>
            <input
              className="form-input"
              placeholder="如：NiPS3 / perovskite / topological..."
              value={q}
              onChange={(e) => setQ(e.target.value)}
            />
          </div>

          <button className="btn btn-primary" type="button" onClick={() => setTo(isoToday())}>
            回到今天
          </button>
        </aside>

        {/* 右：列表 */}
        <section className="card daily-list">
          <div className="section-header">
            <div className="section-title">导读列表</div>
            <div style={{ color: "var(--muted)", fontSize: 12 }}>共 {items.length} 条</div>
          </div>

          {loading ? (
            <div className="empty-block"><div className="empty-text">加载中...</div></div>
          ) : items.length === 0 ? (
            <div className="empty-block"><div className="empty-text">没有数据</div></div>
          ) : (
            <div className="daily-items">
              {items.map((it) => (
                <button key={it.id} className="daily-item" type="button" onClick={() => openDetail(it.id)}>
                  <div className="daily-item-main">
                    <div className="daily-item-title">
                      {it.title || `${it.date}《${it.journal}》期刊新文献导读`}
                    </div>
                    <div className="daily-item-sub">
                      {it.code || "—"} <span className="acad-sep">·</span> {it.category || "未分类"}
                    </div>

                    {q && firstHit(it) ? (
                      <div style={{ marginTop: 6, fontSize: 12, color: "var(--muted)", lineHeight: 1.4 }}>
                        <div style={{ fontWeight: 600, color: "var(--text)" }}>
                          1. {firstHit(it).title}
                        </div>

                        <div style={{ marginTop: 2 }}>
                          {(firstHit(it).published || "").slice(0, 10) || "—"}
                          {firstHit(it).doi ? (
                            <>
                              <span className="acad-sep">·</span> DOI: {firstHit(it).doi}
                            </>
                          ) : null}
                        </div>

                        {firstHit(it).authors?.length ? (
                          <div style={{ marginTop: 2 }}>
                            作者：{firstHit(it).authors.join(", ")}
                          </div>
                        ) : null}
                      </div>
                    ) : null}
                  </div>
                  <div className="daily-item-time">{it.time || ""}</div>
                </button>
              ))}
            </div>
          )}
        </section>

        {/* 详情 Modal */}
        {detailOpen && (
          <>
            <div className="modal-backdrop modal-backdrop-show" onClick={closeDetail} />
            <div className="acad-modal">
              <div className="acad-modal-header">
                <div className="acad-modal-h1">{detail?.title || "导读详情"}</div>
                <button className="icon-btn" type="button" onClick={closeDetail}>✕</button>
              </div>

              <div className="acad-modal-body">
                {detailLoading ? (
                  <div className="empty-block"><div className="empty-text">加载中...</div></div>
                ) : detail ? (
                  <>
                    {detail?.papers?.length ? (
                      <div className="paper-list">
                        {detail.papers.map((p, idx) => (
                          <div key={idx} className="paper-item-card">
                            <div className="paper-title" style={{ fontWeight: 700 }}>
                              {idx + 1}. {p.title}
                            </div>

                            <div className="paper-meta" style={{ color: "var(--muted)", fontSize: 12, marginTop: 6 }}>
                              {p.published ? <span>{p.published}</span> : null}
                              {p.doi ? <span className="acad-sep">·</span> : null}
                              {p.doi ? <span>DOI: {p.doi}</span> : null}
                            </div>

                            {p.authors?.length ? (
                              <div className="paper-authors" style={{ marginTop: 6 }}>
                                <b>作者：</b>{p.authors.join(", ")}
                              </div>
                            ) : null}

                            {(p.abstract_text || p.abstract_raw || p.summary_text) ? (
                              <div className="paper-abstract" style={{ marginTop: 6 }}>
                                <b>{p.abstract_text || p.abstract_raw ? "摘要：" : "简介："}</b>
                                <div style={{ whiteSpace: "pre-wrap" }}>
                                  {p.abstract_text || p.abstract_raw || p.summary_text}
                                </div>
                              </div>
                            ) : null}

                            {p.link ? (
                              <div style={{ marginTop: 8 }}>
                                <a
                                  href={p.link}
                                  target="_blank"
                                  rel="noreferrer"
                                  style={{ color: "#1677ff", fontWeight: 600 }}
                                >
                                  原文链接
                                </a>
                              </div>
                            ) : null}
                          </div>
                        ))}
                      </div>
                    ) : (
                      <pre className="daily-pre">{detail?.content || ""}</pre>
                    )}
                  </>
                ) : (
                  <div className="empty-block"><div className="empty-text">加载失败</div></div>
                )}
              </div>
            </div>
          </>
        )}
      </div>
    </PapersLayout>
  );
}
