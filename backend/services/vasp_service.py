# services/vasp_service.py
from __future__ import annotations
from dataclasses import dataclass
from typing import Optional, List, Dict, Any, Tuple
from datetime import datetime, timedelta
import sqlite3
import os
import re
from functools import lru_cache

from settings_vasp import DB_PATH, get_db_connection  # 复用原逻辑

# ==== 下面这些工具函数都是从 app.py 精简搬过来的 ==== #

ALLOWED_ROOTS = ('/home', '/storage', '/public')

def _safe_task_path(db_path: str) -> Optional[str]:
    if not db_path:
        return None
    real = os.path.realpath(db_path.strip())
    return real if any(real.startswith(p) for p in ALLOWED_ROOTS) else None

def date_format(date_str: str | None) -> str | None:
    if not date_str:
        return None
    for fmt in ('%Y-%m-%d %H:%M:%S.%f', '%Y-%m-%d %H:%M:%S', '%Y-%m-%d'):
        try:
            return datetime.strptime(date_str, fmt).strftime('%Y-%m-%d')
        except ValueError:
            pass
    return date_str.split(' ')[0] if ' ' in date_str else date_str

@lru_cache(maxsize=1)
def vasp_columns() -> set[str]:
    with get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute('PRAGMA table_info(vasp_log)')
        return {row['name'] for row in cur.fetchall()}

def _make_full_daily_stats(rows, start_date: str | None, end_date: str | None) -> dict:
    date_cnt = {r['date']: r['cnt'] for r in rows} if rows else {}

    if end_date:
        try:
            end_dt = datetime.strptime(end_date, '%Y-%m-%d')
        except ValueError:
            end_dt = datetime.today()
    else:
        end_dt = datetime.today()

    if start_date:
        try:
            start_dt = datetime.strptime(start_date, '%Y-%m-%d')
        except ValueError:
            start_dt = end_dt - timedelta(days=7)
    else:
        start_dt = end_dt - timedelta(days=7)

    if start_dt > end_dt:
        start_dt, end_dt = end_dt, start_dt

    dates, counts = [], []
    cur = start_dt
    while cur <= end_dt:
        d = cur.strftime('%Y-%m-%d')
        dates.append(d)
        counts.append(date_cnt.get(d, 0))
        cur += timedelta(days=1)

    return {'dates': dates, 'counts': counts}

import json

DETAIL_WHITELIST = [
    'Path','JobID','Username','User','Hostname','Structure','KPOINTS','NumCores','JobType',
    'SubmitTime','EndTime','Runtime','TotalEnergy',
    'VBM_up','VBM_down','VBM','CBM_up','CBM_down','CBM',
    'E_fermi','E_vac','E_vac_method','E_Gap_up','E_Gap_down','E_Gap',
    'Status','ALGO','C_MOLAR','EB_K','EDIFF','EDIFFG','EFERMI_REF','ENCUT',
    'IBRION','ICHARG','IDIPOL','ISIF','ISMEAR','ISOL','ISPIN','ISTART','ISYM',
    'IVDW','LAECHG','LCHARG','LDIPOL','LELF','LOPTICS','LORBIT','LREAL','LSOL',
    'LVHAR','LVTOT','LWAVE','MAGMOM','NEDOS','NFREE','NPAR','NSW','POTIM',
    'R_ION','SIGMA','ele_set'
]

def build_task_details(row: sqlite3.Row, full: bool=False) -> dict:
    if full:
        return {k: row[k] for k in row.keys()}
    return {k: row[k] for k in DETAIL_WHITELIST if k in row.keys()}

# ---- 元素过滤 ----
EL_RE = re.compile(r'^[A-Z][a-z]?$')

@lru_cache(maxsize=1)
def all_elements() -> set[str]:
    with get_db_connection() as conn:
        cur = conn.cursor()
        rows = cur.execute('''
            SELECT DISTINCT json_each.key AS el
            FROM   ml_features, json_each(comp_json)
        ''').fetchall()
    return {r['el'] for r in rows}

def parse_elements_arg(arg: str) -> list[str] | None:
    if not arg.strip():
        return []
    parts = [p.strip() for p in arg.split(',') if p.strip()]
    bad = [p for p in parts if not EL_RE.fullmatch(p)]
    if bad:
        return None
    parts = [p for p in parts if p in all_elements()]
    return parts

def append_element_filter(date_filter: str, params: list,
                          ele_parts: list[str], exact: bool) -> tuple[str, list]:
    if not ele_parts:
        return date_filter, params

    elems = list(ele_parts)
    if exact:
        ph = ','.join('?' for _ in elems)
        date_filter += f"""
            AND EXISTS (
                SELECT 1
                FROM ml_features mf
                JOIN json_each(mf.comp_json) je
                      ON mf.Path = vasp_log.Path
                GROUP BY mf.Path
                HAVING 
                    SUM(CASE WHEN je.key NOT IN ({ph}) THEN 1 ELSE 0 END) = 0
                AND COUNT(DISTINCT je.key) = ?
                AND COUNT(DISTINCT CASE WHEN je.key IN ({ph}) THEN je.key END) = ?
            )
        """
        params.extend(elems)
        params.append(len(elems))
        params.extend(elems)
        params.append(len(elems))
    else:
        ph = ','.join('?' for _ in elems)
        date_filter += f"""
            AND EXISTS (
                SELECT 1
                FROM ml_features mf
                JOIN json_each(mf.comp_json) je
                      ON mf.Path = vasp_log.Path
                WHERE je.key IN ({ph})
            )
        """
        params.extend(elems)

    return date_filter, params

@dataclass
class TaskQuery:
    user: str                 # 当前登录用户名
    is_root: bool             # 是否管理员（可看全部）
    start: Optional[str] = None
    end: Optional[str] = None
    keyword: str = ""
    status_list: Optional[list[str]] = None
    page: int = 1
    limit: int = 10
    elements: str = ""
    exact: bool = False
    full_details: bool = False
    
def query_user_stats(q: TaskQuery) -> dict:
    """
    纯逻辑版本的 user-stats，本机 vasp_log 信息。
    返回结构与原 Flask /api/user-stats 中 data['local'] 一致：
      {
        users: {...},
        daily_stats: {...},
        status_stats: {...},
        tasks: [...],
        pagination: {...}
      }
    """
    start_date = q.start
    end_date   = q.end
    keyword    = q.keyword.strip()
    status_list = [s.strip().lower() for s in (q.status_list or []) if s.strip()]
    page  = max(int(q.page), 1)
    limit = max(int(q.limit), 1)
    full_details = q.full_details
    offset = (page - 1) * limit

    with get_db_connection() as conn:
        list_cur = conn.cursor()
        stat_cur = conn.cursor()

        date_filter, params = "", []

        if not q.is_root:
            date_filter += ' AND Username = ?'
            params.append(q.user)

        if start_date:
            date_filter += " AND DATE(SubmitTime) >= ?"
            params.append(start_date)
        if end_date:
            date_filter += " AND DATE(SubmitTime) <= ?"
            params.append(end_date)

        if status_list:
            placeholders = ','.join('?' * len(status_list))
            date_filter += f" AND LOWER(REPLACE(Status,'_',' ')) IN ({placeholders})"
            params.extend(status_list)

        exact = q.exact
        ele_parts = parse_elements_arg(q.elements or '')
        if ele_parts is None:
            raise ValueError("elements 参数格式错误")
        date_filter, params = append_element_filter(date_filter, params, ele_parts, exact)

        searchable_cols = {'Path','JobType','Hostname','User','Structure','Status'}
        exist_cols = searchable_cols & vasp_columns()
        keywords = keyword.split() if keyword else []
        for w in keywords:
            like = f'%{w}%'
            sub_sql, likes = [], []
            for col in exist_cols:
                col_expr = f'"{col}"' if col.lower() == 'user' else col
                sub_sql.append(f'{col_expr} LIKE ?')
                likes.append(like)
            if sub_sql:
                date_filter += ' AND ( ' + ' OR '.join(sub_sql) + ' ) '
                params.extend(likes)

        base_sql = f"FROM vasp_log WHERE 1=1 {date_filter}"

        list_sql = f"SELECT * {base_sql} ORDER BY SubmitTime DESC LIMIT {limit} OFFSET {offset}"
        list_cur.execute(list_sql, params)
        rows = list_cur.fetchall()

        stat_cur.execute(f"SELECT COUNT(*) {base_sql}", params)
        total_tasks = stat_cur.fetchone()[0]
        total_pages = (total_tasks + limit - 1) // limit or 1
        if page > total_pages:
            page = total_pages
            offset = (page - 1) * limit
            list_cur.execute(
                f"SELECT * {base_sql} ORDER BY SubmitTime DESC LIMIT {limit} OFFSET {offset}",
                params
            )
            rows = list_cur.fetchall()

        daily_rows = stat_cur.execute(f"""
            SELECT DATE(SubmitTime) AS date, COUNT(*) AS cnt
            {base_sql} GROUP BY DATE(SubmitTime) ORDER BY DATE(SubmitTime)
        """, params).fetchall()
        full_daily_stats = _make_full_daily_stats(daily_rows, start_date, end_date)

        status_rows = stat_cur.execute(f"""
            SELECT LOWER(REPLACE(Status,'_',' ')) AS status, COUNT(*) AS cnt
            {base_sql} GROUP BY LOWER(REPLACE(Status,'_',' '))
        """, params).fetchall()
        full_status = {(r['status'] or 'unknown'): r['cnt'] for r in status_rows}

        agg_sql = f'''
            SELECT COALESCE("User", Username) AS uname,
                   Username AS login,
                   LOWER(REPLACE(Status,'_',' ')) AS status,
                   DATE(SubmitTime) AS d,
                   COUNT(*) AS cnt
            {base_sql}
            GROUP BY uname, login, status, d
        '''
        user_tasks: dict[str, dict] = {}
        for r in stat_cur.execute(agg_sql, params).fetchall():
            u = r['uname']
            info = user_tasks.setdefault(u, {
                'login': r['login'],
                'total': 0, 'completed': 0, 'failed': 0, 'other': 0,
                'daily': {}
            })
            info['total'] += r['cnt']
            if r['status'] == 'completed':
                info['completed'] += r['cnt']
            elif r['status'] == 'failed':
                info['failed'] += r['cnt']
            else:
                info['other'] += r['cnt']
            drec = info['daily'].setdefault(r['d'],
                    {'total':0,'completed':0,'failed':0,'other':0})
            drec['total'] += r['cnt']
            if r['status'] == 'completed':
                drec['completed'] += r['cnt']
            elif r['status'] == 'failed':
                drec['failed'] += r['cnt']
            else:
                drec['other'] += r['cnt']

        task_list = []
        for t in rows:
            rt_raw = t['Runtime']
            if rt_raw:
                try:
                    h = int(float(rt_raw)); m = int((float(rt_raw)-h)*60)
                    runtime_str = f"{h}h {m}m"
                except Exception:
                    runtime_str = "N/A"
            else:
                runtime_str = "N/A"
            task_list.append({
                'server'     : t['Hostname'],
                'username'   : t['User'],
                'path'       : t['Path'],
                'submit_time': t['SubmitTime'],
                'JobType'    : t['JobType'],
                'status'     : (t['Status'] or 'unknown').lower(),
                'runtime'    : runtime_str,
                # 这里先不返回 contcar_url，由 FastAPI 路由来拼地址
                'details'    : build_task_details(t, full_details)
            })

        return {
            'users'       : user_tasks,
            'daily_stats' : full_daily_stats,
            'status_stats': full_status,
            'tasks'       : task_list,
            'pagination'  : {
                'total_tasks': total_tasks,
                'total_pages': total_pages,
                'current_page': page,
                'limit': limit
            }
        }

