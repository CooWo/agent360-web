"""대시보드 라우터 — 화면 /dashboard, AI 브리핑 /api/dashboard/briefing. 로직은 views·services."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import HTMLResponse

from app.core.data import get_backend
from app.core.deps import current_user, dev_users
from app.core.modules import discover
from app.core.permissions import User
from app.core.templating import render
from app.modules.dashboard import views

router = APIRouter(prefix="/dashboard", include_in_schema=False)


def _module():
    return next(m for m in discover() if m.name == "dashboard")


@router.get("", response_class=HTMLResponse)
def dashboard(user: User = Depends(current_user)):
    ctx = views.dashboard(get_backend(), user, _module().screens)
    return HTMLResponse(render("dashboard/dashboard.html", ctx, user=user, module=_module(), active="dashboard",
                               users_for_switch=dev_users()))

