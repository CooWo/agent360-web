"""INFO 자동화 시트 → raw → 마트: 정리 규칙, 적재(가짜 BigQuery), 화면."""
import types

import pytest

from app.core import templating
from app.core.errors import PermissionDenied
from app.core.modules import discover
from app.core.permissions import User
from app.modules.info import views
from app.modules.roster.data.sample import RosterSample
from app.modules.roster.services.info import FIELDS, InfoCleaner, parse_date, raw_rows, tenure_bucket

HEADER = ["사번", "한글명", "Name", "Email", "Airbnb ID", "CE/SR1 Batch", "Tenure", "Shift Type", "Location", "TL",
          "Type", "Tier", "LDAP", "FTE", "", "온보딩 날짜", "R2 온보딩", "Universal", "근속 인센티브", "입사일(UHR)",
          "재직정보", "퇴사 Tenure", "Universal 전\nTier", "R2 온보딩 기준 Tenure", "비고"]


def row(emp, name, status="재직자", joined="2021-03-21", email="A@X.CO", onboarding=""):
    r = [""] * 25
    r[0], r[1], r[3], r[9], r[15], r[19], r[20] = emp, name, email, "ub_tl", onboarding, joined, status
    return r


@pytest.mark.parametrize("v,want", [("2021-03-21", "2021-03-21"), ("2021. 3. 9", "2021-03-09"), ("2021/3/9", "2021-03-09"),
                                    ("20210309", "2021-03-09"), ("7/31/2026", "2026-07-31"), ("31/7/2026", "2026-07-31"),
                                    ("7-31-26", "2026-07-31"), ("2026년 7월 31일", "2026-07-31"), ("Jul 31, 2026", "2026-07-31"),
                                    ("31 July 2026", "2026-07-31"), ("2026-07-31 10:00:00", "2026-07-31"),
                                    ("13/13/2026", None), ("1800-01-01", None), ("3", None), ("45997", "2025-12-06"), ("2021-02-30", None),
                                    ("내일", None), ("", None)])
def test_parse_date(v, want):
    assert parse_date(v) == want


def test_raw_rows_keeps_first_matching_header_and_skips_blank():
    rows = raw_rows(HEADER + ["사번", "이름"], [row("1", "가") + ["999", "딴사람"], [""] * 5, row("2", "나")])
    assert [r["emp_id"] for r in rows] == ["1", "2"] and rows[1]["row_no"] == 3 and set(rows[0]) == {"row_no", *FIELDS}


def test_cleaner_rules():
    raw = raw_rows(HEADER, [row("'100", "가", email="Ga@UBASE.co.kr", onboarding="2021. 3. 9"),
                            row("", "사번없음"),
                            row("200", "나", status="퇴직자"), row("200", "나", status="재직자"),
                            row("300", "다", joined="모름"), row("400.0", "라", status="-"),
                            row("500", "마", joined="확인안됨", onboarding="퇴사")])
    res = InfoCleaner().clean(raw)
    by = {r["emp_id"]: r for r in res.rows}
    assert list(by) == ["100", "200", "300", "400", "500"]
    assert by["500"]["joined"] == "" and by["500"]["onboarding"] == ""          # 상태 표시는 문제로 안 셈
    assert by["500"]["dates_ok"] and not by["300"]["dates_ok"]
    assert by["100"]["email"] == "ga@ubase.co.kr" and by["100"]["onboarding"] == "2021-03-09"
    assert by["200"]["status"] == "재직자"                    # 중복이면 재직자 줄 우선
    assert by["300"]["joined"] == "" and by["400"]["status"] == ""
    assert res.summary() == {"rows_read": 7, "rows_mart": 5, "dropped_no_id": 1, "duplicates": 1, "issues": 1}
    assert res.issues[0]["field"] == "joined"


def test_tenure_bucket():
    assert tenure_bucket("2026-11-01", "2026-11-25") == "0~30 Days"
    assert tenure_bucket("2026-05-01", "2026-11-25") == "181~365 Days"
    assert tenure_bucket("2021-03-21", "2026-11-25") == "365+ Days" and tenure_bucket("", "2026-11-25") == ""


# ── 적재 (가짜 BigQuery) ────────────────────────────
class FakeBQ:
    class LoadJobConfig:
        def __init__(self, **kw):
            self.kw = kw

    class SourceFormat:
        NEWLINE_DELIMITED_JSON = "NDJSON"

    class WriteDisposition:
        WRITE_TRUNCATE, WRITE_APPEND = "TRUNCATE", "APPEND"


class FakeClient:
    project = "v12-2027"

    def __init__(self, current=0):
        self.loads, self.current = [], current

    def get_table(self, name):
        return types.SimpleNamespace(name=name, schema=[])

    def load_table_from_json(self, rows, table, job_config):
        self.loads.append((table.name.split(".")[-1], job_config.kw["write_disposition"], rows))
        return types.SimpleNamespace(result=lambda: None)

    def query(self, sql):
        return types.SimpleNamespace(result=lambda: [{"n": self.current}])


def _loader(client):
    from app.modules.roster.data.info_loader import InfoMartLoader
    ld = InfoMartLoader.__new__(InfoMartLoader)
    ld._bq, ld.client, ld.base = FakeBQ, client, "v12-2027.roster"
    return ld


def test_loader_appends_raw_truncates_mart_logs_load():
    body = [row("1", "가"), row("2", "나", joined="")]
    raw = raw_rows(HEADER, body)
    res = InfoCleaner().clean(raw)
    c = FakeClient()
    lid = _loader(c).save(raw, body, res, source="S/T", by="me")
    assert [(t, d) for t, d, _ in c.loads] == [("info_raw", "APPEND"), ("mart_agent_info", "TRUNCATE"),
                                               ("info_loads", "APPEND")]
    raw_t, mart, log = (x[2] for x in c.loads)
    assert raw_t[0]["load_id"] == lid and raw_t[0]["raw_json"].startswith('["1"')
    assert mart[1]["joined"] is None and mart[0]["joined"] == "2021-03-21"       # 빈 날짜는 NULL
    assert log[0]["rows_mart"] == 2 and log[0]["loaded_by"] == "me"


def test_loader_refuses_big_drop():
    from app.modules.roster.data.info_loader import LoadRefused
    body = [row("1", "가")]
    raw = raw_rows(HEADER, body)
    with pytest.raises(LoadRefused):
        _loader(FakeClient(current=100)).save(raw, body, InfoCleaner().clean(raw), "S", "me")
    c = FakeClient(current=100)
    _loader(c).save(raw, body, InfoCleaner().clean(raw), "S", "me", force=True)
    assert len(c.loads) == 3


# ── 화면 ───────────────────────────────────────────
def test_info_screen(backend):
    mod = next(m for m in discover(with_routers=False) if m.name == "info")
    u = User("wfm@example.com", "w", "wfm")
    ctx = views.info(RosterSample(backend.dir), u, mod.screens, "2026-11-25")
    html = templating.render("info/info.html", {"sync": None, "sync_error": "", "errors": {}, **ctx}, user=u, module=mod, active="info", with_routers=False)
    assert "상담사 INFO" in html and "Tenure (계산)" in html and "own-wfm" in html and "info.js" in html
    with pytest.raises(PermissionDenied):
        views.info(RosterSample(backend.dir), User("v@x", "v", "viewer"), mod.screens, "2026-11-25")


class FakeReader:
    def __init__(self, cells):
        self.cells, self.asked = cells, []

    def values(self, sheet, rng):
        self.asked.append((sheet, rng))
        return self.cells


def test_sync_service_check_then_save_sample(backend):
    from app.modules.roster.data.info_loader import SampleInfoLoader
    from app.modules.roster.services.info_sync import InfoSyncService
    mod = next(m for m in discover(with_routers=False) if m.name == "info")
    store = RosterSample(backend.dir)
    cells = [HEADER] + [row(str(1000 + i), f"사람{i}") for i in range(30)] + [row("1000", "중복", status="퇴직자")]
    rd = FakeReader(cells)
    wfm = User("wfm@example.com", "w", "wfm")
    out = views.info_sync(InfoSyncService(rd), wfm, mod.screens, dry_run=True)
    assert out["rows_mart"] == 30 and out["duplicates"] == 1 and out["load_id"] is None
    assert rd.asked[0] == (mod.screens["screens"]["info"]["source_sheet"], "'INFO 자동화 시트'!A2:Y")
    assert len(store.agent_info()) == 44                                   # 확인만 → 그대로
    out = views.info_sync(InfoSyncService(rd, SampleInfoLoader(store)), wfm, mod.screens, dry_run=False)
    assert out["load_id"] and len(RosterSample(backend.dir).agent_info()) == 30   # 재시작해도 남음
    assert store.info_loads(1)[0]["load_id"] == out["load_id"]
    with pytest.raises(PermissionDenied):
        views.info_sync(InfoSyncService(rd), User("v@x", "v", "viewer"), mod.screens, dry_run=True)
