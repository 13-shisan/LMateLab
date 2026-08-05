// frontend/src/pages/papers/PapersLayout.jsx
import React, { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { modules } from "../../config/modules";
import BackIconButton from "../../components/BackIconButton";

const PAPERS_TYPE_OPTIONS = [
  { key: "daily", label: "每日导读", path: "/dashboard/papers/daily" },
  { key: "subscription", label: "订阅管理", path: "/dashboard/papers/subscription" },
  { key: "library", label: "文献库", path: "/dashboard/papers/library" },
];

export default function PapersLayout({
  currentSubPath,
  currentPapersType,
  children,
}) {
  const navigate = useNavigate();

  const currentTopKey = "papers";
  const currentTopModule = useMemo(
    () => modules.find((m) => m.key === currentTopKey),
    [currentTopKey]
  );

  const topEntries = modules;
  const subEntries = currentTopModule?.children || [];

  const currentSubLabel =
    subEntries.find((e) => e.path === currentSubPath)?.label || "文献推荐";

  const currentPapersOption =
    PAPERS_TYPE_OPTIONS.find((o) => o.key === currentPapersType) ??
    PAPERS_TYPE_OPTIONS[0];

  const showLastCrumb = currentSubLabel !== currentPapersOption.label;

  const [topMenuOpen, setTopMenuOpen] = useState(false);
  const [subMenuOpen, setSubMenuOpen] = useState(false);
  const [papersMenuOpen, setPapersMenuOpen] = useState(false);

  const wrapRef = useRef(null);
  useEffect(() => {
    const onDown = (e) => {
      if (!wrapRef.current) return;
      if (!wrapRef.current.contains(e.target)) {
        setTopMenuOpen(false);
        setSubMenuOpen(false);
        setPapersMenuOpen(false);
      }
    };
    document.addEventListener("mousedown", onDown);
    return () => document.removeEventListener("mousedown", onDown);
  }, []);

  const menuStyle = {
    position: "absolute",
    top: "calc(100% + 10px)",
    left: 0,
    background: "#ffffff",
    borderRadius: 14,
    boxShadow: "0 16px 40px rgba(15, 23, 42, 0.14)",
    border: "1px solid #e5e7eb",
    padding: "6px 0",
    minWidth: 190,
    zIndex: 2000,
  };

  const crumbBtnStyle = {
    border: "none",
    background: "transparent",
    cursor: "pointer",
    display: "inline-flex",
    alignItems: "center",
    gap: 6,
    fontSize: 14,
    padding: "4px 6px",
    borderRadius: 8,
  };

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

  const handlePapersTypeSelect = (opt) => {
    setPapersMenuOpen(false);
    if (!opt.path || opt.path === currentSubPath) return;
    navigate(opt.path);
  };

  return (
    <div className="dashboard-shell" style={{ background: "#f8fafc", minHeight: "100vh" }}>
      <main className="portal-main" style={{ paddingBottom: 24 }}>
        <div
          ref={wrapRef}
          className="page-breadcrumb"
          style={{
            display: "flex",
            alignItems: "center",
            gap: 10,
            position: "sticky",
            top: 64,
            zIndex: 60,
            padding: "12px 24px",
            marginBottom: 16,
            flexWrap: "wrap",
            background: "rgba(248, 250, 252, 0.9)",
            backdropFilter: "blur(8px)",
            borderBottom: "1px solid #e5e7eb",
          }}
        >
          <BackIconButton to="/dashboard" />

          <span style={{ color: "#cbd5e1" }}>/</span>

          <div style={{ position: "relative" }}>
            <button
              type="button"
              onClick={() => {
                setTopMenuOpen((v) => !v);
                setSubMenuOpen(false);
                setPapersMenuOpen(false);
              }}
              style={{
                ...crumbBtnStyle,
                color: "#2563eb",
                fontWeight: 700,
              }}
            >
              <span>{currentTopModule?.label || "文献推荐"}</span>
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
                        padding: "10px 14px",
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

          <span style={{ color: "#cbd5e1" }}>/</span>

          <div style={{ position: "relative" }}>
            <button
              type="button"
              onClick={() => {
                setSubMenuOpen((v) => !v);
                setTopMenuOpen(false);
                setPapersMenuOpen(false);
              }}
              style={{
                ...crumbBtnStyle,
                color: "#334155",
              }}
            >
              <span>{currentSubLabel}</span>
              <span style={{ fontSize: 10, color: "#94a3b8" }}>
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
                        padding: "10px 14px",
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

          {showLastCrumb && (
            <>
              <span style={{ color: "#cbd5e1" }}>/</span>

              <div style={{ position: "relative" }}>
                <button
                  type="button"
                  onClick={() => {
                    setPapersMenuOpen((v) => !v);
                    setTopMenuOpen(false);
                    setSubMenuOpen(false);
                  }}
                  style={{
                    ...crumbBtnStyle,
                    color: "#334155",
                  }}
                >
                  <span>{currentPapersOption.label}</span>
                  <span style={{ fontSize: 10, color: "#94a3b8" }}>
                    {papersMenuOpen ? "▲" : "▼"}
                  </span>
                </button>

                {papersMenuOpen && (
                  <div style={menuStyle}>
                    {PAPERS_TYPE_OPTIONS.map((opt) => {
                      const isActive = opt.key === currentPapersOption.key;
                      return (
                        <button
                          key={opt.key}
                          type="button"
                          onClick={() => handlePapersTypeSelect(opt)}
                          style={{
                            width: "100%",
                            border: "none",
                            background: isActive ? "#eff6ff" : "transparent",
                            color: isActive ? "#1d4ed8" : "#111827",
                            padding: "10px 14px",
                            cursor: isActive ? "default" : "pointer",
                            fontSize: 14,
                            textAlign: "left",
                          }}
                        >
                          {opt.label}
                        </button>
                      );
                    })}
                  </div>
                )}
              </div>
            </>
          )}
        </div>

        <section
          className="card"
          style={{
            flex: 1,
            minHeight: 420,
            padding: 24,
            marginTop: 0,
            marginInline: 24,
            borderRadius: 20,
            background: "#ffffff",
            border: "1px solid #e5e7eb",
            boxShadow: "0 8px 30px rgba(15, 23, 42, 0.05)",
          }}
        >
          {children}
        </section>
      </main>
    </div>
  );
}
