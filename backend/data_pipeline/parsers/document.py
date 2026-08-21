from __future__ import annotations

import re
from html.parser import HTMLParser
from pathlib import Path

from data_pipeline.records import DocumentChunkRecord, PolicyRuleRecord, Provenance


KEY_SECTION_TERMS = (
    "录取",
    "调剂",
    "选科",
    "体检",
    "外语",
    "单科",
    "学费",
    "中外合作",
    "转专业",
    "专业介绍",
    "志愿",
    "投档",
)


class _TextExtractor(HTMLParser):
    BLOCK_TAGS = {"p", "div", "li", "h1", "h2", "h3", "h4", "tr", "br"}

    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self._ignored = 0

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag.lower() in {"script", "style", "noscript"}:
            self._ignored += 1
        elif tag.lower() in self.BLOCK_TAGS:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in {"script", "style", "noscript"}:
            self._ignored = max(0, self._ignored - 1)
        elif tag.lower() in self.BLOCK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._ignored:
            self.parts.append(data)


def extract_document_text(path: str | Path) -> str:
    file_path = Path(path)
    if file_path.suffix.lower() in {".html", ".htm"}:
        parser = _TextExtractor()
        parser.feed(file_path.read_text(encoding="utf-8", errors="replace"))
        text = "".join(parser.parts)
    elif file_path.suffix.lower() == ".pdf":
        try:
            import pdfplumber
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("pdfplumber is required to extract PDF text") from exc
        with pdfplumber.open(file_path) as document:
            text = "\n".join(page.extract_text() or "" for page in document.pages)
    else:
        raise ValueError(f"unsupported document format: {file_path.suffix}")
    lines = [re.sub(r"\s+", " ", line).strip() for line in text.splitlines()]
    return "\n".join(line for line in lines if line)


def chunk_document(
    text: str,
    *,
    document_type: str,
    provenance: Provenance,
    university_code: str | None = None,
    max_chars: int = 1200,
) -> list[DocumentChunkRecord]:
    paragraphs = [part.strip() for part in re.split(r"\n+", text) if part.strip()]
    if document_type in {"policy", "charter", "transfer_policy"}:
        selected = [
            paragraph for paragraph in paragraphs if any(term in paragraph for term in KEY_SECTION_TERMS)
        ]
    else:
        selected = paragraphs
    chunks: list[str] = []
    current = ""
    for paragraph in selected:
        if current and len(current) + len(paragraph) + 1 > max_chars:
            chunks.append(current)
            current = paragraph
        else:
            current = f"{current}\n{paragraph}".strip()
    if current:
        chunks.append(current)
    return [
        DocumentChunkRecord(
            year=provenance.year,
            document_type=document_type,
            university_code=university_code,
            chunk_index=index,
            content=content,
            provenance=provenance,
        )
        for index, content in enumerate(chunks)
    ]


def extract_policy_rule(text: str, *, provenance: Provenance) -> PolicyRuleRecord:
    compact = re.sub(r"\s+", "", text)
    mode = "parallel" if "平行志愿" in compact else "unknown"
    max_match = re.search(r"(?:设置|填报|可填报)(\d{1,3})个院校专业组志愿", compact)
    adjustment_allowed = None
    if "服从专业调剂" in compact or "专业调剂" in compact:
        adjustment_allowed = True
    if "不进行专业调剂" in compact or "不服从专业调剂" in compact:
        adjustment_allowed = False

    tie_match = re.search(r"([^。]{0,80}(?:同分|投档分相同)[^。]{0,180}。)", text)
    filing_match = re.search(r"([^。]{0,80}(?:投档原则|投档规则)[^。]{0,220}。)", text)
    return PolicyRuleRecord(
        year=provenance.year,
        volunteer_mode=mode,
        max_volunteers=int(max_match.group(1)) if max_match else None,
        adjustment_allowed=adjustment_allowed,
        filing_rule=filing_match.group(1).strip() if filing_match else None,
        tie_break_rule=tie_match.group(1).strip() if tie_match else None,
        provenance=provenance,
    )
