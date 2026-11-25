"""팀 구성 화면 라우터 (/roster/...). 로직은 views·services, 여기서는 연결만."""
from __future__ import annotations

import json

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.core.deps import current_user, dev_users
from app.core.errors import InvalidInput, PermissionDenied
from app.core.modules import discover
from app.core.permissions import User
from app.core.templating import render
from app.modules.roster import views
from app.modules.roster.data import get_store
from app.modules.roster.services import paste
from app.modules.roster.services.board import merge_paste
from app.modules.roster.services.changes import BoardChange
from app.modules.roster.services.team_edit import TeamRosterEdit
from app.modules.roster.wiring import change_service, team_change_service, team_sheet_cfg

router = APIRouter(prefix="/roster", include_in_schema=False)
WS = "/roster/workspace"


def _module():
    return next(m for m in discover() if m.name == "roster")


def _page(template: str, ctx: dict, user: User, active: str, status_code: int = 200) -> HTMLResponse:
    html = render(template, ctx, user=user, module=_module(), active=active, users_for_switch=dev_users())
    return HTMLResponse(html, status_code=status_code)


def _ws(user: User, change: str | None = None, errors: dict | None = None, status_code: int = 200):
    ctx = views.workspace(get_store(), user, _module().screens, change_service(), change, errors)
    return _page("roster/workspace.html", ctx, user, "workspace", status_code)


def _rows(form) -> list[dict]:
    try:
        rows = json.loads(form.get("rows_json") or "[]")
    except json.JSONDecodeError as e:
        raise InvalidInput({"rows": "화면 데이터를 읽지 못했습니다. 새로고침 후 다시 해 주세요."}) from e
    if not isinstance(rows, list):
        raise InvalidInput({"rows": "화면 데이터 형식이 올바르지 않습니다."})
    return rows


def _save_draft(user: User, rows: list[dict]) -> None:
    if not user.can("roster.edit"):
        raise PermissionDenied("팀 구성 수정 권한이 없습니다.")
    get_store().save_draft(user.email, rows)


def _board(user: User, change: str | None = None, errors: dict | None = None, status_code: int = 200):
    ctx = views.team_board(get_store(), user, _module().screens, team_change_service(), change, errors,
                           sheet=team_sheet_cfg())
    return _page("roster/board.html", ctx, user, "board", status_code)


@router.get("", response_class=HTMLResponse)
def board(change: str | None = None, user: User = Depends(current_user)):
    """TL별 명단 — 원본 시트 팀구성-New 와 같은 모양. 고칠 수 있는 사람은 칸을 바로 고친다."""
    return _board(user, change)


@router.post("/edit", response_class=HTMLResponse)
async def edit(request: Request, user: User = Depends(current_user)):
    """mode=preview → 바뀐 것 미리보기, mode=save → 바로 저장(누른 사람이 승인). 저장 = team_roster + 원본 시트."""
    form = await request.form()
    svc = team_change_service()
    try:
        ch = svc.preview(user, TeamRosterEdit.kind, {"rows": _rows(form)})
        if form.get("mode") == "save":
            svc.approve(user, ch.change_id)
            return RedirectResponse("/roster#history", status_code=303)
    except InvalidInput as e:
        return _board(user, errors=e.errors, status_code=400)
    return RedirectResponse(f"/roster?change={ch.change_id}#preview", status_code=303)


@router.post("/changes/{change_id}/{action}")
def team_act(change_id: str, action: str, user: User = Depends(current_user)):
    svc = team_change_service()
    do = {"approve": svc.approve, "undo": svc.undo, "discard": svc.discard, "retry": svc.retry}.get(action)
    if do is None:
        return RedirectResponse("/roster", status_code=303)
    try:
        do(user, change_id)
    except InvalidInput as e:
        return _board(user, errors=e.errors, status_code=400)
    return RedirectResponse("/roster#history", status_code=303)


@router.get("/workspace", response_class=HTMLResponse)
def workspace(change: str | None = None, user: User = Depends(current_user)):
    return _ws(user, change)


@router.post("/workspace/save")
async def save(request: Request, user: User = Depends(current_user)):
    form = await request.form()
    try:
        _save_draft(user, _rows(form))
    except InvalidInput as e:
        return _ws(user, errors=e.errors, status_code=400)
    return RedirectResponse(f"{WS}?saved=1", status_code=303)


@router.post("/workspace/paste")
async def paste_rows(request: Request, user: User = Depends(current_user)):
    form = await request.form()
    try:
        rows = _rows(form)
        pasted = paste.parse(str(form.get("paste") or ""), str(form.get("tl") or "").strip())
        _save_draft(user, merge_paste(rows, pasted, form.get("replace_all") == "1"))
    except InvalidInput as e:
        return _ws(user, errors=e.errors, status_code=400)
    return RedirectResponse(WS, status_code=303)


@router.post("/workspace/preview")
async def preview(request: Request, user: User = Depends(current_user)):
    form = await request.form()
    try:
        rows = _rows(form)
        _save_draft(user, rows)
        ch = change_service().preview(user, BoardChange.kind, {"rows": rows})
    except InvalidInput as e:
        return _ws(user, errors=e.errors, status_code=400)
    return RedirectResponse(f"{WS}?change={ch.change_id}", status_code=303)


@router.post("/workspace/reset")
def reset(user: User = Depends(current_user)):
    if not user.can("roster.edit"):
        raise PermissionDenied("팀 구성 수정 권한이 없습니다.")
    get_store().clear_draft(user.email)
    return RedirectResponse(WS, status_code=303)


@router.post("/workspace/{change_id}/{action}")
def act(change_id: str, action: str, user: User = Depends(current_user)):
    svc = change_service()
    do = {"approve": svc.approve, "undo": svc.undo, "discard": svc.discard}.get(action)
    if do is None:
        return RedirectResponse(WS, status_code=303)
    try:
        do(user, change_id)
    except InvalidInput as e:
        return _ws(user, errors=e.errors, status_code=400)
    return RedirectResponse(WS if action != "approve" else "/roster", status_code=303)

