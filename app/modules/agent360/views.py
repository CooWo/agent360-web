"""화면별 데이터(context) 만들기 — 화면 하나 = 함수 하나.

pages.py(웹)와 scripts/preview.py(미리보기), tests 가 같은 함수를 쓴다.
화면 구성값(몇 주, 몇 명, 어떤 섹션)은 screens.json 에서 읽는다 → 코드 수정 없이 조정.
"""
from __future__ import annotations

from datetime import date, timedelta

from app.core.audit import audit
from app.core.charts import line_chart, sparkline
from app.core.errors import NotFound, PermissionDenied
from app.core.permissions import User
from app.modules.agent360.services import coaching as coaching_svc
from app.modules.agent360.services import kpi as kpi_svc
from app.modules.agent360.services import signals as signal_svc


def _team_labels(backend) -> dict:
    return {t["team"]: t["label"] for t in backend.list_teams()}


def home(backend, user: User, screens: dict) -> dict:
    cfg = screens["screens"]["home"]
    as_of = backend.as_of()
    ranked = signal_svc.by_agent(backend, user)
    fu = coaching_svc.followups(backend, user, as_of, cfg.get("followup_days", 3))
    names = {a["agent_id"]: a["name"] for a in backend.list_agents(user.scope)}
    total_agents = len(names)
    return {
        "cfg": cfg, "as_of": as_of, "ranked": ranked[: cfg.get("top_n", 10)], "ranked_total": len(ranked),
        "gaps": coaching_gaps(backend, user),
        "total_agents": total_agents, "followups": fu, "names": names, "teams": _team_labels(backend),
        "statuses": signal_svc.STATUSES, "can_write": user.can_write,
    }


def coaching_gaps(backend, user: User) -> list[dict]:
    """오늘 볼 상담사 — 올린 QA·코칭에서 코칭 부족(코칭 < 평가) 인원 전부, Rate 낮은 순. 내 범위만."""
    from app.modules.agent360.services import qa_coaching as qa_svc
    agents = {a["agent_id"]: a for a in backend.list_agents(user.scope)}
    labels = _team_labels(backend)
    rows = [{**r, "name": agents[r["agent_id"]]["name"],
             "team": labels.get(agents[r["agent_id"]]["team"], agents[r["agent_id"]]["team"])}
            for r in backend.qa_coaching() if r["agent_id"] in agents]
    return qa_svc.coaching_gaps(rows)


def agents(backend, user: User, screens: dict, q: str | None = None, team: str | None = None) -> dict:
    cfg = screens["screens"]["agents"]
    as_of = backend.as_of()
    since = (date.fromisoformat(as_of) - timedelta(days=56)).isoformat()
    rows = backend.list_agents(user.scope, q=q, team=team)
    score = {x["agent"]["agent_id"]: x["score"] for x in signal_svc.by_agent(backend, user)}
    last_coach = {}
    for c in backend.coaching(user.scope):
        last_coach.setdefault(c["agent_id"], c["date"])
    out = []
    kpi_by = backend.kpi_daily_many([a["agent_id"] for a in rows], since)
    for a in rows:
        wk = kpi_svc.weekly(kpi_by.get(a["agent_id"], []), as_of, 8)
        out.append({**a, "score": score.get(a["agent_id"], 0), "last_coaching": last_coach.get(a["agent_id"]),
                    "spark": sparkline([w[cfg.get("spark_metric", "nps")] for w in wk]),
                    "recent": _last_full(wk)})
    teams = [t for t in backend.list_teams() if user.scope.allows(t["team"])]
    return {"cfg": cfg, "as_of": as_of, "rows": out, "q": q or "", "team": team or "", "teams": teams,
            "team_labels": _team_labels(backend)}


def _last_full(wk: list[dict]) -> dict:
    """지난 (끝난) 주 값 — 목록 화면용."""
    done = [w for w in wk if not w["partial"]]
    return done[-1] if done else {}


def kpi_charts(wk: list[dict], cmp_: dict, keys: list[str]) -> list[dict]:
    """지표 카드·추이 차트. 기준선 = 목표값(있으면) 아니면 직전 4주."""
    out = []
    for key in keys:
        m = kpi_svc.BY_KEY[key]
        target = next((w[f"{key}_target"] for w in reversed(wk) if w.get(f"{key}_target") is not None), None)
        prior = cmp_["prior"][key]
        ref, ref_label = (target, "목표") if target is not None else (prior, "직전 4주")
        out.append({"key": key, "label": m.label, "unit": m.unit, "better": m.better, "digits": m.digits, "help": m.help,
                    "svg": line_chart([w["label"] for w in wk], [w[key] for w in wk], unit=m.unit, ref=ref,
                                      ref_label=ref_label if ref is not None else ""),
                    "recent": cmp_["recent"][key], "prior": prior, "delta": cmp_["delta"][key], "target": target,
                    "vs_target": (cmp_["recent"][key] - target) if (target is not None and cmp_["recent"][key] is not None)
                    else None})
    return out


def _qa_of(backend, screens: dict, agent_id: str) -> dict | None:
    """올린 QA·코칭(가장 최근 묶음)에서 이 상담사 한 줄 + 코칭 필요 여부."""
    from app.modules.agent360.services import qa_coaching as qa_svc
    r = qa_svc.latest_by_agent(backend).get(agent_id)
    if not r:
        return None
    below = float(screens["screens"].get("qa", {}).get("need_below", qa_svc.NEED_BELOW))
    return {**r, "need": qa_svc.needs_coaching(r, below), "need_below": below}


def agent_detail(backend, user: User, screens: dict, agent_id: str) -> dict:
    cfg = screens["screens"]["agent_detail"]
    agent = backend.get_agent(user.scope, agent_id)
    if not agent:
        raise NotFound("상담사를 찾을 수 없거나 열람 권한이 없습니다.")
    as_of = backend.as_of()
    t = date.fromisoformat(as_of)
    weeks = cfg.get("kpi_weeks", 8)
    kpi_rows = backend.kpi_daily(agent_id, (t - timedelta(days=7 * weeks + 35)).isoformat())
    wk = kpi_svc.weekly(kpi_rows, as_of, weeks)
    cmp_ = kpi_svc.compare(kpi_rows, as_of)
    charts = kpi_charts(wk, cmp_, cfg["kpi_metrics"])
    att = kpi_svc.attendance_summary(backend.attendance(agent_id, (t - timedelta(days=40)).isoformat()), as_of,
                                     cfg.get("attendance_days", 30))
    qa_rows = backend.qa(agent_id, (t - timedelta(days=cfg.get("qa_days", 90))).isoformat())
    sigs = [s for s in backend.signals(user.scope) if s["agent_id"] == agent_id]
    sigs.sort(key=lambda s: signal_svc.SEVERITY_ORDER.get(s["severity"], 9))

    sensitive = user.can_view_sensitive(agent["team"])
    coaching_rows = backend.coaching(user.scope, agent_id=agent_id)
    if sensitive:
        audit(backend, user, "view_sensitive", "agent", agent_id, {"sections": ["coaching", "incentive"]})
    return {
        "cfg": cfg, "as_of": as_of, "agent": agent, "team_label": _team_labels(backend).get(agent["team"], agent["team"]),
        "charts": charts, "weekly": wk, "ramping_weeks": [w["label"] for w in wk if w["ramping"]], "attendance": att, "qa": qa_rows,
        "qa_avg": (sum(q["score"] for q in qa_rows) / len(qa_rows)) if qa_rows else None,
        "qa_upload": _qa_of(backend, screens, agent_id),
        "training": backend.training(agent_id), "signals": sigs, "statuses": signal_svc.STATUSES,
        "sensitive": sensitive, "coaching": coaching_rows if sensitive else [],
        "coaching_count": len(coaching_rows), "last_coaching": coaching_rows[0]["date"] if coaching_rows else None,
        "incentive": backend.incentive(agent_id) if sensitive else [],
        "can_write": user.can_write and sensitive,
    }


def coaching(backend, user: User, screens: dict, agent_id: str | None = None,
             form: dict | None = None, errors: dict | None = None) -> dict:
    if not user.can_write:
        raise PermissionDenied("코칭 기록은 SV·매니저만 사용할 수 있습니다.")
    cfg = screens["screens"]["coaching"]
    as_of = backend.as_of()
    t = date.fromisoformat(as_of)
    choices = [a for a in backend.list_agents(user.scope) if user.can_view_sensitive(a["team"])]
    names = {a["agent_id"]: a["name"] for a in choices}
    default = {"agent_id": agent_id or "", "date": as_of, "issue_type": "", "summary": "", "agreed_action": "",
               "follow_up_date": (t + timedelta(days=cfg.get("default_followup_days", 7))).isoformat(), "raw_note": "",
               "area_detail": "", "desired_outcome": "", "case_number": "", "root_cause": "", "agent_comment": "",
               "agent_ack": ""}
    recent = [c for c in backend.coaching(user.scope) if user.can_view_sensitive(c["team"])][:30]
    return {
        "cfg": cfg, "as_of": as_of, "agents": choices, "names": names,
        "categories": cfg.get("categories") or coaching_svc.CATEGORIES,
        "form": {**default, **(form or {})}, "errors": errors or {},
        "followups": coaching_svc.followups(backend, user, as_of, 7), "recent": recent,
    }


def admin(backend, user: User, screens: dict) -> dict:
    if not user.can("admin"):
        raise PermissionDenied("관리 화면은 관리자만 볼 수 있습니다.")
    return {"rules": backend.signal_rules(), "users": backend.list_users(), "teams": _team_labels(backend),
            "issue_types": backend.issue_types(),
            "categories": screens["screens"]["coaching"].get("categories") or coaching_svc.CATEGORIES}


def qa(backend, user: User, screens: dict, changes=None, change_id: str | None = None) -> dict:
    """QA · 코칭 — 가장 최근에 올린 묶음, 내 범위(팀) 상담사만. 코칭 필요 = QA 평균 기준 미만."""
    from app.core.changes import APPLIED, PREVIEW
    from app.modules.agent360.services import qa_coaching as qa_svc
    cfg = screens["screens"]["qa"]
    below = float(cfg.get("need_below", qa_svc.NEED_BELOW))
    agents = {a["agent_id"]: a for a in backend.list_agents(user.scope)}
    labels = _team_labels(backend)
    rows = []
    for r in backend.qa_coaching():
        a = agents.get(r["agent_id"])
        if a:
            rows.append({**r, "name": a["name"], "team": labels.get(a["team"], a["team"]),
                         "need": qa_svc.needs_coaching(r, below)})
    rows.sort(key=lambda r: (r["qa_avg"] is None, r["qa_avg"] if r["qa_avg"] is not None else 0))
    ev = sum(r["evaluations"] or 0 for r in rows if r["qa_avg"] is not None)
    teams: dict[str, dict] = {}
    for r in rows:
        t = teams.setdefault(r["team"], {"team": r["team"], "people": 0, "evaluations": 0, "coaching": 0, "need": 0,
                                         "_score": 0.0})
        t["people"] += 1
        t["evaluations"] += r["evaluations"] or 0
        t["coaching"] += r["coaching_sessions"] or 0
        t["need"] += r["need"]
        t["_score"] += (r["qa_avg"] or 0) * (r["evaluations"] or 0)
    for t in teams.values():
        t["qa_avg"] = t["_score"] / t["evaluations"] if t["evaluations"] else None
    preview, history, latest = None, [], None
    if changes is not None and user.can("qa.upload"):
        history = changes.history(user, "agent360.qa_coaching", 10)
        applied = [c for c in history if c.status == APPLIED]
        latest = max(applied, key=lambda c: c.applied_at or "").change_id if applied else None
        if change_id:
            preview = next((c for c in history if c.change_id == change_id and c.status == PREVIEW), None)
    up = rows[0] if rows else (backend.qa_coaching() or [None])[0]
    return {"cfg": cfg, "need_below": below, "rows": rows, "need": [r for r in rows if r["need"]],
            "teams": sorted(teams.values(), key=lambda t: -t["need"]),
            "total": {"people": len(rows), "evaluations": sum(r["evaluations"] or 0 for r in rows),
                      "coaching": sum(r["coaching_sessions"] or 0 for r in rows),
                      "qa_avg": (sum((r["qa_avg"] or 0) * (r["evaluations"] or 0) for r in rows) / ev) if ev else None},
            "upload": up, "can_upload": user.can("qa.upload"), "preview": preview, "history": history,
            "latest_applied": latest}
