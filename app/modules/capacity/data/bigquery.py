"""CapacityBigQuery — 데이터셋 CAPACITY_DATASET (기본 `capacity`). 테이블 정의: sql/ddl/03_capacity.sql.
SQL 은 매개변수(@name)만 쓴다."""
from __future__ import annotations

import threading
import time
from datetime import date, datetime


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

    def _q(self, sql: str, **params) -> list[dict]:
        key = (sql, tuple(sorted(params.items())))
        now = time.time()
        with self._lock:
            hit = self._cache.get(key)
            if hit and now - hit[0] < self.ttl:
                return hit[1]
        qp = [self._bq.ScalarQueryParameter(k, "DATE", v) for k, v in params.items()]
        job = self.client.query(sql, job_config=self._bq.QueryJobConfig(query_parameters=qp), location=self.location)
        rows = [{k: (v.isoformat() if isinstance(v, (date, datetime)) else v) for k, v in dict(r).items()}
                for r in job.result()]
        with self._lock:
            self._cache[key] = (now, rows)
        return rows

    def forecast(self, since: str, until: str) -> list[dict]:
        return self._q(f"SELECT week, channel, volume, aht_sec, kind FROM {self.d}.forecast_weekly "
                       "WHERE week BETWEEN @since AND @until ORDER BY week, channel", since=since, until=until)

    def headcount(self, since: str, until: str) -> list[dict]:
        return self._q(f"SELECT week, channel, hc_production, hc_nesting FROM {self.d}.headcount_weekly "
                       "WHERE week BETWEEN @since AND @until ORDER BY week, channel", since=since, until=until)

    def assumptions(self) -> list[dict]:
        return self._q("SELECT channel, work_hours_week, occupancy, shrinkage, nesting_productivity, sl_target, source "
                       f"FROM {self.d}.assumptions ORDER BY channel")
