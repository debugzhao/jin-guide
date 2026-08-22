from __future__ import annotations

import csv
import io
import json
import os
import re
import subprocess
import tempfile
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from typing import Iterable, Sequence

from data_pipeline.config import PipelineConfig
from data_pipeline.text_encoding import decode_html_bytes
from data_pipeline.records import (
    AdmissionPlanRecord,
    AdmissionScoreRecord,
    Provenance,
    RankSegmentRecord,
    SubjectType,
)


@dataclass(frozen=True)
class TabularDocument:
    rows: list[list[str]]
    page_or_sheet: list[int]


def _cell(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return re.sub(r"\s+", " ", str(value)).strip()


def read_tabular_document(path: str | Path) -> TabularDocument:
    file_path = Path(path)
    suffix = file_path.suffix.lower()
    if suffix == ".csv":
        text = file_path.read_text(encoding="utf-8-sig")
        rows = [[_cell(value) for value in row] for row in csv.reader(io.StringIO(text))]
        return TabularDocument(rows=rows, page_or_sheet=[1] * len(rows))
    if suffix in {".xlsx", ".xls"}:
        return _read_excel(file_path)
    if suffix == ".pdf":
        return _read_pdf(file_path)
    if suffix in {".jpg", ".jpeg", ".png"}:
        return _read_image(file_path)
    if suffix in {".html", ".htm"}:
        return _read_html_table(file_path)
    raise ValueError(f"unsupported tabular document: {file_path.name}")


class _HtmlTableParser(HTMLParser):
    """把第一个 <table> 转成矩形网格，rowspan/colspan 的续格用空字符串占位——
    跟 openpyxl/pdfplumber 读合并单元格的语义一致（续格是空字符串不是重复文本），
    这样 parse_admission_plan_rows 已有的"空列=沿用上一行"前向填充逻辑可以直接复用，
    不需要为HTML另写一套规则。只处理页面第一个 <table>，多表格页面（目前没遇到过）
    需要另外扩展。"""

    def __init__(self) -> None:
        super().__init__()
        self.rows: list[list[str]] = []
        self._table_seen = False
        self._in_table = False
        self._row: list[str] | None = None
        self._cell_parts: list[str] | None = None
        self._cell_colspan = 1
        self._cell_rowspan = 1
        self._pending: dict[int, int] = {}  # column -> 还需要占位的行数
        self._col = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "table" and not self._table_seen:
            self._in_table = True
        elif tag == "tr" and self._in_table:
            self._row = []
            self._col = 0
        elif tag in ("td", "th") and self._row is not None:
            values = dict(attrs)
            self._cell_parts = []
            self._cell_colspan = self._parse_span(values.get("colspan"))
            self._cell_rowspan = self._parse_span(values.get("rowspan"))

    def handle_data(self, data: str) -> None:
        if self._cell_parts is not None:
            self._cell_parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag in ("td", "th") and self._cell_parts is not None and self._row is not None:
            text = re.sub(r"\s+", " ", "".join(self._cell_parts)).strip()
            self._fill_pending_columns()
            for offset in range(self._cell_colspan):
                self._row.append(text if offset == 0 else "")
                if self._cell_rowspan > 1:
                    self._pending[self._col] = self._cell_rowspan - 1
                self._col += 1
            self._cell_parts = None
        elif tag == "tr" and self._row is not None:
            self.rows.append(self._row)
            self._row = None
        elif tag == "table" and self._in_table:
            self._in_table = False
            self._table_seen = True

    def _fill_pending_columns(self) -> None:
        assert self._row is not None
        while self._pending.get(self._col, 0) > 0:
            self._row.append("")
            remaining = self._pending[self._col] - 1
            if remaining <= 0:
                del self._pending[self._col]
            else:
                self._pending[self._col] = remaining
            self._col += 1

    @staticmethod
    def _parse_span(value: str | None) -> int:
        try:
            return max(1, int(value)) if value else 1
        except ValueError:
            return 1


def _read_html_table(path: Path) -> TabularDocument:
    parser = _HtmlTableParser()
    parser.feed(decode_html_bytes(path.read_bytes()))
    return TabularDocument(rows=parser.rows, page_or_sheet=[1] * len(parser.rows))


def _read_excel(path: Path) -> TabularDocument:
    if path.suffix.lower() == ".xls":
        try:
            import xlrd
        except ImportError as exc:  # pragma: no cover - depends on deployment image
            raise RuntimeError("xlrd is required to parse legacy .xls files") from exc
        workbook = xlrd.open_workbook(path)
        rows: list[list[str]] = []
        sheets: list[int] = []
        for sheet_index in range(workbook.nsheets):
            sheet = workbook.sheet_by_index(sheet_index)
            for row_index in range(sheet.nrows):
                normalized = [_cell(value) for value in sheet.row_values(row_index)]
                if any(normalized):
                    rows.append(normalized)
                    sheets.append(sheet_index + 1)
        return TabularDocument(rows=rows, page_or_sheet=sheets)
    try:
        from openpyxl import load_workbook
    except ImportError as exc:  # pragma: no cover - depends on deployment image
        raise RuntimeError("openpyxl is required to parse Excel files") from exc
    workbook = load_workbook(path, read_only=True, data_only=True)
    rows: list[list[str]] = []
    sheets: list[int] = []
    try:
        for sheet_index, sheet in enumerate(workbook.worksheets, start=1):
            for row in sheet.iter_rows(values_only=True):
                normalized = [_cell(value) for value in row]
                if any(normalized):
                    rows.append(normalized)
                    sheets.append(sheet_index)
    finally:
        workbook.close()
    return TabularDocument(rows=rows, page_or_sheet=sheets)


def _read_pdf(path: Path) -> TabularDocument:
    try:
        import pdfplumber
    except ImportError as exc:  # pragma: no cover - depends on deployment image
        raise RuntimeError("pdfplumber is required to parse text PDFs") from exc
    rows: list[list[str]] = []
    pages: list[int] = []
    with pdfplumber.open(path) as document:
        for page_number, page in enumerate(document.pages, start=1):
            for table in page.extract_tables() or []:
                for row in table:
                    normalized = [_cell(value) for value in row]
                    if any(normalized):
                        rows.append(normalized)
                        pages.append(page_number)
    if not rows:
        raise RuntimeError("PDF contains no extractable tables; OCR/manual review required")
    return TabularDocument(rows=rows, page_or_sheet=pages)


def _read_image(path: Path) -> TabularDocument:
    """OCR an image into approximate table rows.

    Production Linux images should provide PaddleOCR. macOS development uses the
    built-in Vision framework, avoiding a heavyweight local model download.
    """
    vision_script = Path(__file__).resolve().parents[2] / "scripts" / "macos_vision_ocr.swift"
    if os.uname().sysname == "Darwin" and vision_script.exists():
        rows = _read_image_with_vision(path, vision_script)
        return TabularDocument(rows=rows, page_or_sheet=[1] * len(rows))
    raise RuntimeError(
        "image OCR unavailable; install PaddleOCR in production or run on macOS with Vision"
    )


def _read_image_with_vision(path: Path, vision_script: Path) -> list[list[str]]:
    try:
        from PIL import Image, ImageOps
    except ImportError:  # pragma: no cover
        return _cluster_ocr_rows(_run_vision(path, vision_script), panel_count=3)

    rows: list[list[str]] = []
    with Image.open(path) as image, tempfile.TemporaryDirectory(dir="/tmp") as temp_dir:
        grayscale = ImageOps.grayscale(image)
        width, height = grayscale.size
        for panel_index in range(3):
            left = round(width * panel_index / 3)
            right = round(width * (panel_index + 1) / 3)
            panel = grayscale.crop((left, 0, right, height))
            panel = ImageOps.autocontrast(panel, cutoff=1)
            # Watermarks are light gray; a conservative threshold removes them
            # while retaining the black printed digits and table rules.
            panel = panel.point(lambda value: 255 if value > 175 else 0)
            panel = panel.resize(
                (panel.width * 2, panel.height * 2), Image.Resampling.LANCZOS
            )
            panel_path = Path(temp_dir) / f"panel-{panel_index}.png"
            panel.save(panel_path)
            observations = _run_vision(panel_path, vision_script)
            rows.extend(_cluster_ocr_rows(observations, panel_count=1))
    return rows


def _run_vision(path: Path, vision_script: Path) -> list[dict]:
    environment = os.environ.copy()
    environment.setdefault("SWIFT_MODULECACHE_PATH", "/tmp/wenjin-swift-module-cache")
    environment.setdefault("CLANG_MODULE_CACHE_PATH", "/tmp/wenjin-clang-module-cache")
    compiled_helper = Path("/tmp/wenjin-macos-vision-ocr")
    command = (
        [str(compiled_helper), str(path)]
        if compiled_helper.exists()
        else ["xcrun", "swift", str(vision_script), str(path)]
    )
    result = subprocess.run(
        command,
        check=True,
        capture_output=True,
        text=True,
        timeout=120,
        env=environment,
    )
    return json.loads(result.stdout)


def _cluster_ocr_rows(
    observations: list[dict], *, panel_count: int = 3
) -> list[list[str]]:
    # JSEE rank images place up to three independent tables side by side and may
    # concatenate multiple pages vertically. Partitioning by x before clustering
    # prevents values from different panels being merged into one logical row.
    panels: list[list[dict]] = [[] for _ in range(panel_count)]
    for item in observations:
        center_x = item["x"] + item["width"] / 2
        panel_index = min(int(center_x * panel_count), panel_count - 1)
        panels[panel_index].append(item)

    clusters: list[dict] = []
    for panel in panels:
        ordered = sorted(panel, key=lambda item: (-item["y"], item["x"]))
        panel_clusters: list[dict] = []
        for item in ordered:
            center_y = item["y"] + item["height"] / 2
            match = next(
                (
                    cluster
                    for cluster in panel_clusters
                    if abs(cluster["center_y"] - center_y)
                    <= max(item["height"], cluster["height"]) * 0.75
                ),
                None,
            )
            if match is None:
                panel_clusters.append(
                    {"center_y": center_y, "height": item["height"], "items": [item]}
                )
            else:
                match["items"].append(item)
        clusters.extend(panel_clusters)
    return [
        [entry["text"] for entry in sorted(cluster["items"], key=lambda item: item["x"])]
        for cluster in clusters
    ]


def _integer(value: str) -> int | None:
    match = re.search(r"(?<!\d)(\d{1,7})(?!\d)", value.replace(",", ""))
    return int(match.group(1)) if match else None


def _row_number(provenance: Provenance, row_number: int, page: int | None) -> Provenance:
    return provenance.model_copy(update={"table_row": row_number, "page_number": page})


def parse_rank_segment_rows(
    document: TabularDocument,
    *,
    subject_type: SubjectType,
    provenance: Provenance,
    config: PipelineConfig,
) -> list[RankSegmentRecord]:
    records: list[RankSegmentRecord] = []
    for row_number, row in enumerate(document.rows, start=1):
        values = [_integer(value) for value in row]
        numbers = [value for value in values if value is not None]
        groups: list[list[int]] = []
        if len(numbers) == 2:
            groups = [[numbers[0], 0, numbers[1]]]
        elif len(numbers) == 3:
            groups = [numbers]
        elif len(numbers) >= 6 and len(numbers) % 3 == 0:
            groups = [numbers[index : index + 3] for index in range(0, len(numbers), 3)]
        for score, count, rank in groups:
            if not 0 <= score <= 750 or rank <= 0 or rank < count:
                continue
            records.append(
                RankSegmentRecord(
                    province=config.province,
                    year=provenance.year,
                    subject_type=subject_type,
                    score=score,
                    cumulative_rank=rank,
                    provenance=_row_number(
                        provenance, row_number, document.page_or_sheet[row_number - 1]
                    ),
                )
            )
    return records


_GROUP_PATTERN = re.compile(
    r"^(?P<name>.+?)(?P<group>[A-Z]?\d{2,3})专业组(?:\((?P<requirement>[^)]+)\))?(?P<tail>.*)$"
)

# 专业组名称后可能出现第二个括注（如 "…专业组(化学)(中外合作办学)"），标注的是招生
# 类型而不是校区。这里用于把这类标签从 tail 中过滤掉，避免它们被误当成校区写入
# campus 字段。
_ADMISSION_TYPE_LABELS = ("中外合作办学", "高校专项", "地方专项", "联合培养")
# 单校招生计划页"类别"列的标准平行志愿写法是"普通类 0005"（类别名+代码，无额外
# 说明文字）；"三位一体"等特殊招生机制会在后面附一长段说明文字，不匹配这个模式。
_PLAIN_CATEGORY_PATTERN = re.compile(r"^普通类\s*\d*$")


def parse_admission_score_rows(
    document: TabularDocument,
    *,
    subject_type: SubjectType,
    provenance: Provenance,
    config: PipelineConfig,
    batch: str = "本科批",
    line_type: str = "regular",
) -> list[AdmissionScoreRecord]:
    by_name = {target.name: target for target in config.target_universities}
    records: list[AdmissionScoreRecord] = []
    for row_number, row in enumerate(document.rows, start=1):
        joined = " ".join(value for value in row if value)
        group_match = None
        group_cell = ""
        group_index = 0
        for cell_index, value in enumerate(row):
            match = _GROUP_PATTERN.match(value.replace(" ", ""))
            if match and match.group("name") in by_name:
                group_match = match
                group_cell = value
                group_index = cell_index
                break
        if group_match is None:
            continue

        integers = [_integer(value) for value in row[group_index + 1 :]]
        numeric = [value for value in integers if value is not None]
        plausible_scores = [value for value in numeric if 0 <= value <= 750]
        if not plausible_scores:
            continue
        min_score = plausible_scores[0]
        university_name = group_match.group("name")
        tail = (group_match.group("tail") or "").strip("()")
        admission_type = "普通"
        for label in _ADMISSION_TYPE_LABELS:
            if label in joined:
                admission_type = label
                break
        campus = tail if tail and tail not in _ADMISSION_TYPE_LABELS else None
        target = by_name[university_name]
        provincial_code = next(
            (value for value in row if re.fullmatch(r"\d{4}", value.strip())), None
        )
        records.append(
            AdmissionScoreRecord(
                province=config.province,
                year=provenance.year,
                batch=batch,
                subject_type=subject_type,
                university_code=target.university_code,
                university_name=university_name,
                provincial_university_code=provincial_code,
                major_group_code=group_match.group("group"),
                major_group_name=group_cell,
                selection_requirement=group_match.group("requirement"),
                admission_type=admission_type,
                campus=campus,
                line_type=line_type,
                min_score=min_score,
                provenance=_row_number(
                    provenance, row_number, document.page_or_sheet[row_number - 1]
                ),
            )
        )
    return records


def parse_zhejiang_admission_score_rows(
    document: TabularDocument,
    *,
    provenance: Provenance,
    config: PipelineConfig,
    batch: str,
) -> list[AdmissionScoreRecord]:
    """浙江省教育考试院投档线是扁平表（学校代号/学校名称/专业代号/专业名称/计划数/
    分数线/位次），每行本身就带位次，不需要像江苏那样另外关联逐分段表做enrichment；
    每个专业本身就是志愿单位，没有"院校专业组"这层概念，这里复用
    major_group_code/major_group_name 字段存专业代号/专业名称（浙江语义下"1个专业
    (类)"就相当于江苏语义下的"1个院校专业组"，都是最小志愿单位，字段含义对得上，不是
    乱塞）。用真实2026年浙江投档线xls验证过表头结构，见
    docs/10_zhejiang_top10_data_collection_status.md。
    """
    aliases = {
        "学校代号": {"学校代号", "学校代码", "院校代号", "院校代码"},
        "学校名称": {"学校名称", "院校名称"},
        "专业代号": {"专业代号", "专业代码"},
        "专业名称": {"专业名称"},
        "分数线": {"分数线", "投档线", "最低分"},
        "位次": {"位次", "最低位次"},
    }
    header_index = None
    columns: dict[str, int] = {}
    for index, row in enumerate(document.rows):
        compact = [re.sub(r"\s+", "", value) for value in row]
        found: dict[str, int] = {}
        for canonical, options in aliases.items():
            for cell_index, value in enumerate(compact):
                if value in options:
                    found[canonical] = cell_index
                    break
        if {"学校名称", "专业名称", "分数线"}.issubset(found):
            header_index = index
            columns = found
            break
    if header_index is None:
        return []

    by_name = {target.name: target for target in config.target_universities}

    def value(row: Sequence[str], key: str) -> str:
        position = columns.get(key)
        return row[position].strip() if position is not None and position < len(row) else ""

    records: list[AdmissionScoreRecord] = []
    for row_number in range(header_index + 1, len(document.rows)):
        row = document.rows[row_number]
        university_name = value(row, "学校名称")
        target = by_name.get(university_name)
        if target is None:
            continue
        major_code = value(row, "专业代号")
        major_name = value(row, "专业名称")
        min_score = _integer(value(row, "分数线"))
        if not major_code or not major_name or min_score is None:
            continue
        records.append(
            AdmissionScoreRecord(
                province=config.province,
                year=provenance.year,
                batch=batch,
                subject_type="unified",
                university_code=target.university_code,
                university_name=university_name,
                provincial_university_code=value(row, "学校代号") or None,
                major_group_code=major_code,
                major_group_name=major_name,
                min_score=min_score,
                min_rank=_integer(value(row, "位次")),
                provenance=_row_number(
                    provenance, row_number, document.page_or_sheet[row_number - 1]
                ),
            )
        )
    return records


def parse_single_university_admission_plan_rows(
    document: TabularDocument,
    *,
    provenance: Provenance,
    config: PipelineConfig,
    target_university_code: str,
    subject_type: SubjectType,
    batch: str = "本科批",
) -> list[AdmissionPlanRecord]:
    """有些学校的招生计划页本身就是"这一所学校专属"的表（浙江10校里能http直采的
    几所都是这样：宁波大学/浙江工业大学等各自招生网自己的页面，不是省考试院发布的
    多校汇总表），没有"院校名称"这一列可以拿来匹配白名单——目标学校已经由
    source.target_university_code 决定，不需要再从某一列里搜校名。各校列头写法差异
    很大（"专业（类）名称" vs "专业名称"，"选考科目" vs "选科要求"），改用关键词包含
    匹配而不是`parse_admission_plan_rows`那种精确相等匹配。用真实宁波大学2026年招生
    计划页（含rowspan合并单元格）验证过。
    """
    by_code = {target.university_code: target for target in config.target_universities}
    target = by_code.get(target_university_code)
    if target is None:
        raise ValueError(f"target_university_code {target_university_code!r} not in whitelist")

    aliases = {
        "类别": ("类别",),
        "专业名称": ("专业",),
        "计划数": ("计划数", "计划人数", "招生计划"),
        "学费": ("学费", "收费"),
        "学制": ("学制", "修业年限"),
        "备注": ("备注", "报考要求"),
        "选科": ("选考科目", "选科要求", "再选科目"),
    }
    header_index = None
    columns: dict[str, int] = {}
    for index, row in enumerate(document.rows):
        compact = [re.sub(r"\s+", "", value) for value in row]
        found: dict[str, int] = {}
        for canonical, keywords in aliases.items():
            for cell_index, value in enumerate(compact):
                if value and any(keyword in value for keyword in keywords):
                    found[canonical] = cell_index
                    break
        if {"专业名称", "计划数"}.issubset(found):
            header_index = index
            columns = found
            break
    if header_index is None:
        return []

    def value(row: Sequence[str], key: str) -> str:
        position = columns.get(key)
        return row[position].strip() if position is not None and position < len(row) else ""

    records: list[AdmissionPlanRecord] = []
    current_category = ""
    for row_number in range(header_index + 1, len(document.rows)):
        row = document.rows[row_number]
        category_value = value(row, "类别")
        if category_value:
            current_category = category_value
        major_name = value(row, "专业名称")
        quota = _integer(value(row, "计划数"))
        if not major_name or quota is None or quota <= 0:
            continue
        if _PLAIN_CATEGORY_PATTERN.match(current_category):
            admission_type = "普通"
        else:
            # 类别栏还可能出现"普通类提前 三位一体 0238 只招已参加我校..."这类特殊
            # 招生机制说明（跟标准平行志愿的"普通类 0005"不是同一回事），如果不
            # 区分开，同一个专业名称在"普通类"和"三位一体"两条轨道下会撞成同一个
            # natural_key、被去重校验误当作重复记录拒绝——已用真实宁波大学数据
            # 验证过这个坑（"水产养殖学（拔尖人才创新班）"在两条轨道各出现一次）。
            # 已知具体标签优先给出可读值，否则退化成用原始类别文本兜底去重。
            admission_type = current_category or "普通"
            for label in _ADMISSION_TYPE_LABELS:
                if label in current_category:
                    admission_type = label
                    break
        records.append(
            AdmissionPlanRecord(
                province=config.province,
                year=provenance.year,
                batch=batch,
                subject_type=subject_type,
                university_code=target.university_code,
                university_name=target.name,
                major_name=major_name,
                quota=quota,
                tuition=_integer(value(row, "学费")),
                duration_years=_integer(value(row, "学制")),
                selection_requirement=value(row, "选科") or None,
                admission_type=admission_type,
                restrictions=value(row, "备注") or None,
                provenance=_row_number(
                    provenance, row_number, document.page_or_sheet[row_number - 1]
                ),
            )
        )
    return records


def parse_admission_plan_rows(
    document: TabularDocument,
    *,
    subject_type: SubjectType,
    provenance: Provenance,
    config: PipelineConfig,
    batch: str = "本科批",
) -> list[AdmissionPlanRecord]:
    aliases = {
        "院校名称": {"院校名称", "学校名称"},
        "院校代码": {"院校代码", "院校代号"},
        "专业组": {"院校专业组", "专业组", "专业组代码"},
        "专业代码": {"专业代码", "专业代号"},
        "专业名称": {"专业名称", "专业名称及方向"},
        "计划数": {"计划数", "招生计划", "计划人数"},
        "学费": {"学费", "收费标准"},
        "学制": {"学制", "修业年限"},
        "校区": {"校区", "办学地点"},
        "选科": {"选科要求", "再选科目要求"},
        "备注": {"备注", "专业备注", "报考要求"},
    }
    header_index = None
    columns: dict[str, int] = {}
    for index, row in enumerate(document.rows):
        compact = [re.sub(r"\s+", "", value) for value in row]
        found: dict[str, int] = {}
        for canonical, options in aliases.items():
            for cell_index, value in enumerate(compact):
                if value in options:
                    found[canonical] = cell_index
                    break
        if {"专业代码", "专业名称", "计划数"}.issubset(found):
            header_index = index
            columns = found
            break
    if header_index is None:
        return []

    by_name = {target.name: target for target in config.target_universities}
    current_name: str | None = None
    current_group: str | None = None
    current_provincial_code: str | None = None
    records: list[AdmissionPlanRecord] = []

    def value(row: Sequence[str], key: str) -> str:
        position = columns.get(key)
        return row[position].strip() if position is not None and position < len(row) else ""

    for row_number in range(header_index + 1, len(document.rows)):
        row = document.rows[row_number]
        name_value = value(row, "院校名称")
        matched_name = next((name for name in by_name if name in name_value), None)
        if name_value:
            # 院校名称列非空代表新院校区块开始（无论是否在白名单内），必须清空
            # 上一个院校残留的专业组/院校代号，否则会把非白名单院校或前一所
            # 院校的专业组代号错误地挂到本院校后续行上。
            current_group = None
            current_provincial_code = None
            current_name = matched_name
        code_value = value(row, "院校代码")
        if code_value:
            current_provincial_code = code_value
        group_value = value(row, "专业组")
        group_match = re.search(r"([A-Z]?\d{2,3})", group_value)
        if group_match:
            current_group = group_match.group(1)
        if not current_name or not current_group:
            continue
        major_code = value(row, "专业代码")
        major_name = value(row, "专业名称")
        quota = _integer(value(row, "计划数"))
        if not major_code or not major_name or quota is None or quota <= 0:
            continue
        tuition = _integer(value(row, "学费"))
        duration = _integer(value(row, "学制"))
        remarks = value(row, "备注")
        admission_type = "普通"
        combined = " ".join(row)
        for label in _ADMISSION_TYPE_LABELS:
            if label in combined:
                admission_type = label
                break
        target = by_name[current_name]
        records.append(
            AdmissionPlanRecord(
                province=config.province,
                year=provenance.year,
                batch=batch,
                subject_type=subject_type,
                university_code=target.university_code,
                university_name=current_name,
                provincial_university_code=current_provincial_code,
                major_group_code=current_group,
                major_code=major_code,
                major_name=major_name,
                quota=quota,
                tuition=tuition,
                duration_years=duration,
                campus=value(row, "校区") or None,
                selection_requirement=value(row, "选科") or None,
                admission_type=admission_type,
                restrictions=remarks or None,
                provenance=_row_number(
                    provenance, row_number + 1, document.page_or_sheet[row_number]
                ),
            )
        )
    return records
