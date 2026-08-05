// frontend/src/pages/notes/Journal.jsx
import React, { useState } from "react";
import { useNavigate } from "react-router-dom";
import { modules } from "../../config/modules";   // 路径注意：从 notes 到 config
import Notes from "../modules/Notes";            // 复用你的 Notes 组件
import BackIconButton from "../../components/BackIconButton";

export default function NotesJournal() {
  const navigate = useNavigate();

  // 顶层模块下拉：实验记录本 / 项目管理 / 文件收集 / ...
  const [topMenuOpen, setTopMenuOpen] = useState(false);
  // 子模块下拉：记录本 / 模板 / 数据合集 / 任务总览 / ...
  const [subMenuOpen, setSubMenuOpen] = useState(false);

  // 当前顶层模块：实验记录本
  const currentTopKey = "notes";
  const currentTopModule = modules.find((m) => m.key === currentTopKey);
  const topEntries = modules;
  const subEntries = currentTopModule?.children || [];

  const currentSubPath = "/dashboard/notes/journal";
  const currentSubLabel =
    subEntries.find((e) => e.path === currentSubPath)?.label || "记录本";

  const handleBack = () => {
    navigate("/dashboard"); // 按你的实际 Dashboard 路由改
  };

  // 选择顶层模块：跳到该模块默认子页面（第一个子模块）
  const handleTopSelect = (mod) => {
    setTopMenuOpen(false);
    const children = mod.children || [];
    if (!children.length) return;
    const first = children[0];
    if (first.path) navigate(first.path);
  };

  // 选择当前顶层模块下的子模块
  const handleSubSelect = (entry) => {
    setSubMenuOpen(false);
    if (!entry.path || entry.path === currentSubPath) return;
    navigate(entry.path);
  };

  return (
    <div className="page-main">
      {/* 顶部两级导航，与 TasksAll 保持一致布局 */}
      <div
        className="page-breadcrumb"
        style={{
          display: "flex",
          alignItems: "center",
          gap: 8,
          position: "relative",
          zIndex: 10,
        }}
      >
        {/* 返回 Dashboard 的箭头 */}
        <BackIconButton to="/dashboard" />

        {/* 顶层模块下拉：实验记录本 / 项目管理 / 文件收集 ... */}
        <div style={{ position: "relative" }}>
          <button
            type="button"
            onClick={() => setTopMenuOpen((v) => !v)}
            style={{
              border: "none",
              background: "transparent",
              cursor: "pointer",
              display: "inline-flex",
              alignItems: "center",
              gap: 4,
              color: "#2563eb",
              fontSize: 14,
              fontWeight: 500,
            }}
          >
            <span>{currentTopModule?.label || "实验记录本"}</span>
            <span style={{ fontSize: 10 }}>{topMenuOpen ? "▲" : "▼"}</span>
          </button>

          {topMenuOpen && (
            <div
              style={{
                position: "absolute",
                top: "140%",
                left: 0,
                background: "#ffffff",
                borderRadius: 12,
                boxShadow: "0 10px 40px rgba(15, 23, 42, 0.15)",
                padding: "6px 0",
                minWidth: 160,
                zIndex: 30,
              }}
            >
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
                      padding: "6px 12px",
                      display: "flex",
                      alignItems: "center",
                      gap: 8,
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

        {/* 分隔符 */}
        <span style={{ color: "#9ca3af" }}>/</span>

        {/* 当前顶层模块的子模块下拉：记录本 / 模板 / 数据合集 / 任务总览 ... */}
        <div style={{ position: "relative" }}>
          <button
            type="button"
            onClick={() => setSubMenuOpen((v) => !v)}
            style={{
              border: "none",
              background: "transparent",
              cursor: "pointer",
              display: "inline-flex",
              alignItems: "center",
              gap: 4,
              color: "#111827",
              fontSize: 14,
            }}
          >
            <span>{currentSubLabel}</span>
            <span style={{ fontSize: 10, color: "#9ca3af" }}>
              {subMenuOpen ? "▲" : "▼"}
            </span>
          </button>

          {subMenuOpen && (
            <div
              style={{
                position: "absolute",
                top: "140%",
                left: 0,
                background: "#ffffff",
                borderRadius: 12,
                boxShadow: "0 10px 40px rgba(15, 23, 42, 0.15)",
                padding: "6px 0",
                minWidth: 160,
                zIndex: 30,
              }}
            >
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
                      padding: "6px 12px",
                      display: "flex",
                      alignItems: "center",
                      gap: 8,
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
      </div>

      {/* 下面是原来的“记录本”主体内容，排版用已有 CSS 控制 */}
      <div className="page-content">
        {/* 顶部磁盘使用 + 标签区域 */}
        <section className="card journal-header-card">
          {/* 磁盘使用情况 */}
          <div className="journal-storage-row">
            <div className="journal-storage-label">磁盘使用情况</div>
            <div className="journal-storage-text">08 / 100GB</div>
          </div>
          <div className="journal-storage-bar">
            <div className="journal-storage-bar-inner" />
          </div>

          {/* 二级导航：我的实验记录本 / 公共记录本 */}
          <div className="journal-tabs-row">
            <div className="journal-tabs-left">
              <button className="journal-tab journal-tab-active">
                我的实验记录本
              </button>
              <button className="journal-tab">公共记录本</button>
            </div>
            <button className="btn btn-primary journal-new-btn">
              + 新建
            </button>
          </div>
        </section>

        {/* 主内容：左我的记录本，右公共记录本说明 */}
        <section className="journal-main-grid">
          {/* 左侧：我的实验记录本（复用 Notes 组件） */}
          <div className="card journal-my-notes-card">
            <Notes />
          </div>

          {/* 右侧：公共记录本列表（静态） */}
          <aside className="card journal-public-card">
            <h3 className="journal-public-title">公共记录本</h3>

            <div className="journal-public-item journal-public-item-global">
              <div className="journal-public-name">全局共享</div>
              <div className="journal-public-desc">
                此记录本对所有用户均可查看
              </div>
              <div className="journal-public-meta">
                创建：2025-03-28 17:40:39
              </div>
            </div>

            <div className="journal-public-empty">
              <div className="journal-public-empty-icon">📓</div>
              <div className="journal-public-empty-text">
                暂无更多公共记录本
              </div>
            </div>
          </aside>
        </section>
      </div>
    </div>
  );
}
