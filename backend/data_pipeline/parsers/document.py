from __future__ import annotations

import re
from html.parser import HTMLParser
from pathlib import Path

from data_pipeline.records import DocumentChunkRecord, PolicyRuleRecord, Provenance
from data_pipeline.text_encoding import decode_html_bytes


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
        parser.feed(decode_html_bytes(file_path.read_bytes()))
        text = "".join(parser.parts)
    elif file_path.suffix.lower() == ".pdf":
        try:
            import pdfplumber
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("pdfplumber is required to extract PDF text") from exc
        with pdfplumber.open(file_path) as document:
            text = "\n".join(page.extract_text() or "" for page in document.pages)
    elif file_path.suffix.lower() == ".docx":
        # 浙江省招生政策通知附件是 .docx（江苏是 .pdf），官方 word 排版里正文段落和
        # 表格是分开的两种元素，逐段读 paragraphs 会漏掉表格里的内容（例如某些年份
        # 把批次控制线放在表格里），所以两者都读，按文档内出现顺序拼接。
        import docx

        document = docx.Document(str(file_path))
        parts: list[str] = []
        for element in document.element.body:
            tag = element.tag.rsplit("}", 1)[-1]
            if tag == "p":
                paragraph = next(
                    (p for p in document.paragraphs if p._element is element), None
                )
                if paragraph is not None and paragraph.text.strip():
                    parts.append(paragraph.text)
            elif tag == "tbl":
                table = next((t for t in document.tables if t._element is element), None)
                if table is not None:
                    for row in table.rows:
                        parts.append(" ".join(cell.text.strip() for cell in row.cells))
        text = "\n".join(parts)
    else:
        raise ValueError(f"unsupported document format: {file_path.suffix}")
    lines = [re.sub(r"\s+", " ", line).strip() for line in text.splitlines()]
    return "\n".join(line for line in lines if line)


def chunk_document(
    text: str,
    *,
    document_type: str,
    provenance: Provenance,
    province: str,
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
            province=province,
            year=provenance.year,
            document_type=document_type,
            university_code=university_code,
            chunk_index=index,
            content=content,
            provenance=provenance,
        )
        for index, content in enumerate(chunks)
    ]


def extract_policy_rule(text: str, *, provenance: Provenance, province: str) -> PolicyRuleRecord:
    compact = re.sub(r"\s+", "", text)
    mode = "parallel" if "平行志愿" in compact else "unknown"
    max_match = re.search(r"(?:设置|填报|可填报)(\d{1,3})个院校专业组志愿", compact)
    if max_match is None:
        # 浙江真实政策原文（2026年实施方案已验证）用"专业平行志愿"，数字和"志愿"之间
        # 没有"院校/专业"这类单位名（"考生每次可填报不超过80个志愿"），跟江苏"设置N个
        # 院校专业组志愿"结构不同。必须锁定"不超过N个志愿"且"个"后直接接"志愿"二字，
        # 否则会误命中同一段里"1个志愿单位"（志愿单位说明句，不是数量上限）或"不超过
        # 6个专业志愿"（提前录取院校志愿的专业数子上限，不是本志愿单位的总数上限）
        max_match = re.search(r"不超过(\d{1,3})个志愿(?!单位|专业|院校)", compact)
    adjustment_allowed = None
    if "服从专业调剂" in compact or "专业调剂" in compact:
        adjustment_allowed = True
    if "不进行专业调剂" in compact or "不服从专业调剂" in compact:
        adjustment_allowed = False

    tie_match = re.search(r"([^。]{0,80}(?:同分|投档分相同)[^。]{0,180}。)", text)
    filing_match = re.search(r"([^。]{0,80}(?:投档原则|投档规则)[^。]{0,220}。)", text)
    return PolicyRuleRecord(
        province=province,
        year=provenance.year,
        volunteer_mode=mode,
        max_volunteers=int(max_match.group(1)) if max_match else None,
        adjustment_allowed=adjustment_allowed,
        filing_rule=filing_match.group(1).strip() if filing_match else None,
        tie_break_rule=tie_match.group(1).strip() if tie_match else None,
        provenance=provenance,
    )
