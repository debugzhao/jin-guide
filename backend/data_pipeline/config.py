from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field, HttpUrl, model_validator


DataType = Literal[
    "policy",
    "rank_segment",
    "admission_plan",
    "admission_score",
    "charter",
    "major_intro",
    "transfer_policy",
    "university_master",
    "major_master",
]
CollectionMethod = Literal["http", "playwright", "manual"]
AuthorityLevel = Literal["official", "semi-official", "authorized"]


class TargetUniversity(BaseModel):
    university_code: str = Field(min_length=1, max_length=20)
    name: str = Field(min_length=1, max_length=200)
    city: str | None = Field(default=None, max_length=50)
    ownership: Literal["central", "provincial"] | None = None
    admissions_url: HttpUrl | None = None


class SourceConfig(BaseModel):
    id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]*$")
    name: str = Field(min_length=1, max_length=200)
    entry_url: HttpUrl
    data_type: DataType
    year: int | None = Field(default=None, ge=2021, le=2100)
    target_university_code: str | None = Field(default=None, max_length=20)
    collection_method: CollectionMethod = "http"
    parser: str = Field(min_length=1, max_length=100)
    update_frequency: str = Field(default="manual", min_length=1, max_length=50)
    authority_level: AuthorityLevel = "official"
    enabled: bool = True
    timeout_seconds: float = Field(default=30.0, gt=0, le=120)
    max_retries: int = Field(default=2, ge=0, le=5)
    max_download_bytes: int = Field(default=50 * 1024 * 1024, gt=0)
    discovery_title_pattern: str | None = Field(default=None, max_length=500)
    discovery_depth: int = Field(default=1, ge=0, le=2)
    # 部分JS单页应用背后的查询接口只接受POST+JSON body（已用浙江师范大学
    # lqcx.zjnu.edu.cn/lqxx/s/api/front/lqxx/getList真实验证：GET同参数返回
    # HTTP 500 "Request method 'GET' not supported"），Access-Control-Allow-
    # Origin锁定同源只影响浏览器fetch，httpx等服务端客户端不受CORS限制，
    # 直接POST能拿到跟浏览器里完全一样的数据，不需要用Playwright采集
    request_method: Literal["GET", "POST"] = "GET"
    request_body: dict | None = None


class PipelineConfig(BaseModel):
    province: str = Field(min_length=1, max_length=50)
    target_universities: list[TargetUniversity] = Field(default_factory=list)
    sources: list[SourceConfig] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_unique_keys(self) -> "PipelineConfig":
        codes = [item.university_code for item in self.target_universities]
        names = [item.name for item in self.target_universities]
        source_ids = [item.id for item in self.sources]
        for label, values in (
            ("target university code", codes),
            ("target university name", names),
            ("source id", source_ids),
        ):
            if len(values) != len(set(values)):
                raise ValueError(f"duplicate {label} in pipeline config")

        allowed_codes = set(codes)
        unknown_codes = {
            source.target_university_code
            for source in self.sources
            if source.target_university_code
            and source.target_university_code not in allowed_codes
        }
        if unknown_codes:
            raise ValueError(
                "sources reference universities outside the whitelist: "
                + ", ".join(sorted(unknown_codes))
            )
        return self


def load_pipeline_config(path: str | Path) -> PipelineConfig:
    config_path = Path(path)
    payload = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    return PipelineConfig.model_validate(payload)
