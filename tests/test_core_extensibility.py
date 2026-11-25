"""확장 지점 — 등록부, 역할 정책, 감사 받는 곳, 변경(미리보기→적용→되돌리기), 업로드."""
import json

import pytest

from app.core.audit import Auditor
from app.core.changes import APPLIED, PREVIEW, REVERTED, ChangeService
from app.core.data.changelog import JsonChangeLog
from app.core.errors import InvalidInput, NotFound, PermissionDenied
from app.core.permissions import POLICIES, RolePolicy, User
from app.core.registry import Registry
from app.core.uploads import PARSERS, TableParser, parse_upload
from app.modules.capacity.data.sample import CapacitySample
from app.modules.capacity.services.changes import handlers


# ── 등록부 ─────────────────────────────────────────
def test_registry_register_get_and_errors():
    r = Registry("시험")
    r.register("a", 1)

    @r.register("b")
    def make(x):
        return x * 2

    assert r.get("a") == 1 and r.create("b", 4) == 8 and r.names() == ["a", "b"]
    with pytest.raises(KeyError, match="등록되지 않은 시험"):
        r.get("c")
    with pytest.raises(ValueError):
        r.register("a", 2)


# ── 역할 정책 ──────────────────────────────────────
def test_new_role_without_touching_user():
    POLICIES.register(RolePolicy("ba_lead", "BA 리드", all_teams=True, grants=frozenset({"capacity.view"})))
    try:
        u = User("x@ubase.co.kr", "x", "ba_lead")
        assert u.scope.all_teams and u.can("capacity.view") and not u.can("capacity.edit")
        assert u.role_label == "BA 리드" and not u.can_write
    finally:
        POLICIES._p.pop("ba_lead"); POLICIES.labels.pop("ba_lead")


def test_unknown_role_has_nothing():
    u = User("x@ubase.co.kr", "x", "nobody", ("R1-A",))
    assert not u.can_write and not u.can("admin") and not u.can_view_sensitive("R1-A") and not u.scope.all_teams


# ── 감사 ───────────────────────────────────────────
def test_auditor_sends_to_every_sink_and_survives_failure():
    got = []

    class Good:
        def write(self, e): got.append(e)

    class Bad:
        def write(self, e): raise RuntimeError("down")

    ev = Auditor([Bad(), Good()]).record(User("a@x", "a", "wfm"), "x", "t", "1", {"k": 1})
    assert got == [ev] and ev["detail"] == {"k": 1}


# ── 변경 흐름 ──────────────────────────────────────
@pytest.fixture()
def cap_env(backend, tmp_path):
    store = CapacitySample(backend.dir)
    events = []

    class Sink:
        def write(self, e): events.append(e)

    svc = ChangeService(handlers(store), JsonChangeLog(backend.dir), Auditor([Sink()]))
    return svc, store, events


WFM = User("wfm@example.com", "정WFM", "wfm")
MANAGER = User("manager@example.com", "최매니저", "manager")


def test_preview_apply_undo(cap_env):
    svc, store, events = cap_env
    before = store.assumptions()
    ch = svc.preview(WFM, "capacity.assumptions", {"rows": [{"channel": "Voice", "shrinkage": "0.35"}]})
    assert ch.status == PREVIEW and ch.diff == [{"key": "Voice", "field": "shrinkage", "label": "Shrinkage",
                                                 "before": 0.3, "after": 0.35}]
    assert store.assumptions() == before                      # 미리보기는 저장 안 함
    ch = svc.approve(WFM, ch.change_id)
    assert ch.status == APPLIED and next(a for a in store.assumptions() if a["channel"] == "Voice")["shrinkage"] == 0.35
    assert CapacitySample(store._runtime.parents[1]).assumptions() == store.assumptions()   # 재시작해도 남음
    ch = svc.undo(WFM, ch.change_id)
    assert ch.status == REVERTED and store.assumptions() == before
    assert [e["action"] for e in events] == ["change_preview", "change_apply", "change_revert"]


def test_change_rules(cap_env):
    svc, store, _ = cap_env
    with pytest.raises(PermissionDenied):
        svc.preview(MANAGER, "capacity.assumptions", {"rows": [{"channel": "Voice", "shrinkage": 0.4}]})
    with pytest.raises(InvalidInput) as e:
        svc.preview(WFM, "capacity.assumptions", {"rows": [{"channel": "Fax", "shrinkage": 2}]})
    assert "rows.1.channel" in e.value.errors
    with pytest.raises(InvalidInput):
        svc.preview(WFM, "capacity.assumptions", {"rows": [{"channel": "Voice", "shrinkage": 1.2}]})
    with pytest.raises(InvalidInput, match="바뀌는 값"):
        svc.preview(WFM, "capacity.assumptions", {"rows": [{"channel": "Voice", "shrinkage": 0.3}]})
    with pytest.raises(NotFound):
        svc.preview(WFM, "nope", {})


def test_stale_preview_and_undo_order(cap_env):
    svc, store, _ = cap_env
    a = svc.preview(WFM, "capacity.assumptions", {"rows": [{"channel": "Voice", "shrinkage": 0.31}]})
    b = svc.preview(WFM, "capacity.assumptions", {"rows": [{"channel": "Voice", "shrinkage": 0.32}]})
    svc.approve(WFM, b.change_id)
    with pytest.raises(InvalidInput, match="바뀌었습니다"):
        svc.approve(WFM, a.change_id)                          # b 적용 후 a 의 미리보기는 낡음
    c = svc.approve(WFM, svc.preview(WFM, "capacity.assumptions",
                                     {"rows": [{"channel": "Async", "occupancy": 0.8}]}).change_id)
    with pytest.raises(InvalidInput, match="최근"):
        svc.undo(WFM, b.change_id)                             # 최근 것(c)부터
    svc.undo(WFM, c.change_id)
    svc.undo(WFM, b.change_id)
    assert next(x for x in store.assumptions() if x["channel"] == "Voice")["shrinkage"] == 0.3


def test_discard_and_history(cap_env):
    svc, _, _ = cap_env
    ch = svc.preview(WFM, "capacity.assumptions", {"rows": [{"channel": "Voice", "occupancy": 0.8}]})
    assert svc.discard(WFM, ch.change_id).status == "discarded"
    with pytest.raises(InvalidInput):
        svc.approve(WFM, ch.change_id)
    assert [c.change_id for c in svc.history(WFM)] == [ch.change_id]
    assert svc.history(User("v@x", "v", "viewer")) == []       # 권한 없는 종류는 안 보임


# ── 업로드 ─────────────────────────────────────────
def test_csv_upload_utf8_and_cp949():
    data = "channel , shrinkage\nVoice, 0.33\n\n".encode("utf-8-sig")
    assert parse_upload("a.CSV", data) == [{"channel": "Voice", "shrinkage": "0.33"}]
    assert parse_upload("b.csv", "channel,source\nVoice,엑셀\n".encode("cp949"))[0]["source"] == "엑셀"
    with pytest.raises(InvalidInput):
        parse_upload("a.xlsx", b"x")
    with pytest.raises(InvalidInput):
        parse_upload("a.csv", b"channel\n")


def test_new_upload_format_by_registering():
    class JsonParser(TableParser):
        def parse(self, data):
            return json.loads(data)

    PARSERS.register(".json", JsonParser())
    try:
        assert parse_upload("a.json", b'[{"channel": "Voice"}]') == [{"channel": "Voice"}]
    finally:
        PARSERS._items.pop(".json")
