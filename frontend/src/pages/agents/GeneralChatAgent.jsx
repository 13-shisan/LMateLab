// frontend/src/pages/agents/GeneralChatAgent.jsx
import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import AgentLayout from "./AgentLayout";
import {
  Sparkles,
  Send,
  Compass,
  BookOpen,
  Server,
  Database,
  Bot,
  Trash2,
  ExternalLink,
  MessageSquarePlus,
  MessageSquare,
  Copy,
  Check,
  RefreshCw,
  ThumbsUp,
  ThumbsDown,
} from "lucide-react";
import api, { apiLong } from "../../api/client";
import { platformGuide } from "../../config/platformGuide";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";
import rehypeKatex from "rehype-katex";
import "katex/dist/katex.min.css";
import "./general-chat-markdown.css";

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
      title: "平台导览支持",
      content: "我可以帮你定位这个平台里的功能入口、页面位置和常见模块。",
    };
  }

  if (includesAny(q, ["功能", "网站", "平台", "模块", "能做什么"])) {
    return {
      type: "overview",
      title: platformGuide.name,
      content: platformGuide.intro,
      modules: platformGuide.modules || [],
    };
  }

  if (includesAny(q, ["服务器", "使用情况", "资源占用", "用户使用总览"]) &&
      includesAny(q, ["怎么看", "怎么查看", "哪里看", "入口", "进入"])) {
    const target = platformGuide.modules.find((m) => m.key === "server_monitor");
    if (target) return buildModuleAnswer(target, "服务器信息");
  }

  if (includesAny(q, ["个人数据库", "全组数据库", "数据库"]) &&
      includesAny(q, ["怎么看", "怎么查看", "哪里看", "入口", "进入"])) {
    const target = platformGuide.modules.find((m) => m.key === "db");
    if (target) return buildModuleAnswer(target, "数据库");
  }

  if (includesAny(q, ["文献", "每日导读", "我的订阅", "文献库"]) &&
      includesAny(q, ["怎么看", "怎么查看", "哪里看", "入口", "进入"])) {
    const target = platformGuide.modules.find((m) => m.key === "papers");
    if (target) return buildModuleAnswer(target, "文献推荐");
  }

  if (includesAny(q, ["学术报告", "报告", "seminar"])) {
    const reportEntry = findEntryByKeywords(["学术报告", "报告"]);
    if (reportEntry) return buildEntryAnswer(reportEntry, "学术报告");
  }

  if (includesAny(q, ["反馈", "建议", "bug", "报错", "问题提交", "反馈问题"])) {
    const feedbackEntry = findEntryByKeywords(["反馈", "建议"]);
    if (feedbackEntry) return buildEntryAnswer(feedbackEntry, "反馈与建议");
  }

  if (includesAny(q, ["更新日志", "更新", "修复记录", "changelog"])) {
    const logEntry = findEntryByKeywords(["更新日志", "日志"]);
    if (logEntry) return buildEntryAnswer(logEntry, "平台更新日志");
  }

  return {
    type: "text",
    title: "平台相关问题",
    content: "我可以继续帮你定位平台功能入口，也可以直接带你跳转到对应页面。",
  };
}

function buildGuideStyleAnswer(question, llmText) {
  const guideMatch = matchGuideAnswer(question);

  return {
    type: guideMatch?.type || "text",
    title: guideMatch?.title || "平台相关问题",
    content: llmText || guideMatch?.content || "暂时没有返回内容。",
    path: guideMatch?.path || null,
    entries: guideMatch?.entries || [],
    modules: guideMatch?.modules || [],
    suggestions: guideMatch?.suggestions || [],
  };
}

function AnswerCard({ answer, navigate, onAsk, fromGeneralChat = false }) {
  if (!answer) return null;

  const goPath = (path) => {
    if (!path) return;
    if (fromGeneralChat) {
      const hasQuery = path.includes("?");
      navigate(`${path}${hasQuery ? "&" : "?"}from=general-chat`);
      return;
    }
    navigate(path);
  };

  const ActionButtons = ({ entries = [] }) =>
    entries.length > 0 ? (
      <div style={{ display: "grid", gap: 8, marginTop: 12 }}>
        {entries.map((entry) => (
          <button
            key={entry.name}
            type="button"
            onClick={() => entry.path && goPath(entry.path)}
            style={{
              border: "1px solid #ede9fe",
              background: "#faf5ff",
              color: "#6d28d9",
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

  if (answer.type === "overview") {
    return (
      <div>
        <div style={{ fontWeight: 700, marginBottom: 8 }}>{answer.title}</div>
        <div style={{ color: "#4b5563", fontSize: 14, marginBottom: 12 }}>
          <MarkdownMessage content={answer.content} />
        </div>
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
        <div style={{ color: "#4b5563", fontSize: 14 }}>
          <MarkdownMessage content={answer.content} />
        </div>
        <ActionButtons entries={answer.entries || []} />
        <div style={{ marginTop: 12 }}>
          <button
            type="button"
            onClick={() => onAsk?.("继续留在通用大模型里帮我解释这个功能")}
            style={{
              border: "1px solid #ddd6fe",
              background: "#fff",
              color: "#6d28d9",
              borderRadius: 999,
              padding: "6px 12px",
              cursor: "pointer",
              fontSize: 13,
            }}
          >
            留在通用大模型继续解释
          </button>
        </div>
      </div>
    );
  }

  if (answer.type === "entry") {
    return (
      <div>
        <div style={{ fontWeight: 700, marginBottom: 8 }}>{answer.title}</div>
        <div style={{ color: "#4b5563", fontSize: 14 }}>
          <MarkdownMessage content={answer.content} />
        </div>

        <div style={{ display: "flex", flexWrap: "wrap", gap: 8, marginTop: 12 }}>
          {answer.path ? (
            <button
              type="button"
              onClick={() => goPath(answer.path)}
              style={{
                border: "1px solid #ede9fe",
                background: "#faf5ff",
                color: "#6d28d9",
                borderRadius: 10,
                padding: "8px 12px",
                cursor: "pointer",
                fontWeight: 600,
                display: "inline-flex",
                alignItems: "center",
                gap: 6,
              }}
            >
              <ExternalLink size={14} />
              直接前往
            </button>
          ) : null}

          <button
            type="button"
            onClick={() => onAsk?.(`继续给我解释：${answer.title}`)}
            style={{
              border: "1px solid #ddd6fe",
              background: "#fff",
              color: "#6d28d9",
              borderRadius: 10,
              padding: "8px 12px",
              cursor: "pointer",
              fontWeight: 600,
            }}
          >
            留在通用大模型继续解释
          </button>
        </div>
      </div>
    );
  }

  return (
    <div>
      <div style={{ fontWeight: 700, marginBottom: 8 }}>{answer.title}</div>
      <div style={{ color: "#4b5563", fontSize: 14 }}>
        <MarkdownMessage content={answer.content} />
      </div>

    </div>
  );
}

function normalizeMathForMarkdown(rawText) {
  const text = String(rawText || "");
  if (!text.trim()) return "";

  // 先保护真正的块公式：独占一行的 $$ ... $$
  const blockPlaceholders = [];
  let protectedText = text.replace(
    /(^|\n)\$\$\s*\n([\s\S]*?)\n\s*\$\$(?=\n|$)/g,
    (match) => {
      const token = `__BLOCK_MATH_${blockPlaceholders.length}__`;
      blockPlaceholders.push(match);
      return token;
    }
  );

  // 再把“短小的、单行的 $$...$$”转成行内 $...$
  // 例如：$$e$$、$$\tau$$、$$m^*$$
  protectedText = protectedText.replace(/\$\$([^\n$]{1,80}?)\$\$/g, (_, expr) => {
    const trimmed = String(expr || "").trim();

    // 如果里面看起来像复杂块公式，就不强转
    if (
      trimmed.length > 40 ||
      trimmed.includes("\\begin") ||
      trimmed.includes("\\end") ||
      trimmed.includes("\\frac") ||
      trimmed.includes("\\sum") ||
      trimmed.includes("\\int") ||
      trimmed.includes("\\begin{pmatrix}")
    ) {
      return `$$${trimmed}$$`;
    }

    return `$${trimmed}$`;
  });

  // 恢复块公式
  protectedText = protectedText.replace(/__BLOCK_MATH_(\d+)__/g, (_, idx) => {
    return blockPlaceholders[Number(idx)] || "";
  });

  return protectedText;
}

function MarkdownMessage({ content, isUser = false }) {
  const text = normalizeMathForMarkdown(content);

  return (
    <div className={isUser ? "chat-markdown chat-markdown-user" : "chat-markdown"}>
      <ReactMarkdown
        remarkPlugins={[remarkGfm, remarkMath]}
        rehypePlugins={[rehypeKatex]}
      >
        {text}
      </ReactMarkdown>
    </div>
  );
}

function getMessagePlainText(msg) {
  if (!msg) return "";

  if (msg.role === "user") {
    return msg.text || "";
  }

  if (msg.answer) {
    return [msg.answer.title, msg.answer.content]
      .filter(Boolean)
      .join("\n\n");
  }

  return msg.text || "";
}

async function copyMessageText(msg, setCopiedMessageId) {
  const text = getMessagePlainText(msg);
  try {
    await navigator.clipboard.writeText(String(text || ""));
    setCopiedMessageId(msg.id || "");
    setTimeout(() => setCopiedMessageId(""), 1500);
  } catch (e) {
    console.error("copy failed:", e);
  }
}

function MessageToolbar({
  msg,
  copied,
  feedback,
  onCopy,
  onRegenerate,
  onFeedback,
}) {
  const iconBtnStyle = {
    width: 30,
    height: 30,
    border: "1px solid #e5e7eb",
    background: "#fff",
    color: "#6b7280",
    borderRadius: 999,
    cursor: "pointer",
    display: "inline-flex",
    alignItems: "center",
    justifyContent: "center",
    transition: "all 0.15s ease",
    boxShadow: "0 2px 8px rgba(15, 23, 42, 0.04)",
  };

  return (
    <div
      style={{
        display: "flex",
        gap: 8,
        flexWrap: "wrap",
        marginTop: 8,
      }}
    >
      <button
        type="button"
        onClick={onCopy}
        title={copied ? "已复制" : "复制"}
        style={{
          ...iconBtnStyle,
          color: copied ? "#16a34a" : "#6b7280",
          borderColor: copied ? "#86efac" : "#e5e7eb",
          background: copied ? "#f0fdf4" : "#fff",
        }}
      >
        {copied ? <Check size={15} /> : <Copy size={15} />}
      </button>

      {msg.role === "assistant" ? (
        <>
          <button
            type="button"
            onClick={onRegenerate}
            title="重新生成"
            style={iconBtnStyle}
          >
            <RefreshCw size={15} />
          </button>

          <button
            type="button"
            onClick={() => onFeedback("like")}
            title="喜欢"
            style={{
              ...iconBtnStyle,
              color: feedback === "like" ? "#16a34a" : "#6b7280",
              borderColor: feedback === "like" ? "#86efac" : "#e5e7eb",
              background: feedback === "like" ? "#f0fdf4" : "#fff",
            }}
          >
            <ThumbsUp size={15} />
          </button>

          <button
            type="button"
            onClick={() => onFeedback("dislike")}
            title="不喜欢"
            style={{
              ...iconBtnStyle,
              color: feedback === "dislike" ? "#dc2626" : "#6b7280",
              borderColor: feedback === "dislike" ? "#fca5a5" : "#e5e7eb",
              background: feedback === "dislike" ? "#fef2f2" : "#fff",
            }}
          >
            <ThumbsDown size={15} />
          </button>
        </>
      ) : null}
    </div>
  );
}


function Bubble({ role, children }) {
  const isUser = role === "user";

  return (
    <div
      style={{
        display: "flex",
        justifyContent: isUser ? "flex-end" : "flex-start",
        marginBottom: 0,
      }}
    >
      <div
        style={{
          maxWidth: isUser ? "72%" : "82%",
          background: isUser
            ? "linear-gradient(135deg, #7c3aed 0%, #5b21b6 100%)"
            : "rgba(255,255,255,0.96)",
          color: isUser ? "#fff" : "#111827",
          border: isUser ? "none" : "1px solid rgba(226,232,240,0.9)",
          borderRadius: isUser ? "18px 18px 6px 18px" : "18px 18px 18px 6px",
          padding: "14px 16px",
          boxShadow: isUser
            ? "0 10px 24px rgba(124, 58, 237, 0.22)"
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

function MessageItem({
  msg,
  idx,
  navigate,
  handleAsk,
  copiedMessageId,
  feedbackMap,
  setCopiedMessageId,
  regenerateAnswer,
  submitFeedback,
}) {
  const isUser = msg.role === "user";

  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        alignItems: isUser ? "flex-end" : "flex-start",
        marginBottom: 18,
      }}
    >
      <Bubble role={msg.role}>
        {msg.role === "user" ? (
          <MarkdownMessage content={msg.text} isUser={true} />
        ) : msg.answer ? (
          <AnswerCard
            answer={msg.answer}
            navigate={navigate}
            onAsk={handleAsk}
            fromGeneralChat={true}
          />
        ) : (
          <div>
            {msg.actualAgent === "platform-guide" ? (
              <div
                style={{
                  marginBottom: 8,
                  display: "inline-flex",
                  alignItems: "center",
                  gap: 6,
                  padding: "4px 10px",
                  borderRadius: 999,
                  background: "#f3e8ff",
                  color: "#6d28d9",
                  fontSize: 12,
                  fontWeight: 700,
                }}
              >
                已调用平台导览智能体
              </div>
            ) : null}

            <MarkdownMessage content={msg.text} />
          </div>
        )}
      </Bubble>

      <div
        style={{
          width: isUser ? "72%" : "82%",
          display: "flex",
          justifyContent: isUser ? "flex-end" : "flex-start",
          padding: isUser ? "0 4px 0 0" : "0 0 0 4px",
        }}
      >
        <MessageToolbar
          msg={msg}
          copied={copiedMessageId === msg.id}
          feedback={feedbackMap[msg.id] || ""}
          onCopy={() => copyMessageText(msg, setCopiedMessageId)}
          onRegenerate={() => regenerateAnswer(idx)}
          onFeedback={(value) => submitFeedback(msg, value)}
        />
      </div>
    </div>
  );
}

function createLocalSessionId() {
  return `general-chat_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`;
}

function createMessageId() {
  return `msg_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`;
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

const INITIAL_ASSISTANT_TEXT =
  "你好，我是通用大模型。你可以直接问我开放式问题，比如概念解释、内容润色、总结归纳、思路整理等。";

export default function GeneralChatAgent() {
  const navigate = useNavigate();

  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [loadingHistory, setLoadingHistory] = useState(false);
  const [currentModel, setCurrentModel] = useState("未连接");
  const [actualAgent, setActualAgent] = useState("general-chat");
  const [messages, setMessages] = useState([
    {
      id: createMessageId(),
      role: "assistant",
      text: INITIAL_ASSISTANT_TEXT,
      actualAgent: "general-chat",
    },
  ]);
  const [sessionList, setSessionList] = useState([]);
  const [activeSessionId, setActiveSessionId] = useState("");
  const [deletingSessionId, setDeletingSessionId] = useState("");
  const [feedbackMap, setFeedbackMap] = useState({});
  const [copiedMessageId, setCopiedMessageId] = useState("");


  const quickQuestions = useMemo(
    () => [
      "帮我解释一下什么是机器学习势函数",
      "帮我润色一段学术表达",
      "如何整理一份组会汇报提纲",
      "介绍一下 VASP 和 QE 的区别",
    ],
    []
  );

  const loadSessions = async (nextActiveId = null) => {
    const res = await api.get("/agents/sessions", {
      params: {
        agent: "general-chat",
        limit: 30,
      },
    });

    const sessions = res?.data?.sessions || [];
    setSessionList(sessions);

    if (nextActiveId) {
      setActiveSessionId(nextActiveId);
      localStorage.setItem("agent_session_general_chat_active", nextActiveId);
      return nextActiveId;
    }

    const savedActive = localStorage.getItem("agent_session_general_chat_active");
    const matched =
      sessions.find((s) => s.session_id === savedActive)?.session_id ||
      sessions[0]?.session_id ||
      "";

    if (matched) {
      setActiveSessionId(matched);
      localStorage.setItem("agent_session_general_chat_active", matched);
    }

    return matched;
  };

  const loadHistory = async (sessionId) => {
    if (!sessionId) {
      setMessages([
        {
          id: createMessageId(),
          role: "assistant",
          text: INITIAL_ASSISTANT_TEXT,
          actualAgent: "general-chat",
        },
      ]);
      return;
    }

    setLoadingHistory(true);

    try {
      const res = await api.get("/agents/history", {
        params: {
          agent: "general-chat",
          session_id: sessionId,
        },
      });

      const history = res?.data?.history || [];

      if (!history.length) {
        setMessages([
          {
            id: createMessageId(),
            role: "assistant",
            text: INITIAL_ASSISTANT_TEXT,
            actualAgent: "general-chat",
          },
        ]);
        return;
      }

      const rebuilt = history.map((item) => {
        if (item.role === "user") {
          return {
            id: item.message_id || createMessageId(),
            role: "user",
            text: item.content || "",
          };
        }

        const actualAgent = item.actual_agent || "general-chat";
        const answerType = item.answer_type || "text";
        const answerPayload = item.answer_payload || null;

        if (answerType === "structured" && answerPayload && typeof answerPayload === "object") {
          return {
            id: item.message_id || createMessageId(),
            role: "assistant",
            actualAgent,
            answer: answerPayload,
          };
        }

        return {
          id: item.message_id || createMessageId(),
          role: "assistant",
          actualAgent,
          text: item.content || "",
        };
      });

      setMessages(rebuilt);
    } catch (e) {
      console.error("load history failed:", e);
      setMessages([
        {
          id: createMessageId(),
          role: "assistant",
          text: INITIAL_ASSISTANT_TEXT,
          actualAgent: "general-chat",
        },
      ]);
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
            agent: "general-chat",
            session_id: newId,
            title: "新对话",
          });
          await loadSessions(newId);
          await loadHistory(newId);
        } else {
          await loadHistory(matched);
        }
      } catch (e) {
        console.error("init general chat sessions failed:", e);
      }
    })();
  }, []);

  const createNewSession = async () => {
    if (loading || loadingHistory) return;

    const newId = createLocalSessionId();

    try {
      await api.post("/agents/session/create", {
        agent: "general-chat",
        session_id: newId,
        title: "新对话",
      });

      await loadSessions(newId);

      setMessages([
        {
          id: createMessageId(),
          role: "assistant",
          text: INITIAL_ASSISTANT_TEXT,
          actualAgent: "general-chat",
        },
      ]);
      setInput("");
      setCurrentModel("未连接");
      setActualAgent("general-chat");
    } catch (e) {
      console.error("create session failed:", e);
    }
  };

  const switchSession = async (sessionId) => {
    if (!sessionId || loading) return;
    setActiveSessionId(sessionId);
    localStorage.setItem("agent_session_general_chat_active", sessionId);
    await loadHistory(sessionId);
  };

  const deleteOneSession = async (sessionId) => {
    if (!sessionId || loading) return;

    setDeletingSessionId(sessionId);

    try {
      await api.post("/agents/session/delete", {
        agent: "general-chat",
        session_id: sessionId,
      });

      const remaining = sessionList.filter((s) => s.session_id !== sessionId);

      if (activeSessionId === sessionId) {
        const nextId = remaining[0]?.session_id || "";
        setActiveSessionId(nextId);
        if (nextId) {
          localStorage.setItem("agent_session_general_chat_active", nextId);
          await loadSessions(nextId);
          await loadHistory(nextId);
        } else {
          localStorage.removeItem("agent_session_general_chat_active");
          await createNewSession();
        }
      } else {
        await loadSessions(activeSessionId);
      }
    } catch (e) {
      console.error("delete session failed:", e);
    } finally {
      setDeletingSessionId("");
    }
  };

  const clearSession = async () => {
    if (loading || !activeSessionId) return;

    try {
      await api.post("/agents/clear", {
        agent: "general-chat",
        session_id: activeSessionId,
      });
    } catch (e) {
      console.error("clear general chat failed:", e);
    } finally {
      setMessages([
        {
          id: createMessageId(),
          role: "assistant",
          text: INITIAL_ASSISTANT_TEXT,
          actualAgent: "general-chat",
        },
      ]);
      setInput("");
      await loadSessions(activeSessionId);
    }
  };

  const handleAsk = async (text) => {
    const question = String(text || input).trim();
    if (!question || loading || !activeSessionId) return;

    const nextUserMessage = {
      id: createMessageId(),
      role: "user",
      text: question,
    };
    setMessages((prev) => [...prev, nextUserMessage]);
    setInput("");
    setLoading(true);

    try {
      const nextMessagesForHistory = [...messages, nextUserMessage];
      const history = nextMessagesForHistory.map((item) => ({
        role: item.role,
        content: getMessagePlainText(item),
      }));

      const res = await apiLong.post("/agents/chat", {
        agent: "general-chat",
        message: question,
        session_id: activeSessionId,
        history,
      });

      const nextActualAgent = res?.data?.actual_agent || "general-chat";
      setCurrentModel(res?.data?.model || "未知模型");
      setActualAgent(nextActualAgent);

      const nextAnswerType = res?.data?.answer_type || "text";
      const nextAnswerPayload = res?.data?.answer_payload || null;

      const assistantMessage =
        nextAnswerType === "structured" && nextAnswerPayload
          ? {
              id: res?.data?.message_id || createMessageId(),
              role: "assistant",
              actualAgent: nextActualAgent,
              answer: nextAnswerPayload,
            }
          : {
              id: res?.data?.message_id || createMessageId(),
              role: "assistant",
              actualAgent: nextActualAgent,
              text: res.data.answer || "暂时没有返回内容。",
            }; 

      setMessages((prev) => [...prev, assistantMessage]);
      await loadSessions(activeSessionId);
    } catch (e) {
      console.error("general chat failed:", e);
      setMessages((prev) => [
        ...prev,
        {
          id: createMessageId(),
          role: "assistant",
          actualAgent: "general-chat",
          text: "通用大模型调用失败，请检查后端服务和 Ollama 是否已启动。",
        },
      ]);
    } finally {
      setLoading(false);
    }
  };

  const regenerateAnswer = async (assistantIndex) => {
    const msg = messages[assistantIndex];
    if (!msg?.id || loading || loadingHistory || !activeSessionId) return;

    setLoading(true);
    try {
      const res = await apiLong.post("/agents/message/regenerate", {
        agent: "general-chat",
        session_id: activeSessionId,
        message_id: msg.id,
      });

      const nextActualAgent = res?.data?.actual_agent || "general-chat";
      const nextAnswerType = res?.data?.answer_type || "text";
      const nextAnswerPayload = res?.data?.answer_payload || null;

      const newAssistant =
        nextAnswerType === "structured" && nextAnswerPayload
          ? {
              id: res?.data?.message_id || createMessageId(),
              role: "assistant",
              actualAgent: nextActualAgent,
              answer: nextAnswerPayload,
            }
          : {
              id: res?.data?.message_id || createMessageId(),
              role: "assistant",
              actualAgent: nextActualAgent,
              text: res?.data?.answer || "暂时没有返回内容。",
            };

      setMessages((prev) => {
        const next = [...prev];
        next[assistantIndex] = newAssistant;
        return next;
      });

      await loadSessions(activeSessionId);
    } catch (e) {
      console.error("regenerate failed:", e);
    } finally {
      setLoading(false);
    }
  };

  const submitFeedback = async (msg, value) => {
    if (!msg?.id || msg.role !== "assistant" || !activeSessionId) return;

    const nextValue = feedbackMap[msg.id] === value ? "cancel" : value;

    try {
      await api.post("/agents/message/feedback", {
        agent: "general-chat",
        session_id: activeSessionId,
        message_id: msg.id,
        feedback: nextValue,
      });

      setFeedbackMap((prev) => ({
        ...prev,
        [msg.id]: nextValue === "cancel" ? "" : nextValue,
      }));
    } catch (e) {
      console.error("submit feedback failed:", e);
    }
  };


  return (
    <AgentLayout
      currentPath="/dashboard/agents/general-chat"
      currentAgentKey="general-chat"
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
            background: "linear-gradient(135deg, #6d28d9 0%, #7c3aed 100%)",
            color: "#fff",
            padding: "20px 24px",
            marginBottom: 16,
            borderRadius: 24,
            boxShadow: "0 12px 32px rgba(124, 58, 237, 0.18)",
          }}
        >
          <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 10 }}>
            <Bot size={20} />
            <span style={{ fontSize: 14, fontWeight: 700, letterSpacing: 1 }}>GENERAL CHAT</span>
          </div>

          <h1 style={{ margin: 0, fontSize: 28 }}>通用大模型</h1>
          <p style={{ margin: "10px 0 0", color: "rgba(255,255,255,0.88)", lineHeight: 1.7 }}>
            适合开放式问答、解释说明、内容润色、总结归纳和思路整理。它比平台导览智能体更“能聊”。
          </p>

          <div
            style={{
              marginTop: 12,
              display: "flex",
              flexWrap: "wrap",
              gap: 10,
            }}
          >
            <div
              style={{
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

            <div
              style={{
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
              <Bot size={14} />
              实际调用：{actualAgent === "platform-guide" ? "平台导览智能体" : "通用大模型"}
            </div>
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
                background: "linear-gradient(135deg, #7c3aed 0%, #5b21b6 100%)",
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
                      border: active ? "1px solid #c4b5fd" : "1px solid #e5e7eb",
                      background: active ? "#faf5ff" : "#fff",
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
                          color: active ? "#6d28d9" : "#111827",
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
                        border: "1px solid #f3e8ff",
                        background: "#fff",
                        color: "#7c3aed",
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
              快速开始
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
                  border: "1px solid #f5d0fe",
                  background: "#faf5ff",
                  color: "#7c3aed",
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
              <div style={{ fontSize: 15, fontWeight: 700, color: "#111827" }}>常用跳转</div>

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
            </div>
          </aside>

          <section
            style={{
              background: "linear-gradient(180deg, #ffffff 0%, #faf7ff 100%)",
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
                  适合问：解释概念、润色表达、总结内容、整理提纲、一般性科研交流。
                </div>
              </div>

              <button
                type="button"
                onClick={clearSession}
                disabled={loading || loadingHistory}
                style={{
                  border: "1px solid #ede9fe",
                  background: "#faf5ff",
                  color: "#7c3aed",
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
                  "radial-gradient(circle at top, rgba(124,58,237,0.06), transparent 28%), #f8fafc",
                overflowY: "auto",
              }}
            >
              {loadingHistory ? (
                <Bubble role="assistant">
                  <div>正在加载历史对话，请稍等片刻...</div>
                </Bubble>
              ) : (
                messages.map((msg, idx) => (
                  <MessageItem
                    key={msg.id || idx}
                    msg={msg}
                    idx={idx}
                    navigate={navigate}
                    handleAsk={handleAsk}
                    copiedMessageId={copiedMessageId}
                    feedbackMap={feedbackMap}
                    setCopiedMessageId={setCopiedMessageId}
                    regenerateAnswer={regenerateAnswer}
                    submitFeedback={submitFeedback}
                  />
                ))
              )}

              {loading ? (
                <Bubble role="assistant">
                  <div>正在思考中，请稍等片刻...</div>
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
                  placeholder="输入你的问题，例如：帮我解释一下什么是第一性原理计算"
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
                      ? "linear-gradient(135deg, #c4b5fd 0%, #a78bfa 100%)"
                      : "linear-gradient(135deg, #7c3aed 0%, #5b21b6 100%)",
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
                      : "0 8px 18px rgba(124, 58, 237, 0.24)",
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
