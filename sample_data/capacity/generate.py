"""Capacity 샘플 데이터 만들기 (실제 개인정보 없음, 숫자는 가짜).

python sample_data/capacity/generate.py → 같은 폴더의 *.json
주 = 토요일 마감 (00-분석.md 설계 결정 2). 기준일 meta.json as_of(2026-11-20) 이 든 주 = 2026-11-21.
"""
from __future__ import annotations

import json
import math
import random
from datetime import date, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
CUR_WEEK = date(2026, 11, 21)
PAST, AHEAD = 8, 12
random.seed(360)

# 채널별 기준값 — 확인 필요 Q6 의 임시 가정
ASSUMPTIONS = [
    {"channel": "Voice", "work_hours_week": 40.0, "occupancy": 0.85, "shrinkage": 0.30,
     "nesting_productivity": 0.5, "sl_target": "80/20", "source": "임시 가정 (Q1·Q6)"},
    {"channel": "Async", "work_hours_week": 40.0, "occupancy": 0.90, "shrinkage": 0.28,
     "nesting_productivity": 0.5, "sl_target": "-", "source": "임시 가정 (Q1·Q6)"},
]
BASE = {"Voice": (9000, 540, 62), "Async": (14000, 300, 36)}  # 주간 물량, AHT(초), 현업 인원


def main():
    forecast, headcount = [], []
    for i in range(-PAST, AHEAD):
        wk = (CUR_WEEK + timedelta(weeks=i)).isoformat()
        season = 1 + 0.12 * math.sin((i + 4) / 26 * 2 * math.pi)  # 연말로 갈수록 물량 증가
        for ch, (vol, aht, hc) in BASE.items():
            forecast.append({"week": wk, "channel": ch, "volume": round(vol * season * random.uniform(0.97, 1.03)),
                             "aht_sec": round(aht * random.uniform(0.98, 1.02)),
                             "kind": "actual" if i < 0 else "forecast"})
            lost = max(0, i) // 3  # 앞으로 3주마다 1명 이탈 가정
            nesting = 6 if 2 <= i <= 5 else 0  # 기수 1개가 W+2~W+5 네스팅
            headcount.append({"week": wk, "channel": ch, "hc_production": hc - lost + (6 if i > 5 else 0),
                              "hc_nesting": nesting if ch == "Voice" else 0})
    for name, rows in {"forecast_weekly": forecast, "headcount_weekly": headcount, "assumptions": ASSUMPTIONS}.items():
        (HERE / f"{name}.json").write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    print("만듦:", len(forecast), len(headcount))


if __name__ == "__main__":
    main()
