"""TL별 명단 웹 수정 — 미리보기 → 저장(team_roster + 원본 시트 '팀구성-New' 맨 위 묶음) → 되돌리기.

원본 시트에는 맨 위(지금) 묶음의 TL 블록 칸을 그 자리에서 고쳐 쓴다 (줄 더하기가 아님).
쓰기 전에 시트의 그 TL 명단이 웹의 '고치기 전' 명단과 같은지 본다 → 다르면 (시트에서 누가 고쳤으면) 멈춘다.
바뀐 TL 블록만 쓰고, 고친 열(Shift·사번·이름·Name·Display name)만 쓴다 → 블록의 다른 칸·서식은 그대로.
"""
from __future__ import annotations

from datetime import datetime, timezone

from app.core.changes import ChangeHandler, ChangeSet
from app.core.errors import InvalidInput
from app.core.permissions import User
from app.core.registry import Registry
from app.core.sheets import SheetAccessError
from app.modules.roster.services.board import BoardRules, clean_emp_id, summarize
from app.modules.roster.services.team_sync import MIN_KEEP, snapshot_blocks

FIELDS = ("shift", "emp_id", "name", "e_name", "display_name")
LABEL = {"shift": "Shift", "emp_id": "사번", "name": "이름", "e_name": "Name", "display_name": "Display name"}


def col_letter(i: int) -> str:
    """0 → A, 25 → Z, 26 → AA."""
    s = ""
    i += 1
    while i:
        i, r = divmod(i - 1, 26)
        s = chr(65 + r) + s
    return s


def _key(r: dict) -> tuple:
    return tuple(clean_emp_id(r.get(f)) if f == "emp_id" else str(r.get(f) or "").strip() for f in FIELDS)


def by_tl(rows: list[dict]) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for r in rows:
        out.setdefault(r["tl"], []).append(r)
    return out


def board_rows(team_roster: list[dict]) -> list[dict]:
    """저장된 team_roster → 화면·비교용 행 {tl, shift, emp_id, name, e_name, display_name} (TL 순서 · 줄 순서)."""
    rows = sorted(team_roster, key=lambda r: (r.get("sort_order") if r.get("sort_order") is not None else 999,
                                               r.get("row_order") if r.get("row_order") is not None else 10 ** 6))
    return [{"tl": r["tl_name"], **{f: str(r.get(f) or "") for f in FIELDS}} for r in rows]


def team_rows(rows: list[dict], tl_order: list[str]) -> list[dict]:
    """화면 행 → team_roster 행 (TL 순서는 지금 순서, 새 TL 은 뒤에)."""
    order = {tl: i for i, tl in enumerate(tl_order)}
    out = []
    for r in rows:
        order.setdefault(r["tl"], len(order))
        out.append({"tl_name": r["tl"], "sort_order": order[r["tl"]], "row_order": len(out),
                    **{f: r.get(f, "") for f in FIELDS}})
    return out


class TeamSheetWriteBack:
    """원본 시트 '팀구성-New' 맨 위 묶음의 TL 블록을 고쳐 쓴다. 서버 서비스 계정에 시트 '편집자' 공유가 필요하다."""

    def __init__(self, reader, writer, sheet: str, tab: str):
        self.reader, self.writer, self.sheet, self.tab = reader, writer, sheet, tab

    def plan(self, before: list[dict], after: list[dict]) -> list[tuple[str, list[list[str]]]]:
        """쓸 범위·값. 시트가 '고치기 전'과 다르거나 칸이 모자라면 ValueError (아무것도 쓰지 않음)."""
        grid = self.reader.values(self.sheet, f"'{self.tab}'!A1:ZZ{MAX_READ}")
        blocks = {b["tl"]: b for b in snapshot_blocks(grid)}
        bt, at = by_tl(before), by_tl(after)
        data: list[tuple[str, list[list[str]]]] = []
        for tl in list(dict.fromkeys(list(bt) + list(at))):
            old, new = [_key(r) for r in bt.get(tl, [])], [_key(r) for r in at.get(tl, [])]
            if old == new:
                continue
            b = blocks.get(tl)
            if not b:
                raise ValueError(f"원본 시트 맨 위 팀 구성에 '{tl}' 블록이 없습니다. 시트에 TL 블록을 먼저 만들어 주세요.")
            if [_key(m) for m in b["members"]] != old:
                raise ValueError(f"원본 시트의 '{tl}' 명단이 웹과 다릅니다 (시트에서 바뀐 것 같습니다). "
                                 "INFO 화면에서 '시트에서 불러오기'로 맞춘 뒤 다시 해 주세요.")
            cap = b["end"] - b["first"]
            if len(new) > cap:
                raise ValueError(f"원본 시트의 '{tl}' 블록 명단 칸이 {cap}줄뿐입니다 ({len(new)}명). 시트에 줄을 먼저 늘려 주세요.")
            for c, f in sorted(b["cols"].items()):
                vals = [[r[FIELDS.index(f)]] for r in new] + [[""]] * (cap - len(new))
                data.append((f"'{self.tab}'!{col_letter(c)}{b['first'] + 1}:{col_letter(c)}{b['end']}", vals))
        return data

    def write(self, data: list[tuple[str, list[list[str]]]]) -> dict:
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        if not data:
            return {"ok": True, "cells": 0, "at": now, "tab": self.tab}
        try:
            n = self.writer.update_many(self.sheet, data)
        except SheetAccessError as e:
            return {"ok": False, "error": str(e), "at": now, "tab": self.tab}
        except Exception as e:  # noqa: BLE001 — 시트 쓰기 실패는 웹 저장을 막지 않고 기록 → 다시 쓰기
            return {"ok": False, "error": f"시트 쓰기 실패: {e}", "at": now, "tab": self.tab}
        return {"ok": True, "cells": n, "at": now, "tab": self.tab}


MAX_READ = 400      # 맨 위 묶음만 보면 된다


class TeamRosterEdit(ChangeHandler):
    """payload = {"rows": [{tl, shift, emp_id, name, e_name, display_name}, ...]} — 명단 전체 (TL·줄 순서 그대로)."""
    kind = "roster.team"
    title = "TL별 명단"
    permission = "roster.edit"

    def __init__(self, store, loader, writeback: TeamSheetWriteBack | None = None):
        self.store, self.loader, self.writeback = store, loader, writeback

    def current(self) -> list[dict]:
        return board_rows(self.store.team_roster())

    def normalize(self, payload: dict) -> list[dict]:
        rows = payload.get("rows") if isinstance(payload, dict) else None
        if not isinstance(rows, list):
            raise InvalidInput({"rows": "명단이 없습니다."})
        info = {clean_emp_id(r["emp_id"]): r for r in self.store.agent_info()}
        out, seen, errors = [], {}, {}
        for r in rows:
            n = {"tl": str(r.get("tl") or "").strip(), **{f: str(r.get(f) or "").strip() for f in FIELDS}}
            n["emp_id"] = clean_emp_id(n["emp_id"])
            if not any(n[f] for f in FIELDS):
                continue
            who = n["name"] or n["e_name"] or n["display_name"]
            i = len(out) + 1
            if not n["emp_id"]:
                errors[f"rows.{i}.emp_id"] = f"{n['tl']} · {who}: 사번이 비었습니다."
            elif n["emp_id"] in seen:
                errors[f"rows.{i}.emp_id"] = f"{who or n['emp_id']}: 사번 {n['emp_id']} 이(가) {seen[n['emp_id']]} 에도 있습니다 (한 사람은 한 TL 에만)."
            seen.setdefault(n["emp_id"], n["tl"])
            if not n["tl"]:
                errors[f"rows.{i}.tl"] = f"{who}: TL 이 비었습니다."
            src = info.get(n["emp_id"])
            if src:            # 이름이 비면 INFO 에서 채움
                n["name"] = n["name"] or src.get("name", "")
                n["e_name"] = n["e_name"] or src.get("e_name", "")
            out.append(n)
        if errors:
            raise InvalidInput(errors)
        if not out:
            raise InvalidInput({"rows": "명단이 비어 있습니다. 전체 삭제는 하지 않습니다."})
        return out

    def preview(self, user: User, payload: dict) -> tuple[str, list[dict]]:
        new = self.normalize(payload)
        cur = self.current()
        diff = BoardRules.diff([{**r, "date": "", "note": ""} for r in cur], [{**r, "date": "", "note": ""} for r in new])
        moved = [tl for tl, rs in by_tl(new).items()
                 if [r["emp_id"] for r in rs] != [r["emp_id"] for r in by_tl(cur).get(tl, [])]
                 and sorted(r["emp_id"] for r in rs) == sorted(r["emp_id"] for r in by_tl(cur).get(tl, []))]
        diff += [{"key": tl, "name": tl, "field": "order", "label": "순서", "before": "", "after": "줄 순서 바뀜"}
                 for tl in moved]
        if not diff:
            raise InvalidInput({"rows": "바뀐 칸이 없습니다."})
        return summarize(diff).replace("팀 구성", "TL별 명단") + (f" · 순서 {len(moved)}" if moved else ""), diff

    def _save(self, rows: list[dict], user: User, tl_order: list[str]) -> str:
        from app.modules.roster.data.info_loader import LoadRefused
        if len(rows) < len(self.current()) * MIN_KEEP:
            raise InvalidInput({"rows": "명단이 지금의 절반 미만이 됩니다. 한 번에 이렇게 많이 빼지 않습니다."})
        try:
            return self.loader.save(team_rows(rows, tl_order), source="web", by=user.email, force=True)
        except LoadRefused as e:
            raise InvalidInput({"rows": str(e)}) from e

    def _plan(self, before: list[dict], after: list[dict]):
        """시트 쓰기 계획. 시트가 다르거나 칸 부족 → 저장하지 않음(InvalidInput). 읽기 권한 문제 → 웹만 저장."""
        if not self.writeback:
            return None, None
        try:
            return self.writeback.plan(before, after), None
        except ValueError as e:
            raise InvalidInput({"sheet": str(e)}) from e
        except SheetAccessError as e:
            return None, {"ok": False, "error": str(e), "at": datetime.now(timezone.utc).isoformat(timespec="seconds")}

    def apply(self, user: User, change: ChangeSet) -> dict:
        before, after = self.current(), self.normalize(change.payload)
        data, failed = self._plan(before, after)
        tl_order = list(by_tl(before))
        load_id = self._save(after, user, tl_order)
        sheet = failed or (self.writeback.write(data) if data is not None else None)
        return {"rows": before, "after": after, "tl_order": tl_order, "load_id": load_id, "sheet": sheet}

    def revert(self, user: User, change: ChangeSet) -> None:
        undo = change.undo or {}
        before, after = undo.get("rows") or [], undo.get("after") or []
        data, failed = self._plan(after, before) if (undo.get("sheet") or {}).get("ok") else (None, None)
        self._save(before, user, undo.get("tl_order") or list(by_tl(before)))
        sheet = failed or (self.writeback.write(data) if data is not None else None)
        if sheet is not None:
            change.undo = {**undo, "sheet_revert": sheet}

    def retry(self, user: User, change: ChangeSet) -> dict:
        """시트 쓰기만 다시 (웹은 이미 저장됨)."""
        undo = dict(change.undo or {})
        reverted = change.status == "reverted"
        key = "sheet_revert" if reverted else "sheet"
        frm, to = (undo.get("after"), undo.get("rows")) if reverted else (undo.get("rows"), undo.get("after"))
        data, failed = self._plan(frm or [], to or [])
        undo[key] = failed or (self.writeback.write(data) if data is not None else undo.get(key))
        return undo


def handlers(store, loader, writeback=None) -> Registry[ChangeHandler]:
    reg: Registry[ChangeHandler] = Registry("TL별 명단 변경")
    h = TeamRosterEdit(store, loader, writeback)
    reg.register(h.kind, h)
    return reg
