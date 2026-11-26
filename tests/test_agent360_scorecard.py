"""코칭 스코어카드 — 지난 6주 + 러닝 주, 목표 달성 표시, 주차별 근태 (손 검산 예제)."""
from pytest import approx

from app.modules.agent360.services.kpi import scorecard


def _kpi(d, net, resp, solved=0, assign=0, target_tp=None):
    return {"date": d, "nps_net": net, "nps_responses": resp, "solved_volume": solved, "assignments": assign,
            "target_throughput": target_tp}


def test_running_week_and_targets():
    # 기준일 2026-11-26(목) → 지난 주 = 11-21(토) 마감, 러닝 주 = 11-28 마감 (11-22~25 데이터)
    rows = [_kpi("2026-11-16", 8, 10, 6, 10, 0.56), _kpi("2026-11-20", 2, 10, 5, 10, 0.56),   # 11-21 주: NPS 50, TP 55%
            _kpi("2026-11-24", 9, 10, 7, 10, 0.56)]                                         # 러닝: NPS 90, TP 70%
    att = [{"date": "2026-11-17", "status": "지각"}, {"date": "2026-11-18", "status": "정상"},
           {"date": "2026-11-25", "status": "결근"}]
    sc = scorecard(rows, att, "2026-11-26", ["nps", "throughput"], 6)
    assert sc["running"] and len(sc["cols"]) == 7
    assert [c["week_end"] for c in sc["cols"]][-2:] == ["2026-11-21", "2026-11-28"]
    nps, tp = sc["rows"]
    assert nps["cells"][-2]["v"] == 50.0 and nps["cells"][-1]["v"] == 90.0 and nps["target"] is None
    assert tp["target"] == approx(56.0) and tp["cells"][-2]["v"] == approx(55.0) and tp["cells"][-2]["ok"] is False
    assert tp["cells"][-1]["v"] == approx(70.0) and tp["cells"][-1]["ok"] is True
    assert sc["cols"][-2]["att"] == [("지각", 1)] and sc["cols"][-1]["att"] == [("결근", 1)]
    assert sc["cols"][-2]["att_days"] == 2


def test_no_running_week_when_no_data_yet():
    sc = scorecard([_kpi("2026-11-20", 2, 10)], [], "2026-11-23", ["nps"], 6)        # 월요일: 이번 주 데이터 없음
    assert not sc["running"] and len(sc["cols"]) == 6 and sc["cols"][-1]["week_end"] == "2026-11-21"


def test_coaching_page_scorecard(backend):
    from fastapi.testclient import TestClient

    from app.main import app
    c = TestClient(app)
    c.cookies.set("dev_user", "manager@example.com")
    page = c.get("/agent360/coaching?agent_id=E240002").text
    assert 'id="scorecard"' in page and "스코어카드 · " in page and "Throughput" in page and "근태" in page
    frag = c.get("/agent360/coaching/scorecard?agent_id=E240001").text
    assert "스코어카드 · " in frag and "<html" not in frag
    assert "상담사를 고르면" in c.get("/agent360/coaching/scorecard").text
