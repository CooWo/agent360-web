"""QA · 코칭 올리기 — 코칭 대시보드 내보내기(zip: dashboard-coaching_dashboard/*.csv) → 상담사별 QA 평균·평가 수·코칭 수.

- 사람 찾기: 내보내기의 영문 이름(Full Name / Agent) ↔ 상담사 목록의 영문 이름(name_en) 또는 이름. 동명이인·못 찾은 이름은 저장하지 않고 미리보기에 보여 준다.
- 코칭 필요 = QA 평균이 기준(screens.json qa_coaching.need_below, 기본 80점) 미만.
- 올리기는 공통 변경 틀(미리보기 → 저장 → 되돌리기). 저장할 때마다 새 묶음(change_id)이 되고, 화면은 가장 최근 묶음을 쓴다.
"""
from __future__ import annotations

import csv
import io
import re
import uuid
import zipfile
from collections import defaultdict
from datetime import datetime, timezone

from app.core.changes import ChangeHandler, ChangeSet
from app.core.errors import InvalidInput
from app.core.permissions import User
from app.core.registry import Registry

NEED_BELOW = 80.0
MAX_ZIP = 5 * 1024 * 1024
MAX_MEMBER = 2 * 1024 * 1024
FILES = {"agent_performance.csv", "coaching_completion_rate.csv", "evaluation_grade_distribution.csv"}
GRADES = {"Bad": "grade_bad", "Needs Improvement": "grade_ni", "Good": "grade_good", "Very Good": "grade_very_good"}


def norm(name: str) -> str:
    return re.sub(r"[^0-9a-z가-힣]", "", (name or "").lower())


def _num(v) -> float | None:
    v = str(v or "").strip().rstrip("%").replace(",", "")
    try:
        return float(v)
    except ValueError:
        return None


def read_zip(data: bytes) -> dict[str, list[list[str]]]:
    """zip → {파일 이름: 칸 격자}. 필요한 csv 만, 크기 제한."""
    if len(data) > MAX_ZIP:
        raise InvalidInput({"file": "파일은 5MB 이하만 올릴 수 있습니다."})
    try:
        z = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        raise InvalidInput({"file": "zip 파일이 아닙니다 (코칭 대시보드에서 내려받은 dashboard-coaching_dashboard.zip)."}) from None
    out = {}
    for info in z.infolist():
        base = info.filename.rsplit("/", 1)[-1]
        if base in FILES and info.file_size <= MAX_MEMBER:
            text = z.read(info).decode("utf-8-sig", errors="replace")
            out[base] = list(csv.reader(io.StringIO(text)))
    if "agent_performance.csv" not in out:
        raise InvalidInput({"file": "agent_performance.csv 가 없습니다. 코칭 대시보드 내보내기 zip 이 맞는지 확인해 주세요."})
    return out


def per_agent(grids: dict[str, list[list[str]]]) -> list[dict]:
    """영문 이름별 한 줄: 평가 수·QA 평균·코칭 수·코치·등급별 평가 수."""
    rows: dict[str, dict] = {}

    def row(name: str) -> dict:
        return rows.setdefault(norm(name), {"full_name": name.strip(), "evaluations": 0, "qa_avg": None,
                                            "coaching_sessions": 0, "coach": "", **{v: 0 for v in GRADES.values()}})

    g = grids["agent_performance.csv"]
    h = [c.strip() for c in g[0]]
    for r in g[1:]:
        d = dict(zip(h, r))
        if not (d.get("Full Name") or "").strip():
            continue
        x = row(d["Full Name"])
        x["evaluations"] = int(_num(d.get("No. of Evaluations")) or 0)
        x["qa_avg"] = _num(d.get("Average QA score"))
    g = grids.get("coaching_completion_rate.csv") or []
    if g:
        h = [c.strip() for c in g[0]]
        for r in g[1:]:
            d = dict(zip(h, r))
            if not (d.get("Agent") or "").strip():      # 코치 합계 줄
                continue
            x = row(d["Agent"])
            x["coaching_sessions"] += int(_num(d.get("No. of Coaching Sessions")) or 0)
            x["coach"] = x["coach"] or (d.get("Coach") or "").strip()
    g = grids.get("evaluation_grade_distribution.csv") or []
    if len(g) > 2:                                          # 1행 등급 이름, 2행 'Agent / No. of Evaluations'
        grades = [c.strip() for c in g[0]]
        for r in g[2:]:
            if len(r) < 2 or not r[1].strip():
                continue
            x = row(r[1])
            for i, gname in enumerate(grades):
                if gname in GRADES and i < len(r):
                    x[GRADES[gname]] = int(_num(r[i]) or 0)
    return sorted(rows.values(), key=lambda x: x["full_name"])


def match(rows: list[dict], agents: list[dict]) -> tuple[list[dict], list[str], list[str]]:
    """→ (상담사 찾은 줄, 못 찾은 이름, 동명이인 이름)."""
    idx: dict[str, list[dict]] = defaultdict(list)
    for a in agents:
        for k in {norm(a.get("name_en") or ""), norm(a.get("name") or "")} - {""}:
            idx[k].append(a)
    found, missing, dup = [], [], []
    for r in rows:
        k = norm(r["full_name"])
        cand = idx.get(k) or idx.get(re.sub(r"\d+$", "", k)) or []
        cand = list({a["agent_id"]: a for a in cand}.values())
        if len(cand) == 1:
            found.append({**r, "agent_id": cand[0]["agent_id"], "name": cand[0].get("name") or r["full_name"]})
        elif cand:
            dup.append(r["full_name"])
        else:
            missing.append(r["full_name"])
    return found, missing, dup


def needs_coaching(row: dict, below: float = NEED_BELOW) -> bool:
    return row.get("qa_avg") is not None and float(row["qa_avg"]) < below


class QaCoachingUpload(ChangeHandler):
    """payload = {"file": 파일 이름, "rows": per_agent() 결과}. 사람 찾기는 미리보기·저장 때마다 다시 한다."""
    kind = "agent360.qa_coaching"
    title = "QA · 코칭 올리기"
    permission = "qa.upload"

    def __init__(self, backend, need_below: float = NEED_BELOW):
        self.backend, self.need_below = backend, need_below

    def _plan(self, user: User, payload: dict):
        rows = payload.get("rows") if isinstance(payload, dict) else None
        if not rows:
            raise InvalidInput({"file": "읽은 상담사가 없습니다."})
        return match(rows, self.backend.list_agents(user.scope))

    def preview(self, user: User, payload: dict) -> tuple[str, list[dict]]:
        found, missing, dup = self._plan(user, payload)
        need = sum(1 for r in found if needs_coaching(r, self.need_below))
        diff = [{"key": r["agent_id"], "name": r["name"], "field": "qa", "label": r["full_name"],
                 "before": "", "after": f"QA {r['qa_avg'] if r['qa_avg'] is not None else '–'} · 평가 {r['evaluations']}"
                                        f" · 코칭 {r['coaching_sessions']}" + (" · 코칭 필요" if needs_coaching(r, self.need_below) else "")}
                for r in found]
        summary = (f"QA·코칭 {len(found)}명 (코칭 필요 {need}명)"
                   + (f" · 못 찾은 이름 {len(missing)}" if missing else "") + (f" · 동명이인 {len(dup)}" if dup else ""))
        return summary, diff

    def apply(self, user: User, change: ChangeSet) -> dict:
        found, _, _ = self._plan(user, change.payload)
        now = datetime.now(timezone.utc).isoformat()
        self.backend.add_qa_coaching([
            {"row_id": "Q" + uuid.uuid4().hex[:12], "change_id": change.change_id, "agent_id": r["agent_id"],
             "full_name": r["full_name"], "evaluations": r["evaluations"], "qa_avg": r["qa_avg"],
             "coaching_sessions": r["coaching_sessions"], "coach": r["coach"],
             **{v: r.get(v, 0) for v in GRADES.values()},
             "source_file": str(change.payload.get("file") or ""), "uploaded_at": now, "uploaded_by": user.email}
            for r in found])
        return {"change_id": change.change_id}

    def revert(self, user: User, change: ChangeSet) -> None:
        self.backend.deactivate_qa_coaching(change.change_id)


def handlers(backend, need_below: float = NEED_BELOW) -> Registry[ChangeHandler]:
    reg: Registry[ChangeHandler] = Registry("상담사 360 변경")
    h = QaCoachingUpload(backend, need_below)
    reg.register(h.kind, h)
    return reg


def latest_by_agent(backend) -> dict[str, dict]:
    return {r["agent_id"]: r for r in backend.qa_coaching()}
