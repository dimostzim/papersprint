from __future__ import annotations

import re
from collections import defaultdict
from copy import deepcopy
from pathlib import Path
from typing import Any

import fitz

from .paper_processing import ExtractedPaper, normalize_text

REFERENCE_HEADING_RE = re.compile(r"(?im)^\s*(references|bibliography|works\s+cited)\b")
BRACKET_REFERENCE_RE = re.compile(r"(?<![A-Za-z0-9])\[(\d{1,4})\]\s+")
NUMBERED_REFERENCE_RE = re.compile(r"(?m)^\s*(\d{1,4})\.\s+")
INLINE_CITATION_RE = re.compile(r"\[(\d{1,4}(?:\s*(?:,|;|-|–|—)\s*\d{1,4})*)\]")
AUTHOR_START_RE = re.compile(r"^[^\s,.]+(?:\s+[^\s,.]+)*\s+[A-Z]{1,4}(?:,|\.|\s+et\s+al\.)")
CONTROL_RE = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")
YEAR_RE = re.compile(r"\b(19\d{2}|20\d{2})\b")

MAX_REFERENCES = 250
MAX_CONTEXTS_PER_CITATION = 8
MAX_REFERENCE_CHARS = 1400
MAX_CONTEXT_CHARS = 700
MAX_RECTS_PER_CITATION_CONTEXT = 8


def extract_citations(extracted: ExtractedPaper) -> list[dict[str, Any]]:
    body_pages, references_text = split_body_and_references(extracted)
    contexts_by_number = collect_inline_contexts(body_pages)
    references = parse_references(references_text)

    if references and not any(reference.get("number") is not None for reference in references):
        contexts_by_id = collect_author_year_contexts(body_pages, references)
        return [
            {
                **reference,
                "contexts": contexts_by_id.get(str(reference["id"]), []),
                "context_count": len(contexts_by_id.get(str(reference["id"]), [])),
            }
            for reference in references
        ]

    citations = []
    seen_numbers: set[int] = set()
    for reference in references:
        number = int(reference["number"])
        seen_numbers.add(number)
        contexts = contexts_by_number.get(number, [])
        citations.append(
            {
                **reference,
                "contexts": contexts,
                "context_count": len(contexts),
            }
        )

    for number in sorted(contexts_by_number):
        if number in seen_numbers or len(citations) >= MAX_REFERENCES:
            continue
        contexts = contexts_by_number[number]
        citations.append(
            {
                "id": f"ref-{number}",
                "label": f"[{number}]",
                "number": number,
                "title": f"Citation [{number}]",
                "authors": "",
                "year": "",
                "raw_reference": "",
                "contexts": contexts,
                "context_count": len(contexts),
            }
        )

    return sorted(citations, key=lambda item: int(item.get("number", item.get("sort_index", 99999))))


def ground_citation_rects(pdf_path: Path, citations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grounded = deepcopy(citations)
    doc = fitz.open(pdf_path)
    try:
        for citation in grounded:
            for context in citation.get("contexts", []):
                page_number = int(context.get("page_number") or 0)
                marker = str(context.get("marker", "")).strip()
                if not page_number or not marker or page_number > len(doc):
                    context["rects"] = []
                    continue

                page = doc[page_number - 1]
                rects = []
                for search_text in citation_search_variants(marker):
                    rects = page.search_for(search_text)
                    if rects:
                        break

                context["rects"] = [
                    [round(rect.x0, 2), round(rect.y0, 2), round(rect.x1, 2), round(rect.y1, 2)]
                    for rect in rects[:MAX_RECTS_PER_CITATION_CONTEXT]
                ]
    finally:
        doc.close()
    return grounded


def citation_search_variants(marker: str) -> list[str]:
    variants = [marker]
    if marker.startswith("(") and marker.endswith(")"):
        variants.append(marker[1:-1])
    if " (" in marker and marker.endswith(")"):
        variants.append(marker.replace(" (", " ").rstrip(")"))
    variants.extend(
        [
            re.sub(r"\s+", "", marker),
            re.sub(r"\s*,\s*", ", ", marker),
            re.sub(r"\s*;\s*", "; ", marker),
            marker.replace(", ", " "),
        ]
    )

    for variant in list(variants):
        variants.extend(
            [
                variant.replace("-", "–"),
                variant.replace("–", "-").replace("—", "-"),
            ]
        )

    unique_variants = []
    for variant in variants:
        if variant and variant not in unique_variants:
            unique_variants.append(variant)
    return unique_variants


def split_body_and_references(extracted: ExtractedPaper) -> tuple[list[dict[str, Any]], str]:
    body_pages: list[dict[str, Any]] = []
    reference_parts: list[str] = []
    in_references = False

    for page in extracted.pages:
        page_number = int(page.get("page_number", 0))
        page_text = str(page.get("text", ""))

        if in_references:
            reference_parts.append(page_text)
            continue

        heading = REFERENCE_HEADING_RE.search(page_text)
        if heading:
            body_pages.append({"page_number": page_number, "text": page_text[: heading.start()]})
            reference_parts.append(page_text[heading.end() :])
            in_references = True
        else:
            body_pages.append({"page_number": page_number, "text": page_text})

    return body_pages, "\n".join(reference_parts)


def parse_references(references_text: str) -> list[dict[str, Any]]:
    text = references_text.strip()
    if not text:
        return []

    matches = list(BRACKET_REFERENCE_RE.finditer(text))
    if not matches:
        matches = list(NUMBERED_REFERENCE_RE.finditer(text))
    if not matches:
        return parse_author_year_references(text)

    references = []
    for index, match in enumerate(matches[:MAX_REFERENCES]):
        next_start = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        raw_reference = clean_reference(text[match.end() : next_start])
        if not raw_reference:
            continue

        number = int(match.group(1))
        year = extract_year(raw_reference)
        references.append(
            {
                "id": f"ref-{number}",
                "label": f"[{number}]",
                "number": number,
                "title": guess_reference_title(raw_reference),
                "authors": guess_reference_authors(raw_reference, year),
                "year": year,
                "raw_reference": raw_reference[:MAX_REFERENCE_CHARS],
            }
        )

    return references


def parse_author_year_references(references_text: str) -> list[dict[str, Any]]:
    lines = [line.strip() for line in references_text.splitlines() if line.strip()]
    entries: list[list[str]] = []
    current: list[str] = []

    for line in lines:
        if looks_like_author_reference_start(line) and current and YEAR_RE.search(" ".join(current)):
            entries.append(current)
            current = [line]
        else:
            current.append(line)

    if current and YEAR_RE.search(" ".join(current)):
        entries.append(current)

    references = []
    for index, entry_lines in enumerate(entries[:MAX_REFERENCES], start=1):
        raw_reference = clean_reference(" ".join(entry_lines))
        year = extract_year(raw_reference)
        first_author = extract_first_author(raw_reference)
        if not year or not first_author:
            continue

        label = f"{first_author} et al. {year}" if " et al." in raw_reference else f"{first_author} {year}"
        references.append(
            {
                "id": f"ref-author-{index}",
                "label": label,
                "number": None,
                "sort_index": index,
                "title": guess_author_year_title(raw_reference),
                "authors": extract_author_prefix(raw_reference),
                "year": year,
                "first_author": first_author,
                "second_author": extract_second_author(raw_reference),
                "raw_reference": raw_reference[:MAX_REFERENCE_CHARS],
            }
        )

    return references


def looks_like_author_reference_start(line: str) -> bool:
    return bool(AUTHOR_START_RE.search(clean_reference(line)[:180]))


def collect_inline_contexts(body_pages: list[dict[str, Any]]) -> dict[int, list[dict[str, Any]]]:
    contexts_by_number: dict[int, list[dict[str, Any]]] = defaultdict(list)
    seen: set[tuple[int, str]] = set()

    for page in body_pages:
        page_number = int(page.get("page_number", 0))
        page_text = normalize_text(str(page.get("text", "")))
        for marker in INLINE_CITATION_RE.finditer(page_text):
            context_sentence = context_around_match(page_text, marker.start(), marker.end())
            for number in expand_citation_numbers(marker.group(1)):
                key = (number, context_sentence)
                if key in seen:
                    continue
                seen.add(key)

                contexts = contexts_by_number[number]
                if len(contexts) >= MAX_CONTEXTS_PER_CITATION:
                    continue
                contexts.append(
                    {
                        "page_number": page_number,
                        "marker": marker.group(0),
                        "sentence": context_sentence[:MAX_CONTEXT_CHARS],
                    }
                )

    return dict(contexts_by_number)


def collect_author_year_contexts(
    body_pages: list[dict[str, Any]],
    references: list[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    contexts_by_id: dict[str, list[dict[str, Any]]] = defaultdict(list)
    seen: set[tuple[str, str]] = set()
    patterns = []

    for reference in references:
        first_author = str(reference.get("first_author", "")).strip()
        second_author = str(reference.get("second_author", "")).strip()
        year = str(reference.get("year", "")).strip()
        if not first_author or not year:
            continue
        pattern_parts = [
            rf"\b{re.escape(first_author)}(?:\s+et\s+al\.)?(?:\s*\({re.escape(year)}\)|,?\s+{re.escape(year)})"
        ]
        if second_author:
            pattern_parts.append(
                rf"\b{re.escape(first_author)}\s+and\s+{re.escape(second_author)}(?:\s*\({re.escape(year)}\)|,?\s+{re.escape(year)})"
            )
        patterns.append((str(reference["id"]), re.compile("|".join(pattern_parts), re.IGNORECASE)))

    for page in body_pages:
        page_number = int(page.get("page_number", 0))
        page_text = normalize_text(str(page.get("text", "")))
        for reference_id, pattern in patterns:
            for match in pattern.finditer(page_text):
                context_sentence = context_around_match(page_text, match.start(), match.end())
                key = (reference_id, context_sentence)
                if key in seen:
                    continue
                seen.add(key)

                contexts = contexts_by_id[reference_id]
                if len(contexts) >= MAX_CONTEXTS_PER_CITATION:
                    continue
                contexts.append(
                    {
                        "page_number": page_number,
                        "marker": match.group(0),
                        "sentence": context_sentence[:MAX_CONTEXT_CHARS],
                    }
                )

    return dict(contexts_by_id)


def context_around_match(text: str, start: int, end: int) -> str:
    left_candidates = [text.rfind(separator, 0, start) for separator in (". ", "? ", "! ")]
    left = max(left_candidates)
    left = left + 2 if left != -1 else max(0, start - 220)

    right_candidates = [position for separator in (". ", "? ", "! ") if (position := text.find(separator, end)) != -1]
    right = min(right_candidates) + 1 if right_candidates else min(len(text), end + 480)
    return text[left:right].strip()


def expand_citation_numbers(value: str) -> list[int]:
    numbers: list[int] = []
    normalized = value.replace("–", "-").replace("—", "-").replace(";", ",")

    for part in normalized.split(","):
        clean = part.strip()
        if not clean:
            continue

        if "-" in clean:
            start_text, end_text = [item.strip() for item in clean.split("-", 1)]
            if not start_text.isdigit() or not end_text.isdigit():
                continue
            start = int(start_text)
            end = int(end_text)
            if start > end or end - start > 25:
                continue
            numbers.extend(range(start, end + 1))
        elif clean.isdigit():
            numbers.append(int(clean))

    unique_numbers = []
    for number in numbers:
        if 0 < number < 10000 and number not in unique_numbers:
            unique_numbers.append(number)
    return unique_numbers


def clean_reference(value: str) -> str:
    text = normalize_text(CONTROL_RE.sub("", str(value)).replace("\xad", ""))
    return re.sub(r"\s+", " ", text).strip(" .")


def extract_year(raw_reference: str) -> str:
    match = YEAR_RE.search(raw_reference)
    return match.group(1) if match else ""


def guess_reference_authors(raw_reference: str, year: str) -> str:
    if not year:
        return ""
    year_index = raw_reference.find(year)
    if year_index <= 0:
        return ""
    return raw_reference[:year_index].strip(" .")[:220]


def extract_first_author(raw_reference: str) -> str:
    author_segment = extract_author_prefix(raw_reference)
    author_segment = author_segment.split(",", 1)[0]
    author_segment = re.sub(r"\s+et\s+al$", "", author_segment, flags=re.IGNORECASE)
    author_segment = re.sub(r"\s+[A-Z]{1,4}$", "", author_segment)
    return author_segment.strip()


def extract_second_author(raw_reference: str) -> str:
    author_prefix = extract_author_prefix(raw_reference)
    if " et al" in author_prefix:
        return ""
    parts = [part.strip() for part in author_prefix.split(",")]
    if len(parts) < 2:
        return ""
    second_author = re.sub(r"\s+[A-Z]{1,4}$", "", parts[1]).strip()
    return second_author


def extract_author_prefix(raw_reference: str) -> str:
    et_al_match = re.search(r"\bet\s+al\.", raw_reference, flags=re.IGNORECASE)
    if et_al_match and et_al_match.start() < 180:
        return raw_reference[: et_al_match.end()].strip(" .")

    first_period = raw_reference.find(". ")
    if first_period != -1:
        return raw_reference[:first_period].strip(" .")
    return raw_reference[:180].strip(" .")


def strip_author_prefix(raw_reference: str) -> str:
    et_al_match = re.search(r"\bet\s+al\.\s+", raw_reference, flags=re.IGNORECASE)
    if et_al_match:
        return raw_reference[et_al_match.end() :].strip()

    first_period = raw_reference.find(". ")
    if first_period != -1:
        return raw_reference[first_period + 2 :].strip()
    return raw_reference


def guess_author_year_title(raw_reference: str) -> str:
    after_authors = strip_author_prefix(raw_reference)
    title_match = re.match(
        r"(.{10,300}?)(?:\.\s+[A-Z][A-Za-z .()&-]{2,120}\s+(?:19|20)\d{2}[;,. ]|\.\s+(?:bioRxiv|arXiv),?|\.\s+https?://|$)",
        after_authors,
    )
    if title_match:
        return title_match.group(1).strip()
    return guess_reference_title(raw_reference)


def guess_reference_title(raw_reference: str) -> str:
    year_match = YEAR_RE.search(raw_reference)
    if year_match:
        after_year = raw_reference[year_match.end() :].lstrip(" .")
        title_match = re.match(r"(.{12,220}?)(?:\.\s+|$)", after_year)
        if title_match:
            return title_match.group(1).strip()

    first_sentence = re.match(r"(.{12,180}?)(?:\.\s+|$)", raw_reference)
    if first_sentence:
        return first_sentence.group(1).strip()
    return raw_reference[:160]
