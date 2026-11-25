"""팀 구성(OPS TL) 모듈 — TL 별 명단 보드, 한 번에 고치는 작업 공간 (docs/roster/)."""
from pathlib import Path

from app.core.modules import Module

FOLDER = Path(__file__).resolve().parent


def build(with_routers: bool = True) -> Module:
    page_router = api_router = None
    if with_routers:
        from app.modules.roster.api import router as api_router
        from app.modules.roster.pages import router as page_router
    return Module(name="roster", folder=FOLDER, page_router=page_router, api_router=api_router, order=12)
