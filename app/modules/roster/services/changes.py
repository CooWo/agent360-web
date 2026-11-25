"""팀 구성 변경 처리기 — 보드 전체를 한 번에 바꾼다 (core/changes.py 의 ChangeHandler).

payload = {"rows": [보드 전체 행]}. 미리보기는 지금 보드와 비교, 적용하면 새 버전 저장 + 내 초안 삭제.
새 TL 이 생기면 on_new_tl(사용자, TL 목록) 을 부른다 (BA 알림 연결 지점).
"""
from __future__ import annotations

from collections.abc import Callable

from app.core.changes import ChangeHandler, ChangeSet
from app.core.errors import InvalidInput
from app.core.permissions import User
from app.core.registry import Registry
from app.modules.roster.data import RosterStore
from app.modules.roster.services.board import BoardRules, summarize


class BoardChange(ChangeHandler):
    kind = "roster.board"
    title = "팀 구성"
    permission = "roster.edit"

    def __init__(self, store: RosterStore, on_new_tl: Callable[[User, list[str]], None] | None = None):
        self.store = store
        self.on_new_tl = on_new_tl or (lambda user, tls: None)

    def rules(self) -> BoardRules:
        return BoardRules(self.store.agent_info())

    def prepare(self, payload: dict) -> tuple[list[dict], list[dict], BoardRules]:
        rows = payload.get("rows") if isinstance(payload, dict) else None
        if not isinstance(rows, list):
            raise InvalidInput({"rows": "보드 행이 없습니다."})
        rules = self.rules()
        new = rules.normalize(rows)
        if not new:
            raise InvalidInput({"rows": "보드가 비어 있습니다. 전체 삭제는 지원하지 않습니다."})
        chk = rules.check(new)
        if chk.errors:
            raise InvalidInput(chk.errors)
        return self.store.board(), new, rules

    def preview(self, user: User, payload: dict) -> tuple[str, list[dict]]:
        current, new, rules = self.prepare(payload)
        diff = rules.diff(current, new)
        return summarize(diff), diff

    def apply(self, user: User, change: ChangeSet) -> dict:
        current, new, _ = self.prepare(change.payload)
        self.store.save_board(new, user.email)
        self.store.clear_draft(user.email)
        new_tls = sorted({r["tl"] for r in new} - {r["tl"] for r in current})
        if new_tls:
            self.on_new_tl(user, new_tls)
        return {"rows": current}

    def revert(self, user: User, change: ChangeSet) -> None:
        self.store.save_board((change.undo or {})["rows"], user.email)


def handlers(store: RosterStore, on_new_tl=None) -> Registry[ChangeHandler]:
    reg: Registry[ChangeHandler] = Registry("팀 구성 변경")
    h = BoardChange(store, on_new_tl)
    reg.register(h.kind, h)
    return reg
