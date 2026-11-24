"""KPI 집계 — 일별 데이터를 주차(토요일 마감, WBR 과 같은 기준)로 묶는다.

비율·평균은 항상 분자 합 / 분모 합으로 계산한다 (행 평균의 평균 금지).
- 일평균 처리 건수 = 처리 건수 합 / 근무일 수
- AHT              = Σ(AHT × 처리 건수) / Σ처리 건수
- NPS              = Σ순추천 / Σ응답 × 100
"""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date, timedelta


def week_end(d: date) -> date:
    return d + timedelta(days=(5 - d.weekday()) % 7)


def _agg(rows: list[dict]) -> dict:
    if not rows:
        return {"handled": None, "aht_sec": None, "nps": None, "days": 0, "nps_responses": 0}
    h = sum(r["handled"] for r in rows)
    resp = sum(r["nps_responses"] for r in rows)
    return {
        "handled": h / len(rows),
        "aht_sec": (sum(r["aht_sec"] * r["handled"] for r in rows) / h) if h else None,
        "nps": (sum(r["nps_net"] for r in rows) / resp * 100) if resp else None,
        "days": len(rows),
        "nps_responses": resp,
    }


def weekly(rows: list[dict], as_of: str, weeks: int) -> list[dict]:
    """최근 weeks 개 주차 (이번 주 포함, 진행 중이면 partial=True)."""
    end = week_end(date.fromisoformat(as_of) - timedelta(days=1))
    buckets = defaultdict(list)
    for r in rows:
        buckets[week_end(date.fromisoformat(r["date"]))].append(r)
    out = []
    for k in range(weeks - 1, -1, -1):
        we = end - timedelta(days=7 * k)
        out.append({"week_end": we.isoformat(), "label": we.strftime("%m-%d"),
                    "partial": we >= date.fromisoformat(as_of), **_agg(buckets.get(we, []))})
    return out


def compare(rows: list[dict], as_of: str, recent_days: int = 28, prior_days: int = 28) -> dict:
    """최근 N일 vs 직전 N일 비교 (요약 카드용)."""
    t = date.fromisoformat(as_of)
    rec = [r for r in rows if 0 < (t - date.fromisoformat(r["date"])).days <= recent_days]
    pri = [r for r in rows if recent_days < (t - date.fromisoformat(r["date"])).days <= recent_days + prior_days]
    a, b = _agg(rec), _agg(pri)
    delta = {k: (a[k] - b[k]) if (a[k] is not None and b[k] is not None) else None for k in ("handled", "aht_sec", "nps")}
    return {"recent": a, "prior": b, "delta": delta}


def attendance_summary(rows: list[dict], as_of: str, days: int) -> dict:
    t = date.fromisoformat(as_of)
    recent = sorted([r for r in rows if 0 < (t - date.fromisoformat(r["date"])).days <= days], key=lambda r: r["date"])
    c = Counter(r["status"] for r in recent)
    return {"days": recent, "count": dict(c), "absent": c.get("결근", 0), "late": c.get("지각", 0), "leave": c.get("연차", 0)}
