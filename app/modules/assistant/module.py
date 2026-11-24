"""AI 질문 모듈 — 기존 BigQuery 데이터 에이전트를 웹에서 쓴다. Capacity Web 에도 이 폴더째 붙일 수 있다."""
from pathlib import Path

from app.core.modules import Module

FOLDER = Path(__file__).resolve().parent


def build(with_routers: bool = True) -> Module:
    page_router = api_router = None
    if with_routers:
        from app.modules.assistant.api import router as api_router
        from app.modules.assistant.pages import router as page_router
    return Module(name="assistant", folder=FOLDER, page_router=page_router, api_router=api_router, order=20)
