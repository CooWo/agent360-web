"""상담사 360 화면 라우터 (/agent360/...). 로직은 views.py, 여기서는 연결만."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.core.data import get_backend
from app.core.deps import current_user, dev_users
from app.core.errors import InvalidInput
from app.core.modules import discover
from app.core.permissions import User
from app.core.templating import render
from app.modules.agent360 import views
from app.modules.agent360.services import coaching as coaching_svc

router = APIRouter(prefix="/agent360", include_in_schema=False)


def _module():
    return next(m for m in discover() if m.name == "agent360")


def _page(template: str, ctx: dict, user: User, active: str, status_code: int = 200) -> HTMLResponse:
    html = render(template, ctx, user=user, module=_module(), active=active, users_for_switch=dev_users())
    return HTMLResponse(html, status_code=status_code)


@router.get("", response_class=HTMLResponse)
def home(user: User = Depends(current_user)):
    return _page("agent360/home.html", views.home(get_backend(), user, _module().screens), user, "home")


@router.get("/agents", response_class=HTMLResponse)
def agents(q: str | None = None, team: str | None = None, user: User = Depends(current_user)):
    return _page("agent360/agents.html", views.agents(get_backend(), user, _module().screens, q=q, team=team), user, "agents")


@router.get("/agents/{agent_id}", response_class=HTMLResponse)
def agent_detail(agent_id: str, saved: int = 0, user: User = Depends(current_user)):
    ctx = views.agent_detail(get_backend(), user, _module().screens, agent_id)
    return _page("agent360/agent_detail.html", {**ctx, "saved": bool(saved)}, user, "agents")


@router.get("/coaching", response_class=HTMLResponse)
def coaching_page(agent_id: str | None = None, user: User = Depends(current_user)):
    return _page("agent360/coaching.html", views.coaching(get_backend(), user, _module().screens, agent_id=agent_id), user, "coaching")


@router.post("/coaching", response_class=HTMLResponse)
async def coaching_save(request: Request, user: User = Depends(current_user)):
    form = dict(await request.form())
    try:
        rec = coaching_svc.create(get_backend(), user, form)
    except InvalidInput as e:
        ctx = views.coaching(get_backend(), user, _module().screens, form=form, errors=e.errors)
        return _page("agent360/coaching.html", ctx, user, "coaching", status_code=400)
    return RedirectResponse(f"/agent360/agents/{rec['agent_id']}?saved=1#coaching", status_code=303)


@router.post("/coaching/{coaching_id}/complete")
def coaching_complete(coaching_id: str, request: Request, user: User = Depends(current_user)):
    coaching_svc.complete(get_backend(), user, coaching_id)
    back = request.headers.get("referer") or "/agent360/coaching"
    return RedirectResponse(back, status_code=303)


@router.get("/admin", response_class=HTMLResponse)
def admin(user: User = Depends(current_user)):
    return _page("agent360/admin.html", views.admin(get_backend(), user, _module().screens), user, "admin")
