const owner = Symbol.for("wavo.cursor.embers");

export default function mount({ parentElement }) {
  document[owner]?.dispose();
  const reduced = matchMedia("(prefers-reduced-motion: reduce)");
  const finePointer = matchMedia("(pointer: fine)");
  const layer = document.createElement("div");
  layer.className = "cursor-embers";
  layer.setAttribute("aria-hidden", "true");
  document.body.append(layer);
  let last = 0;
  let lastX = -100;
  let lastY = -100;
  const particles = new Set();

  function move(event) {
    if (reduced.matches || !finePointer.matches || event.pointerType !== "mouse" || event.buttons) return;
    const target = event.composedPath()[0];
    if (target instanceof Element && target.closest("button, input, textarea, select, a, [role=dialog]")) return;
    const now = performance.now();
    if (now - last < 72 || Math.hypot(event.clientX - lastX, event.clientY - lastY) < 20 || particles.size >= 9) return;
    last = now;
    lastX = event.clientX;
    lastY = event.clientY;
    const spark = document.createElement("i");
    spark.style.left = event.clientX + 7 + "px";
    spark.style.top = event.clientY + 7 + "px";
    layer.append(spark);
    particles.add(spark);
    const drift = (Math.random() - .5) * 16;
    const animation = spark.animate([
      { opacity: .6, transform: "translate(0, 0) rotate(45deg) scale(.85)" },
      { opacity: 0, transform: "translate(" + drift + "px, -18px) rotate(65deg) scale(.2)" },
    ], { duration: 570, easing: "ease-out" });
    function clearSpark() { spark.remove(); particles.delete(spark); }
    animation.onfinish = clearSpark;
    animation.oncancel = clearSpark;
  }
  function dispose() {
    document.removeEventListener("pointermove", move);
    layer.remove();
    particles.clear();
    if (document[owner]?.dispose === dispose) delete document[owner];
  }
  document[owner] = { dispose };
  document.addEventListener("pointermove", move, { passive: true });
  return () => requestAnimationFrame(() => {
    const host = parentElement instanceof ShadowRoot ? parentElement.host : parentElement;
    if (!host.isConnected) dispose();
  });
}
