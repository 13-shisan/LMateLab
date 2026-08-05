// frontend/src/pages/db/DbLayout.jsx
import React, { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { modules } from "../../config/modules";
import BackIconButton from "../../components/BackIconButton";

const PERSONAL_DB_TYPE_OPTIONS = [
  { key: "entry", label: "个人数据库入口", path: "/dashboard/db/personal" },
  { key: "vasp", label: "VASP 数据库", path: "/dashboard/db/personal/vasp" },
  { key: "qe_epw", label: "QE+EPW 数据库", path: "/dashboard/db/personal/qe-epw" },
];

export default function DbLayout({
  currentSubPath,        // "/dashboard/db/group" | "/dashboard/db/personal"
  currentDbType,         // "entry" | "vasp"（可选）
  showDbTypeSelector,    // true/false（可选）
  children,
}) {
  const navigate = useNavigate();

  // 顶层模块固定为 db，但允许像 TasksLayout 一样切换到其他顶层模块
  const currentTopKey = "db";
  const currentTopModule = useMemo(
    () => modules.find((m) => m.key === currentTopKey),
    [currentTopKey]
  );

  const topEntries = modules;
  const subEntries = currentTopModule?.children || [];

  const currentSubLabel =
    subEntries.find((e) => e.path === currentSubPath)?.label || "数据库";

  const currentDbOption =
    PERSONAL_DB_TYPE_OPTIONS.find((o) => o.key === currentDbType) ??
    PERSONAL_DB_TYPE_OPTIONS[0];

  const [topMenuOpen, setTopMenuOpen] = useState(false);
  const [subMenuOpen, setSubMenuOpen] = useState(false);
  const [dbTypeMenuOpen, setDbTypeMenuOpen] = useState(false);

  const handleTopSelect = (mod) => {
    setTopMenuOpen(false);
    const children = mod.children || [];
    if (children.length === 0) return;
    const first = children[0];
    if (first.path) navigate(first.path);
  };

  const handleSubSelect = (entry) => {
    setSubMenuOpen(false);
    if (!entry.path || entry.path === currentSubPath) return;
    navigate(entry.path);
  };

  const handleDbTypeSelect = (opt) => {
    setDbTypeMenuOpen(false);
    if (!opt.path) return;
    navigate(opt.path);
  };

  // —— 点击空白处关闭下拉（防止一直遮挡）——
  const wrapRef = useRef(null);
  useEffect(() => {
    const onDown = (e) => {
      if (!wrapRef.current) return;
      if (!wrapRef.current.contains(e.target)) {
        setTopMenuOpen(false);
        setSubMenuOpen(false);
        setDbTypeMenuOpen(false);
      }
    };
    document.addEventListener("mousedown", onDown);
    return () => document.removeEventListener("mousedown", onDown);
  }, []);

  // —— 统一的下拉面板样式（间距加大 + z-index 提高）——
  const menuStyle = {
    position: "absolute",
    top: "calc(100% + 10px)",   // ✅ 比 140% 更稳定：永远在按钮下面，并留 10px 间距
    left: 0,
    background: "#ffffff",
    borderRadius: 12,
    boxShadow: "0 10px 40px rgba(15, 23, 42, 0.16)",
    padding: "6px 0",
    minWidth: 180,
    zIndex: 2000,              // ✅ 防遮挡
  };

  return (
    <div className="dashboard-shell">
      <main className="portal-main">
        {/* 面包屑：加大间距，避免按钮挤在一起 */}
        <div
          ref={wrapRef}
          className="page-breadcrumb"
          style={{
            display: "flex",
            alignItems: "center",
            gap: 12,                 // ✅ 原来 8，拉大一点更不挤
            position: "sticky",
            top: 64,
            zIndex: 60,
            padding: "10px 24px",    // ✅ 上下略大一点
            marginBottom: 10,
            flexWrap: "wrap",
            background: "#f3f4f6",
            borderBottom: "1px solid #e5e7eb",
          }}
        >
          {/* 返回 Dashboard */}
          <BackIconButton to="/dashboard" />

          <span style={{ color: "#9ca3af" }}>/</span>

          {/* 第一段：顶层模块下拉 */}
          <div style={{ position: "relative" }}>
            <button
              type="button"
              onClick={() => {
                setTopMenuOpen((v) => !v);
                setSubMenuOpen(false);
                setDbTypeMenuOpen(false);
              }}
              style={{
                border: "none",
                background: "transparent",
                cursor: "pointer",
                display: "inline-flex",
                alignItems: "center",
                gap: 6,               // ✅ 按钮内部间距稍大
                color: "#2563eb",
                fontSize: 14,
                fontWeight: 600,
                padding: "2px 4px",
              }}
            >
              <span>{currentTopModule?.label || "数据库"}</span>
              <span style={{ fontSize: 10 }}>{topMenuOpen ? "▲" : "▼"}</span>
            </button>

            {topMenuOpen && (
              <div style={menuStyle}>
                {topEntries.map((mod) => {
                  const isActive = mod.key === currentTopKey;
                  return (
                    <button
                      key={mod.key}
                      type="button"
                      onClick={() => handleTopSelect(mod)}
                      style={{
                        width: "100%",
                        border: "none",
                        background: isActive ? "#eff6ff" : "transparent",
                        color: isActive ? "#1d4ed8" : "#111827",
                        padding: "8px 12px",     // ✅ 单项高度更舒适
                        display: "flex",
                        alignItems: "center",
                        gap: 10,
                        cursor: isActive ? "default" : "pointer",
                        fontSize: 14,
                      }}
                    >
                      <span style={{ fontSize: 16 }}>
                        {mod.children?.[0]?.icon || "📁"}
                      </span>
                      <span>{mod.label}</span>
                    </button>
                  );
                })}
              </div>
            )}
          </div>

          <span style={{ color: "#9ca3af" }}>/</span>

          {/* 第二段：数据库子模块下拉 */}
          <div style={{ position: "relative" }}>
            <button
              type="button"
              onClick={() => {
                setSubMenuOpen((v) => !v);
                setTopMenuOpen(false);
                setDbTypeMenuOpen(false);
              }}
              style={{
                border: "none",
                background: "transparent",
                cursor: "pointer",
                display: "inline-flex",
                alignItems: "center",
                gap: 6,
                color: "#111827",
                fontSize: 14,
                padding: "2px 4px",
              }}
            >
              <span>{currentSubLabel}</span>
              <span style={{ fontSize: 10, color: "#9ca3af" }}>
                {subMenuOpen ? "▲" : "▼"}
              </span>
            </button>

            {subMenuOpen && (
              <div style={menuStyle}>
                {subEntries.map((entry) => {
                  const isActive = entry.path === currentSubPath;
                  return (
                    <button
                      key={entry.key}
                      type="button"
                      onClick={() => handleSubSelect(entry)}
                      style={{
                        width: "100%",
                        border: "none",
                        background: isActive ? "#eff6ff" : "transparent",
                        color: isActive ? "#1d4ed8" : "#111827",
                        padding: "8px 12px",
                        display: "flex",
                        alignItems: "center",
                        gap: 10,
                        cursor: isActive ? "default" : "pointer",
                        fontSize: 14,
                      }}
                    >
                      <span style={{ fontSize: 16 }}>{entry.icon}</span>
                      <span>{entry.label}</span>
                    </button>
                  );
                })}
              </div>
            )}
          </div>

          {/* 第三段：个人数据库的内部模块（可选） */}
          {showDbTypeSelector && (
            <>
              <span style={{ color: "#9ca3af" }}>/</span>

              <div style={{ position: "relative" }}>
                <button
                  type="button"
                  onClick={() => {
                    setDbTypeMenuOpen((v) => !v);
                    setTopMenuOpen(false);
                    setSubMenuOpen(false);
                  }}
                  style={{
                    border: "none",
                    background: "transparent",
                    cursor: "pointer",
                    display: "inline-flex",
                    alignItems: "center",
                    gap: 6,
                    color: "#111827",
                    fontSize: 14,
                    padding: "2px 4px",
                  }}
                >
                  <span>{currentDbOption.label}</span>
                  <span style={{ fontSize: 10, color: "#9ca3af" }}>
                    {dbTypeMenuOpen ? "▲" : "▼"}
                  </span>
                </button>

                {dbTypeMenuOpen && (
                  <div style={menuStyle}>
                    {PERSONAL_DB_TYPE_OPTIONS.map((opt) => {
                      const isActive = opt.key === currentDbOption.key;
                      return (
                        <button
                          key={opt.key}
                          type="button"
                          onClick={() => handleDbTypeSelect(opt)}
                          style={{
                            width: "100%",
                            border: "none",
                            background: isActive ? "#eff6ff" : "transparent",
                            color: isActive ? "#1d4ed8" : "#111827",
                            padding: "8px 12px",
                            display: "flex",
                            alignItems: "center",
                            gap: 10,
                            cursor: isActive ? "default" : "pointer",
                            fontSize: 14,
                          }}
                        >
                          <span>{opt.label}</span>
                        </button>
                      );
                    })}
                  </div>
                )}
              </div>
            </>
          )}
        </div>

        {/* 页面主体内容 */}
        <section className="card" style={{ flex: 1, minHeight: 360, padding: 24, marginTop: 4 }}>
          {children}
        </section>
      </main>
    </div>
  );
}
