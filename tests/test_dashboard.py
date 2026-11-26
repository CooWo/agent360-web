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
    assert "근태 주차별" in html and "평균" in html and "근태 이상" in html and "awc-in" in html


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
    assert "<h1>대시보드</h1>" in page and "AI 브리핑" in page
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


def test_brand_links_dashboard_and_no_dashboard_button(backend):
    from fastapi.testclient import TestClient

    from app.main import app
    c = TestClient(app)
    c.cookies.set("dev_user", "manager@example.com")
    page = c.get("/agent360").text
    assert '<a class="brand" href="/"' in page and ">Ubase Hub</a>" in page
    nav = page.split('<nav class="modnav">')[1].split("</nav>")[0]
    assert "/dashboard" not in nav and "/agent360" in nav
    assert c.get("/", follow_redirects=False).headers["location"].startswith("/dashboard")
    dash = c.get("/dashboard").text                                    # 대시보드는 왼쪽 메뉴 없음
    assert 'class="layout with-ai no-side"' in dash or 'class="layout no-side"' in dash
    assert "no-side" not in page                                        # 다른 화면은 그대로


def test_attendance_weekly_vs_prev_and_avg_hand_checked():
    # 기준일 11-20(금) → 러닝 주 11-21(6일), 끝난 주 10-24(데이터 없음)·10-31·11-07·11-14
    def a(d, s, n=1):
        return [{"agent_id": "A", "date": d, "status": s}] * n
    att = a("2026-10-27", "결근", 2) + a("2026-10-27", "정상") + a("2026-11-03", "결근") + a("2026-11-03", "지각") \
        + a("2026-11-10", "결근", 4) + a("2026-11-10", "연차") + a("2026-11-18", "결근")
    w = summary.attendance_weekly(att, "2026-11-20", 4)
    assert [r["week_end"] for r in w["rows"]] == ["2026-10-24", "2026-10-31", "2026-11-07", "2026-11-14", "2026-11-21"]
    assert w["running"] and w["rows"][-1]["days"] == 6 and w["base"] == "2026-11-14" and w["prev"] == "2026-11-07"
    assert w["rows"][0]["counts"]["결근"] is None and w["avg_weeks"] == 2          # 10-24 = 시트 불러오기 전 → 평균에서 뺌
    c = {x["status"]: x for x in w["compare"]}
    # 결근: 기준 4, 전 주 1 → +3, 평균 (2+1)/2 = 1.5 → +2.5, +166.7%
    assert (c["결근"]["now"], c["결근"]["prev"], c["결근"]["d_prev"], c["결근"]["avg"], c["결근"]["d_avg"]) == (4, 1, 3, 1.5, 2.5)
    assert round(c["결근"]["d_avg_pct"], 1) == 166.7 and c["결근"]["bad_up"]
    assert c["지각"]["d_prev"] == -1 and c["지각"]["d_avg_pct"] == -100.0                 # 0 vs 평균 0.5
    assert c["연차"]["d_avg_pct"] is None and not c["연차"]["bad_up"]                     # 평균 0 → % 없음
    assert c["결근"]["series"] == [None, 2, 1, 4, 1]
    assert c["결근"]["max"] == 4 and w["rows"][-1]["end"] == "2026-11-20" and w["rows"][-1]["start"] == "2026-11-15"
    assert w["rows"][2]["delta"]["결근"] == -1 and w["rows"][1]["delta"]["결근"] is None   # 앞 주 데이터 없음
    assert w["rows"][-1]["delta"]["결근"] is None                                         # 러닝 주는 비교 안 함


def test_attendance_weekly_on_saturday_has_no_running_week():
    w = summary.attendance_weekly([{"date": "2026-11-21", "status": "지각"}], "2026-11-21", 2)
    assert not w["running"] and w["base"] == "2026-11-21" and [r["week_end"] for r in w["rows"]] == ["2026-11-14", "2026-11-21"]
