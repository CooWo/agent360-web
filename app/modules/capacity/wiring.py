"""조립 지점 — 구현 객체를 만들어 서비스에 주입한다 (라우터·미리보기·테스트가 여기서 가져감)."""
from __future__ import annotations

from app.core.audit import Auditor
from app.core.changes import ChangeService
from app.core.data import get_backend
from app.core.data.changelog import get_change_log
from app.modules.capacity.data import get_store
from app.modules.capacity.services.changes import handlers


def change_service(store=None, backend=None, log=None) -> ChangeService:
    store = store or get_store()
    backend = backend or get_backend()
    return ChangeService(handlers(store), log or get_change_log(), Auditor.for_store(backend))
