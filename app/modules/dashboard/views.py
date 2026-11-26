"""대시보드 화면 데이터 — 한 화면 = 함수 하나. 계산은 services/summary.py."""
from __future__ import annotations

from datetime import date, timedelta

from app.core.charts import line_chart
from app.core.permissions import User
from app.modules.agent360.services import coaching as coaching_svc
from app.modules.agent360.services import kpi as kpi_svc
from app.modules.agent360.services import signals as signal_svc
from app.modules.dashboard.services import summary


def dashboard(backend, user: User, screens: dict) -> dict:
    cfg = screens["screens"]["dashboard"]
    as_of = backend.as_of()
    t = date.fromisoformat(as_of)
    agents = backend.list_agents(user.scope)
    ids = [a["agent_id"] for a in agents]
    labels = {x["team"]: x["label"] for x in backend.list_teams()}
    weeks = cfg.get("kpi_weeks", 8)
    kpi_by = backend.kpi_daily_many(ids, (t - timedelta(days=7 * weeks + 35)).isoformat())
    all_kpi = [r for rows in kpi_by.values() for r in rows]
    att_days = cfg.get("attendance_days", 28)
    att = backend.attendance_many(ids, (t - timedelta(days=max(att_days, 56))).isoformat())
    mine = set(ids)
    qa_rows = [r for r in backend.qa_coaching() if r["agent_id"] in mine]
    kpi = summary.kpi_overview(all_kpi, as_of, cfg["kpi_metrics"], weeks)
    for m in kpi["metrics"]:
        m["svg"] = line_chart(m["labels"], m["weekly"], unit=m["unit"], ref=m["prior"], ref_label="직전 4주")
    ranked = signal_svc.by_agent(backend, user)
    fu = coaching_svc.followups(backend, user, as_of, cfg.get("followup_days", 3))
    return {
        "cfg": cfg, "as_of": as_of,
        "headcount": summary.headcount(agents, as_of, cfg.get("new_hire_days", 90)),
        "kpi": kpi,
        "teams": summary.team_table(agents, kpi_by, att, qa_rows, labels, as_of, cfg["team_metrics"], att_days),
        "team_cols": [{"key": k, "label": kpi_svc.BY_KEY[k].label, "unit": kpi_svc.BY_KEY[k].unit,
                       "digits": kpi_svc.BY_KEY[k].digits, "better": kpi_svc.BY_KEY[k].better} for k in cfg["team_metrics"]],
        "attendance": summary.attendance_overview(att, as_of, att_days),
        "qa": summary.qa_overview(qa_rows),
        "signals": {"agents": len(ranked), "open": sum(r["open"] for r in ranked), "top": ranked[:5]},
        "followups": {"overdue": len(fu["overdue"]), "soon": len(fu["soon"])},
    }
