from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.auth import feishu
from app.auth.deps import SESSION_COOKIE, get_auth_service
from app.auth.feishu import FeishuOAuthError
from app.auth.service import AdminSeatTakenError, AuthService
from app.config import Settings, get_settings

auth_router = APIRouter(prefix="/auth")


def _redirect_uri(settings: Settings) -> str:
    return f"{settings.public_base_url.rstrip('/')}/auth/callback"


def _safe_next(value: str | None) -> str:
    return value if value and value.startswith("/") and not value.startswith("//") else "/admin"


def _page(message: str, status_code: int = 200) -> HTMLResponse:
    return HTMLResponse(
        f"<!doctype html><meta charset='utf-8'><body style='font-family:system-ui;margin:3rem'>{message}</body>",
        status_code=status_code,
    )


@auth_router.get("/login")
async def login(
    next: str = "/admin",
    settings: Settings = Depends(get_settings),
    service: AuthService = Depends(get_auth_service),
):
    if not settings.auth_enabled:
        return RedirectResponse(_safe_next(next), status_code=302)
    state = service.create_oauth_state(_safe_next(next))
    return RedirectResponse(feishu.build_authorize_url(settings, state, _redirect_uri(settings)), status_code=302)


@auth_router.get("/callback")
async def callback(
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    settings: Settings = Depends(get_settings),
    service: AuthService = Depends(get_auth_service),
):
    if error:
        return _page("授权被拒绝。", 400)
    ok, next_url = service.consume_oauth_state(state)
    if not code or not ok:
        return _page("无效或已过期的登录请求。", 400)
    try:
        token = await feishu.exchange_code(settings, code, _redirect_uri(settings))
        user = await feishu.fetch_user_info(settings, token)
        service.register_or_check_admin(user.open_id, user.name, user.email)
    except FeishuOAuthError as exc:
        return _page(f"飞书授权失败：{exc}", 502)
    except AdminSeatTakenError:
        return _page("本服务仅允许一个管理员，注册名额已被占用。", 403)
    session = service.create_session(user.open_id)
    response = RedirectResponse(next_url or "/admin", status_code=302)
    response.set_cookie(
        SESSION_COOKIE,
        session.id,
        httponly=True,
        samesite="lax",
        secure=settings.public_base_url.startswith("https://"),
        max_age=int(settings.session_ttl_hours * 3600),
    )
    return response


@auth_router.get("/logout")
async def logout(request: Request, service: AuthService = Depends(get_auth_service)):
    session_id = request.cookies.get(SESSION_COOKIE)
    if session_id:
        service.delete_session(session_id)
    response = RedirectResponse("/", status_code=302)
    response.delete_cookie(SESSION_COOKIE)
    return response
