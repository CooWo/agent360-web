"""조립 지점 — 상담사 360 변경 서비스 (QA·코칭 올리기). 백엔드·변경 기록·감사 주입."""
from __future__ import annotations

from app.core.audit import Auditor
from app.core.changes import ChangeService
from app.core.data import get_backend
from app.core.data.changelog import get_change_log
from app.modules.agent360.services.qa_coaching import NEED_BELOW, handlers


def change_service(backend=None, log=None, need_below: float = NEED_BELOW) -> ChangeService:
    backend = backend or get_backend()
    return ChangeService(handlers(backend, need_below), log or get_change_log(), Auditor.for_store(backend))
