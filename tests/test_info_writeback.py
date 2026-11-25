"""웹 수정 → 원본 시트 맨 아래에 줄 더하기 (가짜 시트), 실패해도 저장 유지 + 다시 쓰기, 되돌리면 한 줄 더."""
from app.core.audit import Auditor
from app.core.data.changelog import JsonChangeLog
from app.core.permissions import User
from app.core.sheets import safe_cell
from app.modules.info.services.edits import InfoEditChange
from app.modules.info.services.writeback import InfoSheetWriteBack
from app.modules.info.wiring import change_service
from app.modules.roster.data.sample import RosterSample

MGR = User("manager@example.com", "m", "manager")
HEAD = ["사번", "한글명", "Name", "Tenure", "Tier", "재직정보", "Universal 전\nTier"]


class Reader:
    def values(self, sheet, a1):
        assert a1 == "'INFO 자동화 시트'!A2:BZ2"
        return [HEAD]


class Writer:
    def __init__(self, fail=False):
        self.rows, self.fail = [], fail

    def append(self, sheet, a1, rows):
        if self.fail:
            raise PermissionError("시트에 쓸 권한이 없습니다")
        assert a1 == "'INFO 자동화 시트'!A2"
        self.rows += rows
        return len(rows)


def _svc(backend, writer):
    store = RosterSample(backend.dir)
    wb = InfoSheetWriteBack(Reader(), writer, "S", "INFO 자동화 시트", 2)
    svc = change_service(store, backend, JsonChangeLog(backend.dir), writeback=wb)
    svc.auditor = Auditor([])
    return store, svc


def test_edit_appends_whole_row_in_sheet_order_and_undo_appends_again(backend):
    w = Writer()
    store, svc = _svc(backend, w)
    r = store.agent_info()[0]
    ch = svc.preview(MGR, InfoEditChange.kind, {"cells": [{"emp_id": r["emp_id"], "field": "tier", "value": "R9"}]})
    ch = svc.approve(MGR, ch.change_id)
    assert ch.undo["sheet"]["ok"] and ch.undo["sheet"]["rows"] == 1
    row = w.rows[0]
    assert len(row) == len(HEAD) and row[0] == r["emp_id"] and row[1] == r["name"] and row[3] == "" and row[4] == "R9"
    ch = svc.undo(MGR, ch.change_id)
    assert ch.undo["sheet_revert"]["ok"] and w.rows[1][4] == r["tier"]          # 되돌린 값으로 한 줄 더


def test_sheet_failure_keeps_web_save_then_retry(backend):
    w = Writer(fail=True)
    store, svc = _svc(backend, w)
    r = store.agent_info()[1]
    ch = svc.preview(MGR, InfoEditChange.kind, {"cells": [{"emp_id": r["emp_id"], "field": "tier", "value": "R8"}]})
    ch = svc.approve(MGR, ch.change_id)
    assert ch.undo["sheet"]["ok"] is False and "권한" in ch.undo["sheet"]["error"]
    assert any(e["value"] == "R8" for e in store.info_edits())               # 웹 저장은 됨
    w.fail = False
    ch = svc.retry(MGR, ch.change_id)
    assert ch.undo["sheet"]["ok"] and w.rows[0][4] == "R8"


def test_safe_cell_blocks_formulas():
    assert safe_cell("=IMPORTRANGE(1)") == "'=IMPORTRANGE(1)" and safe_cell("-1") == "'-1" and safe_cell("가") == "가"
    assert safe_cell(None) == ""
