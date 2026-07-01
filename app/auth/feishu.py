from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlencode

import httpx

from app.config import Settings

AUTH_SCOPE = "contact:user.email:readonly contact:user.base:readonly"


class FeishuOAuthError(Exception):
    pass


@dataclass(frozen=True)
class FeishuUser:
    open_id: str
    name: str | None
    email: str | None


def build_authorize_url(settings: Settings, state: str, redirect_uri: str) -> str:
    params = {
        "client_id": settings.feishu_app_id or "",
        "redirect_uri": redirect_uri,
        "scope": AUTH_SCOPE,
        "state": state,
        "response_type": "code",
    }
    return f"{settings.feishu_auth_base}/open-apis/authen/v1/authorize?{urlencode(params)}"


async def exchange_code(settings: Settings, code: str, redirect_uri: str) -> str:
    payload = {
        "grant_type": "authorization_code",
        "client_id": settings.feishu_app_id,
        "client_secret": settings.feishu_app_secret,
        "code": code,
        "redirect_uri": redirect_uri,
    }
    async with httpx.AsyncClient(timeout=settings.http_timeout_seconds) as client:
        response = await client.post(f"{settings.feishu_api_base}/open-apis/authen/v2/oauth/token", json=payload)
    data = response.json()
    if data.get("code") not in (0, None):
        raise FeishuOAuthError(data.get("error_description") or data.get("msg") or "飞书换 token 失败")
    token = data.get("access_token")
    if not token:
        raise FeishuOAuthError("飞书未返回 access_token")
    return token


async def fetch_user_info(settings: Settings, access_token: str) -> FeishuUser:
    async with httpx.AsyncClient(timeout=settings.http_timeout_seconds) as client:
        response = await client.get(
            f"{settings.feishu_api_base}/open-apis/authen/v1/user_info",
            headers={"Authorization": f"Bearer {access_token}"},
        )
    data = response.json()
    if data.get("code") != 0:
        raise FeishuOAuthError(data.get("msg") or "飞书获取用户信息失败")
    user = data.get("data") or {}
    if not user.get("open_id"):
        raise FeishuOAuthError("飞书用户信息缺少 open_id")
    return FeishuUser(user["open_id"], user.get("name"), user.get("email"))
