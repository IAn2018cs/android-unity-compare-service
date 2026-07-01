from pathlib import Path
from urllib.parse import quote
from zipfile import is_zipfile

import httpx

from app.config import Settings
from app.models import VersionRef


class ApsClient:
    def __init__(self, settings: Settings):
        self.settings = settings

    async def download(self, package_name: str, version: VersionRef, target: Path) -> Path:
        params = {}
        if version.version_code:
            params["versionCode"] = version.version_code
        elif version.version_name:
            params["versionName"] = version.version_name
        headers = {"Authorization": f"Bearer {self.settings.aps_api_key}"} if self.settings.aps_api_key else {}
        url = f"{self.settings.aps_base_url.rstrip('/')}/api/v1/android/apps/{quote(package_name)}/download"
        async with httpx.AsyncClient(follow_redirects=True, timeout=self.settings.aps_download_timeout_seconds) as client:
            response = await client.get(url, params=params, headers=headers)
            if response.status_code == 202:
                response = await self._wait_job(client, response.json(), headers)
            response.raise_for_status()
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(response.content)
        if not target.exists() or target.stat().st_size == 0 or not is_zipfile(target):
            raise ValueError(f"APS returned an invalid package file: {target}")
        return target

    async def _wait_job(self, client: httpx.AsyncClient, data: dict, headers: dict[str, str]) -> httpx.Response:
        import asyncio

        status_url = data.get("statusUrl")
        if not status_url:
            raise ValueError("APS 202 response missing statusUrl")
        while True:
            status = await client.get(status_url, headers=headers)
            status.raise_for_status()
            body = status.json()
            if body.get("status") == "failed":
                raise ValueError(body.get("error") or "APS download job failed")
            if body.get("status") == "succeeded":
                file_url = body.get("fileUrl")
                if not file_url:
                    raise ValueError("APS job succeeded without fileUrl")
                return await client.get(file_url, headers=headers)
            await asyncio.sleep(self.settings.aps_job_poll_seconds)
