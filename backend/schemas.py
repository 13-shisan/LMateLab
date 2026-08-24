# backend/schemas.py
from pydantic import BaseModel, EmailStr, Field, model_validator
from datetime import datetime
from pathlib import Path
from typing import List, Optional
import json
import os
import re

# ---------- 密码策略加载（后端真源） ----------

DEFAULT_POLICY_PATH = Path("/app/var/data/security_policy.json")


def security_policy_path() -> Path:
    return Path(
        os.getenv("SECURITY_POLICY_PATH", str(DEFAULT_POLICY_PATH))
    ).resolve()

def load_policy() -> dict:
    policy_path = security_policy_path()
    try:
        with policy_path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        raise ValueError("服务器未配置安全策略文件 security_policy.json")
    except json.JSONDecodeError:
        raise ValueError("安全策略文件 security_policy.json 格式错误")


def validate_password_by_policy(pw: str) -> None:
    policy = load_policy().get("password", {})
    min_len = int(policy.get("minLength", 6))
    require_upper = bool(policy.get("requireUpper", True))
    require_lower = bool(policy.get("requireLower", True))
    allowed_pattern = policy.get("allowedPattern")
    allowed_desc = policy.get("allowedDescription") or ""

    if pw is None:
        raise ValueError("密码不能为空")

    if len(pw) < min_len:
        raise ValueError(f"密码至少 {min_len} 位")

    if require_upper and not re.search(r"[A-Z]", pw):
        raise ValueError("密码必须包含大写字母")

    if require_lower and not re.search(r"[a-z]", pw):
        raise ValueError("密码必须包含小写字母")

    if allowed_pattern:
        if not re.fullmatch(allowed_pattern, pw):
            # ✅ 报错里带上可读说明（如果配置了）
            if allowed_desc:
                raise ValueError(f"密码包含不允许的字符：{allowed_desc}")
            raise ValueError("密码包含不允许的字符（不允许空格或非常规字符）")


# ---------- 用户相关 ----------

class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=6)
    password2: str
    name: str

    @model_validator(mode="after")
    def validate_register(self):
        if self.password != self.password2:
            raise ValueError("两次输入的密码不一致")
        validate_password_by_policy(self.password)
        return self


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class UserOut(BaseModel):
    id: int
    email: EmailStr
    name: str
    alias: str
    role: str

    class Config:
        from_attributes = True


class TokenOut(BaseModel):
    token: str
    user: UserOut


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str = Field(min_length=6)
    new_password2: str

    @model_validator(mode="after")
    def validate_change(self):
        if self.new_password != self.new_password2:
            raise ValueError("两次输入的新密码不一致")
        if self.current_password == self.new_password:
            raise ValueError("新密码不能与当前密码相同")
        validate_password_by_policy(self.new_password)
        return self


# ---------- 项目 ----------

class ProjectBase(BaseModel):
    name: str
    description: Optional[str] = ""


class ProjectCreate(ProjectBase):
    pass


class ProjectOut(ProjectBase):
    id: int
    owner_id: int
    created_at: datetime

    class Config:
        from_attributes = True


# ---------- 实验记录 ----------

class NoteBase(BaseModel):
    title: str
    content: Optional[str] = ""
    project_id: Optional[int] = None


class NoteCreate(NoteBase):
    pass


class NoteOut(NoteBase):
    id: int
    author_id: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# ---------- 文件 ----------

class FileOut(BaseModel):
    id: int
    filename: str
    original_name: str
    uploader_id: int
    created_at: datetime

    class Config:
        from_attributes = True


# ---------- 设备与预约 ----------

class DeviceCreate(BaseModel):
    name: str
    location: str = ""
    description: str = ""


class DeviceOut(DeviceCreate):
    id: int

    class Config:
        from_attributes = True


class ReservationCreate(BaseModel):
    device_id: int
    start_time: datetime
    end_time: datetime


class ReservationOut(BaseModel):
    id: int
    device_id: int
    user_id: int
    start_time: datetime
    end_time: datetime
    created_at: datetime

    class Config:
        from_attributes = True


# ---------- 忘记密码 ----------

class ForgotPasswordRequest(BaseModel):
    email: EmailStr

class ForgotPasswordVerify(BaseModel):
    email: EmailStr
    code: str

class ForgotPasswordReset(BaseModel):
    reset_token: str
    new_password: str = Field(min_length=6)
    new_password2: str

    @model_validator(mode="after")
    def validate_reset(self):
        if self.new_password != self.new_password2:
            raise ValueError("两次输入的密码不一致")
        validate_password_by_policy(self.new_password)
        return self

# ---------- daily papers ----------
class HitPaper(BaseModel):
    title: str = ""
    link: Optional[str] = None
    published: Optional[str] = None
    doi: Optional[str] = None
    authors: List[str] = []

class DigestListItem(BaseModel):
    id: int
    date: str              # "2026-01-09"
    time: Optional[str] = None
    journal: str
    code: Optional[str] = None
    category: Optional[str] = None
    title: Optional[str] = None

    # ✅ 新增：关键词搜索命中的文章摘要信息（列表页展示用）
    hit_count: int = 0
    hit_papers: List[HitPaper] = []

class DigestListResponse(BaseModel):
    items: List[DigestListItem]

class PaperItem(BaseModel):
    title: str
    link: Optional[str] = None
    published: Optional[str] = None
    doi: Optional[str] = None
    authors: List[str] = []

    summary_html: Optional[str] = None
    summary_text: Optional[str] = None

    abstract_raw: Optional[str] = None
    abstract_text: Optional[str] = None

    source: Optional[str] = None

class DigestDetailResponse(BaseModel):
    id: int
    title: str
    content: str
    date: str
    journal: str
    papers: List[PaperItem] = []
