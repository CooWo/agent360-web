"""Capacity 화면에 넘길 데이터 (웹 프레임워크와 무관 — 테스트·미리보기도 같이 씀)."""
from __future__ import annotations

from datetime import date, timedelta

from app.core import charts
from app.core.errors import NotFound
from app.core.permissions import User
from app.modules.capacity.services import fte


def week_end(d: str) -> str:
    """그 날짜가 든 주의 토요일 (주 = 일~토)."""
    x = date.fromisoformat(d)
    return (x + timedelta(days=(5 - x.weekday()) % 7)).isoformat()


def _short(week: str) -> str:
    return week[5:].replace("-", "/")


def home(backend, store, user: User, screens: dict) -> dict:
    sc = screens["screens"]["home"]
    fte.check_view(user, sc)
    as_of = backend.as_of()
    cur = week_end(as_of)
    c = date.fromisoformat(cur)
    since = (c - timedelta(weeks=sc.get("weeks_back", 4))).isoformat()
    until = (c + timedelta(weeks=sc.get("weeks_ahead", 12))).isoformat()
    assumptions = store.assumptions()
    rows = fte.weekly(store.forecast(since, until), store.headcount(since, until), assumptions)
    totals = fte.total_by_week(rows)
    now = next((t for t in totals if t["week"] == cur), None)
    warn = sc.get("short_warn_pct", -5)
    labels = [_short(t["week"]) for t in totals]
    return {
        "cfg": sc, "as_of": as_of, "week": cur, "now": now, "warn_pct": warn,
        "shortage": fte.first_shortage(totals, cur, warn),
        "totals": totals,
        "channels": [r for r in rows if r["week"] == cur],
        "assumptions": assumptions,
        "chart_gap": charts.bar_chart(labels, [t["gap"] for t in totals], unit=" FTE", mark=_short(cur)),
        "chart_req": charts.line_chart(labels, [t["required"] for t in totals], unit=" FTE", width=640, height=150),
    }


def placeholder(user: User, screens: dict, screen_id: str) -> dict:
    sc = screens["screens"].get(screen_id)
    if not sc:
        raise NotFound("없는 화면입니다.")
    fte.check_view(user, sc)
    return {"cfg": sc}
