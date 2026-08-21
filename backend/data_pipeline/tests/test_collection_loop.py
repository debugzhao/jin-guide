from __future__ import annotations

import asyncio
import json

import httpx
import pytest
from pydantic import ValidationError

from data_pipeline.collectors import CollectionError, HttpCollector
from data_pipeline.config import PipelineConfig, SourceConfig, load_pipeline_config
from data_pipeline.raw_store import RawArtifactStore
from data_pipeline.validators import WhitelistViolation, require_whitelisted_university


def _source(**overrides) -> SourceConfig:
    payload = {
        "id": "jseea-policy-2026",
        "name": "江苏省教育考试院 2026 招生政策",
        "entry_url": "https://example.test/policy.pdf",
        "data_type": "policy",
        "year": 2026,
        "collection_method": "http",
        "parser": "policy_pdf_v1",
        "max_retries": 0,
    }
    payload.update(overrides)
    return SourceConfig.model_validate(payload)


def test_default_config_fails_closed_for_publication() -> None:
    config = PipelineConfig(province="江苏")
    with pytest.raises(WhitelistViolation, match="whitelist is empty"):
        require_whitelisted_university(
            university_code="10284", university_name="南京大学", config=config
        )


def test_jiangsu_config_freezes_ten_universities_and_official_sources() -> None:
    config = load_pipeline_config("data_pipeline/configs/jiangsu.yaml")
    assert len(config.target_universities) == 10
    assert {item.university_code for item in config.target_universities} == {
        "10284", "10285", "10286", "10287", "10288",
        "10290", "10294", "10295", "10307", "10316",
    }
    assert config.sources
    assert all(source.authority_level == "official" for source in config.sources)


def test_config_rejects_source_outside_whitelist() -> None:
    with pytest.raises(ValidationError, match="outside the whitelist"):
        PipelineConfig.model_validate(
            {
                "province": "江苏",
                "target_universities": [
                    {"university_code": "10284", "name": "南京大学"}
                ],
                "sources": [
                    _source(target_university_code="10286").model_dump(mode="json")
                ],
            }
        )


def test_http_collection_is_content_addressed_and_idempotent(tmp_path) -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(
            200,
            content=b"%PDF-1.7 official fixture",
            headers={"content-type": "application/pdf"},
            request=request,
        )

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            collector = HttpCollector(RawArtifactStore(tmp_path), client=client)
            first = await collector.collect("江苏", _source())
            second = await collector.collect("江苏", _source())
            return first, second

    first, second = asyncio.run(run())
    assert calls == 2
    assert first.changed is True
    assert second.changed is False
    assert first.checksum == second.checksum
    assert first.content_path == second.content_path
    assert first.content_path.read_bytes() == b"%PDF-1.7 official fixture"

    metadata = json.loads(first.metadata_path.read_text(encoding="utf-8"))
    assert metadata["source_url"] == "https://example.test/policy.pdf"
    assert metadata["checksum_sha256"] == first.checksum
    assert metadata["parser"] == "policy_pdf_v1"


def test_http_collection_rejects_oversized_response(tmp_path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"12345", request=request)

    async def run() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            collector = HttpCollector(RawArtifactStore(tmp_path), client=client)
            await collector.collect("江苏", _source(max_download_bytes=4))

    with pytest.raises(CollectionError, match="limit is 4"):
        asyncio.run(run())


def test_collection_repairs_missing_sidecar_without_duplicating_content(tmp_path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"official", request=request)

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            collector = HttpCollector(RawArtifactStore(tmp_path), client=client)
            first = await collector.collect("江苏", _source())
            first.metadata_path.unlink()
            second = await collector.collect("江苏", _source())
            return first, second

    first, second = asyncio.run(run())
    assert second.changed is False
    assert second.content_path == first.content_path
    assert second.metadata_path.exists()


def test_whitelist_requires_matching_code_and_name() -> None:
    config = PipelineConfig.model_validate(
        {
            "province": "江苏",
            "target_universities": [
                {"university_code": "10284", "name": "南京大学"}
            ],
        }
    )
    require_whitelisted_university(
        university_code="10284", university_name="南京大学", config=config
    )
    with pytest.raises(WhitelistViolation, match="name mismatch"):
        require_whitelisted_university(
            university_code="10284", university_name="南京大學", config=config
        )
