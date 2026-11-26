"""대시보드 모듈 — 첫 화면. 상담사 360·근태·QA·코칭·신호를 한눈에 (이름은 아직 '대시보드')."""
from pathlib import Path

from app.core.modules import Module

FOLDER = Path(__file__).resolve().parent


def build(with_routers: bool = True) -> Module:
    page_router = api_router = None
    if with_routers:
        from app.modules.dashboard.api import router as api_router
        from app.modules.dashboard.pages import router as page_router
    return Module(name="dashboard", folder=FOLDER, page_router=page_router, api_router=api_router, order=5)
