"""2단계 BigQuery 준비 도구 — 내 PC 의 가상환경에서 실행 (gcloud 로그인 필요).

    python scripts/bq_setup.py ddl     --project v12-2027        # 데이터셋·테이블 만들기 (sql/ddl/*.sql)
    python scripts/bq_setup.py ddl     --project v12-2027 --recreate   # 표 구조가 바뀌었을 때: 지우고 다시 만들기(데이터 삭제)
    python scripts/bq_setup.py sample  --project v12-2027        # 샘플 데이터 올리기 (덮어쓰기)
    python scripts/bq_setup.py check   --project v12-2027        # 앱이 쓰는 조회를 실제로 한 번씩 돌려 보기
    python scripts/bq_setup.py user    --project v12-2027 --email 나@ubase.co.kr --role admin [--teams R1-A,R1-B]

공통 옵션: --location asia-northeast3 --common common --module agent360 --dry-run(실행 없이 SQL 만 출력)
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
SAMPLE = ROOT / "sample_data"
DDL_DIR = ROOT / "sql" / "ddl"

# sample_data 파일 → (데이터셋 종류, 테이블)
SAMPLE_TABLES = {
    "agents": ("common", "dim_agent"), "kpi_daily": ("common", "fact_kpi_daily"),
    "attendance": ("common", "fact_attendance"), "qa": ("common", "fact_qa"),
    "training": ("common", "fact_training"), "incentive": ("common", "fact_incentive"),
    "coaching": ("module", "fact_coaching"), "signals": ("module", "mart_signals"),
    "signal_rules": ("module", "signal_rules"),
}


def ddl_sql(project: str, common: str, module: str, location: str, recreate: bool = False,
            capacity: str = "capacity", roster: str = "roster") -> list[tuple[str, str]]:
    out = []
    for f in sorted(DDL_DIR.glob("*.sql")):
        sql = f.read_text(encoding="utf-8").replace("${PROJECT}", project)
        if recreate:
            sql = sql.replace("CREATE TABLE IF NOT EXISTS", "CREATE OR REPLACE TABLE")
        sql = re.sub(r"`%s\.common(\.|`)" % re.escape(project), rf"`{project}.{common}\1", sql)
        sql = re.sub(r"`%s\.agent360(\.|`)" % re.escape(project), rf"`{project}.{module}\1", sql)
        sql = re.sub(r"`%s\.capacity(\.|`)" % re.escape(project), rf"`{project}.{capacity}\1", sql)
        sql = re.sub(r"`%s\.roster(\.|`)" % re.escape(project), rf"`{project}.{roster}\1", sql)
        sql = sql.replace("location = 'asia-northeast3'", f"location = '{location}'")
        out.append((f.name, sql))
    return out


def _client(a):
    from google.cloud import bigquery
    return bigquery.Client(project=a.project, location=a.location)


def cmd_ddl(a):
    if a.recreate and not a.dry_run:
        ans = input(f"⚠️ {a.project} 의 {a.common}·{a.module} 표를 모두 지우고 다시 만듭니다 (데이터 삭제). 계속하려면 yes 입력: ")
        if ans.strip().lower() != "yes":
            sys.exit("취소했습니다.")
    for name, sql in ddl_sql(a.project, a.common, a.module, a.location, a.recreate):
        if a.dry_run:
            print(f"-- {name}\n{sql}")
            continue
        _client(a).query(sql).result()
        print(f"✅ {name} 실행 완료")


def _sample_rows() -> dict[tuple[str, str], list[dict]]:
    teams = {t["team"]: t["sector"] for t in json.loads((SAMPLE / "teams.json").read_text(encoding="utf-8"))}
    rows: dict[tuple[str, str], list[dict]] = {}
    for name, key in SAMPLE_TABLES.items():
        data = json.loads((SAMPLE / f"{name}.json").read_text(encoding="utf-8"))
        if name == "agents":
            data = [{**r, "sector": teams.get(r["team"])} for r in data]
        rows[key] = data
    users = json.loads((SAMPLE / "users.json").read_text(encoding="utf-8"))
    rows[("module", "user_roles")] = [{**u, "active": True} for u in users]
    issues = json.loads((SAMPLE / "issue_types.json").read_text(encoding="utf-8"))
    rows[("module", "issue_types")] = [{"issue_type": t, "sort_order": i, "active": True} for i, t in enumerate(issues)]
    return rows


def cmd_sample(a):
    ds = {"common": a.common, "module": a.module}
    if a.dry_run:
        for (kind, table), data in _sample_rows().items():
            print(f"{a.project}.{ds[kind]}.{table}: {len(data)}행 (dry-run)")
        return
    from google.cloud import bigquery
    client = _client(a)
    for (kind, table), data in _sample_rows().items():
        tid = f"{a.project}.{ds[kind]}.{table}"
        cfg = bigquery.LoadJobConfig(schema=client.get_table(tid).schema,
                                     write_disposition="WRITE_TRUNCATE",
                                     source_format=bigquery.SourceFormat.NEWLINE_DELIMITED_JSON)
        client.load_table_from_json(data, tid, job_config=cfg).result()
        print(f"✅ {tid}: {len(data)}행")


def cmd_user(a):
    teams = [t.strip() for t in (a.teams or "").split(",") if t.strip()]
    sql = f"""MERGE `{a.project}.{a.module}.user_roles` t
USING (SELECT LOWER(@email) email, @name name, @role role, @teams teams) s ON LOWER(t.email) = s.email
WHEN MATCHED THEN UPDATE SET name = s.name, role = s.role, teams = s.teams, active = TRUE,
  updated_at = CURRENT_TIMESTAMP(), updated_by = 'bq_setup'
WHEN NOT MATCHED THEN INSERT (email, name, role, teams, active, updated_at, updated_by)
  VALUES (s.email, s.name, s.role, s.teams, TRUE, CURRENT_TIMESTAMP(), 'bq_setup')"""
    if a.role not in ("admin", "manager", "sv", "viewer"):
        sys.exit("--role 은 admin | manager | sv | viewer")
    if a.dry_run:
        print(sql, "\n", a.email, a.role, teams)
        return
    from google.cloud import bigquery
    cfg = bigquery.QueryJobConfig(query_parameters=[
        bigquery.ScalarQueryParameter("email", "STRING", a.email),
        bigquery.ScalarQueryParameter("name", "STRING", a.name or a.email.split("@")[0]),
        bigquery.ScalarQueryParameter("role", "STRING", a.role),
        bigquery.ArrayQueryParameter("teams", "STRING", teams),
    ])
    _client(a).query(sql, job_config=cfg).result()
    print(f"✅ {a.email} → {a.role} {teams or '(전체)'}")


def cmd_check(a):
    """앱의 BigQueryBackend 로 실제 조회를 한 번씩 돌린다 (쓰기는 하지 않음)."""
    from app.core.data.bigquery import BigQueryBackend
    from app.core.permissions import Scope
    b = BigQueryBackend(a.project, a.location, a.common, a.module, cache_seconds=0)
    allv = Scope(all_teams=True, teams=())
    steps = [
        ("기준일 as_of", lambda: b.as_of()),
        ("사용자 user_roles", lambda: len(b.list_users())),
        ("팀 목록", lambda: [t["team"] for t in b.list_teams()]),
        ("상담사 수(전체)", lambda: len(b.list_agents(allv))),
    ]
    ok = True
    for label, fn in steps:
        try:
            print(f"✅ {label}: {fn()}")
        except Exception as e:  # noqa: BLE001
            ok = False
            print(f"❌ {label}: {e}")
    try:
        agents = b.list_agents(allv)
        aid = agents[0]["agent_id"]
        team = agents[0]["team"]
        one = Scope(all_teams=False, teams=(team,))
        for label, fn in [
            (f"팀 범위({team}) 상담사 수", lambda: len(b.list_agents(one))),
            (f"KPI 일별({aid})", lambda: len(b.kpi_daily(aid, "2000-01-01"))),
            ("근태", lambda: len(b.attendance(aid, "2000-01-01"))),
            ("QA", lambda: len(b.qa(aid, "2000-01-01"))),
            ("교육", lambda: len(b.training(aid))),
            ("인센티브", lambda: len(b.incentive(aid))),
            ("코칭(전체)", lambda: len(b.coaching(allv))),
            ("오늘 신호", lambda: len(b.signals(allv))),
            ("신호 규칙", lambda: len(b.signal_rules())),
            ("이슈 유형", lambda: len(b.issue_types())),
        ]:
            try:
                print(f"✅ {label}: {fn()}")
            except Exception as e:  # noqa: BLE001
                ok = False
                print(f"❌ {label}: {e}")
    except Exception as e:  # noqa: BLE001
        ok = False
        print(f"❌ 상담사 조회 실패: {e}")
    print("\n모두 정상 — .env 에서 DATA_BACKEND=bigquery 로 바꿔 실행하세요." if ok else "\n❌ 위 오류 줄을 복사해서 알려 주세요.")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["ddl", "sample", "check", "user"])
    ap.add_argument("--project", required=True)
    ap.add_argument("--location", default="asia-northeast3")
    ap.add_argument("--common", default="common")
    ap.add_argument("--module", default="agent360")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--recreate", action="store_true", help="ddl: 표를 지우고 다시 만든다 (데이터 삭제)")
    ap.add_argument("--email")
    ap.add_argument("--name")
    ap.add_argument("--role")
    ap.add_argument("--teams")
    a = ap.parse_args()
    if a.cmd == "user" and not (a.email and a.role):
        ap.error("user 는 --email, --role 이 필요합니다")
    {"ddl": cmd_ddl, "sample": cmd_sample, "check": cmd_check, "user": cmd_user}[a.cmd](a)


if __name__ == "__main__":
    main()
