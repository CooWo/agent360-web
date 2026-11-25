"""데이터 변경 공통 틀 — 미리보기 → 승인(저장) → 되돌리기 (기획안 설계 원칙 2).

웹에서 직접 수정, 파일 업로드, AI 가 제안한 변경 모두 같은 흐름을 탄다.
새 종류의 변경은 ChangeHandler 를 하나 만들어 등록만 하면 된다 (ChangeService 는 그대로).

    class AssumptionsChange(ChangeHandler):
        kind = "capacity.assumptions"; permission = "capacity.edit"
        def preview(self, user, payload): ...   # 검증 + 바뀌는 칸 목록
        def apply(self, user, change): ...      # 저장, 되돌리기용 데이터 반환
        def revert(self, user, change): ...     # 되돌리기

규칙
- 미리보기는 저장하지 않는다. 승인할 때 미리보기를 다시 계산해서, 그 사이 데이터가 바뀌었으면 막는다.
- 되돌리기는 같은 종류에서 가장 최근에 적용한 변경만 (뒤 변경을 덮어쓰지 않게).
- 모든 단계는 감사 로그에 남는다.
"""
from __future__ import annotations

import uuid
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Protocol

from app.core.audit import Auditor
from app.core.errors import InvalidInput, NotFound, PermissionDenied
from app.core.permissions import User
from app.core.registry import Registry

PREVIEW, APPLIED, REVERTED, DISCARDED = "preview", "applied", "reverted", "discarded"
STATUS_LABEL = {PREVIEW: "미리보기", APPLIED: "적용됨", REVERTED: "되돌림", DISCARDED: "취소"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")  # 같은 초 안의 순서도 구분


@dataclass
class ChangeSet:
    kind: str
    actor: str
    summary: str
    payload: dict
    diff: list[dict]                       # [{"key", "field", "before", "after"}]
    change_id: str = field(default_factory=lambda: "CH" + uuid.uuid4().hex[:12])
    status: str = PREVIEW
    created_at: str = field(default_factory=_now)
    undo: dict | None = None
    applied_at: str | None = None
    applied_by: str | None = None
    reverted_at: str | None = None
    reverted_by: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "ChangeSet":
        return cls(**{k: d.get(k) for k in cls.__dataclass_fields__ if k in d})

    @property
    def status_label(self) -> str:
        return STATUS_LABEL.get(self.status, self.status)


class ChangeHandler(ABC):
    """변경 한 종류. kind·title·permission 을 정하고 세 단계를 구현한다."""
    kind: str = ""
    title: str = ""
    permission: str = ""

    def check(self, user: User) -> None:
        if not user.can(self.permission):
            raise PermissionDenied(f"'{self.title}' 변경 권한이 없습니다.")

    @abstractmethod
    def preview(self, user: User, payload: dict) -> tuple[str, list[dict]]:
        """검증하고 (요약, 바뀌는 칸 목록)을 돌려준다. 잘못된 값은 InvalidInput."""

    @abstractmethod
    def apply(self, user: User, change: ChangeSet) -> dict:
        """저장하고 되돌리기에 필요한 데이터를 돌려준다."""

    @abstractmethod
    def revert(self, user: User, change: ChangeSet) -> None:
        """apply 가 돌려준 change.undo 로 원래대로."""


class ChangeLog(Protocol):
    """변경 묶음 저장소 (sample: runtime JSON, bigquery: change_log 표)."""
    def save(self, change: dict) -> None: ...
    def get(self, change_id: str) -> dict | None: ...
    def list(self, kind: str | None = None, limit: int = 50) -> list[dict]: ...


class ChangeService:
    def __init__(self, handlers: Registry[ChangeHandler], log: ChangeLog, auditor: Auditor):
        self.handlers = handlers
        self.log = log
        self.auditor = auditor

    def _handler(self, kind: str) -> ChangeHandler:
        if kind not in self.handlers:
            raise NotFound(f"알 수 없는 변경 종류입니다: {kind}")
        return self.handlers.get(kind)

    def _load(self, change_id: str) -> tuple[ChangeSet, ChangeHandler]:
        row = self.log.get(change_id)
        if not row:
            raise NotFound("변경 기록을 찾을 수 없습니다.")
        ch = ChangeSet.from_dict(row)
        return ch, self._handler(ch.kind)

    def _audit(self, user: User, action: str, ch: ChangeSet, **extra) -> None:
        self.auditor.record(user, action, "change", ch.change_id, {"kind": ch.kind, "summary": ch.summary, **extra})

    def preview(self, user: User, kind: str, payload: dict) -> ChangeSet:
        h = self._handler(kind)
        h.check(user)
        summary, diff = h.preview(user, payload)
        if not diff:
            raise InvalidInput({"payload": "바뀌는 값이 없습니다."})
        ch = ChangeSet(kind=kind, actor=user.email, summary=summary, payload=payload, diff=diff)
        self.log.save(ch.to_dict())
        self._audit(user, "change_preview", ch, rows=len(diff))
        return ch

    def approve(self, user: User, change_id: str) -> ChangeSet:
        ch, h = self._load(change_id)
        h.check(user)
        if ch.status != PREVIEW:
            raise InvalidInput({"status": f"미리보기 상태만 적용할 수 있습니다 (지금: {ch.status_label})."})
        _, fresh = h.preview(user, ch.payload)
        if fresh != ch.diff:
            raise InvalidInput({"diff": "미리보기 이후 데이터가 바뀌었습니다. 다시 미리보기 해 주세요."})
        ch.undo = h.apply(user, ch)
        ch.status, ch.applied_at, ch.applied_by = APPLIED, _now(), user.email
        self.log.save(ch.to_dict())
        self._audit(user, "change_apply", ch, rows=len(ch.diff))
        return ch

    def undo(self, user: User, change_id: str) -> ChangeSet:
        ch, h = self._load(change_id)
        h.check(user)
        if ch.status != APPLIED:
            raise InvalidInput({"status": f"적용된 변경만 되돌릴 수 있습니다 (지금: {ch.status_label})."})
        applied = [r for r in self.log.list(ch.kind, limit=200) if r["status"] == APPLIED]
        latest = max(applied, key=lambda r: r.get("applied_at") or "", default=None)
        if latest and latest["change_id"] != ch.change_id:
            raise InvalidInput({"change_id": "더 최근에 적용한 변경이 있습니다. 최근 것부터 되돌려 주세요."})
        h.revert(user, ch)
        ch.status, ch.reverted_at, ch.reverted_by = REVERTED, _now(), user.email
        self.log.save(ch.to_dict())
        self._audit(user, "change_revert", ch)
        return ch

    def discard(self, user: User, change_id: str) -> ChangeSet:
        ch, h = self._load(change_id)
        h.check(user)
        if ch.status != PREVIEW:
            raise InvalidInput({"status": "미리보기 상태만 취소할 수 있습니다."})
        ch.status = DISCARDED
        self.log.save(ch.to_dict())
        self._audit(user, "change_discard", ch)
        return ch

    def history(self, user: User, kind: str | None = None, limit: int = 50) -> list[ChangeSet]:
        rows = [ChangeSet.from_dict(r) for r in self.log.list(kind, limit)]
        return [c for c in rows if c.kind in self.handlers and user.can(self.handlers.get(c.kind).permission)]
