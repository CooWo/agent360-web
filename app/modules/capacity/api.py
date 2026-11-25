"""Capacity API (/api/capacity/...). 화면과, 나중에 Capacity AI 어시스턴트 도구(C-14)가 쓴다.

데이터 변경은 종류(kind)와 상관없이 같은 네 단계: preview → approve | discard → undo
"""
from __future__ import annotations

from fastapi import APIRouter, Body, Depends

from app.core.data import get_backend
from app.core.deps import current_user
from app.core.modules import discover
from app.core.permissions import User
from app.modules.capacity import views
from app.modules.capacity.data import get_store
from app.modules.capacity.wiring import change_service

router = APIRouter(prefix="/api/capacity", tags=["capacity"])


def _screens():
    return next(m for m in discover() if m.name == "capacity").screens


@router.get("/fte")
def fte_weekly(user: User = Depends(current_user)):
    """주별 필요·가용 FTE 와 갭 (채널 합계 + 이번 주 채널별). 숫자는 계산 엔진 결과 그대로."""
    ctx = views.home(get_backend(), get_store(), user, _screens())
    return {k: ctx[k] for k in ("as_of", "week", "now", "shortage", "totals", "channels", "assumptions")}


@router.get("/changes")
def changes(kind: str | None = None, user: User = Depends(current_user)):
    return [c.to_dict() for c in change_service().history(user, kind)]


@router.post("/changes/{kind}/preview")
def change_preview(kind: str, payload: dict = Body(...), user: User = Depends(current_user)):
    return change_service().preview(user, kind, payload).to_dict()


@router.post("/changes/{change_id}/approve")
def change_approve(change_id: str, user: User = Depends(current_user)):
    return change_service().approve(user, change_id).to_dict()


@router.post("/changes/{change_id}/discard")
def change_discard(change_id: str, user: User = Depends(current_user)):
    return change_service().discard(user, change_id).to_dict()


@router.post("/changes/{change_id}/undo")
def change_undo(change_id: str, user: User = Depends(current_user)):
    return change_service().undo(user, change_id).to_dict()
