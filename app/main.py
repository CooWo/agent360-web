"""앱 진입점 — 모듈을 자동으로 등록한다. (새 모듈을 추가해도 이 파일은 그대로)

실행: uvicorn app.main:app --reload
API 문서: /api/docs
"""
from __future__ import annotations

from pathlib import Path
from urllib.parse import quote

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.config import get_settings
from app.core.data import get_backend
from app.core.errors import InvalidInput, NotFound, PermissionDenied
from app.core.modules import discover
from app.core.templating import render

APP_DIR = Path(__file__).resolve().parent
settings = get_settings()

app = FastAPI(title=f"{settings.app_title} API", docs_url="/api/docs", openapi_url="/api/openapi.json", redoc_url=None)
app.mount("/static", StaticFiles(directory=APP_DIR / "static"), name="static")

MODULES = discover()
for m in MODULES:
    if m.page_router:
        app.include_router(m.page_router)
    if m.api_router:
        app.include_router(m.api_router)


@app.get("/", include_in_schema=False)
def root():
    return RedirectResponse(MODULES[0].base_path if MODULES else "/api/docs")


@app.get("/healthz", include_in_schema=False)
def healthz():
    return {"ok": True, "env": settings.env, "backend": settings.data_backend}


@app.get("/dev/switch", include_in_schema=False)
def dev_switch(email: str, next: str = "/"):  # noqa: A002
    """local 전용: 화면 상단에서 사용자를 바꿔 SV·매니저 화면을 확인."""
    if not settings.is_local:
        return JSONResponse({"detail": "not available"}, status_code=404)
    resp = RedirectResponse(next if next.startswith("/") else "/", status_code=303)
    resp.set_cookie("dev_user", email, httponly=True, samesite="lax")
    return resp


# ── 오류 처리: API 는 JSON, 화면은 오류 페이지 ──────────────────
def _error(request: Request, status: int, message: str, errors: dict | None = None):
    if request.url.path.startswith("/api/"):
        body = {"detail": message}
        if errors:
            body["errors"] = errors
        return JSONResponse(body, status_code=status)
    user = getattr(request.state, "user", None)
    html = render("errors/error.html", {"status": status, "message": message, "path": quote(request.url.path)},
                  user=user, users_for_switch=get_backend().list_users() if settings.is_local else [])
    return HTMLResponse(html, status_code=status)


@app.exception_handler(StarletteHTTPException)
async def http_error(request: Request, exc: StarletteHTTPException):
    msg = exc.detail if isinstance(exc.detail, str) else "요청을 처리할 수 없습니다."
    if exc.status_code == 404 and msg == "Not Found":
        msg = "페이지를 찾을 수 없습니다."
    return _error(request, exc.status_code, msg)


@app.exception_handler(PermissionDenied)
async def denied(request: Request, exc: PermissionDenied):
    return _error(request, 403, str(exc) or "권한이 없습니다.")


@app.exception_handler(NotFound)
async def not_found(request: Request, exc: NotFound):
    return _error(request, 404, str(exc) or "찾을 수 없습니다.")


@app.exception_handler(InvalidInput)
async def invalid(request: Request, exc: InvalidInput):
    return _error(request, 400, "입력값을 확인해 주세요.", exc.errors)


@app.exception_handler(RequestValidationError)
async def validation(request: Request, exc: RequestValidationError):
    errs = {".".join(str(x) for x in e["loc"][1:]): e["msg"] for e in exc.errors()}
    return _error(request, 422, "입력 형식이 올바르지 않습니다.", errs)
