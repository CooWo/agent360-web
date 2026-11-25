"""상담사 INFO 한꺼번에 고치기 — 시트에서 복사해 붙여넣기 · 파일(.xlsx/.csv) 올리기 → InfoEditChange 의 payload.

규칙 (시트 쓰던 방식 그대로)
- 머리글 줄이 있어야 한다 (INFO 자동화 시트의 머리글 이름). 위에 담당 줄(OPS/WFM/BA)이 같이 와도 된다.
- 사번으로 사람을 찾는다. 있는 사번 = 고치기, 없는 사번 = 새 사람.
- 빈 칸은 바꾸지 않는다 (지우려면 화면에서 칸을 직접 비운다).
- 고칠 권한이 없는 열은 건너뛰고, 건너뛴 열 이름을 미리보기에 보여 준다.
- 값 검사(날짜·재직정보 등)와 실제 비교는 InfoEditChange 가 한다 — 여기서는 모양만 바꾼다.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from app.core.errors import InvalidInput
from app.core.permissions import User
from app.modules.info.services.edits import can_edit
from app.modules.roster.services.info import LABEL, clean_id, header_index

MAX_ROWS = 5000
HEADER_SCAN = 5          # 위에서 몇 줄 안에서 머리글을 찾을지


@dataclass
class BulkPlan:
    payload: dict
    rows: int = 0                         # 사번이 있는 데이터 줄
    skipped_cols: list[str] = field(default_factory=list)   # 권한 없어 건너뛴 열
    unknown_cols: list[str] = field(default_factory=list)   # 모르는 머리글 (무시)


def find_header(grid: list[list[str]]) -> int:
    for i, row in enumerate(grid[:HEADER_SCAN]):
        idx = header_index(row)
        if "emp_id" in idx.values() and len(idx) >= 2:
            return i
    raise InvalidInput({"paste": "머리글 줄(사번 · 한글명 …)을 찾지 못했습니다. 시트에서 머리글 줄까지 같이 복사해 주세요."})


def plan(grid: list[list[str]], current_ids: set[str], user: User, source: str) -> BulkPlan:
    grid = [r for r in grid if r is not None]
    if not any(any(c for c in r) for r in grid):
        raise InvalidInput({"paste": "붙여넣은 내용이 없습니다."})
    h = find_header(grid)
    head = grid[h]
    idx = header_index(head)
    emp_col = next(i for i, f in idx.items() if f == "emp_id")
    use = {i: f for i, f in idx.items() if f != "emp_id" and can_edit(user, f)}
    skipped = [LABEL[f] for i, f in sorted(idx.items()) if f != "emp_id" and i not in use]
    unknown = [c for i, c in enumerate(head) if c and i not in idx]
    body = grid[h + 1:]
    if len(body) > MAX_ROWS:
        raise InvalidInput({"paste": f"한 번에 {MAX_ROWS:,}줄까지 할 수 있습니다."})

    cells: dict[tuple[str, str], str] = {}
    new: dict[str, dict] = {}
    rows = 0
    for line in body:
        emp = clean_id(line[emp_col] if emp_col < len(line) else "")
        if not emp:
            continue
        rows += 1
        vals = {f: line[i].strip() for i, f in use.items() if i < len(line) and line[i].strip()}
        if emp in current_ids:
            for f, v in vals.items():
                cells[(emp, f)] = v                  # 같은 사번이 또 나오면 뒤 줄이 이긴다
        else:
            new.setdefault(emp, {"emp_id": emp}).update(vals)
    payload = {"cells": [{"emp_id": e, "field": f, "value": v} for (e, f), v in cells.items()],
               "new": list(new.values()),
               "source": {"how": source, "rows": rows, "skipped_cols": skipped, "unknown_cols": unknown[:10]}}
    return BulkPlan(payload, rows, skipped, unknown)
