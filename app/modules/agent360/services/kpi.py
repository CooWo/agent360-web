"""KPI 집계 — 일별 분자·분모 합을 주차(토요일 마감, WBR 과 같은 기준)로 묶어 지표를 계산한다.

지표 정의는 AI BA CHAT(v11-2026 데이터 에이전트) 안내문 5장과 같다. 비율·평균은 항상 SUM(분자) / SUM(분모).
- NPS              = Σ순추천 / Σ응답 × 100                       (final_view_case)
- SPD              = Σ해결 건수 × 8 / (Σ로그인 생산 분 / 60)          (final_view)
- Throughput       = ΣCases_Solved_Volume / Σ처리(assignments)   (final_view_case)
- Reopen           = Σ재오픈 / Σ해결(case_solves)
- Time to Response = Σ첫 응답 분(메시지 인바운드) / Σ메시지 인바운드 세션
- Work time        = Σ작업 초 / 60 / Σ처리,  Handle time = Σ핸들 초 / 60 / Σ처리
새 지표 = METRICS 에 Metric 하나 등록 (계산 코드는 그대로).
"""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date, timedelta

RAMPING = "Ramping"


@dataclass(frozen=True)
class Metric:
    key: str
    label: str
    unit: str
    num: str                      # 분자 열
    den: str                      # 분모 열
    scale: float = 1.0            # 값 = Σnum / Σden × scale
    better: str = "up"            # up | down
    digits: int = 1
    target: str | None = None     # 목표값 열 (v11 final_view 의 섹터·테뉴어별 목표)
    target_scale: float = 1.0
    help: str = ""

    def value(self, sums: dict) -> float | None:
        d = sums.get(self.den) or 0
        return (sums.get(self.num) or 0) / d * self.scale if d else None


METRICS: tuple[Metric, ...] = (
    Metric("nps", "NPS", "점", "nps_net", "nps_responses", 100, help="순추천 / 응답 × 100"),
    Metric("spd", "SPD", "건", "cases_solved", "logged_min", 480, digits=2, target="target_spd",
           help="해결 건수 × 8 / 로그인 생산 시간(시간)"),
    Metric("throughput", "Throughput", "%", "solved_volume", "assignments", 100, target="target_throughput",
           target_scale=100, help="해결 / 처리 건수"),
    Metric("reopen", "Reopen", "%", "reopens", "case_solves", 100, better="down", target="target_reopen",
           target_scale=100, help="재오픈 / 해결 건수"),
    Metric("ttresp", "Time to Response", "분", "ttresp_min", "msg_sessions", better="down", digits=2,
           target="target_ttresp", help="메시지 인바운드 첫 응답까지 평균 분"),
    Metric("work_time", "Work time", "분", "work_sec", "assignments", 1 / 60, better="down", digits=2,
           target="target_worktime", help="처리 1건당 작업 시간"),
    Metric("handle_time", "Handle time", "분", "handle_sec", "assignments", 1 / 60, better="down", digits=2,
           help="처리 1건당 상담(세션) 시간"),
)
BY_KEY = {m.key: m for m in METRICS}
SUM_FIELDS = tuple(sorted({f for m in METRICS for f in (m.num, m.den)}))


def week_end(d: date) -> date:
    return d + timedelta(days=(5 - d.weekday()) % 7)


def _agg(rows: list[dict]) -> dict:
    sums = {f: sum(r.get(f) or 0 for r in rows) for f in SUM_FIELDS}
    out: dict = {m.key: m.value(sums) for m in METRICS}
    for m in METRICS:
        if m.target:
            ts = [r[m.target] for r in rows if r.get(m.target) is not None]
            out[f"{m.key}_target"] = ts[-1] * m.target_scale if ts else None
    out.update({"days": len(rows), "nps_responses": sums["nps_responses"], "assignments": sums["assignments"],
                "ramping": any(r.get("tenure_group") == RAMPING for r in rows),
                "tenure_group": next((r.get("tenure_group") for r in reversed(rows) if r.get("tenure_group")), None)})
    return out


def weekly(rows: list[dict], as_of: str, weeks: int) -> list[dict]:
    """최근 weeks 개 주차 (as_of 전날이 속한 주까지, 그 주가 아직 안 끝났으면 partial=True)."""
    end = week_end(date.fromisoformat(as_of) - timedelta(days=1))
    buckets = defaultdict(list)
    for r in sorted(rows, key=lambda r: r["date"]):
        buckets[week_end(date.fromisoformat(r["date"]))].append(r)
    out = []
    for k in range(weeks - 1, -1, -1):
        we = end - timedelta(days=7 * k)
        out.append({"week_end": we.isoformat(), "label": we.strftime("%m-%d"),
                    "partial": we >= date.fromisoformat(as_of), **_agg(buckets.get(we, []))})
    return out


ATT_SHOW = ("결근", "지각", "조퇴", "연차", "휴가", "휴직", "연장근로")


def scorecard(kpi_rows: list[dict], att_rows: list[dict], as_of: str, keys: list[str], weeks: int = 6) -> dict:
    """코칭 스코어카드 — 끝난 주 weeks 개 + 러닝 주(아직 안 끝난 이번 주, 데이터가 있을 때만). 근태는 주차별 상태 칸 수."""
    wk = weekly(kpi_rows, as_of, weeks + 1)
    running = wk[-1] if wk[-1]["partial"] and wk[-1]["days"] else None
    full = (wk[:-1] if wk[-1]["partial"] else wk)[-weeks:]
    att: dict[str, Counter] = defaultdict(Counter)
    for r in att_rows:
        att[week_end(date.fromisoformat(r["date"])).isoformat()][r["status"]] += 1
    cols = full + ([running] if running else [])
    for c in cols:
        c["att"] = [(s, att[c["week_end"]][s]) for s in ATT_SHOW if att[c["week_end"]][s]]
        c["att_days"] = sum(att[c["week_end"]].values())
    rows = []
    for k in keys:
        m = BY_KEY[k]
        target = next((c.get(f"{k}_target") for c in reversed(cols) if c.get(f"{k}_target") is not None), None)
        cells = []
        for c in cols:
            v = c[k]
            rv, rt = (None, None) if (v is None or target is None) else (round(v, m.digits), round(target, m.digits))
            ok = None if rv is None else ((rv >= rt) if m.better == "up" else (rv <= rt))   # 보이는 자릿수로 비교
            cells.append({"v": v, "ok": ok})
        rows.append({"key": k, "label": m.label, "unit": m.unit, "digits": m.digits, "target": target, "cells": cells})
    return {"cols": cols, "rows": rows, "running": running is not None}


def compare(rows: list[dict], as_of: str, recent_days: int = 28, prior_days: int = 28) -> dict:
    """최근 N일 vs 직전 N일 비교 (요약 카드용)."""
    t = date.fromisoformat(as_of)
    rows = sorted(rows, key=lambda r: r["date"])
    rec = [r for r in rows if 0 < (t - date.fromisoformat(r["date"])).days <= recent_days]
    pri = [r for r in rows if recent_days < (t - date.fromisoformat(r["date"])).days <= recent_days + prior_days]
    a, b = _agg(rec), _agg(pri)
    delta = {m.key: (a[m.key] - b[m.key]) if (a[m.key] is not None and b[m.key] is not None) else None for m in METRICS}
    return {"recent": a, "prior": b, "delta": delta}


def attendance_summary(rows: list[dict], as_of: str, days: int) -> dict:
    t = date.fromisoformat(as_of)
    recent = sorted([r for r in rows if 0 < (t - date.fromisoformat(r["date"])).days <= days], key=lambda r: r["date"])
    c = Counter(r["status"] for r in recent)
    return {"days": recent, "count": dict(c), "absent": c.get("결근", 0), "late": c.get("지각", 0), "leave": c.get("연차", 0),
            "early": c.get("조퇴", 0), "off_leave": c.get("휴가", 0) + c.get("휴직", 0)}
