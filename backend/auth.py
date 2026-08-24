# backend/auth.py
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from passlib.context import CryptContext
import jwt
from datetime import datetime, timedelta
from pathlib import Path
import json
from database import get_db
from models import User
from schemas import ChangePasswordRequest, RegisterRequest, LoginRequest, UserOut, TokenOut
import os, secrets, hashlib
from models import PasswordResetCode
from schemas import ForgotPasswordRequest, ForgotPasswordVerify, ForgotPasswordReset
from email_utils import send_reset_code
from schemas import load_policy
from auth_identity import (
    JWT_ALGORITHM,
    JWT_SECRET,
    get_current_user,
    password_token_version,
)
from competition_authz import (
    require_account_changes_enabled,
    require_competition_role,
    require_current_edition_user,
)

if not JWT_SECRET:
    raise RuntimeError("JWT_SECRET 未配置（请在后端 .env 中设置）")

router = APIRouter(prefix="/auth", tags=["auth"])
competition_router = APIRouter(prefix="/auth", tags=["auth"])

ACCESS_TOKEN_EXPIRE_DAYS = int(os.getenv("ACCESS_TOKEN_EXPIRE_DAYS", "7"))

RESET_CODE_COOLDOWN_SEC = 60  # 邮箱验证码冷却时间，单位秒

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


@router.get("/password-policy")
@competition_router.get("/password-policy")
def password_policy():
    p = load_policy().get("password", {})
    return {
        "minLength": int(p.get("minLength", 6)),
        "requireUpper": bool(p.get("requireUpper", True)),
        "requireLower": bool(p.get("requireLower", True)),
        "allowedPattern": p.get("allowedPattern", "") or "",
        # 新增：短提示
        "allowedHintShort": p.get("allowedHintShort", "") or "",
        # 原来的长描述仍下发（用于展开）
        "allowedDescription": p.get("allowedDescription", "") or "",
        "allowedExample": p.get("allowedExample", "") or "",
    }


# ---------- 白名单加载与匹配 ----------

DEFAULT_WHITELIST_PATH = Path(__file__).resolve().parent / "var" / "data" / "allowed_users.json"
WHITELIST_PATH = Path(os.getenv("ALLOWED_USERS_PATH", str(DEFAULT_WHITELIST_PATH))).resolve()


def load_whitelist() -> dict:
    try:
        with WHITELIST_PATH.open("r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        raise HTTPException(status_code=500, detail="服务器未配置注册白名单文件")
    except json.JSONDecodeError:
        raise HTTPException(status_code=500, detail="注册白名单文件格式错误")


def find_allowed_user(name_cn: str, wl: dict) -> dict | None:
    name_cn = (name_cn or "").strip()
    if not name_cn:
        return None
    for u in wl.get("users", []):
        if u.get("enabled", True) and u.get("nameCN") == name_cn:
            return u
    return None


@router.get("/allowed-info")
def allowed_info(name: str = Query(..., description="中文姓名（精确匹配白名单）")):
    """
    前端输入姓名时用于实时提示：
    - 不暴露全名单
    - 仅返回该姓名是否允许注册，以及对应 alias/role（如果允许）
    """
    require_account_changes_enabled(feature_flag="LMATELAB_REGISTRATION_ENABLED")
    wl = load_whitelist()
    u = find_allowed_user(name, wl)
    if not u:
        return {"allowed": False}

    return {
        "allowed": True,
        "aliasEN": u.get("aliasEN", ""),
        "role": u.get("role", "user"),
    }


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


def create_access_token(data: dict) -> str:
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(days=ACCESS_TOKEN_EXPIRE_DAYS)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, JWT_SECRET, algorithm=JWT_ALGORITHM)


def norm_email(s: str) -> str:
    """统一邮箱格式：去空格 + 小写，避免重复账号（A@x.com 和 a@x.com）。"""
    return (s or "").strip().lower()


# ---------- 注册 / 登录 ----------

@router.post("/register", response_model=UserOut)
def register(payload: RegisterRequest, db: Session = Depends(get_db)):
    require_account_changes_enabled(feature_flag="LMATELAB_REGISTRATION_ENABLED")
    # 0) 两次密码一致（如果 schemas.py 已强制 password2 必填，这里保留兜底）
    if payload.password2 is None:
        raise HTTPException(status_code=400, detail="请再次确认密码")
    if payload.password != payload.password2:
        raise HTTPException(status_code=400, detail="两次输入的密码不一致")

    # 1) 白名单校验（服务端最终裁决）
    wl = load_whitelist()
    allowed = find_allowed_user(payload.name, wl)
    if not allowed:
        raise HTTPException(status_code=403, detail="该姓名不在允许注册名单中，请联系管理员")

    alias = allowed.get("aliasEN", "")
    role = allowed.get("role", "user")

    # 2) 同时检查：该用户是否已注册、该邮箱是否已注册
    name_in = (payload.name or "").strip()
    email_in = norm_email(payload.email)

    existing_by_name = db.query(User).filter(User.name == name_in).first()
    existing_by_email = db.query(User).filter(User.email == email_in).first()

    if existing_by_name or existing_by_email:
        msgs = []
        if existing_by_name:
            msgs.append("该用户已经注册")
        if existing_by_email:
            msgs.append("该邮箱已经注册")
        raise HTTPException(status_code=400, detail="；".join(msgs))

    # 3) 创建用户：alias/role 由后端白名单决定（不信任前端传参）
    user = User(
        email=email_in,              # 用户输入的邮箱最终保存到数据库 users.email
        name=name_in,
        alias=alias,
        role=role,
        password_hash=hash_password(payload.password),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@router.post("/login", response_model=TokenOut)
@competition_router.post("/login", response_model=TokenOut)
def login(login_req: LoginRequest, db: Session = Depends(get_db)):
    email_in = norm_email(login_req.email)

    user = db.query(User).filter(User.email == email_in).first()
    if not user or not verify_password(login_req.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="邮箱或密码错误"
        )

    require_competition_role(user)

    token = create_access_token({
        "sub": user.id,
        "email": user.email,
        "name": user.name,
        "alias": user.alias,
        "role": user.role,
        "pwdv": password_token_version(user.password_hash),
    })

    return TokenOut(
        token=token,
        user=UserOut.model_validate(user)
    )


@router.get("/me", response_model=UserOut)
@competition_router.get("/me", response_model=UserOut)
def me(current_user: User = Depends(require_current_edition_user)):
    """
    用于前端启动时校验 token：
    - token 有效：返回当前用户信息
    - token 无效/过期：get_current_user 会抛 401
    """
    return UserOut.model_validate(current_user)


@competition_router.post("/change-password")
def change_password(
    payload: ChangePasswordRequest,
    current_user: User = Depends(require_current_edition_user),
    db: Session = Depends(get_db),
):
    if not verify_password(payload.current_password, current_user.password_hash):
        raise HTTPException(status_code=400, detail="当前密码不正确")

    try:
        current_user.password_hash = hash_password(payload.new_password)
        db.commit()
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=500, detail="密码修改失败，请稍后重试") from exc

    return {"ok": True}


RESET_CODE_TTL_MIN = 10
RESET_CODE_MAX_ATTEMPTS = 5
RESET_TOKEN_TTL_MIN = 15


def make_6digit_code() -> str:
    return f"{secrets.randbelow(1_000_000):06d}"


def sha256(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


@router.post("/forgot-password/request")
def forgot_password_request(payload: ForgotPasswordRequest, db: Session = Depends(get_db)):
    require_account_changes_enabled(feature_flag="LMATELAB_PASSWORD_RESET_ENABLED")
    email_in = norm_email(payload.email)

    # 不暴露“邮箱是否存在”：统一返回
    user = db.query(User).filter(User.email == email_in).first()

    # 即使用户不存在，也假装成功（防枚举）
    if not user:
        return {"ok": True, "message": "如果该邮箱存在，验证码已发送"}

    # 60s 频率限制（同邮箱）
    latest = db.query(PasswordResetCode).filter(
        PasswordResetCode.email == email_in
    ).order_by(PasswordResetCode.id.desc()).first()

    if latest and latest.created_at:
        delta = datetime.utcnow() - latest.created_at
        if delta.total_seconds() < RESET_CODE_COOLDOWN_SEC:
            retry_after = int(RESET_CODE_COOLDOWN_SEC - delta.total_seconds())
            # 这里返回 429 更语义化；detail 给前端提示；retry_after 给倒计时用
            raise HTTPException(
                status_code=429,
                detail=f"请求过于频繁，请 {retry_after}s 后再试",
                headers={"Retry-After": str(retry_after)}
            )

    # 清理旧未使用验证码（让之前的全部失效，避免多码并存）
    db.query(PasswordResetCode).filter(
        PasswordResetCode.email == email_in,
        PasswordResetCode.used == False
    ).update({"used": True})
    db.commit()

    code = make_6digit_code()
    rec = PasswordResetCode(
        email=email_in,
        code_hash=sha256(code),
        created_at=datetime.utcnow(),
        expires_at=datetime.utcnow() + timedelta(minutes=RESET_CODE_TTL_MIN),
        used=False,
        attempts=0,
    )
    db.add(rec)
    db.commit()

    try:
        send_reset_code(email_in, code)
    except Exception as e:
        rec.used = True
        db.commit()
        raise HTTPException(status_code=500, detail=f"邮件发送失败：{e}")

    return {"ok": True, "message": "如果该邮箱存在，验证码已发送"}


@router.post("/forgot-password/verify")
def forgot_password_verify(payload: ForgotPasswordVerify, db: Session = Depends(get_db)):
    require_account_changes_enabled(feature_flag="LMATELAB_PASSWORD_RESET_ENABLED")
    email_in = norm_email(payload.email)
    code_in = (payload.code or "").strip()

    rec = db.query(PasswordResetCode).filter(
        PasswordResetCode.email == email_in,
        PasswordResetCode.used == False
    ).order_by(PasswordResetCode.id.desc()).first()

    # 统一错误信息（不泄露）
    if not rec:
        raise HTTPException(status_code=400, detail="验证码无效或已过期")

    if datetime.utcnow() > rec.expires_at:
        rec.used = True
        db.commit()
        raise HTTPException(status_code=400, detail="验证码无效或已过期")

    if rec.attempts >= RESET_CODE_MAX_ATTEMPTS:
        rec.used = True
        db.commit()
        raise HTTPException(status_code=400, detail="验证码无效或已过期")

    rec.attempts += 1

    if sha256(code_in) != rec.code_hash:
        db.commit()
        raise HTTPException(status_code=400, detail="验证码无效或已过期")

    # 验证通过：标记已使用
    rec.used = True
    db.commit()

    user = db.query(User).filter(User.email == email_in).first()
    if not user:
        # 理论上不应发生，但仍保留兜底
        raise HTTPException(status_code=400, detail="验证码无效或已过期")

    # 发一个短期 reset_token（用途标识：pwd_reset）
    expire = datetime.utcnow() + timedelta(minutes=RESET_TOKEN_TTL_MIN)
    reset_token = jwt.encode(
        {"sub": user.id, "purpose": "pwd_reset", "exp": expire},
        JWT_SECRET,
        algorithm=JWT_ALGORITHM
    )
    return {"reset_token": reset_token}


@router.post("/forgot-password/reset")
def forgot_password_reset(payload: ForgotPasswordReset, db: Session = Depends(get_db)):
    require_account_changes_enabled(feature_flag="LMATELAB_PASSWORD_RESET_ENABLED")
    if payload.new_password != payload.new_password2:
        raise HTTPException(status_code=400, detail="两次输入的密码不一致")

    # 这里你可以复用已有的密码策略校验（security_policy.json）
    # 不写也能用，但建议加上；当前 schemas.ForgotPasswordReset 已处理

    try:
        data = jwt.decode(payload.reset_token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except jwt.PyJWTError:
        raise HTTPException(status_code=400, detail="重置凭证无效或已过期")

    if data.get("purpose") != "pwd_reset":
        raise HTTPException(status_code=400, detail="重置凭证无效或已过期")

    user_id = data.get("sub")
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=400, detail="重置凭证无效或已过期")

    user.password_hash = hash_password(payload.new_password)
    db.commit()
    return {"ok": True}
