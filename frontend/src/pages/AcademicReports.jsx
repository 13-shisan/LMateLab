// frontend/src/pages/AcademicReports.jsx
import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import AcademicReportList from "../components/AcademicReportList";
import AcademicReportModal from "../components/AcademicReportModal";
import api from "../api/client";

export default function AcademicReports() {
    const pageSize = 10;
    const [page, setPage] = useState(1);

    const [items, setItems] = useState([]);
    const [total, setTotal] = useState(0);
    const [loading, setLoading] = useState(true);

    const [openId, setOpenId] = useState(null);
    const [detail, setDetail] = useState(null);
    const [detailLoading, setDetailLoading] = useState(false);

    const navigate = useNavigate();

    useEffect(() => {
        let alive = true;

        (async () => {
        setLoading(true);
        try {
            const res = await api.get("/academic-reports", {
            params: { page, page_size: pageSize },
            });
            if (!alive) return;
            setItems(res?.data?.items || []);
            setTotal(res?.data?.total || 0);
        } catch {
            if (!alive) return;
            setItems([]);
            setTotal(0);
        } finally {
            if (alive) setLoading(false);
        }
        })();

        return () => {
        alive = false;
        };
    }, [page]);

    const totalPages = Math.max(1, Math.ceil(total / pageSize));
    const safePage = Math.min(Math.max(1, page), totalPages);

        // 生成中间 3 个页码（尽量围绕当前页）
        const get3Pages = (p, tp) => {
        if (tp <= 3) return Array.from({ length: tp }, (_, i) => i + 1);

        if (p <= 1) return [1, 2, 3];
        if (p >= tp) return [tp - 2, tp - 1, tp];

        // 让当前页尽量在中间
        if (p === 2) return [1, 2, 3];
        if (p === tp - 1) return [tp - 2, tp - 1, tp];
        return [p - 1, p, p + 1];
        };

        const pageBtns = get3Pages(safePage, totalPages);

    const openDetail = async (it) => {
        const id = it?.id;
        if (!id) return;

        setOpenId(id);
        setDetail(it);
        setDetailLoading(true);

        try {
        const res = await api.get(`/academic-reports/${id}`);
        setDetail(res.data);
        } catch (e) {
        console.error(e);
        } finally {
        setDetailLoading(false);
        }
    };

    const closeDetail = () => {
        setOpenId(null);
        setDetail(null);
        setDetailLoading(false);
    };

    return (
        <div className="dashboard-shell">
        <main className="portal-main">
            <div className="card acad-card">
                <div className="section-header">
                    {/* 左侧：返回图标 + 标题 */}
                    <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                    <button
                        type="button"
                        className="icon-btn"
                        onClick={() => navigate("/dashboard")}
                        aria-label="返回"
                        title="返回"
                    >
                        {/* 左箭头图标（SVG，不依赖任何库） */}
                        <svg width="18" height="18" viewBox="0 0 24 24" aria-hidden="true">
                        <path
                            d="M15 18l-6-6 6-6"
                            fill="none"
                            stroke="currentColor"
                            strokeWidth="2.2"
                            strokeLinecap="round"
                            strokeLinejoin="round"
                        />
                        </svg>
                    </button>

                    <div className="section-title">学术报告</div>
                    </div>

                    {/* 右侧留空即可，或者放筛选/搜索 */}
                    <div />
                </div>

                {loading ? (
                    <div className="empty-block">
                    <div className="empty-icon">⏳</div>
                    <div className="empty-text">加载中...</div>
                    </div>
                ) : (
                    <AcademicReportList items={items} onOpen={openDetail} />
                )}

                {/* 右下角分页（首页 / 3页码 / 尾页 + 总条数） */}
                <div className="acad-pager-fab" aria-label="分页">
                <button
                    className="btn acad-pager-fab-btn"
                    type="button"
                    onClick={() => setPage(1)}
                    disabled={safePage <= 1}
                >
                    首页
                </button>

                <div className="acad-pager-pages" aria-label="页码">
                    {pageBtns.map((p) => (
                    <button
                        key={p}
                        type="button"
                        className={`acad-page-btn ${p === safePage ? "is-active" : ""}`}
                        onClick={() => setPage(p)}
                        aria-current={p === safePage ? "page" : undefined}
                    >
                        {p}
                    </button>
                    ))}
                </div>

                <button
                    className="btn acad-pager-fab-btn"
                    type="button"
                    onClick={() => setPage(totalPages)}
                    disabled={safePage >= totalPages}
                >
                    尾页
                </button>

                <div className="acad-pager-total" title={`共 ${total} 条`}>
                    共 {total} 条
                </div>
                </div>
            </div>

            <AcademicReportModal
            open={!!openId}
            item={detail}
            loading={detailLoading}
            onClose={closeDetail}
            />
        </main>
        </div>
    );
}
