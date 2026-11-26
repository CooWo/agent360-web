"""대시보드 화면 데이터 — 한 화면 = 함수 하나. 계산은 services/summary.py."""
from __future__ import annotations

import math
from datetime import date, timedelta

from app.core.charts import count_bars, line_chart
from app.core.permissions import User
from app.modules.agent360.services import coaching as coaching_svc
from app.modules.agent360.services import kpi as kpi_svc
from app.modules.agent360.services import signals as signal_svc
from app.modules.dashboard.services import summary


def dashboard(backend, user: User, screens: dict, weeks=None, start: str | None = None, end: str | None = None) -> dict:
    """weeks = 최근 N주, start·end = 달력으로 고른 기간(우선). 둘 다 없으면 최근 default_weeks 주."""
    cfg = screens["screens"]["dashboard"]
    as_of = backend.as_of()
    period, period_note = summary.resolve_period(as_of, weeks, start, end, cfg.get("default_weeks", 4),
                                                 cfg.get("max_weeks", 26), cfg.get("max_days", 366))
    agents = backend.list_agents(user.scope)
    ids = [a["agent_id"] for a in agents]
    labels = {x["team"]: x["label"] for x in backend.list_teams()}
    cw = summary.chart_weeks(period)
    kpi_since = min(period.prior_start, period.end - timedelta(days=7 * cw + 7))
    kpi_by = backend.kpi_daily_many(ids, kpi_since.isoformat())
    all_kpi = [r for rows in kpi_by.values() for r in rows]
    att_weeks = max(math.ceil(period.days / 7), cfg.get("attendance_weeks", 8))
    att_since = min(period.start, period.end - timedelta(days=7 * (att_weeks + 1)))
    att = backend.attendance_many(ids, att_since.isoformat())
    mine = set(ids)
    qa_rows = [r for r in backend.qa_coaching() if r["agent_id"] in mine]
    kpi = summary.kpi_overview(all_kpi, period, cfg["kpi_metrics"])
    for m in kpi["metrics"]:
        m["svg"] = line_chart(m["labels"], m["weekly"], unit=m["unit"], ref=m["prior"], ref_label="직전 기간")
    att_wk = summary.attendance_weekly(att, period.end.isoformat(), att_weeks)
    mark = next((i for i, r in enumerate(att_wk["rows"]) if r["week_end"] == att_wk["base"]), None)
    faded = len(att_wk["rows"]) - 1 if att_wk["running"] else None
    for c in att_wk["compare"]:
        c["svg"] = count_bars(att_wk["labels"], c["series"], avg=c["avg"], mark=mark, faded=faded, unit="칸")
    ranked = signal_svc.by_agent(backend, user)
    fu = coaching_svc.followups(backend, user, as_of, cfg.get("followup_days", 3))
    return {
        "cfg": cfg, "as_of": as_of, "period": period, "period_note": period_note,
        "data_last": (date.fromisoformat(as_of) - timedelta(days=1)).isoformat(),
        "headcount": summary.headcount(agents, as_of, cfg.get("new_hire_days", 90)),
        "kpi": kpi,
        "teams": summary.team_table(agents, kpi_by, att, qa_rows, labels, period, cfg["team_metrics"]),
        "team_cols": [{"key": k, "label": kpi_svc.BY_KEY[k].label, "unit": kpi_svc.BY_KEY[k].unit,
                       "digits": kpi_svc.BY_KEY[k].digits, "better": kpi_svc.BY_KEY[k].better} for k in cfg["team_metrics"]],
        "attendance": summary.attendance_overview(att, period),
        "att_weekly": att_wk,
        "qa": summary.qa_overview(qa_rows),
        "signals": {"agents": len(ranked), "open": sum(r["open"] for r in ranked), "top": ranked[:5]},
        "followups": {"overdue": len(fu["overdue"]), "soon": len(fu["soon"])},
    }
