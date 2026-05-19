# PaperSprint

PaperSprint is a local AI PDF paper reader. It loads papers in the browser, adds AI-guided reading support, and keeps a paper-aware chat beside the PDF.

## Features

- Local browser PDF reader with multi-PDF upload, a compact paper list, dark mode, PDF zoom, and collapsible left/right panels.
- AI text analysis with overview, beginner-friendly background notes, takeaways, glossary terms, and guided highlights.
- Guided highlight categories for problem, solution, novelty, method, benchmarking, result, ablation, hyperparams, tradeoff, limitation, and failure. Categories appear only when useful evidence exists.
- PDF highlight interactions: click a highlight to jump/select it, read the short AI comment, explain it in chat, or remove it.
- Manual highlighting: select PDF text to copy, explain in chat, add a highlight, reuse an existing category, or create a new category color.
- Citation parsing and grounding during Analyze for author-year citations, numeric citations, and citation ranges. Clicking a citation opens the full reference-list entry and can add it to chat.
- Takeaways and summary panels that stay beside the PDF while you read.
- Paper-aware chat with optional web search, citation context, figure/table context, reset-and-send, Enter to send, and Shift+Enter for a new line.
- Figure and table analysis after text analysis. Visuals are annotated directly in the PDF as results arrive and can be opened, moved, and added to chat.
- Provider controls for Codex subscription, OpenAI API, and OpenRouter API, with separate text/vision model and reasoning-effort selectors.
- Local cache for parsed papers, analyses, citations, figures, and figure images. Refresh reloads papers and results from cache, and deletion removes the paper from the library and cache.

## Quick Start

```bash
git clone git@github.com:dimostzim/PaperSprint.git
cd PaperSprint
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m uvicorn app.main:app --host 127.0.0.1 --port 8788
```

Open `http://127.0.0.1:8788`.

PaperSprint can use a logged-in Codex CLI subscription by default. API keys are optional:

```bash
export OPENAI_API_KEY="sk-..."        # optional
export OPENROUTER_API_KEY="sk-or-..." # optional
```

## Data And Cache

- Current-session PDFs and figure images live under `data/session`.
- Cached paper records, PDFs, and figure images live under `data/cache`.
- The refresh button reloads papers and analysis results from `data/cache` into the current session.
- If a session PDF is missing but the cached PDF exists, PaperSprint restores it automatically.
- Deleting a paper removes it from the visible library and cache.
- Clearing `data/cache` forces papers to be parsed and analyzed again.
