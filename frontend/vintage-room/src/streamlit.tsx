import { useState } from "react";
import { createRoot, type Root } from "react-dom/client";
import { useReducedMotion } from "motion/react";
import { PhotoRoom } from "./PhotoRoom";
import "./room.css";

type RoomData = { entrance?: string; compact?: boolean };
type MountArgs = {
  parentElement: HTMLElement | ShadowRoot;
  data: RoomData;
  setTriggerValue: (key: string, value: boolean) => void;
};

function VintageRoom({
  compact,
  telephone,
}: {
  compact?: boolean;
  telephone: () => void;
}) {
  const [light, setLight] = useState(false);
  const reduced = Boolean(useReducedMotion());
  return (
    <section
      className={`photo-experience${compact ? " compact-room" : ""}`}
      data-theme={light ? "light" : "dark"}
      aria-label="Wavo's interactive hotel room"
    >
      <PhotoRoom
        light={light}
        reduced={reduced}
        onToggle={() => setLight((value) => !value)}
        onPhone={telephone}
      />
      <p className="sr-only" role="status">
        {light ? "The lamp is on." : "The lamp is off."}
      </p>
    </section>
  );
}

const rooms = new WeakMap<HTMLElement, Root>();

export default function mount({
  parentElement,
  data,
  setTriggerValue,
}: MountArgs) {
  const container = parentElement.querySelector<HTMLElement>(".wavo-room-root");
  if (!container) return;
  let root = rooms.get(container);
  if (!root) {
    root = createRoot(container);
    rooms.set(container, root);
  }
  root.render(
    <VintageRoom
      compact={data.compact}
      telephone={() => {
        if (data.entrance)
          window.location.assign(new URL(data.entrance, document.baseURI));
        else setTriggerValue("telephone", true);
      }}
    />,
  );
  return () => {
    // Streamlit may run a render cleanup before passing updated component data.
    // Dispose only when the host has actually been detached.
    requestAnimationFrame(() => {
      if (container.isConnected) return;
      rooms.get(container)?.unmount();
      rooms.delete(container);
    });
  };
}
