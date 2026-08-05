// frontend/src/pages/agents/PlatformGuideAgent.jsx
import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import AgentLayout from "./AgentLayout";
import { platformGuide } from "../../config/platformGuide";
import {
  Sparkles,
  Send,
  Compass,
  BookOpen,
  Server,
  Database,
  Trash2,
  MessageSquarePlus,
  MessageSquare,
} from "lucide-react";
import api, { apiLong } from "../../api/client";

function normalize(text) {
  return String(text || "").trim().toLowerCase();
}

function includesAny(text, keywords = []) {
  const normalizedText = normalize(text);
  return keywords.some((k) => normalizedText.includes(normalize(k)));
}

function findEntryByKeywords(keywords = []) {
  return (
    platformGuide.modules
      .flatMap((m) => m.entries || [])
      .find((e) => includesAny(e.name, keywords)) || null
  );
}

function buildEntryAnswer(entry, title) {
  return {
    type: "entry",
    title: title || entry.name,
    content: entry.usage || "可点击下方按钮直接进入对应页面。",
    path: entry.path || null,
  };
}

function buildModuleAnswer(mod, title) {
  return {
    type: "group",
    title: title || mod.name,
    content: mod.description || "你可以从下面这些入口进入。",
    entries: mod.entries || [],
  };
}

function matchGuideAnswer(input) {
  const q = normalize(input);

  if (!q) {
    return {
      type: "text",
      title: "平台导览智能体",
      content:
        "我是平台导览智能体，可以告诉你这个网站有哪些功能、每个模块怎么用，以及你的需求应该从哪里进入。",
    };
  }

  if (includesAny(q, ["你是谁", "你是干什么的", "你能做什么", "你叫什么"])) {
    return {
      type: "text",
      title: "平台导览智能体",
      content:
        "我是“平台导览智能体”，负责回答这个平台里的功能、入口位置和使用方法问题，帮你少走弯路。",
    };
  }

  if (includesAny(q, ["写论文", "写文章", "发文章", "投稿", "写代码", "闲聊", "讲笑话"])) {
    return {
      type: "out_of_scope",
      title: "当前不在平台导览范围内",
      content:
        "这个问题不属于当前平台导览范围。我主要帮助你查找平台里的功能入口、使用方法和页面位置。你可以继续问我服务器信息、数据库、文献推荐、学术报告、更新日志或反馈入口等问题。",
      suggestions: [
        "这个网站有什么功能？",
        "怎么看服务器使用情况？",
        "怎么查看个人数据库？",
        "怎么反馈问题？",
      ],
    };
  }

  for (const item of platformGuide.faq || []) {
    const question = normalize(item.question);
    if (q.includes(question) || question.includes(q)) {
      return {
        type: "entry",
        title: item.question,
        content: item.answer,
        path: item.path || null,
      };
    }
  }

  if (includesAny(q, ["功能", "网站", "平台", "模块", "能做什么"])) {
    return {
      type: "overview",
      title: platformGuide.name,
      content: platformGuide.intro,
      modules: platformGuide.modules || [],
    };
  }

  if (includesAny(q, ["服务器", "gpu", "跑任务", "使用情况", "资源占用", "用户使用总览"])) {
    const target = platformGuide.modules.find((m) => m.key === "server_monitor");
    if (target) return buildModuleAnswer(target, "服务器信息");
  }

  if (includesAny(q, ["数据库", "personal", "vasp", "qe", "epw", "个人数据库", "全组数据库"])) {
    const target = platformGuide.modules.find((m) => m.key === "db");
    if (target) return buildModuleAnswer(target, "数据库");
  }

  if (includesAny(q, ["文献", "论文", "paper", "article", "每日导读", "我的订阅", "文献库"])) {
    const target = platformGuide.modules.find((m) => m.key === "papers");
    if (target) return buildModuleAnswer(target, "文献推荐");
  }

  if (includesAny(q, ["学术报告", "报告", "seminar"])) {
    const reportEntry = findEntryByKeywords(["学术报告", "报告"]);
    if (reportEntry) return buildEntryAnswer(reportEntry, "学术报告");
  }

  if (includesAny(q, ["反馈", "建议", "bug", "报错", "问题提交", "出错", "反馈问题"])) {
    const feedbackEntry = findEntryByKeywords(["反馈", "建议"]);
    if (feedbackEntry) return buildEntryAnswer(feedbackEntry, "反馈与建议");

    return {
      type: "text",
      title: "反馈与建议",
      content: "你可以在平台的“反馈与建议”模块中提交问题、建议，并跟踪处理情况。",
    };
  }

  if (includesAny(q, ["更新日志", "更新", "修复记录", "changelog"])) {
    const logEntry = findEntryByKeywords(["更新日志", "日志"]);
    if (logEntry) return buildEntryAnswer(logEntry, "平台更新日志");
  }

  if (includesAny(q, ["快捷跳转", "快速跳转", "推荐入口", "从哪里进", "去哪里点"])) {
    const commonEntries = [
      {
        name: "服务器信息",
        usage: "查看服务器概览、服务器详情和用户使用总览",
        path: "/dashboard/server-monitor",
      },
      {
        name: "个人数据库",
        usage: "进入个人数据库入口，查看个人 VASP、QE/EPW 等任务数据",
        path: "/dashboard/db/personal",
      },
      {
        name: "每日导读",
        usage: "查看近期推荐文献",
        path: "/dashboard/papers/daily",
      },
      {
        name: "反馈与建议",
        usage: "提交问题、建议并跟踪处理情况",
        path: "/dashboard/issues",
      },
      {
        name: "返回总览首页",
        usage: "回到平台首页总览",
        path: "/dashboard",
      },
    ];

    return {
      type: "group",
      title: "推荐入口",
      content: "下面这些入口是平台中最常用的快捷跳转位置。",
      entries: commonEntries,
    };
  }

  return {
    type: "fallback",
    title: "不好意思，暂时没完全听懂，我更擅长平台导览问题",
    content:
      "我主要负责这个平台的导览。你可以换一种问法，例如：这个网站有什么功能、怎么看服务器使用情况、怎么查看个人数据库、怎么找文献、怎么查看学术报告、怎么反馈问题。",
    suggestions: [
      "这个网站有什么功能？",
      "怎么看服务器使用情况？",
      "怎么查看个人数据库？",
      "怎么找文献？",
      "怎么查看学术报告？",
      "怎么反馈问题？",
    ],
  };
}

function buildAssistantAnswer(question, llmText) {
  const guideMatch = matchGuideAnswer(question);

  return {
    type: guideMatch?.type || "text",
    title: guideMatch?.title || "平台导览智能体",
    content: llmText || guideMatch?.content || "暂时没有返回内容。",
    path: guideMatch?.path || null,
    entries: guideMatch?.entries || [],
    modules: guideMatch?.modules || [],
    suggestions: guideMatch?.suggestions || [],
  };
}

function Bubble({ role, children }) {
  const isUser = role === "user";

  return (
    <div
      style={{
        display: "flex",
        justifyContent: isUser ? "flex-end" : "flex-start",
        marginBottom: 18,
      }}
    >
      <div
        style={{
          maxWidth: isUser ? "72%" : "82%",
          background: isUser
            ? "linear-gradient(135deg, #2563eb 0%, #1d4ed8 100%)"
            : "rgba(255,255,255,0.96)",
          color: isUser ? "#fff" : "#111827",
          border: isUser ? "none" : "1px solid rgba(226,232,240,0.9)",
          borderRadius: isUser ? "18px 18px 6px 18px" : "18px 18px 18px 6px",
          padding: "14px 16px",
          boxShadow: isUser
            ? "0 10px 24px rgba(37, 99, 235, 0.22)"
            : "0 8px 24px rgba(15, 23, 42, 0.06)",
          whiteSpace: "pre-wrap",
          lineHeight: 1.75,
          fontSize: 14,
          backdropFilter: "blur(8px)",
        }}
      >
        {children}
      </div>
    </div>
  );
}

function createLocalSessionId() {
  return `platform-guide_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`;
}

function formatTime(ts) {
  if (!ts) return "";
  const d = new Date(ts * 1000);
  const mm = String(d.getMonth() + 1).padStart(2, "0");
  const dd = String(d.getDate()).padStart(2, "0");
  const hh = String(d.getHours()).padStart(2, "0");
  const mi = String(d.getMinutes()).padStart(2, "0");
  return `${mm}-${dd} ${hh}:${mi}`;
}

const INITIAL_MESSAGES = [
  {
    role: "assistant",
    answer: {
      type: "text",
      title: "平台导览智能体",
      content:
        "你好，我可以告诉你这个网站有哪些功能、应该怎么用，以及某个需求该从哪里进入。你可以直接问：怎么看服务器使用情况？怎么查看个人数据库？怎么找文献？",
    },
  },
];

function AnswerCard({ answer, navigate, onAsk }) {
  if (!answer) return null;

  const ActionButtons = ({ entries = [] }) =>
    entries.length > 0 ? (
      <div style={{ display: "grid", gap: 8, marginTop: 12 }}>
        {entries.map((entry) => (
          <button
            key={entry.name}
            type="button"
            onClick={() => entry.path && navigate(entry.path)}
            style={{
              border: "1px solid #dbeafe",
              background: "#eff6ff",
              color: "#1d4ed8",
              borderRadius: 10,
              padding: "10px 12px",
              textAlign: "left",
              cursor: "pointer",
            }}
          >
            <div style={{ fontWeight: 700 }}>{entry.name}</div>
            <div style={{ marginTop: 4, fontSize: 13 }}>{entry.usage}</div>
          </button>
        ))}
      </div>
    ) : null;

  const SuggestionButtons = ({ suggestions = [] }) =>
    suggestions.length > 0 ? (
      <div style={{ display: "flex", flexWrap: "wrap", gap: 8, marginTop: 12 }}>
        {suggestions.map((s) => (
          <button
            key={s}
            type="button"
            onClick={() => onAsk?.(s)}
            style={{
              border: "1px solid #e5e7eb",
              background: "#fff",
              color: "#374151",
              borderRadius: 999,
              padding: "6px 10px",
              cursor: "pointer",
              fontSize: 13,
            }}
          >
            {s}
          </button>
        ))}
      </div>
    ) : null;

  if (answer.type === "overview") {
    return (
      <div>
        <div style={{ fontWeight: 700, marginBottom: 8 }}>{answer.title}</div>
        <div style={{ color: "#4b5563", fontSize: 14, marginBottom: 12 }}>{answer.content}</div>
        <div style={{ display: "grid", gap: 8 }}>
          {(answer.modules || []).map((mod) => (
            <div
              key={mod.key}
              style={{
                border: "1px solid #e5e7eb",
                borderRadius: 12,
                padding: 10,
                background: "#f9fafb",
              }}
            >
              <div style={{ fontWeight: 700, color: "#111827" }}>{mod.name}</div>
              <div style={{ color: "#6b7280", fontSize: 13, marginTop: 4 }}>
                {mod.description}
              </div>
            </div>
          ))}
        </div>
      </div>
    );
  }

  if (answer.type === "group") {
    return (
      <div>
        <div style={{ fontWeight: 700, marginBottom: 8 }}>{answer.title}</div>
        <div style={{ color: "#4b5563", fontSize: 14 }}>{answer.content}</div>
        <ActionButtons entries={answer.entries || []} />
      </div>
    );
  }

  if (answer.type === "entry" || answer.type === "faq") {
    return (
      <div>
        <div style={{ fontWeight: 700, marginBottom: 8 }}>{answer.title}</div>
        <div style={{ color: "#4b5563", fontSize: 14 }}>{answer.content}</div>
        {answer.path ? (
          <button
            type="button"
            onClick={() => navigate(answer.path)}
            style={{
              marginTop: 12,
              border: "1px solid #dbeafe",
              background: "#eff6ff",
              color: "#1d4ed8",
              borderRadius: 10,
              padding: "8px 12px",
              cursor: "pointer",
              fontWeight: 600,
            }}
          >
            直接前往
          </button>
        ) : null}
      </div>
    );
  }

  if (answer.type === "out_of_scope" || answer.type === "fallback") {
    return (
      <div>
        <div style={{ fontWeight: 700, marginBottom: 8 }}>{answer.title}</div>
        <div style={{ color: "#4b5563", fontSize: 14 }}>{answer.content}</div>
        <SuggestionButtons suggestions={answer.suggestions || []} />
      </div>
    );
  }

  return (
    <div>
      <div style={{ fontWeight: 700, marginBottom: 8 }}>{answer.title}</div>
      <div style={{ color: "#4b5563", fontSize: 14 }}>{answer.content}</div>
      <SuggestionButtons suggestions={answer.suggestions || []} />
    </div>
  );
}

export default function PlatformGuideAgent() {
  const navigate = useNavigate();
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [loadingHistory, setLoadingHistory] = useState(false);
  const [currentModel, setCurrentModel] = useState("未连接");
  const [messages, setMessages] = useState(INITIAL_MESSAGES);
  const [sessionList, setSessionList] = useState([]);
  const [activeSessionId, setActiveSessionId] = useState("");
  const [deletingSessionId, setDeletingSessionId] = useState("");

  const quickQuestions = useMemo(() => platformGuide.quickQuestions || [], []);

  const loadSessions = async (nextActiveId = null) => {
    const res = await api.get("/agents/sessions", {
      params: {
        agent: "platform-guide",
        limit: 30,
      },
    });

    const sessions = res?.data?.sessions || [];
    setSessionList(sessions);

    if (nextActiveId) {
      setActiveSessionId(nextActiveId);
      localStorage.setItem("agent_session_platform_guide_active", nextActiveId);
      return nextActiveId;
    }

    const savedActive = localStorage.getItem("agent_session_platform_guide_active");
    const matched =
      sessions.find((s) => s.session_id === savedActive)?.session_id ||
      sessions[0]?.session_id ||
      "";

    if (matched) {
      setActiveSessionId(matched);
      localStorage.setItem("agent_session_platform_guide_active", matched);
    }

    return matched;
  };

  const loadHistory = async (sessionId) => {
    if (!sessionId) {
      setMessages(INITIAL_MESSAGES);
      return;
    }

    setLoadingHistory(true);

    try {
      const res = await api.get("/agents/history", {
        params: {
          agent: "platform-guide",
          session_id: sessionId,
        },
      });

      const history = res?.data?.history || [];

      if (!history.length) {
        setMessages(INITIAL_MESSAGES);
        return;
      }

      const rebuilt = history.map((item) => {
        if (item.role === "user") {
          return {
            role: "user",
            text: item.content || "",
          };
        }

        const answerType = item.answer_type || "text";
        const answerPayload = item.answer_payload || null;

        if (answerType === "structured" && answerPayload && typeof answerPayload === "object") {
          return {
            role: "assistant",
            answer: answerPayload,
          };
        }

        return {
          role: "assistant",
          answer: {
            type: "text",
            title: "平台导览智能体",
            content: item.content || "",
          },
        };
      });

      setMessages(rebuilt);
    } catch (e) {
      console.error("load platform guide history failed:", e);
      setMessages(INITIAL_MESSAGES);
    } finally {
      setLoadingHistory(false);
    }
  };

  useEffect(() => {
    (async () => {
      try {
        const matched = await loadSessions();

        if (!matched) {
          const newId = createLocalSessionId();
          await api.post("/agents/session/create", {
            agent: "platform-guide",
            session_id: newId,
            title: "新对话",
          });
          await loadSessions(newId);
          await loadHistory(newId);
        } else {
          await loadHistory(matched);
        }
      } catch (e) {
        console.error("init platform guide sessions failed:", e);
      }
    })();
  }, []);

  const createNewSession = async () => {
    if (loading || loadingHistory) return;

    const newId = createLocalSessionId();

    try {
      await api.post("/agents/session/create", {
        agent: "platform-guide",
        session_id: newId,
        title: "新对话",
      });

      await loadSessions(newId);
      setMessages(INITIAL_MESSAGES);
      setInput("");
      setCurrentModel("未连接");
    } catch (e) {
      console.error("create platform guide session failed:", e);
    }
  };

  const switchSession = async (sessionId) => {
    if (!sessionId || loading) return;
    setActiveSessionId(sessionId);
    localStorage.setItem("agent_session_platform_guide_active", sessionId);
    await loadHistory(sessionId);
  };

  const deleteOneSession = async (sessionId) => {
    if (!sessionId || loading) return;

    setDeletingSessionId(sessionId);

    try {
      await api.post("/agents/session/delete", {
        agent: "platform-guide",
        session_id: sessionId,
      });

      const remaining = sessionList.filter((s) => s.session_id !== sessionId);

      if (activeSessionId === sessionId) {
        const nextId = remaining[0]?.session_id || "";
        setActiveSessionId(nextId);

        if (nextId) {
          localStorage.setItem("agent_session_platform_guide_active", nextId);
          await loadSessions(nextId);
          await loadHistory(nextId);
        } else {
          localStorage.removeItem("agent_session_platform_guide_active");
          await createNewSession();
        }
      } else {
        await loadSessions(activeSessionId);
      }
    } catch (e) {
      console.error("delete platform guide session failed:", e);
    } finally {
      setDeletingSessionId("");
    }
  };

  const clearSession = async () => {
    if (loading || !activeSessionId) return;

    try {
      await api.post("/agents/clear", {
        agent: "platform-guide",
        session_id: activeSessionId,
      });
    } catch (e) {
      console.error("clear platform guide failed:", e);
    } finally {
      setMessages(INITIAL_MESSAGES);
      setInput("");
      await loadSessions(activeSessionId);
    }
  };

  const handleAsk = async (text) => {
    const question = String(text || input).trim();
    if (!question || loading || !activeSessionId) return;

    const nextUserMessage = { role: "user", text: question };

    setMessages((prev) => [...prev, nextUserMessage]);
    setInput("");
    setLoading(true);

    try {
      const history = messages
        .filter((item) => item.role === "user" || item.role === "assistant")
        .map((item) => ({
          role: item.role,
          content: item.role === "user" ? item.text : item.answer?.content || "",
        }));

      const res = await apiLong.post("/agents/chat", {
        agent: "platform-guide",
        message: question,
        session_id: activeSessionId,
        history,
      });

      setCurrentModel(res?.data?.model || "未知模型");

      const nextAnswerType = res?.data?.answer_type || "text";
      const nextAnswerPayload = res?.data?.answer_payload || null;

      const assistantAnswer =
        nextAnswerType === "structured" && nextAnswerPayload
          ? nextAnswerPayload
          : buildAssistantAnswer(question, res.data.answer);

      setMessages((prev) => [
        ...prev,
        {
          role: "assistant",
          answer: assistantAnswer,
        },
      ]);

      await loadSessions(activeSessionId);
    } catch (e) {
      console.error("agent chat failed:", e);

      const fallback = buildAssistantAnswer(question, "");

      setMessages((prev) => [
        ...prev,
        {
          role: "assistant",
          answer: {
            ...fallback,
            content:
              fallback.content ||
              "本地智能体服务调用失败，请检查后端和 Ollama 是否已启动。",
          },
        },
      ]);
    } finally {
      setLoading(false);
    }
  };

  return (
    <AgentLayout
      currentPath="/dashboard/agents/platform-guide"
      currentAgentKey="platform-guide"
    >
      <section
        style={{
          maxWidth: 1480,
          margin: "0 auto",
          width: "100%",
        }}
      >
        <div
          style={{
            background: "linear-gradient(135deg, #1d4ed8 0%, #2563eb 100%)",
            color: "#fff",
            padding: "20px 24px",
            marginBottom: 16,
            borderRadius: 24,
            boxShadow: "0 12px 32px rgba(37, 99, 235, 0.18)",
          }}
        >
          <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 10 }}>
            <Sparkles size={20} />
            <span style={{ fontSize: 14, fontWeight: 700, letterSpacing: 1 }}>AGENT</span>
          </div>

          <h1 style={{ margin: 0, fontSize: 28 }}>平台导览智能体</h1>
          <p style={{ margin: "10px 0 0", color: "rgba(255,255,255,0.88)", lineHeight: 1.7 }}>
            它不会替你写论文，但可以很认真地告诉你这个网站该点哪里、先看哪里、别迷路去哪里。
          </p>

          <div
            style={{
              marginTop: 12,
              display: "inline-flex",
              alignItems: "center",
              gap: 8,
              padding: "6px 12px",
              borderRadius: 999,
              background: "rgba(255,255,255,0.16)",
              color: "#fff",
              fontSize: 13,
              fontWeight: 600,
            }}
          >
            <Sparkles size={14} />
            当前模型：{currentModel}
          </div>
        </div>

        <div
          style={{
            display: "grid",
            gridTemplateColumns: "320px minmax(0, 1fr)",
            gap: 24,
            alignItems: "stretch",
          }}
        >
          <aside
            style={{
              background: "rgba(255,255,255,0.9)",
              borderRadius: 24,
              border: "1px solid rgba(226,232,240,0.9)",
              padding: 18,
              boxShadow: "0 12px 32px rgba(15, 23, 42, 0.05)",
              backdropFilter: "blur(10px)",
              position: "sticky",
              top: 84,
              height: "calc(100vh - 120px)",
              overflowY: "auto",
            }}
          >
            <button
              type="button"
              onClick={createNewSession}
              disabled={loading || loadingHistory}
              style={{
                width: "100%",
                border: "none",
                background: "linear-gradient(135deg, #2563eb 0%, #1d4ed8 100%)",
                color: "#fff",
                borderRadius: 14,
                padding: "12px 14px",
                cursor: loading || loadingHistory ? "not-allowed" : "pointer",
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                gap: 8,
                fontWeight: 700,
                marginBottom: 18,
              }}
            >
              <MessageSquarePlus size={16} />
              新对话
            </button>

            <div style={{ fontSize: 16, fontWeight: 800, color: "#111827", marginBottom: 12 }}>
              最近聊天
            </div>

            <div style={{ display: "grid", gap: 10, marginBottom: 18 }}>
              {sessionList.map((session) => {
                const active = session.session_id === activeSessionId;
                return (
                  <div
                    key={session.session_id}
                    style={{
                      border: active ? "1px solid #93c5fd" : "1px solid #e5e7eb",
                      background: active ? "#eff6ff" : "#fff",
                      borderRadius: 14,
                      padding: 10,
                    }}
                  >
                    <button
                      type="button"
                      onClick={() => switchSession(session.session_id)}
                      style={{
                        width: "100%",
                        border: "none",
                        background: "transparent",
                        textAlign: "left",
                        cursor: "pointer",
                        padding: 0,
                      }}
                    >
                      <div
                        style={{
                          display: "flex",
                          alignItems: "center",
                          gap: 8,
                          color: active ? "#1d4ed8" : "#111827",
                          fontWeight: 700,
                          fontSize: 14,
                        }}
                      >
                        <MessageSquare size={14} />
                        <span
                          style={{
                            overflow: "hidden",
                            textOverflow: "ellipsis",
                            whiteSpace: "nowrap",
                          }}
                        >
                          {session.title || "新对话"}
                        </span>
                      </div>

                      <div style={{ marginTop: 6, fontSize: 12, color: "#6b7280" }}>
                        {formatTime(session.updated_at)}
                      </div>
                    </button>

                    <button
                      type="button"
                      onClick={() => deleteOneSession(session.session_id)}
                      disabled={deletingSessionId === session.session_id}
                      style={{
                        marginTop: 8,
                        border: "1px solid #dbeafe",
                        background: "#fff",
                        color: "#1d4ed8",
                        borderRadius: 10,
                        padding: "6px 10px",
                        cursor: "pointer",
                        fontSize: 12,
                        fontWeight: 600,
                      }}
                    >
                      {deletingSessionId === session.session_id ? "删除中..." : "删除"}
                    </button>
                  </div>
                );
              })}
            </div>

            <div style={{ fontSize: 16, fontWeight: 800, color: "#111827", marginBottom: 12 }}>
              快速提问
            </div>

            <div style={{ display: "grid", gap: 10, marginBottom: 18 }}>
              {quickQuestions.map((q) => (
                <button
                  key={q}
                  type="button"
                  onClick={() => handleAsk(q)}
                  disabled={loading || loadingHistory}
                  style={{
                    border: "1px solid #e5e7eb",
                    background: "#f9fafb",
                    borderRadius: 12,
                    padding: "10px 12px",
                    textAlign: "left",
                    cursor: loading || loadingHistory ? "not-allowed" : "pointer",
                    color: "#111827",
                    fontSize: 14,
                    opacity: loading || loadingHistory ? 0.7 : 1,
                  }}
                >
                  {q}
                </button>
              ))}
            </div>

            <div
              style={{
                borderTop: "1px solid #e5e7eb",
                paddingTop: 16,
                display: "grid",
                gap: 10,
              }}
            >
              <div style={{ fontSize: 15, fontWeight: 700, color: "#111827" }}>会话操作</div>

              <button
                type="button"
                onClick={clearSession}
                disabled={loading || loadingHistory}
                style={{
                  border: "1px solid #bfdbfe",
                  background: "#eff6ff",
                  color: "#1d4ed8",
                  borderRadius: 14,
                  padding: "10px 12px",
                  cursor: loading || loadingHistory ? "not-allowed" : "pointer",
                  display: "flex",
                  alignItems: "center",
                  gap: 10,
                  fontSize: 14,
                  fontWeight: 600,
                  opacity: loading || loadingHistory ? 0.7 : 1,
                }}
              >
                <Trash2 size={16} />
                <span>清空当前对话</span>
              </button>
            </div>

            <div
              style={{
                borderTop: "1px solid #e5e7eb",
                marginTop: 16,
                paddingTop: 16,
                display: "grid",
                gap: 10,
              }}
            >
              <div style={{ fontSize: 15, fontWeight: 700, color: "#111827" }}>推荐入口</div>

              <button
                type="button"
                onClick={() => navigate("/dashboard/server-monitor")}
                style={entryBtnStyle}
              >
                <Server size={16} />
                <span>服务器信息</span>
              </button>

              <button
                type="button"
                onClick={() => navigate("/dashboard/db/personal")}
                style={entryBtnStyle}
              >
                <Database size={16} />
                <span>个人数据库</span>
              </button>

              <button
                type="button"
                onClick={() => navigate("/dashboard/papers/daily")}
                style={entryBtnStyle}
              >
                <BookOpen size={16} />
                <span>每日导读</span>
              </button>

              <button
                type="button"
                onClick={() => navigate("/dashboard")}
                style={entryBtnStyle}
              >
                <Compass size={16} />
                <span>返回总览首页</span>
              </button>

              <button
                type="button"
                onClick={() => navigate("/dashboard/issues")}
                style={entryBtnStyle}
              >
                <span>反馈与建议</span>
              </button>
            </div>
          </aside>

          <section
            style={{
              background: "linear-gradient(180deg, #ffffff 0%, #f8fbff 100%)",
              borderRadius: 24,
              border: "1px solid rgba(226,232,240,0.9)",
              minHeight: "calc(100vh - 220px)",
              maxHeight: "calc(100vh - 220px)",
              display: "flex",
              flexDirection: "column",
              boxShadow: "0 20px 60px rgba(15, 23, 42, 0.08)",
              overflow: "hidden",
            }}
          >
            <div
              style={{
                padding: "18px 20px",
                borderBottom: "1px solid #e5e7eb",
                display: "flex",
                alignItems: "center",
                justifyContent: "space-between",
                gap: 12,
              }}
            >
              <div>
                <div style={{ fontSize: 18, fontWeight: 800, color: "#111827" }}>对话区</div>
                <div style={{ marginTop: 6, fontSize: 13, color: "#6b7280" }}>
                  适合问：这个网站有什么功能、怎么看服务器、怎么找数据库、怎么查文献。
                </div>
              </div>

              <button
                type="button"
                onClick={clearSession}
                disabled={loading || loadingHistory}
                style={{
                  border: "1px solid #bfdbfe",
                  background: "#eff6ff",
                  color: "#1d4ed8",
                  borderRadius: 10,
                  padding: "8px 12px",
                  cursor: loading || loadingHistory ? "not-allowed" : "pointer",
                  fontWeight: 600,
                  opacity: loading || loadingHistory ? 0.7 : 1,
                  whiteSpace: "nowrap",
                }}
              >
                清空当前对话
              </button>
            </div>

            <div
              style={{
                flex: 1,
                padding: "24px 28px",
                background:
                  "radial-gradient(circle at top, rgba(59,130,246,0.06), transparent 28%), #f8fafc",
                overflowY: "auto",
              }}
            >
              {loadingHistory ? (
                <Bubble role="assistant">
                  <div>
                    <div style={{ fontWeight: 700, marginBottom: 8 }}>平台导览智能体</div>
                    <div style={{ color: "#4b5563", fontSize: 14 }}>
                      正在加载历史对话，请稍等片刻...
                    </div>
                  </div>
                </Bubble>
              ) : (
                messages.map((msg, idx) => (
                  <Bubble key={idx} role={msg.role}>
                    {msg.role === "user" ? (
                      msg.text
                    ) : (
                      <AnswerCard answer={msg.answer} navigate={navigate} onAsk={handleAsk} />
                    )}
                  </Bubble>
                ))
              )}

              {loading ? (
                <Bubble role="assistant">
                  <div>
                    <div style={{ fontWeight: 700, marginBottom: 8 }}>平台导览智能体</div>
                    <div style={{ color: "#4b5563", fontSize: 14 }}>
                      正在思考中，请稍等片刻...
                    </div>
                  </div>
                </Bubble>
              ) : null}
            </div>

            <div
              style={{
                borderTop: "1px solid rgba(226,232,240,0.9)",
                padding: "16px 20px 20px",
                background: "rgba(255,255,255,0.88)",
                backdropFilter: "blur(10px)",
              }}
            >
              <div
                style={{
                  display: "flex",
                  gap: 10,
                  alignItems: "center",
                  background: "#fff",
                  border: "1px solid #dbe3ef",
                  borderRadius: 18,
                  padding: 8,
                  boxShadow: "0 8px 24px rgba(15, 23, 42, 0.06)",
                }}
              >
                <input
                  value={input}
                  onChange={(e) => setInput(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") handleAsk();
                  }}
                  placeholder="输入你的问题，例如：怎么看服务器使用情况？"
                  disabled={loading || loadingHistory}
                  style={{
                    flex: 1,
                    border: "none",
                    borderRadius: 14,
                    padding: "12px 14px",
                    fontSize: 14,
                    outline: "none",
                    background: "transparent",
                    color: "#111827",
                  }}
                />

                <button
                  type="button"
                  onClick={() => handleAsk()}
                  disabled={loading || loadingHistory}
                  style={{
                    border: "none",
                    background: loading
                      ? "linear-gradient(135deg, #93c5fd 0%, #60a5fa 100%)"
                      : "linear-gradient(135deg, #2563eb 0%, #1d4ed8 100%)",
                    color: "#fff",
                    borderRadius: 14,
                    padding: "12px 18px",
                    fontWeight: 700,
                    cursor: loading || loadingHistory ? "not-allowed" : "pointer",
                    display: "inline-flex",
                    alignItems: "center",
                    justifyContent: "center",
                    gap: 8,
                    boxShadow: loading
                      ? "none"
                      : "0 8px 18px rgba(37, 99, 235, 0.24)",
                    minWidth: 96,
                  }}
                >
                  <Send size={16} />
                  {loading ? "处理中" : "发送"}
                </button>
              </div>
            </div>
          </section>
        </div>
      </section>
    </AgentLayout>
  );
}

const entryBtnStyle = {
  border: "1px solid #e5e7eb",
  background: "linear-gradient(180deg, #ffffff 0%, #f8fafc 100%)",
  borderRadius: 14,
  padding: "10px 12px",
  cursor: "pointer",
  display: "flex",
  alignItems: "center",
  gap: 10,
  color: "#111827",
  fontSize: 14,
  boxShadow: "0 4px 12px rgba(15, 23, 42, 0.04)",
};

