"""FastAPI 의존성 — 라우터에서 Depends(current_user) 로 로그인 사용자를 받는다."""
from __future__ import annotations

from fastapi import HTTPException, Request

from app.core.auth import AuthError, NotRegistered, load_user, resolve_email
from app.core.config import get_settings
from app.core.data import get_backend
from app.core.permissions import User


def current_user(request: Request) -> User:
    settings = get_settings()
    try:
        email = resolve_email(request.headers, request.cookies, settings)
    except AuthError as e:
        raise HTTPException(status_code=401, detail=str(e)) from e
    try:
        user = load_user(email, get_backend())
    except NotRegistered as e:
        raise HTTPException(status_code=403, detail=f"등록되지 않은 사용자입니다 ({e.email}). 관리자에게 권한 등록을 요청하세요.") from e
    request.state.user = user
    return user


def dev_users() -> list[dict]:
    """local 에서만 화면 상단 '사용자 전환' 목록."""
    return get_backend().list_users() if get_settings().is_local else []
