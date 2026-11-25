"""Capacity 데이터 저장소 선택 (DATA_BACKEND=sample | bigquery). 읽기·쓰기만, 계산은 services."""
from __future__ import annotations

from functools import lru_cache

from app.core.config import get_settings


@lru_cache
def _make(kind: str, sample_dir: str, project: str, location: str, dataset: str, cache_seconds: int):
    if kind == "bigquery":
        from app.modules.capacity.data.bigquery import CapacityBigQuery
        return CapacityBigQuery(project, location, dataset, cache_seconds)
    from app.modules.capacity.data.sample import CapacitySample
    return CapacitySample(sample_dir)


def get_store():
    s = get_settings()
    return _make(s.data_backend, str(s.sample_dir), s.gcp_project, s.bq_location, s.capacity_dataset, s.cache_seconds)
