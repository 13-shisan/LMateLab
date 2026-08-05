// frontend/src/pages/notes/TasksLayout.jsx
import React, { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { modules } from "../../config/modules";
import BackIconButton from "../../components/BackIconButton";

const TASK_TYPE_OPTIONS = [
  { key: "entry", label: "任务类型入口", path: "/dashboard/notes/tasksentry" },
  { key: "all", label: "全部任务", path: "/dashboard/notes/tasksall" },
  { key: "vasp", label: "VASP 任务", path: "/dashboard/notes/tasksvasp" },
  { key: "qe", label: "QE 任务", path: "/dashboard/notes/tasksqe" },
  { key: "gaussian", label: "Gaussian 任务", path: "/dashboard/notes/tasksgaussian" },
  { key: "deepmd", label: "DeepMD 任务", path: "/dashboard/notes/tasksdeepmd" },
  { key: "lasp", label: "LASP 任务", path: "/dashboard/notes/taskslasp" },
  { key: "cp2k", label: "CP2K 任务", path: "/dashboard/notes/taskscp2k" },
];

export default function TasksLayout({
  currentSubPath,          // 如："/dashboard/notes/tasksall"
  currentTaskType,         // 如："vasp"
  showTaskTypeSelector,    // true: 显示第三个下拉
  children,
}) {
  const navigate = useNavigate();

  const [topMenuOpen, setTopMenuOpen] = useState(false);
  const [subMenuOpen, setSubMenuOpen] = useState(false);
  const [taskMenuOpen, setTaskMenuOpen] = useState(false);

  // 顶层模块：notes
  const currentTopKey = "notes";
  const currentTopModule = modules.find((m) => m.key === currentTopKey);
  const topEntries = modules;
  const subEntries = currentTopModule?.children || [];

  const currentSubLabel =
    subEntries.find((e) => e.path === currentSubPath)?.label || "任务总览";

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

  // 任务类型相关：当前 label & 切换
  const currentTaskOption =
    TASK_TYPE_OPTIONS.find((o) => o.key === currentTaskType) ??
    TASK_TYPE_OPTIONS[0];

  const handleTaskSelect = (option) => {
    setTaskMenuOpen(false);
    if (!option.path) return;
    if (option.path === currentSubPath) return;
    navigate(option.path);
  };

  // 点击空白处关闭下拉
  const wrapRef = useRef(null);
  useEffect(() => {
    const onDown = (e) => {
      if (!wrapRef.current) return;
      if (!wrapRef.current.contains(e.target)) {
        setTopMenuOpen(false);
        setSubMenuOpen(false);
        setTaskMenuOpen(false);
      }
    };
    document.addEventListener("mousedown", onDown);
    return () => document.removeEventListener("mousedown", onDown);
  }, []);

  // 统一下拉菜单样式（间距更大、不遮挡）
  const menuStyle = {
    position: "absolute",
    top: "calc(100% + 10px)",
    left: 0,
    background: "#ffffff",
    borderRadius: 12,
    boxShadow: "0 10px 40px rgba(15, 23, 42, 0.16)",
    padding: "6px 0",
    minWidth: 180,
    zIndex: 2000,
  };

  return (
    <div className="dashboard-shell">
      <main className="portal-main">
        {/* 面包屑：固定在蓝色导航条下面 */}
        <div
          ref={wrapRef}
          className="page-breadcrumb"
          style={{
            display: "flex",
            alignItems: "center",
            gap: 12,               // ✅ 拉大间距
            position: "sticky",
            top: 64,
            zIndex: 60,
            padding: "10px 24px",  // ✅ 上下略大一点
            marginBottom: 10,
            flexWrap: "wrap",
            background: "#f3f4f6",
            borderBottom: "1px solid #e5e7eb",
          }}
        >
          {/* 返回 Dashboard */}
          <BackIconButton to="/dashboard" />

          <span style={{ color: "#9ca3af" }}>/</span>

          {/* 顶层模块下拉：实验记录本 ▼ */}
          <div style={{ position: "relative" }}>
            <button
              type="button"
              onClick={() => {
                setTopMenuOpen((v) => !v);
                setSubMenuOpen(false);
                setTaskMenuOpen(false);
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
              <span>{currentTopModule?.label || "实验记录本"}</span>
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

          {/* 第二段：notes 子模块下拉 */}
          <div style={{ position: "relative" }}>
            <button
              type="button"
              onClick={() => {
                setSubMenuOpen((v) => !v);
                setTopMenuOpen(false);
                setTaskMenuOpen(false);
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

          {/* 第三段：任务类型（可选） */}
          {showTaskTypeSelector && (
            <>
              <span style={{ color: "#9ca3af" }}>/</span>

              <div style={{ position: "relative" }}>
                <button
                  type="button"
                  onClick={() => {
                    setTaskMenuOpen((v) => !v);
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
                  <span>{currentTaskOption.label}</span>
                  <span style={{ fontSize: 10, color: "#9ca3af" }}>
                    {taskMenuOpen ? "▲" : "▼"}
                  </span>
                </button>

                {taskMenuOpen && (
                  <div style={menuStyle}>
                    {TASK_TYPE_OPTIONS.map((opt) => {
                      const isActive = opt.key === currentTaskOption.key;
                      return (
                        <button
                          key={opt.key}
                          type="button"
                          onClick={() => handleTaskSelect(opt)}
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
        <section
          className="card"
          style={{
            flex: 1,
            minHeight: 360,
            padding: 24,
            marginTop: 4,
          }}
        >
          {children}
        </section>
      </main>
    </div>
  );
}
