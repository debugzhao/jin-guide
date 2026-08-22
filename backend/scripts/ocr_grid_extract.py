"""Reusable helpers for extracting one column's values from a scanned/screenshotted
table image (e.g. a newspaper-style admission-plan matrix with dozens of province
columns) without relying on OCR to read the (often garbled/merged) header text.

Background: macOS Vision OCR (`scripts/macos_vision_ocr.swift`) reliably reads
individual digits but frequently merges adjacent Chinese header cells into one text
blob and mis-recognizes small/colored Chinese characters — unusable for figuring out
exactly which pixel range belongs to which column. Table border lines are far more
reliable: a true grid line spans nearly its entire row/column length, so scanning for
columns/rows whose "dark pixel fraction" is close to 1.0 finds the true separators
even when individual OCR characters fail.

Usage pattern (see backend/data_pipeline/docs/10_shanghai_top10_data_collection_status.md
"需要人决策的架构问题 #3" for the worked example on 上海交通大学's admission-plan image):

    from scripts.ocr_grid_extract import find_grid_lines, make_two_column_strip

    vlines = find_grid_lines(image_path, axis="v", y_range=(375, 1740), x_range=(0, 2244))
    hlines = find_grid_lines(image_path, axis="h", y_range=(375, 1740), x_range=(668, 2044))
    # Manually confirm column order once by eye against a header crop, then:
    make_two_column_strip(image_path, label_x=(0, 544), target_x=(1034, 1079),
                           y_range=(375, 750), out_path="/tmp/strip1.png")
    # Read the strip visually (Claude Read tool) row by row — this fully avoids
    # miscounting across dozens of columns, which is the failure mode this exists to
    # prevent. Cross-check the sum against the table's own "总计" row when present.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw


def _cluster(values: list[int], gap: int = 3) -> list[int]:
    """Merge consecutive pixel indices within `gap` of each other into one line position."""
    if not values:
        return []
    values = sorted(values)
    groups: list[list[int]] = [[values[0]]]
    for v in values[1:]:
        if v - groups[-1][-1] <= gap:
            groups[-1].append(v)
        else:
            groups.append([v])
    return [int(round(sum(g) / len(g))) for g in groups]


def find_grid_lines(
    image_path: str | Path,
    *,
    axis: str,
    y_range: tuple[int, int],
    x_range: tuple[int, int],
    dark_threshold: int = 150,
    line_fraction: float = 0.85,
) -> list[int]:
    """Find pixel positions of full-length table border lines.

    axis="v" finds vertical column separators (scans dark-pixel fraction per column,
    over the given y_range, restricted to x_range). axis="h" finds horizontal row
    separators (per row, over x_range, restricted to y_range).

    Pick x_range/y_range to cover ONLY the region where the line you want truly spans
    edge-to-edge — e.g. horizontal separators between data rows often don't extend
    under a wide free-text label column, so scan just the numeric-columns sub-range.
    """
    arr = np.array(Image.open(image_path).convert("L"))
    y0, y1 = y_range
    x0, x1 = x_range
    region = arr[y0:y1, x0:x1]
    dark = region < dark_threshold
    if axis == "v":
        frac = dark.mean(axis=0)
        positions = [x0 + i for i, f in enumerate(frac) if f > line_fraction]
    elif axis == "h":
        frac = dark.mean(axis=1)
        positions = [y0 + i for i, f in enumerate(frac) if f > line_fraction]
    else:
        raise ValueError("axis must be 'v' or 'h'")
    return _cluster(positions)


def make_two_column_strip(
    image_path: str | Path,
    *,
    label_x: tuple[int, int],
    target_x: tuple[int, int],
    y_range: tuple[int, int],
    out_path: str | Path,
    scale: int = 2,
) -> None:
    """Crop the row-label column and one target data column side by side (with a
    yellow separator) so the two can be read visually without counting across the
    other columns in between — the failure mode this whole module exists to avoid.
    """
    im = Image.open(image_path).convert("RGB")
    y0, y1 = y_range
    label = im.crop((label_x[0], y0, label_x[1], y1))
    target = im.crop((target_x[0], y0, target_x[1], y1))
    gap = 20
    combo = Image.new("RGB", (label.width + gap + target.width, label.height), (255, 255, 255))
    combo.paste(label, (0, 0))
    combo.paste(target, (label.width + gap, 0))
    ImageDraw.Draw(combo).rectangle(
        [label.width, 0, label.width + gap - 1, label.height - 1], fill=(255, 255, 0)
    )
    combo = combo.resize((combo.width * scale, combo.height * scale))
    combo.save(out_path)
