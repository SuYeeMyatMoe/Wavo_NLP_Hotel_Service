import { useEffect, useRef, useState } from "react";
import { createPhotoRenderer } from "./photoRenderer";
import { createChainRenderer } from "./chainRenderer";
import { PhoneHintArrow } from "./PhoneHintArrow";
const asset = (name: string) =>
  new URL(`app/static/vintage-room/${name}`, document.baseURI).href;
type Props = {
  light: boolean;
  reduced: boolean;
  onToggle: () => void;
  onPhone: () => void;
};
export function PhotoRoom({ light, reduced, onToggle, onPhone }: Props) {
  const stage = useRef<HTMLDivElement>(null!),
    canvas = useRef<HTMLCanvasElement>(null!),
    chainCanvas = useRef<HTMLCanvasElement>(null!),
    handle = useRef<HTMLButtonElement>(null!);
  const [ready, setReady] = useState(false);
  const [hintReady, setHintReady] = useState(false),
    [hintDismissed, setHintDismissed] = useState(false);
  useEffect(() => {
    if (!ready) return;
    let timer: ReturnType<typeof setTimeout>,
      remaining = 5000,
      started = 0;
    function visibility() {
      clearTimeout(timer);
      if (document.hidden) {
        if (started) remaining -= performance.now() - started;
        started = 0;
      } else {
        started = performance.now();
        timer = setTimeout(() => setHintReady(true), Math.max(0, remaining));
      }
    }
    visibility();
    document.addEventListener("visibilitychange", visibility);
    return () => {
      clearTimeout(timer);
      document.removeEventListener("visibilitychange", visibility);
    };
  }, [ready]);
  const state = useRef({
    hover: false,
    drag: false,
    tx: 0,
    ty: 0,
    startX: 0,
    startY: 0,
    startTX: 0,
    startTY: 0,
    moved: 0,
    pull: 0,
    hoverArmed: true,
    ballX: 551,
    ballY: 632,
  });
  const config = useRef({ light, reduced });
  config.current = { light, reduced };
  useEffect(() => {
    let cancelled = false,
      frame = 0;
    let photo: ReturnType<typeof createPhotoRenderer> = null,
      chain: ReturnType<typeof createChainRenderer> | null = null;
    const cleaned = new Image(),
      daylight = new Image(),
      brownPlate = new Image(),
      lightPlate = new Image();
    cleaned.src = asset("room-brown-bare.png");
    daylight.src = asset("room-light-bare.png");
    brownPlate.src = asset("room-brown-plant-plate.png");
    lightPlate.src = asset("room-light-plant-plate.png");
    Promise.all([
      cleaned.decode(),
      daylight.decode(),
      brownPlate.decode(),
      lightPlate.decode(),
    ])
      .then(() => {
        if (cancelled) return;
        photo = createPhotoRenderer(
          canvas.current,
          cleaned,
          daylight,
          brownPlate,
          lightPlate,
        );
        chain = createChainRenderer(chainCanvas.current);
        let last = 0,
          start = 0,
          amount = 0,
          shown = false;
        function animate(now: number) {
          if (cancelled) return;
          if (!last) {
            last = start = now;
          }
          const dt = Math.min((now - last) / 1000, 0.032);
          last = now;
          const s = state.current,
            c = config.current;
          amount += (Number(c.light) - amount) * (1 - Math.exp(-dt * 4.5));
          photo?.draw(0, 0, (now - start) / 1000, amount, !c.reduced);
          const ball = chain!.draw(
            dt,
            s.tx,
            s.ty,
            s.hover || s.drag,
            s.drag,
            c.light,
          );
          s.ballX = ball.x;
          s.ballY = ball.y;
          handle.current.style.left = `${(ball.x / 1670) * 100}%`;
          handle.current.style.top = `${(ball.y / 941) * 100}%`;
          handle.current.dataset.positionX = ball.x.toFixed(1);
          handle.current.dataset.positionY = ball.y.toFixed(1);
          handle.current.dataset.depth = ball.z.toFixed(1);
          if (!shown) {
            shown = true;
            setReady(true);
          }
          frame = requestAnimationFrame(animate);
        }
        frame = requestAnimationFrame(animate);
      })
      .catch(() => setReady(true));
    return () => {
      cancelled = true;
      cancelAnimationFrame(frame);
      photo?.dispose();
      chain?.dispose();
    };
  }, []);
  function point(e: React.PointerEvent) {
    const r = stage.current.getBoundingClientRect();
    return {
      x: ((e.clientX - r.left) / r.width) * 1670,
      y: ((e.clientY - r.top) / r.height) * 941,
    };
  }
  function move(e: React.PointerEvent) {
    const p = point(e),
      s = state.current;
    if (s.drag) {
      const dx = p.x - s.startX,
        dy = p.y - s.startY;
      s.moved = Math.max(s.moved, Math.hypot(dx, dy));
      s.pull = Math.max(s.pull, dy);
      s.tx = Math.max(-110, Math.min(110, s.startTX + dx));
      s.ty = Math.max(-120, Math.min(60, s.startTY + dy));
      return;
    }
    const near = Math.abs(p.x - s.ballX) < 95 && p.y > 453 && p.y < 745;
    if (!s.hoverArmed) {
      s.hover = false;
      if (!near) s.hoverArmed = true;
      return;
    }
    s.hover = near;
    if (s.hover) {
      s.tx = Math.max(-90, Math.min(90, (p.x - 551) * 0.9));
      s.ty = Math.max(-110, Math.min(55, p.y - 632));
    }
  }
  function end(e: React.PointerEvent, cancel = false) {
    const s = state.current;
    if (!s.drag) return;
    s.drag = s.hover = false;
    s.hoverArmed = false;
    if (!cancel && s.moved < 7) onToggle();
    if (e.currentTarget.hasPointerCapture(e.pointerId))
      e.currentTarget.releasePointerCapture(e.pointerId);
  }
  return (
    <section className="photo-room-shell">
      <div
        ref={stage}
        data-hint-ready={hintReady}
        className={`photo-stage ${light ? "lamp-on" : "lamp-off"} ${ready ? "photo-ready" : ""}`}
        onPointerMove={move}
        onPointerLeave={() => {
          if (!state.current.drag) {
            state.current.hover = false;
            state.current.hoverArmed = true;
          }
        }}
      >
        <img
          className="reference-photo cleaned-fallback"
          src={asset("room-brown-bare.png")}
          alt="Vintage room with a brass lamp, plants and antique telephone; no navigation bar"
          draggable={false}
        />
        <canvas
          ref={canvas}
          className={`animated-photo ${ready ? "ready" : ""}`}
          aria-hidden="true"
        />
        <canvas
          ref={chainCanvas}
          className="chain-3d-canvas"
          aria-hidden="true"
        />
        <button
          className="lamp-body-switch"
          aria-label="Switch the lamp and room theme"
          aria-pressed={light}
          onClick={onToggle}
        >
          <span className="sr-only">Switch the lamp</span>
        </button>
        <button
          ref={handle}
          className="photo-chain"
          aria-label="Drag the independent 3D brass chain or click to switch the lamp"
          aria-pressed={light}
          onPointerDown={(e) => {
            e.preventDefault();
            e.currentTarget.setPointerCapture(e.pointerId);
            const p = point(e),
              s = state.current;
            s.drag = true;
            s.startX = p.x;
            s.startY = p.y;
            s.startTX = s.ballX - 551;
            s.startTY = s.ballY - 632;
            s.moved = s.pull = 0;
          }}
          onPointerUp={(e) => end(e)}
          onPointerCancel={(e) => end(e, true)}
          onKeyDown={(e) => {
            if (e.key === "Enter" || e.key === " ") {
              e.preventDefault();
              onToggle();
            }
          }}
        >
          <span className="sr-only">Independent 3D lamp chain</span>
        </button>
        <button
          className="photo-phone"
          aria-label="Press the brass telephone button to open AI reception"
          aria-describedby={
            hintReady && !hintDismissed ? "phone-hint" : undefined
          }
          onClick={() => {
            setHintDismissed(true);
            onPhone();
          }}
        >
          <span className="sr-only">Use telephone</span>
        </button>
        {hintReady && !hintDismissed && (
          <>
            <aside className="phone-hint" id="phone-hint" aria-live="polite">
              <button
                className="hint-close"
                aria-label="Dismiss telephone instructions"
                onClick={() => setHintDismissed(true)}
              >
                ×
              </button>
              <h2>
                <span aria-hidden="true">☎</span> Call the AI
              </h2>
              <p>
                Press the button on the phone to start a conversation with the
                AI.
              </p>
            </aside>
            <PhoneHintArrow />
          </>
        )}
      </div>
    </section>
  );
}
