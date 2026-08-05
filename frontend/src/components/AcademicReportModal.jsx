// frontend/src/components/AcademicReportModal.jsx

import { useEffect } from "react";

function formatDT(iso) {
  if (!iso) return "-";
  const d = new Date(iso);
  const pad2 = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad2(d.getMonth() + 1)}-${pad2(d.getDate())} ${pad2(d.getHours())}:${pad2(d.getMinutes())}`;
}

function Row({ label, value }) {
  return (
    <div className="acad-row">
      <div className="acad-row-label">{label}</div>
      <div className="acad-row-value">{value || "-"}</div>
    </div>
  );
}

export default function AcademicReportModal({ open, item, loading, onClose }) {
  useEffect(() => {
    if (!open) return;
    const onKey = (e) => {
      if (e.key === "Escape") onClose?.();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  if (!open) return null;

  const timeText = item?.endAt
    ? `${formatDT(item?.startAt)} - ${formatDT(item?.endAt)}`
    : formatDT(item?.startAt);

  return (
    <>
    <div className="modal-backdrop modal-backdrop-show" onClick={onClose} />

    <div className="acad-modal acad-modal-show" role="dialog" aria-modal="true">
        <div className="acad-modal-header">
        <div className="acad-modal-title">学术报告详情</div>
            <button type="button" className="module-modal-close" onClick={onClose}>
                ✕
            </button>
        </div>

        <div className="acad-modal-body">
            {loading ? (
                <div className="empty-block">
                <div className="empty-icon">⏳</div>
                <div className="empty-text">加载中...</div>
                </div>
            ) : (
                <>
                {/* 题目 */}
                <div className="acad-modal-h1">{item?.title || "-"}</div>

                {/* 时间 / 地点 / 报告人 */}
                <div className="acad-grid">
                    <Row label="时间" value={timeText} />
                    <Row label="地点" value={item?.location} />
                    <Row label="报告人" value={item?.speaker} />
                    {/* 可选：腾讯会议号 */}
                    {item?.meetingId ? <Row label="腾讯会议号" value={item.meetingId} /> : null}
                </div>

                {/* 报告摘要 */}
                <div className="acad-section">
                    <div className="acad-section-title">报告摘要</div>
                    <div className="acad-section-text" style={{ whiteSpace: "pre-wrap" }}>
                    {item?.abstract || "-"}
                    </div>
                </div>

                {/* 报告人简介 */}
                <div className="acad-section">
                    <div className="acad-section-title">报告人简介</div>
                    <div className="acad-section-text" style={{ whiteSpace: "pre-wrap" }}>
                    {item?.speakerBio || "-"}
                    </div>
                </div>

                {/* 参考文献 */}
                <div className="acad-section">
                    <div className="acad-section-title">参考文献</div>
                    <div className="acad-section-text" style={{ whiteSpace: "pre-wrap" }}>
                    {item?.references || "-"}
                    </div>
                </div>

                {/* 相关链接 */}
                {Array.isArray(item?.links) && item.links.length ? (
                <div className="acad-section">
                    <div className="acad-section-title">相关链接</div>

                    <ul className="acad-links">
                    {item.links.filter(l => l?.url).map((l, idx) => (
                        <li key={idx} className="acad-links-item">
                        <a
                            href={l?.url}
                            target="_blank"
                            rel="noreferrer"
                            className="acad-links-a"
                        >
                            {l?.label || l?.url}
                        </a>

                        {/* 如果 label 存在，再把 url 作为淡化文本展示出来（可选） */}
                        {l?.label ? <span className="acad-links-url">{l?.url}</span> : null}
                        </li>
                    ))}
                    </ul>
                </div>
                ) : null}

                {/* 邀请单位 / 邀请人 */}
                <div className="acad-grid">
                    <Row label="邀请单位" value={item?.invitingUnit} />
                    <Row label="邀请人" value={item?.inviter} />
                </div>
                </>
        )}
        </div>
    </div>
    </>
  );
}
