"""AI 질문 규칙 — 권한·입력 확인, 에이전트 호출, 감사 로그."""
from __future__ import annotations

from app.core.ai.data_agent import Answer, DataAgent, DataAgentError, conversation_prefix
from app.core.audit import audit
from app.core.errors import InvalidInput, PermissionDenied
from app.core.permissions import User


def allowed(user: User, screen: dict) -> bool:
    return user.role in screen.get("roles", ["admin", "manager", "sv", "viewer"])


def ask(backend, agent: DataAgent | None, user: User, screen: dict, question: str,
        conversation: str | None = None, new: bool = False) -> Answer:
    if not allowed(user, screen):
        raise PermissionDenied("AI 질문 권한이 없습니다 (screens.json 의 roles).")
    q = (question or "").strip()
    limit = int(screen.get("max_question", 1000))
    if not q:
        raise InvalidInput({"question": "질문을 입력해 주세요."})
    if len(q) > limit:
        raise InvalidInput({"question": f"질문은 {limit}자 이내로 써 주세요."})
    if agent is None:
        raise DataAgentError("AI 연결이 설정되지 않았습니다 (.env 의 AI_AGENT_PROJECT / AI_AGENT_ID).", 503)
    detail = {"question": q[:500], "new": bool(new)}
    try:
        ans = agent.ask(q, prefix=conversation_prefix(user.email), conversation=conversation, new=new)
    except DataAgentError as e:
        audit(backend, user, "ai_ask", "data_agent", agent.agent_id, {**detail, "ok": False, "error": str(e)[:300]})
        raise
    audit(backend, user, "ai_ask", "data_agent", agent.agent_id,
          {**detail, "ok": True, "secs": ans.secs, "mode": ans.mode, "sql_count": len(ans.sqls),
           "tables": sum(1 for s in ans.segments if s["type"] == "table")})
    return ans
