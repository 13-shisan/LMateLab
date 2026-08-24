import hashlib
import hmac
import os

import jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from database import get_db
from models import User


JWT_SECRET = os.getenv("JWT_SECRET")
JWT_ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")

security = HTTPBearer(auto_error=False)


def password_token_version(password_hash: str) -> str:
    if not JWT_SECRET:
        raise RuntimeError("JWT_SECRET 未配置（请在后端 .env 中设置）")
    return hmac.new(
        JWT_SECRET.encode("utf-8"),
        str(password_hash).encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def get_current_user(
    creds: HTTPAuthorizationCredentials | None = Depends(security),
    db: Session = Depends(get_db),
) -> User:
    if creds is None:
        raise HTTPException(status_code=401, detail="未登录")
    if not JWT_SECRET:
        raise RuntimeError("JWT_SECRET 未配置（请在后端 .env 中设置）")
    try:
        payload = jwt.decode(creds.credentials, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        user_id = payload.get("sub")
        token_password_version = payload.get("pwdv")
        if not user_id:
            raise HTTPException(status_code=401, detail="无效令牌")
    except jwt.PyJWTError as exc:
        raise HTTPException(status_code=401, detail="认证失败") from exc

    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=401, detail="用户不存在")
    if not isinstance(token_password_version, str) or not hmac.compare_digest(
        token_password_version,
        password_token_version(user.password_hash),
    ):
        raise HTTPException(status_code=401, detail="登录状态已失效，请重新登录")
    return user
