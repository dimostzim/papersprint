from pathlib import Path

import pytest

from app.ai import (
    analyze_page_figures,
    build_analysis_prompt,
    build_chat_prompt,
    build_selection_explanation_prompt,
    choose_provider,
    choose_vision_provider,
    normalize_analysis,
    parse_json_payload,
    sanitize_prompt_text,
    select_relevant_excerpts,
)
from app.paper_processing import (
    ExtractedPaper,
    clean_pdf_text,
    normalize_text,
    score_match,
    search_phrases,
    slugify,
    sort_highlights,
    split_sentences,
)


def test_normalize_text_collapses_whitespace():
    assert normalize_text("A\n\n  useful\tpaper") == "A useful paper"


def test_pdf_and_prompt_text_remove_embedded_nulls():
    assert clean_pdf_text("A\x00paper") == "A paper"
    assert sanitize_prompt_text("A\x00prompt") == "A prompt"


def test_split_sentences_keeps_substantial_sentences():
    text = "Short. We propose a method that improves paper reading for researchers. It works on PDFs."
    assert split_sentences(text) == ["We propose a method that improves paper reading for researchers."]


def test_score_match_prefers_shared_scientific_terms():
    assert score_match("semantic graph reader", "The reader uses a semantic graph.") > 0.6
    assert score_match("semantic graph reader", "The dataset contains microscopy images.") == 0


def test_search_phrases_include_reasonable_chunks():
    phrases = search_phrases(
        "This paper presents an interactive reading interface for scholarly documents using AI generated highlights."
    )
    assert phrases
    assert all(len(phrase) >= 40 for phrase in phrases)


def test_parse_json_payload_handles_markdown_fence():
    payload = parse_json_payload('```json\n{"ok": true, "items": [1]}\n```')
    assert payload == {"ok": True, "items": [1]}


def test_parse_json_payload_accepts_raw_control_characters_in_strings():
    payload = parse_json_payload('{"snippet": "first line\nsecond line"}')
    assert payload == {"snippet": "first line\nsecond line"}


def test_build_analysis_prompt_uses_requested_highlight_count():
    extracted = ExtractedPaper("Useful paper", "This paper has enough\x00text to analyze.", [], [])

    prompt = build_analysis_prompt(extracted, 15)

    assert "Return exactly 15 highlights." in prompt
    assert "\x00" not in prompt


def test_normalize_analysis_caps_highlights_to_requested_count():
    extracted = ExtractedPaper("Useful paper", "", [], [])
    payload = {
        "title": "Useful paper",
        "highlights": [
            {"label": "goal", "snippet": "one", "reason": "first"},
            {"label": "method", "snippet": "two", "reason": "second"},
            {"label": "result", "snippet": "three", "reason": "third"},
        ],
    }

    analysis = normalize_analysis(payload, extracted, 2)

    assert [item["snippet"] for item in analysis["highlights"]] == ["one", "two"]


def test_build_selection_explanation_prompt_uses_selection_and_page_context():
    paper = {"title": "Useful paper", "overview": "The paper studies semantic readers."}

    prompt = build_selection_explanation_prompt(
        paper,
        "Semantic Reader",
        3,
        "Semantic Reader augments scholarly PDFs with interactive reading tools.",
    )

    assert "Selected text (p. 3):" in prompt
    assert "Semantic Reader" in prompt
    assert "interactive reading tools" in prompt


def test_build_chat_prompt_includes_citation_focus():
    prompt = build_chat_prompt(
        {"title": "Useful paper", "overview": "The paper studies semantic readers.", "key_takeaways": []},
        [{"role": "user", "content": "Why is this citation important?"}],
        [],
        [],
        {
            "label": "[15]",
            "title": "CiteSee",
            "authors": "A. Reader",
            "year": "2022",
            "raw_reference": "A. Reader. 2022. CiteSee. CHI.",
            "contexts": [{"page_number": 4, "sentence": "CiteSee highlights familiar citations [15]."}],
        },
    )

    assert "Citation focus:" in prompt
    assert "Label: [15]" in prompt
    assert "p. 4: CiteSee highlights familiar citations [15]." in prompt


def test_select_relevant_excerpts_by_question_terms():
    spans = [
        {"text": "The method uses semantic graph features.", "page_number": 2},
        {"text": "The limitation is that scanned PDFs remain difficult.", "page_number": 7},
    ]
    selected = select_relevant_excerpts("What are the limitations?", spans, max_excerpts=1)
    assert selected[0]["page_number"] == 7


def test_slugify_produces_file_safe_name():
    assert slugify(Path("A Semantic Reader!.pdf").stem) == "a-semantic-reader"


def test_choose_provider_rejects_removed_local_provider():
    with pytest.raises(RuntimeError, match="local fallback provider has been removed"):
        choose_provider("local")


def test_choose_provider_requires_ai_provider_for_auto(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("PATH", "")

    with pytest.raises(RuntimeError, match="No AI provider available"):
        choose_provider("auto")


def test_choose_provider_uses_request_api_key_for_auto(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("PATH", "")

    assert choose_provider("auto", "sk-test") == "openai"


def test_choose_vision_provider_prefers_codex_for_auto(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("AI_PROVIDER", "openai")
    monkeypatch.setattr("app.ai.shutil.which", lambda command: "/usr/local/bin/codex" if command == "codex" else None)

    assert choose_vision_provider("auto") == "codex"


def test_choose_vision_provider_requires_available_provider(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr("app.ai.shutil.which", lambda command: None)

    with pytest.raises(RuntimeError, match="No vision provider available"):
        choose_vision_provider("auto")


def test_choose_vision_provider_accepts_request_api_key(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    assert choose_vision_provider("openai", "sk-test") == "openai"


def test_analyze_page_figures_uses_codex_vision(monkeypatch, tmp_path):
    image_path = tmp_path / "page.jpg"
    image_path.write_bytes(b"jpeg")
    monkeypatch.setattr("app.ai.shutil.which", lambda command: "/usr/local/bin/codex" if command == "codex" else None)
    monkeypatch.setattr("app.ai.run_codex_vision", lambda prompt, image_path: '{"figures": []}')

    payload = analyze_page_figures(1, "Figure 1 shows the main result.", image_path, "codex")

    assert payload == {"figures": [], "provider_used": "codex"}


def test_sort_highlights_uses_pdf_position():
    highlights = [
        {"page_number": 3, "rects": [[10, 40, 20, 50]], "snippet": "third"},
        {"page_number": 1, "rects": [[10, 80, 20, 90]], "snippet": "second on page"},
        {"page_number": 1, "rects": [[10, 20, 20, 30]], "snippet": "first on page"},
    ]

    assert [item["snippet"] for item in sort_highlights(highlights)] == [
        "first on page",
        "second on page",
        "third",
    ]
