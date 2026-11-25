"""QA · 코칭 올리기 — 코칭 대시보드 zip 읽기, 영문 이름으로 찾기, 코칭 필요(기준 미만), 미리보기→저장→되돌리기."""
import io
import zipfile

import pytest

from app.core.audit import Auditor
from app.core.data.changelog import JsonChangeLog
from app.core.errors import InvalidInput, PermissionDenied
from app.core.modules import discover
from app.core.permissions import User
from app.modules.agent360 import views
from app.modules.agent360.services import qa_coaching as qa
from app.modules.agent360.wiring import change_service

MGR = User("manager@example.com", "m", "manager")


def make_zip(names=("윤채원", "정현우", "없는사람")) -> bytes:
    a, b, c = names
    files = {
        "agent_performance.csv": f"Full Name,No. of Evaluations,Average QA score\n{a},4,72.5\n{b},2,95\n{c},1,10\n",
        "coaching_completion_rate.csv": (",Coach,Agent,No. of Coaching Sessions,No. of Evaluations,Percentage\n"
                                         f"1,김코치,,5,6,83%\n2,김코치,{a},3,4,75%\n3,박코치,{b},2,2,100%\n"),
        "evaluation_grade_distribution.csv": (",Result Grade,Bad,Good,Needs Improvement,Very Good\n"
                                              ",Agent,No. of Evaluations,No. of Evaluations,No. of Evaluations,No. of Evaluations\n"
                                              f"1,{a},1,2,1,\n2,{b},,,,2\n"),
        "evil.py": "print('x')",
    }
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for n, t in files.items():
            z.writestr(f"dashboard-coaching_dashboard/{n}", t)
    return buf.getvalue()


def test_per_agent_reads_three_csvs():
    rows = {r["full_name"]: r for r in qa.per_agent(qa.read_zip(make_zip()))}
    r = rows["윤채원"]
    assert (r["evaluations"], r["qa_avg"], r["coaching_sessions"], r["coach"]) == (4, 72.5, 3, "김코치")
    assert (r["grade_bad"], r["grade_good"], r["grade_ni"], r["grade_very_good"]) == (1, 2, 1, 0)
    assert rows["정현우"]["grade_very_good"] == 2 and "김코치" not in rows          # 코치 합계 줄은 사람 아님
    assert qa.needs_coaching(r) and not qa.needs_coaching(rows["정현우"]) and not qa.needs_coaching({"qa_avg": None})


def test_read_zip_rejects_bad_files():
    with pytest.raises(InvalidInput):
        qa.read_zip(b"not a zip")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("x.csv", "a")
    with pytest.raises(InvalidInput):
        qa.read_zip(buf.getvalue())


def test_match_english_name_digits_and_duplicates():
    agents = [{"agent_id": "1", "name": "김지수", "name_en": "Jisu Kim"}, {"agent_id": "2", "name": "이지수", "name_en": "Jisu Lee"},
              {"agent_id": "3", "name": "이지수", "name_en": "Jisu Lee"}, {"agent_id": "4", "name": "김현정", "name_en": "Hyunjeong Kim"}]
    rows = [{"full_name": n} for n in ("Jisu Kim", "jisu  KIM", "Jisu Lee", "Hyunjeong Kim3", "Nobody")]
    found, missing, dup = qa.match(rows, agents)
    assert [f["agent_id"] for f in found] == ["1", "1", "4"] and missing == ["Nobody"] and dup == ["Jisu Lee"]


def test_preview_save_undo_and_view(backend):
    svc = change_service(backend, JsonChangeLog(backend.dir))
    svc.auditor = Auditor([])
    rows = qa.per_agent(qa.read_zip(make_zip()))
    ch = svc.preview(MGR, qa.QaCoachingUpload.kind, {"file": "z.zip", "rows": rows})
    assert "QA·코칭 2명 (코칭 필요 1명)" in ch.summary and "못 찾은 이름 1" in ch.summary
    assert backend.qa_coaching() == []                                   # 미리보기는 저장 안 함
    svc.approve(MGR, ch.change_id)
    assert {r["full_name"] for r in backend.qa_coaching()} == {"윤채원", "정현우"}
    screens = next(m for m in discover() if m.name == "agent360").screens
    v = views.qa(backend, MGR, screens, svc)
    assert v["total"]["people"] == 2 and [r["name"] for r in v["need"]] == ["윤채원"]
    assert v["total"]["qa_avg"] == pytest.approx((72.5 * 4 + 95 * 2) / 6)   # 평가 건수 가중
    assert v["latest_applied"] == ch.change_id
    svc.undo(MGR, ch.change_id)
    assert backend.qa_coaching() == []
    with pytest.raises(PermissionDenied):
        svc.preview(User("v@example.com", "v", "viewer"), qa.QaCoachingUpload.kind, {"file": "z", "rows": rows})
