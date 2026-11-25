"""보드 규칙 — 행 정리·검사·비교. 순수 Python.

행: {"tl","shift","emp_id","name","e_name","display_name","date","note"}
키: 사번이 있으면 사번, 없으면 "임시:<이름>" (예: 임시:트레이닝1). 날짜는 계산에 쓰지 않는다 (메모성 '반영일').
"""
from __future__ import annotations

from dataclasses import dataclass, field

FIELDS = ("tl", "shift", "emp_id", "name", "e_name", "display_name", "date", "note")
LABEL = {"tl": "TL", "shift": "Shift", "emp_id": "사번", "name": "이름", "e_name": "Name",
         "display_name": "Display name", "date": "반영일", "note": "메모"}
EDITABLE = ("shift", "name", "e_name", "display_name", "date", "note")
TEMP = "임시:"


def clean_emp_id(v) -> str:
    s = str(v or "").strip().lstrip("'")
    return s[:-2] if s.endswith(".0") and s[:-2].isdigit() else s


def key(row: dict) -> str:
    return row["emp_id"] or f"{TEMP}{row['name']}"


def is_temp(row: dict) -> bool:
    return not row["emp_id"]


@dataclass
class Check:
    errors: dict[str, str] = field(default_factory=dict)      # 적용 불가
    warnings: list[dict] = field(default_factory=list)        # 적용 가능, 확인 권장


class BoardRules:
    """기본정보(INFO)를 주입받아 행을 정리·검사·비교한다."""

    def __init__(self, info: list[dict]):
        self.info = {clean_emp_id(r["emp_id"]): r for r in info}

    def normalize(self, rows: list[dict]) -> list[dict]:
        """공백 정리, 사번 정리, 빈 행 제거, 이름이 비면 INFO 에서 채움."""
        out = []
        for r in rows:
            n = {f: str(r.get(f) or "").strip() for f in FIELDS}
            n["emp_id"] = clean_emp_id(n["emp_id"])
            if not n["emp_id"] and not n["name"]:
                continue
            src = self.info.get(n["emp_id"])
            if src:
                n["name"] = n["name"] or src.get("name", "")
                n["e_name"] = n["e_name"] or src.get("e_name", "")
            out.append(n)
        return out

    def check(self, rows: list[dict], known_tls: set[str] | None = None) -> Check:
        c = Check()
        seen: dict[str, int] = {}
        for i, r in enumerate(rows, 1):
            who = r["name"] or r["emp_id"]
            if not r["tl"]:
                c.errors[f"rows.{i}.tl"] = f"{who}: TL 이 비었습니다."
            k = key(r)
            if k in seen:
                c.errors[f"rows.{i}.emp_id"] = f"{who}: {seen[k]}번째 줄과 같은 사람입니다 (한 사람은 한 TL 에만)."
            seen.setdefault(k, i)
            src = self.info.get(r["emp_id"])
            if is_temp(r):
                c.warnings.append({"row": i, "who": who, "kind": "temp", "text": "사번 없음 → 임시로 등록"})
            elif not src:
                c.warnings.append({"row": i, "who": who, "kind": "unknown", "text": f"INFO 에 없는 사번 {r['emp_id']}"})
            elif src.get("left"):
                c.warnings.append({"row": i, "who": who, "kind": "left", "text": f"퇴사자 (퇴사일 {src['left']})"})
        if known_tls is not None:
            for tl in sorted({r["tl"] for r in rows if r["tl"]} - known_tls):
                c.warnings.append({"row": 0, "who": tl, "kind": "new_tl", "text": "새 TL → BA팀 알림"})
        return c

    @staticmethod
    def diff(before: list[dict], after: list[dict]) -> list[dict]:
        """바뀐 것 목록: 신규 · 빠짐 · 이동 · 수정 · 사번 연결(임시 → 사번)."""
        old = {key(r): r for r in before}
        new = {key(r): r for r in after}
        out: list[dict] = []
        temp_by_name = {r["name"]: k for k, r in old.items() if is_temp(r)}
        linked: set[str] = set()
        for k, r in new.items():
            if k in old:
                continue
            tk = temp_by_name.get(r["name"]) if r["emp_id"] else None
            if tk and tk not in new:
                linked.add(tk)
                out.append(_d(k, r, "link", "사번 연결", f"{old[tk]['name']} (임시)", r["emp_id"]))
                if old[tk]["tl"] != r["tl"]:
                    out.append(_d(k, r, "move", "이동", old[tk]["tl"], r["tl"]))
            else:
                out.append(_d(k, r, "new", "신규", "", r["tl"]))
        for k, r in old.items():
            if k not in new and k not in linked:
                out.append(_d(k, r, "remove", "빠짐", r["tl"], ""))
        for k, r in new.items():
            o = old.get(k)
            if not o:
                continue
            if o["tl"] != r["tl"]:
                out.append(_d(k, r, "move", "이동", o["tl"], r["tl"]))
            for f in EDITABLE:
                if o.get(f, "") != r.get(f, ""):
                    out.append(_d(k, r, f"edit.{f}", f"{LABEL[f]} 수정", o.get(f, ""), r.get(f, "")))
        order = {"new": 0, "link": 1, "move": 2, "remove": 3}
        return sorted(out, key=lambda d: (order.get(d["field"].split(".")[0], 4), d["name"], d["field"]))


def _d(k: str, r: dict, f: str, label: str, before: str, after: str) -> dict:
    return {"key": k, "name": r["name"], "field": f, "label": label, "before": before, "after": after}


def summarize(diff: list[dict]) -> str:
    cnt: dict[str, int] = {}
    for d in diff:
        lab = "수정" if d["field"].startswith("edit.") else d["label"]
        cnt[lab] = cnt.get(lab, 0) + 1
    order = ["신규", "사번 연결", "이동", "빠짐", "수정"]
    return "팀 구성 " + " · ".join(f"{k} {cnt[k]}" for k in order if k in cnt)


def merge_paste(current: list[dict], pasted: list[dict], replace_all: bool) -> list[dict]:
    """붙여넣은 TL 의 명단만 바꾼다 (replace_all 이면 보드 전체를 바꾼다)."""
    if replace_all:
        return list(pasted)
    tls = {r["tl"] for r in pasted}
    return [r for r in current if r["tl"] not in tls] + list(pasted)


def by_tl(rows: list[dict]) -> list[dict]:
    """화면용: TL 별 묶음 (시트 OPS TL 처럼). TL 순서는 처음 나온 순서."""
    groups: dict[str, list] = {}
    for r in rows:
        groups.setdefault(r["tl"], []).append(r)
    return [{"tl": tl, "rows": rs, "count": len(rs)} for tl, rs in groups.items()]
