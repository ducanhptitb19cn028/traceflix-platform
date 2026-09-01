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

// labels/out are only read for the experiments that declare them (live replay);
// the others ignore whatever is on the query string.
export const offlineRunUrl = (p) =>
  `/api/offline/run?key=${p.key}&episodes=${p.episodes}` +
  `&configs=${encodeURIComponent(p.configs)}&seeds=${encodeURIComponent(p.seeds)}` +
  `&labels=${encodeURIComponent(p.labels)}&out=${encodeURIComponent(p.out)}`;

export const figureUrl = (name) => `/api/results/figures/${name}`;

export const streamingStreamUrl = (p) =>
  `/api/streaming/stream?episodes=${p.episodes}` +
  `&max_windows=${p.maxWindows}&delay_ms=${p.delayMs}`;

// The live pages attach to an always-on engine — no run parameters, no trigger.
export const liveStreamUrl = (kind) => `/api/live/${kind}/stream`;

// MELT page: the pillar catalogue, and the engine's rolling buffer of raw windows
// so the charts are populated before the first snapshot arrives over SSE.
export const meltInfoUrl = (kind) => `/api/melt/info?kind=${kind}`;
export const meltWindowsUrl = (kind, limit = 1350) =>
  `/api/melt/windows?kind=${kind}&limit=${limit}`;

export const liveControl = (kind, opts) => {
  const q = Object.entries(opts).map(([k, v]) => `${k}=${v}`).join("&");
  return getJSON(`/api/live/${kind}/control?${q}`);
};
