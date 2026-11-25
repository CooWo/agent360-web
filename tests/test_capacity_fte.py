"""Capacity 계산 — 손으로 검산한 예제."""
import pytest

from app.core.errors import InvalidInput
from app.modules.capacity.services import fte
from app.modules.capacity.views import week_end

A = {"channel": "Voice", "work_hours_week": 40, "occupancy": 0.85, "shrinkage": 0.30, "nesting_productivity": 0.5}


def test_required_fte_hand_checked():
    # 10,000건 × 600초 = 1,666.67시간 ÷ (40 × 0.85 = 34) = 49.02 ÷ 0.7 = 70.03
    assert fte.required_fte(10_000, 600, A) == pytest.approx(70.028, abs=0.001)


def test_available_fte_counts_nesting_at_productivity():
    assert fte.available_fte(60, 6, A) == 63  # 60 + 6 × 0.5


def test_weekly_and_totals():
    fc = [{"week": "2026-11-21", "channel": "Voice", "volume": 10_000, "aht_sec": 600, "kind": "forecast"},
          {"week": "2026-11-21", "channel": "Async", "volume": 3_400, "aht_sec": 3600, "kind": "forecast"}]
    async_a = {**A, "channel": "Async", "occupancy": 1.0, "shrinkage": 0.0}  # 3,400시간 ÷ 40 = 85.0
    hc = [{"week": "2026-11-21", "channel": "Voice", "hc_production": 60, "hc_nesting": 6},
          {"week": "2026-11-21", "channel": "Async", "hc_production": 90, "hc_nesting": 0}]
    rows = fte.weekly(fc, hc, [A, async_a])
    voice = next(r for r in rows if r["channel"] == "Voice")
    assert voice["gap"] == pytest.approx(63 - 70.028, abs=0.001)
    t = fte.total_by_week(rows)[0]
    assert t["required"] == pytest.approx(155.028, abs=0.001)
    assert t["available"] == 153
    assert t["gap_pct"] == pytest.approx(-2.028 / 155.028 * 100, abs=0.001)


def test_missing_headcount_gives_none():
    rows = fte.weekly([{"week": "2026-11-28", "channel": "Voice", "volume": 1, "aht_sec": 1}], [], [A])
    assert rows[0]["available"] is None and fte.total_by_week(rows)[0]["gap"] is None


def test_first_shortage():
    totals = [{"week": "2026-11-14", "gap_pct": -20}, {"week": "2026-11-21", "gap_pct": -3},
              {"week": "2026-11-28", "gap_pct": -6}]
    assert fte.first_shortage(totals, "2026-11-21", -5)["week"] == "2026-11-28"
    assert fte.first_shortage(totals, "2026-11-21", -10) is None


@pytest.mark.parametrize("bad", [{"shrinkage": 1.0}, {"occupancy": 0}, {"work_hours_week": 0}])
def test_invalid_assumptions(bad):
    with pytest.raises(InvalidInput):
        fte.required_fte(100, 100, {**A, **bad})


def test_week_end_is_saturday():
    assert week_end("2026-11-20") == "2026-11-21"  # 금 → 토
    assert week_end("2026-11-21") == "2026-11-21"  # 토
    assert week_end("2026-11-22") == "2026-11-28"  # 일 → 다음 토
