/* Original line icons (24×24, stroke). Injected into any element with data-icon="name". */
"use strict";
const ICONS = {
  home: "M3 11 12 4l9 7M5 10v10h5v-6h4v6h5V10",
  chat: "M4 5h16v11H9l-5 4z",
  mic: "M12 3a3 3 0 0 1 3 3v6a3 3 0 0 1-6 0V6a3 3 0 0 1 3-3zM5 11a7 7 0 0 0 14 0M12 18v3",
  memory: "M7 4h10v16H7zM4 8h3M4 12h3M4 16h3M17 8h3M17 12h3M17 16h3M10 8h4v8h-4z",
  devices: "M3 5h13v10H3zM7 19h5M9.5 15v4M17 9h4v11h-4z",
  control: "M4 6h16M4 12h16M4 18h16M8 4v4M15 10v4M10 16v4",
  history: "M3 12a9 9 0 1 0 3-6.7L3 8M3 3v5h5M12 7v5l3 2",
  ai: "M12 3l2.2 5.8L20 11l-5.8 2.2L12 19l-2.2-5.8L4 11l5.8-2.2z",
  shield: "M12 3l8 3v6c0 4.5-3.4 8.2-8 9-4.6-.8-8-4.5-8-9V6z",
  logout: "M10 4H5v16h5M14 8l4 4-4 4M18 12H9",
  settings: "M12 9a3 3 0 1 1 0 6 3 3 0 0 1 0-6zM12 2v3M12 19v3M4.2 4.2l2.1 2.1M17.7 17.7l2.1 2.1M2 12h3M19 12h3M4.2 19.8l2.1-2.1M17.7 6.3l2.1-2.1",
  tools: "M14 6a4 4 0 0 0 5 5l-9 9-3-3 9-9a4 4 0 0 0-2-2zM4 4l4 4",
  send: "M4 12 20 4l-6 16-3-7z",
  stop: "M7 7h10v10H7z",
  close: "M6 6l12 12M18 6 6 18",
  plus: "M12 5v14M5 12h14",
  back: "M15 5l-7 7 7 7",
  refresh: "M20 11a8 8 0 1 0-2.3 5.7M20 4v7h-7",
  trash: "M4 7h16M9 7V4h6v3M6 7l1 13h10l1-13",
  sync: "M4 12a8 8 0 0 1 14-5l2 2M20 12a8 8 0 0 1-14 5l-2-2M20 4v5h-5M4 20v-5h5",
  more: "M5 12h.01M12 12h.01M19 12h.01",
  android: "M7 9h10v8H7zM9 17v3M15 17v3M5 10v5M19 10v5M8 6l-1-2M16 6l1-2M7 9a5 5 0 0 1 10 0",
  windows: "M3 5l8-1v8H3zM13 4l8-1v9h-8zM3 13h8v8l-8-1zM13 13h8v9l-8-1z",
  cloud: "M7 18a4 4 0 0 1-.5-8A6 6 0 0 1 18 9a4.5 4.5 0 0 1-1 9z",
  web: "M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18zM3 12h18M12 3c3 3 3 15 0 18M12 3c-3 3-3 15 0 18",
  apps: "M4 4h6v6H4zM14 4h6v6h-6zM4 14h6v6H4zM14 14h6v6h-6z",
  camera: "M4 8h4l2-3h4l2 3h4v11H4zM12 10a3.5 3.5 0 1 1 0 7 3.5 3.5 0 0 1 0-7z",
  phone: "M5 4h4l2 5-3 2a11 11 0 0 0 5 5l2-3 5 2v4a2 2 0 0 1-2 2A17 17 0 0 1 3 6a2 2 0 0 1 2-2z",
  message: "M4 5h16v11H8l-4 4zM8 10h8",
  note: "M6 3h9l4 4v14H6zM15 3v4h4M9 12h6M9 16h6",
  alarm: "M12 7v5l3 2M12 4a8 8 0 1 0 0 16 8 8 0 0 0 0-16zM4 4l3-2M20 4l-3-2",
  battery: "M3 8h15v8H3zM20 11v2M6 11v2",
  folder: "M3 6h6l2 2h10v11H3z",
  doc: "M6 3h9l4 4v14H6zM15 3v4h4M9 13h6M9 17h4",
  search: "M11 4a7 7 0 1 1 0 14 7 7 0 0 1 0-14zM20 20l-4-4",
  code: "M8 7l-5 5 5 5M16 7l5 5-5 5",
  check: "M5 12l4 4 10-10",
  clock: "M12 7v5l3 2M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18z",
  user: "M12 4a4 4 0 1 1 0 8 4 4 0 0 1 0-8zM4 21a8 8 0 0 1 16 0",
  star: "M12 3l2.7 5.6 6.2.9-4.5 4.4 1 6.1L12 17l-5.5 3 1.1-6.1L3 9.5l6.2-.9z",
};
function icon(name, size = 20) {
  const ns = "http://www.w3.org/2000/svg";
  const svg = document.createElementNS(ns, "svg");
  svg.setAttribute("viewBox", "0 0 24 24"); svg.setAttribute("width", size); svg.setAttribute("height", size);
  svg.setAttribute("aria-hidden", "true"); svg.classList.add("ic");
  const p = document.createElementNS(ns, "path");
  p.setAttribute("d", ICONS[name] || ICONS.star);
  svg.append(p);
  return svg;
}
function hydrateIcons(root = document) {
  root.querySelectorAll("[data-icon]:not([data-iconed])").forEach(n => {
    n.setAttribute("data-iconed", ""); n.prepend(icon(n.dataset.icon));
  });
}
