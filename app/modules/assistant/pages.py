"""AI 질문 화면 (/assistant)."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import HTMLResponse

from app.core.deps import current_user, dev_users
from app.core.modules import discover
from app.core.permissions import User
from app.core.templating import render
from app.modules.assistant.views import page_context

router = APIRouter(prefix="/assistant", include_in_schema=False)


def _module():
    return next(m for m in discover() if m.name == "assistant")


@router.get("", response_class=HTMLResponse)
def ask_page(user: User = Depends(current_user)):
    m = _module()
    ctx = page_context(user, m.screen("ask"))
    return HTMLResponse(render("assistant/ask.html", ctx, user=user, module=m, active="ask", users_for_switch=dev_users()))
