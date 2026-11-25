"""조립 지점 — INFO 수정 변경 서비스 (저장소·변경 기록·감사 주입)."""
from __future__ import annotations

from app.core.audit import Auditor
from app.core.changes import ChangeService
from app.core.data import get_backend
from app.core.data.changelog import get_change_log
from app.modules.info.services.edits import handlers
from app.modules.roster.data import get_store


def sheet_writeback(screens: dict | None = None):
    """원본 시트 쓰기 — bigquery(운영)일 때만. 샘플·테스트에서는 시트를 건드리지 않는다."""
    from app.core.config import get_settings
    if get_settings().data_backend != "bigquery":
        return None
    from app.core.modules import discover
    from app.core.sheets import GoogleSheetReader, GoogleSheetWriter
    from app.modules.info.services.writeback import InfoSheetWriteBack
    cfg = (screens or next(m for m in discover() if m.name == "info").screens)["screens"]["info"]
    return InfoSheetWriteBack(GoogleSheetReader(), GoogleSheetWriter(), cfg["source_sheet"], cfg["source_tab"],
                              cfg.get("header_row", 2))


def change_service(store=None, backend=None, log=None, writeback=None) -> ChangeService:
    store = store or get_store()
    wb = writeback if writeback is not None else sheet_writeback()
    return ChangeService(handlers(store, wb), log or get_change_log(), Auditor.for_store(backend or get_backend()))
