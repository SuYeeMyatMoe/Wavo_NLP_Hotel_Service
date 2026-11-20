const owner = Symbol.for("wavo.workspace.effects");
const themeKey = "wavo.hotel.theme";

const nativePanels = '[data-testid="stVerticalBlock"], [data-testid="stHorizontalBlock"]';
const workspaceContent = '[data-testid="stMain"], [role="dialog"]';
const revealTargets = [
  "[data-wavo-reveal]", "[data-wavo-panel]", ".st-key-wavo_guest_concierge",
  ".st-key-guest_live_reception", '[class*="st-key-concierge_"]',
  ".hero", "[data-testid='stForm']", "[data-testid='stExpander']", "[data-testid='stMetric']",
  "[data-testid='stDataFrame']", "[data-testid='stTable']", "[data-testid='stVegaLiteChart']",
  "[data-testid='stButton']", "[data-testid='stFormSubmitButton']", "[data-testid='stLinkButton']",
  "[data-testid='stDownloadButton']", "[data-testid='stButtonGroup']", "[data-testid='stPopover']",
  "[data-testid='stTextInput']", "[data-testid='stTextArea']", "[data-testid='stSelectbox']",
  "[data-testid='stNumberInput']", "[data-testid='stDateInput']", "[data-testid='stMultiSelect']",
  ".receipt-details > div",
].join(",");

function watchWorkspace(main) {
  if (!main || !("IntersectionObserver" in window)) return () => {};
  const tracked = new Set();
  const measured = new WeakSet();
  const viewport = new IntersectionObserver((entries) => {
    const entering = entries
      .filter(({ target, isIntersecting, boundingClientRect }) =>
        target.isConnected && isIntersecting && boundingClientRect.width > 0 && boundingClientRect.height > 0)
      .sort((a, b) => a.boundingClientRect.top - b.boundingClientRect.top ||
        a.boundingClientRect.left - b.boundingClientRect.left);
    const animated = [];
    for (const { target } of entering) {
      viewport.unobserve(target);
      tracked.delete(target);
      if (animated.some((parent) => parent.contains(target))) {
        target.dataset.wavoSeen = "";
        continue;
      }
      const order = target.dataset.wavoReveal ?? Math.min(animated.length, 4);
      target.style.setProperty("--wavo-reveal-delay", 75 * Number(order) + "ms");
      target.dataset.wavoRevealed = "";
      animated.push(target);
    }
  }, { rootMargin: "0px 0px 20px 0px", threshold: [0, .05] });

  function glass(element) {
    if (measured.has(element)) return;
    measured.add(element);
    const style = getComputedStyle(element);
    if (parseFloat(style.borderTopWidth) > 0 && style.borderTopStyle === "solid") {
      element.dataset.wavoPanel = "";
    }
  }

  function observe(element) {
    if (tracked.has(element) || element.hasAttribute("data-wavo-revealed") ||
        element.hasAttribute("data-wavo-seen")) return;
    tracked.add(element);
    viewport.observe(element);
  }

  function scan(root) {
    if (!(root instanceof HTMLElement)) return;
    if (root.matches(nativePanels)) glass(root);
    root.querySelectorAll(nativePanels).forEach(glass);
    if (root.matches(revealTargets)) observe(root);
    root.querySelectorAll(revealTargets).forEach(observe);
  }

  const mutations = new MutationObserver((records) => {
    for (const { target, addedNodes, removedNodes } of records) {
      for (const node of addedNodes) {
        if (!(node instanceof HTMLElement)) continue;
        if (node.closest(workspaceContent)) scan(node);
        else if (node.childElementCount) node.querySelectorAll('[role="dialog"]').forEach(scan);
      }
      if (!removedNodes.length || !(target instanceof HTMLElement) || target.closest(".cursor-embers")) continue;
      for (const element of tracked) {
        if (element.isConnected) continue;
        viewport.unobserve(element);
        tracked.delete(element);
      }
    }
  });
  mutations.observe(document.body, { childList: true, subtree: true });
  scan(main);
  document.querySelectorAll('[role="dialog"]').forEach(scan);
  return () => {
    mutations.disconnect();
    viewport.disconnect();
  };
}

export default function mount({ parentElement }) {
  const host = parentElement instanceof ShadowRoot ? parentElement.host : parentElement;
  const current = document[owner];
  if (current?.host === host) return current.cleanup;
  current?.dispose();

  const root = document.documentElement;
  const main = document.querySelector('[data-testid="stMain"]');
  const stopReveals = watchWorkspace(main);
  const viewport = new ResizeObserver(updateWorkspaceWidth);
  function updateWorkspaceWidth() {
    if (main?.clientWidth) main.style.setProperty("--wavo-workspace-width", main.clientWidth + "px");
  }
  if (main) {
    updateWorkspaceWidth();
    viewport.observe(main);
  }
  const reduced = matchMedia("(prefers-reduced-motion: reduce)");
  const layer = document.createElement("div");
  layer.className = "cursor-embers";
  layer.setAttribute("aria-hidden", "true");
  document.body.append(layer);
  const particles = new Set();
  let last = 0;
  let lastX = -100;
  let lastY = -100;

  function applyTheme(theme) {
    root.dataset.wavoTheme = theme === "light" ? "light" : "dark";
    window.dispatchEvent(new Event("wavo:theme-changed"));
  }
  function updateTheme({ detail }) {
    if (detail !== "light" && detail !== "dark") return;
    applyTheme(detail);
    try {
      localStorage.setItem(themeKey, detail);
    } catch {
      // The lamp still controls the current document if browser storage is blocked.
    }
  }
  function themeFromStorage() {
    try {
      return localStorage.getItem(themeKey);
    } catch {
      return null;
    }
  }
  function syncTabs(event) {
    if (event.key === themeKey || event.key === null) applyTheme(themeFromStorage());
  }

  function spark(x, y, driftX, driftY, duration, large = false) {
    if (particles.size >= 56) return;
    const particle = document.createElement("i");
    if (large) particle.className = "ember-bright";
    particle.style.left = x + "px";
    particle.style.top = y + "px";
    layer.append(particle);
    particles.add(particle);
    const animation = particle.animate([
      { opacity: 1, transform: "translate(0, 0) rotate(45deg) scale(.75)" },
      { opacity: .84, offset: .22 },
      { opacity: 0, transform: `translate(${driftX}px, ${driftY}px) rotate(105deg) scale(.1)` },
    ], { duration, easing: "ease-out" });
    function clear() { particle.remove(); particles.delete(particle); }
    animation.onfinish = clear;
    animation.oncancel = clear;
  }

  function move(event) {
    if (reduced.matches || event.pointerType === "touch") return;
    const now = performance.now();
    const dx = event.clientX - lastX;
    const dy = event.clientY - lastY;
    if (now - last < 22 || Math.hypot(dx, dy) < 6) return;
    last = now;
    lastX = event.clientX;
    lastY = event.clientY;
    spark(lastX + 8, lastY + 8, -dx * .11 - 9, -dy * .11 - 15, 610, true);
    spark(lastX + 12, lastY + 12, 13 - Math.random() * 22, -25, 460);
  }

  function dispose() {
    window.removeEventListener("wavo:set-theme", updateTheme);
    window.removeEventListener("storage", syncTabs);
    document.removeEventListener("pointermove", move, true);
    viewport.disconnect();
    stopReveals();
    layer.remove();
    particles.clear();
    if (document[owner]?.dispose === dispose) delete document[owner];
  }

  const cleanup = () => requestAnimationFrame(() => {
    if (!host.isConnected) dispose();
  });
  document[owner] = { host, cleanup, dispose };
  window.addEventListener("wavo:set-theme", updateTheme);
  window.addEventListener("storage", syncTabs);
  applyTheme(root.dataset.wavoTheme || themeFromStorage());
  document.addEventListener("pointermove", move, { capture: true, passive: true });
  return cleanup;
}
