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
from app.modules.roster.wiring import change_service

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


@router.get("", response_class=HTMLResponse)
def board(user: User = Depends(current_user)):
    return _page("roster/board.html", views.board(get_store(), user, _module().screens), user, "board")


def _info_page(user: User, sync: dict | None = None, sync_error: str = "", status_code: int = 200):
    from datetime import date
    ctx = views.info(get_store(), user, _module().screens, date.today().isoformat())
    return _page("roster/info.html", {**ctx, "sync": sync, "sync_error": sync_error}, user, "info", status_code)


@router.get("/info", response_class=HTMLResponse)
def info(user: User = Depends(current_user)):
    return _info_page(user)


@router.post("/info/sync", response_class=HTMLResponse)
async def info_sync(request: Request, user: User = Depends(current_user)):
    """시트에서 불러오기: mode=check(확인만) | save(저장). 서버의 서비스 계정이 시트를 읽는다."""
    from app.core.audit import audit
    from app.core.data import get_backend
    from app.core.sheets import GoogleSheetReader, SheetAccessError
    from app.modules.roster.data import get_store as _store
    from app.modules.roster.data.info_loader import LoadRefused, info_loader
    from app.modules.roster.services.info_sync import InfoSyncService
    form = await request.form()
    save = form.get("mode") == "save"
    try:
        svc = InfoSyncService(GoogleSheetReader(), info_loader(_store()) if save else None)
        out = views.info_sync(svc, user, _module().screens, dry_run=not save, force=form.get("force") == "1")
    except (SheetAccessError, LoadRefused, ValueError) as e:
        return _info_page(user, sync_error=str(e), status_code=400)
    if save:
        audit(get_backend(), user, "info_sync", "info", out["load_id"] or "", {k: out[k] for k in (
            "rows_read", "rows_mart", "dropped_no_id", "duplicates", "issues")})
    return _info_page(user, sync=out)


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

