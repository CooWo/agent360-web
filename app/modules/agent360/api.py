"""상담사 360 API (/api/agent360/...). 화면의 버튼과, 나중에 Capacity Web AI 어시스턴트 도구가 쓴다."""
from __future__ import annotations

from datetime import date, timedelta

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from app.core.data import get_backend
from app.core.deps import current_user
from app.core.errors import NotFound
from app.core.modules import discover
from app.core.permissions import User
from app.modules.agent360 import schemas
from app.modules.agent360.services import coaching as coaching_svc
from app.modules.agent360.services import kpi as kpi_svc
from app.modules.agent360.services import signals as signal_svc

router = APIRouter(prefix="/api/agent360", tags=["agent360"])


@router.get("/me", response_model=schemas.UserOut, summary="로그인 사용자와 역할")
def me(user: User = Depends(current_user)):
    return {"email": user.email, "name": user.name, "role": user.role, "teams": list(user.teams)}


@router.get("/agents", response_model=list[schemas.AgentOut], summary="상담사 목록 (권한 범위 안)")
def list_agents(q: str | None = None, team: str | None = None, user: User = Depends(current_user)):
    return get_backend().list_agents(user.scope, q=q, team=team)


@router.get("/agents/{agent_id}", summary="상담사 360 요약 (주차별 KPI·근태·신호)")
def agent_summary(agent_id: str, weeks: int = 8, user: User = Depends(current_user)):
    b = get_backend()
    agent = b.get_agent(user.scope, agent_id)
    if not agent:
        raise NotFound("상담사를 찾을 수 없거나 권한 밖입니다.")
    as_of = b.as_of()
    since = (date.fromisoformat(as_of) - timedelta(days=7 * weeks + 7)).isoformat()
    att = kpi_svc.attendance_summary(b.attendance(agent_id, since), as_of, 30)
    return {
        "agent": agent, "as_of": as_of,
        "weekly_kpi": kpi_svc.weekly(b.kpi_daily(agent_id, since), as_of, weeks),
        "attendance_30d": {"absent": att["absent"], "late": att["late"], "leave": att["leave"]},
        "signals": [s for s in b.signals(user.scope) if s["agent_id"] == agent_id],
    }


@router.get("/signals/today", response_model=list[schemas.RankedAgentOut], summary="오늘 볼 상담사 (점수 순)")
def signals_today(limit: int = 50, user: User = Depends(current_user)):
    return signal_svc.by_agent(get_backend(), user)[:limit]


@router.post("/signals/{signal_id}/status", response_model=schemas.SignalOut, summary="신호 처리 상태 변경")
def signal_status(signal_id: str, body: schemas.SignalStatusIn, user: User = Depends(current_user)):
    return signal_svc.set_status(get_backend(), user, signal_id, body.status)


@router.get("/coaching", response_model=list[schemas.CoachingOut], summary="코칭 기록 (담당 팀)")
def list_coaching(agent_id: str | None = None, user: User = Depends(current_user)):
    rows = get_backend().coaching(user.scope, agent_id=agent_id)
    return [c for c in rows if user.can_view_sensitive(c["team"])]


@router.post("/coaching", response_model=schemas.CoachingOut, status_code=201, summary="코칭 기록 저장")
def create_coaching(body: schemas.CoachingIn, user: User = Depends(current_user)):
    cats = next(m for m in discover() if m.name == "agent360").screens["screens"]["coaching"].get("categories")
    return coaching_svc.create(get_backend(), user, body.model_dump(), cats)


@router.post("/coaching/{coaching_id}/complete", response_model=schemas.CoachingOut, summary="후속 확인 완료")
def complete_coaching(coaching_id: str, user: User = Depends(current_user)):
    rec = coaching_svc.complete(get_backend(), user, coaching_id)
    full = [c for c in get_backend().coaching(user.scope) if c["coaching_id"] == coaching_id]
    return full[0] if full else JSONResponse(rec)
