"""RosterBigQuery — 데이터셋 ROSTER_DATASET (기본 `roster`). 표 정의: sql/ddl/04_roster.sql.
보드는 버전마다 JSON 한 줄(board_versions), 초안은 사용자별 한 줄(board_drafts). SQL 은 @매개변수만."""
from __future__ import annotations

import json
import uuid
from datetime import date, datetime, timezone

from app.modules.roster.services.info import FIELDS as INFO_COLS


class RosterBigQuery:
    def __init__(self, project: str, location: str, dataset: str, common: str = "common"):
        from google.cloud import bigquery  # 지연 import

        self._bq = bigquery
        self.client = bigquery.Client(project=project or None)
        self.location = location
        self.d = f"`{self.client.project}.{dataset}`"
        self.att = f"`{self.client.project}.{common}.fact_attendance`"

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
        return self._q(f"""SELECT tl_name, sort_order, row_order, shift, emp_id, name, e_name, display_name, load_id,
                                  CAST(loaded_at AS STRING) loaded_at, loaded_by, source
                           FROM {self.d}.team_roster ORDER BY sort_order, row_order, emp_id""")

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

    # ── 근태 (Schedule KR) — common.fact_attendance 에 바뀐 칸만 MERGE, 기록은 attendance_loads ──
    ATT_CHUNK = 3000

    def attendance_rows(self, since: str, until: str) -> list[dict]:
        return self._q(f"""SELECT agent_id, CAST(date AS STRING) date, status, IFNULL(detail, '') detail,
                                  IFNULL(bg, '') bg
                           FROM {self.att} WHERE date BETWEEN DATE(@since) AND DATE(@until)
                             AND source = 'schedule_kr'""", since=since, until=until)

    def apply_attendance(self, upserts: list[dict], deletes: list[tuple[str, str]], load: dict) -> None:
        items = [{**u, "del": False} for u in upserts] + [{"agent_id": a, "date": d, "del": True} for a, d in deletes]
        for i in range(0, len(items), self.ATT_CHUNK):
            self._q(f"""MERGE {self.att} t
                USING (SELECT JSON_VALUE(e, '$.agent_id') agent_id, DATE(JSON_VALUE(e, '$.date')) date,
                              JSON_VALUE(e, '$.status') status, JSON_VALUE(e, '$.detail') detail,
                              JSON_VALUE(e, '$.bg') bg, JSON_VALUE(e, '$.del') = 'true' is_del
                       FROM UNNEST(JSON_QUERY_ARRAY(@rows)) e) s
                ON t.agent_id = s.agent_id AND t.date = s.date
                WHEN MATCHED AND s.is_del THEN DELETE
                WHEN MATCHED THEN UPDATE SET status = s.status, detail = s.detail, bg = s.bg,
                     source = 'schedule_kr', load_id = @load_id, loaded_at = CURRENT_TIMESTAMP()
                WHEN NOT MATCHED AND NOT s.is_del THEN
                     INSERT (agent_id, date, status, detail, bg, source, load_id, loaded_at)
                     VALUES (s.agent_id, s.date, s.status, s.detail, s.bg, 'schedule_kr', @load_id, CURRENT_TIMESTAMP())""",
                    rows=json.dumps(items[i:i + self.ATT_CHUNK], ensure_ascii=False), load_id=load["load_id"])
        self._q(f"""INSERT INTO {self.d}.attendance_loads (load_id, loaded_at, loaded_by, source, since, until, agents,
                        cells, upserts, deletes, by_status, unknown)
                    VALUES (@load_id, CURRENT_TIMESTAMP(), @loaded_by, @source, DATE(@since), DATE(@until), @agents,
                            @cells, @upserts, @deletes, @by_status, @unknown)""",
                load_id=load["load_id"], loaded_by=load["loaded_by"], source=load["source"], since=load["since"],
                until=load["until"], agents=load["agents"], cells=load["cells"], upserts=load["upserts"],
                deletes=load["deletes"], by_status=json.dumps(load["by_status"], ensure_ascii=False),
                unknown=json.dumps(load["unknown"], ensure_ascii=False))

    def attendance_loads(self, limit: int = 10) -> list[dict]:
        rows = self._q(f"""SELECT load_id, CAST(loaded_at AS STRING) loaded_at, loaded_by, source,
                                  CAST(since AS STRING) since, CAST(until AS STRING) until, agents, cells, upserts,
                                  deletes, by_status, unknown
                           FROM {self.d}.attendance_loads ORDER BY loaded_at DESC LIMIT @limit""", limit=limit)
        for r in rows:
            r["by_status"] = json.loads(r["by_status"] or "{}")
            r["unknown"] = json.loads(r["unknown"] or "[]")
        return rows
