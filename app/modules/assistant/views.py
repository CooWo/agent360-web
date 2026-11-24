"""AI 질문 화면에 넘길 데이터 (웹 프레임워크와 무관 — 테스트·미리보기도 같이 씀)."""
from __future__ import annotations

from app.core.ai import get_data_agent
from app.core.config import get_settings
from app.core.errors import PermissionDenied
from app.core.permissions import User
from app.modules.assistant.services import ask as ask_svc


def page_context(user: User, screen: dict) -> dict:
    if not ask_svc.allowed(user, screen):
        raise PermissionDenied("AI 질문 권한이 없습니다 (screens.json 의 roles).")
    s = get_settings()
    return {"screen": screen, "ai_enabled": get_data_agent() is not None, "agent_label": s.ai_agent_label,
            "agent_project": s.ai_agent_project}
