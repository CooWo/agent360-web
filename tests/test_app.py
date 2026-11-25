"""웹 서버 전체 경로 테스트 — FastAPI 가 설치된 환경(내 PC, CI)에서 실행된다."""
import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")


@pytest.fixture()
def client(backend):
    from fastapi.testclient import TestClient

    from app.main import app
    return TestClient(app)


def _as(client, email):
    client.cookies.set("dev_user", email)
    return client


def test_pages_ok(client):
    c = _as(client, "sv.kim@example.com")
    for path in ("/agent360", "/agent360/agents", "/agent360/coaching", "/healthz"):
        assert c.get(path).status_code == 200, path
    assert c.get("/agent360/admin").status_code == 403


def test_api_signal_status_and_coaching(client):
    c = _as(client, "sv.kim@example.com")
    ranked = c.get("/api/agent360/signals/today").json()
    sid = ranked[0]["signals"][0]["signal_id"]
    r = c.post(f"/api/agent360/signals/{sid}/status", json={"status": "확인"})
    assert r.status_code == 200 and r.json()["status"] == "확인"
    aid = c.get("/api/agent360/agents").json()[0]["agent_id"]
    body = {"agent_id": aid, "date": "2026-11-20", "issue_type": "정책 오안내", "summary": "s",
            "agreed_action": "a", "follow_up_date": "2026-11-27"}
    r = c.post("/api/agent360/coaching", json=body)
    assert r.status_code == 201
    bad = c.post("/api/agent360/coaching", json={**body, "issue_type": "x"})
    assert bad.status_code == 400 and "issue_type" in bad.json()["errors"]


def test_outside_scope_404_and_viewer_forbidden(client):
    c = _as(client, "sv.kim@example.com")
    assert c.get("/agent360/agents/E240025").status_code == 404      # R2 상담사
    v = _as(client, "viewer@example.com")
    assert v.get("/agent360/coaching").status_code == 403


def test_form_post_redirects(client):
    c = _as(client, "sv.kim@example.com")
    aid = c.get("/api/agent360/agents").json()[0]["agent_id"]
    r = c.post("/agent360/coaching", data={"agent_id": aid, "date": "2026-11-20", "issue_type": "근태",
                                           "summary": "s", "agreed_action": "a", "follow_up_date": "2026-11-27"},
               follow_redirects=False)
    assert r.status_code == 303 and f"/agent360/agents/{aid}" in r.headers["location"]


def test_assistant_page_and_api(client, monkeypatch):
    from tests.test_assistant import CHAT_RESP, FakeSession
    from app.core.ai.data_agent import DataAgent
    import app.modules.assistant.api as api_mod
    agent = DataAgent("v11-2026", "global", "agent_x",
                      session=FakeSession([(200, {"name": "n/c1"}), (200, CHAT_RESP)]))
    monkeypatch.setattr(api_mod, "get_data_agent", lambda: agent)
    m = _as(client, "manager@example.com")
    assert m.get("/assistant").status_code == 200
    r = m.post("/api/assistant/ask", json={"question": "지난주 NPS"})
    assert r.status_code == 200 and "<table" in r.json()["html"] and r.json()["conversation"] == "n/c1"
    assert m.post("/api/assistant/ask", json={"question": " "}).status_code == 400
    s = _as(client, "sv.kim@example.com")
    assert s.get("/assistant").status_code == 200                   # SV 도 사용 가능


def test_capacity_pages_and_api(client):
    c = _as(client, "wfm@example.com")
    for path in ("/capacity", "/capacity/absence", "/capacity/cohorts", "/capacity/simulator",
                 "/capacity/input", "/capacity/reports"):
        assert c.get(path).status_code == 200, path
    data = c.get("/api/capacity/fte").json()
    assert data["week"] == "2026-11-21" and data["totals"]
    c = _as(client, "viewer@example.com")
    assert c.get("/capacity").status_code == 200 and c.get("/capacity/input").status_code == 403
    c = _as(client, "sv.kim@example.com")
    assert c.get("/capacity").status_code == 403


def test_capacity_input_preview_apply_undo(client):
    c = _as(client, "wfm@example.com")
    r = c.post("/capacity/input/preview", data={"Voice__shrinkage": "0.33", "Voice__occupancy": "0.85",
                                                "Voice__work_hours_week": "40", "Voice__nesting_productivity": "0.5"},
               follow_redirects=False)
    assert r.status_code == 303 and "change=" in r.headers["location"]
    cid = r.headers["location"].split("change=")[1]
    assert "미리보기 · 계산 가정 1칸 변경" in c.get(r.headers["location"]).text
    assert c.post(f"/capacity/input/{cid}/approve", follow_redirects=False).status_code == 303
    assert any(a["shrinkage"] == 0.33 for a in c.get("/api/capacity/fte").json()["assumptions"])
    assert c.post(f"/capacity/input/{cid}/undo", follow_redirects=False).status_code == 303
    up = c.post("/capacity/input/preview", files={"file": ("a.csv", b"channel,shrinkage\nVoice,2\n", "text/csv")})
    assert up.status_code == 400 and "입력값을 확인" in up.text


def test_capacity_change_api(client):
    c = _as(client, "wfm@example.com")
    ch = c.post("/api/capacity/changes/capacity.assumptions/preview",
                json={"rows": [{"channel": "Async", "occupancy": 0.8}]}).json()
    assert ch["status"] == "preview"
    assert c.post(f"/api/capacity/changes/{ch['change_id']}/approve").json()["status"] == "applied"
    assert c.post(f"/api/capacity/changes/{ch['change_id']}/undo").json()["status"] == "reverted"
    v = _as(client, "manager@example.com")
    assert v.post("/api/capacity/changes/capacity.assumptions/preview",
                  json={"rows": [{"channel": "Async", "occupancy": 0.7}]}).status_code == 403


def test_roster_workspace_flow(client):
    import json
    c = _as(client, "wfm@example.com")
    assert c.get("/roster").status_code == 200 and c.get("/roster/workspace").status_code == 200
    board = c.get("/api/roster/board").json()
    rows = [r for g in board["groups"] for r in g["rows"]]
    rows[0]["display_name"] = "Changed"
    assert c.post("/roster/workspace/save", data={"rows_json": json.dumps(rows)}, follow_redirects=False).status_code == 303
    assert "작업 중 초안" in c.get("/roster/workspace").text
    pasted = c.post("/roster/workspace/paste", data={"rows_json": json.dumps(rows), "tl": "TL 신규",
                                                       "paste": "US\t\t트레이닝9\t\t\n"}, follow_redirects=False)
    assert pasted.status_code == 303
    r = c.post("/roster/workspace/preview", data={"rows_json": json.dumps(rows)}, follow_redirects=False)
    cid = r.headers["location"].split("change=")[1]
    assert "미리보기 · 팀 구성 수정 1" in c.get(r.headers["location"]).text
    assert c.post(f"/roster/workspace/{cid}/approve", follow_redirects=False).headers["location"] == "/roster"
    assert "Changed" in c.get("/roster").text
    assert c.post(f"/api/roster/changes/{cid}/undo").json()["status"] == "reverted"
    v = _as(client, "viewer@example.com")
    assert v.get("/roster").status_code == 200 and v.get("/roster/workspace").status_code == 403
    assert v.post("/roster/workspace/save", data={"rows_json": "[]"}).status_code == 403
