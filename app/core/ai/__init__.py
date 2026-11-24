"""AI 연결 — 지금은 기존 BigQuery 데이터 에이전트(Conversational Analytics API)만.
나중에 Gemini 직접 호출(코칭 메모 정리·브리핑 등)도 이 패키지에 추가한다."""
from __future__ import annotations

from functools import lru_cache

from app.core.config import get_settings


@lru_cache
def get_data_agent():
    """설정이 없으면 None (화면에 '미설정' 표시)."""
    s = get_settings()
    if not s.ai_enabled:
        return None
    from app.core.ai.data_agent import DataAgent
    return DataAgent(s.ai_agent_project, s.ai_agent_location, s.ai_agent_id, s.ai_quota_project, s.ai_timeout)
