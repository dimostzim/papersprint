from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

import fitz

from .ai import analyze_page_figures
from .paper_processing import ExtractedPaper, normalize_text

PAGE_IMAGE_ZOOM = 1.6
FIGURE_IMAGE_ZOOM = 2.4
FIGURE_TYPES = {"figure", "table", "plot", "diagram", "screenshot", "equation", "other"}


def int_env(name: str, default: int) -> int:
    try:
        return max(1, int(os.getenv(name, str(default))))
    except ValueError:
        return default


def figure_directory(figures_dir: Path, paper_id: str) -> Path:
    safe_id = re.sub(r"[^a-zA-Z0-9_-]+", "-", paper_id)
    return figures_dir / safe_id


def render_page_image(pdf_path: Path, page_number: int, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    doc = fitz.open(pdf_path)
    try:
        page = doc[page_number - 1]
        pixmap = page.get_pixmap(matrix=fitz.Matrix(PAGE_IMAGE_ZOOM, PAGE_IMAGE_ZOOM), alpha=False)
        pixmap.save(output_path)
    finally:
        doc.close()


def crop_figure_image(pdf_path: Path, page_number: int, bbox_pct: list[float], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    doc = fitz.open(pdf_path)
    try:
        page = doc[page_number - 1]
        page_rect = page.rect
        x0, y0, x1, y1 = bbox_pct
        clip = fitz.Rect(
            page_rect.x0 + page_rect.width * x0 / 100,
            page_rect.y0 + page_rect.height * y0 / 100,
            page_rect.x0 + page_rect.width * x1 / 100,
            page_rect.y0 + page_rect.height * y1 / 100,
        ) & page_rect
        if clip.is_empty or clip.width < 8 or clip.height < 8:
            clip = page_rect
        pixmap = page.get_pixmap(matrix=fitz.Matrix(FIGURE_IMAGE_ZOOM, FIGURE_IMAGE_ZOOM), clip=clip, alpha=False)
        pixmap.save(output_path)
    finally:
        doc.close()


def coerce_bbox_pct(value: Any) -> list[float]:
    if not isinstance(value, list) or len(value) != 4:
        return [0.0, 0.0, 100.0, 100.0]

    numbers = []
    for item in value:
        try:
            numbers.append(float(item))
        except (TypeError, ValueError):
            return [0.0, 0.0, 100.0, 100.0]

    x0, y0, x1, y1 = numbers
    x0, x1 = sorted((max(0.0, min(100.0, x0)), max(0.0, min(100.0, x1))))
    y0, y1 = sorted((max(0.0, min(100.0, y0)), max(0.0, min(100.0, y1))))
    if x1 - x0 < 2 or y1 - y0 < 2:
        return [0.0, 0.0, 100.0, 100.0]
    return [round(x0, 2), round(y0, 2), round(x1, 2), round(y1, 2)]


def sanitize_figure_type(value: Any) -> str:
    normalized = re.sub(r"[^a-z]+", "", str(value).lower())
    return normalized if normalized in FIGURE_TYPES else "other"


def normalize_figure_items(payload: dict[str, Any], page_number: int) -> list[dict[str, Any]]:
    raw_figures = payload.get("figures", [])
    if not isinstance(raw_figures, list):
        return []

    figures = []
    for index, item in enumerate(raw_figures):
        if not isinstance(item, dict):
            continue

        title = normalize_text(str(item.get("title", "")))[:180]
        caption = normalize_text(str(item.get("caption", "")))[:900]
        explanation = normalize_text(str(item.get("explanation", "")))[:900]
        why_it_matters = normalize_text(str(item.get("why_it_matters", "")))[:700]
        if not any([title, caption, explanation, why_it_matters]):
            continue

        label = normalize_text(str(item.get("label", "")))[:120] or f"Page {page_number} visual {index + 1}"
        figures.append(
            {
                "id": "",
                "page_number": page_number,
                "type": sanitize_figure_type(item.get("type", "other")),
                "label": label,
                "title": title or label,
                "bbox_pct": coerce_bbox_pct(item.get("bbox_pct")),
                "caption": caption,
                "explanation": explanation,
                "why_it_matters": why_it_matters,
                "uncertainty": normalize_text(str(item.get("uncertainty", "")))[:500],
            }
        )

    return figures


def analyze_figures(
    pdf_path: Path,
    extracted: ExtractedPaper,
    paper_id: str,
    figures_dir: Path,
    provider: str | None,
    api_key: str | None = None,
) -> dict[str, Any]:
    paper_dir = figure_directory(figures_dir, paper_id)
    paper_dir.mkdir(parents=True, exist_ok=True)

    max_pages = int_env("FIGURE_ANALYSIS_MAX_PAGES", 20)
    max_figures = int_env("FIGURE_ANALYSIS_MAX_FIGURES", 40)
    warnings = []
    figures = []
    provider_used = "unknown"

    pages = extracted.pages[:max_pages]
    if len(extracted.pages) > max_pages:
        warnings.append(f"Figure analysis inspected the first {max_pages} pages only.")

    for page in pages:
        if len(figures) >= max_figures:
            warnings.append(f"Figure analysis stopped after {max_figures} visuals.")
            break

        page_number = int(page["page_number"])
        page_image = paper_dir / f"page-{page_number}.jpg"
        render_page_image(pdf_path, page_number, page_image)
        payload = analyze_page_figures(page_number, str(page.get("text", "")), page_image, provider, api_key)
        provider_used = str(payload.get("provider_used", provider_used))

        for page_index, figure in enumerate(normalize_figure_items(payload, page_number), start=1):
            if len(figures) >= max_figures:
                break
            figure_id = f"p{page_number}-{page_index}"
            image_file = f"{figure_id}.jpg"
            crop_figure_image(pdf_path, page_number, figure["bbox_pct"], paper_dir / image_file)
            figure["id"] = figure_id
            figure["image_file"] = image_file
            figures.append(figure)

    return {
        "figures": figures,
        "figure_warnings": warnings,
        "figure_provider_used": provider_used,
    }
