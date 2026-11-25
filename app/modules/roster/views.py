"""팀 구성 화면 데이터 (웹 프레임워크와 무관 — 테스트·미리보기도 같이 씀)."""
from __future__ import annotations

from app.core.changes import PREVIEW, ChangeService
from app.core.errors import PermissionDenied
from app.core.permissions import User
from app.modules.roster.data import RosterStore
from app.modules.roster.services import info as info_svc
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


def info(store: RosterStore, user: User, screens: dict, today: str) -> dict:
    """상담사 INFO (마트). 개인정보가 있어 info.view 권한만."""
    _need(user, "info.view", "상담사 INFO 보기")
    rows = store.agent_info()
    for r in rows:
        r["tenure"] = info_svc.tenure_bucket(r.get("joined", ""), today)
    cols = [(f, info_svc.LABEL[f], info_svc.OWNER[f]) for f in info_svc.FIELDS]
    cols.insert(cols.index(("joined", info_svc.LABEL["joined"], "BA")), ("tenure", "Tenure (계산)", "BA"))
    status = {}
    for r in rows:
        status[r.get("status") or "(빈 값)"] = status.get(r.get("status") or "(빈 값)", 0) + 1
    loads = store.info_loads(1)
    return {"cfg": screens["screens"]["info"], "rows": rows, "cols": cols, "status_counts": status,
            "tls": sorted({r["tl_ldap"] for r in rows if r.get("tl_ldap")}), "load": loads[0] if loads else None,
            "today": today}
