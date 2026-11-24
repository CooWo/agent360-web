"""데이터 백엔드 선택: DATA_BACKEND=sample | bigquery"""
from __future__ import annotations

from functools import lru_cache

from app.core.config import get_settings


@lru_cache
def get_backend():
    s = get_settings()
    if s.data_backend == "bigquery":
        from app.core.data.bigquery import BigQueryBackend
        return BigQueryBackend(s.gcp_project, s.bq_location, s.common_dataset, s.module_dataset, s.cache_seconds)
    from app.core.data.sample import SampleBackend
    return SampleBackend(s.sample_dir)
