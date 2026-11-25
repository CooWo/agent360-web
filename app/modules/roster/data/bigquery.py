"""RosterBigQuery — 데이터셋 ROSTER_DATASET (기본 `roster`). 표 정의: sql/ddl/04_roster.sql.
보드는 버전마다 JSON 한 줄(board_versions), 초안은 사용자별 한 줄(board_drafts). SQL 은 @매개변수만."""
from __future__ import annotations

import json
import uuid
from datetime import date, datetime, timezone

INFO_COLS = ("emp_id", "airbnb_id", "name", "e_name", "ldap", "joined", "role", "market", "left")


class RosterBigQuery:
    def __init__(self, project: str, location: str, dataset: str):
        from google.cloud import bigquery  # 지연 import

        self._bq = bigquery
        self.client = bigquery.Client(project=project or None)
        self.location = location
        self.d = f"`{self.client.project}.{dataset}`"

    def _q(self, sql: str, **params) -> list[dict]:
        qp = [self._bq.ScalarQueryParameter(k, "INT64" if isinstance(v, int) else "STRING", v) for k, v in params.items()]
        job = self.client.query(sql, job_config=self._bq.QueryJobConfig(query_parameters=qp), location=self.location)
        return [{k: (v.isoformat() if isinstance(v, (date, datetime)) else v) for k, v in dict(r).items()}
                for r in job.result()]

    def agent_info(self) -> list[dict]:
        cols = ", ".join(f"`{c}`" for c in INFO_COLS)
        rows = self._q(f"SELECT {cols} FROM {self.d}.agent_info ORDER BY emp_id")
        return [{k: ("" if v is None else str(v)) for k, v in r.items()} for r in rows]

    def board(self) -> list[dict]:
        rows = self._q(f"SELECT doc FROM {self.d}.board_versions ORDER BY saved_at DESC LIMIT 1")
        return json.loads(rows[0]["doc"]) if rows else []

    def save_board(self, rows: list[dict], by: str) -> str:
        vid = "V" + uuid.uuid4().hex[:10]
        self._q(f"""INSERT INTO {self.d}.board_versions (version_id, saved_at, saved_by, row_count, doc)
                    VALUES (@version_id, CURRENT_TIMESTAMP(), @saved_by, @row_count, @doc)""",
                version_id=vid, saved_by=by, row_count=len(rows), doc=json.dumps(rows, ensure_ascii=False))
        return vid

    def versions(self, limit: int = 20) -> list[dict]:
        rows = self._q(f"""SELECT version_id, saved_at, saved_by, row_count AS count FROM {self.d}.board_versions
                           ORDER BY saved_at DESC LIMIT @limit""", limit=limit)
        return rows

    def draft(self, email: str) -> dict | None:
        rows = self._q(f"SELECT saved_at, doc FROM {self.d}.board_drafts WHERE email = @email", email=email.lower())
        return {"saved_at": rows[0]["saved_at"], "rows": json.loads(rows[0]["doc"])} if rows else None

    def save_draft(self, email: str, rows: list[dict]) -> dict:
        self._q(f"""MERGE {self.d}.board_drafts t USING (SELECT @email AS email) s ON t.email = s.email
                    WHEN MATCHED THEN UPDATE SET saved_at = CURRENT_TIMESTAMP(), doc = @doc
                    WHEN NOT MATCHED THEN INSERT (email, saved_at, doc) VALUES (@email, CURRENT_TIMESTAMP(), @doc)""",
                email=email.lower(), doc=json.dumps(rows, ensure_ascii=False))
        return {"saved_at": datetime.now(timezone.utc).isoformat(), "rows": rows}

    def clear_draft(self, email: str) -> None:
        self._q(f"DELETE FROM {self.d}.board_drafts WHERE email = @email", email=email.lower())
