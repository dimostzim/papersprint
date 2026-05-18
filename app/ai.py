from __future__ import annotations

import base64
import json
import os
import re
import shutil
import subprocess
import tempfile
from functools import lru_cache
from pathlib import Path
from typing import Any

import requests
from dotenv import load_dotenv

from .paper_processing import ExtractedPaper, ground_highlights, normalize_text, score_match

load_dotenv()

MAX_ANALYSIS_HIGHLIGHTS = 40
MAX_HIGHLIGHT_SNIPPET_CHARS = 900
ANALYSIS_VERSION = 13
DEFAULT_MODEL = "gpt-5.5"
DEFAULT_REASONING_EFFORT = "high"
REASONING_EFFORTS = {"none", "low", "medium", "high", "xhigh"}
CODEX_MODEL_OPTIONS = [
    "gpt-5.5",
    "gpt-5.4",
    "gpt-5.4-mini",
    "gpt-5.3-codex",
    "gpt-5.3-codex-spark",
    "gpt-5.2",
]
OPENAI_MODEL_OPTIONS = [
    "gpt-5.5",
    "gpt-5.4",
    "gpt-5.4-mini",
    "gpt-5.3-codex",
    "gpt-5.2",
    "gpt-5.2-pro",
    "gpt-5.1",
    "gpt-5-mini",
    "gpt-4.1",
    "gpt-4.1-mini",
    "o3",
    "o4-mini",
]
OPENROUTER_MODEL_OPTIONS = [
    "openai/gpt-5.5",
    "openai/gpt-5.4",
    "openai/gpt-5.4-mini",
    "openai/gpt-5.2",
    "anthropic/claude-sonnet-4.5",
    "google/gemini-3-pro",
]
MODEL_OPTIONS = list(dict.fromkeys([*CODEX_MODEL_OPTIONS, *OPENAI_MODEL_OPTIONS, *OPENROUTER_MODEL_OPTIONS]))
REFERENCES_START_RE = re.compile(r"(?:^|\n)\s*(?:references|bibliography|works cited)\s*(?:\n|$)", re.IGNORECASE)
PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
MODEL_EXCLUDE_TERMS = (
    "audio",
    "dall-e",
    "embedding",
    "image",
    "moderation",
    "realtime",
    "search",
    "sora",
    "transcribe",
    "tts",
    "whisper",
)


@lru_cache(maxsize=None)
def load_prompt(name: str) -> str:
    return (PROMPTS_DIR / name).read_text(encoding="utf-8").strip()


def render_prompt(name: str, **values: Any) -> str:
    prompt = load_prompt(name)
    for key, value in values.items():
        prompt = prompt.replace(f"{{{{{key}}}}}", str(value))
    return prompt.strip()


ANALYSIS_SYSTEM = load_prompt("analysis_system.md")
CHAT_SYSTEM = load_prompt("chat_system.md")
FIGURE_SYSTEM = load_prompt("figure_system.md")
SELECTION_EXPLANATION_SYSTEM = load_prompt("selection_explanation_system.md")


def provider_status() -> dict[str, Any]:
    has_openai_key = bool(os.getenv("OPENAI_API_KEY"))
    has_openrouter_key = bool(os.getenv("OPENROUTER_API_KEY"))
    has_codex = bool(shutil.which("codex"))
    default_provider = os.getenv("AI_PROVIDER", "codex")
    if default_provider not in {"auto", "codex", "openai", "openrouter"}:
        default_provider = "codex"
    codex_model_options = list_codex_models() if has_codex else CODEX_MODEL_OPTIONS
    model_options = list(dict.fromkeys([*codex_model_options, *OPENAI_MODEL_OPTIONS, *OPENROUTER_MODEL_OPTIONS]))
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
        "model_options": model_options,
        "provider_model_options": {
            "auto": model_options,
            "codex": codex_model_options,
            "openai": OPENAI_MODEL_OPTIONS,
            "openrouter": OPENROUTER_MODEL_OPTIONS,
        },
        "openai_available": has_openai_key,
        "openrouter_available": has_openrouter_key,
        "codex_available": has_codex,
        "providers": [
            {"id": "codex", "label": "Codex subscription"},
            {"id": "openai", "label": "OpenAI API key"},
            {"id": "openrouter", "label": "OpenRouter API key"},
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
    return resolve_model(value, "OPENAI_MODEL", "OPENROUTER_MODEL", "CODEX_MODEL")


def resolve_vision_model(value: str | None) -> str:
    return resolve_model(
        value,
        "OPENAI_VISION_MODEL",
        "OPENROUTER_VISION_MODEL",
        "CODEX_VISION_MODEL",
        "OPENAI_MODEL",
        "OPENROUTER_MODEL",
        "CODEX_MODEL",
    )


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


def openrouter_api_key(api_key: str | None = None) -> str:
    return (api_key or os.getenv("OPENROUTER_API_KEY") or "").strip()


def model_id_is_usable(model_id: str) -> bool:
    normalized = model_id.lower()
    if any(term in normalized for term in MODEL_EXCLUDE_TERMS):
        return False
    return normalized.startswith(("gpt-", "o", "chatgpt-", "computer-use", "openai/", "anthropic/", "google/", "x-ai/", "meta-llama/"))


def sort_model_ids(model_ids: list[str]) -> list[str]:
    preferred = [
        "gpt-5.5",
        "openai/gpt-5.5",
        "gpt-5.4",
        "openai/gpt-5.4",
        "gpt-5.4-mini",
        "openai/gpt-5.4-mini",
        "gpt-5.3-codex",
        "gpt-5.3-codex-spark",
        "gpt-5.2",
        "openai/gpt-5.2",
    ]
    preferred_rank = {model: index for index, model in enumerate(preferred)}
    return sorted(dict.fromkeys(model_ids), key=lambda model: (preferred_rank.get(model, len(preferred)), model))


@lru_cache(maxsize=1)
def list_codex_models() -> list[str]:
    codex_path = shutil.which("codex")
    if not codex_path:
        return CODEX_MODEL_OPTIONS

    try:
        result = subprocess.run(
            [codex_path, "debug", "models"],
            capture_output=True,
            text=True,
            timeout=10,
            check=True,
        )
        payload = json.loads(result.stdout)
    except Exception:
        return CODEX_MODEL_OPTIONS

    model_ids = []
    for item in payload.get("models", []):
        if not isinstance(item, dict) or item.get("visibility") != "list":
            continue
        model_id = str(item.get("slug", "")).strip()
        if model_id:
            model_ids.append(model_id)
    return sort_model_ids(model_ids) or CODEX_MODEL_OPTIONS


def list_openai_models(api_key: str | None = None) -> list[str]:
    key = openai_api_key(api_key)
    if not key:
        return OPENAI_MODEL_OPTIONS

    from openai import OpenAI

    client = OpenAI(api_key=key)
    models = client.models.list()
    model_ids = [
        model.id
        for model in models.data
        if model_id_is_usable(str(model.id))
    ]
    return sort_model_ids(model_ids) or OPENAI_MODEL_OPTIONS


def list_openrouter_models(api_key: str | None = None) -> list[str]:
    headers = {"Accept": "application/json"}
    key = openrouter_api_key(api_key)
    if key:
        headers["Authorization"] = f"Bearer {key}"

    response = requests.get(f"{OPENROUTER_BASE_URL}/models", headers=headers, timeout=10)
    response.raise_for_status()
    payload = response.json()
    model_ids = []
    for item in payload.get("data", []):
        model_id = str(item.get("id", "")).strip()
        architecture = item.get("architecture") if isinstance(item, dict) else {}
        input_modalities = architecture.get("input_modalities", []) if isinstance(architecture, dict) else []
        output_modalities = architecture.get("output_modalities", []) if isinstance(architecture, dict) else []
        supports_text = not input_modalities or "text" in input_modalities
        outputs_text = not output_modalities or "text" in output_modalities
        if model_id and supports_text and outputs_text:
            model_ids.append(model_id)
    return sort_model_ids(model_ids) or OPENROUTER_MODEL_OPTIONS


def provider_model_options(provider: str | None, api_key: str | None = None) -> list[str]:
    selected = (provider or "auto").lower()
    try:
        if selected == "openai":
            return list_openai_models(api_key)
        if selected == "openrouter":
            return list_openrouter_models(api_key)
    except Exception:
        pass
    if selected == "codex":
        return list_codex_models()
    if selected == "openai":
        return OPENAI_MODEL_OPTIONS
    if selected == "openrouter":
        return OPENROUTER_MODEL_OPTIONS
    return MODEL_OPTIONS


def choose_provider(requested: str | None, api_key: str | None = None) -> str:
    provider = (requested or os.getenv("AI_PROVIDER", "auto")).lower()
    if provider == "auto":
        if str(api_key or "").strip().startswith("sk-or-"):
            return "openrouter"
        if openai_api_key(api_key):
            return "openai"
        if openrouter_api_key():
            return "openrouter"
        if shutil.which("codex"):
            return "codex"
        raise RuntimeError("No AI provider available. Log in to Codex CLI or set OPENAI_API_KEY or OPENROUTER_API_KEY.")
    if provider in {"codex", "openai", "openrouter"}:
        return provider
    if provider == "local":
        raise RuntimeError("The local fallback provider has been removed.")
    return provider


def build_analysis_prompt(extracted: ExtractedPaper) -> str:
    text = format_guided_reading_text(extracted)[:70000]
    return render_prompt("analysis_user.md", title=extracted.title, text=text)


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


def openrouter_headers(api_key: str | None = None) -> dict[str, str]:
    key = openrouter_api_key(api_key)
    if not key:
        raise RuntimeError("OPENROUTER_API_KEY is not set.")
    return {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "http://127.0.0.1:8788",
        "X-Title": "PaperSprint",
    }


def openrouter_response_text(payload: dict[str, Any]) -> str:
    choices = payload.get("choices") if isinstance(payload, dict) else None
    if not choices:
        raise RuntimeError("OpenRouter response did not contain a completion.")
    message = choices[0].get("message", {}) if isinstance(choices[0], dict) else {}
    content = message.get("content", "")
    if isinstance(content, list):
        return "\n".join(str(item.get("text", "")) for item in content if isinstance(item, dict)).strip()
    return str(content).strip()


def openrouter_reasoning(reasoning_effort: str | None) -> dict[str, str] | None:
    effort = resolve_reasoning_effort(reasoning_effort, "OPENROUTER_REASONING_EFFORT", "OPENAI_REASONING_EFFORT")
    if effort == "none":
        return None
    return {"effort": effort}


def run_openrouter(
    prompt: str,
    system_prompt: str,
    expect_json: bool,
    api_key: str | None = None,
    model: str | None = None,
    reasoning_effort: str | None = None,
) -> str:
    body: dict[str, Any] = {
        "model": model or os.getenv("OPENROUTER_MODEL") or "openai/gpt-5.5",
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.2,
    }
    reasoning = openrouter_reasoning(reasoning_effort)
    if reasoning:
        body["reasoning"] = reasoning
    if expect_json:
        body["response_format"] = {"type": "json_object"}

    response = requests.post(
        f"{OPENROUTER_BASE_URL}/chat/completions",
        headers=openrouter_headers(api_key),
        json=body,
        timeout=int(os.getenv("OPENROUTER_TIMEOUT_SECONDS", "180")),
    )
    response.raise_for_status()
    return openrouter_response_text(response.json())


def run_openrouter_vision(
    prompt: str,
    image_path: Path,
    api_key: str | None = None,
    model: str | None = None,
    reasoning_effort: str | None = None,
) -> str:
    image_data = base64.b64encode(image_path.read_bytes()).decode("ascii")
    body: dict[str, Any] = {
        "model": model or os.getenv("OPENROUTER_VISION_MODEL") or os.getenv("OPENROUTER_MODEL") or "openai/gpt-5.5",
        "messages": [
            {"role": "system", "content": FIGURE_SYSTEM},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_data}"}},
                ],
            },
        ],
        "temperature": 0.1,
        "response_format": {"type": "json_object"},
    }
    reasoning = openrouter_reasoning(reasoning_effort)
    if reasoning:
        body["reasoning"] = reasoning

    response = requests.post(
        f"{OPENROUTER_BASE_URL}/chat/completions",
        headers=openrouter_headers(api_key),
        json=body,
        timeout=int(os.getenv("OPENROUTER_FIGURE_TIMEOUT_SECONDS", os.getenv("OPENROUTER_TIMEOUT_SECONDS", "180"))),
    )
    response.raise_for_status()
    return openrouter_response_text(response.json())


def run_codex_vision(
    prompt: str,
    image_path: Path,
    model: str | None = None,
    reasoning_effort: str | None = None,
) -> str:
    image_prompt = render_prompt(
        "codex_vision_user.md",
        figure_system=FIGURE_SYSTEM,
        prompt=prompt,
        image_path=image_path.resolve(),
    )
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
    selected_model = resolve_text_model(model)
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
        if selected_model:
            args[5:5] = ["-m", selected_model]

        try:
            result = subprocess.run(
                args,
                cwd=Path(__file__).resolve().parent.parent,
                capture_output=True,
                text=True,
                stdin=subprocess.DEVNULL,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired as error:
            raise RuntimeError(
                f"Codex timed out after {timeout} seconds with model {selected_model}. "
                "Try lower reasoning effort or set CODEX_ANALYSIS_TIMEOUT_SECONDS higher."
            ) from error
        if output_path.exists():
            output = output_path.read_text(encoding="utf-8").strip()
            if output:
                return output
        if result.returncode != 0:
            message = (result.stderr or result.stdout or "Codex failed.").strip()
            raise RuntimeError(message[:1200])
        return result.stdout.strip()


def run_ai(
    prompt: str,
    system_prompt: str,
    provider: str,
    expect_json: bool,
    api_key: str | None = None,
    model: str | None = None,
    reasoning_effort: str | None = None,
    timeout_seconds: int | None = None,
) -> tuple[str, str]:
    selected = choose_provider(provider, api_key)
    if selected == "openai":
        if not openai_api_key(api_key):
            raise RuntimeError("OPENAI_API_KEY is not set.")
        return run_openai(prompt, system_prompt, expect_json, api_key, model, reasoning_effort), "openai"
    if selected == "openrouter":
        if not openrouter_api_key(api_key):
            raise RuntimeError("OPENROUTER_API_KEY is not set.")
        return run_openrouter(prompt, system_prompt, expect_json, api_key, model, reasoning_effort), "openrouter"
    if selected == "codex":
        return run_codex(
            f"{system_prompt}\n\n{prompt}",
            timeout_seconds=timeout_seconds,
            model=model,
            reasoning_effort=reasoning_effort,
        ), "codex"
    raise RuntimeError(f"Unknown AI provider: {provider}")


def choose_vision_provider(requested: str | None, api_key: str | None = None) -> str:
    provider = (requested or os.getenv("FIGURE_AI_PROVIDER", "auto")).lower()
    if provider == "auto":
        if shutil.which("codex"):
            return "codex"
        if openai_api_key(api_key):
            return "openai"
        if openrouter_api_key():
            return "openrouter"
        raise RuntimeError("No vision provider available. Log in to Codex CLI or set OPENAI_API_KEY or OPENROUTER_API_KEY.")
    if provider == "codex":
        if not shutil.which("codex"):
            raise RuntimeError("Codex CLI is not installed or not on PATH.")
        return "codex"
    if provider == "openai":
        if not openai_api_key(api_key):
            raise RuntimeError("OPENAI_API_KEY is not set.")
        return "openai"
    if provider == "openrouter":
        if not openrouter_api_key(api_key):
            raise RuntimeError("OPENROUTER_API_KEY is not set.")
        return "openrouter"
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


def normalize_reference_id(value: Any, fallback: str) -> str:
    text = re.sub(r"[^A-Za-z0-9_-]+", "-", str(value or "").strip()).strip("-").lower()
    return (text[:48] or fallback).strip("-") or fallback


def normalize_analysis(payload: dict[str, Any], extracted: ExtractedPaper) -> dict[str, Any]:
    def list_of_strings(key: str, limit: int) -> list[str]:
        values = payload.get(key, [])
        if not isinstance(values, list):
            return []
        return [normalize_text(str(value)) for value in values[:limit] if normalize_text(str(value))]

    def list_of_summary_items(key: str, limit: int, valid_ids: set[str]) -> list[str | dict[str, Any]]:
        values = payload.get(key, [])
        if not isinstance(values, list):
            return []

        items: list[str | dict[str, Any]] = []
        for value in values[:limit]:
            if isinstance(value, dict):
                text = normalize_text(str(value.get("text") or value.get("takeaway") or value.get("summary") or ""))
                supporting_excerpt = normalize_highlight_snippet(
                    str(
                        value.get("supporting_excerpt")
                        or value.get("evidence_hint")
                        or value.get("evidence")
                        or value.get("evidence_snippet")
                        or ""
                    )
                )
                if text:
                    item: dict[str, Any] = {"text": text}
                    if supporting_excerpt:
                        item["supporting_excerpt"] = supporting_excerpt
                    raw_highlight_ids = value.get("highlight_ids") or value.get("highlightIds") or []
                    if isinstance(raw_highlight_ids, str):
                        raw_highlight_ids = re.split(r"[\s,;]+", raw_highlight_ids)
                    if isinstance(raw_highlight_ids, list):
                        highlight_ids = []
                        for raw_id in raw_highlight_ids:
                            highlight_id = normalize_reference_id(raw_id, "")
                            if highlight_id and highlight_id in valid_ids and highlight_id not in highlight_ids:
                                highlight_ids.append(highlight_id)
                        if highlight_ids:
                            item["highlight_ids"] = highlight_ids
                    items.append(item)
                continue

            text = normalize_text(str(value))
            if text:
                items.append(text)
        return items

    glossary = payload.get("glossary", [])
    if not isinstance(glossary, list):
        glossary = []

    highlights = payload.get("highlights", [])
    if not isinstance(highlights, list):
        highlights = []

    normalized_highlights = []
    used_highlight_ids: set[str] = set()
    for index, item in enumerate(highlights[:MAX_ANALYSIS_HIGHLIGHTS], start=1):
        if not isinstance(item, dict) or not item.get("snippet"):
            continue

        fallback_id = f"h{index}"
        highlight_id = normalize_reference_id(item.get("id"), fallback_id)
        if highlight_id in used_highlight_ids:
            highlight_id = fallback_id
        while highlight_id in used_highlight_ids:
            highlight_id = f"{fallback_id}-{len(used_highlight_ids) + 1}"
        used_highlight_ids.add(highlight_id)

        normalized_highlights.append(
            {
                "id": highlight_id,
                "label": str(item.get("label", "important")),
                "snippet": normalize_highlight_snippet(str(item.get("snippet", ""))),
                "reason": normalize_text(str(item.get("reason", "")))[:500],
                "comment": normalize_text(str(item.get("comment", "")))[:700],
            }
        )
    valid_highlight_ids = {highlight["id"] for highlight in normalized_highlights}

    return {
        "title": normalize_text(str(payload.get("title") or extracted.title))[:220],
        "overview": normalize_text(str(payload.get("overview") or "")),
        "background_notes": list_of_strings("background_notes", 6),
        "key_takeaways": list_of_summary_items("key_takeaways", 8, valid_highlight_ids),
        "not_shown": list_of_strings("not_shown", 4),
        "code_availability": list_of_strings("code_availability", 3),
        "reviewer_questions": list_of_strings("reviewer_questions", 6),
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
        int(os.getenv("CODEX_ANALYSIS_TIMEOUT_SECONDS", os.getenv("CODEX_TIMEOUT_SECONDS", "600"))),
    )
    analysis = normalize_analysis(parse_json_payload(output), extracted)

    analysis["highlights"] = ground_highlights(pdf_path, analysis.get("highlights", []), extracted.sentence_spans)
    analysis["provider_used"] = provider_used
    analysis["warnings"] = analysis.get("warnings", [])
    return analysis


def build_figure_prompt(page_number: int, page_text: str) -> str:
    return render_prompt("figure_user.md", page_number=page_number, page_text=page_text[:5000])


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
    elif selected_provider == "openrouter":
        output = run_openrouter_vision(prompt, image_path, api_key, model, reasoning_effort)
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
    takeaways_text = "\n".join("- " + summary_item_text(item) for item in paper.get("key_takeaways", [])[:8])
    return render_prompt(
        "chat_user.md",
        title=paper.get("title", "Untitled"),
        overview=paper.get("overview", ""),
        key_takeaways=takeaways_text,
        excerpts=excerpt_text,
        citation_context=citation_text,
        figure_context=figure_text,
        web_results=web_text or "None",
        history=history,
    )


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


def summary_item_text(item: Any) -> str:
    if isinstance(item, dict):
        return normalize_text(str(item.get("text") or item.get("takeaway") or item.get("summary") or ""))
    return normalize_text(str(item))


def build_selection_explanation_prompt(
    paper: dict[str, Any],
    selected_text: str,
    page_number: int | None,
    page_text: str,
) -> str:
    page_label = f"p. {page_number}" if page_number else "unknown page"
    return render_prompt(
        "selection_explanation_user.md",
        title=paper.get("title", "Untitled"),
        overview=paper.get("overview", ""),
        page_label=page_label,
        selected_text=normalize_text(selected_text)[:700],
        page_text=normalize_text(page_text)[:5000],
    )


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
