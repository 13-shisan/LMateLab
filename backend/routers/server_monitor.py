from fastapi import APIRouter, BackgroundTasks, Depends, Query
from pathlib import Path
import fcntl
import json
import os
import time
from datetime import datetime, timedelta, timezone
from auth import get_current_user
from routers.server_monitor_config import ALLOWED_SERVERS
from routers.server_monitor_paths import (
    get_history_dir,
    get_status_file,
    get_user_limits_file,
)


router = APIRouter(
    prefix="/server-monitor",
    tags=["server-monitor"],
    dependencies=[Depends(get_current_user)],
)

SERVER_MONITOR_BASE_DIR = Path(
    os.getenv(
        "SERVER_MONITOR_BASE_DIR",
        "/app/var/artifacts/server_monitor"
    )
)
SERVER_MONITOR_CACHE_DIR = Path(
    os.getenv(
        "SERVER_MONITOR_CACHE_DIR",
        "/app/var/tmp/server-monitor",
    )
)
USERS_OVERVIEW_CACHE_TTL_SECONDS = {
    7: 15 * 60,
    30: 30 * 60,
    90: 6 * 60 * 60,
    365: 24 * 60 * 60,
}

DEFAULT_SERVER_NAME = os.getenv("SERVER_MONITOR_DEFAULT_SERVER", "Dell")

SERVER_DISPLAY_NAMES = {
    "Dell": "Dell服务器",
    "Dell-GPU": "4090服务器",
    "Dawn4": "Dawn4",
    "Dawn5": "Dawn5",
    "Sugon": "曙光服务器",
    "Jingzhun-xjwu": "精准平台-xjwu",
    "Jingzhun-jbwu": "精准平台-jbwu",
    "Jingzhun-GPU": "精准平台-GPU",
    "Shuangyiliu-huayuan": "双一流化院",
    "Shuangyiliu-HFNL-xjwu": "双一流微尺度-xjwu",
    "Shuangyiliu-HFNL-hflv": "双一流微尺度-hflv",
    "SCNet":"合肥超算",
    "Wuxi":"无锡超算",
    "Dongfang-xjwu":"东方超算-xjwu",
    "Dongfang-yang4":"东方超算-yang4"
}

USER_ALIAS_MAP = {
    "plyf": "李毅凡",
    "lyf": "李毅凡",

    "zhangwh": "zhangwh",
    "whzhang": "zhangwh",

    "pwjb": "吴佳宝",
    "wjb": "吴佳宝",

    "pzhangka":"张凯",
    "pzhangkai":"张凯",

    "sunmiao":"孙淼",
    "psunmiao":"孙淼",

    "bpf":"白鹏飞",

    "hflv":"吕海峰",

    "pcheyx":"车沂轩",
    "yxche":"车沂轩",

    "plil":"李朗",

    "pliuyd":"刘玉牒",

    "pwjx":"汪俊翔",

    "pwyt":"吴豫婷",
    "wyt":"吴豫婷",

    "pzhangshuo":"张硕",

    "xpb":"徐培博",
    
    "ll":"李朗",
    "lil":"李朗",
}

def ensure_valid_server_name(server_name: str):
    if server_name not in ALLOWED_SERVERS:
        raise HTTPException(status_code=404, detail=f"unknown server: {server_name}")
    
def get_server_display_name(server_name: str) -> str:
    return SERVER_DISPLAY_NAMES.get(server_name, server_name)

def normalize_user_name(user_name: str) -> str:
    text = str(user_name or "").strip()
    if not text:
        return ""

    key = text.lower()
    return USER_ALIAS_MAP.get(key, text)

def load_json_file(file_path: Path):
    with file_path.open("r", encoding="utf-8") as f:
        return json.load(f)


def load_status_json(server_name: str):
    ensure_valid_server_name(server_name)

    status_file = get_status_file(SERVER_MONITOR_BASE_DIR, server_name)

    if not status_file.exists():
        raise HTTPException(
            status_code=404,
            detail=f"status file not found for server '{server_name}': {status_file}"
        )

    try:
        data = load_json_file(status_file)
        data["server_name"] = server_name
        data["display_name"] = get_server_display_name(server_name)
        return data
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"failed to read status file for server '{server_name}': {e}"
        )


def load_user_limits_json(server_name: str):
    ensure_valid_server_name(server_name)

    file_path = get_user_limits_file(SERVER_MONITOR_BASE_DIR, server_name)

    if not file_path.exists():
        raise HTTPException(
            status_code=404,
            detail=f"user limits file not found for server '{server_name}': {file_path}"
        )

    try:
        data = load_json_file(file_path)

        raw_users = data.get("users", []) or []
        normalized_users = []

        for item in raw_users:
            queues = item.get("queues", []) or []

            # 兼容老字段 default_queue
            available_queues = item.get("available_queues")
            if available_queues is None:
                default_queue = item.get("default_queue")
                if isinstance(default_queue, list):
                    available_queues = default_queue
                elif default_queue:
                    available_queues = [default_queue]
                else:
                    available_queues = [q.get("queue") for q in queues if q.get("queue")]

            normalized_users.append({
                "user": item.get("user"),
                "enabled": bool(item.get("enabled", True)),
                "available_queues": available_queues or [],
                "queues": queues,
                "global_limits": {
                    "max_total_running_jobs": (item.get("global_limits") or {}).get("max_total_running_jobs"),
                    "max_total_queued_jobs": (item.get("global_limits") or {}).get("max_total_queued_jobs"),
                    "max_total_nodes": (item.get("global_limits") or {}).get("max_total_nodes"),
                    "max_total_cores": (item.get("global_limits") or {}).get("max_total_cores"),
                    "max_total_gpus": (item.get("global_limits") or {}).get("max_total_gpus"),
                },
                "remark": item.get("remark", ""),
            })

        return {
            "server_name": data.get("server_name", server_name),
            "display_name": get_server_display_name(server_name),
            "updated_at": data.get("updated_at"),
            "source": data.get("source", "unknown"),
            "reviewed": bool(data.get("reviewed", False)),
            "reviewed_by": data.get("reviewed_by"),
            "reviewed_at": data.get("reviewed_at"),
            "description": data.get("description", ""),
            "users": normalized_users,
        }
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"failed to read user limits file for server '{server_name}': {e}"
        )


def parse_iso_time(text: str):
    if not text:
        return None
    try:
        return datetime.fromisoformat(text)
    except Exception:
        return None


def parse_range_to_days(range_text: str) -> int:
    mapping = {
        "7d": 7,
        "30d": 30,
        "90d": 90,
        "365d": 365,
    }
    return mapping.get(range_text, 7)


def safe_extract_server_summary(server_name: str, status_file: Path):
    summary = {
        "name": server_name,
        "display_name": get_server_display_name(server_name),
        "has_data": False,
        "status_file": str(status_file),
        "updated_at": None,
        "host": None,
        "scheduler_type": None,
        "node_total": 0,
        "node_busy": 0,
        "node_free": 0,
        "usage_ratio": None,
        "queues": [],
        "gpu_available": False,
        "gpu_total": 0,
        "gpu_busy": 0,
        "gpu_idle": 0,
    }

    if not status_file.exists():
        return summary

    summary["has_data"] = True

    try:
        stat = status_file.stat()
        summary["updated_at"] = datetime.fromtimestamp(stat.st_mtime).isoformat()
    except Exception:
        summary["updated_at"] = None

    try:
        data = load_json_file(status_file)

        host = data.get("host", {}) or {}
        scheduler = data.get("scheduler", {}) or {}
        overview = data.get("overview", {}) or {}
        nodes = scheduler.get("nodes", {}) or {}
        queue_stats = scheduler.get("queue_stats", []) or []
        gpu = overview.get("gpu", {}) or {}

        node_total = nodes.get("total", 0) or 0
        node_busy = nodes.get("busy", 0) or 0
        node_free = nodes.get("free", 0) or 0

        queues = []
        for item in queue_stats:
            q = item.get("queue")
            if q:
                queues.append(q)

        seen = set()
        unique_queues = []
        for q in queues:
            if q not in seen:
                seen.add(q)
                unique_queues.append(q)

        usage_ratio = None
        if node_total > 0:
            usage_ratio = node_busy / node_total

        summary.update({
            "host": host.get("hostname"),
            "scheduler_type": scheduler.get("type"),
            "node_total": node_total,
            "node_busy": node_busy,
            "node_free": node_free,
            "usage_ratio": usage_ratio,
            "queues": unique_queues,
            "gpu_available": bool(gpu.get("available", False)),
            "gpu_total": gpu.get("total", 0) or 0,
            "gpu_busy": gpu.get("busy", 0) or 0,
            "gpu_idle": gpu.get("idle", 0) or 0,
        })

        return summary

    except Exception:
        return summary


def iter_history_files_in_range(server_name: str, days: int):
    history_dir = get_history_dir(SERVER_MONITOR_BASE_DIR, server_name)
    if not history_dir.exists():
        return []

    now = datetime.now(timezone.utc).astimezone()
    cutoff = now - timedelta(days=days)

    candidate_files = list(history_dir.glob("*.json"))
    for date_dir in history_dir.iterdir():
        if not date_dir.is_dir():
            continue
        try:
            snapshot_date = datetime.strptime(date_dir.name, "%Y-%m-%d").date()
        except ValueError:
            continue
        if cutoff.date() <= snapshot_date <= now.date():
            candidate_files.extend(date_dir.glob("*.json"))

    files = []
    for file_path in candidate_files:
        try:
            data = load_json_file(file_path)
            updated_at = parse_iso_time(data.get("updated_at"))
            if updated_at and updated_at >= cutoff:
                files.append((updated_at, file_path, data))
        except Exception:
            continue

    files.sort(key=lambda x: x[0])
    return files


def parse_nodes_from_job(job: dict):
    """
    尽量从不同调度器字段提取节点名列表
    """
    nodes = []

    node_text = job.get("node") or job.get("exec_host") or job.get("node_or_reason") or ""
    if not node_text:
        return nodes

    text = str(node_text)

    # PBS exec_host 可能是 node01/0+node01/1
    if "/" in text or "+" in text:
        parts = text.replace("+", ",").split(",")
        for part in parts:
            name = part.split("/", 1)[0].strip()
            if name and "(" not in name and ")" not in name:
                nodes.append(name)
    else:
        # Slurm 节点列表先粗略按逗号拆；复杂 bracket 展开暂时不在这里做
        for part in text.split(","):
            name = part.strip()
            if name and "(" not in name and ")" not in name:
                nodes.append(name)

    # 去重
    dedup = []
    seen = set()
    for n in nodes:
        if n not in seen:
            seen.add(n)
            dedup.append(n)

    return dedup

def pick_most_common_name(counter_map: dict):
    if not counter_map:
        return None
    items = sorted(counter_map.items(), key=lambda x: (-x[1], x[0]))
    return items[0][0]

def build_users_overview(days: int):
    realtime_user_map = {}
    history_user_map = {}
    realtime_server_summaries = []

    # ==========
    # 实时：基于各服务器 status.json
    # ==========
    for server_name in ALLOWED_SERVERS:
        status_file = get_status_file(SERVER_MONITOR_BASE_DIR, server_name)
        if not status_file.exists():
            continue

        try:
            data = load_json_file(status_file)
        except Exception:
            continue

        display_name = get_server_display_name(server_name)
        scheduler = data.get("scheduler", {}) or {}
        jobs = scheduler.get("jobs", []) or []
        updated_at = data.get("updated_at")

        server_running_users = set()
        server_queued_users = set()

        for job in jobs:
            raw_user = str(job.get("user") or "").strip()
            user = normalize_user_name(raw_user)
            if not user:
                continue

            state = str(job.get("state") or "").upper()
            queue = job.get("queue") or job.get("partition") or "unknown"
            job_id = str(job.get("job_id") or "").strip() or None

            rec = realtime_user_map.setdefault(user, {
                "user": user,
                "server_count": 0,
                "servers": {},
                "running_jobs": 0,
                "queued_jobs": 0,
                "total_jobs": 0,
                "last_seen_at": None,
            })

            if server_name not in rec["servers"]:
                rec["servers"][server_name] = {
                    "server_name": server_name,
                    "display_name": display_name,
                    "running_jobs": 0,
                    "queued_jobs": 0,
                    "total_jobs": 0,
                    "queues": set(),
                    "job_ids": set(),
                    "updated_at": updated_at,
                }

            item = rec["servers"][server_name]
            item["total_jobs"] += 1
            rec["total_jobs"] += 1

            if queue:
                item["queues"].add(queue)

            if job_id:
                item["job_ids"].add(job_id)

            if state in ("R", "RUNNING"):
                item["running_jobs"] += 1
                rec["running_jobs"] += 1
                server_running_users.add(user)
            elif state in ("Q", "PENDING"):
                item["queued_jobs"] += 1
                rec["queued_jobs"] += 1
                server_queued_users.add(user)

            if updated_at:
                rec["last_seen_at"] = updated_at

        realtime_server_summaries.append({
            "server_name": server_name,
            "display_name": display_name,
            "running_user_count": len(server_running_users),
            "queued_user_count": len(server_queued_users),
            "total_user_count": len(server_running_users | server_queued_users),
            "updated_at": updated_at,
        })

    realtime_users = []
    for user, rec in realtime_user_map.items():
        server_items = []
        for _, item in rec["servers"].items():
            server_items.append({
                "server_name": item["server_name"],
                "display_name": item["display_name"],
                "running_jobs": item["running_jobs"],
                "queued_jobs": item["queued_jobs"],
                "total_jobs": item["total_jobs"],
                "queues": sorted(list(item["queues"])),
                "job_count": len(item["job_ids"]) if item["job_ids"] else item["total_jobs"],
                "updated_at": item["updated_at"],
            })

        server_items.sort(key=lambda x: (-x["total_jobs"], x["display_name"]))

        realtime_users.append({
            "user": user,
            "server_count": len(server_items),
            "running_jobs": rec["running_jobs"],
            "queued_jobs": rec["queued_jobs"],
            "total_jobs": rec["total_jobs"],
            "last_seen_at": rec["last_seen_at"],
            "servers": server_items,
        })

    realtime_users.sort(key=lambda x: (-x["total_jobs"], -x["server_count"], x["user"]))

    # ==========
    # 历史：基于各服务器 history/*.json
    # ==========
    for server_name in ALLOWED_SERVERS:
        display_name = get_server_display_name(server_name)
        samples = iter_history_files_in_range(server_name, days)

        latest_job_map = {}
        for updated_at, _, data in samples:
            scheduler = data.get("scheduler", {}) or {}
            jobs = scheduler.get("jobs", []) or []

            for job in jobs:
                job_id = str(job.get("job_id") or "").strip()
                if not job_id:
                    continue

                raw_user = str(job.get("user") or "").strip()
                user = normalize_user_name(raw_user)
                if not user:
                    continue

                queue = job.get("queue") or job.get("partition") or "unknown"
                state = str(job.get("state") or "").upper()

                latest_job_map[job_id] = {
                    "job_id": job_id,
                    "user": user,
                    "queue": queue,
                    "state": state,
                    "updated_at": updated_at.isoformat(),
                }

        server_user_counter = {}

        for _, job in latest_job_map.items():
            user = job["user"]
            queue = job["queue"]

            rec = history_user_map.setdefault(user, {
                "user": user,
                "server_count": 0,
                "total_jobs": 0,
                "servers": {},
                "last_seen_at": None,
            })

            if server_name not in rec["servers"]:
                rec["servers"][server_name] = {
                    "server_name": server_name,
                    "display_name": display_name,
                    "total_jobs": 0,
                    "queues": {},
                    "last_seen_at": None,
                }

            item = rec["servers"][server_name]
            item["total_jobs"] += 1
            item["queues"][queue] = item["queues"].get(queue, 0) + 1
            item["last_seen_at"] = job["updated_at"]

            rec["total_jobs"] += 1
            rec["last_seen_at"] = job["updated_at"]

            server_user_counter[user] = server_user_counter.get(user, 0) + 1

        # 这里只是为了让后面 overview 更容易算，也顺手可用于调试
        _ = server_user_counter

    history_users = []
    for user, rec in history_user_map.items():
        server_items = []
        for _, item in rec["servers"].items():
            server_items.append({
                "server_name": item["server_name"],
                "display_name": item["display_name"],
                "total_jobs": item["total_jobs"],
                "primary_queue": pick_most_common_name(item["queues"]),
                "last_seen_at": item["last_seen_at"],
            })

        server_items.sort(key=lambda x: (-x["total_jobs"], x["display_name"]))

        history_users.append({
            "user": user,
            "server_count": len(server_items),
            "total_jobs": rec["total_jobs"],
            "last_seen_at": rec["last_seen_at"],
            "servers": server_items,
        })

    history_users.sort(key=lambda x: (-x["total_jobs"], -x["server_count"], x["user"]))

    # ==========
    # 汇总 overview
    # ==========
    realtime_active_server_names = set()
    for item in realtime_server_summaries:
        if item["total_user_count"] > 0:
            realtime_active_server_names.add(item["server_name"])

    history_active_server_names = set()
    for item in history_users:
        for s in item["servers"]:
            history_active_server_names.add(s["server_name"])

    return {
        "range": f"{days}d",
        "realtime": {
            "overview": {
                "active_user_count": len(realtime_users),
                "active_server_count": len(realtime_active_server_names),
                "total_running_jobs": sum(x["running_jobs"] for x in realtime_users),
                "total_queued_jobs": sum(x["queued_jobs"] for x in realtime_users),
            },
            "servers": sorted(realtime_server_summaries, key=lambda x: (-x["total_user_count"], x["display_name"])),
            "users": realtime_users,
        },
        "history": {
            "overview": {
                "active_user_count": len(history_users),
                "active_server_count": len(history_active_server_names),
                "total_unique_jobs": sum(x["total_jobs"] for x in history_users),
            },
            "users": history_users,
        },
    }


def get_users_overview_cache_path(days: int, cache_dir=None) -> Path:
    root = Path(cache_dir) if cache_dir is not None else SERVER_MONITOR_CACHE_DIR
    return root / f"users-overview-{days}d.json"


def load_users_overview_cache(days: int, cache_dir=None):
    cache_path = get_users_overview_cache_path(days, cache_dir)
    if not cache_path.is_file():
        return None
    try:
        data = load_json_file(cache_path)
        age_seconds = max(0, time.time() - cache_path.stat().st_mtime)
        ttl_seconds = USERS_OVERVIEW_CACHE_TTL_SECONDS.get(days, 15 * 60)
        return data, age_seconds <= ttl_seconds
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return None


def refresh_users_overview_cache(days: int, cache_dir=None, builder=None):
    cache_path = get_users_overview_cache_path(days, cache_dir)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = cache_path.with_suffix(f"{cache_path.suffix}.lock")
    build = builder or build_users_overview

    with lock_path.open("a+", encoding="utf-8") as lock_file:
        try:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            cached = load_users_overview_cache(days, cache_dir)
            if cached is not None:
                return cached[0]
            raise RuntimeError(f"users overview cache refresh is already running: {days}d")

        data = build(days)
        temp_path = cache_path.with_name(
            f".{cache_path.name}.{os.getpid()}.tmp"
        )
        try:
            temp_path.write_text(
                json.dumps(data, ensure_ascii=False, separators=(",", ":")),
                encoding="utf-8",
            )
            os.replace(temp_path, cache_path)
        finally:
            temp_path.unlink(missing_ok=True)
        return data


def get_users_overview_response(
    days: int,
    schedule_refresh,
    cache_dir=None,
    builder=None,
):
    build = builder or build_users_overview
    cached = load_users_overview_cache(days, cache_dir)
    if cached is not None:
        data, is_fresh = cached
        if not is_fresh:
            schedule_refresh(
                refresh_users_overview_cache,
                days,
                cache_dir,
                build,
            )
        return data
    return refresh_users_overview_cache(days, cache_dir, build)



def aggregate_usage(server_name: str, days: int):
    samples = iter_history_files_in_range(server_name, days)

    if not samples:
        return {
            "server_name": server_name,
            "display_name": get_server_display_name(server_name),
            "range": f"{days}d",
            "sample_count": 0,
            "time_start": None,
            "time_end": None,
            "overview": {
                "avg_node_usage_ratio": None,
                "peak_node_usage_ratio": None,
                "avg_running_jobs": None,
                "peak_running_jobs": None,
                "avg_queued_jobs": None,
                "peak_queued_jobs": None,
                "active_user_count": 0,
                "total_unique_jobs": 0,
            },
            "user_stats": [],
            "node_stats": [],
            "queue_stats": [],
            "timeline": [],
        }

    total_node_ratio = 0.0
    node_ratio_count = 0
    peak_node_ratio = 0.0

    total_running_jobs = 0
    peak_running_jobs = 0

    total_queued_jobs = 0
    peak_queued_jobs = 0

    timeline = []

    # 每个 job_id 在时间范围内只算一个唯一任务
    latest_job_map = {}

    for updated_at, _, data in samples:
        overview = data.get("overview", {}) or {}
        scheduler = data.get("scheduler", {}) or {}
        jobs = scheduler.get("jobs", []) or []

        node_total = overview.get("node_total", 0) or 0
        node_busy = overview.get("node_busy", 0) or 0

        node_ratio = None
        if node_total > 0:
            node_ratio = node_busy / node_total
            total_node_ratio += node_ratio
            node_ratio_count += 1
            peak_node_ratio = max(peak_node_ratio, node_ratio)

        running_jobs = 0
        queued_jobs = 0

        for job in jobs:
            state = str(job.get("state") or "").upper()
            if state in ("R", "RUNNING"):
                running_jobs += 1
            elif state in ("Q", "PENDING"):
                queued_jobs += 1

        total_running_jobs += running_jobs
        total_queued_jobs += queued_jobs
        peak_running_jobs = max(peak_running_jobs, running_jobs)
        peak_queued_jobs = max(peak_queued_jobs, queued_jobs)

        timeline.append({
            "time": updated_at.isoformat(),
            "node_usage_ratio": node_ratio,
            "running_jobs": running_jobs,
            "queued_jobs": queued_jobs,
            "total_jobs": len(jobs),
        })

        # 每个 job 保留最后一次看到的信息
        for job in jobs:
            job_id = str(job.get("job_id") or "").strip()
            if not job_id:
                continue

            user = job.get("user") or "unknown"
            queue = job.get("queue") or job.get("partition") or "unknown"
            node_names = parse_nodes_from_job(job)
            state = str(job.get("state") or "").upper()

            latest_job_map[job_id] = {
                "job_id": job_id,
                "user": user,
                "queue": queue,
                "nodes": node_names,
                "latest_state": state,
                "latest_seen_at": updated_at.isoformat(),
            }

    total_unique_jobs = len(latest_job_map)

    user_map = {}
    node_map = {}
    queue_map = {}
    active_users = set()

    for _, job in latest_job_map.items():
        user = job["user"]
        queue = job["queue"]
        nodes = job.get("nodes") or []

        active_users.add(user)

        # 用户统计：总任务数 + 最常使用队列 + 涉及节点数
        if user not in user_map:
            user_map[user] = {
                "user": user,
                "total_jobs": 0,
                "queue_counter": {},
                "node_set": set(),
            }

        user_map[user]["total_jobs"] += 1
        user_map[user]["queue_counter"][queue] = user_map[user]["queue_counter"].get(queue, 0) + 1
        for node_name in nodes:
            user_map[user]["node_set"].add(node_name)

        # 节点统计：总任务数 + 最常对应队列
        for node_name in nodes:
            if node_name not in node_map:
                node_map[node_name] = {
                    "node": node_name,
                    "total_jobs": 0,
                    "queue_counter": {},
                }

            node_map[node_name]["total_jobs"] += 1
            node_map[node_name]["queue_counter"][queue] = node_map[node_name]["queue_counter"].get(queue, 0) + 1

        # 队列统计：总任务数 + 活跃用户数 + 占比
        if queue not in queue_map:
            queue_map[queue] = {
                "queue": queue,
                "total_jobs": 0,
                "users": set(),
            }

        queue_map[queue]["total_jobs"] += 1
        queue_map[queue]["users"].add(user)

    user_stats = []
    for _, item in user_map.items():
        user_stats.append({
            "user": item["user"],
            "total_jobs": item["total_jobs"],
            "primary_queue": pick_most_common_name(item["queue_counter"]),
            "node_count": len(item["node_set"]),
            "job_ratio": round(item["total_jobs"] / total_unique_jobs, 4) if total_unique_jobs else 0,
        })

    user_stats.sort(key=lambda x: (-x["total_jobs"], x["user"]))

    node_stats = []
    for _, item in node_map.items():
        node_stats.append({
            "node": item["node"],
            "total_jobs": item["total_jobs"],
            "primary_queue": pick_most_common_name(item["queue_counter"]),
            "job_ratio": round(item["total_jobs"] / total_unique_jobs, 4) if total_unique_jobs else 0,
        })

    node_stats.sort(key=lambda x: (-x["total_jobs"], x["node"]))

    final_queue_stats = []
    for _, item in queue_map.items():
        final_queue_stats.append({
            "queue": item["queue"],
            "total_jobs": item["total_jobs"],
            "active_users": len(item["users"]),
            "job_ratio": round(item["total_jobs"] / total_unique_jobs, 4) if total_unique_jobs else 0,
        })

    final_queue_stats.sort(key=lambda x: (-x["total_jobs"], x["queue"]))

    sample_count = len(samples)

    return {
        "server_name": server_name,
        "range": f"{days}d",
        "sample_count": sample_count,
        "time_start": samples[0][0].isoformat(),
        "time_end": samples[-1][0].isoformat(),
        "overview": {
            "avg_node_usage_ratio": round(total_node_ratio / node_ratio_count, 4) if node_ratio_count else None,
            "peak_node_usage_ratio": round(peak_node_ratio, 4) if node_ratio_count else None,
            "avg_running_jobs": round(total_running_jobs / sample_count, 2) if sample_count else None,
            "peak_running_jobs": peak_running_jobs,
            "avg_queued_jobs": round(total_queued_jobs / sample_count, 2) if sample_count else None,
            "peak_queued_jobs": peak_queued_jobs,
            "active_user_count": len(active_users),
            "total_unique_jobs": total_unique_jobs,
        },
        "user_stats": user_stats,
        "node_stats": node_stats,
        "queue_stats": final_queue_stats,
        "timeline": timeline,
    }


@router.get("/summary")
def get_server_monitor_summary():
    return load_status_json(DEFAULT_SERVER_NAME)


@router.get("/servers")
def get_server_list():
    servers = []
    for server_name in ALLOWED_SERVERS:
        status_file = get_status_file(SERVER_MONITOR_BASE_DIR, server_name)
        item = safe_extract_server_summary(server_name, status_file)
        servers.append(item)

    return {
        "base_dir": str(SERVER_MONITOR_BASE_DIR),
        "default_server": DEFAULT_SERVER_NAME,
        "servers": servers,
    }


@router.get("/status/{server_name}")
def get_server_monitor_status(server_name: str):
    return load_status_json(server_name)


@router.get("/usage/{server_name}")
def get_server_monitor_usage(
    server_name: str,
    range: str = Query("7d", description="7d / 30d / 90d / 365d"),
):
    ensure_valid_server_name(server_name)
    days = parse_range_to_days(range)
    return aggregate_usage(server_name, days)

@router.get("/user-limits/{server_name}")
def get_server_user_limits(server_name: str):
    return load_user_limits_json(server_name)

@router.get("/users-overview")
def get_users_overview(
    background_tasks: BackgroundTasks,
    range: str = Query("30d", description="7d / 30d / 90d / 365d"),
):
    days = parse_range_to_days(range)
    return get_users_overview_response(days, background_tasks.add_task)
