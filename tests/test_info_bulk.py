"""상담사 INFO 한꺼번에 고치기 — 붙여넣기·파일 → 바뀐 칸만, 빈 칸 유지, 권한 없는 열 건너뛰기, 새 사람."""
import io

import pytest

from app.core.errors import InvalidInput
from app.core.permissions import User
from app.core.uploads import parse_grid, text_grid
from app.modules.info.services import bulk

MGR = User("manager@example.com", "m", "manager")      # OPS 열만
WFM = User("wfm@example.com", "w", "wfm")              # WFM·BA 열만

# 시트에서 복사한 모양: 담당 줄 + 머리글(줄바꿈 칸은 따옴표) + 값
PASTE = ('OPS\tOPS\tOPS\tWFM\tBA\n'
         '사번\t한글명\tTier\t"Universal 전\nTier"\t재직정보\t모르는열\n'
         '1001\t가나\tR2\tR1\t퇴직자\tx\n'
         '1002\t\tUS\t\t\t\n'
         '\t\t\t\t\t\n'
         '2001\t새사람\tR1\t\t\t\n'
         '1001\t가나\tR3\t\t\t\n')


def test_text_grid_reads_sheet_copy_with_newline_cell():
    g = text_grid(PASTE)
    assert g[1][3] == "Universal 전\nTier" and g[2][0] == "1001"


def test_plan_paste_manager():
    p = bulk.plan(text_grid(PASTE), {"1001", "1002"}, MGR, "paste")
    cells = {(c["emp_id"], c["field"]): c["value"] for c in p.payload["cells"]}
    # 같은 사번은 뒤 줄이 이김, 빈 칸은 안 바꿈, OPS 아닌 열(Universal 전 Tier·재직정보)은 건너뜀
    assert cells == {("1001", "name"): "가나", ("1001", "tier"): "R3", ("1002", "tier"): "US"}
    assert p.payload["new"] == [{"emp_id": "2001", "name": "새사람", "tier": "R1"}]
    assert p.rows == 4 and p.skipped_cols == ["Universal 전 Tier", "재직정보"] and p.unknown_cols == ["모르는열"]
    assert p.payload["source"]["how"] == "paste"


def test_plan_wfm_only_its_columns():
    p = bulk.plan(text_grid(PASTE), {"1001", "1002"}, WFM, "paste")
    cells = {(c["emp_id"], c["field"]): c["value"] for c in p.payload["cells"]}
    assert cells == {("1001", "tier_before_universal"): "R1", ("1001", "status"): "퇴직자"}
    assert "한글명" in p.skipped_cols and p.payload["new"] == [{"emp_id": "2001"}]   # 이름 권한 없음 → 미리보기에서 막힘


@pytest.mark.parametrize("text", ["", "1001\t가나\n", "이름\t나이\n가\t1\n"])
def test_plan_needs_header(text):
    with pytest.raises(InvalidInput):
        bulk.plan(text_grid(text), set(), MGR, "paste")


def test_parse_grid_csv_and_xlsx():
    assert parse_grid("a.csv", "사번,한글명\n1,가\n".encode("cp949"))[1] == ["1", "가"]
    from datetime import datetime

    from openpyxl import Workbook
    wb = Workbook()
    wb.active.append(["사번", "한글명", "온보딩 날짜"])
    wb.active.append([1001, "가", datetime(2026, 7, 3)])
    buf = io.BytesIO()
    wb.save(buf)
    assert parse_grid("b.XLSX", buf.getvalue())[1] == ["1001", "가", "2026-07-03"]
    for name, data in (("c.pdf", b"x"), ("d.xlsx", b"not a zip"), ("e.csv", b"")):
        with pytest.raises(InvalidInput):
            parse_grid(name, data)
