"""상담사 INFO 화면 라우터 (/info). 로직은 views·services, 여기서는 연결만."""
from __future__ import annotations

import json
from datetime import date

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.core.audit import audit
from app.core.data import get_backend
from app.core.deps import current_user, dev_users
from app.core.errors import InvalidInput
from app.core.modules import discover
from app.core.permissions import User
from app.core.sheets import GoogleSheetReader, SheetAccessError
from app.core.templating import render
from app.modules.info import views
from app.modules.info.services.edits import InfoEditChange
from app.modules.info.wiring import change_service
from app.modules.roster.data import get_store
from app.modules.roster.data.info_loader import LoadRefused, info_loader
from app.modules.roster.services.info_sync import InfoSyncService

router = APIRouter(prefix="/info", include_in_schema=False)


def _module():
    return next(m for m in discover() if m.name == "info")


def _page(user: User, change: str | None = None, status_code: int = 200, **extra) -> HTMLResponse:
    ctx = views.info(get_store(), user, _module().screens, date.today().isoformat(), change_service(), change)
    html = render("info/info.html", {"sync": None, "sync_error": "", "errors": {}, **ctx, **extra}, user=user,
                  module=_module(), active="info", users_for_switch=dev_users())
    return HTMLResponse(html, status_code=status_code)


@router.get("", response_class=HTMLResponse)
def info(change: str | None = None, user: User = Depends(current_user)):
    return _page(user, change)


@router.post("/sync", response_class=HTMLResponse)
async def sync(request: Request, user: User = Depends(current_user)):
    """시트에서 불러오기: mode=check(확인만) | save(저장). 서버의 서비스 계정이 시트를 읽는다."""
    form = await request.form()
    save = form.get("mode") == "save"
    try:
        svc = InfoSyncService(GoogleSheetReader(), info_loader(get_store()) if save else None)
        out = views.info_sync(svc, user, _module().screens, dry_run=not save, force=form.get("force") == "1")
    except (SheetAccessError, LoadRefused, ValueError) as e:
        return _page(user, sync_error=str(e), status_code=400)
    if save:
        audit(get_backend(), user, "info_sync", "info", out["load_id"] or "", {k: out[k] for k in (
            "rows_read", "rows_mart", "dropped_no_id", "duplicates", "issues")})
    return _page(user, sync=out)


@router.post("/preview", response_class=HTMLResponse)
async def preview(request: Request, user: User = Depends(current_user)):
    form = await request.form()
    try:
        payload = json.loads(form.get("payload_json") or "{}")
        ch = change_service().preview(user, InfoEditChange.kind, payload)
    except json.JSONDecodeError:
        return _page(user, errors={"payload": "화면 데이터를 읽지 못했습니다. 새로고침 후 다시 해 주세요."}, status_code=400)
    except InvalidInput as e:
        return _page(user, errors=e.errors, status_code=400)
    return RedirectResponse(f"/info?change={ch.change_id}#preview", status_code=303)


@router.post("/changes/{change_id}/{action}")
def act(change_id: str, action: str, user: User = Depends(current_user)):
    svc = change_service()
    do = {"approve": svc.approve, "undo": svc.undo, "discard": svc.discard}.get(action)
    if do is None:
        return RedirectResponse("/info", status_code=303)
    try:
        do(user, change_id)
    except InvalidInput as e:
        return _page(user, errors=e.errors, status_code=400)
    return RedirectResponse("/info", status_code=303)
