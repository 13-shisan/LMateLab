# backend/digest_models.py
from sqlalchemy import Column, Integer, String, Text, Date, DateTime, UniqueConstraint, Index
from datetime import datetime
from digest_database import DigestBase

class DailyDigest(DigestBase):
    __tablename__ = "daily_digests"

    id = Column(Integer, primary_key=True)
    date = Column(Date, nullable=False)
    journal = Column(String(100), nullable=False)
    code = Column(String(30), nullable=True)
    category = Column(String(100), nullable=True)
    title = Column(String(300), nullable=False)

    # 旧的 content 你可以保留（兼容已有数据）
    content = Column(Text, nullable=False, default="")

    # ✅ 新增：结构化条目（JSON 字符串）
    papers_json = Column(Text, nullable=False, default="[]")

    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("date", "journal", name="uq_daily_digest_date_journal"),
        Index("ix_daily_digests_date", "date"),
        Index("ix_daily_digests_journal", "journal"),
        Index("ix_daily_digests_category", "category"),
        Index("ix_daily_digests_code", "code"),
    )
