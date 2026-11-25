"""상담사 INFO 웹 수정 — 덮어 보기, 열 담당 권한, 미리보기→저장→되돌리기, 시트 다시 불러와도 남음, 화면."""
import pytest

from app.core import templating
from app.core.audit import Auditor
from app.core.data.changelog import JsonChangeLog
from app.core.errors import InvalidInput, PermissionDenied
from app.core.modules import discover
from app.core.permissions import User
from app.modules.info import views
from app.modules.info.services.edits import InfoOverlay, effective_info, normalize
from app.modules.info.wiring import change_service
from app.modules.roster.data.sample import RosterSample

WFM = User("wfm@example.com", "w", "wfm")
MGR = User("manager@example.com", "m", "manager")
VIEW = User("viewer@example.com", "v", "viewer")


def test_overlay_latest_wins_and_new_person():
    base = [{"emp_id": "1", "name": "가", "tier": "R1"}]
    edits = [{"edit_id": "a", "emp_id": "1", "field": "tier", "value": "R2", "edited_at": "2026-11-25T01", "edited_by": "x"},
             {"edit_id": "b", "emp_id": "1", "field": "tier", "value": "US", "edited_at": "2026-11-25T02", "edited_by": "y"},
             {"edit_id": "c", "emp_id": "9", "field": "name", "value": "신규", "edited_at": "2026-11-25T03", "edited_by": "z"}]
    rows = InfoOverlay.apply(base, edits)
    assert rows[0]["tier"] == "US" and rows[0]["_edited"]["tier"]["by"] == "y" and not rows[0]["_new"]
    assert rows[1]["emp_id"] == "9" and rows[1]["name"] == "신규" and rows[1]["_new"]


@pytest.mark.parametrize("f,v,want,err", [("joined", "2026. 7. 3", "2026-07-03", False), ("joined", "어제", "어제", True),
                                          ("onboarding", "퇴사", "", False), ("email", "A@B.CO", "a@b.co", False),
                                          ("status", "재직", "재직", True), ("status", "퇴직자", "퇴직자", False)])
def test_normalize(f, v, want, err):
    got, e = normalize(f, v)
    assert got == want and bool(e) == err


@pytest.fixture()
def env(backend):
    store = RosterSample(backend.dir)
    events = []

    class Sink:
        def write(self, e): events.append(e)

    svc = change_service(store, backend, JsonChangeLog(backend.dir))
    svc.auditor = Auditor([Sink()])
    return store, svc, events


def test_owner_permissions(env):
    store, svc, _ = env
    emp = store.agent_info()[0]["emp_id"]
    with pytest.raises(InvalidInput, match="수정 권한"):          # 매니저(OPS) 는 WFM 열 못 고침
        svc.preview(MGR, "info.edit", {"cells": [{"emp_id": emp, "field": "universal", "value": "Y"}]})
    with pytest.raises(InvalidInput, match="수정 권한"):          # WFM 은 OPS 열 못 고침
        svc.preview(WFM, "info.edit", {"cells": [{"emp_id": emp, "field": "tier", "value": "R2"}]})
    with pytest.raises(PermissionDenied):
        svc.preview(VIEW, "info.edit", {"cells": [{"emp_id": emp, "field": "tier", "value": "R2"}]})
    assert svc.preview(MGR, "info.edit", {"cells": [{"emp_id": emp, "field": "tier", "value": "R9"}]}).diff


def test_edit_new_apply_undo_and_survives_sheet_reload(env):
    from app.modules.roster.data.info_loader import SampleInfoLoader
    from app.modules.roster.services.info import InfoCleaner
    store, svc, events = env
    emp = store.agent_info()[0]["emp_id"]
    ch = svc.preview(MGR, "info.edit", {
        "cells": [{"emp_id": emp, "field": "tier", "value": "R9"}, {"emp_id": emp, "field": "onboarding", "value": "2026/1/5"}],
        "new": [{"emp_id": "77000001", "name": "새사람", "tier": "R1", "onboarding": "2026. 11. 20"}]})
    assert ch.summary == "상담사 INFO 신규 1명 · 1명 2칸 수정"
    assert {(d["field"], d["after"]) for d in ch.diff} >= {("tier", "R9"), ("onboarding", "2026-01-05"), ("new", "새사람")}
    svc.approve(MGR, ch.change_id)
    eff = {r["emp_id"]: r for r in effective_info(store)}
    assert eff[emp]["tier"] == "R9" and "tier" in eff[emp]["_edited"]
    assert eff["77000001"]["onboarding"] == "2026-11-20" and eff["77000001"]["_new"]
    # 시트를 다시 불러와도(마트 교체) 웹 수정은 남는다
    SampleInfoLoader(store).save([], [], InfoCleaner().clean([{**r, "row_no": 1} for r in store.agent_info()]), "S", "x")
    assert {r["emp_id"]: r for r in effective_info(store)}[emp]["tier"] == "R9"
    svc.undo(MGR, ch.change_id)
    eff = {r["emp_id"]: r for r in effective_info(store)}
    assert eff[emp]["tier"] != "R9" and "77000001" not in eff
    assert [e["action"] for e in events] == ["change_preview", "change_apply", "change_revert"]


def test_new_person_rules(env):
    store, svc, _ = env
    emp = store.agent_info()[0]["emp_id"]
    with pytest.raises(InvalidInput, match="사번과 한글명"):
        svc.preview(MGR, "info.edit", {"new": [{"emp_id": "1"}]})
    with pytest.raises(InvalidInput, match="이미 있는 사번"):
        svc.preview(MGR, "info.edit", {"new": [{"emp_id": emp, "name": "x"}]})
    with pytest.raises(InvalidInput, match="입력 권한"):
        svc.preview(MGR, "info.edit", {"new": [{"emp_id": "5", "name": "x", "universal": "Y"}]})


def test_screen_marks_editable_columns(backend, env):
    store, svc, _ = env
    mod = next(m for m in discover(with_routers=False) if m.name == "info")
    ctx = views.info(store, MGR, mod.screens, "2026-11-25", svc)
    editable = {c["f"] for c in ctx["cols"] if c["edit"]}
    assert "tier" in editable and "universal" not in editable and "emp_id" not in editable and ctx["can_add"]
    html = templating.render("info/info.html", {"sync": None, "sync_error": "", "errors": {}, **ctx}, user=MGR,
                             module=mod, active="info", with_routers=False)
    assert 'class="ed"' in html and 'class="ro"' in html and "바뀐 칸 미리보기" in html and "+ 새 사람" in html
    wctx = views.info(store, WFM, mod.screens, "2026-11-25", svc)
    assert not wctx["can_add"] and {c["f"] for c in wctx["cols"] if c["edit"]} >= {"universal", "status"}
