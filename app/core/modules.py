"""모듈 등록 — app/modules/<이름>/module.py 의 build() 를 자동으로 찾는다.

새 모듈(예: Capacity Web 의 다른 메뉴)을 붙이는 방법:
  1) app/modules/<이름>/ 폴더를 만들고 module.py 에 build(with_routers) -> Module 정의
  2) screens.json 에 메뉴·화면 구성 작성
  3) pages.py(화면 라우터), api.py(API 라우터), templates/<이름>/ 작성
main.py 는 고치지 않아도 된다. 다른 앱으로 옮길 때도 이 폴더만 옮긴다.
"""
from __future__ import annotations

import importlib
import json
import pkgutil
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

import app.modules as modules_pkg


@dataclass
class Module:
    name: str                       # 'agent360'
    folder: Path                    # 모듈 폴더
    page_router: Any = None         # FastAPI APIRouter (화면, /<name>)
    api_router: Any = None          # FastAPI APIRouter (API, /api/<name>)
    order: int = 100                # 상단 메뉴 순서
    screens: dict = field(default_factory=dict)

    def __post_init__(self):
        if not self.screens:
            self.screens = json.loads((self.folder / "screens.json").read_text(encoding="utf-8"))

    @property
    def title(self) -> str:
        return self.screens.get("title", self.name)

    @property
    def base_path(self) -> str:
        return self.screens.get("base_path", f"/{self.name}")

    @property
    def templates_dir(self) -> Path:
        return self.folder / "templates"

    def menu_for(self, role: str) -> list[dict]:
        return [m for m in self.screens.get("menu", []) if role in m.get("roles", [])]

    def screen(self, screen_id: str) -> dict:
        return self.screens.get("screens", {}).get(screen_id, {})


@lru_cache
def discover(with_routers: bool = True) -> tuple[Module, ...]:
    """modules 패키지 아래 module.py 를 모두 불러온다.
    with_routers=False 면 웹 라우터 없이(=FastAPI 없이) 화면 구성만 불러온다 (미리보기·테스트용)."""
    found = []
    for info in pkgutil.iter_modules(modules_pkg.__path__):
        if not info.ispkg:
            continue
        mod = importlib.import_module(f"app.modules.{info.name}.module")
        m = mod.build(with_routers=with_routers)
        found.append(m)
    return tuple(sorted(found, key=lambda m: m.order))
