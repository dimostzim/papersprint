import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import fitz
import pytest

from app.ai import (
    DEFAULT_MODEL,
    MAX_ANALYSIS_HIGHLIGHTS,
    analyze_page_figures,
    build_analysis_prompt,
    build_chat_prompt,
    build_figure_prompt,
    build_selection_explanation_prompt,
    choose_provider,
    choose_vision_provider,
    format_analysis_text,
    format_guided_reading_text,
    normalize_analysis,
    normalize_highlight_snippet,
    parse_json_payload,
    list_codex_models,
    provider_model_options,
    provider_status,
    resolve_reasoning_effort,
    resolve_text_model,
    run_codex,
    sanitize_prompt_text,
    select_relevant_excerpts,
)
from app.paper_processing import (
    ExtractedPaper,
    clean_pdf_text,
    find_exact_rects,
    ground_highlights,
    normalize_text,
    score_match,
    search_phrases,
    sanitize_label,
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


def test_find_exact_rects_returns_line_level_sentence_rects(tmp_path):
    pdf_path = tmp_path / "paper.pdf"
    sentence = (
        "Predicting which candidates will produce strong knockdown requires models that generalize across experiments, "
        "but published predictors are trained and evaluated on incompatible datasets."
    )
    doc = fitz.open()
    page = doc.new_page(width=360, height=240)
    page.insert_textbox(fitz.Rect(72, 72, 260, 180), sentence, fontsize=10)
    doc.save(pdf_path)
    doc.close()

    page_number, rects = find_exact_rects(pdf_path, sentence)

    with fitz.open(pdf_path) as saved_doc:
        line_count = len({(word[5], word[6]) for word in saved_doc[0].get_text("words")})
    assert page_number == 1
    assert len(rects) == line_count
    assert len(rects) < len(sentence.split()) / 2


def test_ground_highlights_preserves_comments(tmp_path):
    pdf_path = tmp_path / "paper.pdf"
    sentence = "ParaDISM assigns reads only when unambiguous sequence-specific evidence supports one origin."
    doc = fitz.open()
    page = doc.new_page(width=360, height=240)
    page.insert_textbox(fitz.Rect(72, 72, 280, 180), sentence, fontsize=10)
    doc.save(pdf_path)
    doc.close()

    highlights = [
        {
            "label": "solution",
            "snippet": sentence,
            "reason": "Shows the decision rule.",
            "comment": "The method chooses caution over forced assignment.",
        }
    ]

    grounded = ground_highlights(pdf_path, highlights, [])

    assert grounded[0]["comment"] == "The method chooses caution over forced assignment."
    assert grounded[0]["rects"]


def test_parse_json_payload_handles_markdown_fence():
    payload = parse_json_payload('```json\n{"ok": true, "items": [1]}\n```')
    assert payload == {"ok": True, "items": [1]}


def test_parse_json_payload_accepts_raw_control_characters_in_strings():
    payload = parse_json_payload('{"snippet": "first line\nsecond line"}')
    assert payload == {"snippet": "first line\nsecond line"}


def test_build_analysis_prompt_asks_for_complete_guided_highlights():
    extracted = ExtractedPaper(
        "Useful paper",
        "This paper has enough\x00text to analyze.",
        [{"page_number": 2, "text": "Body text with enough detail to analyze."}],
        [],
    )

    prompt = build_analysis_prompt(extracted)

    assert "problem|solution|novelty|method|benchmarking|result|ablation|hyperparams|tradeoff|limitation|failure" in prompt
    assert '"background_notes": ["3-5 short beginner-friendly notes' in prompt
    assert "Background notes should define or contextualize important terms" in prompt
    assert '"supporting_excerpt": "exact copied paper passage that best supports this takeaway, optional"' in prompt
    assert '"highlight_ids": ["ids of returned highlights that support this takeaway, optional"]' in prompt
    assert '"id": "h1"' in prompt
    assert "Key takeaways should be understandable to a researcher outside this exact subfield" in prompt
    assert "For each key takeaway, include a supporting_excerpt" in prompt
    assert "Do not force a fixed length" in prompt
    assert "When a takeaway depends on returned highlights" in prompt
    assert '"not_shown": ["1-3 important things' in prompt
    assert '"code_availability": ["1-2 notes' in prompt
    assert '"reviewer_questions": ["3-5 concrete questions' in prompt
    assert "[plain-language meaning]" in prompt
    assert "When a figure or table is central evidence for a takeaway" in prompt
    assert "Not-shown items should prevent common over-reading" in prompt
    assert "Reviewer questions should be specific requests" in prompt
    assert "do not optimize for the absolute minimum" in prompt
    assert "Use the problem label for the task" in prompt
    assert "Use the solution label for the paper's proposed" in prompt
    assert "Use the novelty label for contribution claims" in prompt
    assert "Use the benchmarking label for benchmark construction" in prompt
    assert "Use the hyperparams label for hyperparameters" in prompt
    assert "highlight labels as a vocabulary, not a checklist" in prompt
    assert "replace a redundant generic problem/method/result highlight" in prompt
    assert "Use the failure label for reported failure modes" in prompt
    assert "Use the limitation label only for limitations of this paper's own data" in prompt
    assert "Do not label weaknesses of prior work or background motivation as limitation" in prompt
    assert "Never end an excerpt mid-word or mid-sentence" in prompt
    assert "Takeaway supporting_excerpt should usually be broader than a single highlight" in prompt
    assert '"comment": "short plain-language explanation' in prompt
    assert "Every returned highlight must include a non-empty comment" in prompt
    assert "Abstract highlights are allowed" in prompt
    assert "include it; otherwise prefer the more specific body sentence" in prompt
    assert "Do not cluster the set in the opening motivation" in prompt
    assert "[Page 2]" in prompt
    assert "Paper text:" in prompt
    assert "Return exactly" not in prompt
    assert "\x00" not in prompt


def test_format_analysis_text_adds_page_markers_without_mutating_text():
    extracted = ExtractedPaper(
        "Useful paper",
        "Fallback text",
        [
            {"page_number": 1, "text": "Abstract text."},
            {"page_number": 2, "text": "Body\x00 text."},
        ],
        [],
    )

    text = format_analysis_text(extracted)

    assert "[Page 1]\nAbstract text." in text
    assert "[Page 2]\nBody  text." in text


def test_format_guided_reading_text_keeps_abstract_and_removes_references():
    extracted = ExtractedPaper(
        "Useful paper",
        "",
        [
            {
                "page_number": 1,
                "text": (
                    "Title\nAuthors\nAbstract\n"
                    "Background\nAbstract-only motivation. "
                    "Methods\nAbstract-only method. "
                    "Results\nAbstract-only result.\n"
                    "1 Introduction\nBody contribution starts here."
                ),
            },
            {"page_number": 2, "text": "The method body gives implementation details."},
            {"page_number": 3, "text": "References\nA. Author. 2024. Reference title."},
        ],
        [],
    )

    text = format_guided_reading_text(extracted)

    assert "Abstract-only motivation" in text
    assert "[Page 1]\nTitle Authors Abstract Background Abstract-only motivation." in text
    assert "1 Introduction Body contribution starts here." in text
    assert "[Page 2]\nThe method body gives implementation details." in text
    assert "References" not in text


def test_normalize_analysis_caps_highlights_to_hard_limit():
    extracted = ExtractedPaper("Useful paper", "", [], [])
    payload = {
        "title": "Useful paper",
        "background_notes": ["RNA interference: A way to reduce target gene expression."],
        "not_shown": ["The paper does not test clinical deployment."],
        "code_availability": ["Code release is unclear from the provided text."],
        "reviewer_questions": ["Can the authors release the evaluation scripts?"],
        "key_takeaways": [
            {
                "text": "The method improves benchmark accuracy.",
                "supporting_excerpt": (
                    "The method improves benchmark accuracy by five points. "
                    "This supports the main benchmark takeaway."
                ),
                "highlight_ids": ["h1", "missing"],
            }
        ],
        "highlights": [
            {"id": f"h{index + 1}", "label": "problem", "snippet": str(index), "reason": "reason", "comment": "comment"}
            for index in range(MAX_ANALYSIS_HIGHLIGHTS + 5)
        ],
    }

    analysis = normalize_analysis(payload, extracted)

    assert len(analysis["highlights"]) == MAX_ANALYSIS_HIGHLIGHTS
    assert analysis["key_takeaways"] == [
        {
            "text": "The method improves benchmark accuracy.",
            "supporting_excerpt": (
                "The method improves benchmark accuracy by five points. "
                "This supports the main benchmark takeaway."
            ),
            "highlight_ids": ["h1"],
        }
    ]
    assert analysis["background_notes"] == ["RNA interference: A way to reduce target gene expression."]
    assert analysis["not_shown"] == ["The paper does not test clinical deployment."]
    assert analysis["code_availability"] == ["Code release is unclear from the provided text."]
    assert analysis["reviewer_questions"] == ["Can the authors release the evaluation scripts?"]
    assert analysis["highlights"][0]["id"] == "h1"
    assert analysis["highlights"][0]["comment"] == "comment"


def test_normalize_highlight_snippet_does_not_cut_mid_sentence():
    long_sentence = "This complete sentence should survive even when followed by extra text. "
    extra = " ".join(["additional"] * 120)

    snippet = normalize_highlight_snippet(long_sentence + extra)

    assert snippet == long_sentence.strip()


def test_sanitize_label_uses_guided_reading_facets():
    assert sanitize_label("objective") == "problem"
    assert sanitize_label("contribution") == "novelty"
    assert sanitize_label("approach") == "solution"
    assert sanitize_label("evidence") == "result"
    assert sanitize_label("evaluation") == "benchmarking"
    assert sanitize_label("tradeoff") == "tradeoff"
    assert sanitize_label("hyperparameters") == "hyperparams"
    assert sanitize_label("compute") == "hyperparams"
    assert sanitize_label("ablation study") == "ablation"
    assert sanitize_label("failure modes") == "failure"
    assert sanitize_label("definition") == "problem"


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


def test_build_chat_prompt_formats_structured_takeaways():
    prompt = build_chat_prompt(
        {
            "title": "Useful paper",
            "overview": "The paper studies semantic readers.",
            "key_takeaways": [{"text": "The reader links summaries to evidence.", "evidence_hint": "Exact proof."}],
        },
        [{"role": "user", "content": "What is the main takeaway?"}],
        [],
        [],
    )

    assert "- The reader links summaries to evidence." in prompt
    assert "Exact proof" not in prompt


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


def test_build_chat_prompt_includes_figure_focus():
    prompt = build_chat_prompt(
        {"title": "Useful paper", "overview": "The paper studies semantic readers.", "key_takeaways": []},
        [{"role": "user", "content": "What does this figure show?"}],
        [],
        [],
        None,
        [
            {
                "label": "Figure 2",
                "type": "plot",
                "page_number": 6,
                "caption": "Model comparison across benchmarks.",
                "explanation": "The plot compares error across methods.",
                "why_it_matters": "It supports the main evaluation claim.",
            }
        ],
    )

    assert "Figure focus:" in prompt
    assert "Figure 1: Figure 2" in prompt
    assert "Page: 6" in prompt
    assert "The plot compares error across methods." in prompt


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
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.setenv("PATH", "")

    with pytest.raises(RuntimeError, match="No AI provider available"):
        choose_provider("auto")


def test_choose_provider_uses_request_api_key_for_auto(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.setenv("PATH", "")

    assert choose_provider("auto", "sk-test") == "openai"
    assert choose_provider("auto", "sk-or-v1-test") == "openrouter"


def test_choose_provider_accepts_openrouter(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)

    assert choose_provider("openrouter") == "openrouter"


def test_provider_status_exposes_model_defaults(monkeypatch):
    monkeypatch.delenv("OPENAI_MODEL", raising=False)
    monkeypatch.delenv("CODEX_MODEL", raising=False)
    monkeypatch.delenv("OPENAI_REASONING_EFFORT", raising=False)
    monkeypatch.delenv("CODEX_REASONING_EFFORT", raising=False)
    monkeypatch.setattr("app.ai.list_codex_models", lambda: ["gpt-5.5", "gpt-5.4"])

    status = provider_status()

    assert status["default_provider"] == "codex"
    assert status["default_text_model"] == DEFAULT_MODEL
    assert status["default_vision_model"] == DEFAULT_MODEL
    assert status["default_reasoning_effort"] == "high"
    assert status["reasoning_efforts"] == ["none", "low", "medium", "high", "xhigh"]
    assert "auto" not in {provider["id"] for provider in status["providers"]}
    assert "openrouter" in {provider["id"] for provider in status["providers"]}
    assert status["provider_model_options"]["codex"]
    assert status["provider_model_options"]["openrouter"]


def test_list_codex_models_uses_visible_cli_catalog(monkeypatch):
    payload = {
        "models": [
            {"slug": "codex-auto-review", "visibility": "hide"},
            {"slug": "gpt-5.2", "visibility": "list"},
            {"slug": "gpt-5.3-codex-spark", "visibility": "list"},
            {"slug": "gpt-5.5", "visibility": "list"},
        ]
    }

    list_codex_models.cache_clear()
    monkeypatch.setattr("app.ai.shutil.which", lambda command: "/usr/local/bin/codex" if command == "codex" else None)
    monkeypatch.setattr(
        "app.ai.subprocess.run",
        lambda *_args, **_kwargs: SimpleNamespace(stdout=json.dumps(payload)),
    )

    try:
        assert list_codex_models() == ["gpt-5.5", "gpt-5.3-codex-spark", "gpt-5.2"]
    finally:
        list_codex_models.cache_clear()


def test_provider_model_options_uses_codex_catalog(monkeypatch):
    monkeypatch.setattr("app.ai.list_codex_models", lambda: ["gpt-5.5", "gpt-5.3-codex-spark"])

    assert provider_model_options("codex") == ["gpt-5.5", "gpt-5.3-codex-spark"]


def test_run_codex_timeout_hides_full_prompt(monkeypatch):
    def timeout(*_args, **kwargs):
        raise subprocess.TimeoutExpired(cmd=["codex", "very long prompt"], timeout=kwargs["timeout"])

    monkeypatch.setattr("app.ai.shutil.which", lambda command: "/usr/local/bin/codex" if command == "codex" else None)
    monkeypatch.setattr("app.ai.subprocess.run", timeout)

    with pytest.raises(RuntimeError) as error:
        run_codex("very long prompt", timeout_seconds=7, model="gpt-5.4", reasoning_effort="low")

    message = str(error.value)
    assert "Codex timed out after 7 seconds with model gpt-5.4" in message
    assert "very long prompt" not in message


def test_provider_model_options_uses_fallback_for_openrouter(monkeypatch):
    def fail(*_args, **_kwargs):
        raise RuntimeError("network down")

    monkeypatch.setattr("app.ai.list_openrouter_models", fail)

    assert provider_model_options("openrouter")[0].startswith("openai/")


def test_model_and_effort_resolution_prefers_request_then_env(monkeypatch):
    monkeypatch.setenv("OPENAI_MODEL", "gpt-5.4")
    monkeypatch.setenv("OPENAI_REASONING_EFFORT", "medium")

    assert resolve_text_model("gpt-5.5") == "gpt-5.5"
    assert resolve_text_model(None) == "gpt-5.4"
    assert resolve_reasoning_effort("xhigh", "OPENAI_REASONING_EFFORT") == "xhigh"
    assert resolve_reasoning_effort(None, "OPENAI_REASONING_EFFORT") == "medium"
    assert resolve_reasoning_effort("bad", "OPENAI_REASONING_EFFORT") == "medium"


def test_choose_vision_provider_prefers_codex_for_auto(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.setenv("AI_PROVIDER", "openai")
    monkeypatch.setattr("app.ai.shutil.which", lambda command: "/usr/local/bin/codex" if command == "codex" else None)

    assert choose_vision_provider("auto") == "codex"


def test_choose_vision_provider_requires_available_provider(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.setattr("app.ai.shutil.which", lambda command: None)

    with pytest.raises(RuntimeError, match="No vision provider available"):
        choose_vision_provider("auto")


def test_choose_vision_provider_accepts_request_api_key(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    assert choose_vision_provider("openai", "sk-test") == "openai"


def test_build_figure_prompt_prioritizes_scientific_point():
    prompt = build_figure_prompt(3, "Figure 2 compares the benchmark results.")

    assert "main scientific point" in prompt
    assert "not a full inventory of visible details" in prompt
    assert "incidental layout, colors, icons, or decorative details" in prompt
    assert "what claim the visual is evidence for" in prompt


def test_analyze_page_figures_uses_codex_vision(monkeypatch, tmp_path):
    image_path = tmp_path / "page.jpg"
    image_path.write_bytes(b"jpeg")
    monkeypatch.setattr("app.ai.shutil.which", lambda command: "/usr/local/bin/codex" if command == "codex" else None)
    monkeypatch.setattr("app.ai.run_codex_vision", lambda prompt, image_path, model=None, reasoning_effort=None: '{"figures": []}')

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
