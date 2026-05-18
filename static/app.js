import * as pdfjsLib from "https://cdnjs.cloudflare.com/ajax/libs/pdf.js/4.4.168/pdf.min.mjs";

pdfjsLib.GlobalWorkerOptions.workerSrc =
  "https://cdnjs.cloudflare.com/ajax/libs/pdf.js/4.4.168/pdf.worker.min.mjs";

const HIGHLIGHT_FACETS = [
  { id: "all", label: "All" },
  { id: "problem", label: "Problem" },
  { id: "solution", label: "Solution" },
  { id: "novelty", label: "Novelty" },
  { id: "method", label: "Method" },
  { id: "benchmarking", label: "Benchmarking" },
  { id: "result", label: "Result" },
  { id: "ablation", label: "Ablation" },
  { id: "compute", label: "Compute" },
  { id: "tradeoff", label: "Tradeoff" },
  { id: "limitation", label: "Limitation" },
  { id: "failure", label: "Failure" },
];

const DEFAULT_HIGHLIGHT_COLORS = {
  goal: "#72c9e8",
  problem: "#72c9e8",
  solution: "#4fb07a",
  method: "#8ed6a8",
  novelty: "#b8a8ea",
  benchmarking: "#6fb4e8",
  result: "#ffd36d",
  ablation: "#caa66a",
  compute: "#8fa0a8",
  tradeoff: "#f0a36f",
  limitation: "#e99797",
  failure: "#d86969",
  important: "#b6bec3",
};

const PDF_ZOOM_MIN = 0.6;
const PDF_ZOOM_MAX = 2.4;
const PDF_ZOOM_STEP = 0.1;
const MODEL_SETTINGS_KEY = "papersprint.modelSettings";

const state = {
  papers: [],
  selectedPaper: null,
  settings: null,
  chatMessages: [],
  renderToken: 0,
  analysisPoll: null,
  uploadPromise: null,
  pageTexts: new Map(),
  pageWords: new Map(),
  textSelectionDrag: null,
  activeSelection: null,
  activeCitation: null,
  activeHighlightIndex: null,
  pendingCitationContext: null,
  activeFigure: null,
  activeHighlightFacet: "all",
  pdfZoom: 1,
  leftPanelCollapsed: false,
  rightPanelCollapsed: false,
  figureAnalysisRunning: false,
  selectedFigures: [],
};

const els = {
  workspace: document.querySelector(".workspace"),
  uploadForm: document.getElementById("upload-form"),
  pdfInput: document.getElementById("pdf-input"),
  providerSelect: document.getElementById("provider-select"),
  textModelInput: document.getElementById("text-model-input"),
  textEffortSelect: document.getElementById("text-effort-select"),
  visionModelInput: document.getElementById("vision-model-input"),
  visionEffortSelect: document.getElementById("vision-effort-select"),
  modelOptions: document.getElementById("model-options"),
  apiKeyInput: document.getElementById("api-key-input"),
  analyzeButton: document.getElementById("analyze-button"),
  figuresButton: document.getElementById("figures-button"),
  providerStatus: document.getElementById("provider-status"),
  refreshButton: document.getElementById("refresh-button"),
  paperList: document.getElementById("paper-list"),
  assistantPanel: document.querySelector(".assistant-panel"),
  leftPanelToggle: document.getElementById("left-panel-toggle"),
  rightPanelToggle: document.getElementById("right-panel-toggle"),
  chatResizeHandle: document.getElementById("chat-resize-handle"),
  readerPanel: document.querySelector(".reader-panel"),
  readerEmpty: document.getElementById("reader-empty"),
  pdfViewer: document.getElementById("pdf-viewer"),
  pdfZoomControls: document.getElementById("pdf-zoom-controls"),
  pdfZoomOutButton: document.getElementById("pdf-zoom-out-button"),
  pdfZoomInButton: document.getElementById("pdf-zoom-in-button"),
  pdfZoomLabel: document.getElementById("pdf-zoom-label"),
  highlightCount: document.getElementById("highlight-count"),
  highlightFilters: document.getElementById("highlight-filters"),
  highlightList: document.getElementById("highlight-list"),
  paperProvider: document.getElementById("paper-provider"),
  paperTitle: document.getElementById("paper-title"),
  paperOverview: document.getElementById("paper-overview"),
  backgroundSection: document.getElementById("background-section"),
  backgroundNotes: document.getElementById("background-notes"),
  takeawaysTab: document.getElementById("takeaways-tab"),
  takeawaysResizeHandle: document.getElementById("takeaways-resize-handle"),
  notShownSection: document.getElementById("not-shown-section"),
  notShownList: document.getElementById("not-shown-list"),
  codeSection: document.getElementById("code-section"),
  codeList: document.getElementById("code-list"),
  reviewerSection: document.getElementById("reviewer-section"),
  reviewerQuestions: document.getElementById("reviewer-questions"),
  chatFigureFocus: document.getElementById("chat-figure-focus"),
  chatMessages: document.getElementById("chat-messages"),
  chatForm: document.getElementById("chat-form"),
  chatInput: document.getElementById("chat-input"),
  webToggle: document.getElementById("web-toggle"),
  selectionPopover: document.getElementById("selection-popover"),
  explainSelectionButton: document.getElementById("explain-selection-button"),
  addSelectionHighlightButton: document.getElementById("add-selection-highlight-button"),
  selectionHighlightForm: document.getElementById("selection-highlight-form"),
  highlightTextInput: document.getElementById("highlight-text-input"),
  highlightCategorySelect: document.getElementById("highlight-category-select"),
  highlightCategoryInput: document.getElementById("highlight-category-input"),
  highlightColorInput: document.getElementById("highlight-color-input"),
  highlightPopover: document.getElementById("highlight-popover"),
  figurePopover: document.getElementById("figure-popover"),
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

function facetChipStyle(facet) {
  const color = safeHexColor(facet?.color);
  if (!color) {
    return "";
  }
  return ` style="--facet-color: ${color}; --facet-bg: ${hexToRgba(color, 0.26)};"`;
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

function submitChatOnEnter(event) {
  if (event.key !== "Enter" || event.shiftKey || event.isComposing) {
    return;
  }
  event.preventDefault();
  els.chatForm?.requestSubmit();
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

function setTakeawaysHeight(clientY) {
  if (!els.takeawaysTab) {
    return;
  }

  const panelRect = els.takeawaysTab.getBoundingClientRect();
  const nextHeight = clamp(clientY - panelRect.top, 90, 520);
  els.takeawaysTab.style.setProperty("--takeaways-panel-height", `${Math.round(nextHeight)}px`);
}

function currentTakeawaysHeight() {
  return els.takeawaysTab?.getBoundingClientRect().height || 230;
}

function startTakeawaysResize(event) {
  if (!els.takeawaysTab) {
    return;
  }

  event.preventDefault();
  els.takeawaysTab.classList.add("is-resizing");
  const pointerId = event.pointerId;
  els.takeawaysResizeHandle?.setPointerCapture?.(pointerId);
  setTakeawaysHeight(event.clientY);

  const onPointerMove = (moveEvent) => {
    setTakeawaysHeight(moveEvent.clientY);
  };
  const onPointerUp = () => {
    els.takeawaysTab?.classList.remove("is-resizing");
    els.takeawaysResizeHandle?.releasePointerCapture?.(pointerId);
    window.removeEventListener("pointermove", onPointerMove);
    window.removeEventListener("pointerup", onPointerUp);
  };

  window.addEventListener("pointermove", onPointerMove);
  window.addEventListener("pointerup", onPointerUp, { once: true });
}

function resetPaperViewport() {
  window.scrollTo(0, 0);
  if (els.readerPanel) {
    els.readerPanel.scrollTop = 0;
    els.readerPanel.scrollLeft = 0;
  }
  if (els.pdfViewer) {
    els.pdfViewer.scrollTop = 0;
  }
  if (els.chatMessages) {
    els.chatMessages.scrollTop = 0;
  }
}

function clampPdfZoom(value) {
  const rounded = Math.round(Number(value) * 10) / 10;
  return Math.min(PDF_ZOOM_MAX, Math.max(PDF_ZOOM_MIN, rounded || 1));
}

function pdfScrollAnchor() {
  const scroller = els.readerPanel;
  if (!scroller) {
    return null;
  }
  return {
    leftRatio: (scroller.scrollLeft + scroller.clientWidth / 2) / Math.max(1, scroller.scrollWidth),
    topRatio: (scroller.scrollTop + scroller.clientHeight / 2) / Math.max(1, scroller.scrollHeight),
  };
}

function restorePdfScrollAnchor(anchor) {
  const scroller = els.readerPanel;
  if (!scroller || !anchor) {
    return;
  }
  scroller.scrollLeft = Math.max(0, anchor.leftRatio * scroller.scrollWidth - scroller.clientWidth / 2);
  scroller.scrollTop = Math.max(0, anchor.topRatio * scroller.scrollHeight - scroller.clientHeight / 2);
}

function syncPdfZoomControls() {
  const hasPaper = Boolean(state.selectedPaper);
  els.pdfZoomControls?.classList.toggle("hidden", !hasPaper);
  if (els.pdfZoomLabel) {
    els.pdfZoomLabel.textContent = `${Math.round(state.pdfZoom * 100)}%`;
  }
  if (els.pdfZoomOutButton) {
    els.pdfZoomOutButton.disabled = !hasPaper || state.pdfZoom <= PDF_ZOOM_MIN;
  }
  if (els.pdfZoomInButton) {
    els.pdfZoomInButton.disabled = !hasPaper || state.pdfZoom >= PDF_ZOOM_MAX;
  }
}

function syncPanelToggles() {
  els.workspace?.classList.toggle("left-panel-collapsed", state.leftPanelCollapsed);
  els.workspace?.classList.toggle("right-panel-collapsed", state.rightPanelCollapsed);

  if (els.leftPanelToggle) {
    const label = state.leftPanelCollapsed ? "Show left panel" : "Hide left panel";
    els.leftPanelToggle.textContent = state.leftPanelCollapsed ? "›" : "‹";
    els.leftPanelToggle.title = label;
    els.leftPanelToggle.setAttribute("aria-label", label);
    els.leftPanelToggle.setAttribute("aria-pressed", String(state.leftPanelCollapsed));
  }

  if (els.rightPanelToggle) {
    const label = state.rightPanelCollapsed ? "Show right panel" : "Hide right panel";
    els.rightPanelToggle.textContent = state.rightPanelCollapsed ? "‹" : "›";
    els.rightPanelToggle.title = label;
    els.rightPanelToggle.setAttribute("aria-label", label);
    els.rightPanelToggle.setAttribute("aria-pressed", String(state.rightPanelCollapsed));
  }
}

async function setPdfZoom(nextZoom) {
  if (!state.selectedPaper) {
    return;
  }
  const zoom = clampPdfZoom(nextZoom);
  if (zoom === state.pdfZoom) {
    return;
  }
  state.pdfZoom = zoom;
  syncPdfZoomControls();
  await renderPdfPreservingScroll(state.selectedPaper);
  syncPdfZoomControls();
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

function storedModelSettings() {
  try {
    return JSON.parse(window.localStorage.getItem(MODEL_SETTINGS_KEY) || "{}");
  } catch {
    return {};
  }
}

function saveModelSettings() {
  const settings = {
    textModel: selectedTextModel(),
    textEffort: selectedTextEffort(),
    visionModel: selectedVisionModel(),
    visionEffort: selectedVisionEffort(),
  };
  window.localStorage.setItem(MODEL_SETTINGS_KEY, JSON.stringify(settings));
}

function populateEffortSelect(select, efforts, selected, prefix) {
  if (!select) {
    return;
  }
  setHtml(
    select,
    efforts.map((effort) => {
      const isSelected = effort === selected ? " selected" : "";
      return `<option value="${escapeHtml(effort)}"${isSelected}>${escapeHtml(prefix)}: ${escapeHtml(effort)}</option>`;
    }).join(""),
  );
}

function populateModelOptions(settings) {
  if (!els.modelOptions) {
    return;
  }

  const models = [
    settings.default_text_model,
    settings.default_vision_model,
    ...(settings.model_options || []),
  ]
    .map((model) => String(model || "").trim())
    .filter(Boolean);
  const uniqueModels = Array.from(new Set(models));
  setHtml(
    els.modelOptions,
    uniqueModels.map((model) => `<option value="${escapeHtml(model)}"></option>`).join(""),
  );
}

function setModelOptions(settings) {
  const stored = storedModelSettings();
  const efforts = settings.reasoning_efforts?.length
    ? settings.reasoning_efforts
    : ["none", "low", "medium", "high", "xhigh"];
  const textEffort = stored.textEffort || settings.default_reasoning_effort || "high";
  const visionEffort = stored.visionEffort || settings.default_vision_reasoning_effort || textEffort;
  if (els.textModelInput) {
    els.textModelInput.value = stored.textModel || settings.default_text_model || "gpt-5.5";
    els.textModelInput.placeholder = "Text model";
    els.textModelInput.title = "Text model";
  }
  if (els.visionModelInput) {
    els.visionModelInput.value = stored.visionModel || settings.default_vision_model || selectedTextModel();
    els.visionModelInput.placeholder = "Vision model";
    els.visionModelInput.title = "Vision model";
  }
  populateModelOptions(settings);
  populateEffortSelect(els.textEffortSelect, efforts, textEffort, "Text");
  populateEffortSelect(els.visionEffortSelect, efforts, visionEffort, "Vision");
}

function setProviderOptions(settings) {
  if (settings.default_provider && els.providerSelect) {
    els.providerSelect.value = settings.default_provider;
  }
  setModelOptions(settings);
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

function selectedTextModel() {
  return els.textModelInput?.value.trim() || state.settings?.default_text_model || "gpt-5.5";
}

function selectedVisionModel() {
  return els.visionModelInput?.value.trim() || state.settings?.default_vision_model || selectedTextModel();
}

function selectedTextEffort() {
  return els.textEffortSelect?.value || state.settings?.default_reasoning_effort || "high";
}

function selectedVisionEffort() {
  return els.visionEffortSelect?.value || state.settings?.default_vision_reasoning_effort || selectedTextEffort();
}

function textModelRequestOptions() {
  return {
    model: selectedTextModel(),
    reasoning_effort: selectedTextEffort(),
  };
}

function visionModelRequestOptions() {
  return {
    model: selectedVisionModel(),
    reasoning_effort: selectedVisionEffort(),
  };
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

function paperSummary(paper) {
  return {
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
}

function upsertPaperSummary(paper) {
  const summary = paperSummary(paper);
  const existingIndex = state.papers.findIndex((item) => item.id === paper.id);
  if (existingIndex === -1) {
    state.papers = [summary, ...state.papers];
    return;
  }

  state.papers = state.papers.map((item, index) => (index === existingIndex ? summary : item));
}

function prependPaperSummaries(papers) {
  const summaries = [];
  const seen = new Set();
  for (const paper of papers) {
    if (!paper?.id || seen.has(paper.id)) {
      continue;
    }
    seen.add(paper.id);
    summaries.push(paperSummary(paper));
  }

  state.papers = [
    ...summaries,
    ...state.papers.filter((paper) => !seen.has(paper.id)),
  ];
}

async function selectPaper(paperId) {
  resetPaperViewport();
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
  state.selectedFigures = [];
  state.activeFigure = null;
  state.activeHighlightIndex = null;
  state.activeHighlightFacet = "all";
  upsertPaperSummary(paper);
  syncPaperActions();
  renderPaperList();
  renderPaperDetails(paper);
  renderChat();
  renderChatFigureFocus();
}

function clearSelectedPaper() {
  state.selectedPaper = null;
  state.chatMessages = [];
  state.pageTexts = new Map();
  state.pageWords = new Map();
  state.textSelectionDrag = null;
  state.pendingCitationContext = null;
  state.selectedFigures = [];
  state.activeFigure = null;
  state.activeHighlightFacet = "all";
  hideSelectionPopover();
  hideCitationPopover();
  hideFigurePopover();
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
  renderBackgroundNotes([]);
  renderOptionalSummaryList(els.notShownSection, els.notShownList, []);
  renderOptionalSummaryList(els.codeSection, els.codeList, []);
  renderOptionalSummaryList(els.reviewerSection, els.reviewerQuestions, []);
  syncPdfZoomControls();
  if (els.highlightCount) {
    els.highlightCount.textContent = "0";
  }
  setHtml(els.highlightList, `<div class="muted-box">No highlights</div>`);
  renderHighlightFilters([]);
  renderListPanel(els.takeawaysTab, []);
  renderChat();
  renderChatFigureFocus();
}

function syncPaperActions() {
  const isAnalyzing = state.selectedPaper?.analysis_status === "analyzing";
  syncPdfZoomControls();
  setLoadingButton(els.analyzeButton, Boolean(isAnalyzing), isAnalyzing ? "Analyzing" : "Analyze");
  setLoadingButton(els.figuresButton, state.figureAnalysisRunning, state.figureAnalysisRunning ? "Analyzing" : "Figures");
  if (els.analyzeButton) {
    els.analyzeButton.disabled = Boolean(isAnalyzing);
  }
  if (els.figuresButton) {
    els.figuresButton.disabled = !state.selectedPaper || state.figureAnalysisRunning;
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
  renderBackgroundNotes(paper.background_notes || []);
  renderOptionalSummaryList(els.notShownSection, els.notShownList, paper.not_shown || [], true);
  renderOptionalSummaryList(els.codeSection, els.codeList, paper.code_availability || [], true);
  renderOptionalSummaryList(els.reviewerSection, els.reviewerQuestions, paper.reviewer_questions || [], true);
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
    renderListPanel(els.takeawaysTab, paper.key_takeaways || [], { linkEvidence: true });
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
      const hasColor = safeHexColor(facet.color) ? "has-color" : "";
      return `
        <button class="facet-chip ${active} ${hasColor}" data-highlight-facet="${escapeHtml(facet.id)}" type="button"${facetChipStyle(facet)}>
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

function summaryItemText(item) {
  if (item && typeof item === "object") {
    return String(item.text || item.takeaway || item.summary || "").trim();
  }
  return String(item || "").trim();
}

function summaryItemEvidenceHint(item) {
  if (!item || typeof item !== "object") {
    return "";
  }
  return String(item.evidence_hint || item.evidence || item.evidence_snippet || "").trim();
}

const SUMMARY_STOP_WORDS = new Set([
  "about",
  "after",
  "also",
  "because",
  "before",
  "being",
  "between",
  "could",
  "from",
  "into",
  "paper",
  "show",
  "shows",
  "that",
  "their",
  "there",
  "these",
  "this",
  "through",
  "using",
  "with",
  "would",
]);

function summaryTokens(value) {
  return new Set(
    String(value || "")
      .toLowerCase()
      .match(/[a-z][a-z0-9-]{2,}/g)
      ?.filter((token) => !SUMMARY_STOP_WORDS.has(token)) || [],
  );
}

function summaryEvidenceScore(item, highlight) {
  const evidenceHint = summaryItemEvidenceHint(item);
  const text = summaryItemText(item);
  const highlightText = [highlight.snippet, highlight.comment, highlight.reason].filter(Boolean).join(" ");
  if (evidenceHint && highlight.snippet?.toLowerCase().includes(evidenceHint.toLowerCase().slice(0, 80))) {
    return 1;
  }

  const itemTokens = summaryTokens([evidenceHint, text].filter(Boolean).join(" "));
  const highlightTokens = summaryTokens(highlightText);
  if (!itemTokens.size || !highlightTokens.size) {
    return 0;
  }

  let shared = 0;
  for (const token of itemTokens) {
    if (highlightTokens.has(token)) {
      shared += 1;
    }
  }
  return shared / itemTokens.size;
}

function evidenceHighlightIndexForItem(item) {
  const highlights = state.selectedPaper?.highlights || [];
  let bestIndex = null;
  let bestScore = 0;
  highlights.forEach((highlight, index) => {
    if (!highlight.page_number || !highlight.rects?.length) {
      return;
    }
    const score = summaryEvidenceScore(item, highlight);
    if (score > bestScore) {
      bestScore = score;
      bestIndex = index;
    }
  });
  return bestScore >= 0.18 ? bestIndex : null;
}

function renderListPanel(target, items, options = {}) {
  const values = (items || []).filter((item) => summaryItemText(item));
  setHtml(
    target,
    values.length
      ? `<ul>${values.map((item) => {
        const text = summaryItemText(item);
        const highlightIndex = options.linkEvidence ? evidenceHighlightIndexForItem(item) : null;
        const evidenceButton = highlightIndex === null
          ? ""
          : `<button class="summary-proof-button" data-summary-highlight-index="${highlightIndex}" type="button">Text</button>`;
        return `<li class="${evidenceButton ? "has-proof" : ""}"><span>${escapeHtml(text)}</span>${evidenceButton}</li>`;
      }).join("")}</ul>`
      : `<div class="muted-box">No items</div>`,
  );
  target?.querySelectorAll("[data-summary-highlight-index]").forEach((button) => {
    button.addEventListener("click", () => jumpToHighlight(Number(button.dataset.summaryHighlightIndex)));
  });
}

function renderBackgroundNotes(notes) {
  const items = notes || [];
  els.backgroundSection?.classList.toggle("hidden", !items.length);
  if (els.backgroundNotes) {
    renderListPanel(els.backgroundNotes, items);
  }
}

function renderOptionalSummaryList(section, target, items, linkEvidence = false) {
  const values = items || [];
  section?.classList.toggle("hidden", !values.length);
  if (target) {
    renderListPanel(target, values, { linkEvidence });
  }
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
        const comment = highlight.comment
          ? `<p class="highlight-comment">${escapeHtml(highlight.comment)}</p>`
          : "";
        return `
        <button class="highlight-card" data-highlight-index="${highlightIndex}" type="button">
          <span class="label label-${escapeHtml(labelId)}"${customHighlightStyle(highlight)}>${escapeHtml(highlight.label)}</span>
          <strong>${escapeHtml(highlight.snippet)}</strong>
          ${comment}
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

function isFigureSelected(figureId) {
  return state.selectedFigures.some((figure) => figure.id === figureId);
}

function syncSelectedFigures() {
  const figures = state.selectedPaper?.figures || [];
  state.selectedFigures = state.selectedFigures
    .map((figure) => figures.find((item) => item.id === figure.id))
    .filter(Boolean);
}

function selectedFigureContext() {
  return state.selectedFigures.map((figure) => ({
    id: figure.id,
    page_number: figure.page_number,
    type: figure.type,
    label: figure.label,
    title: figure.title,
    caption: figure.caption,
    explanation: figure.explanation,
    why_it_matters: figure.why_it_matters,
    uncertainty: figure.uncertainty,
  }));
}

function renderChatFigureFocus() {
  if (!els.chatFigureFocus) {
    return;
  }
  if (!state.selectedFigures.length) {
    els.chatFigureFocus.classList.add("hidden");
    setHtml(els.chatFigureFocus, "");
    return;
  }

  els.chatFigureFocus.classList.remove("hidden");
  setHtml(
    els.chatFigureFocus,
    state.selectedFigures
      .map((figure) => `
        <span class="figure-focus-chip">
          <span>${escapeHtml(figureTitle(figure))}</span>
          <button data-remove-chat-figure="${escapeHtml(figure.id)}" type="button" aria-label="Remove figure">×</button>
        </span>
      `)
      .join(""),
  );
  els.chatFigureFocus.querySelectorAll("[data-remove-chat-figure]").forEach((button) => {
    button.addEventListener("click", () => {
      state.selectedFigures = state.selectedFigures.filter((figure) => figure.id !== button.dataset.removeChatFigure);
      renderChatFigureFocus();
    });
  });
}

function addFigureToChat(figure) {
  if (!figure?.id || isFigureSelected(figure.id)) {
    return;
  }
  state.selectedFigures.push(figure);
  renderChatFigureFocus();
  els.chatInput?.focus();
  showToast("Figure added to chat");
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
  state.activeHighlightIndex = highlightIndex;
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

function jumpToHighlight(highlightIndex) {
  const highlight = (state.selectedPaper?.highlights || [])[highlightIndex];
  if (!highlight) {
    return;
  }
  selectHighlight(highlightIndex);
  const rect = els.pdfViewer?.querySelector(`[data-highlight-index="${highlightIndex}"]`);
  if (rect) {
    rect.scrollIntoView({ behavior: "smooth", block: "center", inline: "nearest" });
    return;
  }
  if (highlight.page_number) {
    jumpToPage(highlight.page_number);
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
    pageHighlights.push({ ...highlight, highlightIndex: highlight.highlightIndex ?? index });
    map.set(highlight.page_number, pageHighlights);
  }
  return map;
}

function figuresByPage(figures) {
  const map = new Map();
  for (const figure of figures || []) {
    if (!figure?.page_number || !Array.isArray(figure.bbox_pct)) {
      continue;
    }
    const pageFigures = map.get(figure.page_number) || [];
    pageFigures.push(figure);
    map.set(figure.page_number, pageFigures);
  }
  return map;
}

async function renderPdf(paper) {
  const token = ++state.renderToken;
  state.pageTexts = new Map();
  state.pageWords = new Map();
  state.textSelectionDrag = null;
  hideSelectionPopover();
  hideCitationPopover();
  hideFigurePopover();
  hideHighlightPopover();
  els.readerEmpty?.classList.add("hidden");
  els.pdfViewer?.classList.remove("hidden");
  setHtml(els.pdfViewer, `<div class="loading">Rendering PDF</div>`);

  const pdfDoc = await pdfjsLib.getDocument(`/api/papers/${paper.id}/file`).promise;
  const pageHighlights = highlightsByPage(filteredHighlights(paper.highlights || []));
  const pageCitations = citationsByPage(paper.citations);
  const pageFigures = figuresByPage(paper.figures || []);
  const pageSizes = new Map((paper.page_sizes || []).map((page) => [page.page_number, page]));

  const pages = [];
  const pageFragment = document.createDocumentFragment();
  for (let pageNumber = 1; pageNumber <= pdfDoc.numPages; pageNumber += 1) {
    if (token !== state.renderToken) {
      return;
    }

    const page = await pdfDoc.getPage(pageNumber);
    const baseViewport = page.getViewport({ scale: 1 });
    const maxWidth = Math.min(940, Math.max(520, (els.pdfViewer?.clientWidth || 940) - 48));
    const scale = (maxWidth / baseViewport.width) * state.pdfZoom;
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
    pageFragment.appendChild(wrapper);

    pages.push({ page, pageNumber, viewport, context, textLayer, overlay });
  }

  if (token !== state.renderToken) {
    return;
  }
  setHtml(els.pdfViewer, "");
  els.pdfViewer?.appendChild(pageFragment);

  for (const { page, pageNumber, viewport, context, textLayer, overlay } of pages) {
    if (token !== state.renderToken) {
      return;
    }

    await page.render({ canvasContext: context, viewport }).promise;
    if (token !== state.renderToken) {
      return;
    }

    await renderTextLayer(page, textLayer, viewport, pageNumber);
    if (token !== state.renderToken) {
      return;
    }

    renderPageFigures(overlay, pageFigures.get(pageNumber) || [], viewport);
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
  collectTextLayerWords(textLayer, pageNumber);
}

async function renderPdfPreservingScroll(paper) {
  const anchor = pdfScrollAnchor();
  await renderPdf(paper);
  restorePdfScrollAnchor(anchor);
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
      node.title = `${highlight.label}: ${highlight.comment || highlight.reason || highlight.snippet}`;
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

function validFigureBox(figure) {
  const values = (figure?.bbox_pct || []).map(Number);
  if (values.length !== 4 || values.some((value) => !Number.isFinite(value))) {
    return null;
  }

  const [left, top, right, bottom] = values.map((value) => clamp(value, 0, 100));
  if (right <= left || bottom <= top) {
    return null;
  }
  return [left, top, right, bottom];
}

function figureTitle(figure) {
  return String(figure?.label || figure?.title || "Visual").replace(/\s+/g, " ").trim();
}

function renderPageFigures(overlay, figures, viewport) {
  for (const figure of figures) {
    const box = validFigureBox(figure);
    if (!box) {
      continue;
    }

    const [left, top, right, bottom] = box;
    const node = document.createElement("button");
    const isActive = state.activeFigure?.id && state.activeFigure.id === figure.id;
    node.className = `figure-rect ${isActive ? "active" : ""}`;
    node.type = "button";
    node.dataset.figureId = figure.id || "";
    node.title = `${figureTitle(figure)}: ${figure.why_it_matters || figure.explanation || figure.caption || ""}`;
    node.style.left = `${(left / 100) * viewport.width}px`;
    node.style.top = `${(top / 100) * viewport.height}px`;
    node.style.width = `${Math.max(14, ((right - left) / 100) * viewport.width)}px`;
    node.style.height = `${Math.max(14, ((bottom - top) / 100) * viewport.height)}px`;

    const label = document.createElement("span");
    label.textContent = figure.type || "visual";
    node.appendChild(label);
    node.addEventListener("click", (event) => {
      event.stopPropagation();
      showFigurePopover(figure, node.getBoundingClientRect());
    });
    overlay.appendChild(node);
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

  const files = Array.from(els.pdfInput?.files || []);
  if (!files.length) {
    showToast("Choose one or more PDFs first");
    return null;
  }

  showToast(`Loading ${files.length} PDF${files.length === 1 ? "" : "s"}`, true);
  showReaderLoading();

  state.uploadPromise = (async () => {
    const uploadedPapers = [];

    for (const [index, file] of files.entries()) {
      const formData = new FormData();
      formData.append("file", file);
      showToast(`Loading ${index + 1}/${files.length}: ${file.name}`, true);
      const paper = await requestJson("/api/upload", {
        method: "POST",
        body: formData,
      });
      uploadedPapers.push(paper);
    }

    prependPaperSummaries(uploadedPapers);
    renderPaperList();

    const selectedPaper = uploadedPapers[0] || null;
    if (selectedPaper) {
      setSelectedPaper(selectedPaper);
      await renderPdf(selectedPaper);
    }

    hideToast();
    showToast(
      files.length === 1
        ? "PDF loaded. Click Analyze when ready."
        : `${files.length} PDFs loaded. Select a paper or click Analyze for the first one.`,
    );
    return selectedPaper;
  })()
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
  if (!paper && els.pdfInput?.files?.length) {
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
      ...textModelRequestOptions(),
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

function clamp(value, min, max) {
  return Math.min(max, Math.max(min, value));
}

function cleanSelectedText(words) {
  return words
    .map((word) => word.text)
    .join(" ")
    .replace(/\s+([,.;:!?%)\]])/g, "$1")
    .replace(/([([])\s+/g, "$1")
    .replace(/\s+/g, " ")
    .trim();
}

function collectTextLayerWords(textLayer, pageNumber) {
  const page = textLayer.closest(".pdf-page");
  const pageSize = pageSizeFor(pageNumber);
  if (!page || !pageSize) {
    state.pageWords.set(pageNumber, []);
    return;
  }

  const pageRect = page.getBoundingClientRect();
  const scaleX = pageSize.width / pageRect.width;
  const scaleY = pageSize.height / pageRect.height;
  const words = [];

  textLayer.querySelectorAll("span").forEach((span) => {
    const text = span.textContent || "";
    const matches = Array.from(text.matchAll(/\S+/g));
    if (!matches.length) {
      return;
    }

    const spanRect = span.getBoundingClientRect();
    if (spanRect.width < 1 || spanRect.height < 1) {
      return;
    }

    const textLength = Math.max(text.length, 1);
    for (const match of matches) {
      const startRatio = match.index / textLength;
      const endRatio = (match.index + match[0].length) / textLength;
      const x0 = spanRect.left - pageRect.left + spanRect.width * startRatio;
      const x1 = spanRect.left - pageRect.left + spanRect.width * endRatio;
      const y0 = spanRect.top - pageRect.top;
      const y1 = spanRect.bottom - pageRect.top;
      words.push({
        text: match[0],
        cssRect: [x0, y0, x1, y1].map(roundRectValue),
        pdfRect: [
          roundRectValue(x0 * scaleX),
          roundRectValue(y0 * scaleY),
          roundRectValue(x1 * scaleX),
          roundRectValue(y1 * scaleY),
        ],
      });
    }
  });

  state.pageWords.set(pageNumber, words);
}

function distanceToRect(x, y, rect) {
  const dx = x < rect[0] ? rect[0] - x : x > rect[2] ? x - rect[2] : 0;
  const dy = y < rect[1] ? rect[1] - y : y > rect[3] ? y - rect[3] : 0;
  return dx * dx + dy * dy;
}

function nearestWordIndex(words, x, y) {
  let bestIndex = null;
  let bestDistance = Number.POSITIVE_INFINITY;
  words.forEach((word, index) => {
    const distance = distanceToRect(x, y, word.cssRect);
    if (distance < bestDistance) {
      bestDistance = distance;
      bestIndex = index;
    }
  });
  return bestIndex;
}

function mergeWordRects(words, rectKey) {
  const lines = [];
  const sortedWords = [...words].sort((left, right) => {
    const leftCenter = (left.cssRect[1] + left.cssRect[3]) / 2;
    const rightCenter = (right.cssRect[1] + right.cssRect[3]) / 2;
    return leftCenter - rightCenter || left.cssRect[0] - right.cssRect[0];
  });

  for (const word of sortedWords) {
    const centerY = (word.cssRect[1] + word.cssRect[3]) / 2;
    const line = lines.find((item) => Math.abs(item.centerY - centerY) <= 5);
    if (line) {
      line.words.push(word);
      line.centerY = (line.centerY * (line.words.length - 1) + centerY) / line.words.length;
    } else {
      lines.push({ centerY, words: [word] });
    }
  }

  return lines.map((line) => {
    const rects = line.words.map((word) => word[rectKey]);
    return [
      roundRectValue(Math.min(...rects.map((rect) => rect[0]))),
      roundRectValue(Math.min(...rects.map((rect) => rect[1]))),
      roundRectValue(Math.max(...rects.map((rect) => rect[2]))),
      roundRectValue(Math.max(...rects.map((rect) => rect[3]))),
    ];
  });
}

function clientRectForWords(page, words) {
  const pageRect = page.getBoundingClientRect();
  const rects = mergeWordRects(words, "cssRect");
  return {
    left: pageRect.left + Math.min(...rects.map((rect) => rect[0])),
    top: pageRect.top + Math.min(...rects.map((rect) => rect[1])),
    width: Math.max(...rects.map((rect) => rect[2])) - Math.min(...rects.map((rect) => rect[0])),
    height: Math.max(...rects.map((rect) => rect[3])) - Math.min(...rects.map((rect) => rect[1])),
  };
}

function clearSelectionPreview() {
  els.pdfViewer?.querySelectorAll(".selection-preview-rect").forEach((node) => node.remove());
}

function selectionPreviewRects(selection, page) {
  if (selection.previewRects?.length) {
    return selection.previewRects;
  }

  const pageSize = pageSizeFor(selection.pageNumber);
  if (!pageSize) {
    return [];
  }
  const pageRect = page.getBoundingClientRect();
  const scaleX = pageRect.width / pageSize.width;
  const scaleY = pageRect.height / pageSize.height;
  return (selection.rects || []).map((rect) => [
    roundRectValue(rect[0] * scaleX),
    roundRectValue(rect[1] * scaleY),
    roundRectValue(rect[2] * scaleX),
    roundRectValue(rect[3] * scaleY),
  ]);
}

function showSelectionPreview(selection) {
  clearSelectionPreview();
  if (!selection?.pageNumber) {
    return;
  }

  const page = els.pdfViewer?.querySelector(`[data-page-number="${selection.pageNumber}"]`);
  const overlay = page?.querySelector(".overlay-layer");
  if (!overlay) {
    return;
  }

  for (const rect of selectionPreviewRects(selection, page)) {
    const [x0, y0, x1, y1] = rect;
    const node = document.createElement("div");
    node.className = "selection-preview-rect";
    node.style.left = `${x0}px`;
    node.style.top = `${y0}px`;
    node.style.width = `${Math.max(4, x1 - x0)}px`;
    node.style.height = `${Math.max(4, y1 - y0)}px`;
    overlay.appendChild(node);
  }
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

function pagePointFromEvent(event, page) {
  const pageRect = page.getBoundingClientRect();
  return {
    x: clamp(event.clientX - pageRect.left, 0, pageRect.width),
    y: clamp(event.clientY - pageRect.top, 0, pageRect.height),
  };
}

function customSelectionFromDrag(drag, event) {
  const words = state.pageWords.get(drag.pageNumber) || [];
  if (!words.length) {
    return null;
  }

  const end = pagePointFromEvent(event, drag.page);
  const startIndex = nearestWordIndex(words, drag.x, drag.y);
  const endIndex = nearestWordIndex(words, end.x, end.y);
  if (startIndex === null || endIndex === null) {
    return null;
  }

  const firstIndex = Math.min(startIndex, endIndex);
  const lastIndex = Math.max(startIndex, endIndex);
  const selectedWords = words.slice(firstIndex, lastIndex + 1);
  const text = cleanSelectedText(selectedWords);
  if (text.length < 2 || text.length > 900) {
    return null;
  }

  return {
    text,
    pageNumber: drag.pageNumber,
    pageText: state.pageTexts.get(drag.pageNumber) || "",
    rects: mergeWordRects(selectedWords, "pdfRect"),
    previewRects: mergeWordRects(selectedWords, "cssRect"),
    rect: clientRectForWords(drag.page, selectedWords),
  };
}

function startTextSelection(event) {
  if (event.button !== 0 || event.target.closest?.(".highlight-rect, .citation-rect")) {
    return;
  }

  const page = event.target.closest?.(".pdf-page");
  const pageNumber = Number(page?.dataset.pageNumber) || null;
  if (!page || !pageNumber || !(state.pageWords.get(pageNumber) || []).length) {
    return;
  }

  const point = pagePointFromEvent(event, page);
  state.textSelectionDrag = {
    page,
    pageNumber,
    x: point.x,
    y: point.y,
    clientX: event.clientX,
    clientY: event.clientY,
  };
  window.getSelection()?.removeAllRanges();
  hideSelectionPopover();
  hideCitationPopover();
  hideHighlightPopover();
  event.preventDefault();
}

function updateTextSelection(event) {
  const drag = state.textSelectionDrag;
  if (!drag) {
    return;
  }

  const distance = Math.hypot(event.clientX - drag.clientX, event.clientY - drag.clientY);
  if (distance < 4) {
    clearSelectionPreview();
    return;
  }

  const selection = customSelectionFromDrag(drag, event);
  if (selection) {
    showSelectionPreview(selection);
  }
}

function finishTextSelection(event) {
  const drag = state.textSelectionDrag;
  state.textSelectionDrag = null;
  if (!drag) {
    return;
  }

  const distance = Math.hypot(event.clientX - drag.clientX, event.clientY - drag.clientY);
  if (distance < 4) {
    clearSelectionPreview();
    return;
  }

  const selection = customSelectionFromDrag(drag, event);
  if (selection) {
    showSelectionPopoverFor(selection);
  } else {
    clearSelectionPreview();
  }
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

  const preferred = state.activeHighlightFacet !== "all" ? state.activeHighlightFacet : "problem";
  els.highlightCategorySelect.value = options.some((option) => option.id === preferred)
    ? preferred
    : options[0]?.id || "__new__";
  syncSelectionHighlightForm();
}

function resetSelectionHighlightForm() {
  els.selectionHighlightForm?.classList.add("hidden");
  if (els.highlightTextInput) {
    els.highlightTextInput.value = state.activeSelection?.text || "";
  }
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

function showSelectionPopoverFor(selection) {
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
  showSelectionPreview(selection);
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

function showSelectionPopover() {
  showSelectionPopoverFor(selectedTextFromPdf());
}

function hideSelectionPopover() {
  state.activeSelection = null;
  clearSelectionPreview();
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
      <button data-explain-highlight type="button">Explain</button>
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

function figureTextBlock(label, text) {
  const value = String(text || "").replace(/\s+/g, " ").trim();
  return value ? `<p><b>${escapeHtml(label)}:</b> ${escapeHtml(value)}</p>` : "";
}

function renderFigurePopover(figure) {
  setHtml(
    els.figurePopover,
    `
      <div class="figure-popover-copy">
        <div class="figure-popover-heading">
          <span class="label label-important">${escapeHtml(figure?.type || "visual")}</span>
          <span>p. ${Number(figure?.page_number) || "?"}</span>
        </div>
        <strong>${escapeHtml(figureTitle(figure))}</strong>
        ${figureTextBlock("Big picture", figure?.why_it_matters)}
        ${figureTextBlock("What it shows", figure?.explanation)}
        ${figureTextBlock("Caption", figure?.caption)}
        ${figureTextBlock("Uncertainty", figure?.uncertainty)}
      </div>
      <button data-add-active-figure type="button">Add to chat</button>
    `,
  );
}

function selectFigure(figureId) {
  els.pdfViewer?.querySelectorAll(".figure-rect").forEach((node) => {
    node.classList.toggle("active", node.dataset.figureId === figureId);
  });
}

function showFigurePopover(figure, rect) {
  if (!figure || !els.figurePopover) {
    hideFigurePopover();
    return;
  }

  hideSelectionPopover();
  hideCitationPopover();
  hideHighlightPopover();
  state.activeFigure = figure;
  selectFigure(figure.id || "");
  renderFigurePopover(figure);

  const popover = els.figurePopover;
  popover.classList.remove("hidden");
  const top = Math.max(8, rect.top - popover.offsetHeight - 8);
  const left = Math.min(
    window.innerWidth - popover.offsetWidth - 8,
    Math.max(8, rect.left + rect.width / 2 - popover.offsetWidth / 2),
  );
  popover.style.top = `${top}px`;
  popover.style.left = `${left}px`;
}

function hideFigurePopover() {
  state.activeFigure = null;
  els.figurePopover?.classList.add("hidden");
  els.pdfViewer?.querySelectorAll(".figure-rect.active").forEach((node) => node.classList.remove("active"));
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
  const value = els.highlightCategorySelect?.value || "problem";
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
    snippet: (els.highlightTextInput?.value || state.activeSelection.text).replace(/\s+/g, " ").trim(),
    reason: "manual",
    page_number: state.activeSelection.pageNumber,
    rects: state.activeSelection.rects || [],
    reground: true,
  };
  if (!highlight.snippet) {
    showToast("Highlight text is empty");
    els.highlightTextInput?.focus();
    return;
  }
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

async function explainSelection(selection, beforeRequest) {
  if (!state.selectedPaper || !selection) {
    return;
  }
  if (!requireOpenAiKey()) {
    return;
  }

  beforeRequest?.();
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
      ...textModelRequestOptions(),
    }),
  });

  pending.content = payload.answer || "No explanation returned.";
  renderChat();
}

async function explainActiveSelection() {
  if (!state.selectedPaper || !state.activeSelection) {
    hideSelectionPopover();
    return;
  }

  await explainSelection(state.activeSelection, hideSelectionPopover);
}

async function explainActiveHighlight() {
  if (!state.selectedPaper || state.activeHighlightIndex === null) {
    hideHighlightPopover();
    return;
  }

  const highlight = (state.selectedPaper.highlights || [])[state.activeHighlightIndex];
  if (!highlight?.snippet) {
    hideHighlightPopover();
    return;
  }

  await explainSelection(
    {
      text: highlight.snippet,
      pageNumber: highlight.page_number || null,
      pageText: state.pageTexts.get(highlight.page_number) || highlight.reason || "",
    },
    hideHighlightPopover,
  );
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
      figure_context: selectedFigureContext(),
      ...textModelRequestOptions(),
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

async function analyzeFiguresInReader(force = false) {
  if (!state.selectedPaper) {
    showToast("Select a paper first");
    return;
  }
  if (!requireOpenAiKey()) {
    return;
  }

  const paperId = state.selectedPaper.id;
  state.figureAnalysisRunning = true;
  syncPaperActions();
  showToast("Analyzing figures and tables", true);

  try {
    const payload = await requestJson(`/api/papers/${paperId}/figures/analyze`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        provider: selectedProvider(),
        api_key: requestApiKey() || null,
        force,
        ...visionModelRequestOptions(),
      }),
    });
    if (!state.selectedPaper || state.selectedPaper.id !== paperId) {
      hideToast();
      return;
    }

    const figures = payload.figures || [];
    const paper = {
      ...state.selectedPaper,
      figures,
      figure_warnings: payload.warnings || [],
      figure_provider_used: payload.provider_used || "unknown",
      figure_count: figures.length,
    };
    applySelectedPaperUpdate(paper);
    syncSelectedFigures();
    renderChatFigureFocus();
    await renderPdfPreservingScroll(paper);
    hideToast();
    showToast(
      figures.length
        ? `${figures.length} figure/table annotation${figures.length === 1 ? "" : "s"} ready`
        : "No figures or tables found",
    );
  } finally {
    state.figureAnalysisRunning = false;
    syncPaperActions();
  }
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
[
  els.textModelInput,
  els.textEffortSelect,
  els.visionModelInput,
  els.visionEffortSelect,
].forEach((control) => {
  control?.addEventListener("change", saveModelSettings);
});

els.pdfViewer?.addEventListener("pointerdown", startTextSelection);
window.addEventListener("pointermove", updateTextSelection);
window.addEventListener("pointerup", finishTextSelection);

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
  if (!els.figurePopover?.contains(event.target) && !event.target.closest?.(".figure-rect")) {
    hideFigurePopover();
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

els.figurePopover?.addEventListener("mousedown", (event) => {
  event.preventDefault();
});

els.highlightPopover?.addEventListener("click", (event) => {
  if (event.target.closest?.("[data-explain-highlight]")) {
    explainActiveHighlight().catch((error) => {
      state.chatMessages.push({ role: "assistant", content: error.message || String(error) });
      renderChat();
    });
  }
  if (event.target.closest?.("[data-remove-highlight]")) {
    removeActiveHighlight().catch((error) => showToast(error.message || String(error)));
  }
});

els.figurePopover?.addEventListener("click", (event) => {
  if (event.target.closest?.("[data-add-active-figure]")) {
    addFigureToChat(state.activeFigure);
    hideFigurePopover();
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
  analyzeFiguresInReader(false).catch((error) => {
    hideToast();
    showToast(error.message || String(error));
  });
});

els.leftPanelToggle?.addEventListener("click", () => {
  state.leftPanelCollapsed = !state.leftPanelCollapsed;
  syncPanelToggles();
});

els.rightPanelToggle?.addEventListener("click", () => {
  state.rightPanelCollapsed = !state.rightPanelCollapsed;
  syncPanelToggles();
});

els.pdfZoomOutButton?.addEventListener("click", () => {
  setPdfZoom(state.pdfZoom - PDF_ZOOM_STEP).catch((error) => showToast(error.message || String(error)));
});

els.pdfZoomInButton?.addEventListener("click", () => {
  setPdfZoom(state.pdfZoom + PDF_ZOOM_STEP).catch((error) => showToast(error.message || String(error)));
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
els.chatInput?.addEventListener("keydown", submitChatOnEnter);
syncPanelToggles();
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

els.takeawaysResizeHandle?.addEventListener("pointerdown", startTakeawaysResize);
els.takeawaysResizeHandle?.addEventListener("keydown", (event) => {
  if (!["ArrowUp", "ArrowDown"].includes(event.key)) {
    return;
  }

  event.preventDefault();
  const direction = event.key === "ArrowUp" ? -1 : 1;
  const panelTop = els.takeawaysTab?.getBoundingClientRect().top || 0;
  setTakeawaysHeight(panelTop + currentTakeawaysHeight() + direction * 24);
});

loadSettings()
  .then(() => loadPapers())
  .catch((error) => showToast(error.message || String(error)));
