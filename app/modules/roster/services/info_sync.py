"""INFO 불러오기 — 시트 읽기 → 정리 → (저장). 스크립트와 웹 버튼이 같은 서비스를 쓴다.

읽는 쪽(SheetReader)과 저장 쪽(InfoMartLoader)을 주입받는다 → 테스트는 가짜로, 운영은 서비스 계정으로.
"""
from __future__ import annotations

from collections import Counter

from app.modules.roster.services.info import InfoCleaner, raw_rows


class InfoSyncService:
    def __init__(self, reader, loader=None, cleaner: InfoCleaner | None = None):
        self.reader, self.loader, self.cleaner = reader, loader, cleaner or InfoCleaner()

    def run(self, sheet: str, tab: str, by: str, header_row: int = 2, dry_run: bool = True,
            force: bool = False) -> dict:
        cells = self.reader.values(sheet, f"'{tab}'!A{header_row}:Y")
        if not cells:
            raise ValueError("시트가 비어 있습니다.")
        header, body = cells[0], cells[1:]
        raw = raw_rows(header, body)
        res = self.cleaner.clean(raw)
        out = {**res.summary(), "status": dict(Counter(r["status"] or "(빈 값)" for r in res.rows)),
               "issue_samples": res.issues[:10], "duplicate_ids": sorted(set(res.duplicates))[:20],
               "load_id": None, "dry_run": dry_run}
        if not dry_run:
            out["load_id"] = self.loader.save(raw, body, res, source=f"{sheet}/{tab}", by=by, force=force)
        return out
