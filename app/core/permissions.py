"""역할·권한 — 기획안 8장.

역할: admin(관리자) / manager(운영 매니저) / wfm(WFM·BA) / sv / viewer(조회)
- wfm 은 Capacity Web 담당자 (가정 확정·데이터 입력). 상담사 360 에서는 계정 전체 조회만
- 열람 범위: SV 는 자기 팀만, 매니저·관리자는 계정 전체, 조회자는 지정된 팀만
- 민감 정보(코칭 메모·인센티브): 담당 SV 와 매니저만. 열람할 때마다 감사 로그
- 쓰기(코칭 기록·신호 처리): SV(자기 팀)와 매니저
모든 데이터 조회는 Scope 를 받아 팀 필터를 데이터 계층에서 강제한다.
"""
from __future__ import annotations

from dataclasses import dataclass, field

ROLES = ("admin", "manager", "wfm", "sv", "viewer")
ROLE_LABEL = {"admin": "관리자", "manager": "매니저", "wfm": "WFM·BA", "sv": "SV", "viewer": "조회"}


@dataclass(frozen=True)
class User:
    email: str
    name: str
    role: str
    teams: tuple[str, ...] = field(default_factory=tuple)

    @property
    def role_label(self) -> str:
        return ROLE_LABEL.get(self.role, self.role)

    @property
    def scope(self) -> "Scope":
        if self.role in ("admin", "manager", "wfm"):
            return Scope(all_teams=True)
        return Scope(all_teams=False, teams=tuple(self.teams))

    def has_role(self, *roles: str) -> bool:
        return self.role in roles

    @property
    def can_write(self) -> bool:
        """코칭 기록 저장, 신호 처리 상태 변경."""
        return self.role in ("manager", "sv")

    def can_view_sensitive(self, agent_team: str) -> bool:
        """코칭 메모·인센티브: 매니저 또는 그 팀 담당 SV."""
        if self.role == "manager":
            return True
        return self.role == "sv" and agent_team in self.teams


@dataclass(frozen=True)
class Scope:
    """조회 범위. all_teams=True 면 계정 전체, 아니면 teams 에 든 팀만."""
    all_teams: bool = False
    teams: tuple[str, ...] = ()

    def allows(self, team: str | None) -> bool:
        return self.all_teams or (team is not None and team in self.teams)

    def filter(self, rows: list[dict], key: str = "team") -> list[dict]:
        if self.all_teams:
            return list(rows)
        return [r for r in rows if r.get(key) in self.teams]
