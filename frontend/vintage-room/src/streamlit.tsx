import { useEffect, useState } from "react";
import { createRoot, type Root } from "react-dom/client";
import { useReducedMotion } from "motion/react";
import { PhotoRoom } from "./PhotoRoom";
import "./room.css";

type RoomData = { entrance?: string };
type MountArgs = {
  parentElement: HTMLElement | ShadowRoot;
  data: RoomData;
  setTriggerValue: (key: string, value: boolean) => void;
};

function VintageRoom({
  telephone,
}: {
  telephone: () => void;
}) {
  const [light, setLight] = useState(() => {
    const active = document.documentElement.dataset.wavoTheme;
    if (active) return active === "light";
    try {
      return localStorage.getItem("wavo.hotel.theme") === "light";
    } catch {
      return false;
    }
  });
  useEffect(() => {
    function syncTheme() {
      setLight(document.documentElement.dataset.wavoTheme === "light");
    }
    window.addEventListener("wavo:theme-changed", syncTheme);
    return () => window.removeEventListener("wavo:theme-changed", syncTheme);
  }, []);
  const reduced = Boolean(useReducedMotion());
  return (
    <section
      className="photo-experience"
      data-theme={light ? "light" : "dark"}
      aria-label="Wavo's interactive hotel room"
    >
      <PhotoRoom
        light={light}
        reduced={reduced}
        onToggle={() => {
          const theme = light ? "dark" : "light";
          document.documentElement.dataset.wavoTheme = theme;
          setLight(!light);
          window.dispatchEvent(new CustomEvent("wavo:set-theme", { detail: theme }));
        }}
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
