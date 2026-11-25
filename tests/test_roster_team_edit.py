"""TL별 명단 웹 수정 — 팀구성-New 블록 읽기, 원본 시트 쓰기 계획, 미리보기 → 저장 → 되돌리기 (가짜 시트, 가짜 이름)."""
import copy

import pytest

from app.core.audit import Auditor
from app.core.data.changelog import JsonChangeLog
from app.core.errors import InvalidInput
from app.core.permissions import User
from app.core.sheets import SheetAccessError
from app.modules.roster.data.info_loader import SampleTeamRosterLoader
from app.modules.roster.data.sample import RosterSample
from app.modules.roster.services.team_edit import TeamSheetWriteBack, board_rows, col_letter
from app.modules.roster.services.team_sync import roster_from_grid, snapshot_blocks
from app.modules.roster.wiring import team_change_service

H = ["Shift", "사번", "이름", "Name", "Display name"]
# 맨 위 묶음: 1행 날짜, 2행 TL, 3행 머리글, 4~7행 명단 칸, 8행 육아휴가(가팀장 블록만), 9행 인원·Ratio
GRID = [
    ["2026. 12. 7"],
    ["가팀장", "", "", "", "", "나팀장 (R2)"],
    H + H,
    ["US", "90000001", "김가나", "Gana Kim", "Gana", "US", "90000003", "박마바", "Maba Park", "본명"],
    ["US", "90000002", "이다라", "Dara Lee", "Dara", "SWAT", "90000004", "최사아", "Saa Choi", "Saa"],
    ["", "", "", "", "", "", "", "", "", ""],
    ["", "", "", "", "", "", "", "", "", ""],
    ["육아휴가", "90000009", "휴가자", "", "", "", "", "", "", ""],
    ["", "2", "", "", "Ratio: 1:2", "", "2", "", "", "Ratio: 1:2"],
    ["2026. 11. 22"],
    ["가팀장", "", "", "", "", "나팀장"],
    H + H,
    ["US", "90000099", "예전사람", "", "", "", "", "", "", ""],
]
MGR = User("manager@example.com", "m", "manager")


def test_col_letter():
    assert [col_letter(i) for i in (0, 4, 25, 26, 27, 51, 52)] == ["A", "E", "Z", "AA", "AB", "AZ", "BA"]


def test_blocks_stop_at_leave_and_ratio():
    b = snapshot_blocks(GRID)
    assert [x["tl"] for x in b] == ["가팀장", "나팀장"]                        # (R2) 빼기
    assert (b[0]["first"], b[0]["end"]) == (3, 7)                            # 육아휴가 줄(8행) 전까지 → 4줄
    assert (b[1]["first"], b[1]["end"]) == (3, 8)                            # 휴가 표시 없음 → Ratio 줄(9행) 전까지 → 5줄
    assert [m["emp_id"] for m in b[0]["members"]] == ["90000001", "90000002"]
    rows = roster_from_grid(GRID)
    assert [r["emp_id"] for r in rows] == ["90000001", "90000002", "90000003", "90000004"]   # 휴가자·Ratio·예전 묶음 없음
    assert [r["row_order"] for r in rows] == [0, 1, 2, 3]


class Reader:
    def __init__(self, grid):
        self.grid = grid

    def values(self, sheet, a1):
        assert a1.startswith("'팀구성-New'!")
        return self.grid


class Writer:
    def __init__(self, fail=None):
        self.calls, self.fail = [], fail

    def update_many(self, sheet, data):
        if self.fail:
            raise self.fail
        self.calls.append(data)
        return sum(len(v) for _, v in data)


def _before():
    return board_rows(roster_from_grid(GRID))


def test_plan_writes_only_changed_block_columns():
    wb = TeamSheetWriteBack(Reader(GRID), Writer(), "S", "팀구성-New")
    before = _before()
    after = copy.deepcopy(before)
    after.append({**after.pop(1), "tl": "나팀장"})                            # 이다라: 가팀장 → 나팀장 맨 아래 빈 줄
    data = wb.plan(before, after)
    ranges = [r for r, _ in data]
    assert ranges[:5] == ["'팀구성-New'!A4:A7", "'팀구성-New'!B4:B7", "'팀구성-New'!C4:C7",
                          "'팀구성-New'!D4:D7", "'팀구성-New'!E4:E7"]           # 가팀장 블록 4줄 (육아휴가 줄은 안 건드림)
    assert ranges[5:] == ["'팀구성-New'!F4:F8", "'팀구성-New'!G4:G8", "'팀구성-New'!H4:H8",
                          "'팀구성-New'!I4:I8", "'팀구성-New'!J4:J8"]
    assert data[1][1] == [["90000001"], [""], [""], [""]]                     # 가팀장 사번 열: 1명 + 빈 칸
    assert data[6][1] == [["90000003"], ["90000004"], ["90000002"], [""], [""]]


def test_plan_refuses_when_sheet_changed_or_full_or_missing_tl():
    before = _before()
    changed = copy.deepcopy(GRID)
    changed[3][4] = "누가 시트에서 고침"
    after = copy.deepcopy(before)
    after[0]["display_name"] = "New"
    with pytest.raises(ValueError, match="웹과 다릅니다"):
        TeamSheetWriteBack(Reader(changed), Writer(), "S", "팀구성-New").plan(before, after)
    wb = TeamSheetWriteBack(Reader(GRID), Writer(), "S", "팀구성-New")
    full = before + [{"tl": "가팀장", "shift": "US", "emp_id": f"9100000{i}", "name": "", "e_name": "",
                      "display_name": ""} for i in range(3)]                  # 가팀장 칸은 4줄뿐
    with pytest.raises(ValueError, match="4줄뿐"):
        wb.plan(before, full)
    with pytest.raises(ValueError, match="블록이 없습니다"):
        wb.plan(before, before + [{"tl": "새팀장", "shift": "US", "emp_id": "91000009", "name": "", "e_name": "",
                                   "display_name": ""}])


@pytest.fixture
def env(backend):
    store = RosterSample(backend.dir)
    store.replace_team_roster(roster_from_grid(GRID))
    writer = Writer()
    wb = TeamSheetWriteBack(Reader(GRID), writer, "S", "팀구성-New")
    svc = team_change_service(store, backend, JsonChangeLog(backend.dir), writeback=wb,
                              loader=SampleTeamRosterLoader(store))
    svc.auditor = Auditor([])
    return store, svc, wb, writer


def test_preview_save_undo_writes_sheet(env):
    store, svc, wb, writer = env
    rows = board_rows(store.team_roster())
    rows.append({**rows.pop(1), "tl": "나팀장"})
    rows[0]["display_name"] = "가나"
    ch = svc.preview(MGR, "roster.team", {"rows": rows})
    assert "이동 1" in ch.summary and "수정 1" in ch.summary
    assert store.team_roster()[1]["tl_name"] == "가팀장"                      # 미리보기는 저장 안 함
    ch = svc.approve(MGR, ch.change_id)
    assert ch.undo["sheet"]["ok"] and len(writer.calls) == 1
    saved = board_rows(store.team_roster())
    assert [(r["tl"], r["emp_id"]) for r in saved] == [("가팀장", "90000001"), ("나팀장", "90000003"),
                                                        ("나팀장", "90000004"), ("나팀장", "90000002")]
    assert store.team_roster()[0]["source"] == "web"
    # 되돌리기: 시트가 저장한 모양이 됐다고 치고 (가짜 시트에 반영) → 원래대로 다시 씀
    wb.reader = Reader(_apply(GRID, writer.calls[-1]))
    ch = svc.undo(MGR, ch.change_id)
    assert ch.undo["sheet_revert"]["ok"] and len(writer.calls) == 2
    assert board_rows(store.team_roster()) == _before()


def _apply(grid, data):
    """가짜 시트에 쓰기 결과 반영 (A4:A7 같은 한 열 범위만)."""
    import re
    g = copy.deepcopy(grid)
    for rng, vals in data:
        col, r1 = re.match(r"'.*'!([A-Z]+)(\d+):", rng).groups()
        c = sum((ord(ch) - 64) * 26 ** i for i, ch in enumerate(reversed(col))) - 1
        for k, (v,) in enumerate(vals):
            row = g[int(r1) - 1 + k]
            row.extend([""] * (c + 1 - len(row)))
            row[c] = v
    return g


def test_sheet_mismatch_blocks_save_and_access_error_keeps_web(env):
    store, svc, wb, writer = env
    rows = board_rows(store.team_roster())
    rows[0]["display_name"] = "가나"
    changed = copy.deepcopy(GRID)
    changed[3][4] = "시트에서 고침"
    wb.reader = Reader(changed)
    ch = svc.preview(MGR, "roster.team", {"rows": rows})
    with pytest.raises(InvalidInput):
        svc.approve(MGR, ch.change_id)                                       # 시트가 달라졌으면 웹도 저장 안 함
    assert store.team_roster()[0]["display_name"] == "Gana"
    wb.reader = Reader(GRID)
    writer.fail = SheetAccessError("시트에 쓸 권한이 없습니다.")
    ch = svc.preview(MGR, "roster.team", {"rows": rows})
    ch = svc.approve(MGR, ch.change_id)
    assert ch.status == "applied" and not ch.undo["sheet"]["ok"]             # 권한 문제 → 웹은 저장, 실패 기록
    assert board_rows(store.team_roster())[0]["display_name"] == "가나"
    writer.fail = None
    ch = svc.retry(MGR, ch.change_id)                                        # 공유 뒤 다시 쓰기
    assert ch.undo["sheet"]["ok"] and len(writer.calls) == 1


def test_validation(env):
    store, svc, _, _ = env
    rows = board_rows(store.team_roster())
    with pytest.raises(InvalidInput, match="바뀐 칸이 없습니다"):
        svc.preview(MGR, "roster.team", {"rows": rows})
    dup = rows + [{**rows[0], "tl": "나팀장"}]
    with pytest.raises(InvalidInput) as e:
        svc.preview(MGR, "roster.team", {"rows": dup})
    assert "한 사람은 한 TL" in " ".join(e.value.errors.values())
    with pytest.raises(InvalidInput):
        svc.preview(MGR, "roster.team", {"rows": rows + [{"tl": "가팀장", "name": "사번없음"}]})
    with pytest.raises(Exception):
        svc.preview(User("v@example.com", "v", "viewer"), "roster.team", {"rows": rows})
