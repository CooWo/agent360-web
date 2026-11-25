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
                                        "dates_ok": r.get("dates_ok", True), "load_id": load_id, "loaded_at": now}
                                       for r in clean.rows], truncate=True)
        self._load("info_loads", [{"load_id": load_id, "loaded_at": now, "loaded_by": by, "source": source,
                                   **clean.summary(),
                                   "issue_json": json.dumps({"duplicates": sorted(set(clean.duplicates)),
                                                             "issues": clean.issues[:500]}, ensure_ascii=False)}],
                   truncate=False)
        return load_id


class SampleInfoLoader:
    """sample 모드: 정리 결과를 sample_data/runtime/roster_info_mart.json 에 (원본 샘플은 그대로)."""

    def __init__(self, store):
        self.store = store

    def save(self, raw, raw_cells, clean: CleanResult, source: str, by: str, force: bool = False) -> str:
        cur = len(self.store.agent_info())
        if cur and len(clean.rows) < cur * 0.5 and not force:
            raise LoadRefused(f"새 마트 {len(clean.rows)}행 < 지금 {cur}행의 절반. 시트를 확인하거나 강제로 진행하세요.")
        load_id = "L" + datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S") + uuid.uuid4().hex[:4]
        self.store.replace_info(clean.rows, {"load_id": load_id, "loaded_at": datetime.now(timezone.utc).isoformat(),
                                             "loaded_by": by, "source": source, **clean.summary()})
        return load_id


def info_loader(store):
    """지금 데이터 백엔드에 맞는 저장기 (sample | bigquery)."""
    from app.core.config import get_settings
    s = get_settings()
    if s.data_backend == "bigquery":
        return InfoMartLoader(s.gcp_project, s.bq_location, s.roster_dataset)
    return SampleInfoLoader(store)


class TeamRosterLoader:
    """팀 구성(OPS TL) → roster.team_roster 통째로 바꾸기 (load job)."""

    def __init__(self, project: str, location: str, dataset: str, client=None):
        from google.cloud import bigquery  # 지연 import

        self._bq = bigquery
        self.client = client or bigquery.Client(project=project or None, location=location)
        self.base = f"{self.client.project}.{dataset}"

    def save(self, rows: list[dict], source: str, by: str, force: bool = False) -> str:
        from app.modules.roster.services.team_sync import MIN_KEEP, new_load_id
        cur = list(self.client.query(f"SELECT COUNT(*) AS n FROM `{self.base}.team_roster`").result())
        cur = int(cur[0]["n"]) if cur else 0
        if cur and len(rows) < cur * MIN_KEEP and not force:
            raise LoadRefused(f"새 명단 {len(rows)}명 < 지금 {cur}명의 절반. 시트를 확인하거나 강제로 진행하세요.")
        load_id, now = new_load_id(), datetime.now(timezone.utc).isoformat()
        bq = self._bq
        t = self.client.get_table(f"{self.base}.team_roster")
        cfg = bq.LoadJobConfig(schema=t.schema, source_format=bq.SourceFormat.NEWLINE_DELIMITED_JSON,
                               write_disposition=bq.WriteDisposition.WRITE_TRUNCATE)
        self.client.load_table_from_json([{**r, "load_id": load_id, "loaded_at": now, "loaded_by": by, "source": source}
                                          for r in rows], t, job_config=cfg).result()
        return load_id


class SampleTeamRosterLoader:
    def __init__(self, store):
        self.store = store

    def save(self, rows: list[dict], source: str, by: str, force: bool = False) -> str:
        from app.modules.roster.services.team_sync import MIN_KEEP, new_load_id
        cur = len(self.store.team_roster())
        if cur and len(rows) < cur * MIN_KEEP and not force:
            raise LoadRefused(f"새 명단 {len(rows)}명 < 지금 {cur}명의 절반. 시트를 확인하거나 강제로 진행하세요.")
        load_id, now = new_load_id(), datetime.now(timezone.utc).isoformat()
        self.store.replace_team_roster([{**r, "load_id": load_id, "loaded_at": now, "loaded_by": by, "source": source}
                                        for r in rows])
        return load_id


def team_loader(store):
    from app.core.config import get_settings
    s = get_settings()
    if s.data_backend == "bigquery":
        return TeamRosterLoader(s.gcp_project, s.bq_location, s.roster_dataset)
    return SampleTeamRosterLoader(store)
