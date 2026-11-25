"""CapacitySample — sample_data/capacity/*.json (로컬·테스트)."""
from __future__ import annotations

import json
from pathlib import Path


class CapacitySample:
    def __init__(self, sample_dir: str | Path):
        d = Path(sample_dir) / "capacity"
        load = lambda n: json.loads((d / f"{n}.json").read_text(encoding="utf-8"))  # noqa: E731
        self._forecast = load("forecast_weekly")
        self._headcount = load("headcount_weekly")
        self._assumptions = load("assumptions")

    @staticmethod
    def _between(rows, since, until):
        return [dict(r) for r in rows if since <= r["week"] <= until]

    def forecast(self, since: str, until: str) -> list[dict]:
        return self._between(self._forecast, since, until)

    def headcount(self, since: str, until: str) -> list[dict]:
        return self._between(self._headcount, since, until)

    def assumptions(self) -> list[dict]:
        return [dict(a) for a in self._assumptions]
