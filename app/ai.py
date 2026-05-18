from __future__ import annotations

import base64
import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from .paper_processing import ExtractedPaper, ground_highlights, normalize_text, score_match

load_dotenv()

MAX_ANALYSIS_HIGHLIGHTS = 40
MAX_HIGHLIGHT_SNIPPET_CHARS = 900
ANALYSIS_VERSION = 10
DEFAULT_MODEL = "gpt-5.5"
DEFAULT_REASONING_EFFORT = "high"
REASONING_EFFORTS = {"none", "low", "medium", "high", "xhigh"}
REFERENCES_START_RE = re.compile(r"(?:^|\n)\s*(?:references|bibliography|works cited)\s*(?:\n|$)", re.IGNORECASE)

ANALYSIS_SYSTEM = """You help researchers read scientific papers quickly.
Return valid JSON only. Highlight snippets must be exact short excerpts copied from the paper text whenever possible.
Do not invent claims that are not supported by the provided paper text.
Prefer evidence-bound scientific reading: identify the task, failure mode, intervention, mechanism, evaluation, tradeoffs, limitations, and strongest claim supported by the evidence."""

CHAT_SYSTEM = """You are a careful scientific reading assistant.
Answer from the provided paper context first. If web results are provided, use them only as external context and cite URLs.
Be concise, concrete, and explicit about uncertainty.
Calibrate claims to the evidence; distinguish tested results from interpretation."""

FIGURE_SYSTEM = """You inspect scientific paper page images.
Return valid JSON only. Identify visual evidence such as figures, plots, diagrams, tables, screenshots, and multi-panel figure groups.
Do not invent results that are not visible in the image or supported by nearby page text.
Prioritize the scientific point of each visual over exhaustive visual description.
Be explicit about uncertainty when labels, axes, legends, or captions are unclear."""

SELECTION_EXPLANATION_SYSTEM = """You explain selected scientific paper terms and phrases in context.
Use the selected text and nearby page context first.
Be concise, concrete, and explicit when the context is insufficient.
Do not invent paper-specific claims that are not supported by the provided context."""


def provider_status() -> dict[str, Any]:
    has_openai_key = bool(os.getenv("OPENAI_API_KEY"))
    has_codex = bool(shutil.which("codex"))
    default_provider = os.getenv("AI_PROVIDER", "auto")
    if default_provider not in {"auto", "codex", "openai"}:
        default_provider = "auto"
    return {
        "default_provider": default_provider,
        "default_text_model": resolve_text_model(None),
        "default_vision_model": resolve_vision_model(None),
        "default_reasoning_effort": resolve_reasoning_effort(None, "OPENAI_REASONING_EFFORT", "CODEX_REASONING_EFFORT"),
        "default_vision_reasoning_effort": resolve_reasoning_effort(
            None,
            "OPENAI_VISION_REASONING_EFFORT",
            "CODEX_VISION_REASONING_EFFORT",
            "OPENAI_REASONING_EFFORT",
            "CODEX_REASONING_EFFORT",
        ),
        "reasoning_efforts": sorted(REASONING_EFFORTS, key=["none", "low", "medium", "high", "xhigh"].index),
        "openai_available": has_openai_key,
        "codex_available": has_codex,
        "providers": [
            {"id": "auto", "label": "Auto"},
            {"id": "codex", "label": "Codex subscription"},
            {"id": "openai", "label": "OpenAI API key"},
        ],
    }


def resolve_model(value: str | None, *env_names: str) -> str:
    candidates = [value, *(os.getenv(name) for name in env_names), DEFAULT_MODEL]
    for candidate in candidates:
        clean = str(candidate or "").replace('"', "").strip()
        if clean:
            return clean[:120]
    return DEFAULT_MODEL


def resolve_text_model(value: str | None) -> str:
    return resolve_model(value, "OPENAI_MODEL", "CODEX_MODEL")


def resolve_vision_model(value: str | None) -> str:
    return resolve_model(value, "OPENAI_VISION_MODEL", "CODEX_VISION_MODEL", "OPENAI_MODEL", "CODEX_MODEL")


def resolve_reasoning_effort(value: str | None, *env_names: str) -> str:
    candidates = [value, *(os.getenv(name) for name in env_names), DEFAULT_REASONING_EFFORT]
    for candidate in candidates:
        clean = str(candidate or "").strip().lower()
        if clean in REASONING_EFFORTS:
            return clean
    return DEFAULT_REASONING_EFFORT


def sanitize_prompt_text(value: str) -> str:
    return str(value).replace("\x00", " ")


def openai_api_key(api_key: str | None = None) -> str:
    return (api_key or os.getenv("OPENAI_API_KEY") or "").strip()


def choose_provider(requested: str | None, api_key: str | None = None) -> str:
    provider = (requested or os.getenv("AI_PROVIDER", "auto")).lower()
    if provider == "auto":
        if openai_api_key(api_key):
            return "openai"
        if shutil.which("codex"):
            return "codex"
        raise RuntimeError("No AI provider available. Log in to Codex CLI or set OPENAI_API_KEY.")
    if provider in {"codex", "openai"}:
        return provider
    if provider == "local":
        raise RuntimeError("The local fallback provider has been removed.")
    return provider


def build_analysis_prompt(extracted: ExtractedPaper) -> str:
    text = format_guided_reading_text(extracted)[:70000]
    return f"""
{ANALYSIS_SYSTEM}

Analyze this paper for a fast-reading interface.

Return JSON with exactly this shape:
{{
  "title": "paper title",
  "overview": "3-5 sentence plain summary",
  "background_notes": ["3-5 short beginner-friendly notes explaining early terms, acronyms, datasets, or concepts needed to read this paper"],
  "key_takeaways": ["4-7 concrete takeaways with bracketed plain-language clarification when a technical term needs it"],
  "read_this_first": ["3-5 specific paper areas or excerpts to inspect first"],
  "glossary": [{{"term": "term or acronym", "definition": "short paper-specific definition"}}],
  "highlights": [
    {{
      "label": "goal|novelty|method|result|limitation",
      "snippet": "one complete sentence copied exactly from the paper text, usually 90-260 characters",
      "reason": "why this excerpt helps fast comprehension",
      "comment": "short plain-language explanation of what this highlight means and why it matters"
    }}
  ],
  "questions": ["useful follow-up question"]
}}

Highlight requirements:
- Background notes should define or contextualize important terms that appear early in the paper. Keep them short, practical, and specific to this paper.
- Key takeaways should be understandable to a researcher outside this exact subfield. Keep the paper-specific claim, but add a short bracketed explanation when needed, e.g. [plain-language meaning]. Avoid assuming the reader already knows the benchmark, assay, model family, or domain acronym.
- Return enough highlights for a reader to follow the paper's argument without reading every section; do not optimize for the absolute minimum.
- Add a highlight only if it changes the reader's understanding of the task, novelty, method, evidence, or claim limitation.
- Abstract highlights are allowed when they provide useful orientation, especially for goal, novelty, and main result.
- Do not stop after abstract-level summary. Include concrete body passages for the contribution, mechanism, evaluation, and limits when they exist.
- If an abstract sentence is the clearest compact statement of the paper's contribution or result, include it; otherwise prefer the more specific body sentence.
- Do not highlight title, author, affiliation, contact, availability, license, preprint, or header/footer text.
- Do not cluster the set in the opening motivation; later method, evaluation, result, and this-paper limitation passages are usually more useful.
- Use the goal label for the task, problem statement, or motivating failure mode that this paper addresses.
- Use the novelty label for contribution claims: new systems, datasets, benchmarks, architectures, workflows, evaluation framing, or claimed differences from prior work.
- Use the method label for this paper's data construction, model, system, protocol, evaluation design, or analysis procedure.
- Use the result label for this paper's findings, measured evidence, comparisons, rankings, or empirical interpretations.
- Use the limitation label only for limitations of this paper's own data, method, evaluation, assumptions, claims, or generalizability. Do not label weaknesses of prior work or background motivation as limitation; label those as goal when they define the problem.
- Prefer a balanced guided skim across goal, novelty, method, result, and limitation when those facets are present, but do not force equal counts or invent missing facets.
- Stop when the next highlight repeats an idea already covered.
- Highlights must be complete sentence-level excerpts. Most useful highlights are single sentences; use a compact multi-sentence excerpt only when the claim needs immediate context.
- Avoid adjacent highlights unless they serve different labels.
- Spread highlights across introduction, methods/system, evaluation/results, and limitations/discussion when those sections exist.
- Prefer passages that define the task, name the paper's motivating failure mode, introduce this paper's intervention, explain the mechanism, define the evaluation/baseline/metric, report the main result, state a tradeoff, or bound this paper's claim.
- Avoid generic field-motivation sentences unless they create a concrete methodological decision.
- Read-this-first items should help a researcher triage the paper: task, method, evidence, limitations, and claim ceiling.
- Snippets must be exact complete sentences copied from the paper text where possible. Do not include page markers such as [Page 2]. Never end a snippet mid-word or mid-sentence.
- Each highlight comment should explain the highlighted idea in simpler terms, adding just enough definition or background context for a reader who knows the field lightly. Do not repeat the snippet.

Paper title guess: {extracted.title}

Paper text:
{text}
""".strip()


def format_analysis_text(extracted: ExtractedPaper) -> str:
    if not extracted.pages:
        return sanitize_prompt_text(extracted.full_text)

    parts = []
    for page in extracted.pages:
        page_number = int(page.get("page_number", len(parts) + 1))
        text = sanitize_prompt_text(str(page.get("text", ""))).strip()
        if text:
            parts.append(f"[Page {page_number}]\n{text}")
    return "\n\n".join(parts)


def format_guided_reading_text(extracted: ExtractedPaper) -> str:
    if not extracted.pages:
        return sanitize_prompt_text(extracted.full_text)

    parts = []
    for page in extracted.pages:
        page_number = int(page.get("page_number", len(parts) + 1))
        text = sanitize_prompt_text(str(page.get("text", ""))).strip()
        text, found_references = without_reference_section(text)
        text = normalize_text(text)
        if text:
            parts.append(f"[Page {page_number}]\n{text}")
        if found_references:
            break

    return "\n\n".join(parts) or format_analysis_text(extracted)


def without_reference_section(text: str) -> tuple[str, bool]:
    match = REFERENCES_START_RE.search(text)
    if not match:
        return text, False
    return text[: match.start()], True


def parse_json_payload(text: str) -> dict[str, Any]:
    cleaned = text.strip()
    fenced = re.search(r"```(?:json)?\s*(.*?)```", cleaned, re.DOTALL)
    if fenced:
        cleaned = fenced.group(1).strip()

    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError("AI response did not contain a JSON object.")

    return json.loads(cleaned[start : end + 1], strict=False)


def run_openai(
    prompt: str,
    system_prompt: str,
    expect_json: bool,
    api_key: str | None = None,
    model: str | None = None,
    reasoning_effort: str | None = None,
) -> str:
    from openai import OpenAI

    client = OpenAI(api_key=openai_api_key(api_key))
    response = client.responses.create(
        model=resolve_text_model(model),
        input=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt},
        ],
        reasoning={"effort": resolve_reasoning_effort(reasoning_effort, "OPENAI_REASONING_EFFORT")},
        temperature=0.2,
    )
    return response.output_text


def run_openai_vision(
    prompt: str,
    image_path: Path,
    api_key: str | None = None,
    model: str | None = None,
    reasoning_effort: str | None = None,
) -> str:
    from openai import OpenAI

    client = OpenAI(api_key=openai_api_key(api_key))
    image_data = base64.b64encode(image_path.read_bytes()).decode("ascii")
    response = client.responses.create(
        model=resolve_vision_model(model),
        input=[
            {"role": "system", "content": FIGURE_SYSTEM},
            {
                "role": "user",
                "content": [
                    {"type": "input_text", "text": prompt},
                    {"type": "input_image", "image_url": f"data:image/jpeg;base64,{image_data}"},
                ],
            },
        ],
        reasoning={"effort": resolve_reasoning_effort(reasoning_effort, "OPENAI_VISION_REASONING_EFFORT", "OPENAI_REASONING_EFFORT")},
        temperature=0.1,
    )
    return response.output_text


def run_codex_vision(
    prompt: str,
    image_path: Path,
    model: str | None = None,
    reasoning_effort: str | None = None,
) -> str:
    image_prompt = f"""
{FIGURE_SYSTEM}

{prompt}

The page image is this local JPEG file:
{image_path.resolve()}

Inspect that image directly and return only the requested JSON object.
""".strip()
    timeout = int(os.getenv("CODEX_FIGURE_TIMEOUT_SECONDS", os.getenv("CODEX_TIMEOUT_SECONDS", "180")))
    return run_codex(image_prompt, timeout, resolve_vision_model(model), reasoning_effort)


def run_codex(
    prompt: str,
    timeout_seconds: int | None = None,
    model: str | None = None,
    reasoning_effort: str | None = None,
) -> str:
    codex_path = shutil.which("codex")
    if not codex_path:
        raise RuntimeError("Codex CLI is not installed or not on PATH.")

    prompt = sanitize_prompt_text(prompt)
    timeout = timeout_seconds or int(os.getenv("CODEX_TIMEOUT_SECONDS", "180"))
    with tempfile.TemporaryDirectory() as tmp_dir:
        output_path = Path(tmp_dir) / "last-message.txt"
        args = [
            codex_path,
            "--ask-for-approval",
            "never",
            "--sandbox",
            "read-only",
            "exec",
            "--skip-git-repo-check",
            "--ephemeral",
            "--color",
            "never",
            "-c",
            f"model_reasoning_effort={json.dumps(resolve_reasoning_effort(reasoning_effort, 'CODEX_REASONING_EFFORT', 'OPENAI_REASONING_EFFORT'))}",
            "-o",
            str(output_path),
            prompt,
        ]
        selected_model = resolve_text_model(model)
        if selected_model:
            args[5:5] = ["-m", selected_model]

        result = subprocess.run(
            args,
            cwd=Path(__file__).resolve().parent.parent,
            capture_output=True,
            text=True,
            stdin=subprocess.DEVNULL,
            timeout=timeout,
        )
        if output_path.exists():
            output = output_path.read_text(encoding="utf-8").strip()
            if output:
                return output
        if result.returncode != 0:
            raise RuntimeError((result.stderr or result.stdout or "Codex failed.").strip())
        return result.stdout.strip()


def run_ai(
    prompt: str,
    system_prompt: str,
    provider: str,
    expect_json: bool,
    api_key: str | None = None,
    model: str | None = None,
    reasoning_effort: str | None = None,
) -> tuple[str, str]:
    selected = choose_provider(provider, api_key)
    if selected == "openai":
        if not openai_api_key(api_key):
            raise RuntimeError("OPENAI_API_KEY is not set.")
        return run_openai(prompt, system_prompt, expect_json, api_key, model, reasoning_effort), "openai"
    if selected == "codex":
        return run_codex(f"{system_prompt}\n\n{prompt}", model=model, reasoning_effort=reasoning_effort), "codex"
    raise RuntimeError(f"Unknown AI provider: {provider}")


def choose_vision_provider(requested: str | None, api_key: str | None = None) -> str:
    provider = (requested or os.getenv("FIGURE_AI_PROVIDER", "auto")).lower()
    if provider == "auto":
        if shutil.which("codex"):
            return "codex"
        if openai_api_key(api_key):
            return "openai"
        raise RuntimeError("No vision provider available. Log in to Codex CLI or set OPENAI_API_KEY.")
    if provider == "codex":
        if not shutil.which("codex"):
            raise RuntimeError("Codex CLI is not installed or not on PATH.")
        return "codex"
    if provider == "openai":
        if not openai_api_key(api_key):
            raise RuntimeError("OPENAI_API_KEY is not set.")
        return "openai"
    if provider == "local":
        raise RuntimeError("The local fallback provider has been removed.")
    raise RuntimeError(f"Unknown AI provider: {provider}")


def normalize_highlight_snippet(value: str) -> str:
    snippet = normalize_text(str(value))
    if len(snippet) <= MAX_HIGHLIGHT_SNIPPET_CHARS:
        return snippet

    window = snippet[: MAX_HIGHLIGHT_SNIPPET_CHARS + 1]
    sentence_ends = [window.rfind(marker) for marker in (".", "?", "!")]
    sentence_end = max(sentence_ends)
    if sentence_end >= 40:
        return window[: sentence_end + 1].strip()

    return window.rsplit(" ", 1)[0].rstrip(",;:") or window.strip()


def normalize_analysis(payload: dict[str, Any], extracted: ExtractedPaper) -> dict[str, Any]:
    def list_of_strings(key: str, limit: int) -> list[str]:
        values = payload.get(key, [])
        if not isinstance(values, list):
            return []
        return [normalize_text(str(value)) for value in values[:limit] if normalize_text(str(value))]

    glossary = payload.get("glossary", [])
    if not isinstance(glossary, list):
        glossary = []

    highlights = payload.get("highlights", [])
    if not isinstance(highlights, list):
        highlights = []

    normalized_highlights = [
        {
            "label": str(item.get("label", "important")),
            "snippet": normalize_highlight_snippet(str(item.get("snippet", ""))),
            "reason": normalize_text(str(item.get("reason", "")))[:500],
            "comment": normalize_text(str(item.get("comment", "")))[:700],
        }
        for item in highlights[:MAX_ANALYSIS_HIGHLIGHTS]
        if isinstance(item, dict) and item.get("snippet")
    ]

    return {
        "title": normalize_text(str(payload.get("title") or extracted.title))[:220],
        "overview": normalize_text(str(payload.get("overview") or "")),
        "background_notes": list_of_strings("background_notes", 6),
        "key_takeaways": list_of_strings("key_takeaways", 8),
        "read_this_first": list_of_strings("read_this_first", 6),
        "glossary": [
            {
                "term": normalize_text(str(item.get("term", "")))[:120],
                "definition": normalize_text(str(item.get("definition", "")))[:500],
            }
            for item in glossary[:10]
            if isinstance(item, dict) and item.get("term") and item.get("definition")
        ],
        "highlights": normalized_highlights,
        "questions": list_of_strings("questions", 8),
    }


def analyze_paper(
    pdf_path: Path,
    extracted: ExtractedPaper,
    provider: str | None,
    api_key: str | None = None,
    model: str | None = None,
    reasoning_effort: str | None = None,
) -> dict[str, Any]:
    selected_provider = choose_provider(provider, api_key)
    output, provider_used = run_ai(
        build_analysis_prompt(extracted),
        ANALYSIS_SYSTEM,
        selected_provider,
        True,
        api_key,
        model,
        reasoning_effort,
    )
    analysis = normalize_analysis(parse_json_payload(output), extracted)

    analysis["highlights"] = ground_highlights(pdf_path, analysis.get("highlights", []), extracted.sentence_spans)
    analysis["provider_used"] = provider_used
    analysis["warnings"] = analysis.get("warnings", [])
    return analysis


def build_figure_prompt(page_number: int, page_text: str) -> str:
    return f"""
Inspect page {page_number} of this scientific paper.

Nearby extracted page text:
{page_text[:5000]}

Return JSON with exactly this shape:
{{
  "figures": [
    {{
      "type": "figure|table|plot|diagram|screenshot|equation|other",
      "label": "visible label such as Figure 2 or Table 1, or short fallback label",
      "title": "short descriptive title",
      "bbox_pct": [x0, y0, x1, y1],
      "caption": "visible caption or nearby caption text",
      "explanation": "plain explanation of the main scientific point, not a full inventory of visible details",
      "why_it_matters": "how this visual supports, limits, or clarifies the paper's argument or evidence",
      "uncertainty": "what may be ambiguous or hard to read"
    }}
  ]
}}

Bounding boxes must be percentages from 0 to 100 relative to the page image: left, top, right, bottom.
Group multi-panel figures as one figure unless the panels make separate claims.
Ignore ordinary body-text paragraphs, headers, footers, page numbers, and reference-list entries.
Include tables if they carry experimental results or comparisons.
Do not spend space on incidental layout, colors, icons, or decorative details unless they change the scientific interpretation.
Use the caption and nearby page text to explain what claim the visual is evidence for. Refine smaller details only when they are essential to that claim.
""".strip()


def analyze_page_figures(
    page_number: int,
    page_text: str,
    image_path: Path,
    provider: str | None,
    api_key: str | None = None,
    model: str | None = None,
    reasoning_effort: str | None = None,
) -> dict[str, Any]:
    selected_provider = choose_vision_provider(provider, api_key)
    prompt = build_figure_prompt(page_number, page_text)
    if selected_provider == "openai":
        output = run_openai_vision(prompt, image_path, api_key, model, reasoning_effort)
    elif selected_provider == "codex":
        output = run_codex_vision(prompt, image_path, model, reasoning_effort)
    else:
        raise RuntimeError(f"Unknown vision provider: {provider}")
    payload = parse_json_payload(output)
    payload["provider_used"] = selected_provider
    return payload


def select_relevant_excerpts(
    question: str,
    sentence_spans: list[dict[str, Any]],
    max_excerpts: int = 12,
) -> list[dict[str, Any]]:
    scored: list[tuple[float, dict[str, Any]]] = []
    for span in sentence_spans:
        text = str(span.get("text", ""))
        score = score_match(question, text)
        if any(word in question.lower() for word in ["summarize", "overview", "main", "takeaway"]):
            score += 0.1 if int(span.get("page_number", 999)) <= 2 else 0
        if score > 0:
            scored.append((score, span))

    if not scored:
        return sentence_spans[:max_excerpts]

    return [span for _, span in sorted(scored, key=lambda item: item[0], reverse=True)[:max_excerpts]]


def build_chat_prompt(
    paper: dict[str, Any],
    messages: list[dict[str, str]],
    excerpts: list[dict[str, Any]],
    web_results: list[dict[str, str]],
    citation_context: dict[str, Any] | None = None,
    figure_context: list[dict[str, Any]] | None = None,
) -> str:
    history = "\n".join(f"{item['role']}: {item['content']}" for item in messages[-8:])
    excerpt_text = "\n".join(
        f"- p. {item.get('page_number')}: {normalize_text(str(item.get('text', '')))[:700]}" for item in excerpts
    )
    web_text = "\n".join(
        f"- {item['title']} ({item['url']}): {item.get('snippet', '')}" for item in web_results
    )
    citation_text = format_citation_context(citation_context)
    figure_text = format_figure_context(figure_context)
    return f"""
Paper: {paper.get("title", "Untitled")}

Overview:
{paper.get("overview", "")}

Key takeaways:
{chr(10).join("- " + item for item in paper.get("key_takeaways", [])[:8])}

Relevant paper excerpts:
{excerpt_text}

Citation focus:
{citation_text}

Figure focus:
{figure_text}

Web results:
{web_text or "None"}

Conversation:
{history}

Answer the last user message. Use page numbers for paper evidence, and include URLs when using web results.
When useful, structure the answer around task, failure mode, intervention, evidence, tradeoff, and claim ceiling.
""".strip()


def format_citation_context(citation_context: dict[str, Any] | None) -> str:
    if not citation_context:
        return "None"

    contexts = citation_context.get("contexts", [])
    context_lines = []
    for item in contexts[:8]:
        page_number = item.get("page_number") or "?"
        sentence = normalize_text(str(item.get("sentence", "")))
        if sentence:
            context_lines.append(f"- p. {page_number}: {sentence[:700]}")

    return f"""
Label: {citation_context.get("label", "")}
Title: {normalize_text(str(citation_context.get("title", "")))[:300]}
Authors: {normalize_text(str(citation_context.get("authors", "")))[:300]}
Year: {citation_context.get("year", "")}
Reference: {normalize_text(str(citation_context.get("raw_reference", "")))[:1400] or "Reference text not extracted."}
Inline citation contexts:
{chr(10).join(context_lines) if context_lines else "No inline citation context extracted."}
""".strip()


def format_figure_context(figure_context: list[dict[str, Any]] | None) -> str:
    if not figure_context:
        return "None"

    lines = []
    for index, figure in enumerate(figure_context[:6], start=1):
        page_number = figure.get("page_number") or "?"
        title = normalize_text(str(figure.get("title") or figure.get("label") or "Visual"))[:300]
        figure_type = normalize_text(str(figure.get("type", "")))[:80]
        caption = normalize_text(str(figure.get("caption", "")))[:700]
        explanation = normalize_text(str(figure.get("explanation", "")))[:900]
        why_it_matters = normalize_text(str(figure.get("why_it_matters", "")))[:700]
        uncertainty = normalize_text(str(figure.get("uncertainty", "")))[:400]

        parts = [f"Figure {index}: {title}", f"Page: {page_number}"]
        if figure_type:
            parts.append(f"Type: {figure_type}")
        if caption:
            parts.append(f"Caption: {caption}")
        if explanation:
            parts.append(f"Explanation: {explanation}")
        if why_it_matters:
            parts.append(f"Why it matters: {why_it_matters}")
        if uncertainty:
            parts.append(f"Uncertainty: {uncertainty}")
        lines.append("\n".join(parts))

    return "\n\n".join(lines)


def build_selection_explanation_prompt(
    paper: dict[str, Any],
    selected_text: str,
    page_number: int | None,
    page_text: str,
) -> str:
    page_label = f"p. {page_number}" if page_number else "unknown page"
    return f"""
Paper: {paper.get("title", "Untitled")}

Paper overview:
{paper.get("overview", "")}

Selected text ({page_label}):
{normalize_text(selected_text)[:700]}

Nearby page context:
{normalize_text(page_text)[:5000]}

Explain the selected text for a reader of this paper.
- If it is a term, acronym, method name, metric, or phrase, define it in paper context.
- If it is a claim or sentence fragment, explain what it means and why it matters.
- Keep the answer short enough for a chat panel.
- Mention uncertainty if the provided context does not define the selection.
""".strip()


def answer_selection_explanation(
    paper: dict[str, Any],
    selected_text: str,
    page_number: int | None,
    page_text: str,
    provider: str | None,
    api_key: str | None = None,
    model: str | None = None,
    reasoning_effort: str | None = None,
) -> dict[str, Any]:
    selected_provider = choose_provider(provider, api_key)
    prompt = build_selection_explanation_prompt(paper, selected_text, page_number, page_text)
    answer, provider_used = run_ai(prompt, SELECTION_EXPLANATION_SYSTEM, selected_provider, False, api_key, model, reasoning_effort)

    return {
        "answer": answer.strip(),
        "provider_used": provider_used,
        "warnings": [],
    }


def answer_chat(
    paper: dict[str, Any],
    messages: list[dict[str, str]],
    web_results: list[dict[str, str]],
    provider: str | None,
    citation_context: dict[str, Any] | None = None,
    api_key: str | None = None,
    figure_context: list[dict[str, Any]] | None = None,
    model: str | None = None,
    reasoning_effort: str | None = None,
) -> dict[str, Any]:
    last_question = next((item["content"] for item in reversed(messages) if item.get("role") == "user"), "")
    excerpts = select_relevant_excerpts(last_question, paper.get("sentences", []))
    selected_provider = choose_provider(provider, api_key)

    prompt = build_chat_prompt(paper, messages, excerpts, web_results, citation_context, figure_context)
    answer, provider_used = run_ai(prompt, CHAT_SYSTEM, selected_provider, False, api_key, model, reasoning_effort)

    return {
        "answer": answer.strip(),
        "provider_used": provider_used,
        "web_results": web_results,
        "warnings": [],
    }
