"""대시보드 계산 — 순수 Python (데이터는 인자로 받음). 비율은 항상 Σ분자 / Σ분모 (kpi.py 와 같은 규칙)."""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date, timedelta

from app.modules.agent360.services import kpi as kpi_svc

ABSENCE = ("결근", "지각", "조퇴")
LEAVE = ("연차", "휴가", "휴직")


def headcount(agents: list[dict], as_of: str, new_hire_days: int) -> dict:
    t = date.fromisoformat(as_of)
    new = [a for a in agents if a.get("hire_date") and (t - date.fromisoformat(str(a["hire_date"])[:10])).days <= new_hire_days]
    return {"agents": len(agents), "teams": len({a["team"] for a in agents}), "new_hires": len(new)}


def kpi_overview(rows: list[dict], as_of: str, keys: list[str], weeks: int) -> dict:
    """담당 전체 KPI: 최근 4주 vs 직전 4주, 주차 추이. 목표는 섹터·테뉴어마다 달라 전체에는 쓰지 않는다."""
    cmp_ = kpi_svc.compare(rows, as_of)
    wk = kpi_svc.weekly(rows, as_of, weeks)
    out = []
    for k in keys:
        m = kpi_svc.BY_KEY[k]
        rec, pri = cmp_["recent"][k], cmp_["prior"][k]
        delta = cmp_["delta"][k]
        good = None if delta is None or delta == 0 else ((delta > 0) == (m.better == "up"))
        out.append({"key": k, "label": m.label, "unit": m.unit, "digits": m.digits, "better": m.better,
                    "recent": rec, "prior": pri, "delta": delta, "good": good,
                    "weekly": [w[k] for w in wk], "labels": [w["label"] for w in wk]})
    return {"metrics": out, "responses": cmp_["recent"]["nps_responses"], "assignments": cmp_["recent"]["assignments"]}


def team_table(agents: list[dict], kpi_by_agent: dict[str, list[dict]], att: list[dict], qa_rows: list[dict],
               labels: dict, as_of: str, keys: list[str], att_days: int) -> list[dict]:
    """팀(TL)별 한 줄: 인원 · KPI 최근 4주 · 근태(결근·지각·조퇴) · QA 평균 · 코칭 Rate."""
    team_of = {a["agent_id"]: a["team"] for a in agents}
    since = (date.fromisoformat(as_of) - timedelta(days=att_days)).isoformat()
    by_team: dict[str, dict] = defaultdict(lambda: {"agents": 0, "kpi": [], "att": Counter(), "qa": []})
    for a in agents:
        t = by_team[a["team"]]
        t["agents"] += 1
        t["kpi"] += kpi_by_agent.get(a["agent_id"], [])
    for r in att:
        if r["agent_id"] in team_of and r["date"] >= since:
            by_team[team_of[r["agent_id"]]]["att"][r["status"]] += 1
    for r in qa_rows:
        if r["agent_id"] in team_of:
            by_team[team_of[r["agent_id"]]]["qa"].append(r)
    out = []
    for team, t in by_team.items():
        rec = kpi_svc.compare(t["kpi"], as_of)["recent"]
        ev = sum(r.get("evaluations") or 0 for r in t["qa"])
        co = sum(r.get("coaching_sessions") or 0 for r in t["qa"])
        qa_w = [(r["qa_avg"], r.get("evaluations") or 0) for r in t["qa"] if r.get("qa_avg") is not None]
        qa_avg = sum(v * n for v, n in qa_w) / sum(n for _, n in qa_w) if sum(n for _, n in qa_w) else None
        out.append({"team": team, "label": labels.get(team, team), "agents": t["agents"],
                    **{k: rec[k] for k in keys},
                    **{s: t["att"][s] for s in ABSENCE}, "leave": sum(t["att"][s] for s in LEAVE),
                    "qa_avg": qa_avg, "evaluations": ev, "coaching": co,
                    "coach_rate": (co / ev * 100) if ev else None,
                    "gaps": sum(1 for r in t["qa"] if (r.get("coaching_sessions") or 0) < (r.get("evaluations") or 0))})
    out.sort(key=lambda r: r["label"])
    return out


def attendance_overview(att: list[dict], as_of: str, days: int) -> dict:
    """최근 N일 상태별 칸 수, 주차별 결근·지각·조퇴, 마지막 날(가장 최근 근태일) 현황."""
    since = (date.fromisoformat(as_of) - timedelta(days=days)).isoformat()
    rows = [r for r in att if since <= r["date"] <= as_of]
    total = Counter(r["status"] for r in rows)
    work = sum(v for k, v in total.items() if k not in ("휴무",) + LEAVE)
    weekly: dict[str, Counter] = defaultdict(Counter)
    for r in rows:
        weekly[kpi_svc.week_end(date.fromisoformat(r["date"])).isoformat()][r["status"]] += 1
    last = max((r["date"] for r in rows), default=None)
    day = Counter(r["status"] for r in rows if r["date"] == last) if last else Counter()
    return {"days": days, "count": dict(total), "work_days": work,
            "absence_rate": (sum(total[s] for s in ABSENCE) / work * 100) if work else None,
            "weekly": [{"week_end": k, "label": k[5:], **{s: v[s] for s in ABSENCE + LEAVE}} for k, v in sorted(weekly.items())],
            "last_day": last, "last": dict(day)}


def qa_overview(qa_rows: list[dict]) -> dict:
    ev = sum(r.get("evaluations") or 0 for r in qa_rows)
    co = sum(r.get("coaching_sessions") or 0 for r in qa_rows)
    w = [(r["qa_avg"], r.get("evaluations") or 0) for r in qa_rows if r.get("qa_avg") is not None]
    n = sum(x for _, x in w)
    return {"agents": len(qa_rows), "evaluations": ev, "coaching": co, "rate": (co / ev * 100) if ev else None,
            "qa_avg": (sum(v * x for v, x in w) / n) if n else None,
            "gaps": sum(1 for r in qa_rows if (r.get("coaching_sessions") or 0) < (r.get("evaluations") or 0)),
            "below80": sum(1 for r in qa_rows if r.get("qa_avg") is not None and r["qa_avg"] < 80)}


def briefing_prompt(ctx: dict, alias) -> str:
    """대시보드 AI 브리핑 질문 (팀 이름은 가명)."""
    from app.modules.agent360.services.briefing import MAX_PROMPT, RULES, _n
    h, q, a = ctx["headcount"], ctx["qa"], ctx["attendance"]
    lines = [f"[상담 운영 대시보드 브리핑 요청] 기준일 {ctx['as_of']}. 상담사 {h['agents']}명, 팀 {h['teams']}개, "
             f"최근 {ctx['cfg'].get('new_hire_days', 90)}일 입사 {h['new_hires']}명."]
    lines.append("■ KPI 최근 4주 (직전 4주 대비)")
    for m in ctx["kpi"]["metrics"]:
        lines.append(f"- {m['label']} {_n(m['recent'], m['digits'])}{m['unit']} (직전 {_n(m['prior'], m['digits'])}, "
                     f"{'좋아짐' if m['good'] else ('나빠짐' if m['good'] is False else '변화 없음')})")
    c = a["count"]
    lines.append(f"■ 근태 최근 {a['days']}일: " + ", ".join(f"{k} {c.get(k, 0)}" for k in ("결근", "지각", "조퇴", "연차", "휴가", "휴직", "연장근로"))
                 + (f", 결근·지각·조퇴 비율 {_n(a['absence_rate'])}%" if a["absence_rate"] is not None else ""))
    lines.append(f"■ QA·코칭: QA 평균 {_n(q['qa_avg'])}점, 평가 {q['evaluations']} · 코칭 {q['coaching']} (Rate {_n(q['rate'], 0)}%), "
                 f"코칭 부족 {q['gaps']}명, QA 80점 미만 {q['below80']}명")
    lines.append(f"■ 신호 있는 상담사 {ctx['signals']['agents']}명 (미확인 {ctx['signals']['open']}건), "
                 f"코칭 후속 기한 지남 {ctx['followups']['overdue']}건")
    lines.append("■ 팀별 (NPS · 코칭 Rate · 결근)")
    for t in ctx["teams"][:15]:
        coach = f"코칭 Rate {_n(t['coach_rate'], 0)}%" if t["coach_rate"] is not None else "코칭 자료 없음(QA 파일에 없음)"
        lines.append(f"- {alias('팀', t['label'])} {t['agents']}명: NPS {_n(t.get('nps'))}, {coach}, "
                     f"결근 {t['결근']} 지각 {t['지각']}")
    lines.append("요청: 운영 매니저가 이번 주 먼저 볼 것 3~5줄 (잘 되는 점 1줄, 위험 신호, 팀별로 챙길 곳). " + RULES)
    return "\n".join(lines)[:MAX_PROMPT]
