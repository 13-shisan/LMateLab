import React, { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import api from "../../api/client";
import ServerMonitorLayout from "./ServerMonitorLayout";

function formatPercentFromRatio(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "--";
  return `${(Number(value) * 100).toFixed(1)}%`;
}

function formatDateTime(text) {
  if (!text) return "--";
  const d = new Date(text);
  if (Number.isNaN(d.getTime())) return text;
  return d.toLocaleString("zh-CN", { hour12: false });
}

function StatusBadge({ hasData }) {
  return (
    <span
      style={{
        display: "inline-flex",
        alignItems: "center",
        padding: "4px 10px",
        borderRadius: 999,
        fontSize: 12,
        fontWeight: 600,
        background: hasData ? "#dcfce7" : "#f3f4f6",
        color: hasData ? "#166534" : "#6b7280",
      }}
    >
      {hasData ? "已接入数据" : "待接入"}
    </span>
  );
}

export default function ServerMonitorEntry() {
  const navigate = useNavigate();

  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [servers, setServers] = useState([]);

  useEffect(() => {
    let ignore = false;

    async function fetchServers() {
      try {
        setLoading(true);
        setError("");

        const res = await api.get("/server-monitor/servers");
        if (!ignore) {
          setServers(res?.data?.servers || []);
        }
      } catch (e) {
        console.error(e);
        if (!ignore) {
          setError(e?.response?.data?.detail || "获取服务器入口信息失败");
        }
      } finally {
        if (!ignore) {
          setLoading(false);
        }
      }
    }

    fetchServers();

    return () => {
      ignore = true;
    };
  }, []);

  const hasAnyData = useMemo(() => servers.some((s) => s.has_data), [servers]);

  return (
    <ServerMonitorLayout
      currentPath="/dashboard/server-monitor"
      currentServerKey="entry"
    >
      <div style={{ marginBottom: 24 }}>
        <div style={{ fontSize: 24, fontWeight: 700, color: "#111827" }}>
          服务器入口
        </div>
        <div style={{ marginTop: 8, color: "#6b7280", fontSize: 14 }}>
          请选择要查看的服务器监控页面。卡片展示空闲节点、节点使用率，以及 GPU 服务器的空闲/忙碌 GPU 情况，方便先做全局判断再进入详情。
        </div>
      </div>

      {loading ? (
        <div
          style={{
            background: "#fff",
            borderRadius: 16,
            padding: 32,
            border: "1px solid #e5e7eb",
            color: "#6b7280",
          }}
        >
          正在加载服务器入口信息...
        </div>
      ) : error ? (
        <div
          style={{
            background: "#fff",
            borderRadius: 16,
            padding: 24,
            border: "1px solid #fecaca",
            color: "#b91c1c",
          }}
        >
          {error}
        </div>
      ) : (
        <>
          {!hasAnyData && (
            <div
              style={{
                marginBottom: 16,
                background: "#fff",
                borderRadius: 16,
                padding: 20,
                border: "1px solid #e5e7eb",
                color: "#6b7280",
              }}
            >
              当前还没有服务器接入监控数据。
            </div>
          )}

          <div
            style={{
              display: "grid",
              gridTemplateColumns: "repeat(auto-fill, minmax(260px, 1fr))",
              gap: 20,
            }}
          >
            <div
              onClick={() => navigate("/dashboard/server-monitor/users-overview")}
              style={{
                border: "1px solid #dbeafe",
                borderRadius: 18,
                background: "linear-gradient(135deg, #eff6ff 0%, #ffffff 100%)",
                padding: 20,
                cursor: "pointer",
                boxShadow: "0 8px 24px rgba(37, 99, 235, 0.08)",
                transition: "all 0.2s ease",
              }}
            >
              <div style={{ fontSize: 28, marginBottom: 12 }}>👥</div>

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
                  用户使用总览
                </div>
                <span
                  style={{
                    display: "inline-flex",
                    alignItems: "center",
                    padding: "4px 10px",
                    borderRadius: 999,
                    fontSize: 12,
                    fontWeight: 600,
                    background: "#dbeafe",
                    color: "#1d4ed8",
                  }}
                >
                  全局视图
                </span>
              </div>

              <div style={{ fontSize: 13, color: "#6b7280", marginBottom: 14, lineHeight: 1.7 }}>
                查看所有用户当前分别在哪些服务器上运行或排队，以及历史时间范围内的跨服务器使用分布。
              </div>

              <div
                style={{
                  display: "grid",
                  gridTemplateColumns: "repeat(2, minmax(0, 1fr))",
                  gap: 10,
                  marginBottom: 14,
                }}
              >
                <div style={miniStatStyle}>
                  <div style={miniLabelStyle}>实时维度</div>
                  <div style={miniValueStyle}>当前分布</div>
                </div>

                <div style={miniStatStyle}>
                  <div style={miniLabelStyle}>历史维度</div>
                  <div style={miniValueStyle}>长期统计</div>
                </div>
              </div>

              <div style={{ fontSize: 12, color: "#9ca3af" }}>
                进入后可查看概览卡片、进度条、用户分布矩阵与历史统计。
              </div>
            </div>

            {servers.map((server) => {
              const queueText =
                server.queues && server.queues.length > 0
                  ? server.queues.join(" / ")
                  : "暂无队列信息";

              return (
                <div
                  key={server.name}
                  onClick={() => navigate(`/dashboard/server-monitor/${server.name}`)}
                  style={{
                    border: "1px solid #e5e7eb",
                    borderRadius: 18,
                    background: "#fff",
                    padding: 20,
                    cursor: "pointer",
                    boxShadow: "0 8px 24px rgba(15, 23, 42, 0.06)",
                    transition: "all 0.2s ease",
                  }}
                >
                  <div style={{ fontSize: 28, marginBottom: 12 }}>🖥️</div>

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
                      {server.display_name || server.name}
                    </div>
                    <StatusBadge hasData={server.has_data} />
                  </div>

                  <div style={{ fontSize: 13, color: "#6b7280", marginBottom: 14 }}>
                    主机：{server.host || "--"} · 调度器：{server.scheduler_type || "--"}
                  </div>

                  <div
                    style={{
                      display: "grid",
                      gridTemplateColumns: "repeat(2, minmax(0, 1fr))",
                      gap: 10,
                      marginBottom: 14,
                    }}
                  >
                    <div style={miniStatStyle}>
                      <div style={miniLabelStyle}>空闲节点</div>
                      <div style={miniValueStyle}>
                        {server.has_data ? `${server.node_free ?? 0} / ${server.node_total ?? 0}` : "--"}
                      </div>
                    </div>

                    <div style={miniStatStyle}>
                      <div style={miniLabelStyle}>使用率</div>
                      <div style={miniValueStyle}>
                        {server.has_data ? formatPercentFromRatio(server.usage_ratio) : "--"}
                      </div>
                    </div>

                    {server.gpu_available ? (
                      <>
                        <div style={miniStatStyle}>
                          <div style={miniLabelStyle}>空闲 GPU</div>
                          <div style={miniValueStyle}>
                            {server.has_data ? `${server.gpu_idle ?? 0} / ${server.gpu_total ?? 0}` : "--"}
                          </div>
                        </div>

                        <div style={miniStatStyle}>
                          <div style={miniLabelStyle}>忙碌 GPU</div>
                          <div style={miniValueStyle}>
                            {server.has_data ? `${server.gpu_busy ?? 0}` : "--"}
                          </div>
                        </div>
                      </>
                    ) : null}
                  </div>

                  <div style={{ marginBottom: 10 }}>
                    <div style={{ fontSize: 12, fontWeight: 600, color: "#6b7280", marginBottom: 6 }}>
                      队列
                    </div>
                    <div
                      style={{
                        fontSize: 13,
                        color: "#111827",
                        lineHeight: 1.6,
                        minHeight: 42,
                      }}
                    >
                      {queueText}
                    </div>
                  </div>

                  {server.gpu_available ? (
                    <div style={{ marginBottom: 10 }}>
                      <div style={{ fontSize: 12, fontWeight: 600, color: "#6b7280", marginBottom: 6 }}>
                        GPU 摘要
                      </div>
                      <div
                        style={{
                          fontSize: 13,
                          color: "#111827",
                          lineHeight: 1.6,
                        }}
                      >
                        总数 {server.gpu_total ?? 0} / 空闲 {server.gpu_idle ?? 0} / 忙碌 {server.gpu_busy ?? 0}
                      </div>
                    </div>
                  ) : null}

                  <div style={{ marginTop: 12, fontSize: 12, color: "#9ca3af" }}>
                    更新时间：{formatDateTime(server.updated_at)}
                  </div>
                </div>
              );
            })}
          </div>
        </>
      )}
    </ServerMonitorLayout>
  );
}

const miniStatStyle = {
  border: "1px solid #e5e7eb",
  borderRadius: 12,
  padding: "10px 12px",
  background: "#f8fafc",
};

const miniLabelStyle = {
  fontSize: 12,
  color: "#6b7280",
  marginBottom: 4,
};

const miniValueStyle = {
  fontSize: 16,
  fontWeight: 700,
  color: "#111827",
};
