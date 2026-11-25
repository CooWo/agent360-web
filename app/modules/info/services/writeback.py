"""웹 수정 → 원본 시트 맨 아래에 그 사람의 줄을 통째로 더한다 (시트에서 다시 불러오면 아래쪽 줄이 이긴다).

- 줄 = 수정·등록 뒤 '지금 값'(시트 마트 + 웹 수정분) 전체, 시트 머리글 순서대로. 계산 열 등 모르는 열은 비운다.
- 되돌리면 되돌린 뒤의 값으로 한 줄 더 더한다 (시트는 기록처럼 쌓인다).
- 시트에 못 써도 웹 저장은 그대로 두고, 결과를 변경 기록에 남겨 '시트에 다시 쓰기'로 재시도한다.
"""
from __future__ import annotations

from app.modules.roster.services.info import FIELDS, header_index


class InfoSheetWriteBack:
    def __init__(self, reader, writer, sheet: str, tab: str, header_row: int = 2):
        self.reader, self.writer = reader, writer
        self.sheet, self.tab, self.header_row = sheet, tab, header_row

    def rows_for(self, current: dict[str, dict], emp_ids: list[str]) -> list[list[str]]:
        head = (self.reader.values(self.sheet, f"'{self.tab}'!A{self.header_row}:BZ{self.header_row}") or [[]])[0]
        idx = header_index(head)
        if "emp_id" not in idx.values():
            raise ValueError("원본 시트 머리글에서 '사번' 열을 찾지 못했습니다.")
        width = max(idx) + 1
        out = []
        for e in emp_ids:
            r = current.get(e)
            if r:
                out.append([str(r.get(idx[i], "") or "") if i in idx and idx[i] in FIELDS else "" for i in range(width)])
        return out

    def push(self, current: dict[str, dict], emp_ids: list[str]) -> dict:
        rows = self.rows_for(current, emp_ids)
        if not rows:
            return {"ok": True, "rows": 0}
        n = self.writer.append(self.sheet, f"'{self.tab}'!A{self.header_row}", rows)
        return {"ok": True, "rows": n}
