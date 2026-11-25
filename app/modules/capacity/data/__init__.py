"""Capacity 데이터 저장소 — 인터페이스와 구현 선택 (DATA_BACKEND=sample | bigquery).

읽기·쓰기만 한다. 계산은 services. 새 원천은 STORES 에 등록한다.
"""
from __future__ import annotations

from functools import lru_cache
from typing import Protocol

from app.core.config import get_settings
from app.core.registry import Registry


class ForecastSource(Protocol):
    def forecast(self, since: str, until: str) -> list[dict]: ...


class HeadcountSource(Protocol):
    def headcount(self, since: str, until: str) -> list[dict]: ...


class AssumptionStore(Protocol):
    def assumptions(self) -> list[dict]: ...
    def save_assumptions(self, rows: list[dict]) -> None: ...


class CapacityStore(ForecastSource, HeadcountSource, AssumptionStore, Protocol):
    """Capacity 화면이 쓰는 저장소 전체."""


STORES: Registry = Registry("Capacity 저장소")


@STORES.register("sample")
def _sample(sample_dir: str, project: str, location: str, dataset: str, cache_seconds: int):
    from app.modules.capacity.data.sample import CapacitySample
    return CapacitySample(sample_dir)


@STORES.register("bigquery")
def _bigquery(sample_dir: str, project: str, location: str, dataset: str, cache_seconds: int):
    from app.modules.capacity.data.bigquery import CapacityBigQuery
    return CapacityBigQuery(project, location, dataset, cache_seconds)


@lru_cache
def _make(kind: str, sample_dir: str, project: str, location: str, dataset: str, cache_seconds: int):
    return STORES.create(kind, sample_dir, project, location, dataset, cache_seconds)


def get_store() -> CapacityStore:
    s = get_settings()
    return _make(s.data_backend, str(s.sample_dir), s.gcp_project, s.bq_location, s.capacity_dataset, s.cache_seconds)
