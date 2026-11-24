"""샘플 데이터를 BigQuery 개발 데이터셋에 올린다 (2단계 연결 확인용).

    python scripts/load_sample_to_bq.py --project <PROJECT> [--common common_dev] [--module agent360_dev]

먼저 sql/ddl/*.sql 로 테이블을 만들어 두세요. 같은 테이블이 있으면 덮어씁니다(WRITE_TRUNCATE).
"""
import argparse
import json
from pathlib import Path

from google.cloud import bigquery

ROOT = Path(__file__).resolve().parents[1] / "sample_data"
TABLES = {  # json 파일 → (데이터셋 종류, 테이블)
    "agents": ("common", "dim_agent"), "kpi_daily": ("common", "fact_kpi_daily"),
    "attendance": ("common", "fact_attendance"), "qa": ("common", "fact_qa"),
    "training": ("common", "fact_training"), "incentive": ("common", "fact_incentive"),
    "coaching": ("module", "fact_coaching"), "signals": ("module", "mart_signals"),
    "signal_rules": ("module", "signal_rules"),
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", required=True)
    ap.add_argument("--location", default="asia-northeast3")
    ap.add_argument("--common", default="common")
    ap.add_argument("--module", default="agent360")
    a = ap.parse_args()
    client = bigquery.Client(project=a.project, location=a.location)
    ds = {"common": a.common, "module": a.module}
    teams = {t["team"]: t["sector"] for t in json.loads((ROOT / "teams.json").read_text(encoding="utf-8"))}

    def load(rows, dataset, table):
        tid = f"{a.project}.{dataset}.{table}"
        schema = client.get_table(tid).schema
        cfg = bigquery.LoadJobConfig(schema=schema, write_disposition="WRITE_TRUNCATE")
        client.load_table_from_json(rows, tid, job_config=cfg).result()
        print(f"{tid}: {len(rows)}행")

    for name, (kind, table) in TABLES.items():
        rows = json.loads((ROOT / f"{name}.json").read_text(encoding="utf-8"))
        if name == "agents":
            rows = [{**r, "sector": teams.get(r["team"])} for r in rows]
        if name == "signal_rules":
            rows = [{**r, "params": json.dumps(r.get("params") or {})} for r in rows]
        load(rows, ds[kind], table)

    users = json.loads((ROOT / "users.json").read_text(encoding="utf-8"))
    load([{**u, "active": True} for u in users], ds["module"], "user_roles")
    issues = json.loads((ROOT / "issue_types.json").read_text(encoding="utf-8"))
    load([{"issue_type": t if isinstance(t, str) else t["issue_type"], "sort_order": i, "active": True}
          for i, t in enumerate(issues)], ds["module"], "issue_types")


if __name__ == "__main__":
    main()
