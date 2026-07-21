// Tiny API helper. In dev, Vite proxies /api -> FastAPI (localhost:8000);
// in production the SPA is served by FastAPI, so /api is same-origin.

export async function getJSON(path) {
  const r = await fetch(path);
  if (!r.ok) throw new Error(`${path} -> ${r.status}`);
  return r.json();
}

export const onlineStreamUrl = (p) =>
  `/api/online/stream?config=${p.config}&episodes=${p.episodes}` +
  `&include_periodic=${p.includePeriodic}&max_windows=${p.maxWindows}` +
  `&delay_ms=${p.delayMs}`;

export const offlineRunUrl = (p) =>
  `/api/offline/run?key=${p.key}&episodes=${p.episodes}` +
  `&configs=${encodeURIComponent(p.configs)}`;

export const figureUrl = (name) => `/api/results/figures/${name}`;

export const streamingStreamUrl = (p) =>
  `/api/streaming/stream?episodes=${p.episodes}` +
  `&max_windows=${p.maxWindows}&delay_ms=${p.delayMs}`;

// The live pages attach to an always-on engine — no run parameters, no trigger.
export const liveStreamUrl = (kind) => `/api/live/${kind}/stream`;

export const liveControl = (kind, opts) => {
  const q = Object.entries(opts).map(([k, v]) => `${k}=${v}`).join("&");
  return getJSON(`/api/live/${kind}/control?${q}`);
};
