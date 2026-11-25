"""BigQuery 없이 확인할 수 있는 것들.
1) 샘플 데이터 열이 DDL 테이블 열과 맞는지 (적재 시 'no such field' 방지)
2) BigQueryBackend 의 모든 SQL 이 쓰는 @매개변수를 실제로 넘기는지 (가짜 클라이언트로 SQL 만 수집)
"""
import re
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _ddl_columns() -> dict[str, dict[str, bool]]:
    """{'dim_agent': {'agent_id': True(NOT NULL), ...}}"""
    out = {}
    for f in (ROOT / "sql" / "ddl").glob("*.sql"):
        for m in re.finditer(r"CREATE TABLE IF NOT EXISTS `[^`]+\.(\w+)` \((.*?)\n\)", f.read_text(encoding="utf-8"), re.S):
            cols = {}
            for line in m.group(2).splitlines():
                for part in re.sub(r"OPTIONS \(.*?\)", "", line).split(","):   # 한 줄에 열 여러 개도 허용
                    c = re.match(r"\s*(\w+)\s+([A-Z0-9<>]+)(.*)", part)
                    if c:
                        cols[c.group(1)] = "NOT NULL" in c.group(3)
            out[m.group(1)] = cols
    return out


def test_sample_rows_fit_ddl():
    sys.path.insert(0, str(ROOT / "scripts"))
    import bq_setup
    ddl = _ddl_columns()
    for (_, table), rows in bq_setup._sample_rows().items():
        cols = ddl[table]
        extra = set().union(*(r.keys() for r in rows)) - set(cols)
        assert not extra, f"{table}: DDL 에 없는 열 {extra}"
        for name, required in cols.items():
            if required:
                assert all(r.get(name) is not None for r in rows), f"{table}.{name} NOT NULL 인데 빈 값"


def test_ddl_sql_project_and_dataset_rename():
    sys.path.insert(0, str(ROOT / "scripts"))
    import bq_setup
    sql = "\n".join(s for _, s in bq_setup.ddl_sql("v12-2027", "common_dev", "agent360_dev", "asia-northeast3"))
    assert "${PROJECT}" not in sql
    assert "`v12-2027.common_dev.dim_agent`" in sql and "`v12-2027.agent360_dev.user_roles`" in sql
    assert "`v12-2027.common." not in sql and "`v12-2027.agent360." not in sql
    assert "`v12-2027.kpi.v_agent`" in sql and "`v12-2027.roster.v_agent_info`" in sql


def test_kpi_refresh_fills_every_table_column():
    """갱신 SQL 의 INSERT SELECT 식 개수 = 표 열 개수, 앱이 읽는 열은 뷰에 있음."""
    sys.path.insert(0, str(ROOT / "scripts"))
    import bq_setup
    from app.core.data.bigquery import KPI_FIELDS
    ddl = _ddl_columns()
    sql = bq_setup.kpi_refresh_sql("v12-2027", 30)
    assert "${" not in sql and "INTERVAL 30 DAY" in sql and "BEGIN TRANSACTION" in sql
    for table in ("specialist_case_daily", "specialist_time_daily", "case_kpi_weekly", "survey_weekly"):
        body = sql.split(f"INSERT INTO `v12-2027.kpi.{table}`")[1].split("FROM `v11-2026")[0]
        exprs, depth, n = body.split("SELECT", 1)[1], 0, 1
        for ch in exprs:
            depth += ch == "("
            depth -= ch == ")"
            n += ch == "," and depth == 0
        assert n == len(ddl[table]), f"{table}: SELECT {n}개, 표 열 {len(ddl[table])}개"
    view = (ROOT / "sql" / "ddl" / "05_kpi.sql").read_text(encoding="utf-8").split("v_agent_kpi_daily")[1]
    assert all(f in view for f in KPI_FIELDS)
    with pytest.raises(ValueError):
        bq_setup.kpi_refresh_sql("v12-2027", 0)


class _FakeBQ(types.ModuleType):
    """google.cloud.bigquery 대용: 매개변수 객체와 SQL 만 모은다."""

    def __init__(self):
        super().__init__("google.cloud.bigquery")
        self.calls = []
        fake = self

        class P:
            def __init__(self, name, typ, value):
                self.name, self.typ, self.value = name, typ, value

        class QueryJobConfig:
            def __init__(self, query_parameters=()):
                self.query_parameters = list(query_parameters)

        class Job:
            def result(self):
                return []

        class Client:
            def __init__(self, project=None, **kw):
                self.project = project

            def query(self, sql, job_config=None, location=None):
                fake.calls.append((sql, {p.name for p in job_config.query_parameters}))
                return Job()

        self.ScalarQueryParameter = P
        self.ArrayQueryParameter = P
        self.QueryJobConfig = QueryJobConfig
        self.Client = Client


@pytest.fixture()
def fake_backend(monkeypatch):
    fake = _FakeBQ()
    google = types.ModuleType("google")
    cloud = types.ModuleType("google.cloud")
    cloud.bigquery = fake
    google.cloud = cloud
    monkeypatch.setitem(sys.modules, "google", google)
    monkeypatch.setitem(sys.modules, "google.cloud", cloud)
    monkeypatch.setitem(sys.modules, "google.cloud.bigquery", fake)
    from app.core.data.bigquery import BigQueryBackend
    return BigQueryBackend("v12-2027", "asia-northeast3", "common", "agent360", 0), fake


def test_every_sql_param_is_bound(fake_backend):
    from app.core.permissions import Scope
    b, fake = fake_backend
    sv = Scope(all_teams=False, teams=("R1-A",))
    b.as_of(); b.get_user("a@ubase.co.kr"); b.list_users(); b.list_teams()
    b.list_agents(sv, q="kim", team="R1-A"); b.list_agents(sv)
    b.kpi_daily("E1", "2026-01-01"); b.kpi_daily("E1", None); b.kpi_daily_many(["E1", "E2"], "2026-01-01")
    b.attendance("E1", "2026-01-01")
    b.qa("E1", "2026-01-01"); b.training("E1"); b.incentive("E1")
    b.coaching(sv); b.coaching(sv, "E1")
    b.add_coaching({"agent_id": "E1", "sv_email": "s@ubase.co.kr", "date": "2026-11-20", "issue_type": "근태",
                    "summary": "s", "agreed_action": "a", "follow_up_date": "2026-11-27", "raw_note": ""})
    b.complete_coaching("C1", "s@ubase.co.kr")
    b.signals(sv, "2026-11-20"); b.set_signal_status("S1", "확인", "s@ubase.co.kr")
    b.signal_rules(); b.issue_types()
    b.qa_coaching(); b.deactivate_qa_coaching("CH1")
    b.add_qa_coaching([{"row_id": "Q1", "change_id": "CH1", "agent_id": "E1", "qa_avg": 80.5, "evaluations": 2}])
    b.write_audit({"ts": "2026-11-20T00:00:00+00:00", "actor": "a", "role": "sv", "action": "x",
                   "target_type": "agent", "target_id": "E1", "detail": {}})
    assert len(fake.calls) >= 20
    for sql, bound in fake.calls:
        used = set(re.findall(r"@(\w+)", sql))
        assert used <= bound, f"넘기지 않은 매개변수 {used - bound}:\n{sql}"
        assert "`v12-2027.common`" in sql or "`v12-2027.agent360`" in sql or "`v12-2027.kpi`" in sql or "`v12-2027.kpi.v_agent`" in sql


def test_each_ddl_creates_its_dataset():
    for f in (ROOT / "sql" / "ddl").glob("*.sql"):
        assert "CREATE SCHEMA IF NOT EXISTS" in f.read_text(encoding="utf-8"), f.name
