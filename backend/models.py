# backend/models.py
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Text, text, Boolean, Date, UniqueConstraint
from sqlalchemy.orm import relationship
from datetime import datetime
from database import Base


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)

    # ✅ 邮箱全局唯一：一个邮箱只能注册一个账号
    email = Column(String, unique=True, index=True, nullable=False)
    password_hash = Column(String, nullable=False)

    # ✅ 中文姓名唯一：一个用户（按姓名）只能注册一次
    name = Column(String, unique=True, index=True, nullable=False)  # 中文姓名

    alias = Column(String, nullable=False, default="", server_default=text("''"))  # 英文缩写
    role = Column(String, default="user", nullable=False)

    created_at = Column(DateTime, default=datetime.utcnow)

class PasswordResetCode(Base):
    __tablename__ = "password_reset_codes"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, index=True, nullable=False)  # 发给哪个邮箱（规范化后）
    code_hash = Column(String, nullable=False)          # 验证码哈希（不存明文）
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    expires_at = Column(DateTime, nullable=False)
    used = Column(Boolean, default=False, nullable=False)
    attempts = Column(Integer, default=0, nullable=False)  # 防爆破

class Project(Base):
    __tablename__ = "projects"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    description = Column(Text, default="")
    owner_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)


class Note(Base):
    __tablename__ = "notes"

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=True)
    title = Column(String, nullable=False)
    content = Column(Text, default="")
    author_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow)


class FileRecord(Base):
    __tablename__ = "files"

    id = Column(Integer, primary_key=True, index=True)
    filename = Column(String, nullable=False)        # 服务器上的文件名
    original_name = Column(String, nullable=False)   # 上传时的原始文件名
    uploader_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)


class Device(Base):
    __tablename__ = "devices"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    location = Column(String, default="")
    description = Column(Text, default="")


class Reservation(Base):
    __tablename__ = "reservations"

    id = Column(Integer, primary_key=True, index=True)
    device_id = Column(Integer, ForeignKey("devices.id"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    start_time = Column(DateTime, nullable=False)
    end_time = Column(DateTime, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    
class DailyDigest(Base):
    __tablename__ = "daily_digests"
    id = Column(Integer, primary_key=True, index=True)

    date = Column(Date, index=True, nullable=False)          # 2026-01-09
    journal = Column(String(100), index=True, nullable=False) # Nature / PRL ...
    code = Column(String(30), index=True, nullable=True)      # Nature / PRL / PRX ...
    category = Column(String(100), index=True, nullable=True)

    title = Column(String(300), nullable=False)
    content = Column(Text, nullable=False)                    # AI 导读正文（或摘要）
    created_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("date", "journal", name="uq_daily_digest_date_journal"),
    )
