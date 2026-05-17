from __future__ import annotations

import asyncio
import json
import shutil
from pathlib import Path
from typing import Any

import fitz
from dotenv import load_dotenv
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from starlette.requests import Request

from .ai import ANALYSIS_VERSION, analyze_paper, answer_chat, answer_selection_explanation, provider_status
from .citations import extract_citations, ground_citation_rects
from .figures import analyze_figures, figure_directory
from .paper_processing import extract_pdf, file_digest, find_exact_rects, public_page_sizes, slugify, sort_highlights
from .web_search import search_web

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
SESSION_DIR = DATA_DIR / "session"
CACHE_DIR = DATA_DIR / "cache"
PAPERS_DIR = SESSION_DIR / "papers"
FIGURES_DIR = SESSION_DIR / "figures"
CACHE_PAPERS_DIR = CACHE_DIR / "papers"
CACHE_RECORDS_DIR = CACHE_DIR / "records"
CACHE_FIGURES_DIR = CACHE_DIR / "figures"
STATIC_DIR = BASE_DIR / "static"
TEMPLATES_DIR = BASE_DIR / "templates"

shutil.rmtree(SESSION_DIR, ignore_errors=True)
PAPERS_DIR.mkdir(parents=True, exist_ok=True)
FIGURES_DIR.mkdir(parents=True, exist_ok=True)
CACHE_PAPERS_DIR.mkdir(parents=True, exist_ok=True)
CACHE_RECORDS_DIR.mkdir(parents=True, exist_ok=True)
CACHE_FIGURES_DIR.mkdir(parents=True, exist_ok=True)
PAPERS: dict[str, dict[str, Any]] = {}

app = FastAPI(title="PaperSprint")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
templates = Jinja2Templates(directory=TEMPLATES_DIR)


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    messages: list[ChatMessage]
    use_web: bool = False
    provider: str | None = None
    api_key: str | None = None
    citation_context: dict[str, Any] | None = None
    figure_context: list[dict[str, Any]] | None = None


class FigureAnalysisRequest(BaseModel):
    provider: str | None = None
    api_key: str | None = None
    force: bool = False


class AnalysisRequest(BaseModel):
    provider: str | None = "auto"
    api_key: str | None = None


class SelectionExplainRequest(BaseModel):
    selected_text: str
    page_number: int | None = None
    page_text: str = ""
    provider: str | None = None
    api_key: str | None = None


class HighlightsUpdateRequest(BaseModel):
    highlights: list[dict[str, Any]]


def read_paper(paper_id: str) -> dict[str, Any]:
    paper = PAPERS.get(paper_id)
    if not paper:
        raise HTTPException(status_code=404, detail="Paper not found.")
    return paper


def write_paper(paper: dict[str, Any]) -> None:
    PAPERS[paper["id"]] = paper


def cache_record_path(digest: str) -> Path:
    return CACHE_RECORDS_DIR / f"{digest}.json"


def cache_pdf_path(digest: str) -> Path:
    return CACHE_PAPERS_DIR / f"{digest}.pdf"


def cache_figures_path(digest: str) -> Path:
    return figure_directory(CACHE_FIGURES_DIR, digest)


def copy_figure_directory(source: Path, target: Path) -> None:
    shutil.rmtree(target, ignore_errors=True)
    if source.exists():
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(source, target)


def restore_cached_figures(digest: str, paper_id: str, paper: dict[str, Any]) -> None:
    if not paper.get("figures"):
        paper["figures"] = []
        paper["figure_warnings"] = paper.get("figure_warnings", [])
        paper["figure_provider_used"] = paper.get("figure_provider_used", "unknown")
        return

    source_figures = cache_figures_path(digest)
    if source_figures.exists():
        copy_figure_directory(source_figures, figure_directory(FIGURES_DIR, paper_id))
        return

    paper["figures"] = []
    paper["figure_warnings"] = []
    paper["figure_provider_used"] = "unknown"


def restore_cached_figure_analysis(digest: str, paper_id: str, paper: dict[str, Any]) -> None:
    record_path = cache_record_path(digest)
    if not record_path.exists():
        return

    cached = json.loads(record_path.read_text(encoding="utf-8"))
    if not cached.get("figures"):
        return

    paper["figures"] = cached.get("figures", [])
    paper["figure_warnings"] = cached.get("figure_warnings", [])
    paper["figure_provider_used"] = cached.get("figure_provider_used", "unknown")
    restore_cached_figures(digest, paper_id, paper)


def cache_figure_images(digest: str, paper: dict[str, Any]) -> bool:
    target_figures = cache_figures_path(digest)
    if not paper.get("figures"):
        shutil.rmtree(target_figures, ignore_errors=True)
        return False

    source_figures = figure_directory(FIGURES_DIR, str(paper.get("id", "")))
    if source_figures.exists():
        copy_figure_directory(source_figures, target_figures)
        return True

    return target_figures.exists()


def cached_analysis(digest: str, paper_id: str, filename: str, stored_pdf: str) -> dict[str, Any] | None:
    record_path = cache_record_path(digest)
    source_pdf = cache_pdf_path(digest)
    if not record_path.exists() or not source_pdf.exists():
        return None

    paper = json.loads(record_path.read_text(encoding="utf-8"))
    if paper.get("analysis_version") != ANALYSIS_VERSION:
        return None

    paper.update(
        {
            "id": paper_id,
            "filename": filename,
            "stored_pdf": stored_pdf,
        }
    )
    shutil.copyfile(source_pdf, PAPERS_DIR / stored_pdf)
    restore_cached_figures(digest, paper_id, paper)
    return paper


def cached_paper_from_record(record_path: Path) -> dict[str, Any] | None:
    digest = record_path.stem
    source_pdf = cache_pdf_path(digest)
    if not source_pdf.exists():
        return None

    record = json.loads(record_path.read_text(encoding="utf-8"))
    paper_id = digest[:12]
    filename = str(record.get("filename") or f"{paper_id}.pdf")
    stored_pdf = f"{paper_id}-{slugify(Path(filename).stem)}.pdf"

    cached = cached_analysis(digest, paper_id, filename, stored_pdf)
    if cached:
        return cached

    if not record.get("figures"):
        return None

    pdf_path = PAPERS_DIR / stored_pdf
    shutil.copyfile(source_pdf, pdf_path)
    paper = build_uploaded_paper_record(pdf_path, paper_id, filename, digest)
    restore_cached_figure_analysis(digest, paper_id, paper)
    return paper


def restore_all_cached_papers() -> int:
    loaded_count = 0
    record_paths = sorted(CACHE_RECORDS_DIR.glob("*.json"), key=lambda path: path.stat().st_mtime)
    for record_path in record_paths:
        paper = cached_paper_from_record(record_path)
        if not paper:
            continue
        write_paper(paper)
        loaded_count += 1
    return loaded_count


def cache_paper(paper: dict[str, Any], pdf_path: Path) -> None:
    digest = str(paper.get("digest", ""))
    if not digest:
        return

    CACHE_PAPERS_DIR.mkdir(parents=True, exist_ok=True)
    CACHE_RECORDS_DIR.mkdir(parents=True, exist_ok=True)
    CACHE_FIGURES_DIR.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(pdf_path, cache_pdf_path(digest))
    cached = dict(paper)
    if not cache_figure_images(digest, cached):
        cached["figures"] = []
        cached["figure_warnings"] = []
        cached["figure_provider_used"] = "unknown"
    cache_record_path(digest).write_text(json.dumps(cached), encoding="utf-8")


def delete_cached_paper(digest: str, paper_id: str) -> None:
    if digest:
        cache_pdf_path(digest).unlink(missing_ok=True)
        cache_record_path(digest).unlink(missing_ok=True)
        shutil.rmtree(cache_figures_path(digest), ignore_errors=True)
        return

    for directory, suffix in ((CACHE_PAPERS_DIR, ".pdf"), (CACHE_RECORDS_DIR, ".json")):
        for path in directory.glob(f"{paper_id}*{suffix}"):
            path.unlink(missing_ok=True)
    shutil.rmtree(figure_directory(CACHE_FIGURES_DIR, paper_id), ignore_errors=True)


def public_figures(paper_id: str, figures: list[dict[str, Any]]) -> list[dict[str, Any]]:
    public_items = []
    for figure in figures:
        figure_id = figure.get("id")
        if not figure_id:
            continue
        public_item = {key: value for key, value in figure.items() if key != "image_file"}
        public_item["image_url"] = f"/api/papers/{paper_id}/figures/{figure_id}/image"
        public_items.append(public_item)
    return public_items


def clean_highlight_record(highlight: dict[str, Any]) -> dict[str, Any] | None:
    snippet = " ".join(str(highlight.get("snippet", "")).split()).strip()
    if not snippet:
        return None

    label = " ".join(str(highlight.get("label", "important")).split()).strip().lower()
    if not label:
        label = "important"
    label = label[:40]

    try:
        page_number = int(highlight["page_number"]) if highlight.get("page_number") else None
    except (TypeError, ValueError):
        page_number = None

    rects = []
    if isinstance(highlight.get("rects"), list):
        for rect in highlight["rects"]:
            if not isinstance(rect, list) or len(rect) != 4:
                continue
            try:
                rects.append([round(float(value), 2) for value in rect])
            except (TypeError, ValueError):
                continue

    clean: dict[str, Any] = {
        "label": label,
        "snippet": snippet[:900],
        "reason": " ".join(str(highlight.get("reason", "")).split()).strip()[:240],
        "page_number": page_number,
        "rects": rects,
    }
    color = str(highlight.get("color", "")).strip()
    if color:
        clean["color"] = color[:24]
    return clean


def ground_clean_highlight(
    clean: dict[str, Any],
    raw_highlight: dict[str, Any],
    pdf_path: Path,
) -> dict[str, Any]:
    if not raw_highlight.get("reground") or not pdf_path.exists():
        return clean

    page_number, rects = find_exact_rects(pdf_path, clean["snippet"], clean.get("page_number"))
    if rects:
        clean["page_number"] = page_number
        clean["rects"] = rects
    return clean


def public_paper(paper: dict[str, Any], include_details: bool = False) -> dict[str, Any]:
    highlights = sort_highlights(paper.get("highlights", []))
    base = {
        "id": paper["id"],
        "filename": paper["filename"],
        "title": paper["title"],
        "overview": paper.get("overview", ""),
        "provider_used": paper.get("provider_used", "unknown"),
        "warnings": paper.get("warnings", []),
        "analysis_status": paper.get("analysis_status", "complete"),
        "analysis_error": paper.get("analysis_error", ""),
        "highlight_count": len(highlights),
        "figure_count": len(paper.get("figures", [])),
        "citation_count": len(paper.get("citations", [])),
    }
    if include_details:
        base.update(
            {
                "key_takeaways": paper.get("key_takeaways", []),
                "read_this_first": paper.get("read_this_first", []),
                "glossary": paper.get("glossary", []),
                "highlights": highlights,
                "figures": public_figures(paper["id"], paper.get("figures", [])),
                "figure_warnings": paper.get("figure_warnings", []),
                "figure_provider_used": paper.get("figure_provider_used", "unknown"),
                "citations": paper.get("citations", []),
                "questions": paper.get("questions", []),
                "page_sizes": paper.get("page_sizes", []),
            }
        )
    return base


def build_paper_record(
    pdf_path: Path,
    paper_id: str,
    filename: str,
    provider: str | None,
    digest: str,
    api_key: str | None = None,
) -> dict[str, Any]:
    extracted = extract_pdf(pdf_path)
    citations = ground_citation_rects(pdf_path, extract_citations(extracted))
    analysis = analyze_paper(pdf_path, extracted, provider, api_key)
    return {
        "id": paper_id,
        "filename": filename,
        "stored_pdf": pdf_path.name,
        "digest": digest,
        "analysis_version": ANALYSIS_VERSION,
        "title": analysis.get("title") or extracted.title,
        "overview": analysis.get("overview", ""),
        "key_takeaways": analysis.get("key_takeaways", []),
        "read_this_first": analysis.get("read_this_first", []),
        "glossary": analysis.get("glossary", []),
        "highlights": sort_highlights(analysis.get("highlights", [])),
        "figures": [],
        "figure_warnings": [],
        "figure_provider_used": "unknown",
        "citations": citations,
        "questions": analysis.get("questions", []),
        "provider_used": analysis.get("provider_used", "unknown"),
        "warnings": analysis.get("warnings", []),
        "page_sizes": public_page_sizes(extracted.pages),
        "sentences": [
            {
                "text": span.text,
                "page_number": span.page_number,
            }
            for span in extracted.sentence_spans
        ],
        "full_text_chars": len(extracted.full_text),
        "analysis_status": "complete",
        "analysis_error": "",
    }


def build_uploaded_paper_record(
    pdf_path: Path,
    paper_id: str,
    filename: str,
    digest: str,
) -> dict[str, Any]:
    extracted = extract_pdf(pdf_path)
    citations = ground_citation_rects(pdf_path, extract_citations(extracted))
    return {
        "id": paper_id,
        "filename": filename,
        "stored_pdf": pdf_path.name,
        "digest": digest,
        "analysis_version": 0,
        "title": extracted.title or Path(filename).stem,
        "overview": "PDF loaded. Click Analyze to generate takeaways and highlights.",
        "key_takeaways": [],
        "read_this_first": [],
        "glossary": [],
        "highlights": [],
        "figures": [],
        "figure_warnings": [],
        "figure_provider_used": "unknown",
        "citations": citations,
        "questions": [],
        "provider_used": "not analyzed",
        "warnings": [],
        "page_sizes": public_page_sizes(extracted.pages),
        "sentences": [
            {
                "text": span.text,
                "page_number": span.page_number,
            }
            for span in extracted.sentence_spans
        ],
        "full_text_chars": len(extracted.full_text),
        "analysis_status": "ready",
        "analysis_error": "",
    }


def finish_paper_analysis(
    pdf_path: Path,
    paper_id: str,
    filename: str,
    provider: str | None,
    digest: str,
    api_key: str | None = None,
) -> None:
    try:
        paper = build_paper_record(pdf_path, paper_id, filename, provider, digest, api_key)
    except Exception as error:
        pending = PAPERS.get(paper_id)
        if pending:
            pending["analysis_status"] = "error"
            pending["analysis_error"] = str(error)
            pending["overview"] = "Analysis failed."
        return

    existing = PAPERS.get(paper_id, {})
    paper["figures"] = existing.get("figures", [])
    paper["figure_warnings"] = existing.get("figure_warnings", [])
    paper["figure_provider_used"] = existing.get("figure_provider_used", "unknown")
    paper["citations"] = existing.get("citations") or paper.get("citations", [])
    write_paper(paper)
    cache_paper(paper, pdf_path)


@app.get("/")
def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/figures/{paper_id}")
def figures_page(request: Request, paper_id: str):
    return templates.TemplateResponse("figures.html", {"request": request, "paper_id": paper_id})


@app.get("/api/settings")
def settings():
    return provider_status()


@app.get("/api/papers")
def list_papers():
    return {"papers": [public_paper(paper) for paper in reversed(PAPERS.values())]}


@app.post("/api/papers/refresh-cache")
def refresh_papers_from_cache():
    loaded_count = restore_all_cached_papers()
    return {
        "loaded_count": loaded_count,
        "papers": [public_paper(paper) for paper in reversed(PAPERS.values())],
    }


@app.post("/api/upload")
async def upload_paper(file: UploadFile = File(...)):
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Upload a PDF file.")

    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="Uploaded PDF is empty.")

    digest = file_digest(data)
    paper_id = digest[:12]
    safe_name = f"{paper_id}-{slugify(Path(file.filename).stem)}.pdf"
    pdf_path = PAPERS_DIR / safe_name

    if paper_id in PAPERS and pdf_path.exists():
        return public_paper(PAPERS[paper_id], include_details=True)

    cached = cached_analysis(digest, paper_id, file.filename, safe_name)
    if cached:
        write_paper(cached)
        return public_paper(cached, include_details=True)

    pdf_path.write_bytes(data)

    try:
        paper = build_uploaded_paper_record(pdf_path, paper_id, file.filename, digest)
    except fitz.FileDataError as error:
        pdf_path.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail="Uploaded file is not a readable PDF.") from error

    restore_cached_figure_analysis(digest, paper_id, paper)
    write_paper(paper)
    return public_paper(paper, include_details=True)


@app.post("/api/papers/{paper_id}/analyze")
async def analyze_uploaded_paper(paper_id: str, request: AnalysisRequest):
    paper = read_paper(paper_id)
    provider = request.provider or "auto"
    if provider not in {"auto", "codex", "openai"}:
        raise HTTPException(status_code=502, detail="The local fallback provider has been removed.")
    pdf_path = PAPERS_DIR / paper["stored_pdf"]
    if not pdf_path.exists():
        raise HTTPException(status_code=404, detail="PDF file not found.")

    if paper.get("analysis_status") == "analyzing":
        return public_paper(paper, include_details=True)
    if (
        paper.get("analysis_status") == "complete"
        and paper.get("highlights")
        and paper.get("analysis_version") == ANALYSIS_VERSION
    ):
        return public_paper(paper, include_details=True)

    paper.update(
        {
            "overview": "Analysis is running.",
            "key_takeaways": [],
            "read_this_first": [],
            "glossary": [],
            "highlights": [],
            "questions": [],
            "provider_used": "pending",
            "warnings": [],
            "analysis_status": "analyzing",
            "analysis_error": "",
        }
    )
    write_paper(paper)

    asyncio.create_task(
        asyncio.to_thread(
            finish_paper_analysis,
            pdf_path,
            paper_id,
            paper["filename"],
            provider,
            paper.get("digest", ""),
            request.api_key,
        )
    )
    return public_paper(paper, include_details=True)


@app.get("/api/papers/{paper_id}")
def get_paper(paper_id: str):
    return public_paper(read_paper(paper_id), include_details=True)


@app.put("/api/papers/{paper_id}/highlights")
def update_paper_highlights(paper_id: str, request: HighlightsUpdateRequest):
    paper = read_paper(paper_id)
    pdf_path = PAPERS_DIR / str(paper.get("stored_pdf", ""))
    highlights = [
        ground_clean_highlight(clean, item, pdf_path)
        for item in request.highlights[:120]
        if (clean := clean_highlight_record(item))
    ]
    paper["highlights"] = sort_highlights(highlights)
    write_paper(paper)

    if pdf_path.exists():
        cache_paper(paper, pdf_path)

    return public_paper(paper, include_details=True)


@app.delete("/api/papers/{paper_id}")
def delete_paper(paper_id: str):
    paper = PAPERS.pop(paper_id, None)
    if not paper:
        delete_cached_paper("", paper_id)
        shutil.rmtree(figure_directory(FIGURES_DIR, paper_id), ignore_errors=True)
        return {"deleted": False}

    (PAPERS_DIR / str(paper.get("stored_pdf", ""))).unlink(missing_ok=True)
    delete_cached_paper(str(paper.get("digest", "")), paper_id)
    shutil.rmtree(figure_directory(FIGURES_DIR, paper_id), ignore_errors=True)
    return {"deleted": True}


@app.get("/api/papers/{paper_id}/file")
def get_paper_file(paper_id: str):
    paper = read_paper(paper_id)
    pdf_path = PAPERS_DIR / paper["stored_pdf"]
    if not pdf_path.exists():
        raise HTTPException(status_code=404, detail="PDF file not found.")
    return FileResponse(pdf_path, media_type="application/pdf", filename=paper["filename"])


@app.get("/api/papers/{paper_id}/figures")
def get_figures(paper_id: str):
    paper = read_paper(paper_id)
    return {
        "figures": public_figures(paper_id, paper.get("figures", [])),
        "warnings": paper.get("figure_warnings", []),
        "provider_used": paper.get("figure_provider_used", "unknown"),
    }


@app.post("/api/papers/{paper_id}/figures/analyze")
async def analyze_paper_figures(paper_id: str, request: FigureAnalysisRequest):
    paper = read_paper(paper_id)
    if paper.get("figures") and not request.force:
        return {
            "figures": public_figures(paper_id, paper.get("figures", [])),
            "warnings": paper.get("figure_warnings", []),
            "provider_used": paper.get("figure_provider_used", "unknown"),
        }

    pdf_path = PAPERS_DIR / paper["stored_pdf"]
    if not pdf_path.exists():
        raise HTTPException(status_code=404, detail="PDF file not found.")

    try:
        extracted = await asyncio.to_thread(extract_pdf, pdf_path)
        result = await asyncio.to_thread(
            analyze_figures,
            pdf_path,
            extracted,
            paper_id,
            FIGURES_DIR,
            request.provider,
            request.api_key,
        )
    except Exception as error:
        raise HTTPException(status_code=502, detail=str(error)) from error

    latest_paper = read_paper(paper_id)
    latest_paper.update(result)
    write_paper(latest_paper)
    cache_paper(latest_paper, pdf_path)
    return {
        "figures": public_figures(paper_id, latest_paper.get("figures", [])),
        "warnings": latest_paper.get("figure_warnings", []),
        "provider_used": latest_paper.get("figure_provider_used", "unknown"),
    }


@app.get("/api/papers/{paper_id}/figures/{figure_id}/image")
def get_figure_image(paper_id: str, figure_id: str):
    paper = read_paper(paper_id)
    figure = next((item for item in paper.get("figures", []) if item.get("id") == figure_id), None)
    if not figure:
        raise HTTPException(status_code=404, detail="Figure not found.")

    image_path = figure_directory(FIGURES_DIR, paper_id) / str(figure.get("image_file", ""))
    if not image_path.exists():
        raise HTTPException(status_code=404, detail="Figure image not found.")
    return FileResponse(image_path, media_type="image/jpeg")


@app.post("/api/papers/{paper_id}/chat")
async def chat_with_paper(paper_id: str, request: ChatRequest):
    paper = read_paper(paper_id)
    messages = [
        {"role": message.role, "content": message.content}
        for message in request.messages
        if message.role in {"user", "assistant"} and message.content.strip()
    ]
    if not messages:
        raise HTTPException(status_code=400, detail="Send at least one message.")

    web_results = []
    if request.use_web:
        query = messages[-1]["content"]
        try:
            web_results = await asyncio.to_thread(search_web, query, 5)
        except Exception as error:
            web_results = [{"title": "Web search failed", "url": "", "snippet": str(error)}]

    try:
        return await asyncio.to_thread(
            answer_chat,
            paper,
            messages,
            web_results,
            request.provider,
            request.citation_context,
            request.api_key,
            request.figure_context,
        )
    except Exception as error:
        raise HTTPException(status_code=502, detail=str(error)) from error


@app.post("/api/papers/{paper_id}/explain")
async def explain_selection(paper_id: str, request: SelectionExplainRequest):
    paper = read_paper(paper_id)
    selected_text = request.selected_text.strip()
    if not selected_text:
        raise HTTPException(status_code=400, detail="Select text to explain.")
    if len(selected_text) > 700:
        raise HTTPException(status_code=400, detail="Selection is too long.")

    try:
        return await asyncio.to_thread(
            answer_selection_explanation,
            paper,
            selected_text,
            request.page_number,
            request.page_text,
            request.provider,
            request.api_key,
        )
    except Exception as error:
        raise HTTPException(status_code=502, detail=str(error)) from error


@app.get("/api/search")
async def search(query: str):
    try:
        results = await asyncio.to_thread(search_web, query, 8)
    except Exception as error:
        raise HTTPException(status_code=502, detail=str(error)) from error
    return {"results": results}
