"""팀 구성 화면 데이터 (웹 프레임워크와 무관 — 테스트·미리보기도 같이 씀)."""
from __future__ import annotations

from app.core.changes import PREVIEW, ChangeService
from app.core.errors import PermissionDenied
from app.core.permissions import User
from app.modules.roster.data import RosterStore
from app.modules.roster.services.board import FIELDS, LABEL, BoardRules, by_tl


def _need(user: User, perm: str, what: str) -> None:
    if not user.can(perm):
        raise PermissionDenied(f"{what} 권한이 없습니다.")


def board(store: RosterStore, user: User, screens: dict) -> dict:
    _need(user, "roster.view", "팀 구성 보기")
    cfg = screens["screens"]["board"]
    rows = store.board()
    chk = BoardRules(store.agent_info()).check(rows)
    return {"cfg": cfg, "groups": by_tl(rows), "total": len(rows), "warnings": chk.warnings,
            "versions": store.versions(cfg.get("versions", 10)), "can_edit": user.can("roster.edit")}


def workspace(store: RosterStore, user: User, screens: dict, changes: ChangeService,
              change_id: str | None = None, errors: dict | None = None) -> dict:
    _need(user, "roster.edit", "팀 구성 수정")
    cfg = screens["screens"]["workspace"]
    current = store.board()
    draft = store.draft(user.email)
    rows = sorted(draft["rows"] if draft else current, key=lambda r: r.get("tl") or "")   # TL 끼리 모아 보기
    rules = BoardRules(store.agent_info())
    known = {r["tl"] for r in current}
    norm = rules.normalize(rows)
    preview = None
    if change_id:
        preview = next((c for c in changes.history(user, "roster.board", 50)
                        if c.change_id == change_id and c.status == PREVIEW), None)
    history = changes.history(user, "roster.board", 10)
    applied = [c for c in history if c.status == "applied"]
    return {
        "cfg": cfg, "rows": rows, "fields": [(f, LABEL[f]) for f in FIELDS],
        "tls": sorted({r["tl"] for r in rows if r.get("tl")} | known),
        "draft": draft, "check": rules.check(norm, known), "preview": preview, "errors": errors or {},
        "history": history,
        "latest_applied": max(applied, key=lambda c: c.applied_at or "").change_id if applied else None,
        "counts": {g["tl"]: g["count"] for g in by_tl(norm)},
    }



FIELD_COLS = [("shift", "Shift", "w-shift"), ("emp_id", "사번", "w-id"), ("name", "이름", "w-name"),
              ("e_name", "Name", "w-en"), ("display_name", "Display name", "w-disp")]
EXTRA_ROWS = 3          # 고칠 수 있으면 TL 블록마다 빈 줄을 더 보여 준다 (시트처럼 아래 칸에 써 넣기)


def team_board(store: RosterStore, user: User, screens: dict, changes: ChangeService | None = None,
               change_id: str | None = None, errors: dict | None = None, sheet: dict | None = None) -> dict:
    """TL별 명단 — team_roster(원본 시트 팀구성-New 맨 위 묶음 + 웹 수정)를 시트와 같은 모양(TL 블록이 옆으로)으로."""
    from app.modules.roster.services.team_edit import board_rows, by_tl as group
    _need(user, "roster.view", "팀 구성 보기")
    cfg = screens["screens"]["board"]
    raw = store.team_roster()
    rows = board_rows(raw)
    groups = [{"tl": tl, "rows": rs, "count": len(rs)} for tl, rs in group(rows).items()]
    can_edit = user.can("roster.edit")
    height = max((g["count"] for g in groups), default=0) + (EXTRA_ROWS if can_edit else 0)
    chk = BoardRules(store.agent_info()).check([{**r, "date": "", "note": ""} for r in rows])
    preview, history, latest = None, [], None
    if changes is not None and can_edit:
        history = changes.history(user, "roster.team", 20)
        applied = [c for c in history if c.status == "applied"]
        latest = max(applied, key=lambda c: c.applied_at or "").change_id if applied else None
        if change_id:
            preview = next((c for c in history if c.change_id == change_id and c.status == PREVIEW), None)
    last = max(raw, key=lambda r: r.get("loaded_at") or "", default={}) if raw else {}
    return {"cfg": cfg, "groups": groups, "total": len(rows), "height": height, "cols": FIELD_COLS,
            "warnings": [w for w in chk.warnings if w["kind"] != "new_tl"], "can_edit": can_edit,
            "loaded": {k: last.get(k) for k in ("loaded_at", "loaded_by", "source", "load_id")} if last else None,
            "sheet": sheet or {}, "preview": preview, "history": history, "latest_applied": latest,
            "errors": errors or {}}
