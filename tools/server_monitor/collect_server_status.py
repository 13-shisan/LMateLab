#!/usr/bin/env python3
import json
import os
import re
import socket
import shutil
import subprocess
from datetime import datetime, timezone

import psutil

OUTPUT_PATH = "/home/software/LMateLab/var/artifacts/server_monitor/Dell/status.json"
HISTORY_BASE_DIR = "/home/software/LMateLab/var/artifacts/server_monitor/Dell/history"


def run_cmd(cmd):
    try:
        result = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=20,
            check=False,
        )
        return {
            "ok": result.returncode == 0,
            "stdout": result.stdout.strip(),
            "stderr": result.stderr.strip(),
            "returncode": result.returncode,
        }
    except Exception as e:
        return {
            "ok": False,
            "stdout": "",
            "stderr": str(e),
            "returncode": -1,
        }


def parse_key_value_line(line: str):
    data = {}
    for item in line.strip().split():
        if "=" not in item:
            continue
        key, value = item.split("=", 1)
        data[key.strip()] = value.strip()
    return data


def safe_int(value, default=0):
    try:
        return int(str(value).strip())
    except Exception:
        return default


def format_mount_error_item(mount, e):
    return {
        "mount": mount,
        "error": str(e),
    }


def get_disk_mounts():
    mounts = ["/", "/home", "/data", "/storage"]
    items = []

    for mount in mounts:
        try:
            usage = psutil.disk_usage(mount)
            items.append({
                "mount": mount,
                "percent": usage.percent,
                "total": usage.total,
                "used": usage.used,
                "free": usage.free,
            })
        except Exception as e:
            items.append(format_mount_error_item(mount, e))

    return items


def get_logged_in_users_info():
    """
    返回当前登录会话与去重后的登录用户名统计。
    """
    sessions = psutil.users() or []

    usernames = []
    for item in sessions:
        name = getattr(item, "name", "") or ""
        name = str(name).strip()
        if name:
            usernames.append(name)

    unique_usernames = sorted(set(usernames))

    return {
        "logged_in_user_count": len(unique_usernames),   # 去重后的登录用户数
        "logged_in_session_count": len(sessions),        # 登录会话数
        "logged_in_users": unique_usernames,             # 去重后的用户名列表
    }

def get_overview():
    vm = psutil.virtual_memory()
    root_disk = psutil.disk_usage("/")
    login_info = get_logged_in_users_info()

    return {
        "cpu_percent": psutil.cpu_percent(interval=0.5),
        "memory_percent": vm.percent,
        "memory_total": vm.total,
        "memory_used": vm.used,
        "disk_percent": root_disk.percent,
        "disk_total": root_disk.total,
        "disk_used": root_disk.used,
        "logged_in_users": login_info["logged_in_user_count"],
        "logged_in_session_count": login_info["logged_in_session_count"],
        "logged_in_user_list": login_info["logged_in_users"],
        "disk_mounts": get_disk_mounts(),
    }


def get_gpu_info():
    if not shutil.which("nvidia-smi"):
        return {
            "available": False,
            "total": 0,
            "busy": 0,
            "idle": 0,
            "items": [],
            "processes": [],
        }

    gpu_cmd = [
        "nvidia-smi",
        "--query-gpu=index,uuid,name,utilization.gpu,memory.used,memory.total,temperature.gpu,power.draw",
        "--format=csv,noheader,nounits",
    ]
    gpu_result = run_cmd(gpu_cmd)
    if not gpu_result["ok"]:
        return {
            "available": False,
            "total": 0,
            "busy": 0,
            "idle": 0,
            "items": [],
            "processes": [],
            "error": gpu_result["stderr"],
        }

    processes = get_gpu_processes()

    process_map = {}
    for proc in processes:
        gpu_uuid = proc.get("gpu_uuid")
        if not gpu_uuid:
            continue
        process_map.setdefault(gpu_uuid, []).append(proc)

    items = []
    busy = 0
    MEMORY_BUSY_THRESHOLD_MB = 100

    for line in gpu_result["stdout"].splitlines():
        parts = [x.strip() for x in line.split(",")]
        if len(parts) < 8:
            continue

        index = parts[0]
        uuid = parts[1]
        name = parts[2]
        util = safe_int(parts[3], 0)
        mem_used = safe_int(parts[4], 0)
        mem_total = safe_int(parts[5], 0)
        temperature = safe_int(parts[6], 0)
        power_draw = safe_int(parts[7], 0)

        memory_used_ratio = round(mem_used / mem_total, 4) if mem_total else 0
        gpu_process_list = process_map.get(uuid, [])

        # 优先按 GPU 计算进程判断，退化时再用 util / 显存阈值
        is_busy = len(gpu_process_list) > 0 or util > 0 or mem_used >= MEMORY_BUSY_THRESHOLD_MB

        if is_busy:
            busy += 1

        items.append({
            "index": index,
            "uuid": uuid,
            "name": name,
            "utilization_gpu": util,
            "memory_used_mb": mem_used,
            "memory_total_mb": mem_total,
            "memory_used_ratio": memory_used_ratio,
            "temperature_c": temperature,
            "power_draw_w": power_draw,
            "is_busy": is_busy,
            "process_count": len(gpu_process_list),
            "processes": gpu_process_list,
        })

    total = len(items)

    return {
        "available": True,
        "total": total,
        "busy": busy,
        "idle": max(0, total - busy),
        "busy_memory_threshold_mb": MEMORY_BUSY_THRESHOLD_MB,
        "processes": processes,
        "items": items,
    }

def get_gpu_processes():
    if not shutil.which("nvidia-smi"):
        return []

    cmd = [
        "nvidia-smi",
        "--query-compute-apps=gpu_uuid,pid,process_name,used_memory",
        "--format=csv,noheader,nounits",
    ]
    result = run_cmd(cmd)

    if not result["ok"] or not result["stdout"]:
        return []

    items = []
    for line in result["stdout"].splitlines():
        parts = [x.strip() for x in line.split(",")]
        if len(parts) < 4:
            continue

        items.append({
            "gpu_uuid": parts[0],
            "pid": safe_int(parts[1], 0),
            "process_name": parts[2],
            "used_memory_mb": safe_int(parts[3], 0),
        })

    return items


def parse_slurm_nodelist(expr: str):
    """
    将 cpu[192-194,200] 展开成:
    [cpu192, cpu193, cpu194, cpu200]
    """
    if not expr:
        return []

    expr = expr.strip()
    if not expr:
        return []

    if "[" not in expr:
        return [x.strip() for x in expr.split(",") if x.strip()]

    m = re.match(r"^(.*)\[(.+)\]$", expr)
    if not m:
        return [expr]

    prefix = m.group(1)
    inside = m.group(2)

    items = []
    for part in inside.split(","):
        part = part.strip()
        if "-" in part:
            start, end = part.split("-", 1)
            width = len(start)
            try:
                s = int(start)
                e = int(end)
                for i in range(s, e + 1):
                    items.append(f"{prefix}{i:0{width}d}")
            except Exception:
                items.append(f"{prefix}{part}")
        else:
            items.append(f"{prefix}{part}")

    return items


def parse_slurm_reason_or_nodes(raw_value: str):
    """
    %R:
    - 对运行中作业通常是节点名 / 节点列表
    - 对 pending 作业通常是原因，如 Priority、Resources
    """
    if not raw_value:
        return "", ""

    text = raw_value.strip()

    if text.startswith("(") and text.endswith(")"):
        return "", text.strip("()")

    return text, ""


def get_slurm_job_workdir(job_id: str):
    """
    通过 scontrol show job -o <jobid> 获取 WorkDir
    """
    if not shutil.which("scontrol"):
        return ""

    result = run_cmd(["scontrol", "show", "job", "-o", str(job_id)])
    if not result["ok"] or not result["stdout"]:
        return ""

    data = parse_key_value_line(result["stdout"])
    return data.get("WorkDir", "")


def get_slurm_jobs():
    if not shutil.which("squeue"):
        return None

    cmd = [
        "squeue",
        "-h",
        "-o",
        "%i|%u|%j|%T|%P|%M|%D|%R",
    ]
    result = run_cmd(cmd)

    jobs = []
    if result["ok"] and result["stdout"]:
        for line in result["stdout"].splitlines():
            parts = line.split("|")
            if len(parts) < 8:
                continue

            node_text, reason_text = parse_slurm_reason_or_nodes(parts[7])
            workdir = get_slurm_job_workdir(parts[0])

            jobs.append({
                "job_id": parts[0],
                "user": parts[1],
                "name": parts[2],
                "state": parts[3],
                "partition": parts[4],
                "elapsed": parts[5],
                "nodes_count": parts[6],
                "node_or_reason": parts[7],
                "node": node_text,
                "reason": reason_text,
                "workdir": workdir,
            })

    queue_stats = build_queue_stats_from_jobs(jobs, queue_field="partition")
    nodes_info = get_slurm_nodes(jobs)

    running_jobs = [j for j in jobs if (j.get("state") or "").upper() == "RUNNING"]

    active_nodes = set()
    for job in running_jobs:
        node_expr = job.get("node") or ""
        expanded = parse_slurm_nodelist(node_expr)
        for node in expanded:
            active_nodes.add(node)

    return {
        "type": "slurm",
        "jobs": jobs,
        "running_task_count": len(running_jobs),
        "node_count": len(active_nodes),
        "nodes": nodes_info,
        "queue_stats": queue_stats,
    }


def normalize_slurm_node_state(state_text: str):
    text = (state_text or "").strip().lower()

    if not text:
        return ""

    if "down" in text or "drain" in text or "fail" in text:
        return "down"
    if "alloc" in text or "mix" in text or "comp" in text:
        return "busy"
    if "idle" in text:
        return "free"
    return text


def get_slurm_nodes(jobs=None):
    """
    使用 scontrol show node -o 获取节点详情。
    """
    if not shutil.which("scontrol"):
        return {
            "total": 0,
            "busy": 0,
            "free": 0,
            "down": 0,
            "items": [],
            "error": "scontrol not found",
        }

    result = run_cmd(["scontrol", "show", "node", "-o"])
    if not result["ok"] or not result["stdout"]:
        return {
            "total": 0,
            "busy": 0,
            "free": 0,
            "down": 0,
            "items": [],
            "error": result["stderr"],
        }

    jobs_by_node = {}
    if jobs:
        for job in jobs:
            node_expr = job.get("node") or ""
            expanded_nodes = parse_slurm_nodelist(node_expr)
            for node_name in expanded_nodes:
                jobs_by_node.setdefault(node_name, []).append(job.get("job_id", ""))

    items = []
    total = 0
    busy = 0
    free = 0
    down = 0

    for line in result["stdout"].splitlines():
        line = line.strip()
        if not line:
            continue

        raw = parse_key_value_line(line)

        name = raw.get("NodeName", "")
        state_raw = raw.get("State", "")
        state = normalize_slurm_node_state(state_raw)

        partitions = raw.get("Partitions", "")
        features = raw.get("AvailableFeatures", "") or raw.get("ActiveFeatures", "")
        cpu_total = raw.get("CPUTot", "")
        cfg_tres = raw.get("CfgTRES", "")

        np_val = ""
        m = re.search(r"cpu=(\d+)", cfg_tres)
        if m:
            np_val = m.group(1)
        elif cpu_total:
            np_val = cpu_total

        node_jobs = ",".join(jobs_by_node.get(name, []))

        items.append({
            "name": name,
            "state": state_raw,
            "queue": partitions,
            "np": np_val,
            "pcpus": cpu_total,
            "properties": features,
            "jobs": node_jobs,
        })

        total += 1
        if state == "down":
            down += 1
        elif state == "free":
            free += 1
        else:
            busy += 1

    items.sort(key=lambda x: x.get("name", ""))

    return {
        "total": total,
        "busy": busy,
        "free": free,
        "down": down,
        "items": items,
    }


def parse_pbs_kv_output(text: str):
    data = {}
    current_key = None

    for raw_line in text.splitlines():
        line = raw_line.rstrip()
        if not line:
            continue

        if line.startswith("Job Id:"):
            data["Job_Id"] = line.split(":", 1)[1].strip()
            current_key = None
            continue

        if raw_line.startswith("\t") or raw_line.startswith(" "):
            stripped = line.strip()
            if " = " in stripped:
                key, value = stripped.split(" = ", 1)
                data[key.strip()] = value.strip()
                current_key = key.strip()
            elif current_key:
                data[current_key] = data[current_key] + stripped
            continue

        if " = " in line:
            key, value = line.split(" = ", 1)
            data[key.strip()] = value.strip()
            current_key = key.strip()

    return data


def get_pbs_job_ids():
    if not shutil.which("qstat"):
        return []

    result = run_cmd(["qstat"])
    if not result["ok"] or not result["stdout"]:
        return []

    job_ids = []
    for line in result["stdout"].splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith("Job") or line.startswith("---"):
            continue

        parts = line.split()
        if parts:
            job_id = parts[0].strip()
            if "." in job_id or job_id.isdigit():
                job_ids.append(job_id)

    return job_ids


def get_pbs_job_detail(job_id: str):
    result = run_cmd(["qstat", "-f", job_id])
    if not result["ok"] or not result["stdout"]:
        return {
            "job_id": job_id,
            "state": "UNKNOWN",
            "raw_error": result["stderr"],
        }

    raw = parse_pbs_kv_output(result["stdout"])

    owner = raw.get("Job_Owner", "")
    user = owner.split("@", 1)[0] if "@" in owner else owner

    exec_host = raw.get("exec_host", "")
    node_name = ""
    if exec_host:
        node_name = exec_host.split("/", 1)[0]

    return {
        "job_id": raw.get("Job_Id", job_id),
        "name": raw.get("Job_Name", ""),
        "user": user or raw.get("euser", ""),
        "state": raw.get("job_state", ""),
        "queue": raw.get("queue", ""),
        "exec_host": exec_host,
        "node": node_name,
        "session_id": raw.get("session_id", ""),
        "walltime_used": raw.get("resources_used.walltime", ""),
        "cpu_time_used": raw.get("resources_used.cput", ""),
        "memory_used": raw.get("resources_used.mem", ""),
        "vmem_used": raw.get("resources_used.vmem", ""),
        "nodect": raw.get("Resource_List.nodect", ""),
        "nodes_spec": raw.get("Resource_List.nodes", ""),
        "walltime_limit": raw.get("Resource_List.walltime", ""),
        "submit_time": raw.get("qtime", ""),
        "start_time": raw.get("start_time", ""),
        "workdir": raw.get("init_work_dir", raw.get("PBS_O_WORKDIR", "")),
        "submit_args": raw.get("submit_args", ""),
        "raw_detail": raw,
    }


def get_pbs_active_node_count_from_jobs(jobs):
    nodes = set()
    for job in jobs:
        node = job.get("node")
        if node:
            nodes.add(node)
    return len(nodes) if nodes else 0


def parse_pbsnodes_output(text: str):
    nodes = []
    current = None

    for raw_line in text.splitlines():
        line = raw_line.rstrip()

        if not line:
            continue

        if not raw_line.startswith(" ") and not raw_line.startswith("\t"):
            if current:
                nodes.append(current)
            current = {"name": line.strip()}
            continue

        if current is None:
            continue

        stripped = line.strip()
        if " = " in stripped:
            key, value = stripped.split(" = ", 1)
            current[key.strip()] = value.strip()

    if current:
        nodes.append(current)

    return nodes


def guess_node_queue(node):
    if node.get("queue"):
        return node.get("queue")

    if node.get("properties"):
        return node.get("properties")

    if node.get("resources_available.queue"):
        return node.get("resources_available.queue")

    return ""


def is_pbs_node_free(state: str):
    if not state:
        return False
    state = state.lower()
    return "free" in state and "job-exclusive" not in state and "busy" not in state and "down" not in state


def get_pbs_nodes():
    if not shutil.which("pbsnodes"):
        return None

    result = run_cmd(["pbsnodes", "-a"])
    if not result["ok"] or not result["stdout"]:
        return {
            "total": 0,
            "busy": 0,
            "free": 0,
            "down": 0,
            "items": [],
            "error": result["stderr"],
        }

    try:
        raw_nodes = parse_pbsnodes_output(result["stdout"])
    except Exception as e:
        return {
            "total": 0,
            "busy": 0,
            "free": 0,
            "down": 0,
            "items": [],
            "error": str(e),
        }

    items = []
    total = 0
    free = 0
    busy = 0
    down = 0

    for raw in raw_nodes:
        if not isinstance(raw, dict):
            continue

        name = raw.get("name", "")
        state = raw.get("state", "")
        queue = guess_node_queue(raw)

        item = {
            "name": name,
            "state": state,
            "queue": queue,
            "np": raw.get("np", ""),
            "pcpus": raw.get("pcpus", ""),
            "jobs": raw.get("jobs", ""),
            "properties": raw.get("properties", ""),
            "status": raw.get("status", ""),
        }
        items.append(item)

        total += 1
        state_lower = (state or "").lower()

        if "down" in state_lower:
            down += 1
        elif is_pbs_node_free(state):
            free += 1
        else:
            busy += 1

    return {
        "total": total,
        "busy": busy,
        "free": free,
        "down": down,
        "items": items,
    }


def build_queue_stats_from_jobs(jobs, queue_field="queue"):
    stats = {}

    for job in jobs:
        queue = job.get(queue_field) or "unknown"
        state = (job.get("state") or "").upper()

        if queue not in stats:
            stats[queue] = {
                "queue": queue,
                "total_jobs": 0,
                "running_jobs": 0,
                "queued_jobs": 0,
                "other_jobs": 0,
                "users": set(),
            }

        stats[queue]["total_jobs"] += 1

        user = job.get("user")
        if user:
            stats[queue]["users"].add(user)

        if state in ("R", "RUNNING"):
            stats[queue]["running_jobs"] += 1
        elif state in ("Q", "PENDING"):
            stats[queue]["queued_jobs"] += 1
        else:
            stats[queue]["other_jobs"] += 1

    items = []
    for _, item in stats.items():
        total = item["total_jobs"]
        queued = item["queued_jobs"]

        items.append({
            "queue": item["queue"],
            "total_jobs": total,
            "running_jobs": item["running_jobs"],
            "queued_jobs": item["queued_jobs"],
            "other_jobs": item["other_jobs"],
            "active_users": len(item["users"]),
            "queue_ratio": round(queued / total, 4) if total else 0,
        })

    items.sort(key=lambda x: (-x["queued_jobs"], -x["total_jobs"], x["queue"]))
    return items


def get_pbs_jobs():
    if not shutil.which("qstat"):
        return None

    job_ids = get_pbs_job_ids()
    jobs = [get_pbs_job_detail(job_id) for job_id in job_ids]

    running_count = len([j for j in jobs if j.get("state") == "R"])
    active_node_count = get_pbs_active_node_count_from_jobs(jobs)
    queue_stats = build_queue_stats_from_jobs(jobs, queue_field="queue")

    nodes_info = None
    try:
        nodes_info = get_pbs_nodes()
    except Exception:
        nodes_info = None

    return {
        "type": "pbs",
        "jobs": jobs,
        "running_task_count": running_count,
        "node_count": active_node_count,
        "nodes": nodes_info,
        "queue_stats": queue_stats,
    }


def get_scheduler():
    slurm = get_slurm_jobs()
    if slurm:
        return slurm

    pbs = get_pbs_jobs()
    if pbs:
        return pbs

    return {
        "type": "none",
        "jobs": [],
        "running_task_count": 0,
        "node_count": 0,
        "nodes": None,
        "queue_stats": [],
    }

def extract_job_state_signature(data):
    """
    只提取 scheduler.jobs 里的 job_id + state，用于判断两个快照是否相同
    """
    jobs = (((data or {}).get("scheduler") or {}).get("jobs")) or []

    items = []
    for job in jobs:
        if not isinstance(job, dict):
            continue

        job_id = str(job.get("job_id", "")).strip()
        state = str(job.get("state", "")).strip()

        if not job_id:
            continue

        items.append((job_id, state))

    return sorted(items)


def load_json_file(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def list_history_json_files(base_dir):
    """
    列出 history 目录下所有 json 文件，并按路径排序
    目录结构是 history/YYYY-MM-DD/HH-MM-SS.json 时，这样排序就是时间顺序
    """
    results = []

    if not os.path.isdir(base_dir):
        return results

    for root, _, files in os.walk(base_dir):
        for name in files:
            if name.lower().endswith(".json"):
                results.append(os.path.abspath(os.path.join(root, name)))

    results.sort()
    return results


def find_previous_history_file(base_dir, current_file):
    """
    找到当前历史文件的前一个历史文件
    """
    files = list_history_json_files(base_dir)
    current_file = os.path.abspath(current_file)

    try:
        idx = files.index(current_file)
    except ValueError:
        return ""

    if idx <= 0:
        return ""

    return files[idx - 1]


def deduplicate_with_previous_history_file(base_dir, current_file):
    """
    如果当前文件和前一个文件的 job_id + state 完全一致，则删除前一个文件
    """
    previous_file = find_previous_history_file(base_dir, current_file)
    if not previous_file:
        return

    current_data = load_json_file(current_file)
    previous_data = load_json_file(previous_file)

    if current_data is None or previous_data is None:
        return

    current_sig = extract_job_state_signature(current_data)
    previous_sig = extract_job_state_signature(previous_data)

    if current_sig == previous_sig:
        try:
            os.remove(previous_file)
        except Exception:
            pass

def save_history_snapshot(data):
    ts = datetime.now().astimezone()
    day_dir = ts.strftime(os.path.join(HISTORY_BASE_DIR, "%Y-%m-%d"))
    os.makedirs(day_dir, exist_ok=True)

    file_path = os.path.join(day_dir, ts.strftime("%H-%M-%S.json"))
    tmp_path = file_path + ".tmp"

    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    os.replace(tmp_path, file_path)

    deduplicate_with_previous_history_file(HISTORY_BASE_DIR, file_path)


def main():
    try:
        scheduler = get_scheduler()
        overview = get_overview()
        gpu = get_gpu_info()

        nodes_info = scheduler.get("nodes") or {}

        data = {
            "updated_at": datetime.now(timezone.utc).astimezone().isoformat(),
            "host": {
                "hostname": socket.gethostname(),
            },
            "overview": {
                **overview,
                "gpu": {
                    "available": gpu["available"],
                    "total": gpu["total"],
                    "busy": gpu["busy"],
                    "idle": gpu.get("idle", 0),
                },
                "running_task_count": scheduler.get("running_task_count", 0),
                "node_count": scheduler.get("node_count", 0),
                "node_total": nodes_info.get("total", 0),
                "node_busy": nodes_info.get("busy", 0),
                "node_free": nodes_info.get("free", 0),
                "node_down": nodes_info.get("down", 0),
            },
            "scheduler": scheduler,
            "gpu_detail": gpu,
            "system_processes": [],
            "platform_tasks": [],
        }

        os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
        tmp_path = OUTPUT_PATH + ".tmp"

        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        os.replace(tmp_path, OUTPUT_PATH)

        try:
            save_history_snapshot(data)
        except Exception:
            pass

    except Exception as e:
        error_data = {
            "updated_at": datetime.now(timezone.utc).astimezone().isoformat(),
            "host": {
                "hostname": socket.gethostname(),
            },
            "error": str(e),
            "system_processes": [],
            "platform_tasks": [],
        }

        os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
        with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
            json.dump(error_data, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
