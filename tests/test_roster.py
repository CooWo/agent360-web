"""팀 구성 — 규칙(정리·검사·비교), 붙여넣기, 변경 흐름, 화면, BigQuery 매개변수."""
import re
import sys
import types

import pytest

from app.core import templating
from app.core.audit import Auditor
from app.core.data.changelog import JsonChangeLog
from app.core.errors import InvalidInput, PermissionDenied
from app.core.modules import discover
from app.core.permissions import User
from app.modules.roster import views
from app.modules.roster.data.sample import RosterSample
from app.modules.roster.services import paste
from app.modules.roster.services.board import BoardRules, merge_paste, summarize
from app.modules.roster.wiring import change_service

WFM = User("wfm@example.com", "정WFM", "wfm")
INFO = [{"emp_id": "100", "name": "가나", "e_name": "Ga Na", "status": "재직자"},
        {"emp_id": "200", "name": "다라", "e_name": "Da Ra", "status": "퇴직자"}]


def R(tl, emp, name="", **kw):
    return {"tl": tl, "shift": kw.get("shift", "US"), "emp_id": emp, "name": name, "e_name": kw.get("e_name", ""),
            "display_name": kw.get("display_name", ""), "date": "", "note": ""}


# ── 규칙 ───────────────────────────────────────────
def test_normalize_fills_from_info_and_cleans_ids():
    rows = BoardRules(INFO).normalize([{"tl": " A ", "emp_id": "'100"}, {"tl": "A", "emp_id": "300.0", "name": "x"},
                                       {"tl": "A"}])
    assert rows[0]["name"] == "가나" and rows[0]["e_name"] == "Ga Na" and rows[0]["tl"] == "A"
    assert rows[1]["emp_id"] == "300" and len(rows) == 2               # 빈 행 제거


def test_check_errors_and_warnings():
    c = BoardRules(INFO).check([R("A", "100", "가나"), R("B", "100", "가나"), R("", "", "트레이닝1"),
                                R("A", "200", "다라"), R("C", "999", "모름")], known_tls={"A", "B"})
    assert any("같은 사람" in v for v in c.errors.values()) and any("TL 이 비었" in v for v in c.errors.values())
    kinds = {w["kind"] for w in c.warnings}
    assert kinds == {"temp", "left", "unknown", "new_tl"}


def test_diff_new_move_remove_edit_and_link():
    before = [R("A", "100", "가나"), R("A", "", "트레이닝1"), R("B", "200", "다라")]
    after = [R("B", "100", "가나", display_name="Gana"), R("B", "300", "트레이닝1"), R("A", "400", "새사람")]
    d = BoardRules(INFO).diff(before, after)
    got = {(x["label"], x["name"]) for x in d}
    assert ("신규", "새사람") in got and ("빠짐", "다라") in got and ("이동", "가나") in got
    assert ("Display name 수정", "가나") in got
    assert ("사번 연결", "트레이닝1") in got and ("이동", "트레이닝1") in got     # 임시 → 사번, 신규·빠짐 아님
    assert ("신규", "트레이닝1") not in got
    assert summarize(d) == "팀 구성 신규 1 · 사번 연결 1 · 이동 2 · 빠짐 1 · 수정 1"


def test_merge_paste_replaces_only_pasted_tls():
    cur = [R("A", "1"), R("B", "2")]
    assert merge_paste(cur, [R("A", "3")], False) == [R("B", "2"), R("A", "3")]
    assert merge_paste(cur, [R("A", "3")], True) == [R("A", "3")]


# ── 붙여넣기 ───────────────────────────────────────
WIDE = ("2026. 12. 7\t\t\t\t\t\t\t\t\t\t\n"
        "TL 가\t\t\t\t\tTL 나\t\t\t\t\n"
        "Shift\t사번\t이름\tName\tDisplay name\tShift\t사번\t이름\tName\tDisplay name\n"
        "US\t100\t가나\tGa Na\tGana\tEU\t200\t다라\tDa Ra\t본명\n"
        "US\t\t트레이닝1\t\t\t\t\t\t\t\n")


def test_paste_wide_ops_tl_sheet():
    rows = paste.parse(WIDE)
    assert [(r["tl"], r["emp_id"], r["name"]) for r in rows] == [("TL 가", "100", "가나"), ("TL 가", "", "트레이닝1"),
                                                                ("TL 나", "200", "다라")]


def test_paste_long_raw_and_headerless():
    raw = "Date\tLeader\tRGroup\tShift\t사번\t이름\tName\tDisplay Name\n2026. 11. 22\tTL 가\t\tUS\t100\t가나\tGa Na\tGully\n"
    assert paste.parse(raw)[0]["tl"] == "TL 가"
    assert paste.parse("US\t100\t가나\tGa Na\tGana\n", default_tl="TL 다")[0] == {
        "shift": "US", "emp_id": "100", "name": "가나", "e_name": "Ga Na", "display_name": "Gana", "tl": "TL 다"}
    with pytest.raises(InvalidInput):
        paste.parse("US\t100\t가나\n")                                   # 머리글도 TL 도 없음
    with pytest.raises(InvalidInput):
        paste.parse("  \n")


# ── 변경 흐름 (샘플 저장소) ────────────────────────
@pytest.fixture()
def env(backend):
    store = RosterSample(backend.dir)
    events = []

    class Sink:
        def write(self, e): events.append(e)

    svc = change_service(store, backend, JsonChangeLog(backend.dir))
    svc.auditor = Auditor([Sink()])
    return store, svc, events


def test_draft_then_preview_apply_undo(env):
    store, svc, events = env
    base = store.board()
    rows = [dict(r) for r in base]
    rows[0]["tl"] = "TL 새로움"
    rows.append({"tl": "TL 가람", "emp_id": "", "name": "트레이닝2"})
    store.save_draft(WFM.email, rows)
    assert store.draft(WFM.email)["rows"] == rows and store.board() == base   # 초안은 보드에 영향 없음
    ch = svc.preview(WFM, "roster.board", {"rows": rows})
    assert "신규 1" in ch.summary and "이동 1" in ch.summary
    svc.approve(WFM, ch.change_id)
    assert store.board()[0]["tl"] == "TL 새로움" and store.draft(WFM.email) is None
    assert store.versions()[0]["saved_by"] == WFM.email
    svc.undo(WFM, ch.change_id)
    assert store.board() == base and len(store.versions()) == 2                   # 되돌리기도 새 버전
    acts = [e["action"] for e in events]
    assert "change_apply" in acts and "change_revert" in acts


def test_rules_enforced(env):
    store, svc, _ = env
    rows = store.board() + [dict(store.board()[0], tl="TL 나래")]
    with pytest.raises(InvalidInput, match="같은 사람"):
        svc.preview(WFM, "roster.board", {"rows": rows})
    with pytest.raises(PermissionDenied):
        svc.preview(User("sv.kim@example.com", "김SV", "sv"), "roster.board", {"rows": store.board()})
    with pytest.raises(InvalidInput):
        svc.preview(WFM, "roster.board", {"rows": []})


# ── 화면 ───────────────────────────────────────────
@pytest.fixture()
def mod():
    return next(m for m in discover(with_routers=False) if m.name == "roster")


def _r(tpl, ctx, user, mod, active=""):
    return templating.render(tpl, ctx, user=user, module=mod, active=active, with_routers=False)


@pytest.mark.parametrize("role", ["admin", "manager", "wfm", "sv", "viewer"])
def test_board_renders_for_all(backend, mod, role):
    u = User("x@example.com", "x", role, ("R1-A",))
    html = _r("roster/board.html", views.board(RosterSample(backend.dir), u, mod.screens), u, mod, "board")
    assert "TL별 명단" in html and "TL 가람" in html and "임시" in html and "퇴직자" in html
    assert ("명단 고치기" in html) == u.can("roster.edit")


def test_workspace_renders_and_blocks_viewer(backend, mod, env):
    store, svc, _ = env
    html = _r("roster/workspace.html", views.workspace(store, WFM, mod.screens, svc), WFM, mod, "workspace")
    assert "시트에서 붙여넣기" in html and 'data-f="emp_id"' in html and "roster.js" in html
    with pytest.raises(PermissionDenied):
        views.workspace(store, User("v@x", "v", "viewer"), mod.screens, svc)


# ── BigQuery 매개변수 ──────────────────────────────
def test_bigquery_params_bound(monkeypatch):
    calls = []

    class P:
        def __init__(self, name, typ, value):
            self.name = name

    class Cfg:
        def __init__(self, query_parameters=()):
            self.p = list(query_parameters)

    class Client:
        def __init__(self, project=None, **kw):
            self.project = project

        def query(self, sql, job_config=None, location=None):
            calls.append((sql, {p.name for p in job_config.p}))
            return types.SimpleNamespace(result=lambda: [])

    fake = types.ModuleType("google.cloud.bigquery")
    fake.ScalarQueryParameter, fake.QueryJobConfig, fake.Client = P, Cfg, Client
    cloud = types.ModuleType("google.cloud")
    cloud.bigquery = fake
    google = types.ModuleType("google")
    google.cloud = cloud
    for k, v in {"google": google, "google.cloud": cloud, "google.cloud.bigquery": fake}.items():
        monkeypatch.setitem(sys.modules, k, v)
    from app.modules.roster.data.bigquery import RosterBigQuery
    b = RosterBigQuery("v12-2027", "asia-northeast3", "roster")
    b.agent_info(); b.info_loads(3); b.board(); b.save_board([R("A", "1")], "a@x"); b.versions(5)
    b.draft("a@x"); b.save_draft("a@x", []); b.clear_draft("a@x")
    assert len(calls) == 8
    for sql, bound in calls:
        assert set(re.findall(r"@(\w+)", sql)) <= bound
        assert "`v12-2027.roster`" in sql


def test_info_from_sheet_header_mapping():
    from app.modules.roster.services.info import FIELDS, from_sheet
    header = ["사번", "한글명", "Name", "Email", "Airbnb ID", "CE/SR1 Batch", "Tenure", "Shift Type", "Location", "TL",
              "Type", "Tier", "LDAP", "FTE", "", "온보딩 날짜", "R2 온보딩", "Universal", "근속 인센티브", "입사일(UHR)",
              "재직정보", "퇴사 Tenure", "Universal 전\nTier","R2 온보딩 기준 Tenure", "비고", "", "", "Amb.사번", "Amb.TL",
              "메뉴얼 + 함수", "", "", "Date", "Leader", "RGroup", "Shift", "사번", "이름", "Name"]
    rows = from_sheet(header, [["1", "가나", "Ga Na", "", "", "", "365+ Days", "Flex", "WFH", "ub_tl", "Voice", "R1",
                                "ub_ga", "Y/Y", "", "", "", "", "", "2021-03-21", "퇴직자", "", "", "", "",
                                "", "", "", "", "", "", "", "2026. 11. 22", "TL 가", "", "US", "999", "딴사람", "X"],
                               ["", "사번없음"]])
    assert len(rows) == 1 and set(rows[0]) == {*FIELDS, "dates_ok"}
    r = rows[0]
    assert (r["emp_id"], r["tl_ldap"], r["status"], r["joined"], r["e_name"]) == ("1", "ub_tl", "퇴직자", "2021-03-21", "Ga Na")
