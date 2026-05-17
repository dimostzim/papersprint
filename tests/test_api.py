import json

import fitz
from fastapi.testclient import TestClient

from app import main


def make_pdf_bytes(text: str = "Readable paper text.") -> bytes:
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), text)
    data = doc.tobytes()
    doc.close()
    return data


def test_upload_rejects_unreadable_pdf_and_removes_file(tmp_path, monkeypatch):
    papers_dir = tmp_path / "papers"
    papers_dir.mkdir()
    monkeypatch.setattr(main, "PAPERS_DIR", papers_dir)
    main.PAPERS.clear()

    client = TestClient(main.app)
    response = client.post(
        "/api/upload",
        files={"file": ("bad.pdf", b"not a real pdf", "application/pdf")},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Uploaded file is not a readable PDF."
    assert list(papers_dir.iterdir()) == []
    assert main.PAPERS == {}


def test_analyze_preserves_extracted_metadata_while_running(tmp_path, monkeypatch):
    papers_dir = tmp_path / "papers"
    papers_dir.mkdir()
    (papers_dir / "paper.pdf").write_bytes(b"%PDF-1.4\n")
    monkeypatch.setattr(main, "PAPERS_DIR", papers_dir)
    main.PAPERS.clear()

    page_sizes = [{"page_number": 1, "width": 600, "height": 800}]
    sentences = [{"text": "This paper has extracted text ready for chat.", "page_number": 1}]
    main.PAPERS["paper-1"] = {
        "id": "paper-1",
        "filename": "paper.pdf",
        "stored_pdf": "paper.pdf",
        "title": "Readable paper",
        "overview": "PDF loaded.",
        "key_takeaways": [],
        "read_this_first": [],
        "glossary": [],
        "highlights": [],
        "figures": [],
        "figure_warnings": [],
        "figure_provider_used": "unknown",
        "citations": [],
        "questions": [],
        "provider_used": "not analyzed",
        "warnings": [],
        "page_sizes": page_sizes,
        "sentences": sentences,
        "full_text_chars": 120,
        "analysis_status": "ready",
        "analysis_error": "",
    }

    def close_background_task(coroutine):
        coroutine.close()

    monkeypatch.setattr(main.asyncio, "create_task", close_background_task)

    client = TestClient(main.app)
    response = client.post(
        "/api/papers/paper-1/analyze",
        json={"provider": "codex"},
    )

    assert response.status_code == 200
    assert main.PAPERS["paper-1"]["analysis_status"] == "analyzing"
    assert main.PAPERS["paper-1"]["page_sizes"] == page_sizes
    assert main.PAPERS["paper-1"]["sentences"] == sentences
    assert main.PAPERS["paper-1"]["full_text_chars"] == 120


def test_upload_uses_cached_completed_analysis(tmp_path, monkeypatch):
    papers_dir = tmp_path / "papers"
    figures_dir = tmp_path / "figures"
    cache_papers_dir = tmp_path / "cache-papers"
    cache_records_dir = tmp_path / "cache-records"
    cache_figures_dir = tmp_path / "cache-figures"
    for directory in (papers_dir, figures_dir, cache_papers_dir, cache_records_dir, cache_figures_dir):
        directory.mkdir()
    monkeypatch.setattr(main, "PAPERS_DIR", papers_dir)
    monkeypatch.setattr(main, "FIGURES_DIR", figures_dir)
    monkeypatch.setattr(main, "CACHE_PAPERS_DIR", cache_papers_dir)
    monkeypatch.setattr(main, "CACHE_RECORDS_DIR", cache_records_dir)
    monkeypatch.setattr(main, "CACHE_FIGURES_DIR", cache_figures_dir)
    main.PAPERS.clear()

    data = make_pdf_bytes()
    digest = main.file_digest(data)
    cached_pdf = cache_papers_dir / f"{digest}.pdf"
    cached_pdf.write_bytes(data)
    cached_figure_dir = main.figure_directory(cache_figures_dir, digest)
    cached_figure_dir.mkdir()
    (cached_figure_dir / "p1-1.jpg").write_bytes(b"figure")
    cached_record = {
        "id": "old-id",
        "filename": "old.pdf",
        "stored_pdf": "old.pdf",
        "digest": digest,
        "analysis_version": main.ANALYSIS_VERSION,
        "title": "Cached analysis",
        "overview": "Already analyzed.",
        "key_takeaways": ["Cached takeaway"],
        "read_this_first": [],
        "glossary": [],
        "highlights": [{"label": "goal", "snippet": "Cached highlight", "reason": "Cached"}],
        "figures": [{"id": "p1-1", "image_file": "p1-1.jpg", "label": "Figure 1"}],
        "figure_warnings": [],
        "figure_provider_used": "codex",
        "citations": [],
        "questions": [],
        "provider_used": "codex",
        "warnings": [],
        "page_sizes": [],
        "sentences": [],
        "full_text_chars": 42,
        "analysis_status": "complete",
        "analysis_error": "",
    }
    (cache_records_dir / f"{digest}.json").write_text(json.dumps(cached_record), encoding="utf-8")

    client = TestClient(main.app)
    response = client.post(
        "/api/upload",
        files={"file": ("paper.pdf", data, "application/pdf")},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["id"] == digest[:12]
    assert payload["title"] == "Cached analysis"
    assert payload["analysis_status"] == "complete"
    assert payload["highlight_count"] == 1
    assert payload["figure_count"] == 1
    assert main.PAPERS[digest[:12]]["figures"][0]["id"] == "p1-1"
    assert (main.figure_directory(figures_dir, digest[:12]) / "p1-1.jpg").exists()
    assert (papers_dir / f"{digest[:12]}-paper.pdf").exists()


def test_cache_paper_persists_figure_records_and_images(tmp_path, monkeypatch):
    papers_dir = tmp_path / "papers"
    figures_dir = tmp_path / "figures"
    cache_papers_dir = tmp_path / "cache-papers"
    cache_records_dir = tmp_path / "cache-records"
    cache_figures_dir = tmp_path / "cache-figures"
    for directory in (papers_dir, figures_dir, cache_papers_dir, cache_records_dir, cache_figures_dir):
        directory.mkdir()
    monkeypatch.setattr(main, "PAPERS_DIR", papers_dir)
    monkeypatch.setattr(main, "FIGURES_DIR", figures_dir)
    monkeypatch.setattr(main, "CACHE_PAPERS_DIR", cache_papers_dir)
    monkeypatch.setattr(main, "CACHE_RECORDS_DIR", cache_records_dir)
    monkeypatch.setattr(main, "CACHE_FIGURES_DIR", cache_figures_dir)

    pdf_path = papers_dir / "paper.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n")
    figure_dir = main.figure_directory(figures_dir, "paper-1")
    figure_dir.mkdir()
    (figure_dir / "p1-1.jpg").write_bytes(b"figure")
    paper = {
        "id": "paper-1",
        "filename": "paper.pdf",
        "stored_pdf": "paper.pdf",
        "digest": "digest-1",
        "title": "Readable paper",
        "figures": [{"id": "p1-1", "image_file": "p1-1.jpg", "label": "Figure 1"}],
        "figure_warnings": [],
        "figure_provider_used": "codex",
    }

    main.cache_paper(paper, pdf_path)

    cached_record = json.loads((cache_records_dir / "digest-1.json").read_text(encoding="utf-8"))
    assert cached_record["figures"][0]["id"] == "p1-1"
    assert cached_record["figure_provider_used"] == "codex"
    assert (main.figure_directory(cache_figures_dir, "digest-1") / "p1-1.jpg").exists()


def test_refresh_cache_loads_cached_papers_and_figures(tmp_path, monkeypatch):
    papers_dir = tmp_path / "papers"
    figures_dir = tmp_path / "figures"
    cache_papers_dir = tmp_path / "cache-papers"
    cache_records_dir = tmp_path / "cache-records"
    cache_figures_dir = tmp_path / "cache-figures"
    for directory in (papers_dir, figures_dir, cache_papers_dir, cache_records_dir, cache_figures_dir):
        directory.mkdir()
    monkeypatch.setattr(main, "PAPERS_DIR", papers_dir)
    monkeypatch.setattr(main, "FIGURES_DIR", figures_dir)
    monkeypatch.setattr(main, "CACHE_PAPERS_DIR", cache_papers_dir)
    monkeypatch.setattr(main, "CACHE_RECORDS_DIR", cache_records_dir)
    monkeypatch.setattr(main, "CACHE_FIGURES_DIR", cache_figures_dir)
    main.PAPERS.clear()

    data = make_pdf_bytes()
    digest = main.file_digest(data)
    (cache_papers_dir / f"{digest}.pdf").write_bytes(data)
    cached_figure_dir = main.figure_directory(cache_figures_dir, digest)
    cached_figure_dir.mkdir()
    (cached_figure_dir / "p1-1.jpg").write_bytes(b"figure")
    cached_record = {
        "id": "old-id",
        "filename": "paper.pdf",
        "stored_pdf": "old.pdf",
        "digest": digest,
        "analysis_version": main.ANALYSIS_VERSION,
        "title": "Cached paper",
        "overview": "Already analyzed.",
        "key_takeaways": ["Cached takeaway"],
        "read_this_first": [],
        "glossary": [],
        "highlights": [{"label": "goal", "snippet": "Cached highlight", "reason": "Cached"}],
        "figures": [{"id": "p1-1", "image_file": "p1-1.jpg", "label": "Figure 1"}],
        "figure_warnings": [],
        "figure_provider_used": "codex",
        "citations": [],
        "questions": [],
        "provider_used": "codex",
        "warnings": [],
        "page_sizes": [],
        "sentences": [],
        "full_text_chars": 42,
        "analysis_status": "complete",
        "analysis_error": "",
    }
    (cache_records_dir / f"{digest}.json").write_text(json.dumps(cached_record), encoding="utf-8")

    client = TestClient(main.app)
    response = client.post("/api/papers/refresh-cache")

    assert response.status_code == 200
    payload = response.json()
    assert payload["loaded_count"] == 1
    assert payload["papers"][0]["id"] == digest[:12]
    assert payload["papers"][0]["highlight_count"] == 1
    assert payload["papers"][0]["figure_count"] == 1
    assert (papers_dir / f"{digest[:12]}-paper.pdf").exists()
    assert (main.figure_directory(figures_dir, digest[:12]) / "p1-1.jpg").exists()


def test_upload_ignores_stale_cached_analysis(tmp_path, monkeypatch):
    papers_dir = tmp_path / "papers"
    figures_dir = tmp_path / "figures"
    cache_papers_dir = tmp_path / "cache-papers"
    cache_records_dir = tmp_path / "cache-records"
    cache_figures_dir = tmp_path / "cache-figures"
    for directory in (papers_dir, figures_dir, cache_papers_dir, cache_records_dir, cache_figures_dir):
        directory.mkdir()
    monkeypatch.setattr(main, "PAPERS_DIR", papers_dir)
    monkeypatch.setattr(main, "FIGURES_DIR", figures_dir)
    monkeypatch.setattr(main, "CACHE_PAPERS_DIR", cache_papers_dir)
    monkeypatch.setattr(main, "CACHE_RECORDS_DIR", cache_records_dir)
    monkeypatch.setattr(main, "CACHE_FIGURES_DIR", cache_figures_dir)
    main.PAPERS.clear()

    data = make_pdf_bytes()
    digest = main.file_digest(data)
    (cache_papers_dir / f"{digest}.pdf").write_bytes(data)
    cached_figure_dir = main.figure_directory(cache_figures_dir, digest)
    cached_figure_dir.mkdir()
    (cached_figure_dir / "p1-1.jpg").write_bytes(b"figure")
    stale_record = {
        "id": "old-id",
        "filename": "old.pdf",
        "stored_pdf": "old.pdf",
        "digest": digest,
        "analysis_version": main.ANALYSIS_VERSION - 1,
        "title": "Stale analysis",
        "highlights": [{"label": "goal", "snippet": "Bad cached highlight", "reason": ""}],
        "figures": [{"id": "p1-1", "image_file": "p1-1.jpg", "label": "Figure 1"}],
        "figure_warnings": [],
        "figure_provider_used": "codex",
        "analysis_status": "complete",
    }
    (cache_records_dir / f"{digest}.json").write_text(json.dumps(stale_record), encoding="utf-8")

    client = TestClient(main.app)
    response = client.post(
        "/api/upload",
        files={"file": ("paper.pdf", data, "application/pdf")},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["analysis_status"] == "ready"
    assert payload["title"] != "Stale analysis"
    assert payload["highlight_count"] == 0
    assert payload["figure_count"] == 1
    assert main.PAPERS[digest[:12]]["figures"][0]["id"] == "p1-1"


def test_delete_paper_removes_session_files(tmp_path, monkeypatch):
    papers_dir = tmp_path / "papers"
    figures_dir = tmp_path / "figures"
    cache_papers_dir = tmp_path / "cache-papers"
    cache_records_dir = tmp_path / "cache-records"
    cache_figures_dir = tmp_path / "cache-figures"
    papers_dir.mkdir()
    figures_dir.mkdir()
    cache_papers_dir.mkdir()
    cache_records_dir.mkdir()
    cache_figures_dir.mkdir()
    pdf_path = papers_dir / "paper.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n")
    digest = "abc123def456"
    cached_pdf = cache_papers_dir / f"{digest}.pdf"
    cached_record = cache_records_dir / f"{digest}.json"
    cached_pdf.write_bytes(b"%PDF-1.4\n")
    cached_record.write_text("{}", encoding="utf-8")
    cached_figures = main.figure_directory(cache_figures_dir, digest)
    cached_figures.mkdir()
    (cached_figures / "figure.jpg").write_bytes(b"cached image")
    figure_dir = main.figure_directory(figures_dir, "paper-1")
    figure_dir.mkdir()
    (figure_dir / "figure.jpg").write_bytes(b"image")
    monkeypatch.setattr(main, "PAPERS_DIR", papers_dir)
    monkeypatch.setattr(main, "FIGURES_DIR", figures_dir)
    monkeypatch.setattr(main, "CACHE_PAPERS_DIR", cache_papers_dir)
    monkeypatch.setattr(main, "CACHE_RECORDS_DIR", cache_records_dir)
    monkeypatch.setattr(main, "CACHE_FIGURES_DIR", cache_figures_dir)
    main.PAPERS.clear()
    main.PAPERS["paper-1"] = {
        "id": "paper-1",
        "filename": "paper.pdf",
        "stored_pdf": "paper.pdf",
        "digest": digest,
        "title": "Readable paper",
    }

    client = TestClient(main.app)
    response = client.delete("/api/papers/paper-1")

    assert response.status_code == 200
    assert response.json() == {"deleted": True}
    assert "paper-1" not in main.PAPERS
    assert not pdf_path.exists()
    assert not figure_dir.exists()
    assert not cached_pdf.exists()
    assert not cached_record.exists()
    assert not cached_figures.exists()


def test_delete_missing_paper_is_idempotent(tmp_path, monkeypatch):
    figures_dir = tmp_path / "figures"
    cache_papers_dir = tmp_path / "cache-papers"
    cache_records_dir = tmp_path / "cache-records"
    cache_figures_dir = tmp_path / "cache-figures"
    figures_dir.mkdir()
    cache_papers_dir.mkdir()
    cache_records_dir.mkdir()
    cache_figures_dir.mkdir()
    figure_dir = main.figure_directory(figures_dir, "missing-paper")
    figure_dir.mkdir()
    cached_pdf = cache_papers_dir / "missing-paper1234567890.pdf"
    cached_record = cache_records_dir / "missing-paper1234567890.json"
    cached_pdf.write_bytes(b"%PDF-1.4\n")
    cached_record.write_text("{}", encoding="utf-8")
    cached_figures = main.figure_directory(cache_figures_dir, "missing-paper")
    cached_figures.mkdir()
    monkeypatch.setattr(main, "FIGURES_DIR", figures_dir)
    monkeypatch.setattr(main, "CACHE_PAPERS_DIR", cache_papers_dir)
    monkeypatch.setattr(main, "CACHE_RECORDS_DIR", cache_records_dir)
    monkeypatch.setattr(main, "CACHE_FIGURES_DIR", cache_figures_dir)
    main.PAPERS.clear()

    client = TestClient(main.app)
    response = client.delete("/api/papers/missing-paper")

    assert response.status_code == 200
    assert response.json() == {"deleted": False}
    assert not figure_dir.exists()
    assert not cached_pdf.exists()
    assert not cached_record.exists()
    assert not cached_figures.exists()


def test_chat_passes_figure_context(monkeypatch):
    main.PAPERS.clear()
    main.PAPERS["paper-1"] = {
        "id": "paper-1",
        "filename": "paper.pdf",
        "stored_pdf": "paper.pdf",
        "title": "Readable paper",
        "overview": "Paper overview.",
        "key_takeaways": [],
        "sentences": [],
    }
    captured = {}

    def fake_answer_chat(paper, messages, web_results, provider, citation_context=None, api_key=None, figure_context=None):
        captured["figure_context"] = figure_context
        return {"answer": "ok", "provider_used": "test", "web_results": [], "warnings": []}

    monkeypatch.setattr(main, "answer_chat", fake_answer_chat)

    client = TestClient(main.app)
    response = client.post(
        "/api/papers/paper-1/chat",
        json={
            "messages": [{"role": "user", "content": "What does this figure show?"}],
            "figure_context": [{"label": "Figure 1", "page_number": 3, "explanation": "A plotted result."}],
        },
    )

    assert response.status_code == 200
    assert response.json()["answer"] == "ok"
    assert captured["figure_context"][0]["label"] == "Figure 1"
