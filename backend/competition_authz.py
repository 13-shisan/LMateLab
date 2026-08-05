from __future__ import annotations

import os
from collections.abc import Mapping

from fastapi import Depends, HTTPException, Request, status

from auth_identity import get_current_user
from models import User


COMPETITION_ROLES = frozenset({"operator", "viewer"})
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


def _role(current_user: User) -> str:
    return str(getattr(current_user, "role", "") or "").strip().lower()


def require_roles(*allowed_roles: str):
    allowed = frozenset(str(role).strip().lower() for role in allowed_roles)

    def dependency(current_user: User = Depends(get_current_user)) -> User:
        if _role(current_user) not in allowed:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="competition role is not permitted",
            )
        return current_user

    return dependency


_operator_guard = require_roles("operator")
_viewer_or_operator_guard = require_roles("viewer", "operator")


def require_operator(current_user: User = Depends(get_current_user)) -> User:
    return _operator_guard(current_user)


def require_viewer_or_operator(current_user: User = Depends(get_current_user)) -> User:
    return _viewer_or_operator_guard(current_user)


def require_business_access(
    request: Request,
    current_user: User = Depends(get_current_user),
) -> User:
    current_user = require_viewer_or_operator(current_user)
    if request.method.upper() not in SAFE_METHODS:
        current_user = require_operator(current_user)
    return current_user


def _environment(environ: Mapping[str, str] | None) -> Mapping[str, str]:
    return os.environ if environ is None else environ


def is_competition_edition(environ: Mapping[str, str] | None = None) -> bool:
    return _environment(environ).get("LMATELAB_EDITION", "").strip().lower() == "107cup"


def require_account_changes_enabled(
    environ: Mapping[str, str] | None = None,
    feature_flag: str | None = None,
) -> None:
    values = _environment(environ)
    disabled_by_flag = feature_flag is not None and values.get(feature_flag, "1").strip() != "1"
    if is_competition_edition(values) or disabled_by_flag:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="account changes are disabled for this edition",
        )


def require_competition_role(
    current_user: User,
    environ: Mapping[str, str] | None = None,
) -> User:
    if is_competition_edition(environ):
        return require_viewer_or_operator(current_user)
    return current_user


def require_current_edition_user(
    current_user: User = Depends(get_current_user),
) -> User:
    return require_competition_role(current_user)
