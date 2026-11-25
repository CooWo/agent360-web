"""팀 구성 불러오기 — 시트 '팀구성-New'(예전 'OPS TL') (TL 한글 이름 줄 아래 Shift · 사번 · 이름 · Name · Display name 블록) → team_roster.

상담사 360 의 상담사 목록·팀 이름은 이 표를 따른다 (팀 = TL 한글 이름, 이 표에 있는 사람만 보임).
읽는 쪽(SheetReader)·저장 쪽(TeamRosterLoader)을 주입받는다 → 테스트는 가짜로.
"""
from __future__ import annotations

import re
from collections import Counter
from datetime import datetime, timezone

from app.modules.roster.services import paste
from app.modules.roster.services.info import clean_id

TEAM_COLS = ("tl_name", "sort_order", "row_order", "shift", "emp_id", "name", "e_name", "display_name")
MIN_KEEP = 0.5          # 새 명단이 지금의 절반 미만이면 멈춤 (시트가 깨졌을 가능성)


LEAVE_MARKS = ("휴가", "휴직")      # Shift 칸에 육아휴가·출산휴가·무급휴직… → 블록 아래 '쉬는 사람' 구역 시작
FOOTER_MARK = "ratio"              # 묶음 맨 아래 인원·Ratio 줄 (예: 11 · Ratio: 1:12)
MAX_ROWS = 300                     # 다음 묶음·Ratio 줄이 없을 때 한 블록을 몇 줄까지 볼지


def _cell(row: list, i: int) -> str:
    return str(row[i]).strip() if i < len(row) and row[i] is not None else ""


def _is_leave(v: str) -> bool:
    return any(m in v for m in LEAVE_MARKS)


def _is_footer(line: list, s: int, stop: int) -> bool:
    return any(_cell(line, i).lower().startswith(FOOTER_MARK) for i in range(s, stop))


def snapshot_blocks(grid: list[list[str]]) -> list[dict]:
    """팀 구성 시트(팀구성-New · OPS TL)는 날짜별 묶음을 위에서부터 쌓는다 (맨 위 = 지금).
    맨 위 묶음의 TL 블록마다: {"tl", "cols": {열 번호: 항목}, "first": 첫 명단 줄, "end": 명단 칸 끝(제외),
    "members": [명단 줄]}. 줄·열 번호는 0부터. 명단 칸은 '육아휴가' 같은 표시나 Ratio 줄 전까지."""
    heads = [i for i, r in enumerate(grid) if _cell(r, 0).lower() == "shift"]
    if not heads:
        raise ValueError("머리글 줄(Shift · 사번 · 이름 …)을 찾지 못했습니다.")
    h = heads[0]
    end = heads[1] - 2 if len(heads) > 1 else h + 1 + MAX_ROWS      # 다음 묶음의 날짜·TL 줄 전까지
    head = [_cell(grid[h], i).lower() for i in range(len(grid[h]))]
    starts = [i for i, c in enumerate(head) if c == "shift"]
    blocks = []
    for n, s in enumerate(starts):
        stop = starts[n + 1] if n + 1 < len(starts) else len(head)
        cols = {i: paste.HEADER[head[i]] for i in range(s, stop) if head[i] in paste.HEADER}
        tl = re.sub(r"\s*\(.*?\)\s*$", "", _cell(grid[h - 1], s)) if h > 0 else ""
        cap_end, members = end, []
        for r in range(h + 1, end):
            line = grid[r] if r < len(grid) else []
            if _is_leave(_cell(line, s)) or _is_footer(line, s, stop):
                cap_end = r
                break
            rec = {f: _cell(line, i) for i, f in cols.items()}
            if any(rec.values()):
                members.append(rec)
        blocks.append({"tl": tl, "cols": cols, "first": h + 1, "end": cap_end, "members": members})
    return blocks


def latest_snapshot(grid: list[list[str]]) -> list[dict]:
    """맨 위 묶음의 명단 줄 전부 (TL 블록 왼쪽부터, 블록 안은 위에서부터)."""
    return [{**m, "tl": b["tl"]} for b in snapshot_blocks(grid) for m in b["members"]]


def roster_from_grid(grid: list[list[str]]) -> list[dict]:
    """시트 칸 격자 → 지금 팀 구성(맨 위 묶음)에서 사번 있는 행만, TL 순서는 시트 왼쪽부터."""
    rows = latest_snapshot(grid)
    order: dict[str, int] = {}
    out, seen = [], set()
    for r in rows:
        emp = clean_id(r.get("emp_id"))
        tl = str(r.get("tl") or "").strip()
        if not emp or not tl or emp in seen:          # 같은 사번이 두 TL 에 있으면 왼쪽(먼저) TL
            continue
        seen.add(emp)
        order.setdefault(tl, len(order))
        out.append({"tl_name": tl, "sort_order": order[tl], "row_order": len(out),
                    "shift": (r.get("shift") or "").strip(), "emp_id": emp,
                    "name": (r.get("name") or "").strip(), "e_name": (r.get("e_name") or "").strip(),
                    "display_name": (r.get("display_name") or "").strip()})
    return out


class TeamRosterSync:
    def __init__(self, reader, loader=None):
        self.reader, self.loader = reader, loader

    def run(self, sheet: str, tab: str, by: str, dry_run: bool = True, force: bool = False) -> dict:
        grid = self.reader.values(sheet, f"'{tab}'!A1:ZZ1500")
        if not grid:
            raise ValueError("시트가 비어 있습니다.")
        rows = roster_from_grid(grid)
        if not rows:
            raise ValueError("사번이 있는 행을 찾지 못했습니다 (머리글: Shift · 사번 · 이름 · Name · Display name).")
        tls = Counter(r["tl_name"] for r in rows)
        out = {"rows": len(rows), "tls": [{"tl": t, "n": n} for t, n in
                                           sorted(tls.items(), key=lambda kv: min(r["sort_order"] for r in rows
                                                                                  if r["tl_name"] == kv[0]))],
               "dry_run": dry_run, "load_id": None}
        if not dry_run:
            out["load_id"] = self.loader.save(rows, source=f"{sheet}/{tab}", by=by, force=force)
        return out


def new_load_id() -> str:
    return "T" + datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
