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


def team_sheet_cfg() -> dict:
    """팀 구성 원본 시트 위치 — INFO 화면 설정(team_sheet · team_tab)을 같이 쓴다 (불러오기와 같은 곳)."""
    from app.core.modules import discover
    return next(m for m in discover() if m.name == "info").screens["screens"]["info"]


def team_writeback():
    """원본 시트 '팀구성-New' 쓰기 — bigquery(운영)일 때만. 샘플·테스트에서는 시트를 건드리지 않는다."""
    from app.core.config import get_settings
    if get_settings().data_backend != "bigquery":
        return None
    from app.core.sheets import GoogleSheetReader, GoogleSheetWriter
    from app.modules.roster.services.team_edit import TeamSheetWriteBack
    cfg = team_sheet_cfg()
    return TeamSheetWriteBack(GoogleSheetReader(), GoogleSheetWriter(), cfg["team_sheet"], cfg["team_tab"])


def team_change_service(store=None, backend=None, log=None, writeback=None, loader=None) -> ChangeService:
    """TL별 명단 웹 수정 (team_roster + 원본 시트)."""
    from app.modules.roster.data.info_loader import team_loader
    from app.modules.roster.services.team_edit import handlers as team_handlers
    store = store or get_store()
    wb = writeback if writeback is not None else team_writeback()
    return ChangeService(team_handlers(store, loader or team_loader(store), wb), log or get_change_log(),
                         Auditor.for_store(backend or get_backend()))
