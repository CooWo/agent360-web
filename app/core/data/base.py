"""데이터 계층 인터페이스 — 쓰임새별로 작게 나눈다 (인터페이스 분리·의존성 역전).

서비스는 자기가 쓰는 인터페이스만 타입으로 받는다. 예: 코칭 서비스는 AgentDirectory + CoachingStore.
DataBackend 는 이것을 모두 합친 것이고, 구현은 두 개:
- SampleBackend   : sample_data/*.json (로컬 개발·테스트)
- BigQueryBackend : 공통 데이터셋 + 모듈 데이터셋 (운영)
새 구현은 data/__init__.py 의 BACKENDS 에 등록한다 (기존 코드 수정 없음).
새 조회가 필요하면 ① 알맞은 인터페이스에 메서드 추가(또는 새 인터페이스) ② 두 구현 모두 작성 ③ 테스트.
권한: 팀이 있는 데이터는 반드시 scope 를 받아 백엔드 안에서 거른다.
반환값은 dict / list[dict] (날짜는 'YYYY-MM-DD' 문자열).
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable

from app.core.permissions import Scope


class AsOfSource(Protocol):
    def as_of(self) -> str: ...


class UserDirectory(Protocol):
    def get_user(self, email: str) -> dict | None: ...
    def list_users(self) -> list[dict]: ...


class TeamDirectory(Protocol):
    def list_teams(self) -> list[dict]: ...


class AgentDirectory(Protocol):
    def list_agents(self, scope: Scope, q: str | None = None, team: str | None = None) -> list[dict]: ...
    def get_agent(self, scope: Scope, agent_id: str) -> dict | None: ...


class AgentFacts(Protocol):
    """상담사별 사실 데이터 (get_agent 로 권한 확인 후 호출)."""
    def kpi_daily(self, agent_id: str, since: str) -> list[dict]: ...
    def kpi_daily_many(self, agent_ids: list[str], since: str) -> dict[str, list[dict]]: ...   # 목록 화면 (한 번에)
    def attendance(self, agent_id: str, since: str) -> list[dict]: ...
    def attendance_many(self, agent_ids: list[str], since: str) -> list[dict]: ...   # 대시보드 (한 번에)
    def qa(self, agent_id: str, since: str) -> list[dict]: ...
    def training(self, agent_id: str) -> list[dict]: ...
    def incentive(self, agent_id: str) -> list[dict]: ...


class CoachingStore(Protocol):
    def coaching(self, scope: Scope, agent_id: str | None = None) -> list[dict]: ...
    def add_coaching(self, record: dict) -> dict: ...
    def complete_coaching(self, coaching_id: str, by: str) -> dict | None: ...
    def issue_types(self) -> list[str]: ...


class SignalStore(Protocol):
    def signals(self, scope: Scope, as_of: str | None = None) -> list[dict]: ...
    def set_signal_status(self, signal_id: str, status: str, by: str) -> dict | None: ...
    def signal_rules(self) -> list[dict]: ...


@runtime_checkable
class AuditStore(Protocol):
    def write_audit(self, event: dict) -> None: ...


class QaCoachingStore(Protocol):
    """코칭 대시보드 내보내기(zip)에서 올린 상담사별 QA·코칭 — 가장 최근에 저장한 묶음(change_id)만 화면에 쓴다."""
    def qa_coaching(self) -> list[dict]: ...
    def add_qa_coaching(self, rows: list[dict]) -> None: ...
    def deactivate_qa_coaching(self, change_id: str) -> None: ...


class DataBackend(AsOfSource, UserDirectory, TeamDirectory, AgentDirectory, AgentFacts,
                  CoachingStore, SignalStore, AuditStore, QaCoachingStore, Protocol):
    """모든 인터페이스를 합친 백엔드 (상담사 360 기본 데이터)."""
