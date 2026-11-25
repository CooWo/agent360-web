"""RosterBigQuery — 데이터셋 ROSTER_DATASET (기본 `roster`). 표 정의: sql/ddl/04_roster.sql.
보드는 버전마다 JSON 한 줄(board_versions), 초안은 사용자별 한 줄(board_drafts). SQL 은 @매개변수만."""
from __future__ import annotations

import json
import uuid
from datetime import date, datetime, timezone

from app.modules.roster.services.info import FIELDS as INFO_COLS


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
        rows = self._q(f"SELECT {cols} FROM {self.d}.mart_agent_info ORDER BY emp_id")
        return [{k: ("" if v is None else str(v)) for k, v in r.items()} for r in rows]

    def info_loads(self, limit: int = 10) -> list[dict]:
        return self._q(f"""SELECT load_id, loaded_at, loaded_by, source, rows_read, rows_mart, dropped_no_id,
                                  duplicates, issues FROM {self.d}.info_loads ORDER BY loaded_at DESC LIMIT @limit""",
                       limit=limit)

    def team_roster(self) -> list[dict]:
        return self._q(f"""SELECT tl_name, sort_order, shift, emp_id, name, e_name, display_name, load_id,
                                  CAST(loaded_at AS STRING) loaded_at, loaded_by
                           FROM {self.d}.team_roster ORDER BY sort_order, emp_id""")

    def info_edits(self) -> list[dict]:
        return self._q(f"""SELECT edit_id, change_id, emp_id, field, value, is_new, edited_at, edited_by
                           FROM {self.d}.info_edits WHERE active ORDER BY edited_at, edit_id""")

    def add_info_edits(self, rows: list[dict]) -> None:
        self._q(f"""INSERT INTO {self.d}.info_edits
                      (edit_id, change_id, emp_id, field, value, is_new, edited_at, edited_by, active)
                    SELECT JSON_VALUE(e, '$.edit_id'), JSON_VALUE(e, '$.change_id'), JSON_VALUE(e, '$.emp_id'),
                           JSON_VALUE(e, '$.field'), JSON_VALUE(e, '$.value'), JSON_VALUE(e, '$.is_new') = 'true',
                           TIMESTAMP(JSON_VALUE(e, '$.edited_at')), JSON_VALUE(e, '$.edited_by'), TRUE
                    FROM UNNEST(JSON_QUERY_ARRAY(@rows)) AS e""",
                rows=json.dumps([{**r, "is_new": "true" if r.get("is_new") else "false"} for r in rows],
                                ensure_ascii=False))

    def deactivate_info_edits(self, change_id: str, by: str) -> None:
        self._q(f"""UPDATE {self.d}.info_edits SET active = FALSE, reverted_at = CURRENT_TIMESTAMP(), reverted_by = @by
                    WHERE change_id = @change_id""", change_id=change_id, by=by)

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
