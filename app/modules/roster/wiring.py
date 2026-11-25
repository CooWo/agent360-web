"""조립 지점 — 팀 구성 변경 서비스 (저장소·변경 기록·감사 주입, 새 TL 알림 연결)."""
from __future__ import annotations

from app.core.audit import Auditor
from app.core.changes import ChangeService
from app.core.data import get_backend
from app.core.data.changelog import get_change_log
from app.modules.roster.data import get_store
from app.modules.roster.services.changes import handlers


def change_service(store=None, backend=None, log=None) -> ChangeService:
    store = store or get_store()
    auditor = Auditor.for_store(backend or get_backend())

    def notify_new_tl(user, tls):
        # BA팀 알림: 지금은 감사 로그. 슬랙 등은 AuditSink 를 더해 연결한다.
        auditor.record(user, "roster_new_tl", "tl", ",".join(tls), {"tls": tls, "notify": "BA"})

    return ChangeService(handlers(store, notify_new_tl), log or get_change_log(), auditor)
