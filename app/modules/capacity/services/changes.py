"""Capacity 데이터 변경 처리기 — core/changes.py 의 ChangeHandler 구현.

새 변경 종류(물량 업로드, 인원 수정 …)는 이 파일에 처리기를 만들고 HANDLERS 에 등록한다.
"""
from __future__ import annotations

from app.core.changes import ChangeHandler, ChangeSet
from app.core.errors import InvalidInput
from app.core.permissions import User
from app.core.registry import Registry
from app.modules.capacity.data import AssumptionStore
from app.modules.capacity.services.fte import AssumptionRules


class AssumptionsChange(ChangeHandler):
    """채널별 계산 가정 수정. payload = {"rows": [{"channel": "Voice", "shrinkage": 0.32, ...}]}
    업로드 CSV 행도 그대로 넣을 수 있다 (숫자 칸은 문자열이어도 됨)."""
    kind = "capacity.assumptions"
    title = "계산 가정"
    permission = "capacity.edit"

    def __init__(self, store: AssumptionStore):
        self.store = store

    def _merged(self, payload: dict) -> tuple[list[dict], list[dict]]:
        current = self.store.assumptions()
        by_ch = {a["channel"]: dict(a) for a in current}
        rows = payload.get("rows") if isinstance(payload, dict) else None
        if not isinstance(rows, list) or not rows:
            raise InvalidInput({"rows": "바꿀 행이 없습니다."})
        errs: dict[str, str] = {}
        for i, r in enumerate(rows, 1):
            ch = str(r.get("channel") or "").strip()
            if ch not in by_ch:
                errs[f"rows.{i}.channel"] = f"없는 채널입니다: {ch or '(빈 값)'} (가능: {', '.join(by_ch)})"
                continue
            for k in AssumptionRules.NUMERIC:
                if k in r and str(r[k]).strip() != "":
                    try:
                        by_ch[ch][k] = float(r[k])
                    except (TypeError, ValueError):
                        errs[f"rows.{i}.{k}"] = f"{AssumptionRules.LABEL[k]}은(는) 숫자여야 합니다."
            for k, v in AssumptionRules.errors(by_ch[ch]).items():
                errs[f"rows.{i}.{k}"] = v
        if errs:
            raise InvalidInput(errs)
        return current, list(by_ch.values())

    def preview(self, user: User, payload: dict) -> tuple[str, list[dict]]:
        before, after = self._merged(payload)
        old = {a["channel"]: a for a in before}
        diff = [{"key": a["channel"], "field": k, "label": AssumptionRules.LABEL[k],
                 "before": old[a["channel"]].get(k), "after": a[k]}
                for a in after for k in AssumptionRules.NUMERIC if old[a["channel"]].get(k) != a[k]]
        chans = sorted({d["key"] for d in diff})
        return f"계산 가정 {len(diff)}칸 변경 ({', '.join(chans)})", diff

    def apply(self, user: User, change: ChangeSet) -> dict:
        before, after = self._merged(change.payload)
        self.store.save_assumptions(after)
        return {"rows": before}

    def revert(self, user: User, change: ChangeSet) -> None:
        self.store.save_assumptions((change.undo or {})["rows"])


def handlers(store) -> Registry[ChangeHandler]:
    """이 모듈의 변경 처리기 묶음 (저장소를 주입)."""
    reg: Registry[ChangeHandler] = Registry("Capacity 변경")
    for h in (AssumptionsChange(store),):
        reg.register(h.kind, h)
    return reg
