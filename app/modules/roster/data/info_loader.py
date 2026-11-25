"""INFO 불러오기 저장 — info_raw(쌓기) · mart_agent_info(통째로 바꾸기) · info_loads(기록).

BigQuery 적재 작업(load job)으로 넣는다 (streaming insert 아님 → 바로 DML 가능).
안전장치: 새 마트 행 수가 지금의 절반 미만이면 멈춘다 (시트가 깨졌을 가능성). force=True 로만 통과.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

from app.modules.roster.services.info import DATE_FIELDS, FIELDS, CleanResult


class LoadRefused(Exception):
    pass


class InfoMartLoader:
    def __init__(self, project: str, location: str, dataset: str, client=None):
        from google.cloud import bigquery  # 지연 import

        self._bq = bigquery
        self.client = client or bigquery.Client(project=project or None, location=location)
        self.base = f"{self.client.project}.{dataset}"

    def _load(self, table: str, rows: list[dict], truncate: bool) -> None:
        bq = self._bq
        t = self.client.get_table(f"{self.base}.{table}")
        cfg = bq.LoadJobConfig(schema=t.schema, source_format=bq.SourceFormat.NEWLINE_DELIMITED_JSON,
                               write_disposition=bq.WriteDisposition.WRITE_TRUNCATE if truncate
                               else bq.WriteDisposition.WRITE_APPEND)
        self.client.load_table_from_json(rows, t, job_config=cfg).result()

    def current_count(self) -> int:
        rows = list(self.client.query(f"SELECT COUNT(*) AS n FROM `{self.base}.mart_agent_info`").result())
        return int(rows[0]["n"]) if rows else 0

    def save(self, raw: list[dict], raw_cells: list[list], clean: CleanResult, source: str, by: str,
             force: bool = False) -> str:
        now = datetime.now(timezone.utc).isoformat()
        cur = self.current_count()
        if cur and len(clean.rows) < cur * 0.5 and not force:
            raise LoadRefused(f"새 마트 {len(clean.rows)}행 < 지금 {cur}행의 절반. 시트를 확인하거나 --force 로 진행하세요.")
        load_id = "L" + datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S") + uuid.uuid4().hex[:4]
        self._load("info_raw", [{"load_id": load_id, "loaded_at": now, "row_no": r["row_no"],
                                 **{f: r.get(f, "") for f in FIELDS},
                                 "raw_json": json.dumps(raw_cells[r["row_no"] - 1], ensure_ascii=False)}
                                for r in raw], truncate=False)
        self._load("mart_agent_info", [{**{f: (r[f] or None) if f in DATE_FIELDS else r[f] for f in FIELDS},
                                        "load_id": load_id, "loaded_at": now} for r in clean.rows], truncate=True)
        self._load("info_loads", [{"load_id": load_id, "loaded_at": now, "loaded_by": by, "source": source,
                                   **clean.summary(),
                                   "issue_json": json.dumps({"duplicates": sorted(set(clean.duplicates)),
                                                             "issues": clean.issues[:500]}, ensure_ascii=False)}],
                   truncate=False)
        return load_id
