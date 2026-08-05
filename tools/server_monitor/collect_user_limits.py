#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse
import json
import os
import re
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path


def run_cmd(cmd, timeout=20):
    try:
        result = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout,
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


def safe_int(value, default=None):
    if value is None:
        return default
    try:
        text = str(value).strip()
        if text == "":
            return default
        return int(float(text))
    except Exception:
        return default


def now_iso():
    return datetime.now(timezone.utc).astimezone().isoformat()


def ensure_parent_dir(path_str: str):
    Path(path_str).parent.mkdir(parents=True, exist_ok=True)


def parse_key_value_lines(text: str):
    """
    解析类似:
    key = value
    或
    key=value
    """
    data = {}
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue

        if " = " in line:
            key, value = line.split(" = ", 1)
            data[key.strip()] = value.strip()
        elif "=" in line:
            key, value = line.split("=", 1)
            data[key.strip()] = value.strip()

    return data


def normalize_walltime(value):
    """
    尽量保留成 HH:MM:SS 或原值。
    """
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    return text


def default_user_record(user):
    return {
        "user": user,
        "enabled": True,
        "default_queue": None,
        "queues": [],
        "global_limits": {
            "max_total_running_jobs": None,
            "max_total_queued_jobs": None,
            "max_total_nodes": None,
            "max_total_cores": None,
            "max_total_gpus": None,
        },
        "groups": [],
        "account": None,
        "remark": "",
    }


def merge_queue_limit(queue_items, new_item):
    """
    同一个用户同一个队列若多处提取到限制，尽量合并。
    非空优先，数值取更严格/更小的值不一定可靠，所以这里采用:
    - 若原值为空，用新值
    - 若原值非空，保留原值
    这样避免错误覆盖
    """
    for item in queue_items:
        if item.get("queue") == new_item.get("queue"):
            for k, v in new_item.items():
                if k == "queue":
                    continue
                if item.get(k) in (None, "", []):
                    item[k] = v
            return

    queue_items.append(new_item)


# =========================
# PBS / TORQUE / MAUI
# =========================

def parse_qmgr_list_queue_output(text: str):
    """
    尝试解析:
    qmgr -c "list queue <name>"
    或 qmgr -c "print queue <name>"
    的输出
    """
    result = {}
    current_queue = None

    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue

        m = re.match(r"create queue\s+(\S+)", line)
        if m:
            current_queue = m.group(1)
            result.setdefault(current_queue, {})
            continue

        m = re.match(r"set queue\s+(\S+)\s+(\S+)\s*=\s*(.+)", line)
        if m:
            qname = m.group(1)
            key = m.group(2)
            value = m.group(3).strip()
            result.setdefault(qname, {})
            result[qname][key] = value
            continue

    return result

def parse_qmgr_print_server_output(text: str):
    """
    解析:
      qmgr -c "p s"
    或
      qmgr -c "print server"
    输出

    返回:
    {
      "server_attrs": {...},
      "queue_user_map": {
        "username": set(["batch", "high"])
      }
    }

    说明：
    - 不同 PBS/Torque 环境输出差异较大
    - 这里只尽量解析 server 级属性
    - 如果看到类似 acl_users / managers / operators / submit_hosts 这类字段，会提取
    """
    server_attrs = {}
    queue_user_map = {}

    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue

        # 例如:
        # set server acl_user_enable = True
        # set server acl_users = alice,bob
        m = re.match(r"set\s+server\s+(\S+)\s*=\s*(.+)", line, re.I)
        if m:
            key = m.group(1).strip()
            value = m.group(2).strip()
            server_attrs[key] = value
            continue

    # 这里只先把 server_attrs 收集出来
    # 真正按用户映射到队列时，在 collect_pbs_user_limits 里结合 queue_details 做
    return {
        "server_attrs": server_attrs,
        "queue_user_map": queue_user_map,
    }


def get_pbs_queue_details():
    """
    返回:
    {
      "queue_name": { ...attrs... }
    }
    """
    if not shutil.which("qmgr"):
        return {}

    result = run_cmd(["qmgr", "-c", "list queue"])
    if not result["ok"]:
        return {}

    queue_names = []
    for line in result["stdout"].splitlines():
        line = line.strip()
        m = re.match(r"Queue\s+(\S+)", line)
        if m:
            queue_names.append(m.group(1))

    all_data = {}
    for q in queue_names:
        r = run_cmd(["qmgr", "-c", f"list queue {q}"])
        if r["ok"] and r["stdout"]:
            parsed = parse_qmgr_list_queue_output(r["stdout"])
            if q in parsed:
                all_data[q] = parsed[q]
            else:
                all_data[q] = {}
        else:
            all_data[q] = {}

    return all_data

def get_pbs_server_details():
    """
    尝试读取 qmgr -c "p s" / "print server" 的 server 级配置
    返回:
    {
      "server_attrs": {...},
      "queue_user_map": {}
    }
    """
    if not shutil.which("qmgr"):
        return {
            "server_attrs": {},
            "queue_user_map": {},
        }

    # 优先 p s
    result = run_cmd(["qmgr", "-c", "p s"])
    if result["ok"] and result["stdout"]:
        return parse_qmgr_print_server_output(result["stdout"])

    # 兜底 print server
    result = run_cmd(["qmgr", "-c", "print server"])
    if result["ok"] and result["stdout"]:
        return parse_qmgr_print_server_output(result["stdout"])

    return {
        "server_attrs": {},
        "queue_user_map": {},
    }


def parse_mdiag_u_output(text: str):
    """
    尝试解析 mdiag -u 输出。
    不同 Maui 版本格式差异较大，所以这里只做较保守提取。
    返回:
    {
      "user1": {
        "max_running_jobs": ...,
        "max_proc": ...,
        ...
      }
    }
    """
    user_map = {}

    for line in text.splitlines():
        raw = line.strip()
        if not raw:
            continue

        # 常见行里有 "User[x]" 或以用户名开头
        # 这里做宽松匹配
        m = re.search(r"User\[(.+?)\]", raw)
        if m:
            user = m.group(1).strip()
            user_map.setdefault(user, {})
            # 尝试提取 MaxJob / MaxProc / MaxNode
            mj = re.search(r"MaxJob(?:=|:)\s*(\d+)", raw, re.I)
            mp = re.search(r"MaxProc(?:=|:)\s*(\d+)", raw, re.I)
            mn = re.search(r"MaxNode(?:=|:)\s*(\d+)", raw, re.I)
            if mj:
                user_map[user]["max_running_jobs"] = safe_int(mj.group(1))
            if mp:
                user_map[user]["max_cores"] = safe_int(mp.group(1))
            if mn:
                user_map[user]["max_nodes"] = safe_int(mn.group(1))
            continue

        # 兜底：如果一行以用户名开头，后面有若干列
        parts = raw.split()
        if len(parts) >= 2:
            user = parts[0]
            if user.lower() in ("user", "name", "total"):
                continue
            # 只在很像用户名时建立
            if re.match(r"^[A-Za-z0-9._-]+$", user):
                user_map.setdefault(user, {})

    return user_map


def parse_showconfig_output(text: str):
    """
    showconfig / mdiag -c 输出差异很大。
    这里只尝试抓一些全局/用户默认限制关键词。
    """
    data = {}

    for line in text.splitlines():
        raw = line.strip()
        if not raw:
            continue

        if "=" in raw:
            key, value = raw.split("=", 1)
            data[key.strip()] = value.strip()

    return data


def parse_maui_cfg_for_user_limits(text: str):
    """
    粗解析 maui.cfg 中 USERCFG / CLASSCFG / QOSCFG / GROUPCFG
    这里只重点提 USERCFG。
    例如:
      USERCFG[alice] MAXJOB=2 MAXPROC=64 MAXNODE=2
    """
    users = {}
    classes = {}
    qoses = {}
    groups = {}

    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue

        m = re.match(r"USERCFG\[(.+?)\]\s+(.*)$", line, re.I)
        if m:
            user = m.group(1).strip()
            rest = m.group(2).strip()
            users[user] = parse_space_kv(rest)
            continue

        m = re.match(r"CLASSCFG\[(.+?)\]\s+(.*)$", line, re.I)
        if m:
            name = m.group(1).strip()
            classes[name] = parse_space_kv(m.group(2).strip())
            continue

        m = re.match(r"QOSCFG\[(.+?)\]\s+(.*)$", line, re.I)
        if m:
            name = m.group(1).strip()
            qoses[name] = parse_space_kv(m.group(2).strip())
            continue

        m = re.match(r"GROUPCFG\[(.+?)\]\s+(.*)$", line, re.I)
        if m:
            name = m.group(1).strip()
            groups[name] = parse_space_kv(m.group(2).strip())
            continue

    return {
        "users": users,
        "classes": classes,
        "qoses": qoses,
        "groups": groups,
    }


def parse_space_kv(text: str):
    """
    把这种:
      MAXJOB=2 MAXPROC=64 MAXNODE=2 QDEF=batch
    解析成 dict
    """
    data = {}
    for part in text.split():
        if "=" not in part:
            continue
        k, v = part.split("=", 1)
        data[k.strip()] = v.strip()
    return data

def build_pbs_template(server_name: str):
    return {
        "server_name": server_name,
        "updated_at": now_iso(),
        "source": "auto-generated",
        "reviewed": False,
        "reviewed_by": None,
        "reviewed_at": None,
        "description": "用户权限与资源上限配置，由脚本自动采集生成；建议管理员复核后再用于展示",
        "users": [],
    }

def collect_pbs_user_limits(server_name: str, maui_cfg_path=None):
    result = build_pbs_template(server_name)
    user_map = {}

    # 1) 队列信息
    queue_details = get_pbs_queue_details()

    # 1.1) server 级信息（来自 qmgr -c "p s" / "print server"）
    server_details = get_pbs_server_details()
    server_attrs = server_details.get("server_attrs", {}) or {}

    # 2) mdiag -u
    mdiag_user_map = {}
    if shutil.which("mdiag"):
        r = run_cmd(["mdiag", "-u"])
        if r["ok"] and r["stdout"]:
            mdiag_user_map = parse_mdiag_u_output(r["stdout"])

    # 3) showconfig / mdiag -c
    global_cfg = {}
    if shutil.which("showconfig"):
        r = run_cmd(["showconfig"])
        if r["ok"] and r["stdout"]:
            global_cfg = parse_showconfig_output(r["stdout"])
    elif shutil.which("mdiag"):
        r = run_cmd(["mdiag", "-c"])
        if r["ok"] and r["stdout"]:
            global_cfg = parse_showconfig_output(r["stdout"])

    # 4) maui.cfg（管理员权限时最有价值）
    maui_cfg = {"users": {}, "classes": {}, "qoses": {}, "groups": {}}
    candidate_paths = []

    if maui_cfg_path:
        candidate_paths.append(maui_cfg_path)

    candidate_paths.extend([
        "/usr/local/maui/maui.cfg",
        "/etc/maui.cfg",
        "/opt/maui/maui.cfg",
    ])

    for path in candidate_paths:
        try:
            if path and os.path.exists(path):
                with open(path, "r", encoding="utf-8") as f:
                    maui_cfg = parse_maui_cfg_for_user_limits(f.read())
                break
        except Exception:
            pass

    # 5) 从 maui USERCFG 建用户
    for user, attrs in maui_cfg.get("users", {}).items():
        rec = user_map.setdefault(user, default_user_record(user))

        rec["default_queue"] = attrs.get("QDEF") or rec["default_queue"]
        rec["global_limits"]["max_total_running_jobs"] = (
            safe_int(attrs.get("MAXJOB"), rec["global_limits"]["max_total_running_jobs"])
        )
        rec["global_limits"]["max_total_nodes"] = (
            safe_int(attrs.get("MAXNODE"), rec["global_limits"]["max_total_nodes"])
        )
        rec["global_limits"]["max_total_cores"] = (
            safe_int(attrs.get("MAXPROC"), rec["global_limits"]["max_total_cores"])
        )

        # MAUI 里常见字段未必都有 GPU/queued jobs
        if attrs.get("QDEF"):
            rec["remark"] = "default_queue 来自 USERCFG"

    # 6) 从 mdiag -u 合并用户级限制
    for user, attrs in mdiag_user_map.items():
        rec = user_map.setdefault(user, default_user_record(user))

        if rec["global_limits"]["max_total_running_jobs"] is None:
            rec["global_limits"]["max_total_running_jobs"] = attrs.get("max_running_jobs")
        if rec["global_limits"]["max_total_nodes"] is None:
            rec["global_limits"]["max_total_nodes"] = attrs.get("max_nodes")
        if rec["global_limits"]["max_total_cores"] is None:
            rec["global_limits"]["max_total_cores"] = attrs.get("max_cores")
    
    # 7) 为每个用户补队列权限
    #
    # 规则：
    # - 如果 queue 开了 acl_user_enable 且有 acl_users，则按显式用户授权
    # - 如果 queue 没开 acl_user_enable：
    #     - 对已经在 user_map 中出现过的用户（来自 USERCFG / mdiag），视为可提交该队列
    #     - 这是比“给所有系统用户”更保守的策略
    # - qmgr -c "p s" 的 server 级属性先保留做辅助说明
    server_acl_user_enable = str(server_attrs.get("acl_user_enable", "False")).lower() in ("true", "1", "yes")
    server_acl_users = server_attrs.get("acl_users", "")
    server_explicit_users = []
    if server_acl_user_enable and server_acl_users:
        server_explicit_users = [x.strip() for x in re.split(r"[,\s]+", server_acl_users) if x.strip()]

    for qname, qattrs in queue_details.items():
        enabled = str(qattrs.get("enabled", "True")).lower() in ("true", "1", "yes")
        started = str(qattrs.get("started", "True")).lower() in ("true", "1", "yes")
        acl_user_enable = str(qattrs.get("acl_user_enable", "False")).lower() in ("true", "1", "yes")
        acl_users = qattrs.get("acl_users", "")
        acl_group_enable = str(qattrs.get("acl_group_enable", "False")).lower() in ("true", "1", "yes")
        acl_groups = qattrs.get("acl_groups", "")

        if not enabled or not started:
            continue

        queue_note_parts = []

        queue_limit_template = {
            "queue": qname,
            "max_nodes": safe_int(qattrs.get("resources_max.nodect")),
            "max_cores": safe_int(qattrs.get("resources_max.ncpus")),
            "max_running_jobs": safe_int(qattrs.get("max_running")),
            "max_queued_jobs": safe_int(qattrs.get("max_queued")),
            "max_walltime": normalize_walltime(qattrs.get("resources_max.walltime")),
            "max_gpus": safe_int(qattrs.get("resources_max.ngpus")),
            "note": "",
        }

        explicit_users = []
        if acl_user_enable and acl_users:
            explicit_users = [x.strip() for x in re.split(r"[,\s]+", acl_users) if x.strip()]
            queue_note_parts.append("队列 ACL 用户限制")

        explicit_groups = []
        if acl_group_enable and acl_groups:
            explicit_groups = [x.strip() for x in re.split(r"[,\s]+", acl_groups) if x.strip()]
            queue_note_parts.append("队列 ACL 组限制")

        # 情况 A：队列有显式用户 ACL
        if explicit_users:
            for user in explicit_users:
                rec = user_map.setdefault(user, default_user_record(user))
                item = dict(queue_limit_template)
                item["note"] = "；".join(queue_note_parts) if queue_note_parts else ""
                merge_queue_limit(rec["queues"], item)

        # 情况 B：队列没有显式用户 ACL，但 server 级有 acl_users
        elif server_explicit_users:
            for user in server_explicit_users:
                rec = user_map.setdefault(user, default_user_record(user))
                item = dict(queue_limit_template)
                item["note"] = "server 级 ACL 用户可提交；队列未单独限制"
                merge_queue_limit(rec["queues"], item)

        # 情况 C：没有 ACL，则把它赋给“已知用户”
        # 已知用户来源：maui USERCFG / mdiag -u 解析出来的用户
        else:
            known_users = list(user_map.keys())
            for user in known_users:
                rec = user_map.setdefault(user, default_user_record(user))
                item = dict(queue_limit_template)
                item["note"] = "未发现显式 ACL，按已知用户推定可使用；建议管理员复核"
                merge_queue_limit(rec["queues"], item)

        # 组信息先只记录到 remark，不强行展开组成员
        if explicit_groups:
            for user, rec in user_map.items():
                for g in explicit_groups:
                    if g not in rec["groups"]:
                        # 不自动展开组成员，只保留备注
                        pass

    # 8) 结果清洗/排序
    users = list(user_map.values())
    for rec in users:
        rec["queues"].sort(key=lambda x: x.get("queue") or "")

        # 如果没有 default_queue，且只有一个可用队列，自动补上
        if not rec["default_queue"] and len(rec["queues"]) == 1:
            rec["default_queue"] = rec["queues"][0].get("queue")

        # 如果没有全局限制，尝试从队列限制里估一个上界
        if rec["global_limits"]["max_total_running_jobs"] is None:
            vals = [x.get("max_running_jobs") for x in rec["queues"] if x.get("max_running_jobs") is not None]
            if vals:
                rec["global_limits"]["max_total_running_jobs"] = max(vals)

        if rec["global_limits"]["max_total_queued_jobs"] is None:
            vals = [x.get("max_queued_jobs") for x in rec["queues"] if x.get("max_queued_jobs") is not None]
            if vals:
                rec["global_limits"]["max_total_queued_jobs"] = max(vals)

        if rec["global_limits"]["max_total_nodes"] is None:
            vals = [x.get("max_nodes") for x in rec["queues"] if x.get("max_nodes") is not None]
            if vals:
                rec["global_limits"]["max_total_nodes"] = max(vals)

        if rec["global_limits"]["max_total_cores"] is None:
            vals = [x.get("max_cores") for x in rec["queues"] if x.get("max_cores") is not None]
            if vals:
                rec["global_limits"]["max_total_cores"] = max(vals)

        if rec["global_limits"]["max_total_gpus"] is None:
            vals = [x.get("max_gpus") for x in rec["queues"] if x.get("max_gpus") is not None]
            if vals:
                rec["global_limits"]["max_total_gpus"] = max(vals)

        if not rec["remark"]:
            rec["remark"] = "部分限制由自动解析获得，建议管理员复核"


    users.sort(key=lambda x: x["user"])
    result["users"] = users
    return result


# =========================
# SLURM
# =========================

def parse_slurm_assoc_output(text: str):
    """
    解析:
    sacctmgr -nP show assoc format=User,Account,Partition,QOS,MaxJobs,MaxSubmitJobs,GrpTRES,GrpJobs
    使用 -P 时是 | 分隔
    """
    items = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split("|")
        if len(parts) < 8:
            continue

        items.append({
            "user": parts[0].strip(),
            "account": parts[1].strip() or None,
            "partition": parts[2].strip() or None,
            "qos": parts[3].strip() or None,
            "max_jobs": safe_int(parts[4]),
            "max_submit_jobs": safe_int(parts[5]),
            "grp_tres": parts[6].strip() or None,
            "grp_jobs": safe_int(parts[7]),
        })
    return items


def parse_slurm_qos_output(text: str):
    """
    sacctmgr -nP show qos format=Name,MaxTRESPU,MaxTRES,MaxJobsPU,MaxSubmitJobsPU,MaxWall
    """
    items = {}
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split("|")
        if len(parts) < 6:
            continue

        name = parts[0].strip()
        items[name] = {
            "name": name,
            "max_tres_pu": parts[1].strip() or None,
            "max_tres": parts[2].strip() or None,
            "max_jobs_pu": safe_int(parts[3]),
            "max_submit_jobs_pu": safe_int(parts[4]),
            "max_wall": normalize_walltime(parts[5].strip() or None),
        }
    return items


def parse_slurm_partition_output(text: str):
    """
    scontrol show partition
    只抓一些常用字段
    """
    partitions = {}

    blocks = re.split(r"\n(?=PartitionName=)", text.strip(), flags=re.M)
    for block in blocks:
        block = block.strip()
        if not block:
            continue

        data = {}
        for token in block.replace("\n", " ").split():
            if "=" in token:
                k, v = token.split("=", 1)
                data[k.strip()] = v.strip()

        name = data.get("PartitionName")
        if name:
            partitions[name] = data

    return partitions


def parse_tres_to_limits(tres_text):
    """
    从类似:
      cpu=64,gres/gpu=2,node=1
    提取 cpu/gpu/node
    """
    limits = {
        "max_nodes": None,
        "max_cores": None,
        "max_gpus": None,
    }
    if not tres_text:
        return limits

    for part in tres_text.split(","):
        part = part.strip()
        if "=" not in part:
            continue
        k, v = part.split("=", 1)
        if k == "cpu":
            limits["max_cores"] = safe_int(v)
        elif k == "node":
            limits["max_nodes"] = safe_int(v)
        elif k in ("gres/gpu", "gpu"):
            limits["max_gpus"] = safe_int(v)

    return limits


def build_slurm_template(server_name: str):
    return {
        "server_name": server_name,
        "updated_at": now_iso(),
        "source": "auto-generated",
        "reviewed": False,
        "reviewed_by": None,
        "reviewed_at": None,
        "description": "用户权限与资源上限配置，由脚本自动采集生成；建议管理员复核后再用于展示",
        "users": [],
    }


def collect_slurm_user_limits(server_name: str):
    result = build_slurm_template(server_name)
    user_map = {}

    # associations
    assoc_items = []
    if shutil.which("sacctmgr"):
        r = run_cmd([
            "sacctmgr", "-nP", "show", "assoc",
            "format=User,Account,Partition,QOS,MaxJobs,MaxSubmitJobs,GrpTRES,GrpJobs"
        ], timeout=30)
        if r["ok"] and r["stdout"]:
            assoc_items = parse_slurm_assoc_output(r["stdout"])

    # qos
    qos_map = {}
    if shutil.which("sacctmgr"):
        r = run_cmd([
            "sacctmgr", "-nP", "show", "qos",
            "format=Name,MaxTRESPU,MaxTRES,MaxJobsPU,MaxSubmitJobsPU,MaxWall"
        ], timeout=30)
        if r["ok"] and r["stdout"]:
            qos_map = parse_slurm_qos_output(r["stdout"])

    # partitions
    partition_map = {}
    if shutil.which("scontrol"):
        r = run_cmd(["scontrol", "show", "partition"], timeout=30)
        if r["ok"] and r["stdout"]:
            partition_map = parse_slurm_partition_output(r["stdout"])

    for item in assoc_items:
        user = item.get("user")
        if not user:
            continue

        rec = user_map.setdefault(user, default_user_record(user))
        if item.get("account") and not rec.get("account"):
            rec["account"] = item["account"]

        partition = item.get("partition") or "default"
        qos_name = item.get("qos")

        qos_info = qos_map.get(qos_name, {}) if qos_name else {}
        assoc_tres_limits = parse_tres_to_limits(item.get("grp_tres"))
        qos_tres_limits = parse_tres_to_limits(qos_info.get("max_tres_pu"))

        queue_item = {
            "queue": partition,
            "max_nodes": assoc_tres_limits["max_nodes"] if assoc_tres_limits["max_nodes"] is not None else qos_tres_limits["max_nodes"],
            "max_cores": assoc_tres_limits["max_cores"] if assoc_tres_limits["max_cores"] is not None else qos_tres_limits["max_cores"],
            "max_running_jobs": item.get("max_jobs") if item.get("max_jobs") is not None else qos_info.get("max_jobs_pu"),
            "max_queued_jobs": item.get("max_submit_jobs") if item.get("max_submit_jobs") is not None else qos_info.get("max_submit_jobs_pu"),
            "max_walltime": qos_info.get("max_wall"),
            "max_gpus": assoc_tres_limits["max_gpus"] if assoc_tres_limits["max_gpus"] is not None else qos_tres_limits["max_gpus"],
            "note": f"QOS={qos_name}" if qos_name else "",
        }

        merge_queue_limit(rec["queues"], queue_item)

        # 全局限制尽量从 association 估算
        if rec["global_limits"]["max_total_running_jobs"] is None:
            rec["global_limits"]["max_total_running_jobs"] = item.get("max_jobs") or qos_info.get("max_jobs_pu")
        if rec["global_limits"]["max_total_queued_jobs"] is None:
            rec["global_limits"]["max_total_queued_jobs"] = item.get("max_submit_jobs") or qos_info.get("max_submit_jobs_pu")
        if rec["global_limits"]["max_total_nodes"] is None:
            rec["global_limits"]["max_total_nodes"] = assoc_tres_limits["max_nodes"] or qos_tres_limits["max_nodes"]
        if rec["global_limits"]["max_total_cores"] is None:
            rec["global_limits"]["max_total_cores"] = assoc_tres_limits["max_cores"] or qos_tres_limits["max_cores"]
        if rec["global_limits"]["max_total_gpus"] is None:
            rec["global_limits"]["max_total_gpus"] = assoc_tres_limits["max_gpus"] or qos_tres_limits["max_gpus"]

        if rec["default_queue"] is None and partition and partition != "default":
            rec["default_queue"] = partition

    users = list(user_map.values())
    for rec in users:
        rec["queues"].sort(key=lambda x: x.get("queue") or "")
        if not rec["remark"]:
            rec["remark"] = "部分限制由 association / qos 自动推断，建议管理员复核"

    users.sort(key=lambda x: x["user"])
    result["users"] = users
    return result


# =========================
# MAIN
# =========================

def main():
    parser = argparse.ArgumentParser(description="Collect server user limits into template-1 JSON")
    parser.add_argument("--server-name", required=True, help="Server name, e.g. Dell / Dell-GPU")
    parser.add_argument("--scheduler", required=True, choices=["pbs", "slurm"], help="Scheduler type")
    parser.add_argument("--output", required=True, help="Output user_limits.json path")
    parser.add_argument("--maui-cfg", default=None, help="Optional maui.cfg path for PBS/Maui")

    args = parser.parse_args()

    if args.scheduler == "pbs":
        data = collect_pbs_user_limits(args.server_name, maui_cfg_path=args.maui_cfg)
    else:
        data = collect_slurm_user_limits(args.server_name)

    ensure_parent_dir(args.output)
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print(f"saved to: {args.output}")


if __name__ == "__main__":
    main()

