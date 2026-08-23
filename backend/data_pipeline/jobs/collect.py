from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse

import httpx

from data_pipeline.collectors import HttpCollector
from data_pipeline.config import PipelineConfig, SourceConfig
from data_pipeline.discovery import discover_links
from data_pipeline.text_encoding import decode_html_bytes
from data_pipeline.parsers import (
    chunk_document,
    extract_policy_rule,
    extract_document_text,
    parse_admission_score_rows,
    parse_admission_plan_rows,
    parse_rank_segment_rows,
    parse_shmeea_admission_score_rows,
    parse_single_university_admission_plan_rows,
    parse_single_university_admission_result_rows,
    parse_zhejiang_admission_score_rows,
    read_tabular_document,
)
from data_pipeline.raw_store import RawArtifactStore, StoredArtifact
from data_pipeline.records import Provenance
from data_pipeline.validators import validate_records

if TYPE_CHECKING:
    from sqlalchemy.orm import Session
else:
    Session = Any


@dataclass
class SourceRunReport:
    source_id: str
    status: str = "running"
    started_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    finished_at: str | None = None
    artifacts: int = 0
    unchanged_artifacts: int = 0
    parsed_records: int = 0
    valid_records: int = 0
    review_records: int = 0
    rejected_records: int = 0
    staging_path: str | None = None
    messages: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class _ArtifactNode:
    artifact: StoredArtifact
    title: str
    depth: int


class PipelineJob:
    def __init__(
        self,
        *,
        config: PipelineConfig,
        raw_root: str | Path,
        report_root: str | Path,
        session: Session | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.config = config
        self.raw_root = Path(raw_root)
        self.report_root = Path(report_root)
        self.session = session
        self.client = client

    async def run_source(self, source_id: str) -> SourceRunReport:
        source = next((item for item in self.config.sources if item.id == source_id), None)
        if source is None:
            raise ValueError(f"unknown source id: {source_id}")
        report = SourceRunReport(source_id=source.id)
        report.staging_path = str(self._staging_path(report))
        if self.session:
            from data_pipeline.loaders import PipelineRepository

            repository = PipelineRepository(self.session)
        else:
            repository = None
        run = None
        try:
            if repository:
                repository.sync_sources(self.config)
                run = repository.start_run(source.id)
            nodes = await self._collect_graph(source, report)
            for node in nodes:
                document_model = None
                is_new = node.artifact.changed
                if repository and run:
                    document_model, is_new = repository.register_document(
                        run=run,
                        source=source,
                        artifact=node.artifact,
                        title=node.title or source.name,
                    )
                if not is_new:
                    continue
                document_id = document_model.id if document_model else node.artifact.checksum
                validated = self._parse_node(source, node, document_id, report)
                if repository and run and document_model and validated:
                    repository.stage_records(
                        run=run, document=document_model, records=validated
                    )
            if repository and run:
                repository.finish_run(run)
                self.session.commit()
            report.status = "succeeded"
        except Exception as exc:
            report.status = "failed"
            report.messages.append(f"{exc.__class__.__name__}: {exc}")
            if repository and run:
                repository.finish_run(run, error=exc)
                self.session.commit()
        finally:
            report.finished_at = datetime.now(UTC).isoformat()
            self._write_report(report)
        return report

    async def run_all(self) -> list[SourceRunReport]:
        reports: list[SourceRunReport] = []
        for source in self.config.sources:
            if source.enabled:
                reports.append(await self.run_source(source.id))
        return reports

    async def _collect_graph(
        self, source: SourceConfig, report: SourceRunReport
    ) -> list[_ArtifactNode]:
        collector = HttpCollector(RawArtifactStore(self.raw_root), client=self.client)
        root = await collector.collect(self.config.province, source)
        nodes = [_ArtifactNode(root, source.name, 0)]
        seen_urls = {root.source_url}
        cursor = 0
        while cursor < len(nodes):
            node = nodes[cursor]
            cursor += 1
            if node.depth >= source.discovery_depth:
                continue
            if node.artifact.content_path.suffix.lower() not in {".html", ".htm"}:
                continue
            html = decode_html_bytes(node.artifact.content_path.read_bytes())
            links = discover_links(
                html,
                base_url=node.artifact.source_url,
                title_pattern=source.discovery_title_pattern,
                include_pages=True,
            )
            for link in links:
                if link.url in seen_urls:
                    continue
                seen_urls.add(link.url)
                child_payload = source.model_dump(mode="json")
                child_payload.update({"entry_url": link.url, "discovery_depth": 0})
                child_source = SourceConfig.model_validate(child_payload)
                try:
                    artifact = await collector.collect(self.config.province, child_source)
                except Exception as exc:
                    report.messages.append(f"attachment failed: {link.url}: {exc}")
                    continue
                nodes.append(_ArtifactNode(artifact, link.title, node.depth + 1))
        report.artifacts = len(nodes)
        report.unchanged_artifacts = sum(not node.artifact.changed for node in nodes)
        return nodes

    def _parse_node(
        self,
        source: SourceConfig,
        node: _ArtifactNode,
        document_id: str,
        report: SourceRunReport,
    ) -> list:
        provenance = Provenance(
            source_url=node.artifact.source_url,
            source_document_id=document_id,
            source_title=node.title or source.name,
            year=source.year or datetime.now(UTC).year,
            authority_level=source.authority_level,
            collected_at=node.artifact.collected_at,
            parser_version=source.parser,
        )
        suffix = node.artifact.content_path.suffix.lower()
        records = []
        try:
            if source.data_type in {"policy", "charter", "major_intro", "transfer_policy"}:
                if suffix not in {".html", ".htm", ".pdf", ".docx"}:
                    return []
                text = extract_document_text(node.artifact.content_path)
                records = chunk_document(
                    text,
                    document_type=source.data_type,
                    provenance=provenance,
                    province=self.config.province,
                    university_code=source.target_university_code,
                )
                if source.data_type == "policy":
                    records.append(
                        extract_policy_rule(
                            text, provenance=provenance, province=self.config.province
                        )
                    )
            elif source.data_type in {"rank_segment", "admission_score", "admission_plan"}:
                if suffix not in {
                    ".csv", ".xlsx", ".xls", ".pdf", ".jpg", ".jpeg", ".png", ".html", ".htm",
                }:
                    return []
                subject_type = self._infer_subject(node.title, node.artifact.source_url)
                if subject_type is None:
                    report.messages.append(
                        f"manual review: cannot infer subject type for {node.artifact.source_url}"
                    )
                    return []
                document = read_tabular_document(node.artifact.content_path)
                if source.data_type == "rank_segment":
                    records = parse_rank_segment_rows(
                        document,
                        subject_type=subject_type,
                        provenance=provenance,
                        config=self.config,
                    )
                elif source.data_type == "admission_score":
                    if self.config.province == "浙江" and source.target_university_code:
                        # 学校自己"历年招生"栏目发布的录取情况页（带平均分/最高分/
                        # 实际录取人数，省考试院投档线表没有这些字段），跟省考试院
                        # 扁平表结构不同，也不需要按院校名称匹配白名单（学校已知）
                        stage_batch = self._infer_zhejiang_stage(node.title)
                        if stage_batch is None:
                            report.messages.append(
                                f"manual review: cannot infer 第一段/第二段 for {node.artifact.source_url}"
                            )
                            return []
                        records = parse_single_university_admission_result_rows(
                            document,
                            provenance=provenance,
                            config=self.config,
                            target_university_code=source.target_university_code,
                            batch=stage_batch,
                        )
                    elif self.config.province == "浙江":
                        # 浙江投档线是扁平表（学校/专业逐行铺开，自带位次），跟江苏
                        # "院校专业组"合并单元格格式完全不同，需要专用解析函数；
                        # "第一段/第二段"从标题里判断，判断不出来时明确进人工复核，
                        # 不能瞎猜成某一段导致数据张冠李戴
                        stage_batch = self._infer_zhejiang_stage(node.title)
                        if stage_batch is None:
                            report.messages.append(
                                f"manual review: cannot infer 第一段/第二段 for {node.artifact.source_url}"
                            )
                            return []
                        records = parse_zhejiang_admission_score_rows(
                            document,
                            provenance=provenance,
                            config=self.config,
                            batch=stage_batch,
                        )
                    elif self.config.province == "上海":
                        # 上海投档线是"院校专业组"表，不分物理/历史（3+3不分文理）；
                        # 580分及以上考生官方明确不公开，parser内部会跳过而不是编造
                        admission_type = (
                            "中外合作"
                            if "cooperative" in source.id or "Q组" in source.name
                            else "普通"
                        )
                        records, undisclosed = parse_shmeea_admission_score_rows(
                            document,
                            provenance=provenance,
                            config=self.config,
                            batch="本科普通批次",
                            admission_type=admission_type,
                        )
                        if undisclosed:
                            report.messages.append(
                                f"{undisclosed} rows skipped: 580分及以上官方未公开投档线 "
                                f"({node.artifact.source_url})"
                            )
                    else:
                        records = parse_admission_score_rows(
                            document,
                            subject_type=subject_type,
                            provenance=provenance,
                            config=self.config,
                        )
                elif source.target_university_code:
                    # 有target_university_code的招生计划源是"某一所学校自己招生网
                    # 的页面"，天然只含这一所学校的数据、没有"院校名称"列可以匹配
                    # 白名单（跟江苏manual+人工整理JSON发布、从未真正走这条http
                    # 解析路径的admission_plan不同，这是浙江新增的真实http场景）
                    records = parse_single_university_admission_plan_rows(
                        document,
                        provenance=provenance,
                        config=self.config,
                        target_university_code=source.target_university_code,
                        subject_type=subject_type,
                    )
                else:
                    records = parse_admission_plan_rows(
                        document,
                        subject_type=subject_type,
                        provenance=provenance,
                        config=self.config,
                    )
            else:
                report.messages.append(f"parser not implemented for {source.data_type}")
                return []
        except Exception as exc:
            report.messages.append(
                f"parse failed: {node.artifact.source_url}: {exc.__class__.__name__}: {exc}"
            )
            return []

        validated = validate_records(records, self.config)
        self._append_staging(report, validated)
        report.parsed_records += len(validated)
        report.valid_records += sum(item.status == "valid" for item in validated)
        report.review_records += sum(item.status == "needs_review" for item in validated)
        report.rejected_records += sum(item.status == "rejected" for item in validated)
        return validated

    # 省份不分文理（如浙江、上海"3+3"不分科类），标题/URL里不会出现"物理/历史"关键词，
    # 必须先按省份短路判断，否则会被下面的关键词匹配漏判成需要人工复核
    _UNIFIED_SUBJECT_PROVINCES = {"浙江", "上海"}

    def _infer_subject(self, title: str, url: str) -> str | None:
        if self.config.province in self._UNIFIED_SUBJECT_PROVINCES:
            return "unified"
        value = f"{title} {url}".lower()
        if "物理" in value or "physics" in value:
            return "physics"
        if "历史" in value or "history" in value:
            return "history"
        return None

    @staticmethod
    def _infer_zhejiang_stage(title: str) -> str | None:
        if "第一段" in title:
            return "第一段"
        if "第二段" in title:
            return "第二段"
        # 学校自己发布的录取情况页标题习惯写"一段"/"二段"（不带"第"字，如杭州师范
        # 大学"2025年浙江省普通类一段首轮录取情况"），跟省考试院文件的"第一段/
        # 第二段"写法不同，放在省考试院两种精确写法都不匹配之后兜底判断
        if "一段" in title:
            return "第一段"
        if "二段" in title:
            return "第二段"
        return None

    def _write_report(self, report: SourceRunReport) -> None:
        self.report_root.mkdir(parents=True, exist_ok=True)
        stamp = report.started_at.replace(":", "").replace("+", "_")
        path = self.report_root / f"{report.source_id}-{stamp}.json"
        path.write_text(
            json.dumps(asdict(report), ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )

    def _staging_path(self, report: SourceRunReport) -> Path:
        stamp = report.started_at.replace(":", "").replace("+", "_")
        return self.report_root / f"{report.source_id}-{stamp}.staging.jsonl"

    def _append_staging(self, report: SourceRunReport, records: list) -> None:
        if not records:
            return
        self.report_root.mkdir(parents=True, exist_ok=True)
        path = Path(report.staging_path or self._staging_path(report))
        with path.open("a", encoding="utf-8") as handle:
            for record in records:
                handle.write(record.model_dump_json() + "\n")
