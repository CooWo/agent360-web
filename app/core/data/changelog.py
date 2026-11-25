"""변경 묶음(ChangeSet) 저장소 — sample 과 bigquery 두 구현 (core/changes.py 의 ChangeLog)."""
from __future__ import annotations

import json
import threading
from functools import lru_cache
from pathlib import Path

from app.core.config import Settings, get_settings
from app.core.registry import Registry


class JsonChangeLog:
    """sample_data/runtime/change_log.json (원본 샘플은 건드리지 않음)."""

    def __init__(self, sample_dir: str | Path):
        self.path = Path(sample_dir) / "runtime" / "change_log.json"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def _read(self) -> list[dict]:
        return json.loads(self.path.read_text(encoding="utf-8")) if self.path.exists() else []

    def save(self, change: dict) -> None:
        with self._lock:
            rows = [r for r in self._read() if r["change_id"] != change["change_id"]]
            rows.append(change)
            self.path.write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")

    def get(self, change_id: str) -> dict | None:
        return next((r for r in self._read() if r["change_id"] == change_id), None)

    def list(self, kind: str | None = None, limit: int = 50) -> list[dict]:
        rows = [r for r in self._read() if kind is None or r["kind"] == kind]
        return sorted(rows, key=lambda r: (r["created_at"], r["change_id"]), reverse=True)[:limit]


class BigQueryChangeLog:
    """MODULE_DATASET.change_log (sql/ddl/02_agent360.sql). 문서 전체를 JSON 문자열로, 찾는 열은 따로."""

    def __init__(self, project: str, location: str, dataset: str):
        from google.cloud import bigquery  # 지연 import

        self._bq = bigquery
        self.client = bigquery.Client(project=project or None)
        self.location = location
        self.t = f"`{self.client.project}.{dataset}.change_log`"

    def _q(self, sql: str, **params) -> list[dict]:
        qp = [self._bq.ScalarQueryParameter(k, "INT64" if isinstance(v, int) else "STRING", v) for k, v in params.items()]
        job = self.client.query(sql, job_config=self._bq.QueryJobConfig(query_parameters=qp), location=self.location)
        return [dict(r) for r in job.result()]

    def save(self, change: dict) -> None:
        self._q(f"""MERGE {self.t} t
                    USING (SELECT @change_id AS change_id) s ON t.change_id = s.change_id
                    WHEN MATCHED THEN UPDATE SET status = @status, doc = @doc, updated_at = CURRENT_TIMESTAMP()
                    WHEN NOT MATCHED THEN INSERT (change_id, kind, status, actor, created_at, doc, updated_at)
                      VALUES (@change_id, @kind, @status, @actor, TIMESTAMP(@created_at), @doc, CURRENT_TIMESTAMP())""",
                change_id=change["change_id"], kind=change["kind"], status=change["status"], actor=change["actor"],
                created_at=change["created_at"], doc=json.dumps(change, ensure_ascii=False))

    def get(self, change_id: str) -> dict | None:
        rows = self._q(f"SELECT doc FROM {self.t} WHERE change_id = @change_id", change_id=change_id)
        return json.loads(rows[0]["doc"]) if rows else None

    def list(self, kind: str | None = None, limit: int = 50) -> list[dict]:
        rows = self._q(f"""SELECT doc FROM {self.t} WHERE (@kind IS NULL OR kind = @kind)
                           ORDER BY created_at DESC, change_id DESC LIMIT @limit""", kind=kind, limit=limit)
        return [json.loads(r["doc"]) for r in rows]


CHANGE_LOGS: Registry = Registry("변경 기록 저장소")
CHANGE_LOGS.register("sample", lambda sample_dir, project, location, dataset: JsonChangeLog(sample_dir))
CHANGE_LOGS.register("bigquery", lambda sample_dir, project, location, dataset: BigQueryChangeLog(project, location, dataset))


@lru_cache
def _make(kind: str, sample_dir: str, project: str, location: str, dataset: str):
    return CHANGE_LOGS.create(kind, sample_dir, project, location, dataset)


def get_change_log():
    s: Settings = get_settings()
    return _make(s.data_backend, str(s.sample_dir), s.gcp_project, s.bq_location, s.module_dataset)
