# backend/authz_db.py
from __future__ import annotations
import os
import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Dict, List, Optional, Literal
DbScope = Literal["all", "personal", "upload", "custom"]

from fastapi import HTTPException, status

DEFAULT_ALLOWED_USERS_JSON = Path(__file__).resolve().parent / "var" / "data" / "allowed_users.json"
ALLOWED_USERS_JSON = Path(os.getenv("ALLOWED_USERS_PATH", str(DEFAULT_ALLOWED_USERS_JSON))).resolve()

# 上传库根目录（你要求的 docker 固定目录）
UPLOADS_ROOT = Path(os.getenv("UPLOADS_ROOT", "/app/var/uploads")).resolve()

# 用户自定义数据库目录
VASP_CUSTOM_DB_ROOT = Path(os.getenv("VASP_CUSTOM_DB_ROOT", "/app/var/Customized_database/vasp")).resolve()
QE_EPW_CUSTOM_DB_ROOT = Path(os.getenv("QE_EPW_CUSTOM_DB_ROOT", "/app/var/Customized_database/qe_epw")).resolve()


@dataclass(frozen=True)
class AllowedUser:
    nameCN: str
    aliasEN: str
    asedbname: str
    asedbdir: str
    qe_epwdbdir: str
    role: str          # "root" | "user"
    enabled: bool


@dataclass(frozen=True)
class DbRef:
    kind: str          # "personal" | "group" | "upload" | "custom" | "qe_custom"
    key: str           # ✅ 唯一键：personal:{owner}:{dbname} / upload:{owner}:{dbname} / group:{key}
    label: str
    dbname: str
    dbpath: Path
    ownerAlias: Optional[str] = None

    # ✅ 数据库文件是否存在（不存在不报错，让前端展示“未上传/不存在”）
    exists: bool = True
    missingReason: Optional[str] = None

@dataclass(frozen=True)
class OwnerRef:
    kind: str          # 固定 "owner"
    key: str           # owner:{aliasEN}
    label: str
    ownerAlias: str

def assert_inside_dir(dbpath: Path, parent: Path) -> None:
    parent = parent.resolve()
    dbpath = dbpath.resolve()

    # 要求 dbpath 必须在 parent 目录树下
    if dbpath == parent or parent not in dbpath.parents:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="path escape detected",
        )


@lru_cache(maxsize=1)
def _load_allowed_config() -> dict:
    try:
        return json.loads(ALLOWED_USERS_JSON.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"allowed_users.json not found at {ALLOWED_USERS_JSON}",
        )
    except json.JSONDecodeError as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"allowed_users.json invalid json: {e}",
        )


def load_allowed_users() -> Dict[str, AllowedUser]:
    data = _load_allowed_config()
    out: Dict[str, AllowedUser] = {}

    for u in data.get("users", []) or []:
        alias = (u.get("aliasEN") or "").strip()
        if not alias:
            continue
        out[alias] = AllowedUser(
            nameCN=(u.get("nameCN") or "").strip(),
            aliasEN=alias,
            asedbname=(u.get("asedbname") or "").strip(),
            asedbdir=(u.get("asedbdir") or "").strip(),
            qe_epwdbdir=(u.get("qe_epwdbdir") or "").strip(),
            role=(u.get("role") or "user").strip(),
            enabled=bool(u.get("enabled", False)),
        )

    return out


def get_allowed_user(aliasEN: str) -> AllowedUser:
    u = load_allowed_users().get(aliasEN)
    if not u or not u.enabled:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="user not allowed or disabled",
        )
    return u


def _safe_alias(alias: str) -> str:
    alias = (alias or "").strip()
    safe = "".join([c for c in alias if c.isalnum() or c in ("_", "-")])
    if not safe:
        safe = "unknown"
    return safe


# -----------------------------
# Upload DB refs
# -----------------------------
def _upload_db_ref_for_alias(owner_aliasEN: str) -> DbRef:
    """
    上传库：固定为 /app/var/uploads/{alias}/{alias}-uploads.db
    - 文件不存在也返回 DbRef（exists=False）
    """
    alias = _safe_alias(owner_aliasEN)
    user_dir = (UPLOADS_ROOT / alias).resolve()
    dbname = f"{alias}-uploads.db"
    dbpath = (user_dir / dbname).resolve()

    # 防路径穿越
    assert_inside_dir(dbpath, user_dir)

    exists = dbpath.exists() and dbpath.is_file()
    reason = None
    if not exists:
        reason = "upload database not found (no file yet)"

    # ✅ key 必须唯一：包含 owner + dbname
    return DbRef(
        kind="upload",
        key=f"upload:{alias}:{dbname}",
        label=f"上传数据库 ({alias})",
        dbname=dbname,
        dbpath=dbpath,
        ownerAlias=alias,
        exists=exists,
        missingReason=reason,
    )


# -----------------------------
# Personal DB refs
# -----------------------------
def _iter_personal_db_paths(u: AllowedUser) -> List[Path]:
    """
    ✅ 个人库：允许同一个用户在 asedbdir 下有多个库文件
    规则（尽量贴合你当前配置方式）：
    - 如果配置了 asedbname=Pwjb，那么枚举：
      Pwjb.db、Pwjb.sb（以及将来 Pwjb.sqlite 等你想要的后缀）
    - 默认只认 .db 和 .sb（你现在就需要这俩）
    """
    if not u.asedbdir or not u.asedbname:
        return []

    parent = Path(u.asedbdir).resolve()
    prefix = f"{u.asedbname}."

    # 只取你明确提到的两类文件（避免把目录里其它垃圾都扫进来）
    allow_suffix = {".db", ".sb"}

    out: List[Path] = []
    try:
        for p in parent.iterdir():
            if not p.is_file():
                continue
            name = p.name
            if not name.startswith(prefix):
                continue
            if p.suffix.lower() not in allow_suffix:
                continue
            out.append(p.resolve())
    except FileNotFoundError:
        # asedbdir 目录不存在 → 返回空，由上层决定是否提示
        return []
    except Exception:
        return []

    # 固定排序：.db 在前，.sb 在后；同后缀再按名字
    def _sort_key(x: Path):
        suf = x.suffix.lower()
        pri = 0 if suf == ".db" else 1
        return (pri, x.name.lower())

    out.sort(key=_sort_key)
    return out


def _personal_db_refs(u: AllowedUser) -> List[DbRef]:
    """
    个人库允许为空：asedbname/asedbdir 任一为空 => 暂无个人库（返回 []）

    ✅ 修改点：
    - 返回“多个”个人库（比如 Pwjb.db + Pwjb.sb）
    - 文件不存在不抛错（exists=False），由前端展示“数据库不存在”
    - key 唯一：personal:{owner}:{dbname}
    """
    if not u.asedbname or not u.asedbdir:
        return []

    parent = Path(u.asedbdir).resolve()

    refs: List[DbRef] = []
    paths = _iter_personal_db_paths(u)

    # 如果目录存在但没匹配到文件：仍然返回“默认 .db 的占位 ref”
    # 这样前端能提示“配置了但文件不存在”
    if not paths:
        dbname = f"{u.asedbname}.db"
        dbpath = (parent / dbname).resolve()
        assert_inside_dir(dbpath, parent)

        exists = dbpath.exists() and dbpath.is_file()
        reason = None
        if not exists:
            reason = f"personal database file not found under asedbdir: {dbpath}"

        refs.append(DbRef(
            kind="personal",
            key=f"personal:{u.aliasEN}:{dbname}",
            label=f"{u.nameCN} ({u.aliasEN})" if u.nameCN else u.aliasEN,
            dbname=dbname,
            dbpath=dbpath,
            ownerAlias=u.aliasEN,
            exists=exists,
            missingReason=reason,
        ))
        return refs

    for p in paths:
        # 安全检查：必须在 asedbdir 里
        assert_inside_dir(p, parent)

        exists = p.exists() and p.is_file()
        reason = None
        if not exists:
            reason = f"personal database file not found under asedbdir: {p}"

        refs.append(DbRef(
            kind="personal",
            key=f"personal:{u.aliasEN}:{p.name}",
            label=f"{u.nameCN} ({u.aliasEN})" if u.nameCN else u.aliasEN,
            dbname=p.name,
            dbpath=p,
            ownerAlias=u.aliasEN,
            exists=exists,
            missingReason=reason,
        ))

    return refs

def _iter_qe_epw_db_paths(u: AllowedUser) -> List[Path]:
    """
    QE+EPW 个人库：
    - 目录：u.qe_epwdbdir
    - 文件名建议：{asedbname}-qe_epw.sqlite（你现在就是 Pwjb-qe_epw.sqlite）
    - 也允许多个库文件（将来扩展）
    """
    if not u.qe_epwdbdir or not u.asedbname:
        return []

    parent = Path(u.qe_epwdbdir).resolve()

    allow_suffix = {".sqlite", ".db"}
    # 你现在的实际模式：Pwjb-qe_epw.sqlite
    prefix1 = f"{u.asedbname}-qe_epw"
    # 保险：也允许 Pwjb_qe_epw.sqlite 之类
    prefix2 = f"{u.asedbname}_qe_epw"

    out: List[Path] = []
    try:
        for p in parent.iterdir():
            if not p.is_file():
                continue
            name = p.name
            if not (name.startswith(prefix1) or name.startswith(prefix2)):
                continue
            if p.suffix.lower() not in allow_suffix:
                continue
            out.append(p.resolve())
    except FileNotFoundError:
        return []
    except Exception:
        return []

    out.sort(key=lambda x: x.name.lower())
    return out

def _qe_epw_db_refs(u: AllowedUser) -> List[DbRef]:
    if not u.qe_epwdbdir or not u.asedbname:
        return []

    parent = Path(u.qe_epwdbdir).resolve()
    paths = _iter_qe_epw_db_paths(u)

    refs: List[DbRef] = []

    # 如果目录存在但没有文件：也给一个占位 ref（exists=False）
    if not paths:
        dbname = f"{u.asedbname}-qe_epw.sqlite"
        dbpath = (parent / dbname).resolve()
        assert_inside_dir(dbpath, parent)

        exists = dbpath.exists() and dbpath.is_file()
        reason = None if exists else f"qe_epw database file not found under qe_epwdbdir: {dbpath}"

        refs.append(DbRef(
            kind="qe_epw",
            key=f"qe_epw:{u.aliasEN}:{dbname}",
            label=f"{u.nameCN} ({u.aliasEN})" if u.nameCN else u.aliasEN,
            dbname=dbname,
            dbpath=dbpath,
            ownerAlias=u.aliasEN,
            exists=exists,
            missingReason=reason,
        ))
        return refs

    for p in paths:
        assert_inside_dir(p, parent)
        exists = p.exists() and p.is_file()
        reason = None if exists else f"qe_epw database file not found under qe_epwdbdir: {p}"

        refs.append(DbRef(
            kind="qe_epw",
            key=f"qe_epw:{u.aliasEN}:{p.name}",
            label=f"{u.nameCN} ({u.aliasEN})" if u.nameCN else u.aliasEN,
            dbname=p.name,
            dbpath=p,
            ownerAlias=u.aliasEN,
            exists=exists,
            missingReason=reason,
        ))

    return refs

# -----------------------------
# Custom DB refs (Customized_database)
# -----------------------------
def _custom_user_dir(owner_aliasEN: str) -> Path:
    alias = _safe_alias(owner_aliasEN)
    return (VASP_CUSTOM_DB_ROOT / alias).resolve()

def _custom_db_refs(owner_aliasEN: str) -> List[DbRef]:
    """
    VASP 自定义库目录：
      /app/var/Customized_database/vasp/{alias}/*.db

    key 规则：
      custom:{alias}:{dbname}
    """
    alias = _safe_alias(owner_aliasEN)
    user_dir = _custom_user_dir(alias)

    if not user_dir.exists():
        return []

    refs: List[DbRef] = []
    try:
        for p in sorted(user_dir.glob("*.db")):
            dbpath = p.resolve()
            assert_inside_dir(dbpath, user_dir)

            exists = dbpath.exists() and dbpath.is_file()
            reason = None if exists else f"custom database file not found: {dbpath}"

            refs.append(DbRef(
                kind="custom",
                key=f"custom:{alias}:{dbpath.name}",
                label=f"自定义库 ({alias})",
                dbname=dbpath.name,
                dbpath=dbpath,
                ownerAlias=alias,
                exists=exists,
                missingReason=reason,
            ))
    except Exception:
        return []

    return refs

# -----------------------------
# QE+EPW Custom DB refs (Customized_database/qe_epw)
# -----------------------------
def _qe_custom_user_dir(owner_aliasEN: str) -> Path:
    alias = _safe_alias(owner_aliasEN)
    return (QE_EPW_CUSTOM_DB_ROOT / alias).resolve()

def _qe_custom_db_refs(owner_aliasEN: str) -> List[DbRef]:
    """
    QE+EPW 自定义库目录：
      /app/var/Customized_database/qe_epw/{alias}/*.sqlite

    key 规则：
      custom_qe_epw:{alias}:{dbname}
    """
    alias = _safe_alias(owner_aliasEN)
    user_dir = _qe_custom_user_dir(alias)

    if not user_dir.exists():
        return []

    refs: List[DbRef] = []
    try:
        for p in sorted(user_dir.glob("*.sqlite")):
            dbpath = p.resolve()
            assert_inside_dir(dbpath, user_dir)

            exists = dbpath.exists() and dbpath.is_file()
            reason = None if exists else f"qe custom database file not found: {dbpath}"

            refs.append(DbRef(
                kind="qe_custom",
                key=f"custom_qe_epw:{alias}:{dbpath.name}",
                label=f"QE+EPW 自定义库 ({alias})",
                dbname=dbpath.name,
                dbpath=dbpath,
                ownerAlias=alias,
                exists=exists,
                missingReason=reason,
            ))
    except Exception:
        return []

    return refs

# -----------------------------
# Group DB refs
# -----------------------------
def _group_db_refs() -> List[DbRef]:
    """
    ✅ 修改点：
    - group db 文件不存在也不抛错、不跳过（exists=False）
    - key 做成 group:{key} 以避免和 personal/upload 冲突
    """
    data = _load_allowed_config()
    out: List[DbRef] = []

    for g in data.get("groupDatabases", []) or []:
        if not g.get("enabled", False):
            continue
        path_raw = g.get("path")
        if not path_raw:
            continue

        dbpath = Path(path_raw).resolve()
        exists = dbpath.exists() and dbpath.is_file()
        reason = None
        if not exists:
            reason = f"group database file not found: {dbpath}"

        gkey = (g.get("key") or g.get("name") or dbpath.stem)
        out.append(DbRef(
            kind="group",
            key=f"group:{gkey}",
            label=(g.get("label") or g.get("name") or "Group DB"),
            dbname=dbpath.name,
            dbpath=dbpath,
            exists=exists,
            missingReason=reason,
        ))

    return out

def list_accessible_dbs(current_aliasEN: str, scope: DbScope = "all") -> List[DbRef]:
    """
    ✅ scope:
      - all: 所有可访问
        - root: group + 所有 personal（每人可多库） + 所有 upload（每人一个 uploads.db）
        - user: 自己 personal（可多库） + 自己 upload
      - personal: 只返回“我的个人库（asedbdir 下，可能多个）”
      - upload: 只返回“我的上传库”

    ✅ 文件不存在不抛错：exists=False，由前端提示
    """
    me = get_allowed_user(current_aliasEN)
    users = load_allowed_users()

    if scope == "upload":
        return [_upload_db_ref_for_alias(me.aliasEN)]

    if scope == "personal":
        return _personal_db_refs(me)
    
    if scope == "custom":
        return _custom_db_refs(me.aliasEN)

    # scope == "all"
    if me.role == "root":
        refs: List[DbRef] = []
        refs.extend(_group_db_refs())

        # ✅ root 看所有人的 personal（每人可能多个）
        for u in users.values():
            if not u.enabled:
                continue
            refs.extend(_personal_db_refs(u))

        # ✅ root 也看所有人的 upload（你要看到 jbwu-uploads.db 就靠这个）
        for u in users.values():
            if not u.enabled:
                continue
            refs.append(_upload_db_ref_for_alias(u.aliasEN))
            
        # root 也能看到自己的 custom（不默认看所有人的，避免越权）
        refs.extend(_custom_db_refs(me.aliasEN))

        return refs

    # 普通用户：只看自己的 personal + upload
    out: List[DbRef] = []
    out.extend(_personal_db_refs(me))
    out.append(_upload_db_ref_for_alias(me.aliasEN))
    out.extend(_custom_db_refs(me.aliasEN))
    return out

def resolve_db_for_request(current_aliasEN: str, requested: Optional[str]) -> DbRef:
    """
    requested 支持：
      - group key: "group:group_vasp"
      - personal key: "personal:aliasEN:Pwjb.db" / "personal:aliasEN:Pwjb.sb"
      - upload key: "upload:aliasEN:aliasEN-uploads.db"
      - 兼容旧写法：
          - 旧 upload key: "upload:aliasEN"
          - 旧 personal key: "aliasEN"
      - dbname: "Pwjb.db" / "Pwjb.sb" / "jbwu-uploads.db"
        （⚠️ 如果重名，可能有歧义；建议前端用 key）
    """
    me = get_allowed_user(current_aliasEN)
    allowed = list_accessible_dbs(current_aliasEN, scope="all")

    if not requested:
        # user：默认优先 personal（可能多个，取第一个），否则 upload
        if me.role != "root":
            my_personals = [r for r in allowed if r.kind == "personal" and r.ownerAlias == me.aliasEN]
            if my_personals:
                return my_personals[0]

            for ref in allowed:
                if ref.kind == "upload" and ref.ownerAlias == me.aliasEN:
                    return ref

            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="no db configured for user",
            )

        # root：默认策略：优先第一个 group，否则自己的第一个 personal，否则要求指定
        for ref in allowed:
            if ref.kind == "group":
                return ref

        my_personals = [r for r in allowed if r.kind == "personal" and r.ownerAlias == me.aliasEN]
        if my_personals:
            return my_personals[0]

        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="root must specify which db to use",
        )

    req = requested.strip()
    req_dbname = req if req.endswith(".db") or req.endswith(".sb") else f"{req}.db"

    # 1) 优先按 key 精确匹配（推荐）
    for ref in allowed:
        if ref.key == req:
            return ref

    # 2) 兼容旧 upload key：upload:aliasEN
    if req.startswith("upload:") and req.count(":") == 1:
        _, owner = req.split(":", 1)
        owner = owner.strip()
        # 在 allowed 里找该 owner 的 upload
        for ref in allowed:
            if ref.kind == "upload" and ref.ownerAlias == owner:
                return ref

    # 3) 兼容旧 personal key：直接给 aliasEN
    #    （如果该用户有多个 personal，默认取第一个）
    if ":" not in req:
        for ref in allowed:
            if ref.kind == "personal" and ref.ownerAlias == req:
                return ref

    # 4) 按 dbname 匹配（可能有歧义，按第一个返回）
    for ref in allowed:
        if ref.dbname == req_dbname or ref.dbname == req:
            return ref

    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="db not permitted",
    )

def list_accessible_owners(current_aliasEN: str, scope: DbScope = "all") -> List[OwnerRef]:
    """
    返回 owner 列表，用于前端下拉：
      - root：返回所有 enabled 用户
      - user：只返回自己
    scope 暂时不影响“owner 列表是否出现”（你若想在 scope=upload 时隐藏没有 upload 的人，可再加判断）
    """
    me = get_allowed_user(current_aliasEN)
    users = load_allowed_users()

    def _label(u: AllowedUser) -> str:
        return f"{u.nameCN} ({u.aliasEN})" if u.nameCN else u.aliasEN

    if me.role == "root":
        out: List[OwnerRef] = []
        for u in users.values():
            if not u.enabled:
                continue
            out.append(
                OwnerRef(
                    kind="owner",
                    key=f"owner:{u.aliasEN}",
                    label=_label(u),
                    ownerAlias=u.aliasEN,
                )
            )

        # ✅ 排序策略：当前登录用户永远排第一，其余再按 aliasEN 排序
        me_alias = me.aliasEN.lower()
        out.sort(key=lambda x: (0 if x.ownerAlias.lower() == me_alias else 1, x.ownerAlias.lower()))
        return out

    # 普通用户只返回自己
    return [OwnerRef(kind="owner", key=f"owner:{me.aliasEN}", label=_label(me), ownerAlias=me.aliasEN)]

def resolve_dbset_for_request(current_aliasEN: str, requested: Optional[str], scope: DbScope = "all") -> List[DbRef]:
    me = get_allowed_user(current_aliasEN)
    scope2 = (scope or "all").strip().lower()
    if scope2 not in ("all", "personal", "upload", "custom"):
        scope2 = "all"

    if not requested or not str(requested).strip():
        if me.role != "root":
            requested = f"owner:{me.aliasEN}"
        else:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="root must specify owner/db")

    req = str(requested).strip()

    # -------------------------
    # custom_owner:xxx -> 该用户所有自定义库
    # ✅ 强制只允许在 scope=custom 下使用（避免 all/personal/upload 混入 custom）
    # -------------------------
    if req.startswith("custom_owner:"):
        if scope2 != "custom":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="custom_owner is only allowed in scope=custom",
            )

        owner = req.split(":", 1)[1].strip()
        if me.role != "root" and owner != me.aliasEN:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="owner not permitted")

        # 你原来这里进一步限制：root 也不能看别人 custom（保持不变）
        if owner != me.aliasEN:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="owner not permitted")

        return _custom_db_refs(owner)

    # -------------------------
    # owner:xxx -> 多库
    # ✅ 调整：all 不再包含 custom；只有 scope=custom 才返回 custom
    # -------------------------
    if req.startswith("owner:"):
        owner = req.split(":", 1)[1].strip()
        users = load_allowed_users()
        u = users.get(owner)
        if not u or not u.enabled:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="owner not permitted")

        if me.role != "root" and owner != me.aliasEN:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="owner not permitted")

        refs: List[DbRef] = []

        if scope2 in ("all", "personal"):
            refs.extend(_personal_db_refs(u))

        if scope2 in ("all", "upload"):
            refs.append(_upload_db_ref_for_alias(u.aliasEN))

        # ✅ 关键改动：只有 scope=custom 时才返回 custom refs
        if scope2 == "custom":
            refs.extend(_custom_db_refs(u.aliasEN))

        return refs

    # -------------------------
    # 非 owner：兼容旧逻辑（单库）
    # 这里建议你也加一个“scope 与 key 匹配”的约束（可选但很推荐）
    # -------------------------
    ref = resolve_db_for_request(current_aliasEN, req)

    # ✅ 可选：如果 scope!=custom，就不允许请求 custom:...
    if scope2 != "custom":
        if str(getattr(ref, "key", "")).startswith("custom:") or str(getattr(ref, "kind", "")) in ("custom", "vasp_custom"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="custom database is not allowed in scope=all/personal/upload",
            )

    # ✅ 可选：如果 scope=custom，就要求必须是 custom 库
    if scope2 == "custom":
        if not (str(getattr(ref, "key", "")).startswith("custom:") or str(getattr(ref, "kind", "")) in ("custom", "vasp_custom")):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="non-custom database is not allowed in scope=custom",
            )

    return [ref]

# 列出可访问 QE 库
def list_accessible_qe_epw_dbs(current_aliasEN: str, scope: DbScope = "all") -> List[DbRef]:
    """
    QE+EPW 库：personal QE 库 + QE 自定义库（custom）
    """
    me = get_allowed_user(current_aliasEN)
    users = load_allowed_users()

    scope2 = (scope or "all").strip().lower()
    if scope2 not in ("all", "personal", "custom"):
        scope2 = "all"

    def _for_user(u: AllowedUser) -> List[DbRef]:
        out: List[DbRef] = []
        if scope2 in ("all", "personal"):
            out.extend(_qe_epw_db_refs(u))
        if scope2 in ("all", "custom"):
            out.extend(_qe_custom_db_refs(u.aliasEN))
        return out

    if me.role == "root":
        out: List[DbRef] = []
        for u in users.values():
            if not u.enabled:
                continue
            out.extend(_for_user(u))
        return out

    return _for_user(me)

# resolve 单库（支持 key/dbname/owner 兼容）
def resolve_qe_epw_db_for_request(current_aliasEN: str, requested: Optional[str]) -> DbRef:
    me = get_allowed_user(current_aliasEN)
    allowed = list_accessible_qe_epw_dbs(current_aliasEN, scope="all")

    if not requested or not str(requested).strip():
        # 默认：普通用户取自己的第一个；root 强制指定
        if me.role != "root":
            mine = [r for r in allowed if r.ownerAlias == me.aliasEN]
            if mine:
                return mine[0]
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="no qe_epw db configured for user")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="root must specify qe_epw owner/db")

    req = str(requested).strip()

    # 1) key 精确匹配
    for ref in allowed:
        if ref.key == req:
            return ref

    # 2) 兼容：owner alias（如果传 jbwu，就取 jbwu 的第一个 qe_epw 库）
    if ":" not in req:
        for ref in allowed:
            if ref.ownerAlias == req:
                return ref

    # 3) 按 dbname 匹配（可能歧义，按第一个返回）
    for ref in allowed:
        if ref.dbname == req:
            return ref

    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="qe_epw db not permitted")

# resolve 多库（owner:xxx -> 返回该 owner 所有 qe_epw 库）
def resolve_qe_epw_dbset_for_request(current_aliasEN: str, requested: Optional[str], scope: DbScope = "all") -> List[DbRef]:
    me = get_allowed_user(current_aliasEN)

    if not requested or not str(requested).strip():
        if me.role != "root":
            requested = f"owner:{me.aliasEN}"
        else:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="root must specify owner/db")

    req = str(requested).strip()
    scope2 = (scope or "all").strip().lower()
    if scope2 not in ("all", "personal", "custom"):
        scope2 = "all"

    # owner:xxx -> 该 owner 的 qe_epw 多库
    if req.startswith("owner:"):
        owner = req.split(":", 1)[1].strip()
        users = load_allowed_users()
        u = users.get(owner)
        if not u or not u.enabled:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="owner not permitted")

        if me.role != "root" and owner != me.aliasEN:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="owner not permitted")

        refs = list_accessible_qe_epw_dbs(current_aliasEN, scope=scope2)
        # 过滤出 owner 的
        return [r for r in refs if r.ownerAlias == u.aliasEN]

    # 非 owner：按单库解析
    return [resolve_qe_epw_db_for_request(current_aliasEN, req)]
