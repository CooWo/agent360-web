"""감사 로그 — 기획안 8장 '변경 이력'.

남기는 것: 민감 정보 열람, 코칭 저장·수정·완료, 신호 처리 상태 변경, 기준값 변경.
1) Cloud Logging 이 바로 읽는 JSON 한 줄을 표준 출력에 남기고
2) 데이터 백엔드의 audit_log 에도 저장한다 (BigQuery 또는 sample_data/runtime).
"""
from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone

from app.core.permissions import User

_log = logging.getLogger("audit")
if not _log.handlers:
    _h = logging.StreamHandler(sys.stdout)
    _h.setFormatter(logging.Formatter("%(message)s"))
    _log.addHandler(_h)
    _log.setLevel(logging.INFO)
    _log.propagate = False


def audit(backend, user: User, action: str, target_type: str, target_id: str, detail: dict | None = None) -> dict:
    event = {
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "actor": user.email,
        "role": user.role,
        "action": action,              # 예: view_sensitive, coaching_create, signal_status
        "target_type": target_type,    # 예: agent, coaching, signal, rule
        "target_id": target_id,
        "detail": detail or {},
    }
    _log.info(json.dumps({"severity": "NOTICE", "logName": "audit", **event}, ensure_ascii=False))
    try:
        backend.write_audit(event)
    except Exception as e:  # noqa: BLE001  감사 저장 실패가 화면을 막지 않게
        _log.warning(json.dumps({"severity": "WARNING", "message": f"audit 저장 실패: {e}"}, ensure_ascii=False))
    return event
