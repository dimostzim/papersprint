import * as pdfjsLib from "https://cdnjs.cloudflare.com/ajax/libs/pdf.js/4.4.168/pdf.min.mjs";

pdfjsLib.GlobalWorkerOptions.workerSrc =
  "https://cdnjs.cloudflare.com/ajax/libs/pdf.js/4.4.168/pdf.worker.min.mjs";

const state = {
  papers: [],
  selectedPaper: null,
  settings: null,
  chatMessages: [],
  renderToken: 0,
  analysisPoll: null,
  uploadPromise: null,
  pageTexts: new Map(),
  activeSelection: null,
  activeCitation: null,
  pendingCitationContext: null,
};

const els = {
  uploadForm: document.getElementById("upload-form"),
  pdfInput: document.getElementById("pdf-input"),
  providerSelect: document.getElementById("provider-select"),
  apiKeyInput: document.getElementById("api-key-input"),
  highlightCountInput: document.getElementById("highlight-count-input"),
  figuresButton: document.getElementById("figures-button"),
  providerStatus: document.getElementById("provider-status"),
  refreshButton: document.getElementById("refresh-button"),
  paperList: document.getElementById("paper-list"),
  readerPanel: document.querySelector(".reader-panel"),
  readerEmpty: document.getElementById("reader-empty"),
  pdfViewer: document.getElementById("pdf-viewer"),
  highlightCount: document.getElementById("highlight-count"),
  highlightList: document.getElementById("highlight-list"),
  paperProvider: document.getElementById("paper-provider"),
  paperTitle: document.getElementById("paper-title"),
  paperOverview: document.getElementById("paper-overview"),
  takeawaysTab: document.getElementById("takeaways-tab"),
  chatMessages: document.getElementById("chat-messages"),
  chatForm: document.getElementById("chat-form"),
  chatInput: document.getElementById("chat-input"),
  webToggle: document.getElementById("web-toggle"),
  selectionPopover: document.getElementById("selection-popover"),
  explainSelectionButton: document.getElementById("explain-selection-button"),
  citationPopover: document.getElementById("citation-popover"),
  addCitationButton: document.getElementById("add-citation-button"),
  toast: document.getElementById("toast"),
};

function escapeHtml(value = "") {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;");
}

function truncateText(value = "", limit = 220) {
  const text = String(value).replace(/\s+/g, " ").trim();
  return text.length > limit ? `${text.slice(0, limit - 3)}...` : text;
}

function showToast(message, sticky = false) {
  if (!els.toast) {
    return;
  }
  els.toast.textContent = message;
  els.toast.classList.remove("hidden");
  if (!sticky) {
    window.setTimeout(() => els.toast.classList.add("hidden"), 3200);
  }
}

function hideToast() {
  if (!els.toast) {
    return;
  }
  els.toast.classList.add("hidden");
}

function setHtml(target, html) {
  if (!target) {
    return;
  }
  target.innerHTML = html;
}

async function requestJson(url, options = {}) {
  const response = await fetch(url, options);
  const text = await response.text();
  let payload = {};
  if (text) {
    try {
      payload = JSON.parse(text);
    } catch {
      payload = { detail: text };
    }
  }
  if (!response.ok) {
    throw new Error(payload.detail || response.statusText);
  }
  return payload;
}

function setProviderOptions(settings) {
  if (settings.default_provider && els.providerSelect) {
    els.providerSelect.value = settings.default_provider;
  }
  const parts = [];
  parts.push(settings.codex_available ? "Codex ready" : "Codex unavailable");
  parts.push(settings.openai_available ? "OpenAI key set" : "No API key");
  if (els.providerStatus) {
    els.providerStatus.textContent = parts.join(" · ");
  }
  syncApiKeyInput();
}

async function loadSettings() {
  const settings = await requestJson("/api/settings");
  state.settings = settings;
  setProviderOptions(settings);
}

function selectedProvider() {
  return els.providerSelect?.value || "auto";
}

function requestApiKey() {
  return selectedProvider() === "openai" ? els.apiKeyInput?.value.trim() || "" : "";
}

function syncApiKeyInput() {
  if (!els.apiKeyInput) {
    return;
  }
  els.apiKeyInput.classList.toggle("hidden", selectedProvider() !== "openai");
}

function requireOpenAiKey() {
  if (selectedProvider() !== "openai" || requestApiKey()) {
    return true;
  }
  showToast("Enter an OpenAI API key");
  els.apiKeyInput?.focus();
  return false;
}

async function loadPapers(selectFirst = true) {
  const payload = await requestJson("/api/papers");
  state.papers = payload.papers || [];
  if (state.selectedPaper && !state.papers.some((paper) => paper.id === state.selectedPaper.id)) {
    state.selectedPaper = null;
    syncPaperActions();
  }
  renderPaperList();
  if (selectFirst && state.papers.length && !state.selectedPaper) {
    await selectPaper(state.papers[0].id);
  } else if (!state.papers.length) {
    clearSelectedPaper();
  }
}

function renderPaperList() {
  if (!state.papers.length) {
    setHtml(els.paperList, `<div class="muted-box">No PDFs loaded</div>`);
    return;
  }

  setHtml(
    els.paperList,
    state.papers
      .map((paper) => {
      const active = state.selectedPaper?.id === paper.id ? "active" : "";
      const warning = paper.warnings?.length ? `<span class="warning-dot" title="Warnings"></span>` : "";
      const citationText = paper.citation_count ? ` · ${paper.citation_count} citations` : "";
      const statusText = paper.analysis_status === "ready"
        ? `ready to analyze${citationText}`
        : paper.analysis_status === "analyzing"
          ? "analyzing"
          : paper.analysis_status === "error"
            ? "analysis failed"
            : `${paper.highlight_count || 0} highlights${citationText} · ${escapeHtml(paper.provider_used || "unknown")}`;
      return `
        <button class="paper-card ${active}" data-paper-id="${paper.id}" type="button">
          <strong>${escapeHtml(paper.title || paper.filename)}</strong>
          <span>${statusText}</span>
          ${warning}
        </button>
      `;
      })
      .join(""),
  );

  els.paperList?.querySelectorAll("[data-paper-id]").forEach((button) => {
    button.addEventListener("click", () => selectPaper(button.dataset.paperId));
  });
}

function upsertPaperSummary(paper) {
  const summary = {
    id: paper.id,
    filename: paper.filename,
    title: paper.title,
    overview: paper.overview || "",
    provider_used: paper.provider_used || "unknown",
    warnings: paper.warnings || [],
    analysis_status: paper.analysis_status || "complete",
    analysis_error: paper.analysis_error || "",
    highlight_count: paper.highlight_count ?? paper.highlights?.length ?? 0,
    figure_count: paper.figure_count ?? paper.figures?.length ?? 0,
    citation_count: paper.citation_count ?? paper.citations?.length ?? 0,
  };
  state.papers = [summary, ...state.papers.filter((item) => item.id !== paper.id)];
}

async function selectPaper(paperId) {
  showReaderLoading();
  const paper = await requestJson(`/api/papers/${paperId}`);
  setSelectedPaper(paper);
  await renderPdf(paper);
  pollPaperAnalysis(paper.id);
}

function setSelectedPaper(paper) {
  state.selectedPaper = paper;
  state.chatMessages = [];
  state.pendingCitationContext = null;
  upsertPaperSummary(paper);
  syncPaperActions();
  renderPaperList();
  renderPaperDetails(paper);
  renderChat();
}

function clearSelectedPaper() {
  state.selectedPaper = null;
  state.chatMessages = [];
  state.pageTexts = new Map();
  state.pendingCitationContext = null;
  hideSelectionPopover();
  hideCitationPopover();
  if (state.analysisPoll) {
    window.clearTimeout(state.analysisPoll);
    state.analysisPoll = null;
  }
  syncPaperActions();
  els.readerEmpty?.classList.remove("hidden");
  els.pdfViewer?.classList.add("hidden");
  setHtml(els.pdfViewer, "");
  if (els.paperProvider) {
    els.paperProvider.textContent = "Idle";
  }
  if (els.paperTitle) {
    els.paperTitle.textContent = "Paper Reader AI";
  }
  if (els.paperOverview) {
    els.paperOverview.textContent = "";
  }
  if (els.highlightCount) {
    els.highlightCount.textContent = "0";
  }
  setHtml(els.highlightList, `<div class="muted-box">No highlights</div>`);
  renderListPanel(els.takeawaysTab, []);
  renderChat();
}

function syncPaperActions() {
  if (els.figuresButton) {
    els.figuresButton.disabled = !state.selectedPaper;
  }
}

function showReaderLoading() {
  els.readerEmpty?.classList.add("hidden");
  els.pdfViewer?.classList.remove("hidden");
  setHtml(els.pdfViewer, `<div class="loading">Loading paper</div>`);
}

function renderPaperDetails(paper) {
  if (els.paperProvider) {
    els.paperProvider.textContent = paper.provider_used || "unknown";
  }
  if (els.paperTitle) {
    els.paperTitle.textContent = paper.title || paper.filename;
  }
  if (els.paperOverview) {
    els.paperOverview.textContent = paper.overview || "";
  }
  if (els.highlightCount) {
    els.highlightCount.textContent = String(paper.highlights?.length || 0);
  }
  if (paper.analysis_status === "analyzing") {
    renderListPanel(els.takeawaysTab, ["Analysis is running. The PDF is ready to read now."]);
  } else if (paper.analysis_status === "ready") {
    renderListPanel(els.takeawaysTab, ["PDF loaded. Click Analyze when you want AI takeaways and highlights."]);
  } else if (paper.analysis_status === "error") {
    renderListPanel(els.takeawaysTab, [paper.analysis_error || "Analysis failed."]);
  } else {
    renderListPanel(els.takeawaysTab, paper.key_takeaways || []);
  }
  renderHighlights(paper.highlights || []);
}

function renderListPanel(target, items) {
  setHtml(
    target,
    items.length
      ? `<ul>${items.map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ul>`
      : `<div class="muted-box">No items</div>`,
  );
}

function renderHighlights(highlights) {
  if (!highlights.length) {
    setHtml(els.highlightList, `<div class="muted-box">No highlights</div>`);
    return;
  }

  setHtml(
    els.highlightList,
    highlights
      .map((highlight, index) => {
      const page = highlight.page_number ? `p. ${highlight.page_number}` : "unplaced";
      return `
        <button class="highlight-card" data-highlight-index="${index}" type="button">
          <span class="label label-${escapeHtml(highlight.label)}">${escapeHtml(highlight.label)}</span>
          <strong>${escapeHtml(highlight.snippet)}</strong>
          <small>${escapeHtml(page)} · ${escapeHtml(highlight.reason || "")}</small>
        </button>
      `;
      })
      .join(""),
  );

  els.highlightList?.querySelectorAll("[data-highlight-index]").forEach((button) => {
    button.addEventListener("click", () => {
      const highlight = highlights[Number(button.dataset.highlightIndex)];
      if (highlight?.page_number) {
        jumpToPage(highlight.page_number);
      }
    });
  });
}

function citationChatPrefix(citation) {
  const title = truncateText(citation.title || citation.raw_reference || "", 140);
  return title
    ? `Regarding citation ${citation.label || ""}: ${title} — `
    : `Regarding citation ${citation.label || "this citation"} — `;
}

function addCitationToChat(citation) {
  if (!citation || !els.chatInput) {
    return;
  }

  state.pendingCitationContext = citation;
  const prefix = citationChatPrefix(citation);
  if (!els.chatInput.value.includes(prefix)) {
    els.chatInput.value = `${prefix}${els.chatInput.value}`.trimEnd();
  }
  els.chatInput.focus();
  showToast("Citation added to chat");
}

function citationsByPage(citations) {
  const map = new Map();
  for (const [citationIndex, citation] of (citations || []).entries()) {
    for (const context of citation.contexts || []) {
      if (!context.page_number || !context.rects?.length) {
        continue;
      }
      const pageCitations = map.get(context.page_number) || [];
      pageCitations.push({ citation, citationIndex, context });
      map.set(context.page_number, pageCitations);
    }
  }
  return map;
}

function selectHighlight(highlightIndex) {
  els.highlightList?.querySelectorAll(".highlight-card").forEach((node) => node.classList.remove("active"));
  const card = els.highlightList?.querySelector(`[data-highlight-index="${highlightIndex}"]`);
  if (card) {
    card.classList.add("active");
    card.scrollIntoView({ behavior: "smooth", block: "center" });
  }
}

function jumpToPage(pageNumber) {
  if (!pageNumber) {
    return;
  }
  const page = els.pdfViewer?.querySelector(`[data-page-number="${pageNumber}"]`);
  if (page) {
    page.scrollIntoView({ behavior: "smooth", block: "start" });
  }
}

function highlightsByPage(highlights) {
  const map = new Map();
  for (const [index, highlight] of (highlights || []).entries()) {
    if (!highlight.page_number || !highlight.rects?.length) {
      continue;
    }
    const pageHighlights = map.get(highlight.page_number) || [];
    pageHighlights.push({ ...highlight, highlightIndex: index });
    map.set(highlight.page_number, pageHighlights);
  }
  return map;
}

async function renderPdf(paper) {
  const token = ++state.renderToken;
  state.pageTexts = new Map();
  hideSelectionPopover();
  hideCitationPopover();
  els.readerEmpty?.classList.add("hidden");
  els.pdfViewer?.classList.remove("hidden");
  setHtml(els.pdfViewer, `<div class="loading">Rendering PDF</div>`);

  const pdfDoc = await pdfjsLib.getDocument(`/api/papers/${paper.id}/file`).promise;
  const pageHighlights = highlightsByPage(paper.highlights);
  const pageCitations = citationsByPage(paper.citations);
  const pageSizes = new Map((paper.page_sizes || []).map((page) => [page.page_number, page]));
  setHtml(els.pdfViewer, "");

  for (let pageNumber = 1; pageNumber <= pdfDoc.numPages; pageNumber += 1) {
    if (token !== state.renderToken) {
      return;
    }

    const page = await pdfDoc.getPage(pageNumber);
    const baseViewport = page.getViewport({ scale: 1 });
    const maxWidth = Math.min(940, Math.max(520, (els.pdfViewer?.clientWidth || 940) - 48));
    const scale = maxWidth / baseViewport.width;
    const viewport = page.getViewport({ scale });

    const wrapper = document.createElement("div");
    wrapper.className = "pdf-page";
    wrapper.dataset.pageNumber = String(pageNumber);
    wrapper.style.width = `${viewport.width}px`;
    wrapper.style.height = `${viewport.height}px`;

    const canvas = document.createElement("canvas");
    const context = canvas.getContext("2d");
    canvas.width = Math.floor(viewport.width * window.devicePixelRatio);
    canvas.height = Math.floor(viewport.height * window.devicePixelRatio);
    canvas.style.width = `${viewport.width}px`;
    canvas.style.height = `${viewport.height}px`;
    context.scale(window.devicePixelRatio, window.devicePixelRatio);
    wrapper.appendChild(canvas);

    const textLayer = document.createElement("div");
    textLayer.className = "text-layer";
    textLayer.style.setProperty("--scale-factor", String(scale));
    wrapper.appendChild(textLayer);

    const overlay = document.createElement("div");
    overlay.className = "overlay-layer";
    wrapper.appendChild(overlay);
    els.pdfViewer?.appendChild(wrapper);

    await page.render({ canvasContext: context, viewport }).promise;
    await renderTextLayer(page, textLayer, viewport, pageNumber);
    renderPageHighlights(overlay, pageHighlights.get(pageNumber) || [], pageSizes.get(pageNumber), viewport);
    renderPageCitations(overlay, pageCitations.get(pageNumber) || [], pageSizes.get(pageNumber), viewport);
  }
}

async function renderTextLayer(page, textLayer, viewport, pageNumber) {
  const textContent = await page.getTextContent();
  const pageText = textContent.items
    .map((item) => item.str || "")
    .join(" ")
    .replace(/\s+/g, " ")
    .trim();
  state.pageTexts.set(pageNumber, pageText);

  const layer = new pdfjsLib.TextLayer({
    textContentSource: textContent,
    container: textLayer,
    viewport,
  });
  await layer.render();
}

async function renderPdfPreservingScroll(paper) {
  const scrollTop = els.readerPanel?.scrollTop || 0;
  await renderPdf(paper);
  if (els.readerPanel) {
    els.readerPanel.scrollTop = scrollTop;
  }
}

function renderPageHighlights(overlay, highlights, pageSize, viewport) {
  if (!pageSize) {
    return;
  }

  const scaleX = viewport.width / pageSize.width;
  const scaleY = viewport.height / pageSize.height;
  for (const highlight of highlights) {
    for (const rect of highlight.rects || []) {
      const [x0, y0, x1, y1] = rect;
      const node = document.createElement("div");
      node.className = `highlight-rect label-${highlight.label}`;
      node.title = `${highlight.label}: ${highlight.reason || highlight.snippet}`;
      node.dataset.highlightIndex = String(highlight.highlightIndex);
      node.style.left = `${x0 * scaleX}px`;
      node.style.top = `${y0 * scaleY}px`;
      node.style.width = `${Math.max(6, (x1 - x0) * scaleX)}px`;
      node.style.height = `${Math.max(6, (y1 - y0) * scaleY)}px`;
      node.addEventListener("click", () => selectHighlight(highlight.highlightIndex));
      overlay.appendChild(node);
    }
  }
}

function renderPageCitations(overlay, citations, pageSize, viewport) {
  if (!pageSize) {
    return;
  }

  const scaleX = viewport.width / pageSize.width;
  const scaleY = viewport.height / pageSize.height;
  for (const item of citations) {
    for (const rect of item.context.rects || []) {
      const [x0, y0, x1, y1] = rect;
      const node = document.createElement("button");
      node.className = "citation-rect";
      node.type = "button";
      node.title = `${item.citation.label || "Citation"}: ${item.citation.title || ""}`;
      node.style.left = `${x0 * scaleX}px`;
      node.style.top = `${y0 * scaleY}px`;
      node.style.width = `${Math.max(8, (x1 - x0) * scaleX)}px`;
      node.style.height = `${Math.max(8, (y1 - y0) * scaleY)}px`;
      node.addEventListener("click", (event) => {
        event.stopPropagation();
        showCitationPopover(item.citation, node.getBoundingClientRect());
      });
      overlay.appendChild(node);
    }
  }
}

async function loadSelectedPaper() {
  if (state.uploadPromise) {
    return state.uploadPromise;
  }

  const file = els.pdfInput?.files?.[0];
  if (!file) {
    showToast("Choose a PDF first");
    return null;
  }

  const formData = new FormData();
  formData.append("file", file);

  showToast(`Loading ${file.name}`, true);
  showReaderLoading();
  state.uploadPromise = requestJson("/api/upload", {
    method: "POST",
    body: formData,
  })
    .then(async (paper) => {
      hideToast();
      setSelectedPaper(paper);
      await renderPdf(paper);
      showToast("PDF loaded. Click Analyze when ready.");
      return paper;
    })
    .finally(() => {
      state.uploadPromise = null;
    });

  return state.uploadPromise;
}

async function startSelectedPaperAnalysis(event) {
  event.preventDefault();
  if (!requireOpenAiKey()) {
    return;
  }

  let paper = state.uploadPromise ? await state.uploadPromise : state.selectedPaper;
  if (!paper && els.pdfInput?.files?.[0]) {
    paper = await loadSelectedPaper();
  }
  if (!paper) {
    showToast("Choose a PDF first");
    return;
  }
  if (paper.analysis_status === "analyzing") {
    showToast("Analysis is already running");
    pollPaperAnalysis(paper.id);
    return;
  }

  showToast("Analysis is running. You can keep reading.", true);
  paper = await requestJson(`/api/papers/${paper.id}/analyze`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      provider: selectedProvider(),
      api_key: requestApiKey() || null,
      highlight_count: Number(els.highlightCountInput?.value || 15),
    }),
  });
  setSelectedPaper(paper);
  hideToast();
  showToast("Analysis started. Keep reading while it runs.");
  pollPaperAnalysis(paper.id);
}

function pollPaperAnalysis(paperId) {
  if (state.analysisPoll) {
    window.clearTimeout(state.analysisPoll);
  }
  if (!state.selectedPaper || state.selectedPaper.id !== paperId || state.selectedPaper.analysis_status !== "analyzing") {
    state.analysisPoll = null;
    return;
  }

  state.analysisPoll = window.setTimeout(async () => {
    try {
      const paper = await requestJson(`/api/papers/${paperId}`);
      if (!state.selectedPaper || state.selectedPaper.id !== paperId) {
        return;
      }
      state.selectedPaper = paper;
      upsertPaperSummary(paper);
      renderPaperList();
      renderPaperDetails(paper);
      if (paper.analysis_status === "analyzing") {
        pollPaperAnalysis(paperId);
      } else if (paper.analysis_status === "complete") {
        await renderPdfPreservingScroll(paper);
        hideToast();
        showToast("Analysis ready");
      } else if (paper.analysis_status === "error") {
        hideToast();
        showToast(paper.analysis_error || "Analysis failed");
      }
    } catch (error) {
      showToast(error.message || String(error));
    }
  }, 2500);
}

function renderChat() {
  if (!els.chatMessages) {
    return;
  }

  if (!state.chatMessages.length) {
    setHtml(els.chatMessages, `<div class="muted-box">Ask a question about this paper.</div>`);
    return;
  }

  els.chatMessages.replaceChildren();
  for (const message of state.chatMessages) {
    const role = message.role === "user" ? "user" : "assistant";
    const article = document.createElement("article");
    article.className = `chat-message ${role}`;

    const label = document.createElement("strong");
    label.textContent = role === "user" ? "You" : "Assistant";

    const body = document.createElement("p");
    appendChatText(body, message.content);

    article.append(label, body);
    els.chatMessages.appendChild(article);
  }

  els.chatMessages.scrollTop = els.chatMessages.scrollHeight;
}

function appendChatText(target, value) {
  const text = String(value);
  const urlPattern = /https?:\/\/[^\s<>"']+/g;
  let cursor = 0;

  for (const match of text.matchAll(urlPattern)) {
    appendTextSegment(target, text.slice(cursor, match.index));

    const link = document.createElement("a");
    link.href = match[0];
    link.target = "_blank";
    link.rel = "noreferrer";
    link.textContent = match[0];
    target.appendChild(link);

    cursor = match.index + match[0].length;
  }

  appendTextSegment(target, text.slice(cursor));
}

function appendTextSegment(target, text) {
  const lines = text.split("\n");
  lines.forEach((line, index) => {
    if (index > 0) {
      target.appendChild(document.createElement("br"));
    }
    if (line) {
      target.appendChild(document.createTextNode(line));
    }
  });
}

function selectedTextFromPdf() {
  const selection = window.getSelection();
  if (!selection || selection.isCollapsed || selection.rangeCount === 0) {
    return null;
  }

  const text = selection.toString().replace(/\s+/g, " ").trim();
  if (text.length < 2 || text.length > 700) {
    return null;
  }

  const range = selection.getRangeAt(0);
  const container = range.commonAncestorContainer.nodeType === Node.ELEMENT_NODE
    ? range.commonAncestorContainer
    : range.commonAncestorContainer.parentElement;
  const page = container?.closest?.(".pdf-page");
  if (!page) {
    return null;
  }

  const rect = range.getBoundingClientRect();
  if (!rect.width && !rect.height) {
    return null;
  }

  const pageNumber = Number(page.dataset.pageNumber) || null;
  return {
    text,
    pageNumber,
    pageText: state.pageTexts.get(pageNumber) || "",
    rect,
  };
}

function showSelectionPopover() {
  const selection = selectedTextFromPdf();
  if (!selection || !els.selectionPopover) {
    hideSelectionPopover();
    return;
  }
  hideCitationPopover();

  state.activeSelection = {
    text: selection.text,
    pageNumber: selection.pageNumber,
    pageText: selection.pageText,
  };

  const popover = els.selectionPopover;
  popover.classList.remove("hidden");
  const top = Math.max(8, selection.rect.top - popover.offsetHeight - 8);
  const left = Math.min(
    window.innerWidth - popover.offsetWidth - 8,
    Math.max(8, selection.rect.left + selection.rect.width / 2 - popover.offsetWidth / 2),
  );
  popover.style.top = `${top}px`;
  popover.style.left = `${left}px`;
}

function hideSelectionPopover() {
  state.activeSelection = null;
  els.selectionPopover?.classList.add("hidden");
}

function showCitationPopover(citation, rect) {
  if (!citation || !els.citationPopover) {
    hideCitationPopover();
    return;
  }

  hideSelectionPopover();
  state.activeCitation = citation;
  const popover = els.citationPopover;
  popover.classList.remove("hidden");
  const top = Math.max(8, rect.top - popover.offsetHeight - 8);
  const left = Math.min(
    window.innerWidth - popover.offsetWidth - 8,
    Math.max(8, rect.left + rect.width / 2 - popover.offsetWidth / 2),
  );
  popover.style.top = `${top}px`;
  popover.style.left = `${left}px`;
}

function hideCitationPopover() {
  state.activeCitation = null;
  els.citationPopover?.classList.add("hidden");
}

async function explainActiveSelection() {
  if (!state.selectedPaper || !state.activeSelection) {
    hideSelectionPopover();
    return;
  }
  if (!requireOpenAiKey()) {
    return;
  }

  const selection = state.activeSelection;
  hideSelectionPopover();
  window.getSelection()?.removeAllRanges();

  const label = selection.pageNumber ? `p. ${selection.pageNumber}` : "selected text";
  const userMessage = `Explain "${selection.text}" (${label})`;
  state.chatMessages.push({ role: "user", content: userMessage });
  const pending = { role: "assistant", content: "Explaining..." };
  state.chatMessages.push(pending);
  renderChat();

  const payload = await requestJson(`/api/papers/${state.selectedPaper.id}/explain`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      selected_text: selection.text,
      page_number: selection.pageNumber,
      page_text: selection.pageText,
      provider: selectedProvider(),
      api_key: requestApiKey() || null,
    }),
  });

  pending.content = payload.answer || "No explanation returned.";
  renderChat();
}

async function sendChatMessage(content, forceWeb = false, citationContext = null) {
  if (!state.selectedPaper) {
    showToast("Select a paper first");
    return;
  }
  if (!requireOpenAiKey()) {
    return;
  }
  if (!citationContext && state.selectedPaper.analysis_status === "analyzing") {
    showToast("Analysis is still running");
    return;
  }
  if (!citationContext && state.selectedPaper.analysis_status !== "complete") {
    showToast("Analyze this paper before chatting");
    return;
  }

  state.chatMessages.push({ role: "user", content });
  renderChat();
  if (els.chatInput) {
    els.chatInput.value = "";
  }

  const pending = { role: "assistant", content: "Thinking..." };
  state.chatMessages.push(pending);
  renderChat();

  const payload = await requestJson(`/api/papers/${state.selectedPaper.id}/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      messages: state.chatMessages.filter((message) => message.content !== "Thinking..."),
      use_web: citationContext ? Boolean(forceWeb) : forceWeb || els.webToggle.checked,
      provider: selectedProvider(),
      api_key: requestApiKey() || null,
      citation_context: citationContext,
    }),
  });

  pending.content = payload.answer || "No answer returned.";
  if (payload.warnings?.length) {
    pending.content += `\n\n${payload.warnings.join("\n")}`;
  }
  if (citationContext && state.pendingCitationContext?.id === citationContext.id) {
    state.pendingCitationContext = null;
  }
  renderChat();
}

function openFiguresPage() {
  if (!state.selectedPaper) {
    showToast("Select a paper first");
    return;
  }

  window.open(`/figures/${state.selectedPaper.id}`, "_blank", "noopener,noreferrer");
}

els.uploadForm?.addEventListener("submit", (event) => {
  startSelectedPaperAnalysis(event).catch((error) => {
    hideToast();
    showToast(error.message || String(error));
  });
});

els.pdfInput?.addEventListener("change", () => {
  loadSelectedPaper().catch((error) => {
    hideToast();
    showToast(error.message || String(error));
  });
});

els.providerSelect?.addEventListener("change", syncApiKeyInput);

els.pdfViewer?.addEventListener("mouseup", () => {
  window.setTimeout(showSelectionPopover, 0);
});

els.pdfViewer?.addEventListener("keyup", () => {
  window.setTimeout(showSelectionPopover, 0);
});

els.selectionPopover?.addEventListener("mousedown", (event) => {
  event.preventDefault();
});

els.explainSelectionButton?.addEventListener("click", () => {
  explainActiveSelection().catch((error) => {
    state.chatMessages.push({ role: "assistant", content: error.message || String(error) });
    renderChat();
  });
});

document.addEventListener("mousedown", (event) => {
  if (!els.selectionPopover?.contains(event.target) && !els.pdfViewer?.contains(event.target)) {
    hideSelectionPopover();
  }
  if (!els.citationPopover?.contains(event.target) && !event.target.closest?.(".citation-rect")) {
    hideCitationPopover();
  }
});

els.citationPopover?.addEventListener("mousedown", (event) => {
  event.preventDefault();
});

els.addCitationButton?.addEventListener("click", () => {
  addCitationToChat(state.activeCitation);
  hideCitationPopover();
});

els.refreshButton?.addEventListener("click", () => {
  loadPapers(false).catch((error) => showToast(error.message || String(error)));
});

els.figuresButton?.addEventListener("click", () => {
  openFiguresPage();
});

els.chatForm?.addEventListener("submit", (event) => {
  event.preventDefault();
  const content = els.chatInput?.value.trim() || "";
  if (!content) {
    return;
  }
  sendChatMessage(content, false, state.pendingCitationContext).catch((error) => {
    state.chatMessages.push({ role: "assistant", content: error.message || String(error) });
    renderChat();
  });
});

loadSettings()
  .then(() => loadPapers())
  .catch((error) => showToast(error.message || String(error)));
