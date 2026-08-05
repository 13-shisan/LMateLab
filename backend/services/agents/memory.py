# backend/services/agents/memory.py
import json
import os
import time
import uuid
import redis
from typing import List, Dict, Any, Optional



REDIS_URL = os.getenv("CELERY_BROKER_URL", "redis://redis:6379/0")
redis_client = redis.from_url(REDIS_URL, decode_responses=True)

def create_message_id() -> str:
    return f"msg_{uuid.uuid4().hex[:16]}"

def build_feedback_key(user_id: int, agent: str, session_id: str, message_id: str) -> str:
    return f"agent:feedback:{user_id}:{agent}:{session_id}:{message_id}"

def build_feedback_index_key(user_id: int, agent: str) -> str:
    return f"agent:feedback_index:{user_id}:{agent}"

def build_chat_key(user_id: int, agent: str, session_id: str) -> str:
    return f"agent:chat:{user_id}:{agent}:{session_id}"

def build_session_meta_key(user_id: int, agent: str, session_id: str) -> str:
    return f"agent:session:{user_id}:{agent}:{session_id}"

def build_sessions_index_key(user_id: int, agent: str) -> str:
    return f"agent:sessions:{user_id}:{agent}"

def save_message_feedback(
    user_id: int,
    agent: str,
    session_id: str,
    message_id: str,
    feedback: str,
    reason_code: str | None = None,
    reason_text: str | None = None,
    ttl_seconds: int = 60 * 60 * 24 * 30,
):
    key = build_feedback_key(user_id, agent, session_id, message_id)
    index_key = build_feedback_index_key(user_id, agent)
    now_ts = int(time.time())

    payload = {
        "user_id": user_id,
        "agent": agent,
        "session_id": session_id,
        "message_id": message_id,
        "feedback": feedback,
        "reason_code": reason_code or "",
        "reason_text": reason_text or "",
        "created_at": now_ts,
        "updated_at": now_ts,
    }

    redis_client.set(key, json.dumps(payload, ensure_ascii=False), ex=ttl_seconds)
    redis_client.zadd(index_key, {f"{session_id}:{message_id}": now_ts})

def load_message_feedback(user_id: int, agent: str, session_id: str, message_id: str) -> Dict[str, Any] | None:
    key = build_feedback_key(user_id, agent, session_id, message_id)
    raw = redis_client.get(key)
    if not raw:
        return None
    try:
        data = json.loads(raw)
        if isinstance(data, dict):
            return data
    except Exception:
        pass
    return None

def delete_message_feedback(user_id: int, agent: str, session_id: str, message_id: str):
    key = build_feedback_key(user_id, agent, session_id, message_id)
    redis_client.delete(key)

def load_history(user_id: int, agent: str, session_id: str) -> List[Dict[str, Any]]:
    key = build_chat_key(user_id, agent, session_id)
    raw = redis_client.get(key)
    if not raw:
        return []

    try:
        data = json.loads(raw)
        if isinstance(data, list):
            return data
        return []
    except Exception:
        return []


def save_history(
    user_id: int,
    agent: str,
    session_id: str,
    history: List[Dict[str, Any]],
    ttl_seconds: int = 60 * 60 * 24 * 7,
):
    key = build_chat_key(user_id, agent, session_id)
    redis_client.set(key, json.dumps(history, ensure_ascii=False), ex=ttl_seconds)


def clear_history(user_id: int, agent: str, session_id: str):
    key = build_chat_key(user_id, agent, session_id)
    redis_client.delete(key)


def create_session(
    user_id: int,
    agent: str,
    session_id: str,
    title: Optional[str] = None,
    ttl_seconds: int = 60 * 60 * 24 * 7,
):
    now_ts = int(time.time())
    meta = {
        "session_id": session_id,
        "agent": agent,
        "user_id": user_id,
        "title": title or "新对话",
        "created_at": now_ts,
        "updated_at": now_ts,
    }

    meta_key = build_session_meta_key(user_id, agent, session_id)
    index_key = build_sessions_index_key(user_id, agent)

    redis_client.set(meta_key, json.dumps(meta, ensure_ascii=False), ex=ttl_seconds)
    redis_client.zadd(index_key, {session_id: now_ts})


def update_session_meta(
    user_id: int,
    agent: str,
    session_id: str,
    title: Optional[str] = None,
    ttl_seconds: int = 60 * 60 * 24 * 7,
):
    meta_key = build_session_meta_key(user_id, agent, session_id)
    index_key = build_sessions_index_key(user_id, agent)

    raw = redis_client.get(meta_key)
    now_ts = int(time.time())

    if raw:
        try:
            meta = json.loads(raw)
            if not isinstance(meta, dict):
                meta = {}
        except Exception:
            meta = {}
    else:
        meta = {}

    meta.setdefault("session_id", session_id)
    meta.setdefault("agent", agent)
    meta.setdefault("user_id", user_id)
    meta.setdefault("created_at", now_ts)
    meta["updated_at"] = now_ts

    if title:
        meta["title"] = title
    else:
        meta.setdefault("title", "新对话")

    redis_client.set(meta_key, json.dumps(meta, ensure_ascii=False), ex=ttl_seconds)
    redis_client.zadd(index_key, {session_id: now_ts})


def list_sessions(user_id: int, agent: str, limit: int = 20) -> List[Dict[str, Any]]:
    index_key = build_sessions_index_key(user_id, agent)
    session_ids = redis_client.zrevrange(index_key, 0, max(limit - 1, 0))

    results = []
    for session_id in session_ids:
        meta_key = build_session_meta_key(user_id, agent, session_id)
        raw = redis_client.get(meta_key)
        if not raw:
            continue
        try:
            meta = json.loads(raw)
            if isinstance(meta, dict):
                results.append(meta)
        except Exception:
            continue

    return results


def delete_session(user_id: int, agent: str, session_id: str):
    chat_key = build_chat_key(user_id, agent, session_id)
    meta_key = build_session_meta_key(user_id, agent, session_id)
    index_key = build_sessions_index_key(user_id, agent)

    pipe = redis_client.pipeline()
    pipe.delete(chat_key)
    pipe.delete(meta_key)
    pipe.zrem(index_key, session_id)
    pipe.execute()

