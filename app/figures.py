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
VISUAL_CUE_RE = re.compile(
    r"\b(?:fig(?:ure)?\.?|tables?|schemes?|diagrams?|plots?)\s*(?:s?\d+|[ivxlcdm]+|[a-z])\b",
    re.IGNORECASE,
)


def int_env(name: str, default: int) -> int:
    try:
        return max(1, int(os.getenv(name, str(default))))
    except ValueError:
        return default


def figure_directory(figures_dir: Path, paper_id: str) -> Path:
    safe_id = re.sub(r"[^a-zA-Z0-9_-]+", "-", paper_id)
    return figures_dir / safe_id


def page_text_has_visual_cue(text: str) -> bool:
    return bool(VISUAL_CUE_RE.search(normalize_text(text)))


def page_has_pdf_visuals(page: fitz.Page) -> bool:
    page_area = max(float(page.rect.width * page.rect.height), 1.0)
    if page.get_images(full=True):
        return True

    try:
        if page.find_tables().tables:
            return True
    except (AttributeError, RuntimeError, ValueError):
        pass

    try:
        drawings = page.get_drawings()
    except RuntimeError:
        return False

    for drawing in drawings:
        rect = drawing.get("rect")
        if rect and float(rect.width * rect.height) >= page_area * 0.02:
            return True
    return len(drawings) >= 12


def visual_candidate_pages(pdf_path: Path, pages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    text_candidates = {
        int(page.get("page_number", 0))
        for page in pages
        if page_text_has_visual_cue(str(page.get("text", "")))
    }
    structural_candidates: set[int] = set()

    try:
        doc = fitz.open(pdf_path)
    except (RuntimeError, fitz.FileDataError, fitz.EmptyFileError):
        doc = None

    if doc:
        try:
            for page in pages:
                page_number = int(page.get("page_number", 0))
                if 1 <= page_number <= len(doc) and page_has_pdf_visuals(doc[page_number - 1]):
                    structural_candidates.add(page_number)
        finally:
            doc.close()

    candidate_numbers = text_candidates | structural_candidates
    return [page for page in pages if int(page.get("page_number", 0)) in candidate_numbers]


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


def ensure_figure_images(
    pdf_path: Path,
    figures_dir: Path,
    paper_id: str,
    figures: list[dict[str, Any]],
) -> None:
    if not figures or not pdf_path.exists():
        return

    paper_dir = figure_directory(figures_dir, paper_id)
    for figure in figures:
        image_file = Path(str(figure.get("image_file", ""))).name
        if not image_file:
            continue

        try:
            page_number = int(figure.get("page_number") or 0)
        except (TypeError, ValueError):
            continue
        if page_number < 1:
            continue

        image_path = paper_dir / image_file
        if image_path.exists():
            continue

        try:
            crop_figure_image(pdf_path, page_number, coerce_bbox_pct(figure.get("bbox_pct")), image_path)
        except (IndexError, RuntimeError, ValueError, fitz.FileDataError, fitz.EmptyFileError):
            continue


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
    model: str | None = None,
    reasoning_effort: str | None = None,
) -> dict[str, Any]:
    paper_dir = figure_directory(figures_dir, paper_id)
    paper_dir.mkdir(parents=True, exist_ok=True)

    max_pages = int_env("FIGURE_ANALYSIS_MAX_PAGES", 20)
    max_figures = int_env("FIGURE_ANALYSIS_MAX_FIGURES", 40)
    warnings = []
    figures = []
    provider_used = "unknown"

    inspected_pages = extracted.pages[:max_pages]
    if len(extracted.pages) > max_pages:
        warnings.append(f"Figure analysis inspected the first {max_pages} pages only.")

    pages = visual_candidate_pages(pdf_path, inspected_pages)
    skipped_pages = len(inspected_pages) - len(pages)
    if skipped_pages > 0:
        warnings.append(f"Figure analysis skipped {skipped_pages} pages without figure/table signals.")
    if not pages:
        warnings.append("No pages with figure/table signals were detected.")

    for page in pages:
        if len(figures) >= max_figures:
            warnings.append(f"Figure analysis stopped after {max_figures} visuals.")
            break

        page_number = int(page["page_number"])
        page_image = paper_dir / f"page-{page_number}.jpg"
        render_page_image(pdf_path, page_number, page_image)
        payload = analyze_page_figures(
            page_number,
            str(page.get("text", "")),
            page_image,
            provider,
            api_key,
            model,
            reasoning_effort,
        )
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
