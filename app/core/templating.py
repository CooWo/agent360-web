"""화면 렌더링 — 공통 레이아웃(app/templates) + 모든 모듈의 templates 폴더를 한 Jinja 환경으로.

render(template, ctx, user=..., module=..., active=...) 하나로 HTML 을 만든다.
웹 서버(FastAPI)와 미리보기 스크립트·테스트가 같은 함수를 쓰므로 화면이 항상 같다.
"""
from __future__ import annotations

from datetime import date
from functools import lru_cache
from pathlib import Path

from jinja2 import ChoiceLoader, Environment, FileSystemLoader, select_autoescape

from app.core.config import get_settings
from app.core.modules import discover
from app.core.permissions import ROLE_LABEL, User

APP_DIR = Path(__file__).resolve().parents[1]

# 정적 파일 주소. 웹에서는 /static, 미리보기에서는 파일 경로로 바꾼다.
STATIC_PREFIX = {"value": "/static"}


def _num(v, digits: int = 0) -> str:
    if v is None or v == "":
        return "–"
    try:
        return f"{float(v):,.{digits}f}"
    except (TypeError, ValueError):
        return str(v)


def _signed(v, digits: int = 0, suffix: str = "") -> str:
    if v is None:
        return "–"
    return f"{v:+,.{digits}f}{suffix}"


def _days_ago(d: str | None, as_of: str) -> str:
    if not d:
        return "–"
    n = (date.fromisoformat(as_of) - date.fromisoformat(d)).days
    return "오늘" if n == 0 else (f"{n}일 전" if n > 0 else f"{-n}일 후")


def _static(path: str) -> str:
    """정적 파일 주소 + 파일 수정 시각(?v=…). 파일이 바뀌면 주소가 바뀌어 브라우저가 옛 CSS·JS 를 쓰지 않는다."""
    f = APP_DIR / "static" / path
    v = int(f.stat().st_mtime) if f.exists() else 0
    return f"{STATIC_PREFIX['value']}/{path}?v={v}"


@lru_cache
def env(with_routers: bool = True) -> Environment:
    loaders = [FileSystemLoader(str(APP_DIR / "templates"))]
    loaders += [FileSystemLoader(str(m.templates_dir)) for m in discover(with_routers)]
    e = Environment(loader=ChoiceLoader(loaders), autoescape=select_autoescape(["html"]),
                    trim_blocks=True, lstrip_blocks=True)
    e.filters.update(num=_num, signed=_signed)
    e.globals.update(static=_static, days_ago=_days_ago, ROLE_LABEL=ROLE_LABEL)
    return e


def _ai_dock(mods, module, user: User | None) -> dict | None:
    """오른쪽 AI 패널: AI 질문 모듈이 있고 역할이 허용되면 모든 화면에 붙인다 (AI 질문 화면 자신은 제외)."""
    ai = next((m for m in mods if m.name == "assistant"), None)
    if not ai or not user or (module is not None and module.name == "assistant"):
        return None
    screen = ai.screen("ask")
    if user.role not in screen.get("roles", []):
        return None
    from app.core.ai import get_data_agent
    s = get_settings()
    return {"enabled": get_data_agent() is not None, "label": s.ai_agent_label,
            "examples": screen.get("dock_examples") or screen.get("examples", [])[:3],
            "max_len": screen.get("max_question", 1000)}


def render(template: str, ctx: dict, *, user: User | None, module=None, active: str = "",
           users_for_switch: list[dict] | None = None, with_routers: bool = True) -> str:
    s = get_settings()
    mods = discover(with_routers)
    nav = [{"title": m.title, "path": m.base_path, "current": m is module} for m in mods
           if user and m.menu_for(user.role) and m.screens.get("in_nav", True)]
    side = module.menu_for(user.role) if (module and user) else []
    ai_dock = _ai_dock(mods, module, user)
    base = {
        "app_title": s.app_title, "is_local": s.is_local, "user": user, "module": module,
        "nav": nav, "side": side, "active": active, "ai_dock": ai_dock, "users_for_switch": users_for_switch or [],
    }
    return env(with_routers).get_template(template).render({**base, **ctx})
