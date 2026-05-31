"""Cliente liviano para consultar la API v2 de GeoNode."""
from __future__ import annotations

from typing import Any

import httpx

from .config import settings


class GeoNodeClient:
    """Consulta la API v2 de GeoNode usando el host interno del compose."""

    def __init__(self) -> None:
        self._base = settings.geonode_base_url.rstrip("/")
        self._host = settings.geonode_host_header

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            timeout=30,
            follow_redirects=True,
            headers={"Host": self._host},
        )

    async def list_datasets(self, page_size: int = 50) -> list[dict[str, Any]]:
        url = f"{self._base}/api/v2/datasets?page_size={page_size}"
        async with self._client() as client:
            r = await client.get(url)
            r.raise_for_status()
            return r.json().get("datasets", [])

    async def get_dataset(self, alternate: str) -> dict[str, Any] | None:
        url = f"{self._base}/api/v2/datasets?filter{{alternate}}={alternate}"
        async with self._client() as client:
            r = await client.get(url)
            r.raise_for_status()
            results = r.json().get("datasets", [])
            return results[0] if results else None

    async def ping(self) -> bool:
        try:
            async with self._client() as client:
                # /api/v2/ es mas estable como ping que /
                r = await client.get(f"{self._base}/api/v2/", timeout=5)
                return r.status_code < 500
        except httpx.HTTPError:
            return False


geonode = GeoNodeClient()
