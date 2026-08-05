// frontend/src/pages/agents/AgentEntry.jsx
import React from "react";
import { useNavigate } from "react-router-dom";
import { Bot, Compass, Sparkles } from "lucide-react";
import AgentLayout from "./AgentLayout";

const agents = [
  {
    key: "general-chat",
    name: "通用大模型",
    description:
      "适合进行开放式问答、内容润色、思路整理、总结归纳和一般性科研交流，不局限于平台导览。",
    path: "/dashboard/agents/general-chat",
    status: "可用",
    icon: Bot,
    accent: "linear-gradient(135deg, #ede9fe 0%, #f5f3ff 100%)",
  },
  {
    key: "platform-guide",
    name: "平台导览智能体",
    description:
      "帮助你快速了解平台有哪些功能、每个需求应该从哪里进入，以及常见页面如何找到。",
    path: "/dashboard/agents/platform-guide",
    status: "可用",
    icon: Compass,
    accent: "linear-gradient(135deg, #dbeafe 0%, #eff6ff 100%)",
  },
];


export default function AgentEntry() {
  const navigate = useNavigate();

  return (
    <AgentLayout currentPath="/dashboard/agents" currentAgentKey="entry">
      <div style={{ marginBottom: 24 }}>
        <div style={{ fontSize: 26, fontWeight: 800, color: "#111827" }}>
          智能体入口
        </div>
        <div style={{ marginTop: 8, color: "#6b7280", fontSize: 14, lineHeight: 1.8 }}>
          这里汇总平台中的各类智能体。你可以先选择一个适合当前任务的助手进入使用。
          目前已开放通用大模型与平台导览智能体：前者适合开放式问答，后者适合快速定位平台功能入口。
        </div>
      </div>

      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fill, minmax(280px, 1fr))",
          gap: 20,
        }}
      >
        {agents.map((agent) => {
          const Icon = agent.icon || Bot;

          return (
            <button
              key={agent.key}
              type="button"
              onClick={() => navigate(agent.path)}
              style={{
                border: "1px solid #e5e7eb",
                borderRadius: 20,
                background: "#fff",
                padding: 20,
                textAlign: "left",
                cursor: "pointer",
                boxShadow: "0 10px 30px rgba(15, 23, 42, 0.06)",
                transition: "all 0.2s ease",
              }}
            >
              <div
                style={{
                  width: 52,
                  height: 52,
                  borderRadius: 16,
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  background: agent.accent,
                  color: "#1d4ed8",
                  marginBottom: 16,
                }}
              >
                <Icon size={24} />
              </div>

              <div
                style={{
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "space-between",
                  gap: 12,
                  marginBottom: 8,
                }}
              >
                <div style={{ fontSize: 18, fontWeight: 700, color: "#111827" }}>
                  {agent.name}
                </div>

                <span
                  style={{
                    display: "inline-flex",
                    alignItems: "center",
                    gap: 6,
                    padding: "4px 10px",
                    borderRadius: 999,
                    fontSize: 12,
                    fontWeight: 600,
                    background: "#dcfce7",
                    color: "#166534",
                  }}
                >
                  <Sparkles size={12} />
                  {agent.status}
                </span>
              </div>

              <div style={{ fontSize: 14, color: "#6b7280", lineHeight: 1.8 }}>
                {agent.description}
              </div>

              <div style={{ marginTop: 16, fontSize: 13, color: "#2563eb", fontWeight: 700 }}>
                点击进入 →
              </div>
            </button>
          );
        })}
      </div>
    </AgentLayout>
  );
}
