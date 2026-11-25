"""팀 구성 API (/api/roster/...). 다른 도구(시트 동기화, AI 어시스턴트)가 쓴다.
변경은 공통 흐름: preview → approve | discard → undo."""
from __future__ import annotations

from fastapi import APIRouter, Body, Depends

from app.core.deps import current_user
from app.core.errors import NotFound
from app.core.modules import discover
from app.core.permissions import User
from app.modules.roster import views
from app.modules.roster.data import get_store
from app.modules.roster.services import paste
from app.modules.roster.wiring import change_service

router = APIRouter(prefix="/api/roster", tags=["roster"])


def _screens():
    return next(m for m in discover() if m.name == "roster").screens


@router.get("/board")
def board(user: User = Depends(current_user)):
    ctx = views.board(get_store(), user, _screens())
    return {"total": ctx["total"], "groups": ctx["groups"], "warnings": ctx["warnings"], "versions": ctx["versions"]}


@router.post("/parse")
def parse(body: dict = Body(...), user: User = Depends(current_user)):
    """붙여넣을 글자 → 행 (저장 안 함)."""
    return {"rows": paste.parse(str(body.get("text") or ""), str(body.get("tl") or ""))}


@router.post("/changes/preview")
def change_preview(body: dict = Body(...), user: User = Depends(current_user)):
    return change_service().preview(user, "roster.board", {"rows": body.get("rows")}).to_dict()


@router.post("/changes/{change_id}/{action}")
def change_action(change_id: str, action: str, user: User = Depends(current_user)):
    svc = change_service()
    do = {"approve": svc.approve, "undo": svc.undo, "discard": svc.discard}.get(action)
    if do is None:
        raise NotFound("approve · undo · discard 중 하나여야 합니다.")
    return do(user, change_id).to_dict()
