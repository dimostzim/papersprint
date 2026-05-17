# PaperSprint

PaperSprint is a local AI PDF paper reader. It loads papers in the browser, adds AI-guided reading support, and keeps a paper-aware chat beside the PDF.

## Features

- Upload and read PDFs locally.
- Generate a paper summary and takeaways.
- Show guided highlights on the PDF for goal, novelty, method, result, and limitation.
- Click citations in the paper and add the full reference-list entry to chat.
- Select text in the PDF and send it to chat for explanation.
- Chat with the current paper, with optional web search.
- Analyze figures, tables, plots, diagrams, and screenshots in a separate figures view.
- Cache analyzed papers and remove papers from the local library.

## Quick Start

```bash
cd /Users/nucleotaid/Projects/papersprint
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8788
```

Open `http://127.0.0.1:8788`.

## Figure Analysis

After loading a paper, click `Figures` to open the figures workspace. PaperSprint renders PDF pages as images and uses Codex to identify and summarize figures, tables, plots, diagrams, screenshots, and multi-panel visual evidence.

## Data And Cache

- Current-session PDFs live under `data/session`.
- Cached analyzed records and PDFs live under `data/cache`.
- The refresh button reloads papers and analysis results from `data/cache` into the current session.
- Deleting a paper removes it from the visible library and cache.
- Clearing `data/cache` forces papers to be parsed and analyzed again.
