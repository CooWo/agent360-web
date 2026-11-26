"""근태 — 원본 시트 'Schedule KR' (행 = 상담사, 열 = 날짜) → common.fact_attendance.

칸 하나 → 상태 하나. 판정 순서 (위에서 먼저 맞는 것):
1. 빈 칸                                        → 기록 없음
2. 인사 표시 (Resignation, Move to …, End of Contract …) → 기록 없음 (근태가 아님, 요약에만 셈)
3. 글로 정해진 근태: Absent·Planned Absences → 결근, Approved AL(*) → 연차, Sat off·PH → 휴무,
   …휴직·Military → 휴직, …휴가·검진 → 휴가, Training → 교육
4. 근무시간(09:00~18:00 …, NOT·BOT 표기 포함): 배경 #ff9900 → 지각, #f9cb9c → 조퇴, 글에 Late → 지각,
   Early → 조퇴, 그 밖 → 정상
5. Early left → 조퇴, Late → 지각
6. 나머지 → 기타 (글은 detail 에 그대로, 요약의 '모르는 값'에 보임)
숫자는 만들지 않는다: 칸 글(detail)과 배경색(bg)을 그대로 같이 저장한다.
"""
from __future__ import annotations

import re
from collections import Counter
from datetime import date

LATE_BG, EARLY_BG = "#ff9900", "#f9cb9c"
STATUSES = ("정상", "지각", "조퇴", "결근", "연차", "휴가", "휴직", "휴무", "교육", "기타")
_TIME = r"\d{1,2}\s*:\s*\d{2}"
SHIFT_RE = re.compile(rf"{_TIME}\s*:?\s*[~\-–—～]\s*{_TIME}")
DATE_RE = re.compile(r"^\s*(\d{4})\s*[.\-/]\s*(\d{1,2})\s*[.\-/]\s*(\d{1,2})\s*\.?\s*$")
EMP_RE = re.compile(r"^\d{8}$")
HR_MARKS = ("resignation", "end of contract", "move to", "transfer to", "transition to", "back to", "rejoin")


def parse_date(v: str) -> date | None:
    m = DATE_RE.match(str(v or ""))
    if not m:
        return None
    try:
        return date(*map(int, m.groups()))
    except ValueError:
        return None


def classify(text: str, bg: str = "") -> str | None:
    """칸 글 + 배경색 → 상태 (STATUSES 중 하나) 또는 None (기록 없음)."""
    t = " ".join(str(text or "").split())
    if not t:
        return None
    k = t.lower()
    if k.startswith(HR_MARKS):
        return None
    if k.startswith(("absent", "planned absence")):
        return "결근"
    if k.startswith(("approved al", "pending al")):
        return "연차"
    if k in ("sat off", "off", "ph"):
        return "휴무"
    if "휴직" in t or k.startswith("military"):
        return "휴직"
    if "휴가" in t or "검진" in t:
        return "휴가"
    if k.startswith(("training", "refresher training")):
        return "교육"
    bg = (bg or "").lower()
    if SHIFT_RE.search(t):
        if bg == LATE_BG or "late" in k:
            return "지각"
        if bg == EARLY_BG or "early" in k:
            return "조퇴"
        return "정상"
    if k.startswith("early"):
        return "조퇴"
    if k.startswith("late"):
        return "지각"
    return "기타"


def is_hr_mark(text: str) -> bool:
    return " ".join(str(text or "").split()).lower().startswith(HR_MARKS)


def date_columns(header: list[str], since: date, until: date) -> list[tuple[int, date]]:
    """1행(날짜 머리글)에서 기간 안 날짜 열 (0부터 센 열 번호, 날짜)."""
    out = []
    for i, v in enumerate(header):
        d = parse_date(v)
        if d and since <= d <= until:
            out.append((i, d))
    return out


def read_block(ids: list[str], block: list[list[tuple[str, str]]], first_row: int, cols: list[tuple[int, date]],
               first_col: int) -> tuple[dict, dict]:
    """시트 칸 → {(사번, 'YYYY-MM-DD'): {status, detail, bg}} 와 요약.

    ids: A열 전체 (ids[0] = 1행). block: first_row(0부터)행 · first_col 열부터 읽은 칸 (값, 배경색).
    같은 사번이 두 줄이면 먼저 나온 줄의 값을 쓰고, 다른 값이 있으면 요약의 conflicts 에 남긴다.
    """
    rows: dict[tuple[str, str], dict] = {}
    by_status: Counter = Counter()
    unknown: Counter = Counter()
    hr = 0
    agents: set[str] = set()
    seen_row: dict[str, int] = {}
    dup_ids, conflicts = set(), []
    for bi, line in enumerate(block):
        ri = first_row + bi
        emp = str(ids[ri] if ri < len(ids) else "").strip()
        if not EMP_RE.match(emp):
            continue
        if emp in seen_row:
            dup_ids.add(emp)
        else:
            seen_row[emp] = ri
        agents.add(emp)
        for ci, d in cols:
            j = ci - first_col
            text, bg = line[j] if 0 <= j < len(line) else ("", "")
            text = str(text or "").strip()
            st = classify(text, bg)
            if st is None:
                hr += is_hr_mark(text)
                continue
            key = (emp, d.isoformat())
            row = {"status": st, "detail": text[:200], "bg": (bg or "").lower()}
            if key in rows:
                if rows[key] != row:
                    conflicts.append({"emp_id": emp, "date": key[1], "kept": rows[key]["detail"], "other": text})
                continue
            rows[key] = row
            by_status[st] += 1
            if st == "기타":
                unknown[text] += 1
    summary = {"agents": len(agents), "cells": len(rows), "by_status": {s: by_status[s] for s in STATUSES if by_status[s]},
               "unknown": unknown.most_common(15), "hr_marks": hr, "duplicate_ids": sorted(dup_ids),
               "conflicts": conflicts[:20]}
    return rows, summary


def diff(new: dict, old: dict, agents: set[str]) -> tuple[list[dict], list[tuple[str, str]]]:
    """바꿀 것만: (넣거나 고칠 행, 지울 (사번, 날짜)). 지우기는 이번에 시트에서 읽은 사번만 (다른 탭으로 옮긴 사람은 둠)."""
    upserts = [{"agent_id": a, "date": d, **v} for (a, d), v in sorted(new.items()) if old.get((a, d)) != v]
    deletes = sorted(k for k in old if k not in new and k[0] in agents)
    return upserts, deletes
