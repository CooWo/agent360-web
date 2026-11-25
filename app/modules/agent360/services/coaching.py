"""코칭 기록 — 기획안 6-3.

1단계: SV 가 직접 칸을 채워 저장 (자유 입력 원문 raw_note 도 같이 저장).
6단계: Gemini 가 raw_note 를 같은 스키마(상담사·이슈 유형·요약·합의 행동·후속 확인일)로 채워 주고,
       SV 는 미리보기를 고쳐서 저장한다. → validate() 는 그대로 재사용.
"""
from __future__ import annotations

from datetime import date, timedelta

from app.core.audit import Auditor
from app.core.data.base import AgentDirectory, CoachingStore
from app.core.errors import InvalidInput, NotFound, PermissionDenied
from app.core.permissions import User

FIELDS = ("agent_id", "date", "issue_type", "summary", "agreed_action", "follow_up_date", "raw_note",
          "area_detail", "desired_outcome", "case_number", "root_cause", "agent_comment", "agent_ack")
# 코칭 폼 (기존 Coaching Form 양식):
#   Areas Where Coaching is needed → issue_type(카테고리, 우선순위 P0~P3) + area_detail
#   Desired Outcomes of Coaching   → desired_outcome
#   TL's Comments: Case Number → case_number · Opportunities(개선점) → summary · Root cause(근본 원인) → root_cause
#                  Actions moving forward(개선 방향 및 타겟 설정) → agreed_action
#   Agent's Comments → agent_comment · Agent's Signature → agent_ack · TL's Signature → sv_email (저장한 사람)
CATEGORIES: dict[str, list[str]] = {
    "P0": ["ZTP", "Compliance"],
    "P1": ["NPS(CSQ)"],
    "P2": ["Soft Skill", "Investigation", "Loss", "Reopen", "Pending SOP", "SH task(status etc)"],
    "P3": ["Mis-escalation", "Handoff", "First touch delays", "KSG", "Others", "Nova Guide"],
}
TEXT_LIMITS = {"summary": ("개선점", 1000, True), "agreed_action": ("개선 방향 및 타겟", 1000, True),
               "area_detail": ("코칭 필요 영역 (세부)", 300, False), "desired_outcome": ("코칭 목표", 1000, False),
               "root_cause": ("근본 원인", 1000, False), "agent_comment": ("상담사 코멘트", 1000, False),
               "case_number": ("케이스 번호", 60, False)}


def priority_of(category: str, categories: dict[str, list[str]] | None = None) -> str | None:
    return next((p for p, cats in (categories or CATEGORIES).items() if category in cats), None)


class CoachingService:
    """코칭 기록 규칙. 필요한 데이터 인터페이스(상담사·코칭)와 감사 기록기를 주입받는다."""

    def __init__(self, agents: AgentDirectory, store: CoachingStore, auditor: Auditor,
                 categories: dict[str, list[str]] | None = None):
        self.agents, self.store, self.auditor = agents, store, auditor
        self.categories = categories or CATEGORIES

    @classmethod
    def of(cls, backend, categories: dict[str, list[str]] | None = None) -> "CoachingService":
        return cls(backend, backend, Auditor.for_store(backend), categories)

    def validate(self, user: User, form: dict) -> dict:
        """입력값 검사 + 정리. 오류는 칸별 메시지로 InvalidInput."""
        if not user.can_write:
            raise PermissionDenied("코칭 기록은 SV·매니저만 저장할 수 있습니다.")
        f = {k: (str(form.get(k) or "")).strip() for k in FIELDS}
        f["agent_ack"] = f["agent_ack"].lower() in ("1", "true", "on", "yes")
        err: dict[str, str] = {}
        agent = self.agents.get_agent(user.scope, f["agent_id"]) if f["agent_id"] else None
        if not agent:
            err["agent_id"] = "상담사를 선택해 주세요 (담당 팀만 가능)."
        elif not user.can_view_sensitive(agent["team"]):
            err["agent_id"] = "담당 팀 상담사만 기록할 수 있습니다."
        f["priority"] = priority_of(f["issue_type"], self.categories)
        if not f["priority"]:
            err["issue_type"] = "코칭 필요 영역(카테고리)을 목록에서 선택해 주세요."
        for k, (label, limit, required) in TEXT_LIMITS.items():
            if required and not f[k]:
                err[k] = f"{label}을(를) 입력해 주세요."
            elif len(f[k]) > limit:
                err[k] = f"{label}은(는) {limit:,}자 이내로 입력해 주세요."
        try:
            d = date.fromisoformat(f["date"])
        except ValueError:
            err["date"] = "코칭 일자를 입력해 주세요."
            d = None
        try:
            fu = date.fromisoformat(f["follow_up_date"])
            if d and fu < d:
                err["follow_up_date"] = "후속 확인일은 코칭 일자 이후여야 합니다."
        except ValueError:
            err["follow_up_date"] = "후속 확인일을 입력해 주세요."
        if len(f["raw_note"]) > 4000:
            err["raw_note"] = "원문 메모는 4,000자 이내로 입력해 주세요."
        if err:
            raise InvalidInput(err)
        return f

    def create(self, user: User, form: dict) -> dict:
        f = self.validate(user, form)
        rec = self.store.add_coaching({**f, "sv_email": user.email})
        self.auditor.record(user, "coaching_create", "coaching", rec["coaching_id"],
                            {"agent_id": rec["agent_id"], "issue_type": rec["issue_type"], "priority": rec.get("priority"),
                             "follow_up_date": rec["follow_up_date"]})
        return rec

    def complete(self, user: User, coaching_id: str) -> dict:
        if not user.can_write:
            raise PermissionDenied("후속 완료 처리는 SV·매니저만 할 수 있습니다.")
        rows = [c for c in self.store.coaching(user.scope) if c["coaching_id"] == coaching_id]
        if not rows or not user.can_view_sensitive(rows[0]["team"]):
            raise NotFound("코칭 기록을 찾을 수 없거나 권한 밖입니다.")
        rec = self.store.complete_coaching(coaching_id, user.email)
        self.auditor.record(user, "coaching_complete", "coaching", coaching_id, {"agent_id": rows[0]["agent_id"]})
        return rec

    def followups(self, user: User, as_of: str, within_days: int) -> dict:
        """후속 확인: 지난 것(미완료)과 곧 다가오는 것."""
        t = date.fromisoformat(as_of)
        rows = [c for c in self.store.coaching(user.scope) if not c["done"] and user.can_view_sensitive(c["team"])]
        overdue = [c for c in rows if date.fromisoformat(c["follow_up_date"]) < t]
        soon = [c for c in rows if t <= date.fromisoformat(c["follow_up_date"]) <= t + timedelta(days=within_days)]
        key = lambda c: c["follow_up_date"]  # noqa: E731
        return {"overdue": sorted(overdue, key=key), "soon": sorted(soon, key=key)}


# ── 예전 호출 방식 (views·api·tests) ─────────────────
def validate(backend, user: User, form: dict, categories: dict | None = None) -> dict:
    return CoachingService.of(backend, categories).validate(user, form)


def create(backend, user: User, form: dict, categories: dict | None = None) -> dict:
    return CoachingService.of(backend, categories).create(user, form)


def complete(backend, user: User, coaching_id: str) -> dict:
    return CoachingService.of(backend).complete(user, coaching_id)


def followups(backend, user: User, as_of: str, within_days: int) -> dict:
    return CoachingService.of(backend).followups(user, as_of, within_days)
