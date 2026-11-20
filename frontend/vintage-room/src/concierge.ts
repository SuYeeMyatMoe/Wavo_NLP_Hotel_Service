import {
  ACESFilmicToneMapping, AmbientLight, DirectionalLight, PerspectiveCamera,
  PMREMGenerator, Scene, SRGBColorSpace, WebGLRenderer,
} from "three";
import { RoomEnvironment } from "three/addons/environments/RoomEnvironment.js";
import { createConcierge } from "./conciergeModel";

const mounted = new WeakSet<HTMLElement>();
const tau = Math.PI * 2;

export function mountMascot(element: HTMLElement | null) {
  if (!element || mounted.has(element)) return;
  const host = element;
  mounted.add(host);
  const reduced = matchMedia("(prefers-reduced-motion: reduce)");
  let renderer: WebGLRenderer;
  try {
    renderer = new WebGLRenderer({ alpha: true, antialias: true, powerPreference: "low-power" });
  } catch {
    // The transparent portrait stays available when WebGL is unavailable.
    return;
  }

  const scene = new Scene();
  const studio = new RoomEnvironment();
  const pmrem = new PMREMGenerator(renderer);
  const reflections = pmrem.fromScene(studio, .08);
  scene.environment = reflections.texture;
  scene.environmentIntensity = 1.04;
  studio.dispose();
  pmrem.dispose();
  const fill = new AmbientLight("#ebc69c", .56);
  const key = new DirectionalLight("#ffe3b0", 1.95);
  key.position.set(-3, 5, 4);
  const rim = new DirectionalLight("#ffb873", 1.26);
  rim.position.set(3, 2, -4);
  scene.add(fill, key, rim);
  const camera = new PerspectiveCamera(34, 1, .1, 16);
  camera.position.set(0, .16, 5.85);
  camera.lookAt(0, .035, 0);

  const model = createConcierge();
  scene.add(model.root);
  renderer.outputColorSpace = SRGBColorSpace;
  renderer.toneMapping = ACESFilmicToneMapping;
  renderer.toneMappingExposure = 1.19;
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 1.5));
  const canvas = renderer.domElement;
  canvas.className = "wavo-concierge-canvas";
  canvas.setAttribute("aria-hidden", "true");
  host.prepend(canvas);
  host.dataset.mesh = "";
  let visible = false;
  let frame = 0;
  let disposed = false;
  let lastFrame = 0;
  let yaw = -.105, desiredYaw = yaw;
  let pitch = 0, desiredPitch = 0;
  let winkAt = -100;
  let strollAt = -100;
  let previousMode = "";
  let startSpeak = 0;
  let talking = 0;
  let blockClick = false;
  let gesture: { id: number; x: number; y: number; lastX: number; lastY: number; active: boolean } | undefined;
  const callPanel = host.closest<HTMLElement>(".call-avatar");
  const started = performance.now();

  function animate(now: number) {
    frame = 0;
    if (disposed || !visible || document.hidden) return;
    // This small preview looks smooth at 30 fps and leaves the voice controls responsive.
    if (now - lastFrame >= 31) {
      lastFrame = now;
      const time = (now - started) / 1000;
      const mode = callPanel?.dataset.mode || "idle";
      if (mode === "speaking" && previousMode !== "speaking") startSpeak = time;
      previousMode = mode;
      const speech = time - startSpeak;
      const jaw = mode === "speaking" && !reduced.matches
        ? .13 + .63 * Math.pow(.5 + .5 * Math.sin(speech * 14 + Math.sin(speech * 8)), 1.4)
        : 0;
      talking += (jaw - talking) * .38;
      const autoBlink = reduced.matches ? 0 : Math.max(0, 1 - Math.abs(time % 5.3 - 4.65) / .128);
      const winkTime = now / 1000 - winkAt;
      const wink = Math.max(0, Math.sin(Math.PI * Math.min(1, winkTime / .36)));
      const wave = time - strollAt;
      const automaticStep = Math.max(0, time % 15 - 12.8);
      const step = wave < 1.7 ? wave : automaticStep;
      const stride = reduced.matches ? 0 : Math.sin(Math.PI * Math.min(1, step / 1.7));
      yaw += (desiredYaw - yaw) * .28;
      pitch += (desiredPitch - pitch) * .23;
      model.root.rotation.set(pitch, yaw % tau, 0);
      model.pose(1 - Math.max(autoBlink, wink), 1 - autoBlink, talking, wink, step * 10, stride);
      renderer.render(scene, camera);
    }
    if (!reduced.matches || Math.abs(desiredYaw - yaw) > .002 || Math.abs(desiredPitch - pitch) > .002 || now / 1000 - winkAt < .4) {
      frame = requestAnimationFrame(animate);
    }
  }
  function redraw() {
    if (!frame && visible && !document.hidden && !disposed) {
      frame = requestAnimationFrame(animate);
    }
  }
  function measure() {
    const size = host.clientWidth;
    if (!size) return;
    renderer.setSize(size, size, false);
    lastFrame = 0;
    redraw();
  }

  function begin(event: PointerEvent) {
    if (!event.isPrimary || event.button !== 0) return;
    gesture = { id: event.pointerId, x: event.clientX, y: event.clientY, lastX: event.clientX, lastY: event.clientY, active: false };
    blockClick = false;
  }
  function move(event: PointerEvent) {
    if (!gesture || event.pointerId !== gesture.id) return;
    const dx = event.clientX - gesture.x, dy = event.clientY - gesture.y;
    if (!gesture.active) {
      if (Math.abs(dx) < 6 || Math.abs(dx) < Math.abs(dy)) return;
      gesture.active = blockClick = true;
      host.setPointerCapture(event.pointerId);
      host.dataset.orbiting = "";
    }
    desiredYaw += (event.clientX - gesture.lastX) * .026;
    desiredPitch = Math.max(-.32, Math.min(.32, desiredPitch + (event.clientY - gesture.lastY) * .007));
    gesture.lastX = event.clientX;
    gesture.lastY = event.clientY;
    redraw();
  }
  function release(event: PointerEvent) {
    if (!gesture || event.pointerId !== gesture.id) return;
    gesture = undefined;
    delete host.dataset.orbiting;
  }
  function greet(event: MouseEvent) {
    if (blockClick && event.detail > 0) {
      event.stopImmediatePropagation();
      event.preventDefault();
      blockClick = false;
      return;
    }
    if (reduced.matches) return;
    winkAt = performance.now() / 1000;
    strollAt = (performance.now() - started) / 1000;
    redraw();
  }
  function turn(event: KeyboardEvent) {
    if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
    event.preventDefault();
    desiredYaw += event.key === "ArrowLeft" ? -.57 : .57;
    desiredPitch = 0;
    redraw();
  }

  const resize = new ResizeObserver(measure);
  const viewport = new IntersectionObserver(([entry]) => {
    visible = entry.isIntersecting;
    redraw();
  });
  const lifecycle = new MutationObserver(() => {
    if (!host.isConnected) dispose();
  });
  function dispose() {
    if (disposed) return;
    disposed = true;
    cancelAnimationFrame(frame);
    viewport.disconnect();
    resize.disconnect();
    lifecycle.disconnect();
    document.removeEventListener("visibilitychange", redraw);
    reduced.removeEventListener("change", redraw);
    host.removeEventListener("pointerdown", begin);
    window.removeEventListener("pointermove", move);
    window.removeEventListener("pointerup", release);
    window.removeEventListener("pointercancel", release);
    host.removeEventListener("click", greet, true);
    host.removeEventListener("keydown", turn);
    model.dispose();
    reflections.dispose();
    renderer.dispose();
    renderer.forceContextLoss();
    canvas.remove();
    delete host.dataset.mesh;
    mounted.delete(host);
  }
  canvas.addEventListener("webglcontextlost", dispose, { once: true });
  resize.observe(host);
  viewport.observe(host);
  lifecycle.observe(document.body, { childList: true, subtree: true });
  document.addEventListener("visibilitychange", redraw);
  reduced.addEventListener("change", redraw);
  host.addEventListener("pointerdown", begin);
  window.addEventListener("pointermove", move);
  window.addEventListener("pointerup", release);
  window.addEventListener("pointercancel", release);
  host.addEventListener("click", greet, true);
  host.addEventListener("keydown", turn);
}
