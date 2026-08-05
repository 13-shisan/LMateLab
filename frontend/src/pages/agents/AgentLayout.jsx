// frontend/src/pages/agents/AgentLayout.jsx
import React, { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { modules } from "../../config/modules";
import BackIconButton from "../../components/BackIconButton";
import { Bot, Compass } from "lucide-react";

const AGENT_OPTIONS = [
  { key: "entry", label: "智能体入口", path: "/dashboard/agents", icon: Bot },
  { key: "general-chat", label: "通用大模型", path: "/dashboard/agents/general-chat", icon: Bot },
  { key: "platform-guide", label: "平台导览智能体", path: "/dashboard/agents/platform-guide", icon: Compass },
];

export default function AgentLayout({
  currentPath,
  currentAgentKey = "entry",
  children,
}) {
  const navigate = useNavigate();

  const currentTopKey = "agents";
  const currentTopModule = useMemo(
    () => modules.find((m) => m.key === currentTopKey),
    []
  );

  const topEntries = modules;
  const currentAgent =
    AGENT_OPTIONS.find((s) => s.key === currentAgentKey) || AGENT_OPTIONS[0];

  const [topMenuOpen, setTopMenuOpen] = useState(false);
  const [agentMenuOpen, setAgentMenuOpen] = useState(false);

  const wrapRef = useRef(null);

  useEffect(() => {
    const onDown = (e) => {
      if (!wrapRef.current) return;
      if (!wrapRef.current.contains(e.target)) {
        setTopMenuOpen(false);
        setAgentMenuOpen(false);
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

  const handleAgentSelect = (entry) => {
    setAgentMenuOpen(false);
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
                setAgentMenuOpen(false);
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
              <span>{currentTopModule?.label || "智能体"}</span>
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
                        {mod.children?.[0]?.icon || "🤖"}
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
                setAgentMenuOpen((v) => !v);
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
              <span>{currentAgent.label}</span>
              <span style={{ fontSize: 10, color: "#9ca3af" }}>
                {agentMenuOpen ? "▲" : "▼"}
              </span>
            </button>

            {agentMenuOpen && (
              <div style={menuStyle}>
                {AGENT_OPTIONS.map((entry) => {
                  const isActive = entry.key === currentAgent.key;
                  const Icon = entry.icon || Bot;

                  return (
                    <button
                      key={entry.key}
                      type="button"
                      onClick={() => handleAgentSelect(entry)}
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
                      <Icon size={16} />
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
