"""Ingest a document-type (policy/charter/major_intro/transfer_policy) record
whose正文 was obtained OUTSIDE the http collector — OCR'd from a scanned image,
or scraped in a real browser (WeChat article behind anti-crawl) — into the same
`pipeline_staging_records` + `rag_documents`/`rag_chunks` tables a normal
`--source <id> --persist` run would produce.

为什么需要这个脚本：`HttpCollector`只认`collection_method: http`，遇到
`manual`/`playwright`会直接抛`CollectionError`（见`collectors/http.py`），
本来就没打算走这条路；但内容一旦拿到手（不管是OCR文字还是浏览器复制下来的
正文），后半段"切块+落库+embedding"跟http源应该走同一套代码，不需要另起
炉灶——先用`RawArtifactStore.save()`把正文存成`.txt`留痕（保留可审计的原始
文件，跟http采集的`data/raw/`语义一致，只是内容来源标注为manual），再直接
调用`chunk_document`+`validate_records`+`PipelineRepository.register_document/
stage_records`，`stage_records`内部本来就会自动同步`rag_documents`/
`rag_chunks`（`_sync_rag_chunks`），不用另外手写RAG写入逻辑。

source_id 必须已经在 configs/zhejiang.yaml 里登记（`collection_method: manual`），
否则`sync_sources`不会认识它、后续`enrollment_data`等下游查询按source_id关联
时会找不到来源。

Usage:
    docker compose exec backend python -m scripts.publish_zhejiang_manual_document \\
        --source-id hdu-charter-2026 --text-file /tmp/hdu_ocr/ocr_output.txt \\
        --document-type charter --university-code 10336 --year 2026 \\
        --source-url https://zhaosheng.hdu.edu.cn/admin/upload/image/20260521111207_43906.png \\
        --title "杭州电子科技大学2026年普通高校招生章程"
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-id", required=True)
    parser.add_argument("--text-file", type=Path, required=True)
    parser.add_argument(
        "--document-type",
        required=True,
        choices=["policy", "charter", "major_intro", "transfer_policy"],
    )
    parser.add_argument("--university-code", required=True)
    parser.add_argument("--year", type=int, required=True)
    parser.add_argument("--source-url", required=True)
    parser.add_argument("--title", required=True)
    parser.add_argument(
        "--config",
        type=Path,
        default=BACKEND_ROOT / "data_pipeline" / "configs" / "zhejiang.yaml",
    )
    return parser.parse_args()


def run(args: argparse.Namespace) -> dict:
    from app.database import SyncSessionLocal
    from data_pipeline.config import load_pipeline_config
    from data_pipeline.loaders import PipelineRepository
    from data_pipeline.parsers import chunk_document
    from data_pipeline.raw_store import RawArtifactStore
    from data_pipeline.records import Provenance
    from data_pipeline.validators import validate_records
    from datetime import UTC, datetime

    config = load_pipeline_config(args.config)
    source = next((s for s in config.sources if s.id == args.source_id), None)
    if source is None:
        raise SystemExit(
            f"source_id {args.source_id!r} not registered in {args.config}; "
            "add a collection_method: manual entry first"
        )

    text = args.text_file.read_text(encoding="utf-8")
    # OCR/浏览器抓到的原文常常一行一个短句（Vision按文本框切行，公众号正文
    # 按DOM块切段），直接原样按行送进chunk_document会被`\n+`拆成一堆零碎
    # "段落"，章程类逐段关键词过滤时不少半句因为单行不含关键词被误删；但如果
    # 反过来整个文档拼成没有换行的一整块，chunk_document的`max_chars`截断
    # 逻辑只在"追加下一段前"检查长度，只有一个"段落"时永远不会触发拆分，会
    # 产出一个远超1200字的巨型chunk，同样不可用。两种极端都不对，改成按中文
    # 句号重新分句（每句当一个"段落"），既不会因为逐行太碎丢内容，也能让
    # chunk_document按字数正常切成多个chunk。
    flat_text = "".join(line.strip() for line in text.splitlines() if line.strip())
    sentences = [s.strip() + "。" for s in flat_text.split("。") if s.strip()]
    joined_text = "\n".join(sentences)

    session = SyncSessionLocal()
    try:
        repository = PipelineRepository(session)
        repository.sync_sources(config)
        run_model = repository.start_run(source.id)

        store = RawArtifactStore(BACKEND_ROOT / "data" / "raw")
        artifact = store.save(
            province=config.province,
            source=source,
            content=text.encode("utf-8"),
            content_type="text/plain",
            final_url=args.source_url.rstrip("/") + ".manual.txt",
        )

        document, is_new = repository.register_document(
            run=run_model, source=source, artifact=artifact, title=args.title
        )
        if not is_new:
            return {"published": None, "reason": "identical content already ingested before"}

        provenance = Provenance(
            source_url=args.source_url,
            source_document_id=document.id,
            source_title=args.title,
            year=args.year,
            authority_level=source.authority_level,
            collected_at=artifact.collected_at,
            parser_version=source.parser,
        )
        chunks = chunk_document(
            joined_text,
            document_type=args.document_type,
            provenance=provenance,
            province=config.province,
            university_code=args.university_code,
        )
        validated = validate_records(chunks, config)
        staged = repository.stage_records(run=run_model, document=document, records=validated)
        repository.finish_run(run_model)
        session.commit()
        return {
            "source_id": source.id,
            "artifacts": 1,
            "parsed_records": len(staged),
            "valid_records": sum(1 for r in validated if r.status == "valid"),
            "needs_review": sum(1 for r in validated if r.status == "needs_review"),
            "rejected": sum(1 for r in validated if r.status == "rejected"),
        }
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


if __name__ == "__main__":
    print(json.dumps(run(parse_args()), ensure_ascii=False, indent=2, default=str))
