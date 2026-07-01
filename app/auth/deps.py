from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from urllib.parse import quote

from app.config import Settings, get_settings
from app.auth.service import AdminUser, ApiKey, AuthService

SESSION_COOKIE = "auc_session"
API_KEY_HEADER = "X-API-Key"
_bearer = HTTPBearer(auto_error=False)


def _api_key(request: Request, credentials: HTTPAuthorizationCredentials | None) -> str | None:
    if credentials and credentials.scheme.lower() == "bearer":
        return credentials.credentials
    return request.headers.get(API_KEY_HEADER)


def get_auth_service(settings: Settings = Depends(get_settings)) -> AuthService:
    return AuthService(settings.auth_db_path, session_ttl_hours=settings.session_ttl_hours)


def _load_admin(request: Request, service: AuthService) -> AdminUser | None:
    session = service.get_session(request.cookies.get(SESSION_COOKIE))
    if session is None:
        return None
    admin = service.get_admin()
    if admin is None or admin.open_id != session.open_id:
        return None
    return admin


async def require_admin_session(request: Request, settings: Settings = Depends(get_settings)) -> AdminUser | None:
    if not settings.auth_enabled:
        return None
    admin = _load_admin(request, get_auth_service(settings))
    if admin is None:
        next_url = request.url.path + (f"?{request.url.query}" if request.url.query else "")
        raise HTTPException(status_code=302, headers={"Location": f"/auth/login?next={quote(next_url, safe='')}"})
    return admin


async def require_api_key(
    request: Request,
    settings: Settings = Depends(get_settings),
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> ApiKey | None:
    if not (settings.auth_enabled and settings.auth_api_key_enabled):
        return None
    raw = _api_key(request, credentials)
    if raw in settings.accepted_api_keys:
        return None
    key = get_auth_service(settings).verify_api_key(raw)
    if key is not None:
        return key
    raise HTTPException(status_code=401, detail="需要有效的 API Key（Authorization: Bearer <key> 或 X-API-Key）。")
