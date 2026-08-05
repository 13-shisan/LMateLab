# services/scan_lock.py
from __future__ import annotations

import os
import time
import uuid
import hashlib
from dataclasses import dataclass
from typing import Optional

import redis


def _redis_client() -> redis.Redis:
    url = os.getenv("CELERY_BROKER_URL", "redis://127.0.0.1:6379/0")
    # 复用 broker 的 redis；也可以单独配 REDIS_URL
    return redis.Redis.from_url(url, decode_responses=True)


def _db_key(dbpath_str: str) -> str:
    # 用 db 路径 hash 成稳定 key，避免 key 太长/含特殊字符
    return hashlib.sha1(dbpath_str.encode("utf-8")).hexdigest()


def lock_key_for_db(dbpath_str: str) -> str:
    return f"vasp_scan:lock:{_db_key(dbpath_str)}"


def task_key_for_db(dbpath_str: str) -> str:
    return f"vasp_scan:task:{_db_key(dbpath_str)}"


_RELEASE_LUA = """
if redis.call("GET", KEYS[1]) == ARGV[1] then
  return redis.call("DEL", KEYS[1])
else
  return 0
end
"""


@dataclass(frozen=True)
class RedisLock:
    key: str
    token: str
    ttl_seconds: int


def acquire_scan_lock(dbpath_str: str, ttl_seconds: int = 60 * 30) -> Optional[RedisLock]:
    """
    用 SET NX EX 实现互斥锁。拿到锁返回 RedisLock，否则返回 None。
    ttl_seconds：防止 worker 崩溃导致死锁（到期自动释放）。
    """
    r = _redis_client()
    k = lock_key_for_db(dbpath_str)
    token = f"{uuid.uuid4()}:{time.time()}"
    ok = r.set(k, token, nx=True, ex=ttl_seconds)
    if not ok:
        return None
    return RedisLock(key=k, token=token, ttl_seconds=ttl_seconds)


def release_scan_lock(lock: RedisLock) -> bool:
    """用 Lua 脚本保证“只能释放自己拿到的锁”。"""
    r = _redis_client()
    released = r.eval(_RELEASE_LUA, 1, lock.key, lock.token)
    return bool(released)


def get_current_task_id(dbpath_str: str) -> Optional[str]:
    r = _redis_client()
    return r.get(task_key_for_db(dbpath_str))


def set_current_task_id(dbpath_str: str, task_id: str, ttl_seconds: int = 60 * 60) -> None:
    """
    记录当前 db 正在扫描的 task_id，便于去重复用。
    ttl 给长一点，避免扫描较久时 key 过期。
    """
    r = _redis_client()
    r.set(task_key_for_db(dbpath_str), task_id, ex=ttl_seconds)


def clear_current_task_id(dbpath_str: str, task_id: Optional[str] = None) -> None:
    """
    扫描结束后清除 task_id。
    如果提供 task_id，则只在匹配时清除（防止并发误删）。
    """
    r = _redis_client()
    k = task_key_for_db(dbpath_str)
    if task_id is None:
        r.delete(k)
        return
    val = r.get(k)
    if val == task_id:
        r.delete(k)
