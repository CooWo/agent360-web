"""대시보드 — 계산(손 검산), 역할별 화면, 첫 화면 연결, AI 브리핑(가짜 에이전트), 디트랙터 카드."""
import pytest

from app.core.ai.data_agent import Answer
from app.modules.dashboard import views
from app.modules.dashboard.services import summary


def test_attendance_and_qa_overview_hand_checked():
    att = [{"agent_id": "A", "date": "2026-11-16", "status": s} for s in ("정상", "정상", "결근", "지각", "연차", "휴무")]
    att += [{"agent_id": "A", "date": "2026-11-20", "status": "정상"}, {"agent_id": "A", "date": "2026-11-20", "status": "결근"}]
    o = summary.attendance_overview(att, "2026-11-20", 28)
    # 근무일 = 휴무·연차·휴가·휴직 뺀 6칸, 결근·지각·조퇴 3칸 → 50%
    assert o["work_days"] == 6 and o["absence_rate"] == 50.0
    assert o["last_day"] == "2026-11-20" and o["last"] == {"정상": 1, "결근": 1}
    q = summary.qa_overview([{"qa_avg": 90, "evaluations": 3, "coaching_sessions": 3},
                             {"qa_avg": 70, "evaluations": 1, "coaching_sessions": 0},
                             {"qa_avg": None, "evaluations": 0, "coaching_sessions": 0}])
    assert q["qa_avg"] == 85.0 and q["rate"] == 75.0 and q["gaps"] == 1 and q["below80"] == 1   # (90×3+70×1)/4, 3/4


def test_headcount_new_hires():
    h = summary.headcount([{"team": "T1", "hire_date": "2026-10-01"}, {"team": "T1", "hire_date": "2025-01-01"},
                           {"team": "T2", "hire_date": None}], "2026-11-20", 90)
    assert h == {"agents": 3, "teams": 2, "new_hires": 1}


@pytest.mark.parametrize("who", ["admin", "manager", "sv", "viewer"])
def test_dashboard_renders_by_role(backend, users, who):
    from app.core.modules import discover
    from app.core.templating import render
    mod = next(m for m in discover(with_routers=False) if m.name == "dashboard")
    ctx = views.dashboard(backend, users[who], mod.screens)
    assert ctx["headcount"]["agents"] == len(backend.list_agents(users[who].scope))
    assert sum(t["agents"] for t in ctx["teams"]) == ctx["headcount"]["agents"]      # 팀 합 = 전체
    html = render("dashboard/dashboard.html", ctx, user=users[who], module=mod, active="dashboard", with_routers=False)
    assert "팀별 비교" in html and 'data-kind="dashboard"' in html


class FakeAgent:
    agent_id = "fake"

    def __init__(self):
        self.questions = []

    def ask(self, question, *, prefix, conversation=None, new=False):
        self.questions.append(question)
        return Answer(segments=[{"type": "text", "text": "- 팀#1 코칭 Rate 낮음"}], secs=1.0)


def test_root_is_dashboard_and_briefing(backend, users, monkeypatch):
    from fastapi.testclient import TestClient

    import app.core.ai as ai
    from app.main import app
    from app.modules.agent360.services import briefing as brief_svc
    brief_svc._cache.clear()
    ag = FakeAgent()
    monkeypatch.setattr(ai, "get_data_agent", lambda: ag)
    c = TestClient(app)
    c.cookies.set("dev_user", "manager@example.com")
    r = c.get("/", follow_redirects=False)
    assert r.headers["location"] == "/dashboard"
    page = c.get("/dashboard").text
    assert ">대시보드</a>" in page and "AI 브리핑" in page
    r = c.post("/api/dashboard/briefing", json={})
    assert r.status_code == 200 and "<b>" in r.json()["html"]                          # 팀#1 → 팀 이름
    from app.core.modules import discover
    screens = next(m for m in discover() if m.name == "dashboard").screens
    teams = {t["label"] for t in views.dashboard(backend, users["manager"], screens)["teams"]}
    assert not [t for t in teams if t in ag.questions[0]]                             # 팀 이름은 보내지 않음
    # 디트랙터: LDAP 으로 에이전트가 직접 조회
    aid = "E240002"                                                               # 가짜 설문: ub_sample02 디트랙터 2건 / 응답 4건
    n = len(ag.questions)
    r = c.post("/api/agent360/briefing", json={"kind": "detractor", "agent_id": aid})
    assert r.status_code == 200 and r.json()["facts"] == {"responses": 4, "detractors": 2}
    assert "디트랙터 2건</b> / 응답 4건 (50%)" in r.json()["html"]                 # 건수는 서버 계산
    q = ag.questions[-1]
    assert len(ag.questions) == n + 1 and "환불 안내가 늦고" in q and "ub_sample02" not in q and "정현우" not in q
    r = c.post("/api/agent360/briefing", json={"kind": "detractor", "agent_id": "E240001"})   # 설문 없음 → AI 안 부름
    assert r.json()["facts"]["detractors"] == 0 and len(ag.questions) == n + 1
    assert 'data-kind="detractor"' in c.get(f"/agent360/agents/{aid}").text
