"""AI 질문 API (/api/assistant/...)."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.core.ai import get_data_agent
from app.core.ai.data_agent import DataAgentError
from app.core.ai.render import answer_html
from app.core.data import get_backend
from app.core.deps import current_user
from app.core.errors import PermissionDenied
from app.core.modules import discover
from app.core.permissions import User
from app.modules.assistant.services import ask as ask_svc

router = APIRouter(prefix="/api/assistant", tags=["assistant"])


class AskIn(BaseModel):
    question: str = Field(description="질문 (1000자 이내)")
    conversation: str | None = Field(default=None, description="이어 묻기용 대화 이름 (직전 응답의 conversation)")
    new: bool = Field(default=False, description="true 면 새 대화로 시작")


def _screen() -> dict:
    return next(m for m in discover() if m.name == "assistant").screen("ask")


@router.post("/ask", summary="데이터 에이전트에게 질문 (답변 HTML·SQL·대화 이름)")
def ask(body: AskIn, user: User = Depends(current_user)):
    try:
        ans = ask_svc.ask(get_backend(), get_data_agent(), user, _screen(), body.question, body.conversation, body.new)
    except DataAgentError as e:
        return JSONResponse({"detail": str(e)}, status_code=e.status if e.status in (400, 401, 403, 404, 429, 503, 504) else 502)
    return {"html": answer_html(ans), "text": ans.text, "sqls": ans.sqls, "notes": ans.notes,
            "conversation": ans.conversation, "mode": ans.mode, "secs": ans.secs}


@router.get("/ping", summary="에이전트 연결 점검 (조회 비용 없음)")
def ping(user: User = Depends(current_user)):
    if not ask_svc.allowed(user, _screen()):
        raise PermissionDenied("AI 질문 권한이 없습니다 (screens.json 의 roles).")
    agent = get_data_agent()
    if agent is None:
        return JSONResponse({"detail": "AI 연결이 설정되지 않았습니다."}, status_code=503)
    try:
        info = agent.info()
    except DataAgentError as e:
        return JSONResponse({"detail": str(e)}, status_code=e.status if e.status < 500 else 502)
    return {"ok": True, "agent": info.get("displayName") or agent.agent_id}
