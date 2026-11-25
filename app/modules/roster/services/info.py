"""기본정보 = 시트 'INFO 자동화 시트' (다른 파일에서 IMPORTRANGE 로 가져온 허브 표).

열마다 입력 담당이 정해져 있다 (시트 1행): OPS 입력 / WFM 입력 / BA용(계산·HR) / schedule.
웹에서는 같은 담당 구분으로 열 단위 수정 권한을 나누고, BA용 계산 열(Tenure 등)은 저장하지 않고 계산한다.
"""
from __future__ import annotations

# (필드, 시트 머리글, 담당)
COLUMNS: tuple[tuple[str, str, str], ...] = (
    ("emp_id", "사번", "OPS"),
    ("name", "한글명", "OPS"),
    ("e_name", "Name", "OPS"),
    ("email", "Email", "OPS"),
    ("airbnb_id", "Airbnb ID", "OPS"),
    ("batch", "CE/SR1 Batch", "OPS"),
    ("shift_type", "Shift Type", "OPS"),
    ("location", "Location", "OPS"),
    ("tl_ldap", "TL", "BA"),                    # OPS 시트 자동반영 + 팀장 수정(Amb.TL) 으로 정해짐
    ("type", "Type", "OPS"),
    ("tier", "Tier", "OPS"),
    ("ldap", "LDAP", "OPS"),
    ("fte", "FTE", "OPS"),
    ("onboarding", "온보딩 날짜", "OPS"),
    ("r2_onboarding", "R2 온보딩", "OPS"),
    ("universal", "Universal", "WFM"),
    ("incentive_date", "근속 인센티브", "OPS"),
    ("joined", "입사일(UHR)", "BA"),
    ("status", "재직정보", "BA"),               # 재직자 | 퇴직자
    ("tier_before_universal", "Universal 전\nTier", "WFM"),
    ("note", "비고", "BA"),
)
FIELDS = tuple(c[0] for c in COLUMNS)
HEADER_TO_FIELD = {h.replace("\n", " ").strip().lower(): f for f, h, _ in COLUMNS}
OWNER = {f: o for f, _, o in COLUMNS}
RETIRED = "퇴직자"


def is_retired(row: dict | None) -> bool:
    return bool(row) and str(row.get("status") or "").strip() == RETIRED


def from_sheet(header: list[str], rows: list[list[str]]) -> list[dict]:
    """시트 2행 머리글 + 값 → 필드 이름 dict (모르는 열은 버림, 사번 없는 행 제외)."""
    idx = {}
    for i, h in enumerate(header):
        f = HEADER_TO_FIELD.get(str(h).replace("\n", " ").strip().lower())
        if f and f not in idx.values():
            idx[i] = f
    out = []
    for r in rows:
        d = {f: (str(r[i]).strip() if i < len(r) else "") for i, f in idx.items()}
        if d.get("emp_id"):
            out.append({f: d.get(f, "") for f in FIELDS})
    return out
