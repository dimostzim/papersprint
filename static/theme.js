const THEME_KEY = "papersprint-theme";

function preferredTheme() {
  const saved = localStorage.getItem(THEME_KEY);
  if (saved === "dark" || saved === "light") {
    return saved;
  }
  return window.matchMedia?.("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

function applyTheme(theme) {
  document.documentElement.dataset.theme = theme;
  const toggle = document.getElementById("theme-toggle");
  if (toggle) {
    toggle.textContent = theme === "dark" ? "☀" : "☾";
    toggle.title = theme === "dark" ? "Use light mode" : "Use dark mode";
    toggle.setAttribute("aria-label", toggle.title);
  }
}

function toggleTheme() {
  const nextTheme = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
  localStorage.setItem(THEME_KEY, nextTheme);
  applyTheme(nextTheme);
}

applyTheme(preferredTheme());
document.getElementById("theme-toggle")?.addEventListener("click", toggleTheme);
