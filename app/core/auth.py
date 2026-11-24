"""로그인 — 누가 접속했는지 이메일을 정하고, 역할표(user_roles)에서 권한을 찾는다.

prod  : Cloud Run 앞의 IAP(구글 워크스페이스 SSO)가 로그인을 처리한다.
        IAP 가 넣어 주는 헤더 X-Goog-Authenticated-User-Email 을 읽고,
        IAP_AUDIENCE 가 있으면 X-Goog-IAP-JWT-Assertion 서명까지 검증한다.
local : 로그인 없이 쿠키 dev_user(또는 DEV_USER)로 사용자를 흉내 낸다. 화면 상단에서 전환.
웹 프레임워크와 무관한 순수 함수로 두어, FastAPI 의존성(deps.py)과 테스트가 같이 쓴다.
"""
from __future__ import annotations

from collections.abc import Mapping

from app.core.config import Settings
from app.core.permissions import User

IAP_EMAIL_HEADER = "x-goog-authenticated-user-email"
IAP_JWT_HEADER = "x-goog-iap-jwt-assertion"
DEV_COOKIE = "dev_user"


class AuthError(Exception):
    """로그인 정보가 없거나 검증 실패."""


class NotRegistered(Exception):
    """로그인은 됐지만 역할표에 없는 사용자."""

    def __init__(self, email: str):
        super().__init__(email)
        self.email = email


def _verify_iap_jwt(token: str, audience: str) -> str:
    from google.auth.transport import requests as g_requests  # 지연 import (prod 에서만 필요)
    from google.oauth2 import id_token

    claims = id_token.verify_token(
        token, g_requests.Request(), audience=audience,
        certs_url="https://www.gstatic.com/iap/verify/public_key",
    )
    return claims["email"]


def _check_domain(email: str, settings: Settings) -> str:
    """prod 에서 회사 도메인(ALLOWED_DOMAINS)이 아니면 막는다. IAP 그룹 설정이 잘못돼도 한 번 더 지킨다."""
    if settings.allowed_domains and email.rsplit("@", 1)[-1] not in settings.allowed_domains:
        raise AuthError(f"허용되지 않은 도메인: {email}")
    return email


def resolve_email(headers: Mapping[str, str], cookies: Mapping[str, str], settings: Settings) -> str:
    """요청에서 로그인 이메일을 꺼낸다. headers 키는 소문자로 비교."""
    if settings.is_local:
        return (cookies.get(DEV_COOKIE) or settings.dev_user).strip().lower()
    return _check_domain(_resolve_prod(headers, settings), settings)


def _resolve_prod(headers: Mapping[str, str], settings: Settings) -> str:
    h = {k.lower(): v for k, v in headers.items()}

    if settings.iap_audience:
        token = h.get(IAP_JWT_HEADER)
        if not token:
            raise AuthError("IAP 토큰 없음")
        try:
            return _verify_iap_jwt(token, settings.iap_audience).lower()
        except Exception as e:  # noqa: BLE001
            raise AuthError(f"IAP 토큰 검증 실패: {e}") from e

    raw = h.get(IAP_EMAIL_HEADER, "")
    if not raw:
        raise AuthError("IAP 로그인 헤더 없음")
    return raw.split(":", 1)[-1].strip().lower()   # "accounts.google.com:user@x.com"


def load_user(email: str, backend) -> User:
    """역할표에서 사용자를 찾는다. 없으면 NotRegistered."""
    row = backend.get_user(email)
    if not row:
        raise NotRegistered(email)
    return User(email=row["email"], name=row.get("name") or row["email"],
                role=row["role"], teams=tuple(row.get("teams") or ()))
