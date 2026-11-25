"""Capacity 화면 라우터 (/capacity/...). 로직은 views.py, 여기서는 연결만."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import HTMLResponse

from app.core.data import get_backend
from app.core.deps import current_user, dev_users
from app.core.modules import discover
from app.core.permissions import User
from app.core.templating import render
from app.modules.capacity import views
from app.modules.capacity.data import get_store

router = APIRouter(prefix="/capacity", include_in_schema=False)
PLACEHOLDERS = ("absence", "cohorts", "simulator", "input", "reports")


def _module():
    return next(m for m in discover() if m.name == "capacity")


def _page(template: str, ctx: dict, user: User, active: str) -> HTMLResponse:
    return HTMLResponse(render(template, ctx, user=user, module=_module(), active=active, users_for_switch=dev_users()))


@router.get("", response_class=HTMLResponse)
def home(user: User = Depends(current_user)):
    return _page("capacity/home.html", views.home(get_backend(), get_store(), user, _module().screens), user, "home")


def _placeholder_route(sid: str):
    def page(user: User = Depends(current_user)):
        return _page("capacity/placeholder.html", views.placeholder(user, _module().screens, sid), user, sid)
    page.__name__ = f"capacity_{sid}"
    return page


for _sid in PLACEHOLDERS:
    router.add_api_route(f"/{_sid}", _placeholder_route(_sid), methods=["GET"], response_class=HTMLResponse)
