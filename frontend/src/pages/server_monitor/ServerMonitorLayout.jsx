// frontend/src/pages/ServerMonitorLayout.jsx
import React, { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { modules } from "../../config/modules";
import BackIconButton from "../../components/BackIconButton";

const SERVER_OPTIONS = [
  { key: "entry", label: "服务器入口", path: "/dashboard/server-monitor" },
  { key: "users-overview", label: "用户使用总览", path: "/dashboard/server-monitor/users-overview" },
  { key: "Dell", label: "Dell", path: "/dashboard/server-monitor/Dell" },
  { key: "Dell-GPU", label: "Dell-GPU", path: "/dashboard/server-monitor/Dell-GPU" },
  { key: "Dawn4", label: "Dawn4", path: "/dashboard/server-monitor/Dawn4" },
  { key: "Dawn5", label: "Dawn5", path: "/dashboard/server-monitor/Dawn5" },
  { key: "Sugon", label: "Sugon", path: "/dashboard/server-monitor/Sugon" },
  { key: "Jingzhun-xjwu", label: "精准-xjwu", path: "/dashboard/server-monitor/Jingzhun-xjwu" },
  { key: "Jingzhun-jbwu", label: "精准-jbwu", path: "/dashboard/server-monitor/Jingzhun-jbwu" },
  { key: "Jingzhun-GPU", label: "精准-GPU", path: "/dashboard/server-monitor/Jingzhun-GPU" },
  { key: "Shuangyiliu-huayuan", label: "双一流化院", path: "/dashboard/server-monitor/Shuangyiliu-huayuan" },
  { key: "Shuangyiliu-HFNL-xjwu", label: "双一流微尺度-xjwu", path: "/dashboard/server-monitor/Shuangyiliu-HFNL-xjwu" },
  { key: "Shuangyiliu-HFNL-hflv", label: "双一流微尺度-hflv", path: "/dashboard/server-monitor/Shuangyiliu-HFNL-hflv" },
  { key: "SCNet", label: "合肥超算", path: "/dashboard/server-monitor/SCNet" },
  { key: "Wuxi", label: "无锡超算", path: "/dashboard/server-monitor/Wuxi" },
  { key: "Dongfang-xjwu", label: "东方超算-xjwu", path: "/dashboard/server-monitor/Dongfang-xjwu" },
  { key: "Dongfang-yang4", label: "东方超算-yang4", path: "/dashboard/server-monitor/Dongfang-yang4" }

];

export default function ServerMonitorLayout({
  currentPath,
  currentServerKey = "entry",
  children,
}) {
  const navigate = useNavigate();

  const currentTopKey = "server_monitor";
  const currentTopModule = useMemo(
    () => modules.find((m) => m.key === currentTopKey),
    [currentTopKey]
  );

  const topEntries = modules;
  const currentServer =
    SERVER_OPTIONS.find((s) => s.key === currentServerKey) || SERVER_OPTIONS[0];

  const [topMenuOpen, setTopMenuOpen] = useState(false);
  const [serverMenuOpen, setServerMenuOpen] = useState(false);

  const wrapRef = useRef(null);

  useEffect(() => {
    const onDown = (e) => {
      if (!wrapRef.current) return;
      if (!wrapRef.current.contains(e.target)) {
        setTopMenuOpen(false);
        setServerMenuOpen(false);
      }
    };
    document.addEventListener("mousedown", onDown);
    return () => document.removeEventListener("mousedown", onDown);
  }, []);

  const handleTopSelect = (mod) => {
    setTopMenuOpen(false);
    const children = mod.children || [];
    if (children.length === 0) return;
    const first = children[0];
    if (first.path) navigate(first.path);
  };

  const handleServerSelect = (entry) => {
    setServerMenuOpen(false);
    if (!entry.path || entry.path === currentPath) return;
    navigate(entry.path);
  };

  const menuStyle = {
    position: "absolute",
    top: "calc(100% + 10px)",
    left: 0,
    background: "#ffffff",
    borderRadius: 12,
    boxShadow: "0 10px 40px rgba(15, 23, 42, 0.16)",
    padding: "6px 0",
    minWidth: 220,
    zIndex: 2000,
  };

  return (
    <div className="dashboard-shell">
      <main className="portal-main">
        <div
          ref={wrapRef}
          className="page-breadcrumb"
          style={{
            display: "flex",
            alignItems: "center",
            gap: 12,
            position: "sticky",
            top: 64,
            zIndex: 60,
            padding: "10px 24px",
            marginBottom: 10,
            flexWrap: "wrap",
            background: "#f3f4f6",
            borderBottom: "1px solid #e5e7eb",
          }}
        >
          <BackIconButton to="/dashboard" />

          <span style={{ color: "#9ca3af" }}>/</span>

          <div style={{ position: "relative" }}>
            <button
              type="button"
              onClick={() => {
                setTopMenuOpen((v) => !v);
                setServerMenuOpen(false);
              }}
              style={{
                border: "none",
                background: "transparent",
                cursor: "pointer",
                display: "inline-flex",
                alignItems: "center",
                gap: 6,
                color: "#2563eb",
                fontSize: 14,
                fontWeight: 600,
                padding: "2px 4px",
              }}
            >
              <span>{currentTopModule?.label || "服务器信息"}</span>
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
                        padding: "8px 12px",
                        display: "flex",
                        alignItems: "center",
                        gap: 10,
                        cursor: isActive ? "default" : "pointer",
                        fontSize: 14,
                      }}
                    >
                      <span style={{ fontSize: 16 }}>
                        {mod.children?.[0]?.icon || "🖥️"}
                      </span>
                      <span>{mod.label}</span>
                    </button>
                  );
                })}
              </div>
            )}
          </div>

          <span style={{ color: "#9ca3af" }}>/</span>

          <div style={{ position: "relative" }}>
            <button
              type="button"
              onClick={() => {
                setServerMenuOpen((v) => !v);
                setTopMenuOpen(false);
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
              <span>{currentServer.label}</span>
              <span style={{ fontSize: 10, color: "#9ca3af" }}>
                {serverMenuOpen ? "▲" : "▼"}
              </span>
            </button>

            {serverMenuOpen && (
              <div style={menuStyle}>
                {SERVER_OPTIONS.map((entry) => {
                  const isActive = entry.key === currentServer.key;
                  return (
                    <button
                      key={entry.key}
                      type="button"
                      onClick={() => handleServerSelect(entry)}
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
                      <span>🖥️</span>
                      <span>{entry.label}</span>
                    </button>
                  );
                })}
              </div>
            )}
          </div>
        </div>

        <section
          className="card"
          style={{ flex: 1, minHeight: 360, padding: 24, marginTop: 4 }}
        >
          {children}
        </section>
      </main>
    </div>
  );
}
