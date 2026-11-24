"""상담사 360 모듈 정의 — Capacity Web 으로 옮길 때 이 폴더(app/modules/agent360)만 옮긴다."""
from pathlib import Path

from app.core.modules import Module

FOLDER = Path(__file__).resolve().parent


def build(with_routers: bool = True) -> Module:
    page_router = api_router = None
    if with_routers:
        from app.modules.agent360.api import router as api_router
        from app.modules.agent360.pages import router as page_router
    return Module(name="agent360", folder=FOLDER, page_router=page_router, api_router=api_router, order=10)
