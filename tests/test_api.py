from fastapi.testclient import TestClient

from app import main


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
        "highlight_target": 15,
        "analysis_status": "ready",
        "analysis_error": "",
    }

    def close_background_task(coroutine):
        coroutine.close()

    monkeypatch.setattr(main.asyncio, "create_task", close_background_task)

    client = TestClient(main.app)
    response = client.post(
        "/api/papers/paper-1/analyze",
        json={"provider": "codex", "highlight_count": 8},
    )

    assert response.status_code == 200
    assert main.PAPERS["paper-1"]["analysis_status"] == "analyzing"
    assert main.PAPERS["paper-1"]["page_sizes"] == page_sizes
    assert main.PAPERS["paper-1"]["sentences"] == sentences
    assert main.PAPERS["paper-1"]["full_text_chars"] == 120
