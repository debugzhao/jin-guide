from __future__ import annotations

import asyncio

import httpx

from data_pipeline.config import SourceConfig
from data_pipeline.raw_store import RawArtifactStore, StoredArtifact


class CollectionError(RuntimeError):
    pass


class HttpCollector:
    def __init__(
        self,
        store: RawArtifactStore,
        *,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.store = store
        self._client = client

    async def collect(self, province: str, source: SourceConfig) -> StoredArtifact:
        if not source.enabled:
            raise CollectionError(f"source {source.id!r} is disabled")
        if source.collection_method != "http":
            raise CollectionError(
                f"source {source.id!r} requires {source.collection_method}, not http"
            )

        owns_client = self._client is None
        client = self._client or httpx.AsyncClient(
            follow_redirects=True,
            headers={"User-Agent": "WenjinAdmissionDataCollector/0.1 (+official-data-only)"},
        )
        try:
            response = await self._request_with_retries(client, source)
            content = response.content
            if len(content) > source.max_download_bytes:
                raise CollectionError(
                    f"source {source.id!r} returned {len(content)} bytes; "
                    f"limit is {source.max_download_bytes}"
                )
            if not content:
                raise CollectionError(f"source {source.id!r} returned an empty response")
            return self.store.save(
                province=province,
                source=source,
                content=content,
                content_type=response.headers.get("content-type"),
                final_url=str(response.url),
            )
        finally:
            if owns_client:
                await client.aclose()

    async def _request_with_retries(
        self, client: httpx.AsyncClient, source: SourceConfig
    ) -> httpx.Response:
        last_error: Exception | None = None
        for attempt in range(source.max_retries + 1):
            try:
                if source.request_method == "POST":
                    response = await client.post(
                        str(source.entry_url),
                        json=source.request_body or {},
                        timeout=source.timeout_seconds,
                    )
                else:
                    response = await client.get(
                        str(source.entry_url), timeout=source.timeout_seconds
                    )
                response.raise_for_status()
                return response
            except (httpx.HTTPError, httpx.TimeoutException) as exc:
                last_error = exc
                if attempt < source.max_retries:
                    await asyncio.sleep(min(0.25 * (2**attempt), 1.0))
        raise CollectionError(
            f"failed to collect source {source.id!r} after "
            f"{source.max_retries + 1} attempt(s): {last_error}"
        ) from last_error
