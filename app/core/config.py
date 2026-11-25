"""앱 설정 — 모두 환경 변수(.env)로 바꾼다. 코드에 값을 직접 쓰지 않는다.

ENV            local | prod       local 이면 가짜 로그인(사용자 전환) 허용
DATA_BACKEND   sample | bigquery  sample 이면 sample_data/*.json 사용
GCP_PROJECT    BigQuery 프로젝트
BQ_LOCATION    BigQuery 리전 (예: asia-northeast3)
COMMON_DATASET 공통 데이터셋 (dim_agent, fact_* — Capacity Web 과 공유)
MODULE_DATASET 모듈 전용 데이터셋 (fact_coaching, mart_signals, user_roles, audit_log …)
IAP_AUDIENCE   설정하면 IAP JWT 서명을 검증 (prod 권장)
ALLOWED_DOMAINS 쉼표 구분. prod 에서 이 도메인 이메일만 통과 (예: ubase.co.kr)
DEV_USER       local 기본 로그인 사용자 이메일
AI_AGENT_*     기존 BigQuery 데이터 에이전트(Conversational Analytics API) 연결 — 비우면 AI 질문 메뉴가 '미설정'
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[2]


def _load_dotenv(path: Path) -> None:
    """.env 파일을 읽어 환경 변수에 없는 값만 채운다 (외부 패키지 없이)."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), _clean_value(v))


def _clean_value(v: str) -> str:
    """값 뒤 설명(  # ...)을 떼고 따옴표를 벗긴다. 따옴표 안의 # 은 그대로 둔다."""
    v = v.strip()
    if v[:1] in ('"', "'") and v[0] in v[1:]:
        return v[1:v.index(v[0], 1)]
    for i, ch in enumerate(v):
        if ch == "#" and (i == 0 or v[i - 1] in " \t"):
            v = v[:i]
            break
    return v.strip()


@dataclass(frozen=True)
class Settings:
    env: str = "local"
    app_title: str = "상담사 360"
    data_backend: str = "sample"
    gcp_project: str = ""
    bq_location: str = "asia-northeast3"
    common_dataset: str = "common"
    module_dataset: str = "agent360"
    capacity_dataset: str = "capacity"
    roster_dataset: str = "roster"
    iap_audience: str = ""
    allowed_domains: tuple[str, ...] = ()
    dev_user: str = "sv.kim@example.com"
    sample_dir: Path = field(default_factory=lambda: BASE_DIR / "sample_data")
    cache_seconds: int = 60
    ai_agent_project: str = ""
    ai_agent_location: str = "global"
    ai_agent_id: str = ""
    ai_agent_label: str = "AI BA CHAT (Volume)"
    ai_quota_project: str = ""
    ai_timeout: int = 280

    @property
    def ai_enabled(self) -> bool:
        return bool(self.ai_agent_project and self.ai_agent_id)

    @property
    def is_local(self) -> bool:
        return self.env == "local"


@lru_cache
def get_settings() -> Settings:
    _load_dotenv(BASE_DIR / ".env")
    e = lambda k, d="": _clean_value(os.environ.get(k, d))  # noqa: E731
    env = e("ENV", "local").lower()
    if env not in ("local", "prod"):
        raise ValueError(f"ENV 는 local 또는 prod 여야 합니다 (지금 값: {env!r}). .env 를 확인하세요.")
    backend = e("DATA_BACKEND", "sample").lower()
    if backend not in ("sample", "bigquery"):
        raise ValueError(f"DATA_BACKEND 는 sample 또는 bigquery 여야 합니다 (지금 값: {backend!r}).")
    return Settings(
        env=env,
        app_title=e("APP_TITLE", "상담사 360"),
        data_backend=backend,
        gcp_project=e("GCP_PROJECT", ""),
        bq_location=e("BQ_LOCATION", "asia-northeast3"),
        common_dataset=e("COMMON_DATASET", "common"),
        module_dataset=e("MODULE_DATASET", "agent360"),
        capacity_dataset=e("CAPACITY_DATASET", "capacity"),
        roster_dataset=e("ROSTER_DATASET", "roster"),
        iap_audience=e("IAP_AUDIENCE", ""),
        allowed_domains=tuple(d.strip().lower().lstrip("@") for d in e("ALLOWED_DOMAINS", "").split(",") if d.strip()),
        dev_user=e("DEV_USER", "sv.kim@example.com"),
        sample_dir=Path(e("SAMPLE_DIR", str(BASE_DIR / "sample_data"))),
        cache_seconds=int(e("CACHE_SECONDS", "60")),
        ai_agent_project=e("AI_AGENT_PROJECT", ""),
        ai_agent_location=e("AI_AGENT_LOCATION", "global"),
        ai_agent_id=e("AI_AGENT_ID", ""),
        ai_agent_label=e("AI_AGENT_LABEL", "AI BA CHAT (Volume)"),
        ai_quota_project=e("AI_QUOTA_PROJECT", ""),
        ai_timeout=int(e("AI_TIMEOUT", "280")),
    )
