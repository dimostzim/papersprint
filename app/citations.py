from __future__ import annotations

import re
import unicodedata
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
AUTHOR_NAME_PATTERN = r"[A-Z][A-Za-zÀ-ÖØ-öø-ÿ'’-]{1,80}"
YEAR_PATTERN = r"(?:19\d{2}|20[0-2]\d)[a-z]?"
AUTHOR_YEAR_PAREN_RE = re.compile(rf"\((?P<body>[^()]{{0,260}}\b{YEAR_PATTERN}[^()]*)\)")
AUTHOR_YEAR_ITEM_RE = re.compile(
    rf"\b(?P<first>{AUTHOR_NAME_PATTERN})(?P<etal>\s+et\s+al\.)?"
    rf"(?:\s+and\s+(?P<second>{AUTHOR_NAME_PATTERN}))?"
    rf"(?:,\s*|\s+)(?P<year>{YEAR_PATTERN})\b"
)
AUTHOR_YEAR_NARRATIVE_RE = re.compile(
    rf"\b(?P<first>{AUTHOR_NAME_PATTERN})(?P<etal>\s+et\s+al\.)?"
    rf"(?:\s+and\s+(?P<second>{AUTHOR_NAME_PATTERN}))?"
    rf"(?:(?:\s*\((?P<year_paren>{YEAR_PATTERN})\))|(?:,?\s+(?P<year>{YEAR_PATTERN})\b))"
)
AUTHOR_INITIALS_PATTERN = r"[A-Z](?:-?[A-Z]){0,3}"
AUTHOR_START_RE = re.compile(
    rf"^[^\s,.]+(?:\s+[^\s,.]+)*\s+{AUTHOR_INITIALS_PATTERN}(?:,|\.|\s+et\s+al\.)"
)
INITIAL_AUTHOR_START_RE = re.compile(
    rf"^(?:(?:[A-Z]\.|[A-Z]\.-[A-Z]\.)\s*){{1,4}}{AUTHOR_NAME_PATTERN}(?:,|\b)"
)
CONTROL_RE = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")
YEAR_RE = re.compile(r"\b(19\d{2}|20[0-2]\d)\b")
NON_AUTHOR_WORDS = {
    "Appendix",
    "Algorithm",
    "All",
    "Also",
    "Abstract",
    "As",
    "At",
    "Background",
    "Before",
    "Between",
    "By",
    "Conclusion",
    "Conclusions",
    "Data",
    "Discussion",
    "Equation",
    "Experiment",
    "Experiments",
    "Figure",
    "Fig",
    "For",
    "From",
    "Fund",
    "Funding",
    "Here",
    "In",
    "It",
    "Jan",
    "January",
    "Feb",
    "February",
    "Mar",
    "March",
    "Apr",
    "April",
    "May",
    "Jun",
    "June",
    "Jul",
    "July",
    "Aug",
    "August",
    "Sep",
    "September",
    "Oct",
    "October",
    "Nov",
    "November",
    "Dec",
    "December",
    "Introduction",
    "Method",
    "Methods",
    "Result",
    "Results",
    "Section",
    "Since",
    "Supplementary",
    "Table",
    "The",
    "There",
    "These",
    "This",
    "Those",
    "To",
    "Using",
    "We",
    "When",
    "Where",
    "While",
    "With",
    "Bioinformatics",
}

MAX_REFERENCES = 250
MAX_CONTEXTS_PER_CITATION = 64
MAX_REFERENCE_CHARS = 1400
MAX_CONTEXT_CHARS = 700
MAX_RECTS_PER_CITATION_CONTEXT = 32
CITATION_VERSION = 9


def extract_citations(extracted: ExtractedPaper) -> list[dict[str, Any]]:
    body_pages, references_text = split_body_and_references(extracted)
    contexts_by_number = collect_inline_contexts(body_pages)
    contexts_by_author_year = collect_author_year_contexts(body_pages)
    references = parse_references(references_text)

    if contexts_by_number or any(reference.get("number") is not None for reference in references):
        return build_numbered_citations(contexts_by_number, references)
    return build_author_year_citations(contexts_by_author_year, references)


def build_numbered_citations(
    contexts_by_number: dict[int, list[dict[str, Any]]],
    references: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    citations: list[dict[str, Any]] = []
    seen_numbers: set[int] = set()

    for reference in references:
        if reference.get("number") is None:
            continue
        number = int(reference["number"])
        seen_numbers.add(number)
        contexts = contexts_by_number.get(number, [])
        citations.append(
            {
                **reference,
                "resolved": True,
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
                "resolved": False,
                "contexts": contexts,
                "context_count": len(contexts),
            }
        )

    return sorted(citations, key=lambda item: int(item.get("number", item.get("sort_index", 99999))))


def build_author_year_citations(
    contexts_by_key: dict[str, list[dict[str, Any]]],
    references: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    references_by_key = {}
    for reference in references:
        for key in reference_author_year_keys(reference):
            references_by_key.setdefault(key, reference)

    citations = []
    used_reference_ids: set[str] = set()
    for sort_index, key in enumerate(sorted(contexts_by_key), start=1):
        contexts = contexts_by_key[key]
        reference = references_by_key.get(key)
        if reference:
            used_reference_ids.add(str(reference["id"]))
            citation = {**reference, "resolved": True}
        elif references and not unresolved_author_year_context_is_useful(contexts[0]):
            continue
        else:
            citation = fallback_author_year_citation(contexts[0], sort_index)

        citation["contexts"] = contexts
        citation["context_count"] = len(contexts)
        citations.append(citation)

    for reference in references:
        if reference.get("number") is not None or str(reference["id"]) in used_reference_ids:
            continue
        citations.append({**reference, "resolved": True, "contexts": [], "context_count": 0})

    return citations[:MAX_REFERENCES]


def fallback_author_year_citation(context: dict[str, Any], sort_index: int) -> dict[str, Any]:
    label = str(context.get("label", "")).strip() or str(context.get("marker", "")).strip()
    return {
        "id": f"ref-author-inline-{sort_index}",
        "label": label,
        "number": None,
        "sort_index": sort_index,
        "title": f"Citation {label}".strip(),
        "authors": "",
        "year": str(context.get("year", "")),
        "first_author": str(context.get("first_author", "")),
        "second_author": str(context.get("second_author", "")),
        "raw_reference": "",
        "resolved": False,
    }


def unresolved_author_year_context_is_useful(context: dict[str, Any]) -> bool:
    marker = str(context.get("marker", ""))
    first_author = str(context.get("first_author", ""))
    return (
        looks_like_inline_author(first_author)
        and first_author not in NON_AUTHOR_WORDS
        and bool(re.search(r"\bet\s+al\.|\band\b", marker))
    )


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
                word_rects = marker_rects_from_words(page, marker)
                if word_rects:
                    rects = word_rects
                if not rects:
                    for search_text in citation_search_variants(marker, context, include_author_fallback=True):
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


def citation_search_variants(
    marker: str,
    context: dict[str, Any] | None = None,
    include_author_fallback: bool = False,
) -> list[str]:
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
                strip_diacritics(variant),
                variant.replace("-", "–"),
                variant.replace("–", "-").replace("—", "-"),
            ]
        )

    first_author = str((context or {}).get("first_author", "")).strip()
    if include_author_fallback and first_author:
        for author_variant in [first_author, strip_diacritics(first_author)]:
            clean_author = re.sub(r"[^A-Za-zÀ-ÖØ-öø-ÿ'’-]+", "", author_variant)
            if len(clean_author) >= 5:
                variants.append(clean_author)
            if len(clean_author) >= 7:
                variants.append(clean_author[:-1])

    unique_variants = []
    for variant in variants:
        if variant and variant not in unique_variants:
            unique_variants.append(variant)
    return unique_variants


def marker_rects_from_words(page: fitz.Page, marker: str) -> list[fitz.Rect]:
    if is_numeric_bracket_marker(marker):
        return numeric_marker_rects_from_words(page, marker)

    marker_tokens = citation_marker_tokens(marker)
    if not marker_tokens:
        return []

    words = page.get_text("words")
    word_entries = [
        {
            "rect": fitz.Rect(word[:4]),
            "tokens": citation_marker_tokens(str(word[4])),
            "block": int(word[5]),
            "line": int(word[6]),
        }
        for word in words
        if citation_marker_tokens(str(word[4]))
    ]
    token_entries = [
        {**entry, "token": token}
        for entry in word_entries
        for token in entry["tokens"]
    ]
    spans = marker_token_spans(token_entries, marker_tokens)
    if not spans:
        return []

    rects: list[fitz.Rect] = []
    for start, end in spans:
        matched_entries = token_entries[start:end]
        rects_by_line: dict[tuple[int, int], fitz.Rect] = {}
        for entry in matched_entries:
            key = (entry["block"], entry["line"])
            rects_by_line[key] = rects_by_line[key] | entry["rect"] if key in rects_by_line else fitz.Rect(entry["rect"])
        rects.extend(rects_by_line.values())
    return rects


def citation_marker_tokens(value: str) -> list[str]:
    normalized = strip_diacritics(clean_citation_text(value)).lower()
    return re.findall(r"[a-z0-9]+", normalized)


def is_numeric_bracket_marker(marker: str) -> bool:
    return bool(INLINE_CITATION_RE.fullmatch(marker.strip()))


def numeric_marker_rects_from_words(page: fitz.Page, marker: str) -> list[fitz.Rect]:
    marker_tokens = citation_marker_tokens(marker)
    if not marker_tokens:
        return []

    words = page.get_text("words")
    word_entries = [
        {
            "rect": fitz.Rect(word[:4]),
            "tokens": citation_marker_tokens(str(word[4])),
            "raw": str(word[4]),
            "word_index": index,
            "block": int(word[5]),
            "line": int(word[6]),
        }
        for index, word in enumerate(words)
        if citation_marker_tokens(str(word[4]))
    ]
    token_entries = [
        {**entry, "token": token}
        for entry in word_entries
        for token in entry["tokens"]
    ]
    spans = marker_token_spans(token_entries, marker_tokens)
    if not spans:
        return []

    rects: list[fitz.Rect] = []
    for start, end in spans:
        matched_entries = token_entries[start:end]
        if not numeric_marker_span_matches(matched_entries, marker):
            continue

        rects_by_line: dict[tuple[int, int], fitz.Rect] = {}
        for entry in matched_entries:
            key = (entry["block"], entry["line"])
            rects_by_line[key] = rects_by_line[key] | entry["rect"] if key in rects_by_line else fitz.Rect(entry["rect"])
        rects.extend(rects_by_line.values())
    return rects


def numeric_marker_span_matches(entries: list[dict[str, Any]], marker: str) -> bool:
    raw_parts = []
    seen_word_indices: set[int] = set()
    for entry in entries:
        word_index = int(entry["word_index"])
        if word_index in seen_word_indices:
            continue
        seen_word_indices.add(word_index)
        raw_parts.append(str(entry["raw"]))

    compact_raw = normalize_numeric_marker_text("".join(raw_parts))
    compact_marker = normalize_numeric_marker_text(marker)
    return "[" in compact_raw and "]" in compact_raw and compact_marker in compact_raw


def normalize_numeric_marker_text(value: str) -> str:
    return re.sub(r"\s+", "", value).replace("–", "-").replace("—", "-")


def marker_token_spans(token_entries: list[dict[str, Any]], marker_tokens: list[str]) -> list[tuple[int, int]]:
    spans = []
    for start in range(0, len(token_entries)):
        cursor = start
        matched = True
        for marker_token in marker_tokens:
            combined = ""
            while cursor < len(token_entries) and len(combined) < len(marker_token):
                next_value = combined + token_entries[cursor]["token"]
                if not marker_token.startswith(next_value):
                    if marker_token_fuzzy_matches_word_text(marker_token, combined):
                        break
                    matched = False
                    break
                combined = next_value
                cursor += 1
                if combined == marker_token:
                    break
            if not matched or not marker_token_matches_word_text(marker_token, combined):
                matched = False
                break
        if matched:
            spans.append((start, cursor))
    return spans


def marker_token_matches_word_text(marker_token: str, word_text: str) -> bool:
    return marker_token == word_text or marker_token_fuzzy_matches_word_text(marker_token, word_text)


def marker_token_fuzzy_matches_word_text(marker_token: str, word_text: str) -> bool:
    return (
        len(marker_token) >= 6
        and len(marker_token) - len(word_text) == 1
        and marker_token.startswith(word_text)
    )


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
    if matches:
        return parse_numbered_references(text, matches)

    matches = numbered_reference_matches(text)
    if not matches:
        return parse_author_year_references(text)

    return parse_numbered_references(text, matches)


def numbered_reference_matches(text: str) -> list[re.Match[str]]:
    matches = list(NUMBERED_REFERENCE_RE.finditer(text))
    if not matches:
        return []

    numbers = [int(match.group(1)) for match in matches]
    if numbers[0] > 3:
        return []
    if len(numbers) == 1:
        after_marker = text[matches[0].end() : matches[0].end() + 180]
        return matches if looks_like_author_reference_start(after_marker) else []

    consecutive_pairs = sum(1 for left, right in zip(numbers, numbers[1:]) if right == left + 1)
    return matches if consecutive_pairs >= max(1, len(numbers) // 2) else []


def parse_numbered_references(text: str, matches: list[re.Match[str]]) -> list[dict[str, Any]]:
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
    lines = merge_reference_lines([line.strip() for line in references_text.splitlines() if line.strip()])
    entries: list[list[str]] = []
    current: list[str] = []

    for line in lines:
        if current and YEAR_RE.search(" ".join(current)) and re.match(r"^\d{4}\.\s+", line):
            continue
        if looks_like_author_reference_start(line) and current and YEAR_RE.search(" ".join(current)):
            entries.append(current)
            current = [line]
        else:
            current.append(line)

    if current and YEAR_RE.search(" ".join(current)):
        entries.append(current)

    references = []
    raw_references = []
    for entry_lines in entries:
        raw_references.extend(split_author_year_reference_entry(" ".join(entry_lines)))

    for index, raw_reference in enumerate(raw_references[:MAX_REFERENCES], start=1):
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


def split_author_year_reference_entry(entry: str) -> list[str]:
    text = clean_reference(entry)
    if not text:
        return []

    starts = [0]
    for match in re.finditer(r"\.\s+(?=[A-ZÀ-ÖØ-Þ])", text):
        start = match.end()
        previous = text[starts[-1] : start]
        if YEAR_RE.search(previous) and looks_like_author_reference_start(text[start : start + 180]):
            starts.append(start)

    return [
        clean_reference(text[start : starts[index + 1] if index + 1 < len(starts) else len(text)])
        for index, start in enumerate(starts)
    ]


def merge_reference_lines(lines: list[str]) -> list[str]:
    merged: list[str] = []
    index = 0
    while index < len(lines):
        line = lines[index]
        while index + 1 < len(lines) and re.fullmatch(r"(?:(?:[A-Z]\.|[A-Z]\.-[A-Z]\.)\s*)+", line):
            index += 1
            line = f"{line} {lines[index]}"
        merged.append(line)
        index += 1
    return merged


def looks_like_author_reference_start(line: str) -> bool:
    clean = clean_reference(line)[:180]
    return bool(AUTHOR_START_RE.search(clean) or INITIAL_AUTHOR_START_RE.search(clean))


def collect_inline_contexts(body_pages: list[dict[str, Any]]) -> dict[int, list[dict[str, Any]]]:
    contexts_by_number: dict[int, list[dict[str, Any]]] = defaultdict(list)
    seen: set[tuple[int, str]] = set()

    for page in body_pages:
        page_number = int(page.get("page_number", 0))
        page_text = clean_citation_text(page.get("text", ""))
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


def collect_author_year_contexts(body_pages: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    contexts_by_key: dict[str, list[dict[str, Any]]] = defaultdict(list)
    seen: set[tuple[str, str, str]] = set()
    for page in body_pages:
        page_number = int(page.get("page_number", 0))
        page_text = clean_citation_text(page.get("text", ""))
        parenthetical_spans = []

        for parenthetical in AUTHOR_YEAR_PAREN_RE.finditer(page_text):
            parenthetical_spans.append((parenthetical.start(), parenthetical.end()))
            inner_text = parenthetical.group("body")
            inner_offset = parenthetical.start("body")
            for match in AUTHOR_YEAR_ITEM_RE.finditer(inner_text):
                add_author_year_context(
                    contexts_by_key,
                    seen,
                    page_number,
                    page_text,
                    inner_offset + match.start(),
                    inner_offset + match.end(),
                    match,
                )

        for match in AUTHOR_YEAR_NARRATIVE_RE.finditer(page_text):
            if any(start <= match.start() and match.end() <= end for start, end in parenthetical_spans):
                continue
            add_author_year_context(
                contexts_by_key,
                seen,
                page_number,
                page_text,
                match.start(),
                match.end(),
                match,
            )

    return dict(contexts_by_key)


def add_author_year_context(
    contexts_by_key: dict[str, list[dict[str, Any]]],
    seen: set[tuple[str, str, str]],
    page_number: int,
    page_text: str,
    start: int,
    end: int,
    match: re.Match[str],
) -> None:
    first_author = str(match.group("first") or "").strip()
    second_author = str(match.group("second") or "").strip()
    year = str(match.groupdict().get("year") or match.groupdict().get("year_paren") or "").strip()
    if not first_author or not year or not looks_like_inline_author(first_author):
        return

    key = author_year_key(first_author, year)
    marker = page_text[start:end].strip()
    context_sentence = context_around_match(page_text, start, end)
    seen_key = (key, marker, context_sentence)
    if seen_key in seen:
        return
    seen.add(seen_key)

    contexts = contexts_by_key[key]
    if len(contexts) >= MAX_CONTEXTS_PER_CITATION:
        return
    contexts.append(
        {
            "page_number": page_number,
            "marker": marker,
            "sentence": context_sentence[:MAX_CONTEXT_CHARS],
            "first_author": first_author,
            "second_author": second_author,
            "year": year[:4],
            "label": author_year_label(first_author, second_author, bool(match.group("etal")), year),
        }
    )


def looks_like_inline_author(value: str) -> bool:
    name = clean_citation_text(value).strip()
    if not name or name in NON_AUTHOR_WORDS:
        return False

    letters = re.sub(r"[^A-Za-zÀ-ÖØ-öø-ÿ]", "", name)
    if len(letters) >= 2 and letters.isupper():
        return False
    return bool(re.search(r"[a-zÀ-ÖØ-öø-ÿ]", letters))


def context_around_match(text: str, start: int, end: int) -> str:
    left_candidates = [text.rfind(separator, 0, start) for separator in (". ", "? ", "! ")]
    left = max(left_candidates)
    left = left + 2 if left != -1 else max(0, start - 220)

    right_candidates = [position for separator in (". ", "? ", "! ") if (position := text.find(separator, end)) != -1]
    right = min(right_candidates) + 1 if right_candidates else min(len(text), end + 480)
    return text[left:right].strip()


def author_year_key(first_author: str, year: str) -> str:
    return f"{author_key_text(first_author)}:{year[:4]}"


def reference_author_year_key(reference: dict[str, Any]) -> str:
    keys = reference_author_year_keys(reference)
    return keys[0] if keys else ""


def reference_author_year_keys(reference: dict[str, Any]) -> list[str]:
    first_author = str(reference.get("first_author", "")).strip()
    year = str(reference.get("year", "")).strip()
    if not first_author or not year:
        return []

    keys = [author_year_key(first_author, year)]
    author_parts = first_author.split()
    if len(author_parts) > 1:
        keys.append(author_year_key(author_parts[-1], year))
        if author_key_text(author_parts[0]) in {"de", "der", "van", "von"}:
            keys.append(author_year_key(" ".join(author_parts[1:]), year))

    unique_keys = []
    for key in keys:
        if key and key not in unique_keys:
            unique_keys.append(key)
    return unique_keys


def citation_has_context(citation: dict[str, Any]) -> bool:
    return bool(citation.get("contexts"))


def author_year_label(first_author: str, second_author: str, et_al: bool, year: str) -> str:
    if et_al:
        return f"{first_author} et al. {year[:4]}"
    if second_author:
        return f"{first_author} and {second_author} {year[:4]}"
    return f"{first_author} {year[:4]}"


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
    text = clean_citation_text(value)
    return re.sub(r"\s+", " ", text).strip(" .")


def clean_citation_text(value: Any) -> str:
    return normalize_text(CONTROL_RE.sub("", str(value)).replace("\xad", ""))


def strip_diacritics(value: str) -> str:
    return "".join(
        character
        for character in unicodedata.normalize("NFKD", value)
        if not unicodedata.combining(character)
    )


def author_key_text(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", strip_diacritics(clean_citation_text(value)).lower())


def extract_year(raw_reference: str) -> str:
    matches = YEAR_RE.findall(raw_reference)
    return matches[0] if matches else ""


def guess_reference_authors(raw_reference: str, year: str) -> str:
    if not year:
        return ""
    year_index = raw_reference.find(year)
    if year_index <= 0:
        return ""
    return raw_reference[:year_index].strip(" .")[:220]


def extract_first_author(raw_reference: str) -> str:
    initial_first = re.match(
        rf"^(?:(?:[A-Z]\.|[A-Z]\.-[A-Z]\.)\s*){{1,4}}(?P<last>{AUTHOR_NAME_PATTERN})\b",
        raw_reference,
    )
    if initial_first:
        return initial_first.group("last").strip()

    author_segment = extract_author_prefix(raw_reference)
    author_segment = author_segment.split(",", 1)[0]
    author_segment = re.sub(r"\s+et\s+al$", "", author_segment, flags=re.IGNORECASE)
    author_segment = re.sub(rf"\s+{AUTHOR_INITIALS_PATTERN}$", "", author_segment)
    return author_segment.strip()


def extract_second_author(raw_reference: str) -> str:
    author_prefix = extract_author_prefix(raw_reference)
    if " et al" in author_prefix:
        return ""

    initial_first = re.match(
        rf"^(?:(?:[A-Z]\.|[A-Z]\.-[A-Z]\.)\s*){{1,4}}{AUTHOR_NAME_PATTERN}\s*,\s*"
        rf"(?:(?:[A-Z]\.|[A-Z]\.-[A-Z]\.)\s*){{1,4}}(?P<last>{AUTHOR_NAME_PATTERN})\b",
        author_prefix,
    )
    if initial_first:
        return initial_first.group("last").strip()

    initial_and = re.match(
        rf"^(?:(?:[A-Z]\.|[A-Z]\.-[A-Z]\.)\s*){{1,4}}{AUTHOR_NAME_PATTERN}\s+and\s+"
        rf"(?:(?:[A-Z]\.|[A-Z]\.-[A-Z]\.)\s*){{1,4}}(?P<last>{AUTHOR_NAME_PATTERN})\b",
        author_prefix,
    )
    if initial_and:
        return initial_and.group("last").strip()

    parts = [part.strip() for part in author_prefix.split(",")]
    if len(parts) < 2:
        return ""
    second_author = re.sub(rf"\s+{AUTHOR_INITIALS_PATTERN}$", "", parts[1]).strip()
    return second_author


def extract_author_prefix(raw_reference: str) -> str:
    et_al_match = re.search(r"\bet\s+al\.", raw_reference, flags=re.IGNORECASE)
    if et_al_match and et_al_match.start() < 180:
        return raw_reference[: et_al_match.end()].strip(" .")

    boundary = author_title_boundary(raw_reference)
    if boundary != -1:
        return raw_reference[:boundary].strip(" .")
    return raw_reference[:180].strip(" .")


def strip_author_prefix(raw_reference: str) -> str:
    et_al_match = re.search(r"\bet\s+al\.\s+", raw_reference, flags=re.IGNORECASE)
    if et_al_match:
        return raw_reference[et_al_match.end() :].strip()

    boundary = author_title_boundary(raw_reference)
    if boundary != -1:
        return raw_reference[boundary + 1 :].strip()
    return raw_reference


def author_title_boundary(raw_reference: str) -> int:
    for match in re.finditer(r"\.\s+", raw_reference):
        previous_token = raw_reference[: match.start()].split()[-1].strip(",")
        if len(previous_token.replace(".", "")) > 1:
            return match.start()
    return -1


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
