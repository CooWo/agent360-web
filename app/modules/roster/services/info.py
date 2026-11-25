"""기본정보 = 시트 'INFO 자동화 시트' (원천 파일의 같은 이름 탭을 IMPORTRANGE 로 가져온 허브 표).

흐름: 시트 → info_raw(받은 그대로, 불러올 때마다 쌓음) → 정리(InfoCleaner) → mart_agent_info(사번당 한 줄)
열마다 입력 담당이 정해져 있다 (시트 1행): OPS 입력 / WFM 입력 / BA용(계산·HR).
BA용 계산 열(Tenure 등)은 저장하지 않고 화면·SQL 에서 계산한다.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, timedelta

# (필드, 시트 머리글, 담당, 종류)
COLUMNS: tuple[tuple[str, str, str, str], ...] = (
    ("emp_id", "사번", "OPS", "id"),
    ("name", "한글명", "OPS", "text"),
    ("e_name", "Name", "OPS", "text"),
    ("email", "Email", "OPS", "text"),
    ("airbnb_id", "Airbnb ID", "OPS", "id"),
    ("batch", "CE/SR1 Batch", "OPS", "text"),
    ("shift_type", "Shift Type", "OPS", "text"),
    ("location", "Location", "OPS", "text"),
    ("tl_ldap", "TL", "BA", "text"),            # OPS 시트 자동반영 + 팀장 수정(Amb.TL) 으로 정해짐
    ("type", "Type", "OPS", "text"),
    ("tier", "Tier", "OPS", "text"),
    ("ldap", "LDAP", "OPS", "text"),
    ("fte", "FTE", "OPS", "text"),
    ("onboarding", "온보딩 날짜", "OPS", "date"),
    ("r2_onboarding", "R2 온보딩", "OPS", "date"),
    ("universal", "Universal", "WFM", "text"),
    ("incentive_date", "근속 인센티브", "OPS", "date"),
    ("joined", "입사일(UHR)", "BA", "date"),
    ("status", "재직정보", "BA", "text"),        # 재직자 | 퇴직자
    ("tier_before_universal", "Universal 전\nTier", "WFM", "text"),
    ("note", "비고", "BA", "text"),
)
FIELDS = tuple(c[0] for c in COLUMNS)
LABEL = {c[0]: c[1].replace("\n", " ") for c in COLUMNS}
OWNER = {c[0]: c[2] for c in COLUMNS}
KIND = {c[0]: c[3] for c in COLUMNS}
DATE_FIELDS = tuple(f for f in FIELDS if KIND[f] == "date")
HEADER_TO_FIELD = {h.replace("\n", " ").strip().lower(): f for f, h, _, _ in COLUMNS}
ACTIVE, RETIRED = "재직자", "퇴직자"
EMPTY_MARKS = {"-", "–", "#N/A", "#REF!", "N/A", "n/a"}
# 날짜 칸에 날짜 대신 적힌 상태 표시 — 날짜는 비우고 문제로 세지 않는다 (원본은 info_raw 에 그대로 남음)
DATE_TEXT_MARKS = {"퇴사", "확인안됨", "확인 안됨", "미정", "없음"}


def is_retired(row: dict | None) -> bool:
    return bool(row) and str(row.get("status") or "").strip() == RETIRED


def header_index(header: list[str]) -> dict[int, str]:
    """시트 머리글 줄 → {열 번호: 필드}. 같은 이름이 뒤에 또 나오면(OPS 자동반영 블록의 '사번' 등) 첫 번째만."""
    idx: dict[int, str] = {}
    for i, h in enumerate(header):
        f = HEADER_TO_FIELD.get(str(h).replace("\n", " ").strip().lower())
        if f and f not in idx.values():
            idx[i] = f
    return idx


def raw_rows(header: list[str], values: list[list]) -> list[dict]:
    """머리글 아래 값 → 필드 dict (받은 그대로 문자열, 정리 전). row_no 는 시트 행 번호 기준이 아닌 데이터 순서(1부터)."""
    idx = header_index(header)
    out = []
    for n, r in enumerate(values, 1):
        d = {f: ("" if i >= len(r) or r[i] is None else str(r[i])) for i, f in idx.items()}
        if any(v.strip() for v in d.values()):
            out.append({"row_no": n, **{f: d.get(f, "") for f in FIELDS}})
    return out


def from_sheet(header: list[str], rows: list[list]) -> list[dict]:
    """머리글 + 값 → 정리된 마트 행 (예전 호출 방식)."""
    return InfoCleaner().clean(raw_rows(header, rows)).rows


def tenure_bucket(joined: str, today: str) -> str:
    """BA용 Tenure 를 저장하지 않고 계산 (시트와 같은 구간 이름)."""
    if not joined:
        return ""
    n = (date.fromisoformat(today) - date.fromisoformat(joined)).days
    for hi, label in ((30, "0~30 Days"), (60, "31~60 Days"), (90, "61~90 Days"), (180, "91~180 Days"),
                      (365, "181~365 Days")):
        if n <= hi:
            return label
    return "365+ Days"


# ── 정리 ───────────────────────────────────────────
_SHEETS_EPOCH = date(1899, 12, 30)


_YEAR_OK = range(1990, 2101)


def _ok(d: date | None) -> str | None:
    return d.isoformat() if d and d.year in _YEAR_OK else None


def parse_date(v: str) -> str | None:
    """날짜로 읽을 수 있는 형식은 모두 'YYYY-MM-DD' 로. 못 읽으면 None.

    예: 2021-03-21 · 2021. 3. 21 · 2021/3/21 · 20210321 · 2021년 3월 21일 · 7/31/2026 · 31/7/2026 · 7-31-26
        · Jul 31, 2026 · 31 Jul 2026 · 2026-07-31 10:00 · 시트 날짜 숫자(45997)
    숫자/숫자/연도 에서 앞 숫자가 12보다 크면 일/월, 아니면 월/일 로 읽는다 (시트 기본 형식).
    연도는 1990~2100 만 날짜로 인정.
    """
    s = str(v or "").strip().rstrip(".")
    if not s or not re.search(r"\d", s):
        return None
    s = re.sub(r"\s*(년|월)\s*", "-", s).replace("일", "").strip(" -")
    try:
        m = re.fullmatch(r"(\d{4})\s*[-./]\s*(\d{1,2})\s*[-./]\s*(\d{1,2})(?:[ T].*)?", s)
        if m:
            return _ok(date(int(m[1]), int(m[2]), int(m[3])))
        m = re.fullmatch(r"(\d{4})(\d{2})(\d{2})", s)
        if m:
            return _ok(date(int(m[1]), int(m[2]), int(m[3])))
        if re.fullmatch(r"\d{5}(\.\d+)?", s):                       # 시트 날짜 숫자
            return _ok(_SHEETS_EPOCH + timedelta(days=int(float(s))))
        m = re.fullmatch(r"(\d{1,2})\s*[-./]\s*(\d{1,2})\s*[-./]\s*(\d{2}|\d{4})", s)
        if m:
            a, b, y = int(m[1]), int(m[2]), int(m[3])
            y = y + 2000 if y < 100 else y
            month, day = (b, a) if a > 12 else (a, b)
            return _ok(date(y, month, day))
        if re.search(r"[A-Za-z]{3}", s):                           # Jul 31, 2026 · 31 July 2026
            from dateutil import parser as du
            return _ok(du.parse(s, fuzzy=False).date())
    except (ValueError, OverflowError):
        return None
    return None


def clean_id(v) -> str:
    s = str(v or "").strip().lstrip("'").replace(",", "")
    return s[:-2] if s.endswith(".0") and s[:-2].isdigit() else s


@dataclass
class CleanResult:
    """rows: 마트 행 (FIELDS + dates_ok: 날짜 칸이 모두 날짜로 읽혔거나 비었으면 True)."""
    rows: list[dict]
    read: int = 0
    dropped_no_id: int = 0
    duplicates: list[str] = field(default_factory=list)     # 같은 사번이 여러 줄
    issues: list[dict] = field(default_factory=list)        # {"emp_id","field","value","text"}

    def summary(self) -> dict:
        return {"rows_read": self.read, "rows_mart": len(self.rows), "dropped_no_id": self.dropped_no_id,
                "duplicates": len(self.duplicates), "issues": len(self.issues)}


class InfoCleaner:
    """받은 그대로의 행 → 사번당 한 줄. 규칙은 여기 한 곳에서만."""

    def _one(self, r: dict, issues: list[dict]) -> dict:
        out: dict = {"dates_ok": True}
        for f in FIELDS:
            v = str(r.get(f) or "").strip()
            v = "" if v in EMPTY_MARKS else v
            if KIND[f] == "id":
                v = clean_id(v)
            elif KIND[f] == "date" and v in DATE_TEXT_MARKS:
                v = ""
            elif KIND[f] == "date" and v:
                d = parse_date(v)
                if d is None:
                    out["dates_ok"] = False
                    issues.append({"emp_id": clean_id(r.get("emp_id")), "field": f, "value": v,
                                   "text": f"{LABEL[f]} 날짜를 읽을 수 없음"})
                v = d or ""
            elif f == "email":
                v = v.lower()
            out[f] = v
        return out

    def clean(self, raw: list[dict]) -> CleanResult:
        res = CleanResult(rows=[], read=len(raw))
        by_id: dict[str, dict] = {}
        order: list[str] = []
        for r in raw:
            row = self._one(r, res.issues)
            k = row["emp_id"]
            if not k:
                res.dropped_no_id += 1
                continue
            if k in by_id:
                res.duplicates.append(k)
                # 재직자 줄을 우선, 같으면 아래쪽(나중) 줄
                if not (by_id[k]["status"] == ACTIVE and row["status"] != ACTIVE):
                    by_id[k] = row
                continue
            by_id[k] = row
            order.append(k)
        res.rows = [by_id[k] for k in order]
        return res
