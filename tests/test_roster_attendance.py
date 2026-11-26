"""근태 불러오기 — Schedule KR 칸 판정, 바뀐 칸만 저장, 지우기 안전장치, BigQuery SQL 매개변수 (가짜 시트·가짜 사번)."""
import copy
import re
import sys
import types
from datetime import date

import pytest

from app.core.sheets import cell_bg
from app.modules.roster.services import attendance_sync as sync_mod
from app.modules.roster.services.attendance import classify, date_columns, diff, parse_date, read_block
from app.modules.roster.services.attendance_sync import AttendanceRefused, AttendanceSync, default_since

W, LATE, EARLY = "#ffffff", "#ff9900", "#f9cb9c"


@pytest.mark.parametrize("text,bg,want", [
    ("09:00~18:00", W, "정상"),
    ("8:00~17:00", "#d9ead3", "정상"),                       # 다른 배경(교대 등)은 정상
    ("09:00~18:00", LATE, "지각"),
    ("09:00~18:00", EARLY, "조퇴"),
    ("17:40 NOT (40mins)", "#ffff00", "기타"),                 # 시간대(~)가 없으면 근무시간으로 보지 않음
    ("12:00~21:00 NOT (30mins)", "#ffff00", "정상"),
    ("8:02~17:00", LATE, "지각"),
    ("10:00 ~ 19:00 Late (15mins) NOT (30mins)", W, "지각"),
    ("Early left", W, "조퇴"), ("8:00–21:40 BOT 240 mins + NOT 40 mins", W, "정상"),
    ("Approved AL", "#3c78d8", "연차"), ("Approved AL*", "#93c47d", "연차"), ("Approved AL(4)", W, "연차"),
    ("Absent", "#ff0000", "결근"), ("Planned Absences", "#c60000", "결근"),
    ("Sat off", "#f2dcdb", "휴무"), ("PH", "#38761d", "휴무"),
    ("육아휴가", "#00ffff", "휴가"), ("보건휴가", "#00ffff", "휴가"), ("태아건강검진", "#00ffff", "휴가"),
    ("무급휴직", "#bf9000", "휴직"), ("가족돌봄휴직", "#00ffff", "휴직"), ("Military", "#54bd70", "휴직"),
    ("Training", "#ff00ff", "교육"), ("Refresher Training", "#ff00ff", "교육"),
    ("Resignation", "#666666", None), ("Move to CS Labs Tab", "#666666", None), ("End of contract", "", None),
    ("", "#666666", None), ("Hyunji", W, "기타"),
])
def test_classify(text, bg, want):
    assert classify(text, bg) == want


def test_dates_and_colors():
    assert parse_date("2026. 11. 8") == date(2026, 11, 8) and parse_date("Sun") is None
    assert date_columns(["", "x", "2026. 11. 8", "2026. 11. 9", "2026. 11. 10"], date(2026, 11, 9), date(2026, 11, 30)) \
        == [(3, date(2026, 11, 9)), (4, date(2026, 11, 10))]
    assert cell_bg({"backgroundColor": {"red": 1, "green": 0.6}}) == "#ff9900"
    assert cell_bg({"backgroundColorStyle": {"rgbColor": {"red": 0.9764706, "green": 0.79607844, "blue": 0.6117647}}}) \
        == "#f9cb9c"
    assert cell_bg({}) == ""


def _c(v, bg=W):
    return (v, bg)


# 1행 날짜, 2행 요일, 3행부터 사번. 열: A 사번, B 이름, C~E 날짜 (11/8 ~ 11/10)
HEADER = ["", "Name", "2026. 11. 8", "2026. 11. 9", "2026. 11. 10"]
IDS = ["", "사번", "90000001", "90000002", "90000003", "90000001"]
BLOCK = [  # C1:E6
    [_c("2026. 11. 8"), _c("2026. 11. 9"), _c("2026. 11. 10")],
    [_c("Sun"), _c("Mon"), _c("Tue")],
    [_c("Sat off", "#f2dcdb"), _c("09:00~18:00", LATE), _c("Approved AL", "#3c78d8")],
    [_c("09:00~18:00"), _c("09:00~18:00", EARLY), _c("Absent", "#ff0000")],
    [_c("Resignation", "#666666"), _c("", "#666666")],
    [_c("Sat off", "#f2dcdb"), _c("12:00~21:00"), _c("Approved AL", "#3c78d8")],   # 같은 사번 두 번째 줄
]


def test_read_block_and_diff():
    cols = date_columns(HEADER, date(2026, 11, 8), date(2026, 11, 10))
    rows, s = read_block(IDS, BLOCK, 0, cols, 2)
    assert rows[("90000001", "2026-11-09")] == {"status": "지각", "detail": "09:00~18:00", "bg": LATE}
    assert rows[("90000002", "2026-11-09")]["status"] == "조퇴"
    assert ("90000003", "2026-11-08") not in rows                     # 퇴사 표시는 근태 아님
    assert s["agents"] == 3 and s["cells"] == 6 and s["hr_marks"] == 1
    assert s["by_status"] == {"정상": 1, "지각": 1, "조퇴": 1, "결근": 1, "연차": 1, "휴무": 1}
    assert s["duplicate_ids"] == ["90000001"] and s["conflicts"][0]["other"] == "12:00~21:00"
    old = {("90000001", "2026-11-08"): rows[("90000001", "2026-11-08")],
           ("90000002", "2026-11-09"): {"status": "정상", "detail": "09:00~18:00", "bg": W},
           ("90000002", "2026-11-07"): {"status": "정상", "detail": "x", "bg": W},      # 시트에서 사라진 칸
           ("90000099", "2026-11-08"): {"status": "정상", "detail": "x", "bg": W}}      # 시트에 없는 사람 → 둠
    up, de = diff(rows, old, {"90000001", "90000002", "90000003"})
    assert len(up) == 5 and ("90000001", "2026-11-08") not in {(u["agent_id"], u["date"]) for u in up}
    assert de == [("90000002", "2026-11-07")]


class Reader:
    def __init__(self, block):
        self.block, self.calls = block, []

    def values(self, sheet, a1):
        self.calls.append(a1)
        return [HEADER] if a1.endswith("!1:1") else [[i] for i in IDS]

    def cells(self, sheet, a1):
        self.calls.append(a1)
        assert a1 == "'Schedule KR'!C1:E6"                          # 기간 열만
        return self.block


@pytest.fixture
def store(backend, monkeypatch):
    from app.modules.roster.data.sample import RosterSample
    monkeypatch.setattr(sync_mod, "kst_today", lambda: date(2026, 11, 10))
    return RosterSample(backend.dir)


def _run(store, block, **kw):
    return AttendanceSync(Reader(block), store).run("S", "Schedule KR", "m@x", date(2026, 11, 1), **kw)


def test_sync_preview_save_then_only_changes(store):
    out = _run(store, BLOCK)
    assert out["upserts"] == 6 and out["load_id"] is None and store.attendance_rows("2026-11-01", "2026-11-30") == []
    out = _run(store, BLOCK, dry_run=False)
    assert out["load_id"] and len(store.attendance_rows("2026-11-01", "2026-11-30")) == 6
    assert _run(store, BLOCK)["upserts"] == 0                                   # 그대로면 쓸 것 없음
    b = copy.deepcopy(BLOCK)
    b[3][2] = _c("09:00~18:00")                                                 # 결근 → 정상으로 고침
    b[3][0] = _c("")                                                            # 칸 지움
    out = _run(store, b, dry_run=False)
    assert (out["upserts"], out["deletes"]) == (1, 1)
    got = {(r["agent_id"], r["date"]): r["status"] for r in store.attendance_rows("2026-11-01", "2026-11-30")}
    assert got[("90000002", "2026-11-10")] == "정상" and ("90000002", "2026-11-08") not in got
    assert store.attendance_loads(1)[0]["upserts"] == 1


def test_future_dates_skipped_and_default_since(store):
    out = AttendanceSync(Reader(BLOCK), store).run("S", "Schedule KR", "m", date(2026, 11, 8), date(2026, 12, 31))
    assert out["until"] == "2026-11-10"                                         # 오늘(한국) 넘는 날짜는 안 읽음
    assert default_since(date(2026, 1, 15)) == date(2025, 12, 1)


def test_delete_guard(store, monkeypatch):
    _run(store, BLOCK, dry_run=False)
    monkeypatch.setattr(sync_mod, "MIN_DELETE_GUARD", 1)
    empty = [r if i < 2 else [_c("")] * 3 for i, r in enumerate(BLOCK)]
    out = _run(store, empty)
    assert out["deletes"] == 6 and "너무 많습니다" in out["refused"]
    with pytest.raises(AttendanceRefused):
        _run(store, empty, dry_run=False)
    assert _run(store, empty, dry_run=False, force=True)["deletes"] == 6


def test_attendance_page(backend, monkeypatch):
    from fastapi.testclient import TestClient

    from app.main import app
    from app.modules.info import pages
    monkeypatch.setattr(pages, "GoogleSheetReader", lambda: Reader(BLOCK))
    monkeypatch.setattr(sync_mod, "kst_today", lambda: date(2026, 11, 10))
    c = TestClient(app)
    c.cookies.set("dev_user", "manager@example.com")
    r = c.post("/info/attendance-sync", data={"mode": "preview"})
    assert r.status_code == 200 and "근태 미리보기" in r.text and "바뀔 칸 <b>6</b>" in r.text
    r = c.post("/info/attendance-sync", data={"mode": "save"})
    assert "근태 반영" in r.text and "마지막 반영" in c.get("/info").text
    c.cookies.set("dev_user", "viewer@example.com")
    assert c.post("/info/attendance-sync", data={"mode": "save"}).status_code == 403


def test_bigquery_sql_params(monkeypatch):
    calls = []

    class P:
        def __init__(self, name, typ, value):
            self.name = name

    class Cfg:
        def __init__(self, query_parameters=()):
            self.p = query_parameters

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
    b = RosterBigQuery("v12-2027", "asia-northeast3", "roster", "common")
    b.ATT_CHUNK = 2
    b.attendance_rows("2026-11-01", "2026-11-10")
    b.apply_attendance([{"agent_id": "1", "date": "2026-11-01", "status": "정상", "detail": "x", "bg": W}] * 3,
                       [("1", "2026-11-02")], {"load_id": "A1", "loaded_by": "m", "source": "S/T", "since": "2026-11-01",
                                               "until": "2026-11-10", "agents": 1, "cells": 3, "upserts": 3,
                                               "deletes": 1, "by_status": {"정상": 3}, "unknown": []})
    b.attendance_loads(5)
    assert len(calls) == 1 + 2 + 1 + 1                                         # 읽기, MERGE 2번(4건/2), 기록, 기록 읽기
    for sql, bound in calls:
        assert set(re.findall(r"@(\w+)", sql)) <= bound
    assert "`v12-2027.common.fact_attendance`" in calls[1][0] and "`v12-2027.roster`.attendance_loads" in calls[3][0]
