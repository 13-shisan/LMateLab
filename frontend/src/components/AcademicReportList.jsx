// frontend/src/components/AcademicReportList.jsx
function pad2(n) {
  return String(n).padStart(2, "0");
}

function formatCNDate(d) {
  // 01月08日
  return `${pad2(d.getMonth() + 1)}月${pad2(d.getDate())}日`;
}

function formatTime(d) {
  // 14:00
  return `${pad2(d.getHours())}:${pad2(d.getMinutes())}`;
}

export default function AcademicReportList({ items = [], onOpen }) {
  if (!items.length) {
    return (
      <div className="empty-block">
        <div className="empty-icon">📄</div>
        <div className="empty-text">暂无内容</div>
      </div>
    );
  }

  return (
    <div className="acad-list">
      {items.map((it) => {
        const d = it?.startAt ? new Date(it.startAt) : new Date();
        return (
          <div key={it.id} className="acad-item">
            <div className="acad-timebox">
              <div className="acad-date">{formatCNDate(d)}</div>
              <div className="acad-time">{formatTime(d)}</div>
            </div>

            <div className="acad-body">
                <button
                    type="button"
                    className="acad-title acad-title-btn"
                    onClick={() => onOpen?.(it)}
                    title="查看详情"
                    >
                    {it.title}
                </button>
                <div className="acad-meta">
                    <span className="acad-speaker">{it.speaker}</span>
                    <span className="acad-sep">·</span>
                    <span className="acad-location">{it.location}</span>
                </div>
            </div>
          </div>
        );
      })}
    </div>
  );
}
