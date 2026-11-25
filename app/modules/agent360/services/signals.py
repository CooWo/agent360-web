"""신호 — 오늘 볼 상담사 순서와 처리 상태 (기획안 6-1).

신호 자체는 새벽 배치가 SQL 규칙으로 만든다(5단계). 여기서는
- 상담사별 점수 합산(상 3, 중 2, 하 1)과 정렬
- SV 의 처리 상태 기록(확인 / 코칭 예정 / 해당 없음) → 규칙 정확도 검수에 사용
'해당 없음'으로 처리한 신호는 점수에서 뺀다.
"""
from __future__ import annotations

from collections import defaultdict

from app.core.audit import Auditor
from app.core.data.base import AgentDirectory, SignalStore
from app.core.errors import InvalidInput, NotFound, PermissionDenied
from app.core.permissions import User

STATUSES = ["미확인", "확인", "코칭 예정", "해당 없음"]
SEVERITY_ORDER = {"상": 0, "중": 1, "하": 2}


class SignalService:
    def __init__(self, agents: AgentDirectory, store: SignalStore, auditor: Auditor):
        self.agents, self.store, self.auditor = agents, store, auditor

    @classmethod
    def of(cls, backend) -> "SignalService":
        return cls(backend, backend, Auditor.for_store(backend))

    def by_agent(self, user: User) -> list[dict]:
        """권한 범위 안의 오늘 신호를 상담사별로 묶어 점수 내림차순."""
        agents = {a["agent_id"]: a for a in self.agents.list_agents(user.scope)}
        grouped: dict[str, list] = defaultdict(list)
        for s in self.store.signals(user.scope):
            if s["agent_id"] in agents:
                grouped[s["agent_id"]].append(s)
        out = []
        for aid, sigs in grouped.items():
            sigs.sort(key=lambda s: (SEVERITY_ORDER.get(s["severity"], 9), s["label"]))
            score = sum(s["score"] for s in sigs if s["status"] != "해당 없음")
            out.append({"agent": agents[aid], "signals": sigs, "score": score,
                        "open": sum(1 for s in sigs if s["status"] == "미확인")})
        out.sort(key=lambda x: (-x["score"], -x["open"], x["agent"]["name"]))
        return out

    def set_status(self, user: User, signal_id: str, status: str) -> dict:
        if not user.can_write:
            raise PermissionDenied("신호 처리는 SV·매니저만 할 수 있습니다.")
        if status not in STATUSES:
            raise InvalidInput({"status": f"다음 중 하나여야 합니다: {', '.join(STATUSES)}"})
        mine = {s["signal_id"]: s for s in self.store.signals(user.scope)}
        if signal_id not in mine:
            raise NotFound("신호를 찾을 수 없거나 권한 밖입니다.")
        row = self.store.set_signal_status(signal_id, status, user.email)
        self.auditor.record(user, "signal_status", "signal", signal_id,
                            {"from": mine[signal_id]["status"], "to": status, "agent_id": mine[signal_id]["agent_id"]})
        return row


# ── 예전 호출 방식 (views·api·tests) ─────────────────
def by_agent(backend, user: User) -> list[dict]:
    return SignalService.of(backend).by_agent(user)


def set_status(backend, user: User, signal_id: str, status: str) -> dict:
    return SignalService.of(backend).set_status(user, signal_id, status)
