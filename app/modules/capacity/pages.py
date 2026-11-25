"""Capacity 화면 라우터 (/capacity/...). 로직은 views·services, 여기서는 연결만."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.core.data import get_backend
from app.core.deps import current_user, dev_users
from app.core.errors import InvalidInput
from app.core.modules import discover
from app.core.permissions import User
from app.core.templating import render
from app.core.uploads import parse_upload
from app.modules.capacity import views
from app.modules.capacity.data import get_store
from app.modules.capacity.services.changes import AssumptionsChange
from app.modules.capacity.wiring import change_service

router = APIRouter(prefix="/capacity", include_in_schema=False)
PLACEHOLDERS = ("absence", "cohorts", "simulator", "reports")


def _module():
    return next(m for m in discover() if m.name == "capacity")


def _page(template: str, ctx: dict, user: User, active: str, status_code: int = 200) -> HTMLResponse:
    html = render(template, ctx, user=user, module=_module(), active=active, users_for_switch=dev_users())
    return HTMLResponse(html, status_code=status_code)


@router.get("", response_class=HTMLResponse)
def home(user: User = Depends(current_user)):
    return _page("capacity/home.html", views.home(get_backend(), get_store(), user, _module().screens), user, "home")


# ── 데이터 입력: 미리보기 → 승인 → 되돌리기 ─────────────
def _input(user: User, preview=None, errors: dict | None = None, status_code: int = 200) -> HTMLResponse:
    ctx = views.input_page(user, _module().screens, change_service(), get_store())
    return _page("capacity/input.html", {**ctx, "preview": preview, "errors": errors or {}}, user, "input", status_code)


@router.get("/input", response_class=HTMLResponse)
def input_page(change: str | None = None, user: User = Depends(current_user)):
    svc = change_service()
    pending = next((c for c in svc.history(user, limit=50) if c.change_id == change and c.status == "preview"), None)
    return _input(user, preview=pending)


@router.post("/input/preview", response_class=HTMLResponse)
async def input_preview(request: Request, user: User = Depends(current_user)):
    form = await request.form()
    try:
        upload = form.get("file")
        if upload is not None and getattr(upload, "filename", ""):
            rows = parse_upload(upload.filename, await upload.read())
        else:
            rows = views.assumption_rows_from_form(dict(form))
        ch = change_service().preview(user, AssumptionsChange.kind, {"rows": rows})
    except InvalidInput as e:
        return _input(user, errors=e.errors, status_code=400)
    return RedirectResponse(f"/capacity/input?change={ch.change_id}", status_code=303)


@router.post("/input/{change_id}/{action}")
def input_action(change_id: str, action: str, user: User = Depends(current_user)):
    svc = change_service()
    do = {"approve": svc.approve, "undo": svc.undo, "discard": svc.discard}.get(action)
    if do is None:
        return RedirectResponse("/capacity/input", status_code=303)
    try:
        do(user, change_id)
    except InvalidInput as e:
        return _input(user, errors=e.errors, status_code=400)
    return RedirectResponse("/capacity/input", status_code=303)


# ── 준비 중 화면 ───────────────────────────────────
def _placeholder_route(sid: str):
    def page(user: User = Depends(current_user)):
        return _page("capacity/placeholder.html", views.placeholder(user, _module().screens, sid), user, sid)
    page.__name__ = f"capacity_{sid}"
    return page


for _sid in PLACEHOLDERS:
    router.add_api_route(f"/{_sid}", _placeholder_route(_sid), methods=["GET"], response_class=HTMLResponse)
