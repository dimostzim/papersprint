const MODEL_SETTINGS_KEY = "papersprint.modelSettings";

const state = {
  paperId: document.body.dataset.paperId,
  paper: null,
  figures: [],
  warnings: [],
  providerUsed: "unknown",
  running: false,
  chatRunning: false,
  chatMessages: [],
  selectedFigures: [],
};

const els = {
  title: document.getElementById("figures-title"),
  status: document.getElementById("figures-status"),
  statusPill: document.getElementById("figures-status-pill"),
  provider: document.getElementById("figures-provider"),
  providerSelect: document.getElementById("provider-select"),
  apiKeyInput: document.getElementById("api-key-input"),
  textModelInput: document.getElementById("text-model-input"),
  textEffortSelect: document.getElementById("text-effort-select"),
  visionModelInput: document.getElementById("vision-model-input"),
  visionEffortSelect: document.getElementById("vision-effort-select"),
  modelOptions: document.getElementById("model-options"),
  warnings: document.getElementById("figure-warnings"),
  list: document.getElementById("figures-list"),
  reanalyzeButton: document.getElementById("reanalyze-figures-button"),
  chatFocus: document.getElementById("figure-chat-focus"),
  chatMessages: document.getElementById("figure-chat-messages"),
  chatForm: document.getElementById("figure-chat-form"),
  chatInput: document.getElementById("figure-chat-input"),
  toast: document.getElementById("toast"),
};

function escapeHtml(value = "") {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;");
}

function setHtml(target, html) {
  if (!target) {
    return;
  }
  target.innerHTML = html;
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
  els.toast?.classList.add("hidden");
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

function setStatus(message, pill = "Figures") {
  if (els.status) {
    els.status.textContent = message;
  }
  if (els.statusPill) {
    els.statusPill.textContent = pill;
  }
}

function storedModelSettings() {
  try {
    return JSON.parse(window.localStorage.getItem(MODEL_SETTINGS_KEY) || "{}");
  } catch {
    return {};
  }
}

function selectedTextModel() {
  return els.textModelInput?.value.trim() || "gpt-5.5";
}

function selectedProvider() {
  return els.providerSelect?.value || "codex";
}

function requestApiKey() {
  return ["openai", "openrouter"].includes(selectedProvider()) ? els.apiKeyInput?.value.trim() || "" : "";
}

function syncApiKeyInput() {
  const needsKey = ["openai", "openrouter"].includes(selectedProvider());
  const label = selectedProvider() === "openrouter" ? "OpenRouter API key" : "OpenAI API key";
  els.apiKeyInput?.classList.toggle("hidden", !needsKey);
  els.apiKeyInput?.setAttribute("placeholder", label);
  els.apiKeyInput?.setAttribute("aria-label", label);
}

function requireOpenAiKey() {
  if (!["openai", "openrouter"].includes(selectedProvider()) || requestApiKey()) {
    return true;
  }
  showToast(`Enter an ${selectedProvider() === "openrouter" ? "OpenRouter" : "OpenAI"} API key`);
  els.apiKeyInput?.focus();
  return false;
}

function selectedVisionModel() {
  return els.visionModelInput?.value.trim() || selectedTextModel();
}

function selectedTextEffort() {
  return els.textEffortSelect?.value || "high";
}

function selectedVisionEffort() {
  return els.visionEffortSelect?.value || selectedTextEffort();
}

function saveModelSettings() {
  window.localStorage.setItem(
    MODEL_SETTINGS_KEY,
    JSON.stringify({
      textModel: selectedTextModel(),
      textEffort: selectedTextEffort(),
      visionModel: selectedVisionModel(),
      visionEffort: selectedVisionEffort(),
    }),
  );
}

function populateEffortSelect(select, efforts, selected, prefix) {
  if (!select) {
    return;
  }
  const options = Array.from(new Set((efforts || []).map((effort) => String(effort || "").trim()).filter(Boolean)));
  const selectedEffort = options.includes(selected) ? selected : options[0] || "high";
  select.value = selectedEffort;
  const picker = select.closest(".effort-picker");
  if (!picker) {
    return;
  }
  const button = picker.querySelector("[data-effort-button]");
  const menu = picker.querySelector(".effort-menu");
  if (button) {
    button.textContent = selectedEffort;
    button.setAttribute("aria-label", `${prefix} reasoning effort: ${selectedEffort}`);
  }
  setHtml(
    menu,
    options.map((effort) => {
      const isSelected = effort === selectedEffort ? "true" : "false";
      return `<button type="button" role="option" data-effort-option="${escapeHtml(effort)}" aria-selected="${isSelected}">${escapeHtml(effort)}</button>`;
    }).join(""),
  );
}

function closeEffortPickers(exceptPicker = null) {
  document.querySelectorAll(".effort-picker").forEach((picker) => {
    if (picker === exceptPicker) {
      return;
    }
    picker.querySelector(".effort-menu")?.classList.add("hidden");
    picker.querySelector("[data-effort-button]")?.setAttribute("aria-expanded", "false");
  });
}

function toggleEffortPicker(button) {
  const picker = button.closest(".effort-picker");
  if (!picker) {
    return;
  }
  const menu = picker.querySelector(".effort-menu");
  const isOpen = !menu?.classList.contains("hidden");
  closeEffortPickers(picker);
  menu?.classList.toggle("hidden", isOpen);
  button.setAttribute("aria-expanded", String(!isOpen));
}

function selectEffortOption(option) {
  const picker = option.closest(".effort-picker");
  const input = picker?.querySelector("input[type='hidden']");
  const button = picker?.querySelector("[data-effort-button]");
  if (!input || !button) {
    return;
  }
  input.value = option.dataset.effortOption || "high";
  button.textContent = input.value;
  picker.querySelectorAll("[data-effort-option]").forEach((node) => {
    node.setAttribute("aria-selected", String(node === option));
  });
  input.dispatchEvent(new Event("change", { bubbles: true }));
  closeEffortPickers();
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

async function loadSettings() {
  const settings = await requestJson("/api/settings");
  if (settings.default_provider && els.providerSelect) {
    els.providerSelect.value = settings.default_provider;
  }
  syncApiKeyInput();
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

function syncButton() {
  if (!els.reanalyzeButton) {
    return;
  }
  els.reanalyzeButton.disabled = state.running || !state.paperId || !state.paper;
  const label = state.running
    ? "Analyzing"
    : state.figures.length
      ? "Reanalyze"
      : "Analyze";
  setLoadingButton(els.reanalyzeButton, state.running, label);
}

function resizeChatInput() {
  if (!els.chatInput) {
    return;
  }
  const style = window.getComputedStyle(els.chatInput);
  const lineHeight = Number.parseFloat(style.lineHeight) || 18;
  const verticalPadding = Number.parseFloat(style.paddingTop) + Number.parseFloat(style.paddingBottom);
  const verticalBorder = Number.parseFloat(style.borderTopWidth) + Number.parseFloat(style.borderBottomWidth);
  const maxHeight = lineHeight * 5 + verticalPadding + verticalBorder;
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

function renderWarnings() {
  if (!els.warnings) {
    return;
  }
  if (!state.warnings.length) {
    els.warnings.classList.add("hidden");
    setHtml(els.warnings, "");
    return;
  }
  els.warnings.classList.remove("hidden");
  setHtml(
    els.warnings,
    `<div class="figure-warnings">${state.warnings.map((item) => `<p>${escapeHtml(item)}</p>`).join("")}</div>`,
  );
}

function figureTitle(figure) {
  return figure.label || figure.title || "Visual";
}

function isFigureSelected(figureId) {
  return state.selectedFigures.some((figure) => figure.id === figureId);
}

function syncSelectedFigures() {
  state.selectedFigures = state.selectedFigures
    .map((figure) => state.figures.find((item) => item.id === figure.id))
    .filter(Boolean);
}

function addFigureToChat(figureId) {
  const figure = state.figures.find((item) => item.id === figureId);
  if (!figure || isFigureSelected(figureId)) {
    return;
  }
  state.selectedFigures.push(figure);
  renderFigureFocus();
  syncFigureButtons();
  els.chatInput?.focus();
  showToast("Figure added to chat");
}

function removeFigureFromChat(figureId) {
  state.selectedFigures = state.selectedFigures.filter((figure) => figure.id !== figureId);
  renderFigureFocus();
  syncFigureButtons();
}

function renderFigureFocus() {
  if (!els.chatFocus) {
    return;
  }
  if (!state.selectedFigures.length) {
    els.chatFocus.classList.add("hidden");
    setHtml(els.chatFocus, "");
    return;
  }
  els.chatFocus.classList.remove("hidden");
  setHtml(
    els.chatFocus,
    state.selectedFigures
      .map(
        (figure) => `
          <span class="figure-focus-chip">
            <span>${escapeHtml(figureTitle(figure))}</span>
            <button data-remove-figure="${escapeHtml(figure.id)}" type="button" aria-label="Remove figure">x</button>
          </span>
        `,
      )
      .join(""),
  );

  els.chatFocus.querySelectorAll("[data-remove-figure]").forEach((button) => {
    button.addEventListener("click", () => removeFigureFromChat(button.dataset.removeFigure || ""));
  });
}

function syncFigureButtons() {
  els.list?.querySelectorAll("[data-add-figure]").forEach((button) => {
    const isAdded = isFigureSelected(button.dataset.addFigure || "");
    button.classList.toggle("is-added", isAdded);
    button.textContent = isAdded ? "Added" : "Add to chat";
  });
}

function renderFigures() {
  renderWarnings();
  syncButton();

  if (!state.figures.length) {
    setHtml(els.list, `<div class="muted-box">No figure analysis yet</div>`);
    return;
  }

  setHtml(
    els.list,
    state.figures
      .map(
        (figure) => `
          <article class="figure-card">
            <img src="${figure.image_url}" alt="" loading="eager" decoding="async" />
            <div class="figure-copy">
              <div class="figure-card-heading">
                <span class="label label-important">${escapeHtml(figure.type || "visual")}</span>
                <div class="figure-card-actions">
                  <span class="figure-page">p. ${Number(figure.page_number) || "?"}</span>
                  <button class="figure-add-button ${isFigureSelected(figure.id) ? "is-added" : ""}" data-add-figure="${escapeHtml(figure.id)}" type="button">
                    ${isFigureSelected(figure.id) ? "Added" : "Add to chat"}
                  </button>
                </div>
              </div>
              <strong>${escapeHtml(figureTitle(figure))}</strong>
              ${figure.title ? `<p>${escapeHtml(figure.title)}</p>` : ""}
              ${figure.caption ? `<p><b>Caption:</b> ${escapeHtml(figure.caption)}</p>` : ""}
              ${figure.explanation ? `<p><b>Figure explanation:</b> ${escapeHtml(figure.explanation)}</p>` : ""}
              ${figure.why_it_matters ? `<p><b>Why it matters:</b> ${escapeHtml(figure.why_it_matters)}</p>` : ""}
              ${figure.uncertainty ? `<small>${escapeHtml(figure.uncertainty)}</small>` : ""}
            </div>
          </article>
        `,
      )
      .join(""),
  );

  els.list?.querySelectorAll("[data-add-figure]").forEach((button) => {
    button.addEventListener("click", () => addFigureToChat(button.dataset.addFigure || ""));
  });
}

async function loadPaper() {
  const paper = await requestJson(`/api/papers/${state.paperId}`);
  state.paper = paper;
  if (els.title) {
    els.title.textContent = paper.title || paper.filename || "Figures";
  }
  if (els.provider) {
    els.provider.textContent = paper.analysis_status === "analyzing" ? "Text analysis running" : "Figures";
  }
}

async function loadFigures() {
  const payload = await requestJson(`/api/papers/${state.paperId}/figures`);
  state.figures = payload.figures || [];
  syncSelectedFigures();
  state.warnings = payload.warnings || [];
  state.providerUsed = payload.provider_used || "unknown";
  setStatus(
    state.figures.length
      ? `${state.figures.length} visual${state.figures.length === 1 ? "" : "s"} analyzed.`
      : "No figure analysis yet.",
    state.providerUsed,
  );
  renderFigures();
  renderFigureFocus();
}

async function analyzeFigures(force = false) {
  if (!requireOpenAiKey()) {
    return;
  }
  state.running = true;
  syncButton();
  showToast("Analyzing figures", true);
  setStatus("Converting candidate PDF pages to JPEG and analyzing figures.", "Figures");
  setHtml(els.list, `<div class="loading">Analyzing figures</div>`);

  try {
    const payload = await requestJson(`/api/papers/${state.paperId}/figures/analyze`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        provider: selectedProvider(),
        api_key: requestApiKey() || null,
        force,
        ...visionModelRequestOptions(),
      }),
    });
    state.figures = payload.figures || [];
    syncSelectedFigures();
    state.warnings = payload.warnings || [];
    state.providerUsed = payload.provider_used || "unknown";
    setStatus(
      state.figures.length
        ? `${state.figures.length} visual${state.figures.length === 1 ? "" : "s"} analyzed.`
        : "No figures found.",
      state.providerUsed,
    );
    hideToast();
    showToast("Figure analysis ready");
  } finally {
    state.running = false;
    renderFigures();
    renderFigureFocus();
  }
}

function renderChat() {
  if (!els.chatMessages) {
    return;
  }

  if (!state.chatMessages.length) {
    setHtml(els.chatMessages, `<div class="muted-box">Ask about this paper or selected figures.</div>`);
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

async function sendChatMessage(content) {
  if (!state.paperId || state.chatRunning) {
    return;
  }
  if (!requireOpenAiKey()) {
    return;
  }
  state.chatRunning = true;
  state.chatMessages.push({ role: "user", content });
  if (els.chatInput) {
    els.chatInput.value = "";
    resizeChatInput();
  }

  const pending = { role: "assistant", content: "Thinking..." };
  state.chatMessages.push(pending);
  renderChat();

  try {
    const payload = await requestJson(`/api/papers/${state.paperId}/chat`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        messages: state.chatMessages.filter((message) => message.content !== "Thinking..."),
        use_web: false,
        provider: selectedProvider(),
        api_key: requestApiKey() || null,
        figure_context: selectedFigureContext(),
        ...textModelRequestOptions(),
      }),
    });

    pending.content = payload.answer || "No answer returned.";
    if (payload.warnings?.length) {
      pending.content += `\n\n${payload.warnings.join("\n")}`;
    }
  } catch (error) {
    pending.content = error.message || String(error);
  } finally {
    state.chatRunning = false;
    renderChat();
  }
}

els.reanalyzeButton?.addEventListener("click", () => {
  analyzeFigures(true).catch((error) => {
    hideToast();
    setStatus(error.message || String(error), "Error");
    showToast(error.message || String(error));
  });
});

els.chatForm?.addEventListener("submit", (event) => {
  event.preventDefault();
  const content = els.chatInput?.value.trim() || "";
  if (!content) {
    return;
  }
  sendChatMessage(content).catch((error) => {
    state.chatMessages.push({ role: "assistant", content: error.message || String(error) });
    renderChat();
  });
});

els.chatInput?.addEventListener("input", resizeChatInput);
els.chatInput?.addEventListener("keydown", submitChatOnEnter);
els.providerSelect?.addEventListener("change", syncApiKeyInput);
document.addEventListener("click", (event) => {
  const effortOption = event.target.closest?.("[data-effort-option]");
  if (effortOption) {
    selectEffortOption(effortOption);
    return;
  }

  const effortButton = event.target.closest?.("[data-effort-button]");
  if (effortButton) {
    toggleEffortPicker(effortButton);
    return;
  }

  if (!event.target.closest?.(".effort-picker")) {
    closeEffortPickers();
  }
});
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape") {
    closeEffortPickers();
  }
});
[
  els.textModelInput,
  els.textEffortSelect,
  els.visionModelInput,
  els.visionEffortSelect,
].forEach((control) => {
  control?.addEventListener("change", saveModelSettings);
});

async function init() {
  if (!state.paperId) {
    setStatus("Paper not found.", "Error");
    syncButton();
    return;
  }

  await loadSettings();
  await loadPaper();
  await loadFigures();
  renderChat();
  resizeChatInput();
  if (!state.figures.length) {
    await analyzeFigures(false);
  }
}

init().catch((error) => {
  hideToast();
  setStatus(error.message || String(error), "Error");
  showToast(error.message || String(error));
  syncButton();
});
