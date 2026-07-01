from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.config import Settings, get_settings

_bearer = HTTPBearer(auto_error=False)


def _api_key(request: Request, credentials: HTTPAuthorizationCredentials | None) -> str | None:
    if credentials and credentials.scheme.lower() == "bearer":
        return credentials.credentials
    return request.headers.get("X-API-Key")


async def require_api_key(
    request: Request,
    settings: Settings = Depends(get_settings),
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> None:
    if not (settings.auth_enabled and settings.auth_api_key_enabled):
        return
    if _api_key(request, credentials) in settings.accepted_api_keys:
        return
    raise HTTPException(status_code=401, detail="需要有效的 API Key（Authorization: Bearer <key> 或 X-API-Key）。")
