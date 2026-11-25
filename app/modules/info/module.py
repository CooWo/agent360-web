"""상담사 INFO 모듈 — INFO 자동화 시트 마트 보기·불러오기·웹 수정 (데이터는 roster 데이터셋)."""
from pathlib import Path

from app.core.modules import Module

FOLDER = Path(__file__).resolve().parent


def build(with_routers: bool = True) -> Module:
    page_router = None
    if with_routers:
        from app.modules.info.pages import router as page_router
    return Module(name="info", folder=FOLDER, page_router=page_router, order=11)
