"""근태 불러오기 예약 실행 — Cloud Run 작업이 Cloud Scheduler 로 1시간마다 실행 (웹 서버와 따로 돈다).

    python -m app.modules.roster.attendance_job                       # 지난달 1일 ~ 오늘, 바뀐 칸만 저장
    python -m app.modules.roster.attendance_job --dry-run             # 읽고 비교만
    python -m app.modules.roster.attendance_job --since 2025-12-28    # 처음 한 번: 과거 전체 채우기

환경 변수는 웹과 같다 (DATA_BACKEND=bigquery, GCP_PROJECT, COMMON_DATASET, ROSTER_DATASET).
시트 위치는 상담사 INFO 설정(screens.json 의 attendance_sheet · attendance_tab)을 같이 쓴다.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date


def attendance_cfg() -> dict:
    from app.core.modules import discover
    cfg = next(m for m in discover() if m.name == "info").screens["screens"]["info"]
    return {"sheet": cfg["attendance_sheet"], "tab": cfg["attendance_tab"]}


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--since", type=date.fromisoformat)
    p.add_argument("--until", type=date.fromisoformat)
    p.add_argument("--by", default="scheduler")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--force", action="store_true", help="지울 칸이 많아도 저장")
    a = p.parse_args(argv)

    from app.core.sheets import GoogleSheetReader, SheetAccessError
    from app.modules.roster.data import get_store
    from app.modules.roster.services.attendance_sync import AttendanceRefused, AttendanceSync

    cfg = attendance_cfg()
    try:
        out = AttendanceSync(GoogleSheetReader(), get_store()).run(
            cfg["sheet"], cfg["tab"], a.by, a.since, a.until, dry_run=a.dry_run, force=a.force)
    except (SheetAccessError, AttendanceRefused, ValueError) as e:
        print(f"❌ {e}", file=sys.stderr)
        return 1
    keep = ("since", "until", "days", "agents", "cells", "by_status", "upserts", "deletes", "stored_before",
            "unknown", "duplicate_ids", "load_id", "dry_run", "refused")
    print(json.dumps({k: out.get(k) for k in keep}, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
