"""상담사 INFO 화면 라우터 (/info). 로직은 views·services, 여기서는 연결만."""
from __future__ import annotations

import json
from datetime import date

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from starlette.datastructures import UploadFile

from app.core.audit import audit
from app.core.data import get_backend
from app.core.deps import current_user, dev_users
from app.core.errors import InvalidInput, PermissionDenied
from app.core.modules import discover
from app.core.permissions import User
from app.core.sheets import GoogleSheetReader, SheetAccessError
from app.core.templating import render
from app.core.uploads import parse_grid, text_grid
from app.modules.info import views
from app.modules.info.services import bulk
from app.modules.info.services.edits import InfoEditChange, effective_info
from app.modules.info.wiring import change_service
from app.modules.roster.data import get_store
from app.modules.roster.data.info_loader import LoadRefused, info_loader, team_loader
from app.modules.roster.services.info_sync import InfoSyncService
from app.modules.roster.services.team_sync import TeamRosterSync

router = APIRouter(prefix="/info", include_in_schema=False)


def _module():
    return next(m for m in discover() if m.name == "info")


def _page(user: User, change: str | None = None, status_code: int = 200, **extra) -> HTMLResponse:
    ctx = views.info(get_store(), user, _module().screens, date.today().isoformat(), change_service(), change)
    html = render("info/info.html", {"sync": None, "sync_error": "", "team": None, "team_error": "", "errors": {},
                                     **ctx, **extra}, user=user,
                  module=_module(), active="info", users_for_switch=dev_users())
    return HTMLResponse(html, status_code=status_code)


@router.get("", response_class=HTMLResponse)
def info(change: str | None = None, user: User = Depends(current_user)):
    return _page(user, change)


@router.post("/sync", response_class=HTMLResponse)
async def sync(request: Request, user: User = Depends(current_user)):
    """시트에서 불러오기 — INFO 자동화 시트 + OPS TL(팀 구성). mode=preview(확인만) | save(저장)."""
    form = await request.form()
    save = form.get("mode") == "save"
    force = form.get("force") == "1"
    reader = GoogleSheetReader()
    extra: dict = {"sync_saved": save}
    try:
        out = views.info_sync(InfoSyncService(reader, info_loader(get_store()) if save else None), user,
                              _module().screens, dry_run=not save, force=force)
        if save:
            audit(get_backend(), user, "info_sync", "info", out["load_id"] or "", {k: out[k] for k in (
                "rows_read", "rows_mart", "dropped_no_id", "duplicates", "issues")})
        extra["sync"] = out
    except (SheetAccessError, LoadRefused, ValueError) as e:
        extra["sync_error"] = str(e)
    try:
        team = views.team_sync(TeamRosterSync(reader, team_loader(get_store()) if save else None), user,
                               _module().screens, dry_run=not save, force=force)
        if save:
            audit(get_backend(), user, "team_sync", "roster", team["load_id"] or "", {"rows": team["rows"],
                                                                                    "tls": len(team["tls"])})
        extra["team"] = team
    except (SheetAccessError, LoadRefused, ValueError) as e:
        extra["team_error"] = str(e)
    return _page(user, status_code=400 if ("sync_error" in extra or "team_error" in extra) else 200, **extra)


@router.post("/team-sync", response_class=HTMLResponse)
async def team_sync(request: Request, user: User = Depends(current_user)):
    """팀 구성(시트 OPS TL) 불러오기: mode=check | save."""
    form = await request.form()
    save = form.get("mode") == "save"
    try:
        svc = TeamRosterSync(GoogleSheetReader(), team_loader(get_store()) if save else None)
        out = views.team_sync(svc, user, _module().screens, dry_run=not save, force=form.get("force") == "1")
    except (SheetAccessError, LoadRefused, ValueError) as e:
        return _page(user, team_error=str(e), status_code=400)
    if save:
        audit(get_backend(), user, "team_sync", "roster", out["load_id"] or "", {"rows": out["rows"], "tls": len(out["tls"])})
    return _page(user, team=out)


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


@router.post("/import", response_class=HTMLResponse)
async def import_table(request: Request, user: User = Depends(current_user)):
    """시트에서 복사한 글(paste) 또는 파일(file: .xlsx/.csv/.tsv). mode=preview → 바뀐 칸만 미리보기,
    mode=save → 미리보기를 거치지 않고 바로 저장 (누른 사람이 승인한 것으로 기록)."""
    if not user.can("info.edit"):
        raise PermissionDenied("상담사 INFO 수정 권한이 없습니다.")
    form = await request.form()
    upload, text = form.get("file"), str(form.get("paste") or "")
    try:
        if isinstance(upload, UploadFile) and upload.filename:
            grid, how = parse_grid(upload.filename, await upload.read()), "file"
        else:
            grid, how = text_grid(text), "paste"
        current = {r["emp_id"] for r in effective_info(get_store())}
        p = bulk.plan(grid, current, user, how)
        svc = change_service()
        ch = svc.preview(user, InfoEditChange.kind, p.payload)
        if form.get("mode") == "save":
            svc.approve(user, ch.change_id)
            return RedirectResponse("/info#history", status_code=303)
    except InvalidInput as e:
        return _page(user, errors=e.errors, paste_text=text[:200_000], status_code=400)
    return RedirectResponse(f"/info?change={ch.change_id}#preview", status_code=303)


@router.post("/changes/{change_id}/{action}")
def act(change_id: str, action: str, user: User = Depends(current_user)):
    svc = change_service()
    do = {"approve": svc.approve, "undo": svc.undo, "discard": svc.discard, "retry": svc.retry}.get(action)
    if do is None:
        return RedirectResponse("/info", status_code=303)
    try:
        do(user, change_id)
    except InvalidInput as e:
        return _page(user, errors=e.errors, status_code=400)
    return RedirectResponse("/info", status_code=303)
