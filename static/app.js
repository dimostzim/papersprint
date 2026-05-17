import * as pdfjsLib from "https://cdnjs.cloudflare.com/ajax/libs/pdf.js/4.4.168/pdf.min.mjs";

pdfjsLib.GlobalWorkerOptions.workerSrc =
  "https://cdnjs.cloudflare.com/ajax/libs/pdf.js/4.4.168/pdf.worker.min.mjs";

const HIGHLIGHT_FACETS = [
  { id: "all", label: "All" },
  { id: "goal", label: "Goal" },
  { id: "novelty", label: "Novelty" },
  { id: "method", label: "Method" },
  { id: "result", label: "Result" },
  { id: "limitation", label: "Limitation" },
];

const DEFAULT_HIGHLIGHT_COLORS = {
  goal: "#72c9e8",
  method: "#8ed6a8",
  novelty: "#b8a8ea",
  result: "#ffd36d",
  limitation: "#e99797",
  important: "#b6bec3",
};

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
  activeHighlightIndex: null,
  pendingCitationContext: null,
  activeHighlightFacet: "all",
};

const els = {
  uploadForm: document.getElementById("upload-form"),
  pdfInput: document.getElementById("pdf-input"),
  providerSelect: document.getElementById("provider-select"),
  apiKeyInput: document.getElementById("api-key-input"),
  analyzeButton: document.getElementById("analyze-button"),
  figuresButton: document.getElementById("figures-button"),
  providerStatus: document.getElementById("provider-status"),
  refreshButton: document.getElementById("refresh-button"),
  paperList: document.getElementById("paper-list"),
  assistantPanel: document.querySelector(".assistant-panel"),
  chatResizeHandle: document.getElementById("chat-resize-handle"),
  readerPanel: document.querySelector(".reader-panel"),
  readerEmpty: document.getElementById("reader-empty"),
  pdfViewer: document.getElementById("pdf-viewer"),
  highlightCount: document.getElementById("highlight-count"),
  highlightFilters: document.getElementById("highlight-filters"),
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
  addSelectionHighlightButton: document.getElementById("add-selection-highlight-button"),
  selectionHighlightForm: document.getElementById("selection-highlight-form"),
  highlightCategorySelect: document.getElementById("highlight-category-select"),
  highlightCategoryInput: document.getElementById("highlight-category-input"),
  highlightColorInput: document.getElementById("highlight-color-input"),
  highlightPopover: document.getElementById("highlight-popover"),
  citationPopover: document.getElementById("citation-popover"),
  toast: document.getElementById("toast"),
};

function escapeHtml(value = "") {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function highlightLabelId(value = "") {
  return String(value || "important")
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "") || "important";
}

function safeHexColor(value) {
  const color = String(value || "").trim();
  return /^#[0-9a-f]{6}$/i.test(color) ? color : "";
}

function hexToRgba(hex, alpha) {
  const color = safeHexColor(hex);
  if (!color) {
    return "";
  }
  const value = Number.parseInt(color.slice(1), 16);
  const red = (value >> 16) & 255;
  const green = (value >> 8) & 255;
  const blue = value & 255;
  return `rgba(${red}, ${green}, ${blue}, ${alpha})`;
}

function highlightColor(highlight) {
  return safeHexColor(highlight?.color) || DEFAULT_HIGHLIGHT_COLORS[highlightLabelId(highlight?.label)] || "";
}

function customHighlightStyle(highlight) {
  const color = highlightColor(highlight);
  if (!color || !safeHexColor(highlight?.color)) {
    return "";
  }
  return ` style="background: ${hexToRgba(color, 0.24)}; color: var(--ink);"`;
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

function setLoadingButton(button, isLoading, label) {
  if (!button) {
    return;
  }
  button.classList.toggle("is-loading", isLoading);
  button.setAttribute("aria-busy", isLoading ? "true" : "false");
  const labelNode = button.querySelector(".button-label");
  if (labelNode) {
    labelNode.textContent = label;
  } else {
    button.textContent = label;
  }
}

function resizeChatInput() {
  if (!els.chatInput) {
    return;
  }

  const style = window.getComputedStyle(els.chatInput);
  const lineHeight = Number.parseFloat(style.lineHeight) || Number.parseFloat(style.fontSize) * 1.35 || 18;
  const verticalPadding = Number.parseFloat(style.paddingTop) + Number.parseFloat(style.paddingBottom);
  const verticalBorder = Number.parseFloat(style.borderTopWidth) + Number.parseFloat(style.borderBottomWidth);
  const maxHeight = Math.ceil(lineHeight * 5 + verticalPadding + verticalBorder);

  els.chatInput.style.height = "auto";
  els.chatInput.style.height = `${Math.min(els.chatInput.scrollHeight + verticalBorder, maxHeight)}px`;
  els.chatInput.style.overflowY = els.chatInput.scrollHeight + verticalBorder > maxHeight ? "auto" : "hidden";
}

function setChatPanelSplit(clientY) {
  if (!els.assistantPanel || !els.chatResizeHandle) {
    return;
  }

  const panelRect = els.assistantPanel.getBoundingClientRect();
  const handleHeight = els.chatResizeHandle.getBoundingClientRect().height || 8;
  const minSummaryHeight = 130;
  const minChatHeight = 180;
  const maxSummaryHeight = Math.max(minSummaryHeight, panelRect.height - handleHeight - minChatHeight);
  const nextSummaryHeight = Math.min(
    maxSummaryHeight,
    Math.max(minSummaryHeight, clientY - panelRect.top),
  );
  els.assistantPanel.style.setProperty("--summary-panel-height", `${Math.round(nextSummaryHeight)}px`);
}

function currentSummaryPanelHeight() {
  const summaryPanel = els.assistantPanel?.querySelector(".summary-panel");
  return summaryPanel?.getBoundingClientRect().height || 0;
}

function startChatPanelResize(event) {
  if (!els.assistantPanel) {
    return;
  }

  event.preventDefault();
  els.assistantPanel.classList.add("is-resizing");
  const pointerId = event.pointerId;
  els.chatResizeHandle?.setPointerCapture?.(pointerId);
  setChatPanelSplit(event.clientY);

  const onPointerMove = (moveEvent) => {
    setChatPanelSplit(moveEvent.clientY);
  };
  const onPointerUp = () => {
    els.assistantPanel?.classList.remove("is-resizing");
    els.chatResizeHandle?.releasePointerCapture?.(pointerId);
    window.removeEventListener("pointermove", onPointerMove);
    window.removeEventListener("pointerup", onPointerUp);
  };

  window.addEventListener("pointermove", onPointerMove);
  window.addEventListener("pointerup", onPointerUp, { once: true });
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
  await applyPaperSummaries(payload.papers || [], selectFirst);
}

async function applyPaperSummaries(papers, selectFirst = true) {
  state.papers = papers;
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

async function refreshPapersFromCache() {
  showToast("Loading cached papers", true);
  const selectedId = state.selectedPaper?.id || null;
  const payload = await requestJson("/api/papers/refresh-cache", { method: "POST" });
  await applyPaperSummaries(payload.papers || [], false);

  const nextId = selectedId && state.papers.some((paper) => paper.id === selectedId)
    ? selectedId
    : state.papers[0]?.id;
  if (nextId) {
    await selectPaper(nextId);
  } else {
    clearSelectedPaper();
  }

  hideToast();
  showToast(`Loaded ${payload.loaded_count || 0} cached paper${payload.loaded_count === 1 ? "" : "s"}`);
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
        <article class="paper-card ${active}">
          <button class="paper-card-main" data-paper-id="${paper.id}" type="button">
            <strong>${escapeHtml(paper.title || paper.filename)}</strong>
            <span>${statusText}</span>
          </button>
          <button class="paper-remove-button" data-remove-paper-id="${paper.id}" title="Remove paper" type="button" aria-label="Remove paper">
            ×
          </button>
          ${warning}
        </article>
      `;
      })
      .join(""),
  );

  els.paperList?.querySelectorAll("[data-paper-id]").forEach((button) => {
    button.addEventListener("click", () => selectPaper(button.dataset.paperId));
  });
  els.paperList?.querySelectorAll("[data-remove-paper-id]").forEach((button) => {
    button.addEventListener("click", (event) => {
      event.stopPropagation();
      removePaper(button.dataset.removePaperId).catch((error) => showToast(error.message || String(error)));
    });
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

async function removePaper(paperId) {
  if (!paperId) {
    return;
  }

  await requestJson(`/api/papers/${paperId}`, { method: "DELETE" });
  state.papers = state.papers.filter((paper) => paper.id !== paperId);
  if (state.selectedPaper?.id === paperId) {
    clearSelectedPaper();
    if (state.papers.length) {
      await selectPaper(state.papers[0].id);
    } else {
      renderPaperList();
    }
  } else {
    renderPaperList();
  }
  showToast("Paper removed");
}

function setSelectedPaper(paper) {
  state.selectedPaper = paper;
  state.chatMessages = [];
  state.pendingCitationContext = null;
  state.activeHighlightIndex = null;
  state.activeHighlightFacet = "all";
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
  state.activeHighlightFacet = "all";
  hideSelectionPopover();
  hideCitationPopover();
  hideHighlightPopover();
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
    els.paperTitle.textContent = "PaperSprint";
  }
  if (els.paperOverview) {
    els.paperOverview.textContent = "";
  }
  if (els.highlightCount) {
    els.highlightCount.textContent = "0";
  }
  setHtml(els.highlightList, `<div class="muted-box">No highlights</div>`);
  renderHighlightFilters([]);
  renderListPanel(els.takeawaysTab, []);
  renderChat();
}

function syncPaperActions() {
  const isAnalyzing = state.selectedPaper?.analysis_status === "analyzing";
  setLoadingButton(els.analyzeButton, Boolean(isAnalyzing), isAnalyzing ? "Analyzing" : "Analyze");
  if (els.analyzeButton) {
    els.analyzeButton.disabled = Boolean(isAnalyzing);
  }
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
  const highlights = paper.highlights || [];
  if (
    state.activeHighlightFacet !== "all"
    && !highlights.some((highlight) => highlight.label === state.activeHighlightFacet)
  ) {
    state.activeHighlightFacet = "all";
  }
  const visibleHighlights = filteredHighlights(highlights);
  if (els.highlightCount) {
    els.highlightCount.textContent = state.activeHighlightFacet === "all"
      ? String(highlights.length)
      : `${visibleHighlights.length}/${highlights.length}`;
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
  renderHighlightFilters(highlights);
  renderHighlights(visibleHighlights);
}

function filteredHighlights(highlights) {
  return (highlights || [])
    .map((highlight, index) => ({ ...highlight, highlightIndex: index }))
    .filter((highlight) => state.activeHighlightFacet === "all" || highlight.label === state.activeHighlightFacet);
}

function highlightCategoryOptions(highlights) {
  const options = HIGHLIGHT_FACETS
    .filter((facet) => facet.id !== "all")
    .map((facet) => ({
      id: facet.id,
      label: facet.label,
      color: DEFAULT_HIGHLIGHT_COLORS[facet.id] || "",
    }));
  const seen = new Set(options.map((option) => option.id));
  for (const highlight of highlights || []) {
    const id = String(highlight.label || "").trim();
    if (!id || seen.has(id)) {
      continue;
    }
    seen.add(id);
    options.push({
      id,
      label: id,
      color: highlightColor(highlight) || DEFAULT_HIGHLIGHT_COLORS.important,
    });
  }
  return options;
}

function renderHighlightFilters(highlights) {
  if (!els.highlightFilters) {
    return;
  }

  const counts = new Map();
  for (const highlight of highlights || []) {
    counts.set(highlight.label, (counts.get(highlight.label) || 0) + 1);
  }
  const facets = [
    HIGHLIGHT_FACETS[0],
    ...highlightCategoryOptions(highlights),
  ];

  setHtml(
    els.highlightFilters,
    facets.map((facet) => {
      const count = facet.id === "all" ? (highlights || []).length : counts.get(facet.id) || 0;
      const active = state.activeHighlightFacet === facet.id ? "active" : "";
      return `
        <button class="facet-chip ${active}" data-highlight-facet="${facet.id}" type="button">
          ${escapeHtml(facet.label)}
          <span>${count}</span>
        </button>
      `;
    }).join(""),
  );

  els.highlightFilters.querySelectorAll("[data-highlight-facet]").forEach((button) => {
    button.addEventListener("click", async () => {
      state.activeHighlightFacet = button.dataset.highlightFacet || "all";
      if (!state.selectedPaper) {
        return;
      }
      renderPaperDetails(state.selectedPaper);
      await renderPdfPreservingScroll(state.selectedPaper);
    });
  });
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
      const highlightIndex = highlight.highlightIndex ?? index;
      const labelId = highlightLabelId(highlight.label);
      return `
        <button class="highlight-card" data-highlight-index="${highlightIndex}" type="button">
          <span class="label label-${escapeHtml(labelId)}"${customHighlightStyle(highlight)}>${escapeHtml(highlight.label)}</span>
          <strong>${escapeHtml(highlight.snippet)}</strong>
          <small>${escapeHtml(page)} · ${escapeHtml(highlight.reason || "")}</small>
        </button>
      `;
      })
      .join(""),
  );

  els.highlightList?.querySelectorAll("[data-highlight-index]").forEach((button) => {
    button.addEventListener("click", () => {
      const highlightIndex = Number(button.dataset.highlightIndex);
      const highlight = (state.selectedPaper?.highlights || [])[highlightIndex];
      selectHighlight(highlightIndex);
      if (highlight?.page_number) {
        jumpToPage(highlight.page_number);
      }
    });
  });
}

function normalizeCitationReference(value) {
  return String(value || "").replace(/\s+/g, " ").trim();
}

function citationChatText(citation) {
  const rawReferences = Array.isArray(citation.raw_references)
    ? citation.raw_references.map(normalizeCitationReference).filter(Boolean)
    : [normalizeCitationReference(citation.raw_reference)].filter(Boolean);
  if (rawReferences.length) {
    return rawReferences.join("\n");
  }

  const parts = [
    citation.authors,
    citation.title,
    citation.year,
  ]
    .map(normalizeCitationReference)
    .filter(Boolean);
  if (parts.length) {
    return parts.join(". ");
  }

  const context = citation.contexts?.[0]?.sentence || "";
  return [citation.label, context]
    .map((value) => String(value || "").replace(/\s+/g, " ").trim())
    .filter(Boolean)
    .join(" ");
}

function addCitationToChat(citation) {
  if (!citation || !els.chatInput) {
    return;
  }

  state.pendingCitationContext = citation;
  const citationText = citationChatText(citation);
  if (citationText && !els.chatInput.value.includes(citationText)) {
    els.chatInput.value = [els.chatInput.value.trim(), citationText].filter(Boolean).join("\n");
  }
  resizeChatInput();
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

function citationRectKey(rect) {
  return (rect || []).map((value) => Number(value).toFixed(2)).join(",");
}

function citationGroupLabel(item) {
  return normalizeCitationReference(item.context?.marker || item.citation?.label || "Citation");
}

function groupedCitationRects(citations) {
  const groups = new Map();
  for (const item of citations) {
    for (const rect of item.context.rects || []) {
      const label = citationGroupLabel(item);
      const key = `${item.context.page_number || ""}|${label}|${citationRectKey(rect)}`;
      if (!groups.has(key)) {
        groups.set(key, { label, rect, items: [] });
      }
      groups.get(key).items.push(item);
    }
  }
  return Array.from(groups.values());
}

function uniqueValues(values) {
  const seen = new Set();
  const result = [];
  for (const value of values) {
    const normalized = normalizeCitationReference(value);
    if (!normalized || seen.has(normalized)) {
      continue;
    }
    seen.add(normalized);
    result.push(normalized);
  }
  return result;
}

function uniqueCitationItems(items) {
  const seen = new Set();
  const result = [];
  for (const item of items) {
    const citation = item.citation || {};
    const key = normalizeCitationReference(citation.id || citation.raw_reference || citation.label || citation.title);
    if (!key || seen.has(key)) {
      continue;
    }
    seen.add(key);
    result.push(item);
  }
  return result;
}

function citationContextKey(context) {
  return [
    context.page_number || "",
    context.marker || "",
    normalizeCitationReference(context.sentence || ""),
  ].join("|");
}

function citationChoiceTitle(citation) {
  return normalizeCitationReference(citation.raw_reference || citation.title || citation.label || "Citation");
}

function citationChoiceMeta(citation) {
  return [
    citation.label,
    citation.year,
  ]
    .map(normalizeCitationReference)
    .filter(Boolean)
    .join(" · ");
}

function citationForGroup(group) {
  const uniqueItems = uniqueCitationItems(group.items);
  if (uniqueItems.length === 1) {
    return uniqueItems[0].citation;
  }

  const firstCitation = uniqueItems[0]?.citation || {};
  const references = uniqueValues(uniqueItems.map((item) => item.citation?.raw_reference || ""));
  const titles = uniqueValues(uniqueItems.map((item) => item.citation?.title || ""));
  const contexts = [];
  const seenContexts = new Set();
  for (const item of group.items) {
    const key = citationContextKey(item.context);
    if (!seenContexts.has(key)) {
      seenContexts.add(key);
      contexts.push(item.context);
    }
  }

  return {
    ...firstCitation,
    id: `citation-group-${group.label}-${references.join("|")}`,
    label: group.label,
    title: titles.length ? `${group.label} (${titles.length} references)` : group.label,
    authors: "",
    year: "",
    raw_reference: references.join("\n"),
    raw_references: references,
    grouped_citations: uniqueItems.map((item) => item.citation),
    contexts,
    resolved: uniqueItems.every((item) => item.citation?.resolved),
  };
}

function selectHighlight(highlightIndex) {
  els.highlightList?.querySelectorAll(".highlight-card").forEach((node) => node.classList.remove("active"));
  els.pdfViewer?.querySelectorAll(".highlight-rect").forEach((node) => node.classList.remove("active"));
  const card = els.highlightList?.querySelector(`[data-highlight-index="${highlightIndex}"]`);
  if (card) {
    card.classList.add("active");
    card.scrollIntoView({ behavior: "smooth", block: "center" });
  }
  els.pdfViewer?.querySelectorAll(`[data-highlight-index="${highlightIndex}"]`).forEach((node) => {
    node.classList.add("active");
  });
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
    pageHighlights.push({ ...highlight, highlightIndex: highlight.highlightIndex ?? index });
    map.set(highlight.page_number, pageHighlights);
  }
  return map;
}

async function renderPdf(paper) {
  const token = ++state.renderToken;
  state.pageTexts = new Map();
  hideSelectionPopover();
  hideCitationPopover();
  hideHighlightPopover();
  els.readerEmpty?.classList.add("hidden");
  els.pdfViewer?.classList.remove("hidden");
  setHtml(els.pdfViewer, `<div class="loading">Rendering PDF</div>`);

  const pdfDoc = await pdfjsLib.getDocument(`/api/papers/${paper.id}/file`).promise;
  const pageHighlights = highlightsByPage(filteredHighlights(paper.highlights || []));
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
    const labelId = highlightLabelId(highlight.label);
    const color = highlightColor(highlight);
    for (const rect of highlight.rects || []) {
      const [x0, y0, x1, y1] = rect;
      const node = document.createElement("div");
      node.className = `highlight-rect label-${labelId}`;
      node.title = `${highlight.label}: ${highlight.reason || highlight.snippet}`;
      node.dataset.highlightIndex = String(highlight.highlightIndex);
      if (safeHexColor(highlight.color) && color) {
        node.style.background = color;
      }
      node.style.left = `${x0 * scaleX}px`;
      node.style.top = `${y0 * scaleY}px`;
      node.style.width = `${Math.max(6, (x1 - x0) * scaleX)}px`;
      node.style.height = `${Math.max(6, (y1 - y0) * scaleY)}px`;
      node.addEventListener("click", (event) => {
        event.stopPropagation();
        showHighlightPopover(highlight.highlightIndex, node.getBoundingClientRect());
      });
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
  for (const group of groupedCitationRects(citations)) {
    const [x0, y0, x1, y1] = group.rect;
    const citation = citationForGroup(group);
    const referenceCount = citation.grouped_citations?.length || 1;
    const node = document.createElement("button");
    node.className = "citation-rect";
    node.type = "button";
    node.title = referenceCount > 1
      ? `${group.label}: ${referenceCount} references`
      : `${citation.label || "Citation"}: ${citation.title || ""}`;
    node.style.left = `${x0 * scaleX}px`;
    node.style.top = `${y0 * scaleY}px`;
    node.style.width = `${Math.max(8, (x1 - x0) * scaleX)}px`;
    node.style.height = `${Math.max(8, (y1 - y0) * scaleY)}px`;
    node.addEventListener("click", (event) => {
      event.stopPropagation();
      showCitationPopover(citation, node.getBoundingClientRect());
    });
    overlay.appendChild(node);
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
  syncPaperActions();
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

function pageSizeFor(pageNumber) {
  return (state.selectedPaper?.page_sizes || []).find((page) => page.page_number === pageNumber);
}

function roundRectValue(value) {
  return Math.round(value * 100) / 100;
}

function selectionRectsForPage(range, page, pageNumber) {
  const pageSize = pageSizeFor(pageNumber);
  if (!pageSize) {
    return [];
  }

  const pageRect = page.getBoundingClientRect();
  const scaleX = pageSize.width / pageRect.width;
  const scaleY = pageSize.height / pageRect.height;
  return Array.from(range.getClientRects())
    .map((rect) => {
      const left = Math.max(rect.left, pageRect.left);
      const top = Math.max(rect.top, pageRect.top);
      const right = Math.min(rect.right, pageRect.right);
      const bottom = Math.min(rect.bottom, pageRect.bottom);
      if (right - left < 2 || bottom - top < 2) {
        return null;
      }
      return [
        roundRectValue((left - pageRect.left) * scaleX),
        roundRectValue((top - pageRect.top) * scaleY),
        roundRectValue((right - pageRect.left) * scaleX),
        roundRectValue((bottom - pageRect.top) * scaleY),
      ];
    })
    .filter(Boolean);
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
  const rects = selectionRectsForPage(range, page, pageNumber);
  if (!rects.length) {
    return null;
  }
  return {
    text,
    pageNumber,
    pageText: state.pageTexts.get(pageNumber) || "",
    rect,
    rects,
  };
}

function renderSelectionHighlightCategories() {
  if (!els.highlightCategorySelect) {
    return;
  }

  const options = highlightCategoryOptions(state.selectedPaper?.highlights || []);
  setHtml(
    els.highlightCategorySelect,
    `${options
      .map((option) => `<option value="${escapeHtml(option.id)}">${escapeHtml(option.label)}</option>`)
      .join("")}
      <option value="__new__">New category</option>`,
  );

  const preferred = state.activeHighlightFacet !== "all" ? state.activeHighlightFacet : "goal";
  els.highlightCategorySelect.value = options.some((option) => option.id === preferred)
    ? preferred
    : options[0]?.id || "__new__";
  syncSelectionHighlightForm();
}

function resetSelectionHighlightForm() {
  els.selectionHighlightForm?.classList.add("hidden");
  if (els.highlightCategoryInput) {
    els.highlightCategoryInput.value = "";
  }
  if (els.highlightColorInput) {
    els.highlightColorInput.value = DEFAULT_HIGHLIGHT_COLORS.important;
  }
  renderSelectionHighlightCategories();
}

function syncSelectionHighlightForm() {
  const isNewCategory = els.highlightCategorySelect?.value === "__new__";
  els.highlightCategoryInput?.classList.toggle("hidden", !isNewCategory);
  els.highlightColorInput?.classList.toggle("hidden", !isNewCategory);
  if (isNewCategory) {
    els.highlightCategoryInput?.focus();
  }
}

function showSelectionPopover() {
  const selection = selectedTextFromPdf();
  if (!selection || !els.selectionPopover) {
    hideSelectionPopover();
    return;
  }
  hideCitationPopover();
  hideHighlightPopover();

  state.activeSelection = {
    text: selection.text,
    pageNumber: selection.pageNumber,
    pageText: selection.pageText,
    rects: selection.rects,
  };
  resetSelectionHighlightForm();

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
  els.selectionHighlightForm?.classList.add("hidden");
  els.selectionPopover?.classList.add("hidden");
}

function renderHighlightPopover(highlight) {
  setHtml(
    els.highlightPopover,
    `
      <div class="highlight-popover-label">
        <span class="label label-${escapeHtml(highlightLabelId(highlight?.label))}"${customHighlightStyle(highlight)}>${escapeHtml(highlight?.label || "highlight")}</span>
      </div>
      <button data-remove-highlight type="button">Remove</button>
    `,
  );
}

function showHighlightPopover(highlightIndex, rect) {
  if (!state.selectedPaper || !els.highlightPopover) {
    return;
  }

  const highlight = (state.selectedPaper.highlights || [])[highlightIndex];
  if (!highlight) {
    hideHighlightPopover();
    return;
  }

  window.getSelection()?.removeAllRanges();
  hideSelectionPopover();
  hideCitationPopover();
  state.activeHighlightIndex = highlightIndex;
  selectHighlight(highlightIndex);
  renderHighlightPopover(highlight);

  const popover = els.highlightPopover;
  popover.classList.remove("hidden");
  const top = Math.max(8, rect.top - popover.offsetHeight - 8);
  const left = Math.min(
    window.innerWidth - popover.offsetWidth - 8,
    Math.max(8, rect.left + rect.width / 2 - popover.offsetWidth / 2),
  );
  popover.style.top = `${top}px`;
  popover.style.left = `${left}px`;
}

function hideHighlightPopover() {
  state.activeHighlightIndex = null;
  els.highlightPopover?.classList.add("hidden");
}

function renderCitationPopover(citation) {
  const choices = citation.grouped_citations?.length ? citation.grouped_citations : [citation];

  setHtml(
    els.citationPopover,
    `
      <div class="citation-choice-list">
        ${choices
          .map((choice, index) => `
            <button class="citation-choice" data-citation-choice="${index}" type="button">
              <span>${escapeHtml(citationChoiceMeta(choice))}</span>
              <strong>${escapeHtml(citationChoiceTitle(choice))}</strong>
            </button>
          `)
          .join("")}
      </div>
    `,
  );
}

function showCitationPopover(citation, rect) {
  if (!citation || !els.citationPopover) {
    hideCitationPopover();
    return;
  }

  hideSelectionPopover();
  hideHighlightPopover();
  state.activeCitation = citation;
  renderCitationPopover(citation);
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

function applySelectedPaperUpdate(paper) {
  state.selectedPaper = paper;
  upsertPaperSummary(paper);
  syncPaperActions();
  renderPaperList();
  renderPaperDetails(paper);
}

async function saveHighlights(highlights, message) {
  if (!state.selectedPaper) {
    return;
  }

  const paper = await requestJson(`/api/papers/${state.selectedPaper.id}/highlights`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ highlights }),
  });
  applySelectedPaperUpdate(paper);
  await renderPdfPreservingScroll(paper);
  showToast(message);
}

function selectedHighlightCategory() {
  const value = els.highlightCategorySelect?.value || "goal";
  if (value !== "__new__") {
    const option = highlightCategoryOptions(state.selectedPaper?.highlights || [])
      .find((item) => item.id === value);
    return {
      label: value,
      color: option && !DEFAULT_HIGHLIGHT_COLORS[highlightLabelId(value)] ? option.color : "",
    };
  }

  const label = String(els.highlightCategoryInput?.value || "")
    .replace(/\s+/g, " ")
    .trim()
    .toLowerCase();
  return {
    label,
    color: safeHexColor(els.highlightColorInput?.value) || DEFAULT_HIGHLIGHT_COLORS.important,
  };
}

async function addActiveSelectionHighlight() {
  if (!state.selectedPaper || !state.activeSelection) {
    hideSelectionPopover();
    return;
  }

  const category = selectedHighlightCategory();
  if (!category.label) {
    showToast("Name the new category");
    els.highlightCategoryInput?.focus();
    return;
  }

  const highlight = {
    label: category.label,
    snippet: state.activeSelection.text,
    reason: "manual",
    page_number: state.activeSelection.pageNumber,
    rects: state.activeSelection.rects || [],
  };
  if (category.color) {
    highlight.color = category.color;
  }

  const highlights = [...(state.selectedPaper.highlights || []), highlight];
  hideSelectionPopover();
  window.getSelection()?.removeAllRanges();
  await saveHighlights(highlights, "Highlight added");
}

async function removeActiveHighlight() {
  if (!state.selectedPaper || state.activeHighlightIndex === null) {
    hideHighlightPopover();
    return;
  }

  const highlights = (state.selectedPaper.highlights || [])
    .filter((_, index) => index !== state.activeHighlightIndex);
  hideHighlightPopover();
  await saveHighlights(highlights, "Highlight removed");
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
    resizeChatInput();
  }

  const pending = { role: "assistant", content: "Thinking..." };
  state.chatMessages.push(pending);
  renderChat();

  const payload = await requestJson(`/api/papers/${state.selectedPaper.id}/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      messages: state.chatMessages.filter((message) => message.content !== "Thinking..."),
      use_web: forceWeb || Boolean(els.webToggle?.checked),
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
  event.stopPropagation();
});

els.explainSelectionButton?.addEventListener("click", () => {
  explainActiveSelection().catch((error) => {
    state.chatMessages.push({ role: "assistant", content: error.message || String(error) });
    renderChat();
  });
});

els.addSelectionHighlightButton?.addEventListener("click", () => {
  renderSelectionHighlightCategories();
  els.selectionHighlightForm?.classList.remove("hidden");
});

els.highlightCategorySelect?.addEventListener("change", syncSelectionHighlightForm);

els.selectionHighlightForm?.addEventListener("submit", (event) => {
  event.preventDefault();
  addActiveSelectionHighlight().catch((error) => showToast(error.message || String(error)));
});

document.addEventListener("mousedown", (event) => {
  if (!els.selectionPopover?.contains(event.target) && !els.pdfViewer?.contains(event.target)) {
    hideSelectionPopover();
  }
  if (!els.citationPopover?.contains(event.target) && !event.target.closest?.(".citation-rect")) {
    hideCitationPopover();
  }
  if (!els.highlightPopover?.contains(event.target) && !event.target.closest?.(".highlight-rect")) {
    hideHighlightPopover();
  }
});

els.citationPopover?.addEventListener("mousedown", (event) => {
  event.preventDefault();
});

els.highlightPopover?.addEventListener("mousedown", (event) => {
  event.preventDefault();
});

els.highlightPopover?.addEventListener("click", (event) => {
  if (event.target.closest?.("[data-remove-highlight]")) {
    removeActiveHighlight().catch((error) => showToast(error.message || String(error)));
  }
});

els.citationPopover?.addEventListener("click", (event) => {
  const choiceButton = event.target.closest?.("[data-citation-choice]");
  if (choiceButton) {
    const choices = state.activeCitation?.grouped_citations?.length
      ? state.activeCitation.grouped_citations
      : [state.activeCitation];
    addCitationToChat(choices[Number(choiceButton.dataset.citationChoice)]);
    hideCitationPopover();
  }
});

els.refreshButton?.addEventListener("click", () => {
  refreshPapersFromCache().catch((error) => {
    hideToast();
    showToast(error.message || String(error));
  });
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

els.chatInput?.addEventListener("input", resizeChatInput);
resizeChatInput();

els.chatResizeHandle?.addEventListener("pointerdown", startChatPanelResize);
els.chatResizeHandle?.addEventListener("keydown", (event) => {
  if (!["ArrowUp", "ArrowDown"].includes(event.key)) {
    return;
  }

  event.preventDefault();
  const direction = event.key === "ArrowUp" ? -1 : 1;
  const panelTop = els.assistantPanel?.getBoundingClientRect().top || 0;
  setChatPanelSplit(panelTop + currentSummaryPanelHeight() + direction * 24);
});

loadSettings()
  .then(() => loadPapers())
  .catch((error) => showToast(error.message || String(error)));
