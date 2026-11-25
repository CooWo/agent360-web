"""팀 구성 저장소 — 인터페이스와 구현 선택 (DATA_BACKEND=sample | bigquery). 새 원천은 STORES 에 등록."""
from __future__ import annotations

from functools import lru_cache
from typing import Protocol

from app.core.config import get_settings
from app.core.registry import Registry


class AgentInfoSource(Protocol):
    """기본정보 (Standard INFO TABLE). 사번(emp_id) 키."""
    def agent_info(self) -> list[dict]: ...


class BoardStore(Protocol):
    """지금 보드와 버전. 적용할 때마다 보드 전체가 새 버전으로 쌓인다."""
    def board(self) -> list[dict]: ...
    def save_board(self, rows: list[dict], by: str) -> str: ...
    def versions(self, limit: int = 20) -> list[dict]: ...


class DraftStore(Protocol):
    """사용자별 작업 중 초안."""
    def draft(self, email: str) -> dict | None: ...
    def save_draft(self, email: str, rows: list[dict]) -> dict: ...
    def clear_draft(self, email: str) -> None: ...


class RosterStore(AgentInfoSource, BoardStore, DraftStore, Protocol):
    """팀 구성 화면이 쓰는 저장소 전체."""


STORES: Registry = Registry("팀 구성 저장소")


@STORES.register("sample")
def _sample(sample_dir: str, project: str, location: str, dataset: str):
    from app.modules.roster.data.sample import RosterSample
    return RosterSample(sample_dir)


@STORES.register("bigquery")
def _bigquery(sample_dir: str, project: str, location: str, dataset: str):
    from app.modules.roster.data.bigquery import RosterBigQuery
    return RosterBigQuery(project, location, dataset)


@lru_cache
def _make(kind: str, sample_dir: str, project: str, location: str, dataset: str):
    return STORES.create(kind, sample_dir, project, location, dataset)


def get_store() -> RosterStore:
    s = get_settings()
    return _make(s.data_backend, str(s.sample_dir), s.gcp_project, s.bq_location, s.roster_dataset)
