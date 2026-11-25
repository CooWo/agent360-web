"""조립 지점 — INFO 수정 변경 서비스 (저장소·변경 기록·감사 주입)."""
from __future__ import annotations

from app.core.audit import Auditor
from app.core.changes import ChangeService
from app.core.data import get_backend
from app.core.data.changelog import get_change_log
from app.modules.info.services.edits import handlers
from app.modules.roster.data import get_store


def change_service(store=None, backend=None, log=None) -> ChangeService:
    store = store or get_store()
    return ChangeService(handlers(store), log or get_change_log(), Auditor.for_store(backend or get_backend()))
