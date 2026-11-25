"""감사 로그 — 기획안 8장 '변경 이력'.

남기는 것: 민감 정보 열람, 코칭 저장·완료, 신호 처리 상태 변경, 데이터 변경(미리보기·승인·되돌리기).
Auditor 가 기록 한 건을 여러 '받는 곳(sink)'에 보낸다:
  LogSink   : Cloud Logging 이 읽는 JSON 한 줄 (표준 출력)
  StoreSink : 데이터 백엔드의 audit_log (BigQuery 또는 sample_data/runtime)
받는 곳을 늘릴 때(예: 슬랙 알림)는 AuditSink 를 하나 더 만들어 넘긴다 — Auditor 는 그대로.
받는 곳 하나가 실패해도 화면은 막지 않는다.
"""
from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone
from typing import Protocol

from app.core.data.base import AuditStore
from app.core.permissions import User

_log = logging.getLogger("audit")
if not _log.handlers:
    _h = logging.StreamHandler(sys.stdout)
    _h.setFormatter(logging.Formatter("%(message)s"))
    _log.addHandler(_h)
    _log.setLevel(logging.INFO)
    _log.propagate = False


class AuditSink(Protocol):
    def write(self, event: dict) -> None: ...


class LogSink:
    def write(self, event: dict) -> None:
        _log.info(json.dumps({"severity": "NOTICE", "logName": "audit", **event}, ensure_ascii=False))


class StoreSink:
    def __init__(self, store: AuditStore):
        self.store = store

    def write(self, event: dict) -> None:
        self.store.write_audit(event)


class Auditor:
    def __init__(self, sinks: list[AuditSink]):
        self.sinks = list(sinks)

    @classmethod
    def for_store(cls, store: AuditStore) -> "Auditor":
        return cls([LogSink(), StoreSink(store)])

    def record(self, user: User, action: str, target_type: str, target_id: str, detail: dict | None = None) -> dict:
        event = {
            "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "actor": user.email,
            "role": user.role,
            "action": action,              # 예: view_sensitive, coaching_create, change_apply
            "target_type": target_type,    # 예: agent, coaching, signal, change
            "target_id": target_id,
            "detail": detail or {},
        }
        for sink in self.sinks:
            try:
                sink.write(event)
            except Exception as e:  # noqa: BLE001  감사 저장 실패가 화면을 막지 않게
                _log.warning(json.dumps({"severity": "WARNING", "message": f"audit 저장 실패({type(sink).__name__}): {e}"},
                                        ensure_ascii=False))
        return event


def audit(backend: AuditStore, user: User, action: str, target_type: str, target_id: str,
          detail: dict | None = None) -> dict:
    """예전 호출 방식 그대로: 로그 + 백엔드 audit_log."""
    return Auditor.for_store(backend).record(user, action, target_type, target_id, detail)
