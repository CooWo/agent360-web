"""필요·가용 FTE 와 갭 — 순수 Python.

계산식은 전략 객체로 바꿔 끼운다 (C-05 에서 WFM 엑셀 계산식을 새 Formula 로 등록하고 screens.json 의
"formula" 만 바꾸면 된다). FtePlanner 는 계산식을 주입받아 주·채널 표를 만든다.

임시 계산식 "workload" (00-분석.md 확인 필요 Q1):
  필요 FTE = 물량 × AHT(시간) ÷ (주당 근무시간 × 점유율) ÷ (1 − Shrinkage)
  가용 FTE = 현업 인원 + 네스팅 인원 × 네스팅 생산성
  갭      = 가용 − 필요   (음수 = 부족)
"""
from __future__ import annotations

from typing import Protocol

from app.core.errors import InvalidInput, PermissionDenied
from app.core.permissions import User
from app.core.registry import Registry


# ── 가정 검증 (계산식·변경 처리기가 같이 씀) ─────────────
class AssumptionRules:
    NUMERIC = ("work_hours_week", "occupancy", "shrinkage", "nesting_productivity")
    LABEL = {"work_hours_week": "주당 근무시간", "occupancy": "점유율", "shrinkage": "Shrinkage",
             "nesting_productivity": "네스팅 생산성"}

    @staticmethod
    def errors(a: dict) -> dict[str, str]:
        errs = {}
        if not a.get("work_hours_week", 0) > 0:
            errs["work_hours_week"] = "주당 근무시간은 0보다 커야 합니다."
        if not 0 < a.get("occupancy", 0) <= 1:
            errs["occupancy"] = "점유율은 0 초과 1 이하입니다."
        if not 0 <= a.get("shrinkage", -1) < 1:
            errs["shrinkage"] = "Shrinkage 는 0 이상 1 미만입니다."
        if not 0 <= a.get("nesting_productivity", 0) <= 1:
            errs["nesting_productivity"] = "네스팅 생산성은 0 이상 1 이하입니다."
        return errs

    @classmethod
    def validate(cls, a: dict) -> None:
        errs = cls.errors(a)
        if errs:
            raise InvalidInput(errs)


# ── 계산식 (전략) ──────────────────────────────────
class RequiredFteFormula(Protocol):
    def required(self, volume: float, aht_sec: float, a: dict) -> float: ...


class AvailableFteFormula(Protocol):
    def available(self, hc_production: float, hc_nesting: float, a: dict) -> float: ...


class WorkloadFormula:
    """물량 × AHT 업무량 방식."""

    def required(self, volume: float, aht_sec: float, a: dict) -> float:
        AssumptionRules.validate(a)
        hours = volume * aht_sec / 3600
        return hours / (a["work_hours_week"] * a["occupancy"]) / (1 - a["shrinkage"])


class NestingWeighted:
    """현업 + 네스팅 × 생산성."""

    def available(self, hc_production: float, hc_nesting: float, a: dict) -> float:
        return hc_production + hc_nesting * a.get("nesting_productivity", 0)


FORMULAS: Registry = Registry("필요 FTE 계산식")
FORMULAS.register("workload", WorkloadFormula)


# ── 계획표 ──────────────────────────────────────────
class FtePlanner:
    def __init__(self, required: RequiredFteFormula | None = None, available: AvailableFteFormula | None = None):
        self.req = required or WorkloadFormula()
        self.avail = available or NestingWeighted()

    @classmethod
    def from_config(cls, cfg: dict) -> "FtePlanner":
        return cls(required=FORMULAS.create(cfg.get("formula", "workload")))

    def weekly(self, forecast: list[dict], headcount: list[dict], assumptions: list[dict]) -> list[dict]:
        """주·채널별 필요/가용/갭. 인원 데이터가 없는 주는 가용 None."""
        by_ch = {a["channel"]: a for a in assumptions}
        hc = {(h["week"], h["channel"]): h for h in headcount}
        out = []
        for f in sorted(forecast, key=lambda r: (r["week"], r["channel"])):
            a = by_ch.get(f["channel"])
            if a is None:
                continue
            req = self.req.required(f["volume"], f["aht_sec"], a)
            h = hc.get((f["week"], f["channel"]))
            avail = self.avail.available(h["hc_production"], h["hc_nesting"], a) if h else None
            gap = None if avail is None else avail - req
            out.append({"week": f["week"], "channel": f["channel"], "kind": f.get("kind", "forecast"),
                        "required": req, "available": avail, "gap": gap,
                        "gap_pct": None if gap is None or req == 0 else gap / req * 100})
        return out

    @staticmethod
    def total_by_week(rows: list[dict]) -> list[dict]:
        """채널 합계 (주 단위). 한 채널이라도 인원이 비면 그 주 가용·갭은 None."""
        acc: dict[str, dict] = {}
        for r in rows:
            t = acc.setdefault(r["week"], {"week": r["week"], "kind": r["kind"], "required": 0.0, "available": 0.0})
            t["required"] += r["required"]
            t["available"] = None if (t["available"] is None or r["available"] is None) else t["available"] + r["available"]
        out = sorted(acc.values(), key=lambda t: t["week"])
        for t in out:
            t["gap"] = None if t["available"] is None else t["available"] - t["required"]
            t["gap_pct"] = None if t["gap"] is None or not t["required"] else t["gap"] / t["required"] * 100
        return out

    @staticmethod
    def first_shortage(totals: list[dict], from_week: str, warn_pct: float) -> dict | None:
        """from_week 이후 처음으로 갭 비율이 warn_pct(%) 보다 나빠지는 주."""
        return next((t for t in totals if t["week"] >= from_week and t["gap_pct"] is not None
                     and t["gap_pct"] < warn_pct), None)


# ── 화면 권한 ───────────────────────────────────────
def check_view(user: User, screen: dict) -> None:
    """screens.json 화면의 roles 로 판단 (설정으로 조정)."""
    if user.role not in screen.get("roles", []):
        raise PermissionDenied("이 Capacity 화면을 볼 권한이 없습니다.")


# ── 함수형 호출 (기본 계산식) ─────────────────────────
_default = FtePlanner()
validate = AssumptionRules.validate


def required_fte(volume: float, aht_sec: float, a: dict) -> float:
    return _default.req.required(volume, aht_sec, a)


def available_fte(hc_production: float, hc_nesting: float, a: dict) -> float:
    return _default.avail.available(hc_production, hc_nesting, a)


weekly = _default.weekly
total_by_week = FtePlanner.total_by_week
first_shortage = FtePlanner.first_shortage
