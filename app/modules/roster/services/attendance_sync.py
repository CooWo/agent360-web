"""근태 불러오기 — 'Schedule KR' 읽기(값 + 배경색) → 판정 → 바뀐 칸만 저장.

부하를 줄이는 방법
- 시트: 호출 3번 (1행 날짜, A열 사번, 기간 열만 값+배경색). 필요한 필드만 받는다.
- BigQuery: 기간 안 저장분을 한 번 읽어 비교 → 바뀐 칸만 MERGE (없으면 쓰기 없음).
정확하게
- 기본 기간은 '지난달 1일 ~ 오늘(한국 시간)': 월말 인센티브 정리 때 고친 칸도 다시 맞춘다.
- 읽다가 실패하면 아무것도 쓰지 않는다. 지울 칸이 너무 많으면(시트 행을 지웠거나 탭이 바뀜) 멈춘다.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone

from app.modules.roster.services.attendance import date_columns, diff, read_block
from app.modules.roster.services.team_edit import col_letter

KST = timezone(timedelta(hours=9))
SOURCE = "schedule_kr"
MAX_DELETE_RATIO = 0.2      # 기간 안 저장분의 20% 넘게 지우려 하면 멈춤 (force 로만)
MIN_DELETE_GUARD = 50


class AttendanceRefused(Exception):
    pass


def kst_today() -> date:
    return datetime.now(KST).date()


def default_since(today: date) -> date:
    return (today.replace(day=1) - timedelta(days=1)).replace(day=1)


class AttendanceSync:
    def __init__(self, reader, store=None):
        self.reader, self.store = reader, store

    def run(self, sheet: str, tab: str, by: str, since: date | None = None, until: date | None = None,
            dry_run: bool = True, force: bool = False) -> dict:
        until = min(until or kst_today(), kst_today())          # 앞으로의 날짜(계획)는 넣지 않는다
        since = since or default_since(until)
        header = (self.reader.values(sheet, f"'{tab}'!1:1") or [[]])[0]
        cols = date_columns(header, since, until)
        if not cols:
            raise ValueError(f"'{tab}' 1행에서 {since} ~ {until} 날짜 열을 찾지 못했습니다.")
        ids = [(r[0] if r else "") for r in self.reader.values(sheet, f"'{tab}'!A:A")]
        c1, c2 = cols[0][0], cols[-1][0]
        block = self.reader.cells(sheet, f"'{tab}'!{col_letter(c1)}1:{col_letter(c2)}{max(len(ids), 1)}")
        new, summary = read_block(ids, block, 0, cols, c1)
        agents = {a for a, _ in new} | {str(i).strip() for i in ids if str(i).strip().isdigit()}
        old = {}
        if self.store is not None:
            old = {(r["agent_id"], r["date"]): {"status": r["status"], "detail": r.get("detail") or "",
                                                "bg": r.get("bg") or ""}
                   for r in self.store.attendance_rows(since.isoformat(), until.isoformat())}
        upserts, deletes = diff(new, old, agents)
        limit = max(MIN_DELETE_GUARD, int(len(old) * MAX_DELETE_RATIO))
        out = {**summary, "since": since.isoformat(), "until": until.isoformat(), "days": len(cols),
               "upserts": len(upserts), "deletes": len(deletes), "stored_before": len(old),
               "samples": [{**u, "before": (old.get((u["agent_id"], u["date"])) or {}).get("detail", "")}
                           for u in upserts[:15]],
               "load_id": None, "dry_run": dry_run, "source": f"{sheet}/{tab}"}
        if len(deletes) > limit and not force:
            out["refused"] = (f"지울 칸이 {len(deletes)}개로 너무 많습니다 (기준 {limit}). 시트 행·탭이 바뀌었는지 "
                              "확인하세요. 맞으면 '그래도 저장'으로 다시 하세요.")
            if not dry_run:
                raise AttendanceRefused(out["refused"])
        if not dry_run:
            load_id = "A" + datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S") + uuid.uuid4().hex[:4]
            self.store.apply_attendance(upserts, deletes, {
                "load_id": load_id, "loaded_by": by, "source": out["source"], "since": out["since"],
                "until": out["until"], "agents": out["agents"], "cells": out["cells"], "upserts": len(upserts),
                "deletes": len(deletes), "by_status": out["by_status"], "unknown": out["unknown"]})
            out["load_id"] = load_id
        return out
