"""데이터 백엔드 선택: DATA_BACKEND=sample | bigquery

구현은 BACKENDS 등록부에 이름으로 등록한다. 새 원천(예: 다른 DB)은 register 만 하면 된다.
"""
from __future__ import annotations

from functools import lru_cache

from app.core.config import Settings, get_settings
from app.core.registry import Registry

BACKENDS: Registry = Registry("데이터 백엔드")


@BACKENDS.register("sample")
def _sample(s: Settings):
    from app.core.data.sample import SampleBackend
    return SampleBackend(s.sample_dir)


@BACKENDS.register("bigquery")
def _bigquery(s: Settings):
    from app.core.data.bigquery import BigQueryBackend
    return BigQueryBackend(s.gcp_project, s.bq_location, s.common_dataset, s.module_dataset, s.cache_seconds,
                           s.kpi_dataset, s.survey_table)


@lru_cache
def get_backend():
    s = get_settings()
    return BACKENDS.create(s.data_backend, s)
