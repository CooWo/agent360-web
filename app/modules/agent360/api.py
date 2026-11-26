"""상담사 360 API (/api/agent360/...). 화면의 버튼과, 나중에 Capacity Web AI 어시스턴트 도구가 쓴다."""
from __future__ import annotations

from datetime import date, timedelta

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

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


class BriefIn(BaseModel):
    kind: str = Field(description="home = 오늘 볼 상담사 아침 브리핑, agent = 상담사 한 명 요약")
    agent_id: str | None = None
    refresh: bool = Field(default=False, description="true 면 캐시를 쓰지 않고 다시 묻기")


def templates_detractor_head(facts: dict, since: str, as_of: str) -> str:
    """디트랙터 건수 줄 (SQL 결과로 서버가 만든 숫자 — AI 가 만든 숫자가 아님)."""
    import html as h
    rate = f" ({facts['rate']:.0f}%)" if facts["rate"] is not None else ""
    wk = " · ".join(f"{w[5:]} {n}" for w, n in facts["weekly"]) or "없음"
    cr = " · ".join(f"{h.escape(k)} {v}" for k, v in facts["by_cr"]) or "–"
    return (f'<p><b>디트랙터 {facts["detractors"]}건</b> / 응답 {facts["responses"]}건{rate} '
            f'<span class="muted">({since} ~ {as_of})</span></p>'
            f'<p class="muted">주차별(토 마감): {wk}<br>문의 유형: {cr}</p>')


@router.post("/briefing", summary="AI 브리핑 — 화면 숫자를 AI BA CHAT 에 보내 요약 (이름은 가명으로)")
def briefing(body: BriefIn, user: User = Depends(current_user)):
    from app.core.ai import get_data_agent
    from app.core.ai.data_agent import DataAgentError
    from app.modules.agent360 import views
    from app.modules.agent360.services import briefing as brief_svc
    b = get_backend()
    screens = next(m for m in discover() if m.name == "agent360").screens
    screen = next(m for m in discover() if m.name == "assistant").screen("ask")
    alias = brief_svc.Alias()
    if body.kind == "detractor" and body.agent_id:
        a = b.get_agent(user.scope, body.agent_id)
        if not a:
            raise NotFound("상담사를 찾을 수 없거나 권한 밖입니다.")
        if not a.get("ldap"):
            return JSONResponse({"detail": "이 상담사의 LDAP 이 없어 디트랙터를 찾을 수 없습니다 (상담사 INFO 확인)."}, status_code=400)
        as_of = b.as_of()
        since = (date.fromisoformat(as_of) - timedelta(days=7 * brief_svc.DETRACTOR_WEEKS)).isoformat()
        facts = brief_svc.detractor_facts(b.surveys(a["ldap"], since))
        head = templates_detractor_head(facts, since, as_of)
        if not facts["comments"]:
            return {"html": head + '<p class="muted">요약할 디트랙터 코멘트가 없습니다.</p>', "secs": 0, "cached": False,
                    "asked_at": "", "facts": {k: facts[k] for k in ("responses", "detractors")}}
        prompt, key = brief_svc.detractor_prompt(facts, as_of), f"detractor:{body.agent_id}:{as_of}"
        try:
            out = brief_svc.brief(b, get_data_agent(), user, screen, key, prompt, alias, body.refresh)
        except DataAgentError as e:
            return JSONResponse({"detail": str(e)}, status_code=e.status if e.status in (400, 401, 403, 404, 429, 503, 504) else 502)
        return {**out, "html": head + out["html"], "facts": {k: facts[k] for k in ("responses", "detractors")}}
    elif body.kind == "agent" and body.agent_id:
        ctx = views.agent_detail(b, user, screens, body.agent_id, audit_view=False)
        prompt, key = brief_svc.agent_prompt(ctx, alias), f"agent:{body.agent_id}:{ctx['as_of']}"
    else:
        ctx = views.home(b, user, screens)
        prompt, key = brief_svc.home_prompt(ctx, alias), f"home:{ctx['as_of']}"
    try:
        return brief_svc.brief(b, get_data_agent(), user, screen, key, prompt, alias, body.refresh)
    except DataAgentError as e:
        return JSONResponse({"detail": str(e)}, status_code=e.status if e.status in (400, 401, 403, 404, 429, 503, 504) else 502)
