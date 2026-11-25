"""팀 구성(시트 OPS TL) 불러오기 — TL 한글 이름 블록 읽기, 저장, 권한."""
import pytest

from app.core.errors import PermissionDenied
from app.core.modules import discover
from app.core.permissions import User
from app.modules.info import views
from app.modules.roster.data.info_loader import LoadRefused, SampleTeamRosterLoader
from app.modules.roster.data.sample import RosterSample
from app.modules.roster.services.team_sync import TeamRosterSync, roster_from_grid

# 실제 OPS TL 모양: 1행 날짜·체크박스, 2행 TL 이름, 3행 머리글이 TL 마다 반복
GRID = [
    ["2026. 1. 1", "", "", "", "", "", "", "", "", "", "FALSE"],
    ["가팀장", "", "", "", "", "나팀장"],
    ["Shift", "사번", "이름", "Name", "Display name", "Shift", "사번", "이름", "Name", "Display name"],
    ["US", "90000001", "김가나", "Gana Kim", "Ana", "US", "90000003", "박마바", "Maba Park", "Ben"],
    ["US", "90000002", "이다라", "Dara Lee", "Dara", "US", "90000004", "최사아", "Saa Choi", "Cora"],
    ["", "", "", "", "", "KR", "90000002", "이다라", "", ""],          # 두 TL 에 같은 사번 → 왼쪽 TL
    ["육아휴가", "", "", "", "", "", "", "", "", ""],                       # 쉬는 사람 구역 → 빼기
    ["US", "90000009", "휴가자", "", "", "", "", "", "", ""],
    ["11"],
    ["2025. 12. 1"],                                                       # 아래는 예전 팀 구성 (안 읽음)
    ["가팀장 (R2)", "", "", "", "", "나팀장"],
    ["Shift", "사번", "이름", "Name", "Display name", "Shift", "사번", "이름", "Name", "Display name"],
    ["R2", "90000099", "예전사람", "", "", "R2", "90000098", "예전사람2", "", ""],
]
MGR = User("manager@example.com", "m", "manager")


class Reader:
    def values(self, sheet, a1):
        assert a1.startswith("'OPS TL'!")
        return GRID


def test_roster_from_grid():
    rows = roster_from_grid(GRID)
    assert [(r["tl_name"], r["emp_id"], r["name"]) for r in rows] == [
        ("가팀장", "90000001", "김가나"), ("가팀장", "90000002", "이다라"),
        ("나팀장", "90000003", "박마바"), ("나팀장", "90000004", "최사아")]
    assert rows[0]["sort_order"] == 0 and rows[2]["sort_order"] == 1 and rows[0]["display_name"] == "Ana"


def test_team_sync_check_save_and_guard(backend):
    store = RosterSample(backend.dir)
    screens = next(m for m in discover() if m.name == "info").screens
    out = views.team_sync(TeamRosterSync(Reader()), MGR, screens, dry_run=True)
    assert out["rows"] == 4 and [t["tl"] for t in out["tls"]] == ["가팀장", "나팀장"] and not store.team_roster()
    out = views.team_sync(TeamRosterSync(Reader(), SampleTeamRosterLoader(store)), MGR, screens, dry_run=False)
    assert out["load_id"].startswith("T") and len(store.team_roster()) == 4
    small = SampleTeamRosterLoader(store)
    with pytest.raises(LoadRefused):
        small.save(store.team_roster()[:1], "s", "x")
    with pytest.raises(PermissionDenied):
        views.team_sync(TeamRosterSync(Reader()), User("v@example.com", "v", "viewer"), screens, dry_run=True)
