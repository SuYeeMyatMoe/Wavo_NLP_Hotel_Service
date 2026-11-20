const owner = Symbol.for("wavo.workspace.effects");
const themeKey = "wavo.hotel.theme";

function watchLanding(main) {
  if (!main || !("IntersectionObserver" in window)) return () => {};
  const selector = "[data-wavo-reveal]:not([data-wavo-revealed])";
  const observed = new WeakSet();
  const viewport = new IntersectionObserver((entries) => {
    for (const { target, isIntersecting } of entries) {
      if (!isIntersecting || !target.isConnected) continue;
      viewport.unobserve(target);
      target.style.setProperty("--wavo-reveal-delay", 85 * Number(target.dataset.wavoReveal) + "ms");
      target.dataset.wavoRevealed = "";
    }
  }, { root: main, rootMargin: "0px 0px 32px 0px", threshold: .08 });
  function observeNewContent() {
    for (const element of main.querySelectorAll(selector)) {
      if (observed.has(element)) continue;
      observed.add(element);
      viewport.observe(element);
    }
  }
  const mutations = new MutationObserver(observeNewContent);
  mutations.observe(main, { childList: true, subtree: true });
  observeNewContent();
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
  const stopReveals = watchLanding(main);
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
