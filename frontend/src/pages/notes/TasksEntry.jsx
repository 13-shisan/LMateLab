// src/pages/notes/TasksEntry.jsx
import React, { useState } from "react";
import { useNavigate } from "react-router-dom";
import { modules } from "../../config/modules";

const VASP_EXTERNAL_URL = "https://matflow.top:6443/";

export default function TasksEntry() {
  const navigate = useNavigate();

  const [topMenuOpen, setTopMenuOpen] = useState(false);
  const [subMenuOpen, setSubMenuOpen] = useState(false);

  // 当前顶层模块（本页是“实验记录本”）
  const currentTopKey = "notes";
  const currentTopModule = modules.find((m) => m.key === currentTopKey);
  const topEntries = modules;
  const subEntries = currentTopModule?.children || [];

  const currentSubPath = "/dashboard/notes/tasksentry";
  const currentSubLabel =
    subEntries.find((e) => e.path === currentSubPath)?.label || "任务总览";

  const handleBack = () => {
    navigate("/dashboard");
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

  // 8 个卡片配置：点击行为 + 右侧展示的信息
  const taskCards = [
    {
      key: "vasp-external",
      title: "外部 VASP 统计系统",
      subtitle: "matflow.top",
      type: "external",
      stats: {
        desc: "打开 matflow.top 中的 VASP 任务统计系统。",
        extra: "适合查看集群层面的整体 VASP 运行情况。",
      },
    },
    {
      key: "all",
      title: "全部任务总览",
      subtitle: "All Tasks",
      type: "route",
      path: "/dashboard/notes/tasksall",
      stats: {
        desc: "查看所有软件类型任务的总体情况。",
        extra: "可用于快速了解当前整体任务压力。",
      },
    },
    {
      key: "vasp",
      title: "VASP 任务",
      subtitle: "VASP",
      type: "route",
      path: "/dashboard/notes/tasksvasp",
      stats: {
        desc: "VASP 相关计算任务的统计与管理。",
        extra: "后续可展示：排队/运行/完成的 VASP 任务数量。",
      },
    },
    {
      key: "qe",
      title: "Quantum ESPRESSO 任务",
      subtitle: "QE",
      type: "route",
      path: "/dashboard/notes/tasksqe",
      stats: {
        desc: "QE 任务的提交记录与运行状态。",
        extra: "后续可展示：近 7 天 QE 任务提交趋势等。",
      },
    },
    {
      key: "gaussian",
      title: "Gaussian 任务",
      subtitle: "Gaussian",
      type: "route",
      path: "/dashboard/notes/tasksgaussian",
      stats: {
        desc: "Gaussian 量子化学计算任务。",
        extra: "适合查看体系优化/频率计算等任务概况。",
      },
    },
    {
      key: "deepmd",
      title: "DeepMD 任务",
      subtitle: "DeepMD",
      type: "route",
      path: "/dashboard/notes/tasksdeepmd",
      stats: {
        desc: "基于 DeepMD 的势能面训练与模拟任务。",
        extra: "后续可展示：训练轮次、数据集规模等信息。",
      },
    },
    {
      key: "lasp",
      title: "LASP 任务",
      subtitle: "LASP",
      type: "route",
      path: "/dashboard/notes/taskslasp",
      stats: {
        desc: "LASP 结构搜索与计算任务。",
        extra: "适合查看当前活跃的结构搜索项目。",
      },
    },
    {
      key: "cp2k",
      title: "CP2K 任务",
      subtitle: "CP2K",
      type: "route",
      path: "/dashboard/notes/taskscp2k",
      stats: {
        desc: "CP2K 分子动力学与量子化学任务。",
        extra: "后续可展示：不同体系/功能的任务统计。",
      },
    },
  ];

  return (
    <div className="dashboard-shell">
      <main className="portal-main">
        {/* 面包屑 */}
        <div
          className="page-breadcrumb"
          style={{
            display: "flex",
            alignItems: "center",
            gap: 8,
            position: "relative",
            zIndex: 10,
            marginBottom: 12,
          }}
        >
          <button
            type="button"
            onClick={handleBack}
            style={{
              border: "none",
              background: "transparent",
              cursor: "pointer",
              display: "flex",
              alignItems: "center",
              padding: 0,
              color: "#2563eb",
            }}
          >
            <span
              style={{
                display: "inline-flex",
                alignItems: "center",
                justifyContent: "center",
                width: 20,
                height: 20,
                borderRadius: "999px",
                background: "#e5edff",
                marginRight: 2,
              }}
            >
              <span style={{ fontSize: 12 }}>←</span>
            </span>
          </button>

          {/* 顶层模块切换 */}
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

          <span style={{ color: "#9ca3af" }}>/</span>

          {/* notes 子模块选择 */}
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

        {/* 主内容：8 个竖排卡片（每个卡片里左标题 + 右侧基本信息） */}
        <section
          className="card"
          style={{
            flex: 1,
            minHeight: 360,
            padding: 24,
            display: "flex",
            flexDirection: "column",
            gap: 12,
          }}
        >
          {taskCards.map((card) => {
            // 为每张卡片构造 href 和额外属性
            let href = "#";
            let extraProps = {};

            if (card.type === "route") {
              href = card.path;
            } else if (card.type === "external") {
              href = VASP_EXTERNAL_URL;
              extraProps = {
                target: "_blank",
                rel: "noreferrer",
              };
            }

            return (
              <a
                key={card.key}
                href={href}
                {...extraProps}
                style={{ textDecoration: "none" }}
              >
                <div
                  style={{
                    width: "100%",
                    borderRadius: 16,
                    border: "1px solid #e5e7eb",
                    padding: "12px 16px",
                    background: "#ffffff",
                    cursor: "pointer",
                    boxShadow: "0 4px 10px rgba(15, 23, 42, 0.04)",
                    textAlign: "left",
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "space-between",
                    gap: 16,
                  }}
                >
                  {/* 左侧：名称 + 小标签 */}
                  <div
                    style={{
                      display: "flex",
                      flexDirection: "column",
                      gap: 4,
                      minWidth: 180,
                    }}
                  >
                    <div
                      style={{
                        fontSize: 15,
                        fontWeight: 600,
                        color: "#111827",
                      }}
                    >
                      {card.title}
                      {card.type === "external" && (
                        <span
                          style={{
                            marginLeft: 6,
                            fontSize: 11,
                            color: "#6b7280",
                          }}
                        >
                          (外链)
                        </span>
                      )}
                    </div>
                    <div
                      style={{
                        fontSize: 12,
                        color: "#6b7280",
                      }}
                    >
                      {card.subtitle}
                    </div>
                  </div>

                  {/* 右侧：简单的基本信息/说明 */}
                  <div
                    style={{
                      flex: 1,
                      display: "flex",
                      flexDirection: "column",
                      alignItems: "flex-start",
                      gap: 4,
                      fontSize: 12,
                      color: "#4b5563",
                    }}
                  >
                    <span>{card.stats.desc}</span>
                    <span
                      style={{
                        color: "#9ca3af",
                        fontSize: 11,
                      }}
                    >
                      {card.stats.extra}
                    </span>
                  </div>
                </div>
              </a>
            );
          })}
        </section>
      </main>
    </div>
  );
}
