from __future__ import annotations

import asyncio
import json

import httpx

from data_pipeline.config import PipelineConfig, SourceConfig, load_pipeline_config
from data_pipeline.jobs import PipelineJob


def test_job_discovers_parses_validates_and_skips_unchanged_content(tmp_path) -> None:
    base = load_pipeline_config("data_pipeline/configs/jiangsu.yaml")
    source = SourceConfig.model_validate(
        {
            "id": "fixture-score",
            "name": "投档线 fixture",
            "entry_url": "https://official.test/index.html",
            "data_type": "admission_score",
            "year": 2025,
            "parser": "fixture_v1",
            "discovery_title_pattern": "物理类投档线",
            "discovery_depth": 1,
            "max_retries": 0,
        }
    )
    config = PipelineConfig(
        province="江苏", target_universities=base.target_universities, sources=[source]
    )

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/index.html":
            content = '<a href="/physics.csv">物理类投档线</a>'.encode()
            return httpx.Response(200, content=content, headers={"content-type": "text/html"})
        content = "院校代号,院校专业组,投档最低分\n1101,南京大学07专业组(化学),661\n".encode(
            "utf-8"
        )
        return httpx.Response(200, content=content, headers={"content-type": "text/csv"})

    async def run_twice():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            job = PipelineJob(
                config=config,
                raw_root=tmp_path / "raw",
                report_root=tmp_path / "reports",
                client=client,
            )
            return await job.run_source(source.id), await job.run_source(source.id)

    first, second = asyncio.run(run_twice())
    assert first.status == "succeeded"
    assert first.artifacts == 2
    assert first.parsed_records == 1
    assert first.review_records == 1  # min_rank awaits exact rank-segment join
    assert second.unchanged_artifacts == 2
    assert second.parsed_records == 0
    report_path = next((tmp_path / "reports").glob("fixture-score-*.json"))
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["status"] == "succeeded"


def test_policy_job_extracts_only_retrieval_relevant_text(tmp_path) -> None:
    source = SourceConfig.model_validate(
        {
            "id": "fixture-policy",
            "name": "政策 fixture",
            "entry_url": "https://official.test/policy.html",
            "data_type": "policy",
            "year": 2025,
            "parser": "policy_v1",
            "discovery_depth": 0,
            "max_retries": 0,
        }
    )
    config = PipelineConfig(province="江苏", sources=[source])

    def handler(request: httpx.Request) -> httpx.Response:
        html = (
            "<p>网站导航</p><p>本科批实行平行志愿，可填报40个院校专业组志愿，"
            "按照考生投档分排序录取。</p><p>版权信息</p>"
        )
        return httpx.Response(
            200, content=html.encode(), headers={"content-type": "text/html"}
        )

    async def run_once():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            job = PipelineJob(
                config=config,
                raw_root=tmp_path / "raw",
                report_root=tmp_path / "reports",
                client=client,
            )
            return await job.run_source(source.id)

    report = asyncio.run(run_once())
    assert report.status == "succeeded"
    assert report.parsed_records == 2
    assert report.valid_records == 2
