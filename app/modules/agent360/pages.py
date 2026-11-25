"""상담사 360 화면 라우터 (/agent360/...). 로직은 views.py, 여기서는 연결만."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from starlette.datastructures import UploadFile

from app.core.data import get_backend
from app.core.deps import current_user, dev_users
from app.core.errors import InvalidInput, PermissionDenied
from app.core.modules import discover
from app.core.permissions import User
from app.core.templating import render
from app.modules.agent360 import views
from app.modules.agent360.services import coaching as coaching_svc
from app.modules.agent360.services import qa_coaching as qa_svc
from app.modules.agent360.wiring import change_service

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


def _qa_changes():
    below = float(_module().screens["screens"]["qa"].get("need_below", qa_svc.NEED_BELOW))
    return change_service(get_backend(), need_below=below)


def _qa_page(user: User, change: str | None = None, status_code: int = 200, **extra) -> HTMLResponse:
    ctx = views.qa(get_backend(), user, _module().screens, _qa_changes(), change)
    return _page("agent360/qa.html", {"errors": {}, **ctx, **extra}, user, "qa", status_code)


@router.get("/qa", response_class=HTMLResponse)
def qa(change: str | None = None, user: User = Depends(current_user)):
    return _qa_page(user, change)


@router.post("/qa/upload", response_class=HTMLResponse)
async def qa_upload(request: Request, user: User = Depends(current_user)):
    """코칭 대시보드 zip → 미리보기 (저장은 승인 후)."""
    if not user.can("qa.upload"):
        raise PermissionDenied("QA·코칭 올리기 권한이 없습니다.")
    form = await request.form()
    f = form.get("file")
    try:
        if not isinstance(f, UploadFile) or not f.filename:
            raise InvalidInput({"file": "파일을 골라 주세요."})
        rows = qa_svc.per_agent(qa_svc.read_zip(await f.read()))
        _, missing, dup = qa_svc.match(rows, get_backend().list_agents(user.scope))   # 미리보기에 보여 줄 이름
        ch = _qa_changes().preview(user, qa_svc.QaCoachingUpload.kind,
                                   {"file": f.filename, "rows": rows, "missing": missing, "dup": dup})
    except InvalidInput as e:
        return _qa_page(user, errors=e.errors, status_code=400)
    return RedirectResponse(f"/agent360/qa?change={ch.change_id}#preview", status_code=303)


@router.post("/qa/changes/{change_id}/{action}")
def qa_act(change_id: str, action: str, user: User = Depends(current_user)):
    svc = _qa_changes()
    do = {"approve": svc.approve, "undo": svc.undo, "discard": svc.discard}.get(action)
    if do is None:
        return RedirectResponse("/agent360/qa", status_code=303)
    try:
        do(user, change_id)
    except InvalidInput as e:
        return _qa_page(user, errors=e.errors, status_code=400)
    return RedirectResponse("/agent360/qa", status_code=303)
