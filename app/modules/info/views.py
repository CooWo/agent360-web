"""상담사 INFO 화면 데이터 (웹 프레임워크와 무관 — 테스트·미리보기도 같이 씀)."""
from __future__ import annotations

from app.core.changes import APPLIED, PREVIEW, ChangeService
from app.core.errors import PermissionDenied
from app.core.permissions import User
from app.modules.info.services.edits import can_edit, effective_info
from app.modules.roster.services import info as info_svc


def _need(user: User, perm: str, what: str) -> None:
    if not user.can(perm):
        raise PermissionDenied(f"{what} 권한이 없습니다.")


def info(store, user: User, screens: dict, today: str, changes: ChangeService | None = None,
         change_id: str | None = None) -> dict:
    """INFO 표 (시트 마트 + 웹 수정분). 개인정보가 있어 info.view 권한만."""
    _need(user, "info.view", "상담사 INFO 보기")
    rows = effective_info(store)
    for r in rows:
        r["tenure"] = info_svc.tenure_bucket(r.get("joined", ""), today)
        r["dates_ok"] = "" if str(r.get("dates_ok", True)).lower() in ("true", "1") else "확인 필요"
    cols = [{"f": f, "label": info_svc.LABEL[f], "owner": info_svc.OWNER[f], "edit": can_edit(user, f),
             "date": f in info_svc.DATE_FIELDS} for f in info_svc.FIELDS]
    at = next(i for i, c in enumerate(cols) if c["f"] == "joined")
    cols.insert(at, {"f": "tenure", "label": "Tenure (계산)", "owner": "BA", "edit": False, "date": False})
    cols.append({"f": "dates_ok", "label": "날짜 확인", "owner": "BA", "edit": False, "date": False})
    status: dict[str, int] = {}
    for r in rows:
        k = r.get("status") or "(빈 값)"
        status[k] = status.get(k, 0) + 1
    loads = store.info_loads(1)
    team = store.team_roster()
    preview, history, latest = None, [], None
    if changes is not None and user.can("info.edit"):
        history = changes.history(user, "info.edit", 30)
        applied = [c for c in history if c.status == APPLIED]
        latest = max(applied, key=lambda c: c.applied_at or "").change_id if applied else None
        if change_id:
            preview = next((c for c in history if c.change_id == change_id and c.status == PREVIEW), None)
    return {"cfg": screens["screens"]["info"], "rows": rows, "cols": cols, "status_counts": status,
            "tls": sorted({r["tl_ldap"] for r in rows if r.get("tl_ldap")}), "load": loads[0] if loads else None,
            "today": today, "can_sync": user.can("info.sync"), "can_edit": any(c["edit"] for c in cols),
            "can_add": can_edit(user, "name"), "edited_count": sum(1 for r in rows if r["_edited"]),
            "preview": preview, "history": history, "latest_applied": latest, "header_help": header_help(user),
            "team_load": {"rows": len(team), "tls": len({r["tl_name"] for r in team}),
                          "loaded_at": str(team[0].get("loaded_at") or ""), "loaded_by": team[0].get("loaded_by")}
            if team else None}


def info_sync(service, user: User, screens: dict, dry_run: bool, force: bool = False) -> dict:
    """시트에서 불러오기 (먼저 dry_run 으로 확인 → 저장)."""
    _need(user, "info.sync", "INFO 불러오기")
    cfg = screens["screens"]["info"]
    return service.run(cfg["source_sheet"], cfg["source_tab"], user.email, cfg.get("header_row", 2), dry_run, force)


def team_sync(service, user: User, screens: dict, dry_run: bool, force: bool = False) -> dict:
    """팀 구성(시트 OPS TL) 불러오기 — 상담사 360 의 팀(TL 한글 이름)·명단 기준."""
    _need(user, "info.sync", "팀 구성 불러오기")
    cfg = screens["screens"]["info"]
    return service.run(cfg["team_sheet"], cfg["team_tab"], user.email, dry_run, force)


def _fmt(f: str) -> str:
    if f == "emp_id":
        return "사번 그대로 (숫자, 임시면 '트레이닝1' 처럼) — 이 값으로 사람을 찾음"
    if f == "status":
        return "재직자 · 퇴직자 · 확인안됨 중 하나"
    if f == "email":
        return "이메일 (소문자로 바꿔 저장)"
    if f in info_svc.DATE_FIELDS:
        return "날짜 — 2026-07-03 · 2026. 7. 3 · 20260703 · 7/3/2026 등 날짜로 읽히면 됨 (YYYY-MM-DD 로 저장)"
    if info_svc.KIND[f] == "id":
        return "숫자 (앞의 ' 나 .0 은 빼고 읽음)"
    return "글자 그대로"


def header_help(user: User) -> list[dict]:
    """한꺼번에 고치기 — 쓸 수 있는 머리글 전체 (원본 시트 머리글과 같음)."""
    return [{"f": f, "header": info_svc.LABEL[f], "owner": info_svc.OWNER[f], "edit": f != "emp_id" and can_edit(user, f),
             "required": f == "emp_id", "fmt": _fmt(f)} for f in info_svc.FIELDS]
