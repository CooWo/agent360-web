"""AI 브리핑 — 이름은 가명으로만 보내고 답에서 되돌림, 캐시, 화면 자동 요약 API (가짜 에이전트)."""
import pytest

from app.core.ai.data_agent import Answer
from app.modules.agent360 import views
from app.modules.agent360.services import briefing as brief_svc


class FakeAgent:
    agent_id = "fake"

    def __init__(self):
        self.questions = []

    def ask(self, question, *, prefix, conversation=None, new=False):
        self.questions.append(question)
        return Answer(segments=[{"type": "text", "text": "- 상담사#1 먼저 코칭 (팀#1)\n- 상담사 # 2 후속 확인"}], secs=1.5)


@pytest.fixture(autouse=True)
def clear_cache():
    brief_svc._cache.clear()


def test_alias_restore_escapes():
    a = brief_svc.Alias()
    assert a("상담사", "김<가>") == "상담사#1" and a("상담사", "김<가>") == "상담사#1" and a("팀", "정란") == "팀#1"
    assert a.restore("<p>상담사#1 · 팀 #1 · 상담사#9</p>") == "<p><b>김&lt;가&gt;</b> · <b>정란</b> · 상담사#9</p>"


def test_home_prompt_has_no_names(backend, users, screens):
    ctx = views.home(backend, users["manager"], screens)
    alias = brief_svc.Alias()
    p = brief_svc.home_prompt(ctx, alias)
    names = [a["name"] for a in backend.list_agents(users["manager"].scope)]
    assert not [n for n in names if n in p]
    assert "상담사#1" in p and "새 숫자를 계산하거나 만들지" in p and len(p) <= brief_svc.MAX_PROMPT
    assert f"담당 상담사 {ctx['total_agents']}명" in p


def test_agent_prompt_and_cache(backend, users, screens):
    u = users["manager"]
    aid = backend.list_agents(u.scope)[0]["agent_id"]
    ctx = views.agent_detail(backend, u, screens, aid, audit_view=False)
    alias = brief_svc.Alias()
    p = brief_svc.agent_prompt(ctx, alias)
    assert ctx["agent"]["name"] not in p and "■ KPI 최근 4주" in p and "■ 근태" in p
    ag = FakeAgent()
    out = brief_svc.brief(backend, ag, u, {"roles": ["manager"]}, "k", p, alias)
    assert ctx["agent"]["name"] in out["html"] and not out["cached"]
    assert brief_svc.brief(backend, ag, u, {"roles": ["manager"]}, "k", p, alias)["cached"]
    brief_svc.brief(backend, ag, u, {"roles": ["manager"]}, "k", p, alias, refresh=True)
    assert len(ag.questions) == 2                                                # 캐시 1번, 다시 요약 1번


def test_briefing_api(backend, monkeypatch):
    from fastapi.testclient import TestClient

    import app.core.ai as ai
    from app.main import app
    ag = FakeAgent()
    monkeypatch.setattr(ai, "get_data_agent", lambda: ag)
    c = TestClient(app)
    c.cookies.set("dev_user", "manager@example.com")
    r = c.post("/api/agent360/briefing", json={"kind": "home"})
    assert r.status_code == 200 and "<li>" in r.json()["html"]
    aid = c.get("/api/agent360/agents").json()[0]["agent_id"]
    r = c.post("/api/agent360/briefing", json={"kind": "agent", "agent_id": aid})
    assert r.status_code == 200 and len(ag.questions) == 2
    monkeypatch.setattr(ai, "get_data_agent", lambda: None)
    assert c.post("/api/agent360/briefing", json={"kind": "home", "refresh": True}).status_code == 503
    page = c.get(f"/agent360/agents/{aid}").text
    assert 'class="card ai-brief"' in page and 'data-kind="agent"' in page
    assert 'data-kind="home"' in c.get("/agent360").text
    monkeypatch.setattr(ai, "get_data_agent", lambda: ag)                       # AI 켜짐 → 카드가 자동 요약을 시작
    assert 'data-enabled="1"' in c.get("/agent360").text and 'data-enabled="1"' in c.get(f"/agent360/agents/{aid}").text
