"""API 요청·응답 형식 — /api/docs 에 자동으로 문서화된다 (기획안 7장 '요청·응답 형식 문서화')."""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class Loose(BaseModel):
    model_config = ConfigDict(extra="allow")


class UserOut(BaseModel):
    email: str
    name: str
    role: str = Field(description="admin | manager | sv | viewer")
    teams: list[str]


class AgentOut(Loose):
    agent_id: str = Field(description="사번 (상담사 키 · 조회 기준)")
    ldap: str | None = Field(default=None, description="LDAP (상담 데이터 연결용)")
    name: str
    team: str
    sv_email: str | None = None
    hire_date: str | None = None
    cohort: str | None = None
    skill_tags: list[str] = []
    status: str | None = None


class SignalOut(Loose):
    signal_id: str
    agent_id: str
    type: str | None = None
    label: str | None = None
    severity: str | None = Field(default=None, description="상 | 중 | 하")
    score: int | None = None
    evidence: str | None = None
    status: str = Field(description="미확인 | 확인 | 코칭 예정 | 해당 없음")


class RankedAgentOut(BaseModel):
    agent: AgentOut
    score: int = Field(description="심각도 점수 합 (해당 없음 처리 제외)")
    open: int = Field(description="미확인 신호 수")
    signals: list[SignalOut]


class SignalStatusIn(BaseModel):
    status: str = Field(description="미확인 | 확인 | 코칭 예정 | 해당 없음")


class CoachingIn(BaseModel):
    agent_id: str
    date: str = Field(description="YYYY-MM-DD")
    issue_type: str = Field(description="issue_types 목록 중 하나")
    summary: str
    agreed_action: str
    follow_up_date: str = Field(description="YYYY-MM-DD, 코칭 일자 이후")
    raw_note: str = Field(default="", description="자유 입력 원문 (6단계에서 AI 구조화 입력)")


class CoachingOut(Loose):
    coaching_id: str
    agent_id: str
    sv_email: str | None = None
    date: str
    issue_type: str
    summary: str
    agreed_action: str
    follow_up_date: str
    done: bool
