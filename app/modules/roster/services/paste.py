"""시트에서 복사한 내용(탭으로 구분된 글자) → 보드 행.

읽는 모양
1) OPS TL 통째로: TL 이름 줄 아래에 'Shift · 사번 · 이름 · Name · Display name' 머리글이 TL 마다 반복
2) 한 TL 블록만: 같은 머리글 하나 (TL 은 화면에서 고른 값)
3) OPS RAW 처럼 세로로 긴 표: 머리글에 Leader(또는 TL) 열이 있음
4) 머리글 없이 값만: Shift · 사번 · 이름 · Name · Display name 순서로 보고, TL 은 화면에서 고른 값
"""
from __future__ import annotations

from app.core.errors import InvalidInput

HEADER = {"shift": "shift", "사번": "emp_id", "ubase id": "emp_id", "이름": "name", "name": "e_name",
          "e-name": "e_name", "display name": "display_name", "leader": "tl", "tl": "tl", "반영일": "date",
          "date": "date", "메모": "note", "note": "note"}
DEFAULT_ORDER = ("shift", "emp_id", "name", "e_name", "display_name")
MAX_ROWS = 5000


def _cells(text: str) -> list[list[str]]:
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    return [[c.strip() for c in ln.split("\t")] for ln in lines]


def _is_header(row: list[str]) -> bool:
    low = {c.lower() for c in row}
    return "사번" in low and ("shift" in low or "이름" in low)


def parse(text: str, default_tl: str = "") -> list[dict]:
    grid = [r for r in _cells(text or "")]
    if not any(any(c for c in r) for r in grid):
        raise InvalidInput({"paste": "붙여넣은 내용이 없습니다."})
    h = next((i for i, r in enumerate(grid) if _is_header(r)), None)
    blocks: list[tuple[int, dict[int, str], str]] = []      # (시작 열, {열: 칸}, TL)
    if h is None:
        if not default_tl:
            raise InvalidInput({"tl": "머리글이 없으면 TL 을 먼저 골라 주세요."})
        blocks.append((0, {i: f for i, f in enumerate(DEFAULT_ORDER)}, default_tl))
        body = grid
    else:
        head = grid[h]
        long_form = any(HEADER.get(c.lower()) == "tl" for c in head)      # OPS RAW 처럼 TL 열이 있으면 한 블록
        starts = [0] if long_form else ([i for i, c in enumerate(head) if c.lower() == "shift"] or [0])
        for n, s in enumerate(starts):
            end = starts[n + 1] if n + 1 < len(starts) else len(head)
            cols = {i: HEADER[head[i].lower()] for i in range(s, end) if head[i].lower() in HEADER}
            above = grid[h - 1][s] if h > 0 and s < len(grid[h - 1]) else ""
            blocks.append((s, cols, above or default_tl))
        body = grid[h + 1:]
    rows: list[dict] = []
    for start, cols, tl in blocks:
        if "tl" not in cols.values() and not tl:
            raise InvalidInput({"tl": f"{start + 1}번째 열 블록의 TL 을 알 수 없습니다 (머리글 위 줄에 TL 이름 또는 화면에서 TL 선택)."})
        for line in body:
            r = {f: (line[i] if i < len(line) else "") for i, f in cols.items()}
            if not any(r.values()):
                continue
            r.setdefault("tl", tl)
            r["tl"] = r["tl"] or tl
            rows.append(r)
    if not rows:
        raise InvalidInput({"paste": "읽을 수 있는 행이 없습니다."})
    if len(rows) > MAX_ROWS:
        raise InvalidInput({"paste": f"한 번에 {MAX_ROWS:,}행까지 붙여넣을 수 있습니다."})
    return rows
