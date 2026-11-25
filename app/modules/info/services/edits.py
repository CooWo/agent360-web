"""상담사 INFO 웹 수정 — 시트 마트 위에 웹 수정분을 덮어 보여 주고(InfoOverlay), 수정은 공통 변경 틀로(InfoEditChange).

- 시트를 다시 불러와도 웹 수정분(info_edits)은 남는다. 같은 칸은 가장 최근 수정이 이긴다.
- 열 담당(OPS · WFM · BA)에 맞는 권한(info.edit.ops / .wfm / .ba)이 있어야 그 열을 고친다.
- 새 사람 등록 = 사번 + 한글명 필수, 나머지 칸은 고칠 권한이 있는 것만.
- 날짜 칸은 날짜로 읽을 수 있어야 저장 (YYYY-MM-DD 로 바꿔 저장).
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from app.core.changes import ChangeHandler, ChangeSet
from app.core.errors import InvalidInput
from app.core.permissions import User
from app.core.registry import Registry
from app.modules.roster.services.info import (DATE_FIELDS, DATE_TEXT_MARKS, EMPTY_MARKS, FIELDS, KIND, LABEL, OWNER,
                                              clean_id, parse_date)

STATUS_VALUES = ("재직자", "퇴직자", "확인안됨")


def can_edit(user: User, field: str) -> bool:
    return field != "emp_id" and user.can(f"info.edit.{OWNER[field].lower()}")


def normalize(field: str, value) -> tuple[str, str | None]:
    """칸 하나 → (저장할 값, 오류 문구)."""
    v = str(value if value is not None else "").strip()
    if v in EMPTY_MARKS:
        v = ""
    if KIND[field] == "id":
        return clean_id(v), None
    if field in DATE_FIELDS and v:
        if v in DATE_TEXT_MARKS:
            return "", None
        d = parse_date(v)
        return (d, None) if d else (v, f"{LABEL[field]}: 날짜로 읽을 수 없습니다 ({v})")
    if field == "email":
        return v.lower(), None
    if field == "status" and v and v not in STATUS_VALUES:
        return v, f"재직정보는 {' · '.join(STATUS_VALUES)} 중 하나입니다."
    return v, None


class InfoOverlay:
    """시트 마트 + 웹 수정분 → 화면·다른 모듈이 쓰는 지금 상태."""

    @staticmethod
    def apply(base: list[dict], edits: list[dict]) -> list[dict]:
        rows = {r["emp_id"]: {**{f: r.get(f, "") or "" for f in FIELDS}, "dates_ok": r.get("dates_ok", True),
                              "_edited": {}, "_new": False} for r in base}
        order = list(rows)
        for e in sorted(edits, key=lambda x: (str(x.get("edited_at") or ""), x.get("edit_id") or "")):
            r = rows.get(e["emp_id"])
            if r is None:
                r = rows[e["emp_id"]] = {**{f: "" for f in FIELDS}, "emp_id": e["emp_id"], "dates_ok": True,
                                         "_edited": {}, "_new": True}
                order.append(e["emp_id"])
            if e["field"] in FIELDS and e["field"] != "emp_id":
                r[e["field"]] = e.get("value") or ""
                r["_edited"][e["field"]] = {"by": e.get("edited_by"), "at": str(e.get("edited_at") or "")[:16],
                                            "change_id": e.get("change_id")}
        return [rows[k] for k in order]


def effective_info(store) -> list[dict]:
    return InfoOverlay.apply(store.agent_info(), store.info_edits())


class InfoEditChange(ChangeHandler):
    """payload = {"cells": [{"emp_id","field","value"}], "new": [{필드: 값, ...}]}"""
    kind = "info.edit"
    title = "상담사 INFO"
    permission = "info.edit"

    def __init__(self, store):
        self.store = store

    def _plan(self, user: User, payload: dict) -> list[dict]:
        if not isinstance(payload, dict):
            raise InvalidInput({"payload": "형식이 올바르지 않습니다."})
        current = {r["emp_id"]: r for r in effective_info(self.store)}
        errs: dict[str, str] = {}
        out: list[dict] = []
        for i, n in enumerate(payload.get("new") or [], 1):
            emp = clean_id(n.get("emp_id"))
            name = str(n.get("name") or "").strip()
            if not emp or not name:
                errs[f"new.{i}"] = "새 사람은 사번과 한글명이 필요합니다."
                continue
            if emp in current:
                errs[f"new.{i}"] = f"이미 있는 사번입니다: {emp}"
                continue
            out.append({"emp_id": emp, "name": name, "field": "new", "label": "신규 등록", "before": "", "after": name,
                        "is_new": True})
            for f in FIELDS:
                if f == "emp_id" or str(n.get(f) or "").strip() == "":
                    continue
                if not can_edit(user, f):
                    errs[f"new.{i}.{f}"] = f"{LABEL[f]}({OWNER[f]} 담당) 칸은 입력 권한이 없습니다."
                    continue
                v, e = normalize(f, n.get(f))
                if e:
                    errs[f"new.{i}.{f}"] = e
                out.append({"emp_id": emp, "name": name, "field": f, "label": LABEL[f], "before": "", "after": v,
                            "is_new": True})
        seen: dict[tuple, int] = {}
        for i, c in enumerate(payload.get("cells") or [], 1):
            emp, f = clean_id(c.get("emp_id")), str(c.get("field") or "")
            if emp not in current:
                errs[f"cells.{i}"] = f"없는 사번입니다: {emp}"
                continue
            if f not in FIELDS:
                errs[f"cells.{i}"] = f"없는 항목입니다: {f}"
                continue
            if not can_edit(user, f):
                errs[f"cells.{i}"] = f"{current[emp]['name']} · {LABEL[f]}({OWNER[f]} 담당) 칸은 수정 권한이 없습니다."
                continue
            v, e = normalize(f, c.get("value"))
            if e:
                errs[f"cells.{i}"] = f"{current[emp]['name']} · {e}"
                continue
            before = current[emp].get(f, "") or ""
            if v == before:
                continue
            d = {"emp_id": emp, "name": current[emp]["name"], "field": f, "label": LABEL[f], "before": before,
                 "after": v, "is_new": False}
            if (emp, f) in seen:
                out[seen[(emp, f)]] = d
            else:
                seen[(emp, f)] = len(out)
                out.append(d)
        if errs:
            raise InvalidInput(errs)
        return out

    def preview(self, user: User, payload: dict) -> tuple[str, list[dict]]:
        plan = self._plan(user, payload)
        diff = [{"key": d["emp_id"], **{k: d[k] for k in ("name", "field", "label", "before", "after")}} for d in plan]
        new = sorted({d["emp_id"] for d in plan if d["field"] == "new"})
        edits = [d for d in plan if not d["is_new"]]
        people = sorted({d["emp_id"] for d in edits})
        parts = ([f"신규 {len(new)}명"] if new else []) + ([f"{len(people)}명 {len(edits)}칸 수정"] if edits else [])
        return "상담사 INFO " + " · ".join(parts), diff

    def apply(self, user: User, change: ChangeSet) -> dict:
        now = datetime.now(timezone.utc).isoformat()
        rows = [{"edit_id": "E" + uuid.uuid4().hex[:12], "change_id": change.change_id, "emp_id": d["emp_id"],
                 "field": "name" if d["field"] == "new" else d["field"], "value": d["after"], "is_new": d["is_new"],
                 "edited_at": now, "edited_by": user.email}
                for d in self._plan(user, change.payload)]
        self.store.add_info_edits(rows)
        return {"change_id": change.change_id}

    def revert(self, user: User, change: ChangeSet) -> None:
        self.store.deactivate_info_edits(change.change_id, user.email)


def handlers(store) -> Registry[ChangeHandler]:
    reg: Registry[ChangeHandler] = Registry("상담사 INFO 변경")
    h = InfoEditChange(store)
    reg.register(h.kind, h)
    return reg
