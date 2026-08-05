# backend/services/agents/service.py
import os
import json
from typing import List, Dict, Any


from .registry import AGENT_REGISTRY
from .prompts import get_system_prompt
from .provider_ollama import OllamaProvider
from .memory import (
    load_history,
    save_history,
    clear_history,
    create_session,
    update_session_meta,
    list_sessions,
    delete_session,
    create_message_id,
    save_message_feedback,
    delete_message_feedback,
)

from .retriever import retrieve, format_retrieved_context


class AgentService:
    def __init__(self):
        self.provider_name = "ollama"
        self.ollama_base_url = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434")
        self.ollama_timeout = int(os.getenv("OLLAMA_TIMEOUT", "120"))
        self.default_model = os.getenv("OLLAMA_MODEL", "qwen2.5:7b")

    def _resolve_model(self, agent: str) -> str:
        conf = AGENT_REGISTRY.get(agent, {})
        model_env = conf.get("model_env")
        fallback_model = conf.get("fallback_model", self.default_model)

        if model_env:
            return os.getenv(model_env, fallback_model)

        return fallback_model

    def _validate_agent(self, agent: str):
        conf = AGENT_REGISTRY.get(agent)
        if not conf or not conf.get("enabled"):
            raise ValueError(f"Unknown or disabled agent: {agent}")
        return conf

    def _is_paper_query(self, message: str) -> bool:
        text = (message or "").strip().lower()
        if not text:
            return False

        paper_keywords = [
            "论文", "文献", "文章", "paper", "abstract", "introduction", "conclusion",
            "summary", "作者", "doi", "这篇文章", "这篇论文", "这篇文献",
            "讲了什么", "主要内容", "核心观点", "主要结论", "摘要是什么",
            "研究了什么", "研究内容", "工作内容", "文章内容", "论文内容",
            "title", "题目", "标题", "这篇", "前文这篇", "上面这篇",
            "文中", "前文", "该文", "该论文", "该文章",
            "what limits", "mobility", "electrons", "holes", "two dimensional",
            "jacs", "nature", "science", "adv mater", "advanced materials",
            "acs catalysis", "physical review", "npj",
        ]

        return any(k in text for k in paper_keywords)

    def _is_platform_guide_query(self, message: str) -> bool:
        text = (message or "").strip().lower()
        if not text:
            return False

        general_chat_patterns = [
            "什么是",
            "介绍一下",
            "解释一下",
            "区别",
            "原理",
            "怎么理解",
            "帮我解释",
            "帮我润色",
            "帮我总结",
            "帮我整理",
            "写一个",
            "写一段",
        ]

        if any(p in text for p in general_chat_patterns):
            return False

        explicit_platform_words = [
            "这个网站",
            "这个平台",
            "本平台",
            "平台里",
            "网站里",
            "页面",
            "入口",
            "模块",
            "功能",
            "去哪里点",
            "从哪里进",
            "在哪里看",
            "怎么进入",
            "怎么打开",
            "怎么查看",
            "怎么使用这个网站",
            "平台导览",
        ]

        platform_modules = [
            "服务器入口",
            "用户使用总览",
            "个人数据库",
            "全组数据库",
            "每日导读",
            "我的订阅",
            "文献库",
            "学术报告",
            "更新日志",
            "反馈与建议",
            "反馈",
            "issues",
            "changelog",
        ]

        navigation_verbs = [
            "进入",
            "打开",
            "跳转",
            "查看",
            "前往",
            "点哪里",
            "哪里看",
            "哪里进入",
            "怎么找",
        ]

        has_explicit_platform = any(k in text for k in explicit_platform_words)
        has_platform_module = any(k in text for k in platform_modules)
        has_navigation_verb = any(k in text for k in navigation_verbs)

        if has_explicit_platform:
            return True

        if has_platform_module and has_navigation_verb:
            return True

        strong_patterns = [
            "怎么看服务器使用情况",
            "怎么查看个人数据库",
            "怎么找文献",
            "怎么查看学术报告",
            "怎么反馈问题",
            "服务器信息在哪",
            "个人数据库在哪",
            "每日导读在哪",
            "反馈入口在哪",
        ]

        if any(p in text for p in strong_patterns):
            return True

        return False

    def _delegate_agent_if_needed(self, agent: str, message: str) -> str:
        if agent == "general-chat" and self._is_platform_guide_query(message):
            return "platform-guide"
        return agent

    def _build_session_title(self, message: str) -> str:
        title = (message or "").strip().replace("\n", " ")
        if len(title) > 18:
            title = title[:18] + "..."
        return title or "新对话"

    def _build_platform_answer_payload(self, question: str, answer: str):
        text = (question or "").strip().lower()

        payload = {
            "type": "text",
            "title": "平台相关问题",
            "content": answer,
            "path": None,
            "entries": [],
            "modules": [],
            "suggestions": [],
        }

        if "服务器" in text and any(k in text for k in ["怎么看", "怎么查看", "入口", "哪里看", "进入"]):
            payload.update({
                "type": "group",
                "title": "服务器信息",
                "content": answer,
                "entries": [
                    {
                        "name": "服务器信息",
                        "usage": "查看服务器概览、服务器详情和用户使用总览",
                        "path": "/dashboard/server-monitor",
                    }
                ],
            })
            return payload

        if "数据库" in text and any(k in text for k in ["怎么看", "怎么查看", "入口", "哪里看", "进入"]):
            payload.update({
                "type": "group",
                "title": "数据库",
                "content": answer,
                "entries": [
                    {
                        "name": "个人数据库",
                        "usage": "进入个人数据库入口，查看个人 VASP、QE/EPW 等任务数据",
                        "path": "/dashboard/db/personal",
                    }
                ],
            })
            return payload

        if any(k in text for k in ["文献", "每日导读", "我的订阅", "文献库"]) and any(
            k in text for k in ["怎么看", "怎么查看", "入口", "哪里看", "进入"]
        ):
            payload.update({
                "type": "group",
                "title": "文献推荐",
                "content": answer,
                "entries": [
                    {
                        "name": "每日导读",
                        "usage": "查看近期推荐文献",
                        "path": "/dashboard/papers/daily",
                    }
                ],
            })
            return payload

        if "学术报告" in text:
            payload.update({
                "type": "entry",
                "title": "学术报告",
                "content": answer,
                "path": "/dashboard/academic-reports",
            })
            return payload

        if "反馈" in text or "建议" in text or "报错" in text:
            payload.update({
                "type": "entry",
                "title": "反馈与建议",
                "content": answer,
                "path": "/dashboard/issues",
            })
            return payload

        if "更新日志" in text:
            payload.update({
                "type": "entry",
                "title": "平台更新日志",
                "content": answer,
                "path": "/dashboard/changelog",
            })
            return payload

        return payload

    def _retrieve_for_agent(self, actual_agent: str, message: str):
        if actual_agent == "platform-guide":
            return retrieve("platform", message, top_k=4)

        if self._is_paper_query(message):
            paper_items = retrieve("papers", message, top_k=6)
            if paper_items:
                return paper_items
            return retrieve("research", message, top_k=4)

        return retrieve("research", message, top_k=4)



    def _build_rag_system_prompt(
        self,
        actual_agent: str,
        base_prompt: str,
        message: str,
        retrieved_context: str,
    ) -> str:
        if not retrieved_context:
            return (
                f"{base_prompt}\n\n"
                "当前没有从本地知识库检索到可用内容。"
                "请基于通用知识回答，但不要声称你访问了外部数据库、实时网络或原始论文全文。"
            )

        if actual_agent == "platform-guide":
            return (
                f"{base_prompt}\n\n"
                "下面是从本地平台知识库中检索到的内容。"
                "请优先依据这些内容回答。"
                "如果内容已经足够，就不要说你无法访问平台或数据库。"
                "回答要尽量直接、清楚，并优先给出页面入口和操作说明。\n\n"
                f"{retrieved_context}"
            )

        if self._is_paper_query(message):
            return (
                f"{base_prompt}\n\n"
                "下面是从本地论文知识库中检索到的内容。"
                "请优先基于这些内容回答，不要说“我无法访问论文”或“我无法访问数据库”。"
                "如果当前上下文已经是同一篇论文的完整或大部分内容，请先概括这篇论文讲了什么，"
                "再根据用户要求摘录检索到的原文片段。"
                "如果用户要求“给出原文”，可以引用检索到的英文原文片段，但不要整篇无节制输出。"
                "优先摘录与摘要、引言、结论最相关的段落。"
                "不要编造未出现的实验数据、图号和精确结论。\n\n"
                f"{retrieved_context}"
            )



        return (
            f"{base_prompt}\n\n"
            "下面是从本地知识库中检索到的内容。"
            "请优先依据这些内容回答。"
            "不要虚构来源，也不要声称已访问外部数据库。"
            "如果检索内容不足，请明确说明是“根据当前检索到的内容”作出的回答。\n\n"
            f"{retrieved_context}"
        )
        
    def _extract_paper_root(self, source: str) -> str:
        """
        例如：
        papers/2024-AdvFunctMater-36339bf95214/full.md
        papers/2024-AdvFunctMater-36339bf95214/mineru/full.md
        都归一到：
        papers/2024-AdvFunctMater-36339bf95214
        """
        source = (source or "").strip()
        if not source.startswith("papers/"):
            return ""

        parts = source.split("/")
        if len(parts) >= 2:
            return "/".join(parts[:2])

        return ""


    def _select_primary_paper_root(self, items: List[Dict[str, Any]]) -> str:
        """
        从检索结果里选出最可能的主论文 root。
        策略：统计命中次数，次数相同则取最先出现的。
        """
        counts = {}
        first_index = {}

        for idx, item in enumerate(items):
            meta = item.get("metadata", {}) or {}
            source = meta.get("source", "")
            root = self._extract_paper_root(source)
            if not root:
                continue

            counts[root] = counts.get(root, 0) + 1
            if root not in first_index:
                first_index[root] = idx

        if not counts:
            return ""

        ranked = sorted(
            counts.items(),
            key=lambda x: (-x[1], first_index.get(x[0], 10**9))
        )
        return ranked[0][0]


    def _choose_best_source_within_root(self, items: List[Dict[str, Any]], paper_root: str) -> str:
        """
        在同一篇论文下，优先选择 full.md；
        如果没有 full.md，再选最先出现的 source。
        """
        candidates = []
        for idx, item in enumerate(items):
            meta = item.get("metadata", {}) or {}
            source = meta.get("source", "")
            if source.startswith(paper_root + "/"):
                candidates.append((idx, source))

        if not candidates:
            return ""

        for _, source in candidates:
            if source == f"{paper_root}/full.md":
                return source

        return candidates[0][1]


    def _load_all_chunks_for_source(self, target_source: str) -> List[Dict[str, Any]]:
        """
        从 processed/chunks_papers.jsonl 中读取某个 source 的全部 chunks。
        例如：
        papers/2024-AdvFunctMater-36339bf95214/full.md
        """
        if not target_source:
            return []

        from .rag_config import PROCESSED_DIR

        path = os.path.join(PROCESSED_DIR, "chunks_papers.jsonl")
        if not os.path.isfile(path):
            print(f"[AgentService] chunks file not found: {path}", flush=True)
            return []

        result = []
        try:
            with open(path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        item = json.loads(line)
                    except Exception:
                        continue

                    source = item.get("source", "")
                    chunk_type = item.get("chunk_type", "")
                    if source == target_source and chunk_type != "paper_metadata":
                        result.append({
                            "text": item.get("text", ""),
                            "metadata": {
                                "source": source,
                                "chunk_index": item.get("chunk_index", 0),
                                "domain": item.get("domain", "papers"),
                                "paper_id": item.get("paper_id", ""),
                                "title": item.get("title", ""),
                                "chunk_type": chunk_type,
                            },
                            "distance": None,
                        })

        except Exception as e:
            print(f"[AgentService] failed to load source={target_source} error={e}", flush=True)
            return []

        result.sort(key=lambda x: x.get("metadata", {}).get("chunk_index", 0))
        print(f"[AgentService] loaded full source={target_source}, chunks={len(result)}", flush=True)
        return result


    def _expand_paper_context_if_needed(
        self,
        actual_agent: str,
        message: str,
        retrieved_items: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """
        对论文问题：如果命中了某篇论文，则把该论文最佳 source 的所有 chunks 都加载出来，
        让模型基于整篇文章回答，而不是只看零散 top_k 片段。
        """
        if actual_agent == "platform-guide":
            return retrieved_items

        if not self._is_paper_query(message):
            return retrieved_items

        if not retrieved_items:
            return retrieved_items

        paper_root = self._select_primary_paper_root(retrieved_items)
        if not paper_root:
            return retrieved_items

        target_source = self._choose_best_source_within_root(retrieved_items, paper_root)
        if not target_source:
            return retrieved_items

        full_items = self._load_all_chunks_for_source(target_source)
        if full_items:
            print(
                f"[AgentService] expand context to full source={target_source} (paper_root={paper_root})",
                flush=True
            )
            return full_items

        return retrieved_items


    def chat(self, user_id: int, agent: str, message: str, history=None, session_id: str | None = None):
        self._validate_agent(agent)

        actual_agent = self._delegate_agent_if_needed(agent, message)
        self._validate_agent(actual_agent)

        model = self._resolve_model(actual_agent)
        provider = OllamaProvider(
            base_url=self.ollama_base_url,
            model=model,
            timeout=self.ollama_timeout,
        )

        system_prompt = get_system_prompt(actual_agent)

        retrieved_items = self._retrieve_for_agent(actual_agent, message)

        print(f"[AgentService.chat] agent={agent}, actual_agent={actual_agent}, model={model}", flush=True)
        print(f"[AgentService.chat] message={message}", flush=True)
        print(f"[AgentService.chat] retrieved_items={len(retrieved_items)}", flush=True)
        for i, item in enumerate(retrieved_items[:5], 1):
            meta = item.get("metadata", {}) or {}
            print(
                f"[AgentService.chat] hit#{i} source={meta.get('source')} distance={item.get('distance')}",
                flush=True
            )

        retrieved_items = self._expand_paper_context_if_needed(actual_agent, message, retrieved_items)

        print(f"[AgentService.chat] final_context_items={len(retrieved_items)}", flush=True)
        for i, item in enumerate(retrieved_items[:5], 1):
            meta = item.get("metadata", {}) or {}
            print(
                f"[AgentService.chat] final#{i} source={meta.get('source')} chunk_index={meta.get('chunk_index')}",
                flush=True
            )

        retrieved_context = format_retrieved_context(retrieved_items)


        system_prompt = self._build_rag_system_prompt(
            actual_agent=actual_agent,
            base_prompt=system_prompt,
            message=message,
            retrieved_context=retrieved_context,
        )

        if session_id:
            actual_history = load_history(user_id, agent, session_id)
            if not actual_history:
                create_session(user_id, agent, session_id, title=self._build_session_title(message))
                actual_history = []
        else:
            actual_history = history or []

        provider_history = []
        for item in actual_history:
            role = item.get("role")
            content = item.get("content", "")
            if role in ("user", "assistant") and content:
                provider_history.append({
                    "role": role,
                    "content": content,
                })

        answer = provider.chat(
            system_prompt=system_prompt,
            user_message=message,
            history=provider_history,
        )

        answer_type = "text"
        answer_payload = None
        assistant_message_id = None
        if actual_agent == "platform-guide":
            answer_type = "structured"
            answer_payload = self._build_platform_answer_payload(message, answer)

        if session_id:
            actual_history = self._ensure_message_ids(actual_history)

            user_message_id = create_message_id()
            assistant_message_id = create_message_id()

            if session_id:
                new_history = actual_history + [
                    {
                        "message_id": user_message_id,
                        "role": "user",
                        "content": message,
                    },
                    {
                        "message_id": assistant_message_id,
                        "role": "assistant",
                        "content": answer,
                        "actual_agent": actual_agent,
                        "answer_type": answer_type,
                        "answer_payload": answer_payload,
                    },
                ]
                save_history(user_id, agent, session_id, new_history)
                update_session_meta(user_id, agent, session_id, title=self._build_session_title(message))

        return {
            "agent": agent,
            "answer": answer,
            "provider": self.provider_name,
            "model": model,
            "session_id": session_id,
            "actual_agent": actual_agent,
            "answer_type": answer_type,
            "answer_payload": answer_payload,
            "message_id": assistant_message_id,
        }

    def clear(self, user_id: int, agent: str, session_id: str):
        self._validate_agent(agent)

        if not session_id:
            raise ValueError("session_id is required")

        clear_history(user_id, agent, session_id)

    def get_history(self, user_id: int, agent: str, session_id: str):
        self._validate_agent(agent)

        if not session_id:
            raise ValueError("session_id is required")

        history = load_history(user_id, agent, session_id)
        history = self._ensure_message_ids(history)
        save_history(user_id, agent, session_id, history)

        return {
            "agent": agent,
            "session_id": session_id,
            "history": history,
        }

    def get_sessions(self, user_id: int, agent: str, limit: int = 20):
        self._validate_agent(agent)
        return {
            "agent": agent,
            "sessions": list_sessions(user_id, agent, limit=limit),
        }

    def create_new_session(self, user_id: int, agent: str, session_id: str, title: str | None = None):
        self._validate_agent(agent)

        if not session_id:
            raise ValueError("session_id is required")

        create_session(user_id, agent, session_id, title=title or "新对话")
        return {
            "ok": True,
            "agent": agent,
            "session_id": session_id,
        }

    def delete_session(self, user_id: int, agent: str, session_id: str):
        self._validate_agent(agent)

        if not session_id:
            raise ValueError("session_id is required")

        delete_session(user_id, agent, session_id)
        return {
            "ok": True,
            "agent": agent,
            "session_id": session_id,
        }
        
    def _ensure_message_ids(self, history: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        changed = False
        result = []

        for item in history or []:
            if not isinstance(item, dict):
                continue

            obj = dict(item)
            if not obj.get("message_id"):
                obj["message_id"] = create_message_id()
                changed = True

            result.append(obj)

        return result
    
    def _find_message_index(self, history: List[Dict[str, Any]], message_id: str) -> int:
        for idx, item in enumerate(history or []):
            if item.get("message_id") == message_id:
                return idx
        return -1

    def _find_previous_user_message(self, history: List[Dict[str, Any]], assistant_index: int) -> Dict[str, Any] | None:
        for i in range(assistant_index - 1, -1, -1):
            item = history[i]
            if item.get("role") == "user":
                return item
        return None
    
    def submit_feedback(
        self,
        user_id: int,
        agent: str,
        session_id: str,
        message_id: str,
        feedback: str,
        reason_code: str | None = None,
        reason_text: str | None = None,
    ):
        self._validate_agent(agent)

        if not session_id:
            raise ValueError("session_id is required")
        if not message_id:
            raise ValueError("message_id is required")
        if feedback not in ("like", "dislike", "cancel"):
            raise ValueError("feedback must be one of: like, dislike, cancel")

        history = load_history(user_id, agent, session_id)
        history = self._ensure_message_ids(history)

        idx = self._find_message_index(history, message_id)
        if idx < 0:
            raise ValueError("message not found")

        message = history[idx]
        if message.get("role") != "assistant":
            raise ValueError("feedback only supports assistant message")

        if feedback == "cancel":
            delete_message_feedback(user_id, agent, session_id, message_id)
        else:
            save_message_feedback(
                user_id=user_id,
                agent=agent,
                session_id=session_id,
                message_id=message_id,
                feedback=feedback,
                reason_code=reason_code,
                reason_text=reason_text,
            )

        return {
            "ok": True,
            "agent": agent,
            "session_id": session_id,
            "message_id": message_id,
            "feedback": feedback,
        }
        
    def regenerate(
        self,
        user_id: int,
        agent: str,
        session_id: str,
        message_id: str,
    ):
        self._validate_agent(agent)

        if not session_id:
            raise ValueError("session_id is required")
        if not message_id:
            raise ValueError("message_id is required")

        actual_history = load_history(user_id, agent, session_id)
        actual_history = self._ensure_message_ids(actual_history)

        assistant_index = self._find_message_index(actual_history, message_id)
        if assistant_index < 0:
            raise ValueError("message not found")

        assistant_msg = actual_history[assistant_index]
        if assistant_msg.get("role") != "assistant":
            raise ValueError("regenerate target must be assistant message")

        user_msg = self._find_previous_user_message(actual_history, assistant_index)
        if not user_msg:
            raise ValueError("previous user message not found")

        message = (user_msg.get("content") or "").strip()
        if not message:
            raise ValueError("previous user message is empty")

        actual_agent = self._delegate_agent_if_needed(agent, message)
        self._validate_agent(actual_agent)

        model = self._resolve_model(actual_agent)
        provider = OllamaProvider(
            base_url=self.ollama_base_url,
            model=model,
            timeout=self.ollama_timeout,
        )

        system_prompt = get_system_prompt(actual_agent)

        retrieved_items = self._retrieve_for_agent(actual_agent, message)
        retrieved_items = self._expand_paper_context_if_needed(actual_agent, message, retrieved_items)
        retrieved_context = format_retrieved_context(retrieved_items)

        system_prompt = self._build_rag_system_prompt(
            actual_agent=actual_agent,
            base_prompt=system_prompt,
            message=message,
            retrieved_context=retrieved_context,
        )

        provider_history = []
        for item in actual_history[:assistant_index]:
            role = item.get("role")
            content = item.get("content", "")
            if role in ("user", "assistant") and content:
                provider_history.append({
                    "role": role,
                    "content": content,
                })

        if provider_history and provider_history[-1].get("role") == "user":
            provider_history = provider_history[:-1]


        answer = provider.chat(
            system_prompt=system_prompt,
            user_message=message,
            history=provider_history,
        )

        answer_type = "text"
        answer_payload = None
        if actual_agent == "platform-guide":
            answer_type = "structured"
            answer_payload = self._build_platform_answer_payload(message, answer)

        new_message_id = create_message_id()

        actual_history[assistant_index] = {
            "message_id": new_message_id,
            "role": "assistant",
            "content": answer,
            "actual_agent": actual_agent,
            "answer_type": answer_type,
            "answer_payload": answer_payload,
            "regenerated_from_message_id": message_id,
        }

        save_history(user_id, agent, session_id, actual_history)
        update_session_meta(user_id, agent, session_id)

        return {
            "ok": True,
            "agent": agent,
            "session_id": session_id,
            "message_id": new_message_id,
            "answer": answer,
            "provider": self.provider_name,
            "model": model,
            "actual_agent": actual_agent,
            "answer_type": answer_type,
            "answer_payload": answer_payload,
            "regenerated_from_message_id": message_id,
        }




