"""Capacity API (/api/capacity/...). 화면과, 나중에 Capacity AI 어시스턴트 도구(C-14)가 쓴다."""
from __future__ import annotations

from fastapi import APIRouter, Depends

from app.core.data import get_backend
from app.core.deps import current_user
from app.core.modules import discover
from app.core.permissions import User
from app.modules.capacity import views
from app.modules.capacity.data import get_store

router = APIRouter(prefix="/api/capacity", tags=["capacity"])


@router.get("/fte")
def fte_weekly(user: User = Depends(current_user)):
    """주별 필요·가용 FTE 와 갭 (채널 합계 + 이번 주 채널별). 숫자는 계산 엔진 결과 그대로."""
    screens = next(m for m in discover() if m.name == "capacity").screens
    ctx = views.home(get_backend(), get_store(), user, screens)
    return {k: ctx[k] for k in ("as_of", "week", "now", "shortage", "totals", "channels", "assumptions")}
