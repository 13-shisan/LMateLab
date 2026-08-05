import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  Users,
  Server,
  Activity,
  BarChart3,
  Clock3,
  Layers3,
} from "lucide-react";
import api from "../../api/client";
import ServerMonitorLayout from "./ServerMonitorLayout";

function formatDateTime(text) {
  if (!text) return "--";
  const d = new Date(text);
  if (Number.isNaN(d.getTime())) return text;
  return d.toLocaleString("zh-CN", { hour12: false });
}

function formatRatio(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "--";
  return `${(Number(value) * 100).toFixed(1)}%`;
}

function OverviewCard({ icon: Icon, title, value, subtext }) {
  return (
    <div
      style={{
        background: "#fff",
        border: "1px solid #e5e7eb",
        borderRadius: 16,
        padding: 18,
        boxShadow: "0 4px 14px rgba(15, 23, 42, 0.04)",
      }}
    >
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          marginBottom: 10,
        }}
      >
        <div style={{ color: "#6b7280", fontSize: 14, fontWeight: 600 }}>{title}</div>
        <div
          style={{
            width: 36,
            height: 36,
            borderRadius: 10,
            background: "#f3f4f6",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            color: "#111827",
          }}
        >
          <Icon size={18} />
        </div>
      </div>

      <div style={{ fontSize: 28, fontWeight: 700, color: "#111827", lineHeight: 1.2 }}>
        {value}
      </div>

      <div style={{ marginTop: 6, color: "#6b7280", fontSize: 13 }}>
        {subtext || " "}
      </div>
    </div>
  );
}

function BlockTitle({ title, subtitle }) {
  return (
    <div style={{ marginBottom: 16 }}>
      <div style={{ fontSize: 22, fontWeight: 800, color: "#111827" }}>{title}</div>
      {subtitle ? (
        <div style={{ marginTop: 6, fontSize: 14, color: "#6b7280" }}>{subtitle}</div>
      ) : null}
    </div>
  );
}

function SectionCard({ title, subtitle, children, right }) {
  return (
    <section
      style={{
        background: "#fff",
        borderRadius: 16,
        border: "1px solid #e5e7eb",
        overflow: "hidden",
        marginBottom: 24,
      }}
    >
      <div
        style={{
          padding: "18px 20px",
          borderBottom: "1px solid #e5e7eb",
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          gap: 12,
          flexWrap: "wrap",
        }}
      >
        <div>
          <div style={{ fontSize: 18, fontWeight: 700, color: "#111827" }}>{title}</div>
          {subtitle ? (
            <div style={{ marginTop: 4, fontSize: 13, color: "#6b7280" }}>{subtitle}</div>
          ) : null}
        </div>
        {right || null}
      </div>

      <div>{children}</div>
    </section>
  );
}

function UserServerProgress({ user, maxServerCount }) {
  const count = user?.server_count || 0;
  const total = maxServerCount || 1;
  const percent = Math.max(0, Math.min(100, (count / total) * 100));

  return (
    <div>
      <div
        style={{
          height: 8,
          background: "#e5e7eb",
          borderRadius: 999,
          overflow: "hidden",
          marginBottom: 6,
        }}
      >
        <div
          style={{
            width: `${percent}%`,
            height: "100%",
            background: "#2563eb",
            borderRadius: 999,
          }}
        />
      </div>
      <div style={{ fontSize: 12, color: "#6b7280" }}>
        覆盖 {count} / {total} 台服务器
      </div>
    </div>
  );
}

function ServerPill({ text, onClick, clickable = false }) {
  return (
    <button
      type="button"
      onClick={onClick}
      style={{
        display: "inline-flex",
        alignItems: "center",
        padding: "2px 10px",
        borderRadius: 999,
        fontSize: 12,
        fontWeight: 600,
        background: clickable ? "#dbeafe" : "#eff6ff",
        color: "#1d4ed8",
        whiteSpace: "nowrap",
        border: clickable ? "1px solid #93c5fd" : "1px solid transparent",
        cursor: clickable ? "pointer" : "default",
      }}
      title={clickable ? "点击跳转到对应服务器详情页" : undefined}
    >
      {text}
    </button>
  );
}


export default function ServerMonitorUsersOverview() {
  const navigate = useNavigate();

  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [range, setRange] = useState("30d");
  const [data, setData] = useState(null);
  const [selectedUser, setSelectedUser] = useState("ALL");

  const fetchData = async (rangeValue = range) => {
    setLoading(true);
    setError("");

    try {
      const res = await api.get(`/server-monitor/users-overview?range=${rangeValue}`);
      setData(res.data);
    } catch (e) {
      console.error(e);
      setError(e?.response?.data?.detail || e?.response?.data?.error || "获取用户使用总览失败");
      setData(null);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchData(range);
  }, [range]);

  const realtimeOverview = data?.realtime?.overview || {};
  const realtimeUsers = data?.realtime?.users || [];
  const realtimeServers = data?.realtime?.servers || [];

  const historyOverview = data?.history?.overview || {};
  const historyUsers = data?.history?.users || [];

  const userOptions = useMemo(() => {
    const names = new Set();
    realtimeUsers.forEach((item) => names.add(item.user));
    historyUsers.forEach((item) => names.add(item.user));
    return ["ALL", ...Array.from(names).sort((a, b) => a.localeCompare(b, "zh-CN"))];
  }, [realtimeUsers, historyUsers]);

  const filteredRealtimeUsers = useMemo(() => {
    if (selectedUser === "ALL") return realtimeUsers;
    return realtimeUsers.filter((item) => item.user === selectedUser);
  }, [realtimeUsers, selectedUser]);

  const filteredHistoryUsers = useMemo(() => {
    if (selectedUser === "ALL") return historyUsers;
    return historyUsers.filter((item) => item.user === selectedUser);
  }, [historyUsers, selectedUser]);

  const maxRealtimeServerCount = useMemo(() => {
    if (!filteredRealtimeUsers.length) return 1;
    return Math.max(...filteredRealtimeUsers.map((item) => item.server_count || 0), 1);
  }, [filteredRealtimeUsers]);

  const maxHistoryServerCount = useMemo(() => {
    if (!filteredHistoryUsers.length) return 1;
    return Math.max(...filteredHistoryUsers.map((item) => item.server_count || 0), 1);
  }, [filteredHistoryUsers]);

  return (
    <ServerMonitorLayout
      currentPath="/dashboard/server-monitor/users-overview"
      currentServerKey="users-overview"
    >
      <section
        style={{
          background: "linear-gradient(135deg, #0f172a 0%, #1e293b 100%)",
          color: "#fff",
          borderRadius: 20,
          padding: "28px 30px",
          marginBottom: 24,
          boxShadow: "0 10px 30px rgba(15, 23, 42, 0.18)",
        }}
      >
        <div
          style={{
            display: "flex",
            gap: 16,
            alignItems: "flex-start",
            justifyContent: "space-between",
            flexWrap: "wrap",
          }}
        >
          <div>
            <div style={{ fontSize: 13, letterSpacing: 1.2, opacity: 0.8, marginBottom: 10 }}>
              USERS OVERVIEW
            </div>
            <h1 style={{ margin: 0, fontSize: 32, lineHeight: 1.2 }}>
              用户跨服务器使用总览
            </h1>
            <p style={{ margin: "10px 0 0", color: "rgba(255,255,255,0.82)", fontSize: 15 }}>
              从实时快照和历史数据两个维度，观察所有用户分别在哪些服务器上使用资源，以及跨服务器的分布情况。
            </p>
          </div>

          <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
            {[
              { key: "7d", label: "近7天" },
              { key: "30d", label: "近1个月" },
              { key: "90d", label: "近3个月" },
              { key: "365d", label: "近1年" },
            ].map((item) => (
              <button
                key={item.key}
                type="button"
                onClick={() => setRange(item.key)}
                style={{
                  border: range === item.key ? "1px solid #60a5fa" : "1px solid rgba(255,255,255,0.18)",
                  background: range === item.key ? "#eff6ff" : "rgba(255,255,255,0.08)",
                  color: range === item.key ? "#1d4ed8" : "#fff",
                  borderRadius: 10,
                  padding: "8px 14px",
                  fontSize: 13,
                  fontWeight: 600,
                  cursor: "pointer",
                }}
              >
                {item.label}
              </button>
            ))}
          </div>
        </div>
      </section>

      {loading ? (
        <div
          style={{
            background: "#fff",
            borderRadius: 16,
            padding: 40,
            textAlign: "center",
            color: "#6b7280",
            border: "1px solid #e5e7eb",
          }}
        >
          正在加载用户跨服务器使用总览...
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
      ) : !data ? (
        <div
          style={{
            background: "#fff",
            borderRadius: 16,
            padding: 24,
            border: "1px solid #e5e7eb",
            color: "#6b7280",
          }}
        >
          当前暂无用户跨服务器使用数据。
        </div>
      ) : (
        <>
          <section style={{ marginBottom: 32 }}>
            <BlockTitle
              title="实时信息"
              subtitle="基于各服务器最新 status.json 快照，展示当前用户正在在哪些服务器运行或排队。"
            />

            <div
              style={{
                display: "grid",
                gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))",
                gap: 16,
                marginBottom: 20,
              }}
            >
              <OverviewCard
                icon={Users}
                title="当前活跃用户数"
                value={realtimeOverview.active_user_count ?? "--"}
                subtext="当前至少在一台服务器上有运行中或排队作业的用户数"
              />
              <OverviewCard
                icon={Server}
                title="当前活跃服务器数"
                value={realtimeOverview.active_server_count ?? "--"}
                subtext="当前至少有用户活跃的服务器数量"
              />
              <OverviewCard
                icon={Activity}
                title="当前运行任务数"
                value={realtimeOverview.total_running_jobs ?? "--"}
                subtext="所有服务器实时运行中的任务总数"
              />
              <OverviewCard
                icon={Clock3}
                title="当前排队任务数"
                value={realtimeOverview.total_queued_jobs ?? "--"}
                subtext="所有服务器实时排队中的任务总数"
              />
            </div>

            <SectionCard
              title="服务器实时活跃用户分布"
              subtitle="更适合用条形进度来快速判断哪台服务器当前用户最集中。"
            >
              <div style={{ padding: 20, display: "grid", gap: 14 }}>
                {realtimeServers.length === 0 ? (
                  <div style={{ color: "#6b7280", fontSize: 14 }}>暂无实时服务器分布数据</div>
                ) : (
                  realtimeServers.map((item) => {
                    const maxValue = Math.max(...realtimeServers.map((x) => x.total_user_count || 0), 1);
                    const percent = ((item.total_user_count || 0) / maxValue) * 100;

                    return (
                      <div key={item.server_name}>
                        <div
                          style={{
                            display: "flex",
                            justifyContent: "space-between",
                            alignItems: "center",
                            gap: 12,
                            marginBottom: 6,
                            flexWrap: "wrap",
                          }}
                        >
                          <div style={{ fontSize: 14, fontWeight: 700, color: "#111827" }}>
                            {item.display_name}
                          </div>
                          <div style={{ fontSize: 12, color: "#6b7280" }}>
                            总用户 {item.total_user_count ?? 0} / 运行 {item.running_user_count ?? 0} / 排队 {item.queued_user_count ?? 0}
                          </div>
                        </div>

                        <div
                          style={{
                            height: 10,
                            background: "#e5e7eb",
                            borderRadius: 999,
                            overflow: "hidden",
                          }}
                        >
                          <div
                            style={{
                              width: `${percent}%`,
                              height: "100%",
                              background: "linear-gradient(90deg, #60a5fa 0%, #2563eb 100%)",
                              borderRadius: 999,
                            }}
                          />
                        </div>
                      </div>
                    );
                  })
                )}
              </div>
            </SectionCard>

            <SectionCard
              title="当前活跃用户分布"
              subtitle="展示每个用户当前活跃在哪些服务器上，适合用覆盖进度条 + 服务器标签来直观看分布。"
              right={
                <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
                  <span style={{ fontSize: 13, color: "#6b7280" }}>筛选用户</span>
                  <select
                    value={selectedUser}
                    onChange={(e) => setSelectedUser(e.target.value)}
                    style={{
                      border: "1px solid #d1d5db",
                      borderRadius: 10,
                      padding: "8px 12px",
                      fontSize: 13,
                      color: "#111827",
                      background: "#fff",
                      minWidth: 180,
                    }}
                  >
                    {userOptions.map((name) => (
                      <option key={name} value={name}>
                        {name === "ALL" ? "全部用户" : name}
                      </option>
                    ))}
                  </select>
                </div>
              }
            >
              <div style={{ padding: 20 }}>
                {filteredRealtimeUsers.length === 0 ? (
                  <div style={{ color: "#6b7280", fontSize: 14 }}>暂无符合筛选条件的实时用户数据</div>
                ) : (
                  <div style={{ display: "grid", gap: 20 }}>
                    {filteredRealtimeUsers.map((item) => (
                      <div
                        key={item.user}
                        style={{
                          border: "1px solid #e5e7eb",
                          borderRadius: 14,
                          padding: 16,
                          background: "#fcfcfd",
                        }}
                      >
                        <div
                          style={{
                            display: "flex",
                            justifyContent: "space-between",
                            alignItems: "center",
                            gap: 12,
                            flexWrap: "wrap",
                            marginBottom: 12,
                          }}
                        >
                          <div>
                            <div style={{ fontSize: 16, fontWeight: 700, color: "#111827" }}>
                              {item.user}
                            </div>
                            <div style={{ marginTop: 4, fontSize: 13, color: "#6b7280" }}>
                              运行 {item.running_jobs ?? 0} / 排队 {item.queued_jobs ?? 0} / 总任务 {item.total_jobs ?? 0}
                            </div>
                          </div>
                          <div style={{ fontSize: 12, color: "#6b7280" }}>
                            最近观察：{formatDateTime(item.last_seen_at)}
                          </div>
                        </div>

                        <div style={{ marginBottom: 12 }}>
                          <UserServerProgress user={item} maxServerCount={maxRealtimeServerCount} />
                        </div>

                        <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
                          {(item.servers || []).map((server) => (
                            <ServerPill
                              key={`${item.user}-${server.server_name}`}
                              text={`${server.display_name}（${server.total_jobs}）`}
                              clickable
                              onClick={() => navigate(`/dashboard/server-monitor/${server.server_name}`)}
                            />
                          ))}
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </SectionCard>

            <SectionCard
              title="实时用户 × 服务器矩阵"
              subtitle="矩阵方式适合快速回答：某个用户当前到底在哪几台服务器上有作业。"
            >
              <div style={{ overflowX: "auto" }}>
                <table style={{ width: "100%", borderCollapse: "collapse", minWidth: 960 }}>
                  <thead>
                    <tr style={{ background: "#f8fafc", textAlign: "left" }}>
                      <th style={thStyle}>用户</th>
                      <th style={thStyle}>服务器数</th>
                      <th style={thStyle}>服务器列表</th>
                      <th style={thStyle}>运行任务</th>
                      <th style={thStyle}>排队任务</th>
                      <th style={thStyle}>总任务</th>
                      <th style={thStyle}>最近观察时间</th>
                    </tr>
                  </thead>
                  <tbody>
                    {filteredRealtimeUsers.length === 0 ? (
                      <tr>
                        <td colSpan={7} style={emptyTdStyle}>暂无符合筛选条件的实时用户矩阵数据</td>
                      </tr>
                    ) : (
                      filteredRealtimeUsers.map((item) => (
                        <tr key={item.user} style={{ borderTop: "1px solid #f1f5f9" }}>
                          <td style={tdStyle}>{item.user}</td>
                          <td style={tdStyle}>{item.server_count ?? 0}</td>
                          <td style={tdStyle}>
                            <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
                              {(item.servers || []).map((server) => (
                                <ServerPill
                                  key={`${item.user}-${server.server_name}`}
                                  text={server.display_name}
                                  clickable
                                  onClick={() => navigate(`/dashboard/server-monitor/${server.server_name}`)}
                                />
                              ))}
                            </div>
                          </td>
                          <td style={tdStyle}>{item.running_jobs ?? 0}</td>
                          <td style={tdStyle}>{item.queued_jobs ?? 0}</td>
                          <td style={tdStyle}>{item.total_jobs ?? 0}</td>
                          <td style={tdStyle}>{formatDateTime(item.last_seen_at)}</td>
                        </tr>
                      ))
                    )}
                  </tbody>
                </table>
              </div>
            </SectionCard>
          </section>

          <section style={{ marginBottom: 32 }}>
            <BlockTitle
              title="历史信息"
              subtitle={`基于近 ${data.range || range} 的历史快照聚合，展示用户跨服务器使用分布与长期活跃情况。`}
            />

            <div
              style={{
                display: "grid",
                gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))",
                gap: 16,
                marginBottom: 20,
              }}
            >
              <OverviewCard
                icon={Users}
                title="历史活跃用户数"
                value={historyOverview.active_user_count ?? "--"}
                subtext="在所选时间范围内提交或运行过任务的用户数"
              />
              <OverviewCard
                icon={Server}
                title="历史活跃服务器数"
                value={historyOverview.active_server_count ?? "--"}
                subtext="在所选时间范围内被使用过的服务器数量"
              />
              <OverviewCard
                icon={Layers3}
                title="历史任务总量"
                value={historyOverview.total_unique_jobs ?? "--"}
                subtext="按服务器聚合后的用户任务量汇总"
              />
              <OverviewCard
                icon={BarChart3}
                title="统计时间范围"
                value={data.range || range}
                subtext="支持近 7 天、1 个月、3 个月、1 年"
              />
            </div>

            <SectionCard
              title="历史用户跨服务器覆盖情况"
              subtitle="这部分最适合看谁是‘多服务器常客’，用进度条比纯表格更直观。"
            >
              <div style={{ padding: 20, display: "grid", gap: 20 }}>
                {filteredHistoryUsers.length === 0 ? (
                  <div style={{ color: "#6b7280", fontSize: 14 }}>暂无符合筛选条件的历史用户分布数据</div>
                ) : (
                  filteredHistoryUsers.map((item) => (
                    <div
                      key={item.user}
                      style={{
                        border: "1px solid #e5e7eb",
                        borderRadius: 14,
                        padding: 16,
                        background: "#fcfcfd",
                      }}
                    >
                      <div
                        style={{
                          display: "flex",
                          justifyContent: "space-between",
                          alignItems: "center",
                          gap: 12,
                          flexWrap: "wrap",
                          marginBottom: 12,
                        }}
                      >
                        <div>
                          <div style={{ fontSize: 16, fontWeight: 700, color: "#111827" }}>
                            {item.user}
                          </div>
                          <div style={{ marginTop: 4, fontSize: 13, color: "#6b7280" }}>
                            历史总任务 {item.total_jobs ?? 0}
                          </div>
                        </div>
                        <div style={{ fontSize: 12, color: "#6b7280" }}>
                          最近活跃：{formatDateTime(item.last_seen_at)}
                        </div>
                      </div>

                      <div style={{ marginBottom: 12 }}>
                        <UserServerProgress user={item} maxServerCount={maxHistoryServerCount} />
                      </div>

                      <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
                        {(item.servers || []).map((server) => (
                          <ServerPill
                            key={`${item.user}-${server.server_name}`}
                            text={`${server.display_name}（${server.total_jobs}）`}
                            clickable
                            onClick={() => navigate(`/dashboard/server-monitor/${server.server_name}`)}
                          />
                        ))}
                      </div>
                    </div>
                  ))
                )}
              </div>
            </SectionCard>

            <SectionCard
              title="历史用户详细统计"
              subtitle="这里保留精确表格，方便查具体某个用户在哪些服务器使用最多。"
            >
              <div style={{ overflowX: "auto" }}>
                <table style={{ width: "100%", borderCollapse: "collapse", minWidth: 1080 }}>
                  <thead>
                    <tr style={{ background: "#f8fafc", textAlign: "left" }}>
                      <th style={thStyle}>用户</th>
                      <th style={thStyle}>活跃服务器数</th>
                      <th style={thStyle}>历史总任务数</th>
                      <th style={thStyle}>主要服务器</th>
                      <th style={thStyle}>主要队列</th>
                      <th style={thStyle}>最近活跃时间</th>
                    </tr>
                  </thead>
                  <tbody>
                    {filteredHistoryUsers.length === 0 ? (
                      <tr>
                        <td colSpan={6} style={emptyTdStyle}>暂无符合筛选条件的历史用户统计数据</td>
                      </tr>
                    ) : (
                      filteredHistoryUsers.map((item) => {
                        const topServer = (item.servers || [])[0];
                        return (
                          <tr key={item.user} style={{ borderTop: "1px solid #f1f5f9" }}>
                            <td style={tdStyle}>{item.user}</td>
                            <td style={tdStyle}>{item.server_count ?? 0}</td>
                            <td style={tdStyle}>{item.total_jobs ?? 0}</td>
                            <td style={tdStyle}>{topServer?.display_name || "--"}</td>
                            <td style={tdStyle}>{topServer?.primary_queue || "--"}</td>
                            <td style={tdStyle}>{formatDateTime(item.last_seen_at)}</td>
                          </tr>
                        );
                      })
                    )}
                  </tbody>
                </table>
              </div>
            </SectionCard>
          </section>
        </>
      )}
    </ServerMonitorLayout>
  );
}

const thStyle = {
  padding: "14px 16px",
  fontSize: 13,
  fontWeight: 700,
  color: "#374151",
  borderBottom: "1px solid #e5e7eb",
  whiteSpace: "nowrap",
};

const tdStyle = {
  padding: "14px 16px",
  fontSize: 14,
  color: "#111827",
  verticalAlign: "top",
};

const emptyTdStyle = {
  padding: "28px 16px",
  textAlign: "center",
  color: "#6b7280",
  fontSize: 14,
};
