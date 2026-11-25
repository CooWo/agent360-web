"""INFO 자동화 시트 → BigQuery (info_raw 쌓기 → 정리 → mart_agent_info).

    python scripts/info_sync.py --project v12-2027 --dry-run   # 읽고 정리 결과만 보기 (저장 안 함)
    python scripts/info_sync.py --project v12-2027             # 저장

시트 읽기 권한: 개인 로그인(ADC)은 Google 이 시트 권한을 막으므로, 보통은 웹 '상담사 INFO' 의
'시트에서 불러오기' 버튼(서버의 서비스 계정이 읽음)을 쓴다. 이 스크립트는 서비스 계정 자격으로 실행할 때 쓴다.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.core.sheets import GoogleSheetReader, SheetAccessError  # noqa: E402
from app.modules.roster.data.info_loader import InfoMartLoader, LoadRefused  # noqa: E402
from app.modules.roster.services.info_sync import InfoSyncService  # noqa: E402

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

    loader = None if a.dry_run else InfoMartLoader(a.project, a.location, a.dataset)
    try:
        out = InfoSyncService(GoogleSheetReader(), loader).run(a.sheet, a.tab, a.by, a.header_row, a.dry_run, a.force)
    except (SheetAccessError, LoadRefused, ValueError) as e:
        sys.exit(f"❌ {e}")
    print(f"읽은 행 {out['rows_read']} → 마트 {out['rows_mart']}명 · 사번 없음 {out['dropped_no_id']} · "
          f"중복 사번 {out['duplicates']} · 확인 필요 칸 {out['issues']}")
    print("재직정보:", out["status"])
    for i in out["issue_samples"]:
        print(f"  ⚠ {i['emp_id']} {i['text']}: {i['value']!r}")
    print("\n(--dry-run: 저장하지 않음)" if a.dry_run else f"\n✅ 저장 완료 load_id={out['load_id']}")


if __name__ == "__main__":
    main()
