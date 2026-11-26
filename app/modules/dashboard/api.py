"""대시보드 API (/api/dashboard/...)."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.core.data import get_backend
from app.core.deps import current_user
from app.core.modules import discover
from app.core.permissions import User
from app.modules.dashboard import views

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


def _module():
    return next(m for m in discover() if m.name == "dashboard")


class BriefIn(BaseModel):
    refresh: bool = False


@router.post("/briefing", summary="대시보드 AI 브리핑 (화면 숫자 → AI BA CHAT 요약, 팀 이름은 가명)")
def briefing(body: BriefIn, user: User = Depends(current_user)):
    from app.core.ai import get_data_agent
    from app.core.ai.data_agent import DataAgentError
    from app.modules.agent360.services import briefing as brief_svc
    from app.modules.dashboard.services.summary import briefing_prompt
    b = get_backend()
    ctx = views.dashboard(b, user, _module().screens)
    alias = brief_svc.Alias()
    prompt = briefing_prompt(ctx, alias)
    screen = next(m for m in discover() if m.name == "assistant").screen("ask")
    try:
        return brief_svc.brief(b, get_data_agent(), user, screen, f"dashboard:{ctx['as_of']}", prompt, alias, body.refresh)
    except DataAgentError as e:
        return JSONResponse({"detail": str(e)}, status_code=e.status if e.status in (400, 401, 403, 404, 429, 503, 504) else 502)
