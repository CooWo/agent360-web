"""역할·권한 — 기획안 8장.

역할마다 RolePolicy(무엇을 할 수 있는지)를 등록부에 둔다. 새 역할이나 새 기능 권한은
POLICIES.register(RolePolicy(...)) 또는 grants 에 권한 이름을 더하는 것으로 붙인다 (User 는 그대로).

기본 역할: admin(관리자) / manager(운영 매니저) / wfm(WFM·BA) / sv / viewer(조회)
- 열람 범위: SV 는 자기 팀만, 매니저·WFM·관리자는 계정 전체, 조회자는 지정된 팀만
- 민감 정보(코칭 메모·인센티브): 담당 SV 와 매니저만. 열람할 때마다 감사 로그
- 쓰기(코칭 기록·신호 처리): SV(자기 팀)와 매니저
- 기능 권한(grants): "admin", "capacity.edit" 처럼 이름으로 확인 → User.can("capacity.edit")
모든 데이터 조회는 Scope 를 받아 팀 필터를 데이터 계층에서 강제한다.
"""
from __future__ import annotations

from dataclasses import dataclass, field

# 민감 정보 열람 범위
SENSITIVE_NONE, SENSITIVE_OWN_TEAMS, SENSITIVE_ALL = "none", "own_teams", "all"


@dataclass(frozen=True)
class RolePolicy:
    role: str
    label: str
    all_teams: bool = False                 # 계정 전체 열람
    write: bool = False                     # 상담사 360 쓰기 (코칭·신호 처리)
    sensitive: str = SENSITIVE_NONE         # none | own_teams | all
    grants: frozenset[str] = frozenset()    # 기능 권한 이름

    def can_view_sensitive(self, team: str, my_teams: tuple[str, ...]) -> bool:
        if self.sensitive == SENSITIVE_ALL:
            return True
        return self.sensitive == SENSITIVE_OWN_TEAMS and team in my_teams


class PolicyRegistry:
    """역할 이름 → RolePolicy. 등록되지 않은 역할은 아무 권한 없는 정책으로 본다."""

    def __init__(self):
        self._p: dict[str, RolePolicy] = {}
        self.labels: dict[str, str] = {}    # 화면 표시용 (같은 dict 를 계속 갱신)

    def register(self, policy: RolePolicy) -> RolePolicy:
        self._p[policy.role] = policy
        self.labels[policy.role] = policy.label
        return policy

    def get(self, role: str) -> RolePolicy:
        return self._p.get(role) or RolePolicy(role=role, label=role)

    def roles(self) -> tuple[str, ...]:
        return tuple(self._p)


POLICIES = PolicyRegistry()
_CAP_ALL = {"capacity.view", "capacity.plan", "capacity.edit"}
_ROSTER_ALL = {"roster.view", "roster.edit", "info.view", "info.edit"}
_INFO_EDIT_ALL = {"info.edit.ops", "info.edit.wfm", "info.edit.ba"}
for _p in (
    RolePolicy("admin", "관리자", all_teams=True, grants=frozenset({"admin", "info.sync", "qa.upload", *_INFO_EDIT_ALL, *_CAP_ALL, *_ROSTER_ALL})),
    RolePolicy("manager", "매니저", all_teams=True, write=True, sensitive=SENSITIVE_ALL,
               grants=frozenset({"capacity.view", "capacity.plan", "info.sync", "info.edit.ops", "qa.upload",
                                 *_ROSTER_ALL})),
    RolePolicy("wfm", "WFM·BA", all_teams=True, grants=frozenset({"info.sync", "info.edit.wfm", "info.edit.ba", "qa.upload", *_CAP_ALL, *_ROSTER_ALL})),
    RolePolicy("sv", "SV", write=True, sensitive=SENSITIVE_OWN_TEAMS, grants=frozenset({"roster.view"})),
    RolePolicy("viewer", "조회", grants=frozenset({"capacity.view", "roster.view"})),
):
    POLICIES.register(_p)

ROLES = POLICIES.roles()
ROLE_LABEL = POLICIES.labels


@dataclass(frozen=True)
class User:
    email: str
    name: str
    role: str
    teams: tuple[str, ...] = field(default_factory=tuple)

    @property
    def policy(self) -> RolePolicy:
        return POLICIES.get(self.role)

    @property
    def role_label(self) -> str:
        return self.policy.label

    @property
    def scope(self) -> "Scope":
        if self.policy.all_teams:
            return Scope(all_teams=True)
        return Scope(all_teams=False, teams=tuple(self.teams))

    def has_role(self, *roles: str) -> bool:
        return self.role in roles

    def can(self, permission: str) -> bool:
        """기능 권한 이름으로 확인 (예: "admin", "capacity.edit")."""
        return permission in self.policy.grants

    @property
    def can_write(self) -> bool:
        """코칭 기록 저장, 신호 처리 상태 변경."""
        return self.policy.write

    def can_view_sensitive(self, agent_team: str) -> bool:
        """코칭 메모·인센티브: 매니저 또는 그 팀 담당 SV."""
        return self.policy.can_view_sensitive(agent_team, self.teams)


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
