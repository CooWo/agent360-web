"""INFO 자동화 시트 → BigQuery (info_raw 쌓기 → 정리 → mart_agent_info).

    python scripts/info_sync.py --project v12-2027 --dry-run   # 읽고 정리 결과만 보기 (저장 안 함)
    python scripts/info_sync.py --project v12-2027             # 저장

먼저 시트를 읽을 수 있게 한 번 로그인 (내 PC):
    gcloud auth application-default login --scopes=https://www.googleapis.com/auth/spreadsheets.readonly,https://www.googleapis.com/auth/cloud-platform
"""
from __future__ import annotations

import argparse
import os
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.core.sheets import GoogleSheetReader, SheetAccessError  # noqa: E402
from app.modules.roster.data.info_loader import InfoMartLoader, LoadRefused  # noqa: E402
from app.modules.roster.services.info import InfoCleaner, raw_rows  # noqa: E402

# 원천: INFO 자동화 시트 원본 파일 (Airbnb Standard INFO TABLE 의 같은 탭은 이 파일을 IMPORTRANGE)
SOURCE_SHEET = "1WlX447Bbez4Tl81aq5dTn1Px8b5anui3r4meyin86Lk"
SOURCE_TAB = "INFO 자동화 시트"


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--project", required=True)
    p.add_argument("--location", default="asia-northeast3")
    p.add_argument("--dataset", default=os.environ.get("ROSTER_DATASET", "roster"))
    p.add_argument("--sheet", default=SOURCE_SHEET)
    p.add_argument("--tab", default=SOURCE_TAB)
    p.add_argument("--header-row", type=int, default=2, help="머리글 줄 번호 (1행은 입력 담당 표시)")
    p.add_argument("--by", default=os.environ.get("USERNAME") or os.environ.get("USER") or "info_sync")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--force", action="store_true", help="행 수가 크게 줄어도 저장")
    a = p.parse_args(argv)

    try:
        cells = GoogleSheetReader().values(a.sheet, f"'{a.tab}'!A{a.header_row}:Y")
    except SheetAccessError as e:
        sys.exit(f"❌ {e}")
    if not cells:
        sys.exit("❌ 시트가 비어 있습니다.")
    header, body = cells[0], cells[1:]
    raw = raw_rows(header, body)
    res = InfoCleaner().clean(raw)
    s = res.summary()
    print(f"읽은 행 {s['rows_read']} → 마트 {s['rows_mart']}명 · 사번 없음 {s['dropped_no_id']} · "
          f"중복 사번 {s['duplicates']} · 확인 필요 칸 {s['issues']}")
    print("재직정보:", dict(Counter(r["status"] or "(빈 값)" for r in res.rows)))
    for i in res.issues[:10]:
        print(f"  ⚠ {i['emp_id']} {i['text']}: {i['value']!r}")
    if a.dry_run:
        print("\n(--dry-run: 저장하지 않음)")
        return
    try:
        load_id = InfoMartLoader(a.project, a.location, a.dataset).save(
            raw, body, res, source=f"{a.sheet}/{a.tab}", by=a.by, force=a.force)
    except LoadRefused as e:
        sys.exit(f"❌ {e}")
    print(f"\n✅ 저장 완료 load_id={load_id} → {a.project}.{a.dataset}.mart_agent_info")


if __name__ == "__main__":
    main()
