import { useEffect, useRef } from "react";

/** Drawn in viewport coordinates so it also points correctly from the mobile box. */
export function PhoneHintArrow() {
  const path = useRef<SVGPathElement>(null!);
  useEffect(() => {
    const room = path.current.getRootNode() as Document | ShadowRoot;
    const hint = room.querySelector("#phone-hint");
    const button = room.querySelector(".photo-phone");
    const stage = room.querySelector(".photo-stage");
    if (!hint || !button || !stage) return;
    const clamp = (v: number, lo: number, hi: number) =>
      Math.min(hi, Math.max(lo, v));
    function update() {
      const box = hint!.getBoundingClientRect(),
        target = button!.getBoundingClientRect();
      const desktop = window.innerWidth > 700;
      const endX = desktop
        ? target.right + 9
        : target.left + target.width * 0.68;
      const endY = target.top + target.height * 0.35;
      let x: number, y: number;
      if (desktop && endX < box.left) {
        // Same descending sweep as the reference: box's lower-left side to shelf.
        x = box.left + 1;
        y = box.top + box.height * 0.76;
        path.current.setAttribute(
          "d",
          `M ${x} ${y} C ${x - 14} ${y + 20}, ${endX + 24} ${endY - 10}, ${endX} ${endY}`,
        );
        return;
      } else if (endX < box.left) {
        x = box.left + 1;
        y = clamp(endY, box.top + 20, box.bottom - 20);
      } else if (endY < box.top) {
        x = clamp(endX, box.left + 22, box.right - 22);
        y = box.top + 1;
      } else if (endX > box.right) {
        x = box.right - 1;
        y = clamp(endY, box.top + 20, box.bottom - 20);
      } else {
        x = clamp(endX, box.left + 22, box.right - 22);
        y = box.bottom - 1;
      }
      const dx = endX - x,
        dy = endY - y;
      path.current.setAttribute(
        "d",
        `M ${x} ${y} C ${x + dx * 0.45} ${y + dy * 0.12}, ${x + dx * 0.65} ${y + dy * 0.88}, ${endX} ${endY}`,
      );
    }
    const observer = new ResizeObserver(update);
    observer.observe(hint);
    observer.observe(stage);
    window.addEventListener("resize", update);
    window.addEventListener("scroll", update, true);
    // Track the box's short entrance animation, then stop doing per-frame work.
    let frame = 0;
    const until = performance.now() + 350;
    function settle(now: number) {
      update();
      if (now < until) frame = requestAnimationFrame(settle);
    }
    frame = requestAnimationFrame(settle);
    return () => {
      observer.disconnect();
      cancelAnimationFrame(frame);
      window.removeEventListener("resize", update);
      window.removeEventListener("scroll", update, true);
    };
  }, []);
  return (
    <svg className="phone-hint-arrow" aria-hidden="true">
      <defs>
        <filter
          id="reference-arrow-glow"
          x="-40%"
          y="-70%"
          width="180%"
          height="240%"
          colorInterpolationFilters="sRGB"
        >
          <feGaussianBlur
            in="SourceGraphic"
            stdDeviation="1.6"
            result="softGlow"
          />
          <feMerge>
            <feMergeNode in="softGlow" />
            <feMergeNode in="SourceGraphic" />
          </feMerge>
        </filter>
        <marker
          id="phone-hint-arrowhead"
          markerWidth="12"
          markerHeight="12"
          refX="10"
          refY="6"
          orient="auto"
          markerUnits="strokeWidth"
        >
          <path
            d="M 2 1.5 L 10 6 L 2 10.5"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.2"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        </marker>
      </defs>
      <path
        ref={path}
        fill="none"
        stroke="currentColor"
        strokeWidth="2.4"
        strokeLinecap="round"
        markerEnd="url(#phone-hint-arrowhead)"
        filter="url(#reference-arrow-glow)"
      />
    </svg>
  );
}
