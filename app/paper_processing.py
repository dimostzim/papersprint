from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import fitz


@dataclass(frozen=True)
class SentenceSpan:
    text: str
    page_number: int
    rects: list[list[float]]


@dataclass(frozen=True)
class ExtractedPaper:
    title: str
    full_text: str
    pages: list[dict[str, Any]]
    sentence_spans: list[SentenceSpan]


def slugify(value: str) -> str:
    clean = re.sub(r"[^a-zA-Z0-9]+", "-", value.lower()).strip("-")
    return clean or "paper"


def normalize_text(value: str) -> str:
    value = value.replace("\x00", " ").replace("\n", " ")
    return re.sub(r"\s+", " ", value).strip()


def clean_pdf_text(value: str) -> str:
    return str(value).replace("\x00", " ")


def file_digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def split_sentences(text: str) -> list[str]:
    normalized = normalize_text(text)
    parts = re.split(r"(?<=[.!?])\s+(?=[A-Z0-9(\[])", normalized)
    return [part.strip() for part in parts if len(part.strip()) >= 45]


def union_rect(rects: list[list[float]]) -> list[list[float]]:
    if not rects:
        return []
    x0 = min(rect[0] for rect in rects)
    y0 = min(rect[1] for rect in rects)
    x1 = max(rect[2] for rect in rects)
    y1 = max(rect[3] for rect in rects)
    return [[round(x0, 2), round(y0, 2), round(x1, 2), round(y1, 2)]]


def choose_title(pdf_path: Path, doc: fitz.Document, full_text: str) -> str:
    metadata_title = normalize_text(doc.metadata.get("title", ""))
    if metadata_title and len(metadata_title) > 8 and metadata_title.lower() != "untitled":
        return metadata_title[:220]

    for line in full_text.splitlines():
        candidate = normalize_text(line)
        if 20 <= len(candidate) <= 220 and not candidate.lower().startswith(("arxiv:", "abstract")):
            return candidate

    return pdf_path.stem


def extract_page_text(page: fitz.Page) -> str:
    parts = []
    for block in page.get_text("blocks"):
        if len(block) >= 7 and block[6] != 0:
            continue
        text = clean_pdf_text(block[4]).strip()
        if text:
            parts.append(text)
    return "\n".join(parts)


def extract_pdf(pdf_path: Path) -> ExtractedPaper:
    doc = fitz.open(pdf_path)
    pages: list[dict[str, Any]] = []
    sentence_spans: list[SentenceSpan] = []
    full_text_parts: list[str] = []

    for page_index, page in enumerate(doc):
        page_number = page_index + 1
        text_dict = page.get_text("dict")
        page_text_parts: list[str] = []

        for block in text_dict.get("blocks", []):
            if block.get("type") != 0:
                continue

            span_texts: list[str] = []
            span_rects: list[list[float]] = []
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    text = normalize_text(span.get("text", ""))
                    if not text:
                        continue
                    bbox = span.get("bbox", [0, 0, 0, 0])
                    span_texts.append(text)
                    span_rects.append([round(float(value), 2) for value in bbox])

            block_text = normalize_text(" ".join(span_texts))
            if not block_text:
                continue

            page_text_parts.append(block_text)
            block_rect = union_rect(span_rects)
            for sentence in split_sentences(block_text):
                sentence_spans.append(SentenceSpan(sentence, page_number, block_rect))

        block_page_text = "\n".join(page_text_parts)
        page_text = extract_page_text(page) or block_page_text
        full_text_parts.append(page_text)
        pages.append(
            {
                "page_number": page_number,
                "width": round(float(page.rect.width), 2),
                "height": round(float(page.rect.height), 2),
                "text": page_text,
            }
        )

    full_text = "\n\n".join(full_text_parts)
    title = choose_title(pdf_path, doc, full_text)
    doc.close()
    return ExtractedPaper(title, full_text, pages, sentence_spans)


def score_match(snippet: str, candidate: str) -> float:
    snippet_words = token_set(snippet)
    candidate_words = token_set(candidate)
    if not snippet_words or not candidate_words:
        return 0.0
    return len(snippet_words & candidate_words) / len(snippet_words)


def token_set(value: str) -> set[str]:
    tokens = re.findall(r"[a-zA-Z][a-zA-Z0-9-]{2,}", value.lower())
    normalized = set()
    for token in tokens:
        if token.endswith("ies") and len(token) > 4:
            normalized.add(f"{token[:-3]}y")
        elif token.endswith("s") and len(token) > 4:
            normalized.add(token[:-1])
        else:
            normalized.add(token)
    return normalized


def search_phrases(snippet: str) -> list[str]:
    normalized = normalize_text(snippet)
    if not normalized:
        return []

    phrases = [normalized[:180]]
    words = normalized.split()
    for size in (16, 12, 9):
        if len(words) < size:
            continue
        starts = {0, max(0, len(words) // 3), max(0, len(words) // 2)}
        for start in starts:
            phrase = " ".join(words[start : start + size])
            if len(phrase) >= 40:
                phrases.append(phrase)

    unique: list[str] = []
    for phrase in phrases:
        if phrase not in unique:
            unique.append(phrase)
    return unique


def find_exact_rects(pdf_path: Path, snippet: str) -> tuple[int | None, list[list[float]]]:
    phrases = search_phrases(snippet)
    if not phrases:
        return None, []

    doc = fitz.open(pdf_path)
    try:
        for page_index, page in enumerate(doc):
            for phrase in phrases:
                rects = page.search_for(phrase)
                if rects:
                    return page_index + 1, [
                        [round(rect.x0, 2), round(rect.y0, 2), round(rect.x1, 2), round(rect.y1, 2)]
                        for rect in rects[:10]
                    ]
    finally:
        doc.close()

    return None, []


def ground_highlights(
    pdf_path: Path,
    highlights: list[dict[str, str]],
    sentence_spans: list[SentenceSpan],
) -> list[dict[str, Any]]:
    grounded: list[dict[str, Any]] = []

    for item in highlights:
        snippet = normalize_text(item.get("snippet", ""))
        page_number, rects = find_exact_rects(pdf_path, snippet)

        best_span: SentenceSpan | None = None
        best_score = 0.0
        if not rects:
            for span in sentence_spans:
                score = score_match(snippet, span.text)
                if snippet and snippet.lower() in span.text.lower():
                    score = 1.0
                if score > best_score:
                    best_span = span
                    best_score = score

        if not rects and best_span and best_score >= 0.38:
            page_number = best_span.page_number
            rects = best_span.rects

        grounded.append(
            {
                "label": sanitize_label(item.get("label", "important")),
                "snippet": snippet,
                "reason": normalize_text(item.get("reason", "")),
                "page_number": page_number,
                "rects": rects,
            }
        )

    return sort_highlights(grounded)


def sort_highlights(highlights: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(highlights, key=highlight_position)


def highlight_position(highlight: dict[str, Any]) -> tuple[int, float, float]:
    page_number = highlight.get("page_number") or 9999
    rects = highlight.get("rects") or []
    if not rects:
        return int(page_number), 9999.0, 9999.0
    first_rect = sorted(rects, key=lambda rect: (rect[1], rect[0]))[0]
    return int(page_number), float(first_rect[1]), float(first_rect[0])


def sanitize_label(label: str) -> str:
    normalized = re.sub(r"[^a-z]+", "", label.lower())
    aliases = {
        "objective": "goal",
        "contribution": "goal",
        "finding": "result",
        "results": "result",
        "approach": "method",
        "methods": "method",
        "caveat": "limitation",
        "term": "definition",
    }
    normalized = aliases.get(normalized, normalized)
    if normalized in {"goal", "method", "result", "limitation", "definition"}:
        return normalized
    return "important"


def public_page_sizes(pages: list[dict[str, Any]]) -> list[dict[str, float | int]]:
    return [
        {
            "page_number": page["page_number"],
            "width": page["width"],
            "height": page["height"],
        }
        for page in pages
    ]
