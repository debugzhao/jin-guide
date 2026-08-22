from __future__ import annotations

import hashlib
import json
import os
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import parse_qsl, urlparse

from data_pipeline.config import SourceConfig


@dataclass(frozen=True)
class StoredArtifact:
    source_id: str
    source_url: str
    checksum: str
    content_path: Path
    metadata_path: Path
    collected_at: str
    changed: bool
    size_bytes: int


class RawArtifactStore:
    """Content-addressed raw storage with an immutable sidecar manifest."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)

    def save(
        self,
        *,
        province: str,
        source: SourceConfig,
        content: bytes,
        content_type: str | None,
        final_url: str,
    ) -> StoredArtifact:
        checksum = hashlib.sha256(content).hexdigest()
        collected_at = datetime.now(UTC).isoformat()
        year = str(source.year) if source.year is not None else "undated"
        artifact_dir = self.root / province / year / source.id
        artifact_dir.mkdir(parents=True, exist_ok=True)

        suffix = self._safe_suffix(final_url, content_type)
        content_path = artifact_dir / f"{checksum}{suffix}"
        metadata_path = artifact_dir / f"{checksum}.metadata.json"
        changed = not content_path.exists()

        if changed:
            self._atomic_write(content_path, content)
        if metadata_path.exists():
            existing = json.loads(metadata_path.read_text(encoding="utf-8"))
            collected_at = existing["collected_at"]
        else:
            metadata = {
                "source_id": source.id,
                "source_name": source.name,
                "source_url": final_url,
                "entry_url": str(source.entry_url),
                "data_type": source.data_type,
                "year": source.year,
                "target_university_code": source.target_university_code,
                "authority_level": source.authority_level,
                "parser": source.parser,
                "checksum_sha256": checksum,
                "content_type": content_type,
                "size_bytes": len(content),
                "collected_at": collected_at,
            }
            self._atomic_write(
                metadata_path,
                json.dumps(metadata, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8"),
            )

        return StoredArtifact(
            source_id=source.id,
            source_url=final_url,
            checksum=checksum,
            content_path=content_path,
            metadata_path=metadata_path,
            collected_at=collected_at,
            changed=changed,
            size_bytes=len(content),
        )

    @staticmethod
    def _atomic_write(path: Path, content: bytes) -> None:
        with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as handle:
            temp_path = Path(handle.name)
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, path)

    @staticmethod
    def _safe_suffix(url: str, content_type: str | None) -> str:
        allowed = {
            ".html", ".htm", ".xlsx", ".xls", ".csv", ".pdf", ".json", ".xml",
            ".docx", ".doc", ".jpg", ".jpeg", ".png",
        }
        parsed = urlparse(url)
        suffix = Path(parsed.path).suffix.lower()
        if suffix in allowed:
            return suffix
        # 部分官网用下载代理端点分发附件（如浙江省教育考试院的
        # /module/download/downfile.jsp?...&filename=xxx.docx），真实扩展名藏在
        # query参数值里而不是URL路径；这类老旧CMS的Content-Type还经常被错误标成
        # text/html（已用真实线上URL验证过），query参数比Content-Type更可信，
        # 必须先查它，否则docx会被错误存成.html再被当成HTML解析出乱码
        for _, value in parse_qsl(parsed.query):
            candidate = Path(value).suffix.lower()
            if candidate in allowed:
                return candidate
        mime_suffixes = {
            "text/html": ".html",
            "text/csv": ".csv",
            "application/pdf": ".pdf",
            "application/json": ".json",
            "application/vnd.ms-excel": ".xls",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
            "application/msword": ".doc",
            "image/jpeg": ".jpg",
            "image/png": ".png",
        }
        normalized_type = (content_type or "").split(";", 1)[0].strip().lower()
        return mime_suffixes.get(normalized_type, ".bin")
