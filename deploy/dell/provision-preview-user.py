#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import secrets
from pathlib import Path

from database import Base, SessionLocal, engine
from models import User
from auth import hash_password


def main() -> int:
    email = os.environ.get("LMATELAB_PREVIEW_EMAIL", "zhuxiping@mail.ustc.edu.cn")
    alias = os.environ.get("LMATELAB_PREVIEW_ALIAS", "Pzxp")
    config_dir = Path(os.environ["LMATELAB_CONFIG_DIR"])
    credential_path = config_dir / "web-login.json"
    config_dir.mkdir(mode=0o700, parents=True, exist_ok=True)

    Base.metadata.create_all(bind=engine)
    password = secrets.token_urlsafe(18)
    with SessionLocal() as session:
        user = session.query(User).filter(User.email == email).one_or_none()
        if user is None:
            user = User(
                email=email,
                password_hash=hash_password(password),
                name="Joo",
                alias=alias,
                role="operator",
            )
            session.add(user)
        else:
            user.password_hash = hash_password(password)
            user.role = "operator"
            user.alias = alias
        session.commit()

    credential_path.write_text(
        json.dumps({"email": email, "password": password}, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    credential_path.chmod(0o600)
    print(f"preview credentials written to {credential_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
