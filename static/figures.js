const state = {
  paperId: document.body.dataset.paperId,
  paper: null,
  figures: [],
  warnings: [],
  providerUsed: "unknown",
  running: false,
};

const els = {
  title: document.getElementById("figures-title"),
  status: document.getElementById("figures-status"),
  statusPill: document.getElementById("figures-status-pill"),
  provider: document.getElementById("figures-provider"),
  warnings: document.getElementById("figure-warnings"),
  list: document.getElementById("figures-list"),
  reanalyzeButton: document.getElementById("reanalyze-figures-button"),
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
            <img src="${figure.image_url}" alt="" loading="lazy" />
            <div class="figure-copy">
              <div class="figure-card-heading">
                <span class="label label-important">${escapeHtml(figure.type || "visual")}</span>
                <span class="figure-page">p. ${Number(figure.page_number) || "?"}</span>
              </div>
              <strong>${escapeHtml(figure.label || figure.title || "Visual")}</strong>
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
  state.warnings = payload.warnings || [];
  state.providerUsed = payload.provider_used || "unknown";
  setStatus(
    state.figures.length
      ? `${state.figures.length} visual${state.figures.length === 1 ? "" : "s"} analyzed.`
      : "No figure analysis yet.",
    state.providerUsed,
  );
  renderFigures();
}

async function analyzeFigures(force = false) {
  state.running = true;
  syncButton();
  showToast("Analyzing figures with Codex", true);
  setStatus("Converting PDF pages to JPEG and analyzing with Codex.", "Codex");
  setHtml(els.list, `<div class="loading">Analyzing figures</div>`);

  try {
    const payload = await requestJson(`/api/papers/${state.paperId}/figures/analyze`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ provider: "codex", force }),
    });
    state.figures = payload.figures || [];
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
  }
}

els.reanalyzeButton?.addEventListener("click", () => {
  analyzeFigures(true).catch((error) => {
    hideToast();
    setStatus(error.message || String(error), "Error");
    showToast(error.message || String(error));
  });
});

async function init() {
  if (!state.paperId) {
    setStatus("Paper not found.", "Error");
    syncButton();
    return;
  }

  await loadPaper();
  await loadFigures();
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
