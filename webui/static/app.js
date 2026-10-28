// 詳細画面のタブ（企業ログ / 面談ログ）. URL の #iv-... で該当タブを開く
function selectTab(root, id) {
  const panels = root.querySelectorAll(".tab-panel");
  if (![...panels].some((p) => p.id === id)) return false;
  panels.forEach((p) => (p.hidden = p.id !== id));
  root.querySelectorAll("[data-tab]").forEach((b) => b.setAttribute("aria-selected", String(b.dataset.tab === id)));
  return true;
}

function initTabs() {
  document.querySelectorAll("[data-tabs]").forEach((root) => {
    root.querySelectorAll("[data-tab]").forEach((button) => {
      button.addEventListener("click", () => {
        selectTab(root, button.dataset.tab);
        history.replaceState(null, "", button.dataset.tab === "log" ? location.pathname + location.search : "#" + button.dataset.tab);
      });
    });
    if (location.hash && selectTab(root, location.hash.slice(1))) root.scrollIntoView();
  });

  document.querySelectorAll("[data-tab-jump]").forEach((btn) => {
    btn.addEventListener("click", (e) => {
      const tabId = btn.dataset.tabJump;
      const tabsRoot = document.querySelector("[data-tabs]");
      if (tabsRoot && selectTab(tabsRoot, tabId)) {
        history.replaceState(null, "", "#" + tabId);
        tabsRoot.scrollIntoView({ behavior: "smooth" });
        e.preventDefault();
      }
    });
  });
}

document.addEventListener("DOMContentLoaded", initTabs);
