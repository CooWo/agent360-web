import json

import pytest

from app.core.errors import InvalidInput, NotFound, PermissionDenied
from app.modules.agent360.services import coaching as coaching_svc
from app.modules.agent360.services import kpi as kpi_svc
from app.modules.agent360.services import signals as signal_svc


def test_weekly_kpi_uses_sum_over_sum():
    rows = [
        {"date": "2026-11-16", "handled": 10, "aht_sec": 600, "nps_responses": 2, "nps_net": 2},
        {"date": "2026-11-17", "handled": 30, "aht_sec": 400, "nps_responses": 8, "nps_net": 0},
    ]
    wk = kpi_svc.weekly(rows, "2026-11-20", 1)[0]
    assert wk["week_end"] == "2026-11-21" and wk["partial"]
    assert wk["handled"] == 20                         # 일평균
    assert wk["aht_sec"] == pytest.approx(450)          # (10*600+30*400)/40
    assert wk["nps"] == pytest.approx(20)               # 2/10*100 (행 평균이면 50)


def test_signals_ranked_desc_and_scoped(backend, users):
    ranked = signal_svc.by_agent(backend, users["sv"])
    scores = [r["score"] for r in ranked]
    assert scores == sorted(scores, reverse=True)
    assert {r["agent"]["team"] for r in ranked} == {"R1-A"}


def test_set_status_updates_score_and_audits(backend, users):
    top = signal_svc.by_agent(backend, users["sv"])[0]
    sig = top["signals"][0]
    signal_svc.set_status(backend, users["sv"], sig["signal_id"], "해당 없음")
    after = next(r for r in signal_svc.by_agent(backend, users["sv"]) if r["agent"]["agent_id"] == top["agent"]["agent_id"])
    assert after["score"] == top["score"] - sig["score"]
    log = (backend.runtime / "audit_log.jsonl").read_text(encoding="utf-8").strip().splitlines()
    assert json.loads(log[-1])["action"] == "signal_status"


def test_set_status_rules(backend, users):
    sig = signal_svc.by_agent(backend, users["sv"])[0]["signals"][0]
    with pytest.raises(PermissionDenied):
        signal_svc.set_status(backend, users["viewer"], sig["signal_id"], "확인")
    with pytest.raises(InvalidInput):
        signal_svc.set_status(backend, users["sv"], sig["signal_id"], "아무거나")
    with pytest.raises(NotFound):                      # 다른 팀 SV
        signal_svc.set_status(backend, users["sv_b"], sig["signal_id"], "확인")


def _form(agent_id, **kw):
    f = {"agent_id": agent_id, "date": "2026-11-20", "issue_type": "정책 오안내", "summary": "환불 정책 오안내 2건",
         "agreed_action": "KB 재숙지", "follow_up_date": "2026-11-27", "raw_note": ""}
    f.update(kw)
    return f


def test_coaching_create_and_followup(backend, users):
    aid = backend.list_agents(users["sv"].scope)[0]["agent_id"]
    rec = coaching_svc.create(backend, users["sv"], _form(aid))
    assert rec["coaching_id"] and rec["sv_email"] == "sv.kim@example.com"
    fu = coaching_svc.followups(backend, users["sv"], "2026-11-25", 3)
    assert any(c["coaching_id"] == rec["coaching_id"] for c in fu["soon"])
    coaching_svc.complete(backend, users["sv"], rec["coaching_id"])
    assert next(c for c in backend.coaching(users["sv"].scope) if c["coaching_id"] == rec["coaching_id"])["done"]


def test_coaching_validation(backend, users):
    aid = backend.list_agents(users["sv"].scope)[0]["agent_id"]
    with pytest.raises(InvalidInput) as e:
        coaching_svc.create(backend, users["sv"], _form(aid, issue_type="없는 유형", summary="", follow_up_date="2026-11-01"))
    assert set(e.value.errors) == {"issue_type", "summary", "follow_up_date"}
    other = backend.list_agents(users["manager"].scope, team="R2-A")[0]["agent_id"]
    with pytest.raises(InvalidInput) as e2:
        coaching_svc.create(backend, users["sv"], _form(other))
    assert "agent_id" in e2.value.errors
    with pytest.raises(PermissionDenied):
        coaching_svc.create(backend, users["viewer"], _form(aid))


def test_runtime_persists_after_reload(backend, users):
    from app.core.data.sample import SampleBackend
    aid = backend.list_agents(users["sv"].scope)[0]["agent_id"]
    rec = coaching_svc.create(backend, users["sv"], _form(aid))
    again = SampleBackend(backend.dir)
    assert any(c["coaching_id"] == rec["coaching_id"] for c in again.coaching(users["sv"].scope))
