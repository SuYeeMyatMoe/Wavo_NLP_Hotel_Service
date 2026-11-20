const owner = Symbol.for("wavo.workspace.effects");
const themeKey = "wavo.hotel.theme";

export default function mount({ parentElement }) {
  const host = parentElement instanceof ShadowRoot ? parentElement.host : parentElement;
  const current = document[owner];
  if (current?.host === host) return current.cleanup;
  current?.dispose();

  const root = document.documentElement;
  const reduced = matchMedia("(prefers-reduced-motion: reduce)");
  const layer = document.createElement("div");
  layer.className = "cursor-embers";
  layer.setAttribute("aria-hidden", "true");
  document.body.append(layer);
  const particles = new Set();
  const jumps = new WeakMap();
  const depth = new WeakMap();
  let last = 0;
  let lastX = -100;
  let lastY = -100;
  let hoveredMascot;

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

  function getMascot(event) {
    return event.composedPath().find(
      (node) => node instanceof Element && node.hasAttribute("data-wavo-mascot"),
    );
  }

  function tiltMascot(mascot, pitch, yaw) {
    if (!depth.has(mascot)) {
      const image = mascot.querySelector(".wavo-mascot-actor img");
      if (image?.complete) depth.set(mascot, createMascotDepth(mascot));
    }
    const model = depth.get(mascot);
    if (model) {
      model.tilt(pitch, yaw);
    } else {
      mascot.style.setProperty("--mascot-tilt-x", pitch + "rad");
      mascot.style.setProperty("--mascot-tilt-y", yaw + "rad");
    }
  }

  function move(event) {
    if (reduced.matches || event.pointerType === "touch") return;
    const mascot = getMascot(event);
    if (hoveredMascot && hoveredMascot !== mascot) {
      tiltMascot(hoveredMascot, 0, 0);
    }
    hoveredMascot = mascot;
    if (mascot) {
      const bounds = mascot.getBoundingClientRect();
      const x = (event.clientX - bounds.left) / bounds.width - .5;
      const y = (event.clientY - bounds.top) / bounds.height - .5;
      tiltMascot(mascot, -y * .55, x * .74);
    }
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

  function jump(event) {
    if (reduced.matches) return;
    const mascot = getMascot(event);
    const actor = mascot?.querySelector(".wavo-mascot-actor");
    if (!actor) return;
    tiltMascot(mascot, 0, 0);
    jumps.get(actor)?.cancel();
    const animation = actor.animate([
      { translate: "0 0", scale: "1" },
      { translate: "0 5px", scale: "1.08 .91", offset: .14 },
      { translate: "0 -35px", scale: ".98 1.04", offset: .48 },
      { translate: "0 0", scale: "1.06 .95", offset: .8 },
      { translate: "0 0", scale: "1" },
    ], { duration: 690, easing: "ease-in-out" });
    jumps.set(actor, animation);
    mascot.setAttribute("data-jumping", "");
    animation.onfinish = animation.oncancel = () => {
      if (jumps.get(actor) === animation) mascot.removeAttribute("data-jumping");
    };
    const { x, y, width, height } = mascot.getBoundingClientRect();
    for (let i = 0; i < 9; i++) {
      const angle = i * Math.PI * 2 / 9;
      spark(x + width / 2, y + height * .6, Math.cos(angle) * 92, Math.sin(angle) * 67 - 19, 620 + i * 21, i % 3 === 0);
    }
  }

  function dispose() {
    window.removeEventListener("wavo:set-theme", updateTheme);
    window.removeEventListener("storage", syncTabs);
    document.removeEventListener("pointermove", move, true);
    document.removeEventListener("click", jump, true);
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
  document.addEventListener("click", jump, true);
  return cleanup;
}
