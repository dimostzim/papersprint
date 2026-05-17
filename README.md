# Paper Reader AI

Local-first Semantic Reader-style MVP for reading papers faster.

## What works

- Upload a PDF from the browser.
- View the PDF with highlighted AI-selected passages.
- Read summary, takeaways, and figures.
- Keep uploaded papers only for the current server session.
- Analyze figures, plots, diagrams, screenshots, and tables from rendered page images with Codex CLI vision support or an OpenAI vision-capable model.
- Chat with the paper in a side panel.
- Toggle web search in chat for external context.
- Use `codex` CLI subscription or an OpenAI API key.

## Quick Start

```bash
cd /Users/nucleotaid/Projects/paper-reader-ai
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --host 127.0.0.1 --port 8787
```

Open `http://127.0.0.1:8787`.

## AI Providers

The default `AI_PROVIDER=auto` chooses:

1. `openai` if `OPENAI_API_KEY` is set.
2. `codex` if the `codex` CLI is installed and logged in.

If neither provider is available, analysis and chat fail with a clear error instead of producing heuristic output.

ChatGPT consumer subscriptions do not expose a direct programmatic API. The `codex` provider is the practical local subscription path because it calls `codex exec` non-interactively.

## Notes

- Text-based PDFs work best. Scanned image PDFs need OCR, which is not part of this MVP.
- Highlight grounding uses exact PDF text search first, then approximate sentence matching.
- Uploaded papers and analyses are stored in memory plus `data/session` only while the server is running; restarting clears them.
- Figure analysis renders PDF pages to JPEG. The figures page uses the Codex CLI provider, and the backend can also use OpenAI with `OPENAI_VISION_MODEL`.
- Future parser upgrade: replace the PyMuPDF extraction layer with PaperMage for richer figures, captions, and document structure.
