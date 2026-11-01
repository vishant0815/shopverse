"use client";

import { useEffect, useRef, useState } from "react";

const STORAGE_KEY = "theme";

function currentTheme() {
  return document.documentElement.dataset.theme === "light" ? "light" : "dark";
}

// Same rule as the early script in layout.js: saved choice first, then the device setting.
function preferredTheme() {
  let saved = null;
  try {
    saved = localStorage.getItem(STORAGE_KEY);
  } catch {
    // storage blocked
  }
  if (saved === "light" || saved === "dark") return saved;
  return window.matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark";
}

function saveTheme(theme) {
  try {
    localStorage.setItem(STORAGE_KEY, theme);
  } catch {
    // Storage can be blocked (private mode); the switch still works for this visit.
  }
}

export default function ThemeSwitch() {
  const button = useRef(null);
  const [theme, setTheme] = useState(null); // unknown until mounted, to match the server render

  useEffect(() => {
    // Safety net: if anything replaced the page's theme attribute, put the right one back.
    const theme = preferredTheme();
    if (document.documentElement.dataset.theme !== theme) document.documentElement.dataset.theme = theme;
    setTheme(theme);
  }, []);

  function apply(next) {
    document.documentElement.dataset.theme = next;
    setTheme(next);
    saveTheme(next);
  }

  async function toggle() {
    const next = currentTheme() === "dark" ? "light" : "dark";
    const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (!document.startViewTransition || reduceMotion) {
      apply(next);
      return;
    }

    // A circle centred on this button, big enough at full size to cover the farthest corner.
    const box = button.current.getBoundingClientRect();
    const x = box.left + box.width / 2;
    const y = box.top + box.height / 2;
    const radius = Math.hypot(Math.max(x, window.innerWidth - x), Math.max(y, window.innerHeight - y));
    const closed = `circle(0px at ${x}px ${y}px)`;
    const open = `circle(${radius}px at ${x}px ${y}px)`;

    const root = document.documentElement;
    root.dataset.switching = next === "dark" ? "to-dark" : "to-light";
    const transition = document.startViewTransition(() => apply(next));
    try {
      await transition.ready;
      const timing = { duration: 750, easing: "cubic-bezier(0.7, 0, 0.3, 1)" };
      if (next === "dark") {
        // Darkness pours out of the switch...
        root.animate({ clipPath: [closed, open] }, { ...timing, pseudoElement: "::view-transition-new(root)" });
      } else {
        // ...and is pulled back into it.
        root.animate({ clipPath: [open, closed] }, { ...timing, pseudoElement: "::view-transition-old(root)" });
      }
      await transition.finished;
    } finally {
      delete root.dataset.switching;
    }
  }

  const label = theme === "dark" ? "Switch to light theme" : theme === "light" ? "Switch to dark theme" : "Switch theme";

  return (
    <button ref={button} type="button" onClick={toggle} className="theme-switch" aria-label={label} title={label}>
      <svg className="icon" style={{ left: "0.55rem" }} viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
        <circle cx="12" cy="12" r="5" />
        <g stroke="currentColor" strokeWidth="2" strokeLinecap="round">
          <path d="M12 1v2M12 21v2M4.2 4.2l1.4 1.4M18.4 18.4l1.4 1.4M1 12h2M21 12h2M4.2 19.8l1.4-1.4M18.4 5.6l1.4-1.4" />
        </g>
      </svg>
      <svg className="icon" style={{ right: "0.55rem" }} viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
        <path d="M20 15.5A8.5 8.5 0 0 1 8.5 4a8.5 8.5 0 1 0 11.5 11.5z" />
      </svg>
      <span className="knob" aria-hidden="true" />
    </button>
  );
}
