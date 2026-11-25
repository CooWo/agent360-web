"""CapacityBigQuery — 데이터셋 CAPACITY_DATASET (기본 `capacity`). 테이블 정의: sql/ddl/03_capacity.sql.
SQL 은 매개변수(@name)만 쓴다. 쓰기는 DML."""
from __future__ import annotations

import threading
import time
from datetime import date, datetime

ASSUMPTION_COLS = ("channel", "work_hours_week", "occupancy", "shrinkage", "nesting_productivity", "sl_target", "source")


class CapacityBigQuery:
    def __init__(self, project: str, location: str, dataset: str, cache_seconds: int = 60):
        from google.cloud import bigquery  # 지연 import: sample 모드에서는 패키지 없어도 됨

        self._bq = bigquery
        self.client = bigquery.Client(project=project or None)
        self.location = location
        self.d = f"`{self.client.project}.{dataset}`"
        self.ttl = cache_seconds
        self._cache: dict = {}
        self._lock = threading.Lock()

    def _param(self, k, v):
        typ = "FLOAT64" if isinstance(v, float) else ("INT64" if isinstance(v, int) else "STRING")
        return self._bq.ScalarQueryParameter(k, typ, v)

    def _run(self, sql: str, params: dict) -> list[dict]:
        qp = [self._param(k, v) for k, v in params.items()]
        job = self.client.query(sql, job_config=self._bq.QueryJobConfig(query_parameters=qp), location=self.location)
        return [{k: (v.isoformat() if isinstance(v, (date, datetime)) else v) for k, v in dict(r).items()}
                for r in job.result()]

    def _q(self, sql: str, **params) -> list[dict]:
        key = (sql, tuple(sorted(params.items())))
        now = time.time()
        with self._lock:
            hit = self._cache.get(key)
            if hit and now - hit[0] < self.ttl:
                return hit[1]
        rows = self._run(sql, params)
        with self._lock:
            self._cache[key] = (now, rows)
        return rows

    def forecast(self, since: str, until: str) -> list[dict]:
        return self._q(f"SELECT week, channel, volume, aht_sec, kind FROM {self.d}.forecast_weekly "
                       "WHERE week BETWEEN DATE(@since) AND DATE(@until) ORDER BY week, channel", since=since, until=until)

    def headcount(self, since: str, until: str) -> list[dict]:
        return self._q(f"SELECT week, channel, hc_production, hc_nesting FROM {self.d}.headcount_weekly "
                       "WHERE week BETWEEN DATE(@since) AND DATE(@until) ORDER BY week, channel", since=since, until=until)

    def assumptions(self) -> list[dict]:
        return self._q(f"SELECT {', '.join(ASSUMPTION_COLS)} FROM {self.d}.assumptions ORDER BY channel")

    def save_assumptions(self, rows: list[dict]) -> None:
        for r in rows:
            p = {c: r.get(c) for c in ASSUMPTION_COLS}
            for c in ("work_hours_week", "occupancy", "shrinkage", "nesting_productivity"):
                p[c] = float(p[c])
            self._run(f"""MERGE {self.d}.assumptions t USING (SELECT @channel AS channel) s ON t.channel = s.channel
                          WHEN MATCHED THEN UPDATE SET work_hours_week = @work_hours_week, occupancy = @occupancy,
                            shrinkage = @shrinkage, nesting_productivity = @nesting_productivity,
                            sl_target = @sl_target, source = @source
                          WHEN NOT MATCHED THEN INSERT ({', '.join(ASSUMPTION_COLS)})
                            VALUES (@channel, @work_hours_week, @occupancy, @shrinkage, @nesting_productivity,
                                    @sl_target, @source)""", p)
        with self._lock:
            self._cache.clear()
