"""Capacity Web 모듈 — 필요·가용 FTE, 결근·이탈, 기수, 시뮬레이션 (docs/capacity/)."""
from pathlib import Path

from app.core.modules import Module

FOLDER = Path(__file__).resolve().parent


def build(with_routers: bool = True) -> Module:
    page_router = api_router = None
    if with_routers:
        from app.modules.capacity.api import router as api_router
        from app.modules.capacity.pages import router as page_router
    return Module(name="capacity", folder=FOLDER, page_router=page_router, api_router=api_router, order=15)
