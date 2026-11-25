"""CapacitySample — sample_data/capacity/*.json (로컬·테스트).

화면에서 바꾼 가정은 sample_data/runtime/capacity_assumptions.json 에 따로 저장 (원본은 그대로).
"""
from __future__ import annotations

import json
import threading
from pathlib import Path


class CapacitySample:
    def __init__(self, sample_dir: str | Path):
        d = Path(sample_dir) / "capacity"
        load = lambda n: json.loads((d / f"{n}.json").read_text(encoding="utf-8"))  # noqa: E731
        self._forecast = load("forecast_weekly")
        self._headcount = load("headcount_weekly")
        self._runtime = Path(sample_dir) / "runtime" / "capacity_assumptions.json"
        self._runtime.parent.mkdir(parents=True, exist_ok=True)
        self._assumptions = (json.loads(self._runtime.read_text(encoding="utf-8")) if self._runtime.exists()
                             else load("assumptions"))
        self._lock = threading.Lock()

    @staticmethod
    def _between(rows, since, until):
        return [dict(r) for r in rows if since <= r["week"] <= until]

    def forecast(self, since: str, until: str) -> list[dict]:
        return self._between(self._forecast, since, until)

    def headcount(self, since: str, until: str) -> list[dict]:
        return self._between(self._headcount, since, until)

    def assumptions(self) -> list[dict]:
        return [dict(a) for a in self._assumptions]

    def save_assumptions(self, rows: list[dict]) -> None:
        with self._lock:
            self._assumptions = [dict(r) for r in rows]
            self._runtime.write_text(json.dumps(self._assumptions, ensure_ascii=False, indent=1), encoding="utf-8")
