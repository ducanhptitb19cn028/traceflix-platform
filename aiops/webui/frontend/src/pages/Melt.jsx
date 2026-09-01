import { useEffect, useMemo, useRef, useState } from "react";
import {
  Area, AreaChart, Bar, BarChart, CartesianGrid, Legend, Line, LineChart,
  ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";
import { getJSON, liveStreamUrl, meltInfoUrl, meltWindowsUrl } from "../api.js";

// Where the windows on this page come from. The distinction is the whole point of
// the selector: one reads the deployed mesh, the other invents it, and a page that
// showed the four pillars without saying which would be worthless.
const SOURCES = [
  { key: "cluster", label: "🛰 Deployed cluster", real: true,
    hint: "PromQL / LogQL / TraceQL against the running stack. Needs TF_LIVE=1 and the port-forwards." },
  { key: "ml", label: "🧠 Generator", real: false,
    hint: "ml.dataset — plausible signals with injected labels. Always available, never evidence about the deployment." },
];

// Fields promoted to the mesh sweep: the one signal per pillar that a fault moves
// first. Everything else lives in the per-service panels below.
const HEADLINE = [
  { pillar: "metrics", key: "err_rate", label: "5xx rate", scale: "" },
  { pillar: "logs", key: "error_logs", label: "error logs", scale: "" },
  { pillar: "traces", key: "error_spans", label: "error spans", scale: "" },
  { pillar: "events", key: "__events", label: "k8s events", scale: "" },
];
const EVENT_KEYS = ["oomkilled", "crashloop", "pod_restarts", "unhealthy"];

const fmt = (v, scale = "") => {
  if (v == null || Number.isNaN(v)) return "—";
  switch (scale) {
    case "bytes":
      return v >= 1e9 ? (v / 1e9).toFixed(2) + " GB"
        : v >= 1e6 ? (v / 1e6).toFixed(1) + " MB"
        : v >= 1e3 ? (v / 1e3).toFixed(1) + " kB" : v.toFixed(0) + " B";
    case "s":
      return v >= 1 ? v.toFixed(2) + " s" : (v * 1000).toFixed(1) + " ms";
    case "ms":
      return v >= 1000 ? (v / 1000).toFixed(2) + " s" : v.toFixed(1) + " ms";
    case "ratio":
      return (v * 100).toFixed(1) + "%";
    default:
      return Math.abs(v) >= 1e6 ? (v / 1e6).toFixed(2) + "M"
        : Math.abs(v) >= 1000 ? Math.round(v).toLocaleString()
        : Number.isInteger(v) ? String(v) : v.toFixed(3);
  }
};

// The cluster engine stamps windows with wall-clock epoch seconds; the generator
// counts from zero. One axis has to read both.
const clock = (ts) =>
  ts == null ? "" : ts > 1e9
    ? new Date(ts * 1000).toLocaleTimeString([], { hour12: false })
    : "t+" + Math.round(ts) + "s";

// Fold new windows into the buffer, de-duplicated on the engine's sequence number
// and capped at what the engine itself keeps, so the page's window never claims
// more history than the backfill could restore after a reload.
const merge = (have, incoming) => {
  const seen = new Set(have.map((r) => r.seq));
  const add = incoming.filter((r) => !seen.has(r.seq));
  if (!add.length) return have;
  return [...have, ...add].sort((a, b) => a.seq - b.seq).slice(-1350);
};

const median = (xs) => {
  const a = xs.filter((v) => Number.isFinite(v)).sort((x, y) => x - y);
  if (!a.length) return 0;
  const m = a.length >> 1;
  return a.length % 2 ? a[m] : (a[m - 1] + a[m]) / 2;
};

function Chart({ title, note, children, height = 190 }) {
  return (
    <div style={{ flex: 1, minWidth: 300 }}>
      <div className="muted" style={{ fontSize: 12, marginBottom: 4 }}>
        <b style={{ color: "var(--text)" }}>{title}</b>{note && <> — {note}</>}
      </div>
      <ResponsiveContainer width="100%" height={height}>{children}</ResponsiveContainer>
    </div>
  );
}

const AXIS = { stroke: "#8a93a6", fontSize: 11 };
const TIP = {
  contentStyle: { background: "#161b24", border: "1px solid #2a2f3a", borderRadius: 8 },
  labelStyle: { color: "#8a93a6" },
};

export default function Melt() {
  const [kind, setKind] = useState("cluster");
  const [info, setInfo] = useState(null);
  const [rows, setRows] = useState([]);          // raw MELT windows, oldest first
  const [snap, setSnap] = useState(null);
  const [connected, setConnected] = useState(false);
  const [apiError, setApiError] = useState(null);
  const [picked, setPicked] = useState(null);    // null = follow the fault
  const esRef = useRef(null);

  // Re-attach whenever the source changes: catalogue, backfill, then the stream.
  useEffect(() => {
    let dead = false;
    setRows([]); setSnap(null); setInfo(null); setApiError(null); setConnected(false);
    esRef.current?.close();

    getJSON(meltInfoUrl(kind)).then((i) => !dead && setInfo(i))
      .catch((e) => !dead && setApiError(String(e)));
    // Merged, not assigned: the stream is already delivering by the time this
    // resolves, and replacing would drop whatever arrived in between. `seq` is
    // the engine's own counter, so it also absorbs the window the `start` event
    // repeats out of the snapshot.
    getJSON(meltWindowsUrl(kind)).then((d) => !dead && setRows((h) => merge(h, d.windows ?? [])))
      .catch(() => {});

    const es = new EventSource(liveStreamUrl(kind));
    esRef.current = es;
    es.onopen = () => setConnected(true);
    es.onmessage = (e) => {
      const ev = JSON.parse(e.data);
      if (!ev.melt) { setSnap((p) => ({ ...(p ?? {}), ...ev })); return; }
      setSnap(ev);
      setRows((h) => merge(h, [{
        seq: ev.seq, ts: ev.ts, service: ev.service, fault: ev.label_fault,
        label: ev.label === "anomaly" ? 1 : 0, ...ev.melt,
      }]));
    };
    es.onerror = () => setConnected(false);
    return () => { dead = true; es.close(); };
  }, [kind]);

  const pillars = info?.pillars ?? [];
  const services = info?.services ?? [];

  // Latest window per service = the mesh as it stands right now.
  const latest = useMemo(() => {
    const m = {};
    rows.forEach((r) => { m[r.service] = r; });
    return m;
  }, [rows]);

  // Each signal's own median over the buffer, per service. The sweep reports a
  // deviation against this rather than against a threshold: the deployed mesh
  // idles two orders of magnitude below the generator, so no fixed cut-off can
  // mean the same thing on both sources.
  const medians = useMemo(() => {
    const acc = {};
    HEADLINE.forEach(({ pillar, key }) => {
      services.forEach((s) => {
        const xs = rows.filter((r) => r.service === s).map((r) =>
          key === "__events"
            ? EVENT_KEYS.reduce((t, k) => t + (r.events?.[k] ?? 0), 0)
            : r[pillar]?.[key]);
        acc[s + "/" + key] = median(xs);
      });
    });
    return acc;
  }, [rows, services]);

  const faulted = services.filter((s) => latest[s] && latest[s].fault !== "normal");
  const service = picked ?? faulted[0] ?? services[0] ?? null;

  // One row per collected instant for the chosen service, flattened for recharts.
  const series = useMemo(() => rows
    .filter((r) => r.service === service)
    .map((r) => ({
      t: clock(r.ts), seq: r.seq, fault: r.fault, label: r.label,
      ...r.metrics, ...r.logs, ...r.traces, ...r.events,
      p50_ms: (r.metrics?.p50_latency ?? 0) * 1000,
      p99_ms: (r.metrics?.p99_latency ?? 0) * 1000,
      cpu_pct: (r.metrics?.cpu ?? 0) * 100,
      heap_mb: (r.metrics?.mem ?? 0) / 1e6,
      baseline_mb: (r.metrics?.mem_baseline_1h ?? 0) / 1e6,
      gc_ms: (r.metrics?.gc_pause ?? 0) * 1000,
      other_logs: Math.max(0, (r.logs?.log_volume ?? 0)
        - (r.logs?.error_logs ?? 0) - (r.logs?.warn_logs ?? 0) - (r.logs?.request_logs ?? 0)),
      events_total: EVENT_KEYS.reduce((t, k) => t + (r.events?.[k] ?? 0), 0),
    })), [rows, service]);

  const cur = latest[service];
  const eventsSeen = series.some((p) => p.events_total > 0);
  const status = snap?.status ?? info?.engine;
  const src = SOURCES.find((s) => s.key === kind);

  return (
    <div className="page">
      <h1>🔭 MELT — all four pillars, live</h1>
      <p className="subtitle">
        Every other live page shows what a <i>detector</i> made of the telemetry.
        This one shows the telemetry: the raw <b>Metrics</b>, <b>Events</b>,{" "}
        <b>Logs</b> and <b>Traces</b> of each window, exactly as the collectors
        returned them and before <code>build_features</code> selects the subset a
        configuration is allowed to see. C1 keeps only the metrics column below;
        C4 keeps all four. What the completeness result is a claim about is
        therefore visible here in full.
      </p>

      {/* ---- provenance: which of the two possible sources is on screen ---- */}
      <div className="controls">
        <label className="inline">source
          <select value={kind} onChange={(e) => { setKind(e.target.value); setPicked(null); }}>
            {SOURCES.map((s) => <option key={s.key} value={s.key}>{s.label}</option>)}
          </select>
        </label>
        <label className="inline">service
          <select value={service ?? ""} onChange={(e) => setPicked(e.target.value)}>
            {services.map((s) => (
              <option key={s} value={s}>
                {s}{latest[s]?.fault && latest[s].fault !== "normal" ? ` — ${latest[s].fault}` : ""}
              </option>
            ))}
          </select>
        </label>
        {picked && (
          <button className="btn primary" onClick={() => setPicked(null)}
            title="go back to showing whichever service is currently under fault">
            follow the fault
          </button>
        )}
      </div>

      <div style={{ margin: "4px 0 14px" }}>
        <span className={"chip " + (src?.real ? "chip-green" : "chip-amber")} title={src?.hint}>
          {src?.real ? "real telemetry — the deployed mesh" : "generated telemetry — not the deployment"}
        </span>
        <span className={"chip " + (connected ? "chip-green" : "chip-red")}>
          {connected ? "stream attached" : "stream detached"}
        </span>
        <span className="chip chip-muted">
          {rows.length.toLocaleString()} of {info?.capacity?.toLocaleString() ?? "—"} windows buffered
        </span>
        {info?.cadence_s != null && (
          <span className="chip chip-muted">one instant every {snap?.cadence_s ?? info.cadence_s}s</span>
        )}
        {faulted.length > 0 && (
          <span className="chip chip-red">
            under fault: {faulted.map((s) => `${s} (${latest[s].fault})`).join(", ")}
          </span>
        )}
      </div>

      {apiError && <div className="status err">API error — {apiError}</div>}
      {status === "error" && (
        <div className="callout warn">
          ⚠ <b>The {kind} engine is not collecting</b>
          {(snap?.error ?? info?.error) && <> — <code>{snap?.error ?? info?.error}</code></>}.
          {kind === "cluster" && (
            <> The cluster engine refuses to run without <code>TF_LIVE=1</code> rather
              than quietly serve generated telemetry as the mesh's. Start the
              port-forwards and set it, or switch the source above to the generator —
              which is honest about being one.</>
          )}
        </div>
      )}
      {!rows.length && status !== "error" && (
        <div className="hint">
          Waiting for the first windows. The engine collects all nine services per
          instant{info?.cadence_s ? `, every ${info.cadence_s}s` : ""}, so the panels
          below fill a sweep at a time.
        </div>
      )}

      {/* ---- the whole mesh at the latest instant ---- */}
      {rows.length > 0 && (
        <>
          <h3>🕸 The mesh right now — one row per service</h3>
          <div className="feed" style={{ maxHeight: 420 }}>
            <table className="table">
              <thead>
                <tr>
                  <th>service</th><th>truth</th>
                  {HEADLINE.map((h) => <th key={h.key} style={{ textAlign: "right" }}>{h.label}</th>)}
                  <th style={{ textAlign: "right" }} title="the largest of the four columns above, as a multiple of that same signal's median over the buffered windows for this service. A ratio, not a verdict — no detector runs on this page.">
                    peak × own median
                  </th>
                </tr>
              </thead>
              <tbody>
                {services.map((s) => {
                  const r = latest[s];
                  const vals = HEADLINE.map((h) => r == null ? null
                    : h.key === "__events"
                      ? EVENT_KEYS.reduce((t, k) => t + (r.events?.[k] ?? 0), 0)
                      : r[h.pillar]?.[h.key]);
                  const peak = Math.max(0, ...HEADLINE.map((h, i) => {
                    const m = medians[s + "/" + h.key];
                    return m > 0 && vals[i] != null ? vals[i] / m : 0;
                  }));
                  const anom = r && r.fault !== "normal";
                  return (
                    <tr key={s} style={s === service ? { background: "var(--panel2)" } : undefined}>
                      <td>
                        {/* a plain .btn has no background of its own and white
                            text, so it renders as white-on-white here; this cell
                            wants a link anyway, not a control */}
                        <button
                          onClick={() => setPicked(s)}
                          style={{
                            background: "none", border: "none", padding: 0,
                            cursor: "pointer", fontSize: 14, fontWeight: 600,
                            color: s === service ? "var(--blue)" : "var(--text)",
                          }}>{s}</button>
                      </td>
                      <td>
                        <span className={"chip " + (anom ? "chip-red" : "chip-green")}>
                          {r?.fault ?? "—"}
                        </span>
                      </td>
                      {vals.map((v, i) => (
                        <td key={i} style={{ textAlign: "right" }}>{fmt(v, HEADLINE[i].scale)}</td>
                      ))}
                      <td style={{ textAlign: "right",
                        color: peak >= 2 ? "var(--amber)" : "var(--muted)" }}>
                        {peak > 0 ? "×" + peak.toFixed(1) : "—"}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          <p className="muted" style={{ fontSize: 12, marginTop: -4 }}>
            The truth column is {src?.real
              ? "read from the Chaos Mesh resources actually injected into the namespace"
              : "the fault the generator injected"}, never inferred from the numbers
            beside it. Nothing on this page classifies anything.
          </p>
        </>
      )}

      {/* ---- the four pillars, for one service, over time ---- */}
      {series.length > 0 && (
        <>
          <h3>
            📈 Metrics — <code>{service}</code>
            <span className="chip chip-blue" style={{ marginLeft: 8 }}>Prometheus · PromQL</span>
            {cur?.fault && cur.fault !== "normal" &&
              <span className="chip chip-red">{cur.fault}</span>}
          </h3>
          <div className="chart-box">
            <div className="pipes" style={{ margin: 0 }}>
              <Chart title="Throughput and errors" note="per second, over the collector's 2 m window">
                <LineChart data={series}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#2a2f3a" />
                  <XAxis dataKey="t" {...AXIS} minTickGap={40} />
                  <YAxis {...AXIS} />
                  <Tooltip {...TIP} />
                  <Legend wrapperStyle={{ fontSize: 11 }} />
                  <Line type="monotone" dataKey="req_rate" name="requests/s" stroke="#3b82f6" dot={false} isAnimationActive={false} />
                  <Line type="monotone" dataKey="err_rate" name="5xx/s" stroke="#ef4444" dot={false} isAnimationActive={false} />
                </LineChart>
              </Chart>
              <Chart title="Latency" note="server-side histogram quantiles">
                <LineChart data={series}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#2a2f3a" />
                  <XAxis dataKey="t" {...AXIS} minTickGap={40} />
                  <YAxis {...AXIS} unit=" ms" />
                  <Tooltip {...TIP} />
                  <Legend wrapperStyle={{ fontSize: 11 }} />
                  <Line type="monotone" dataKey="p50_ms" name="p50" stroke="#22c55e" dot={false} isAnimationActive={false} />
                  <Line type="monotone" dataKey="p99_ms" name="p99" stroke="#f59e0b" dot={false} isAnimationActive={false} />
                </LineChart>
              </Chart>
            </div>
            <div className="pipes" style={{ margin: "14px 0 0" }}>
              <Chart title="JVM resources" note="CPU on the left axis, heap on the right — two different units, never one scale">
                <LineChart data={series}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#2a2f3a" />
                  <XAxis dataKey="t" {...AXIS} minTickGap={40} />
                  <YAxis yAxisId="l" {...AXIS} unit="%" />
                  <YAxis yAxisId="r" orientation="right" {...AXIS} unit=" MB" />
                  <Tooltip {...TIP} />
                  <Legend wrapperStyle={{ fontSize: 11 }} />
                  <Line yAxisId="l" type="monotone" dataKey="cpu_pct" name="CPU %" stroke="#3b82f6" dot={false} isAnimationActive={false} />
                  <Line yAxisId="r" type="monotone" dataKey="heap_mb" name="heap MB" stroke="#6366f1" dot={false} isAnimationActive={false} />
                  <Line yAxisId="r" type="monotone" dataKey="baseline_mb" name="1 h baseline (C4)" stroke="#8a93a6" strokeDasharray="4 3" dot={false} isAnimationActive={false} />
                </LineChart>
              </Chart>
              <Chart title="GC and threads" note="the two signals a saturation fault moves after CPU">
                <LineChart data={series}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#2a2f3a" />
                  <XAxis dataKey="t" {...AXIS} minTickGap={40} />
                  <YAxis yAxisId="l" {...AXIS} unit=" ms" />
                  <YAxis yAxisId="r" orientation="right" {...AXIS} />
                  <Tooltip {...TIP} />
                  <Legend wrapperStyle={{ fontSize: 11 }} />
                  <Line yAxisId="l" type="monotone" dataKey="gc_ms" name="GC pause ms/s" stroke="#f59e0b" dot={false} isAnimationActive={false} />
                  <Line yAxisId="r" type="monotone" dataKey="threads" name="threads" stroke="#22c55e" dot={false} isAnimationActive={false} />
                </LineChart>
              </Chart>
            </div>
            <p className="muted" style={{ fontSize: 11, marginBottom: 0 }}>
              The dashed 1 h heap baseline is read from VictoriaMetrics, not
              Prometheus, and is the only signal here that C4 adds over C3 — a leak
              is a departure from it rather than a level.
            </p>
          </div>

          <h3>
            🔔 Events — <code>{service}</code>
            <span className="chip chip-amber" style={{ marginLeft: 8 }}>Kubernetes API</span>
          </h3>
          <div className="chart-box">
            {eventsSeen ? (
              <Chart title="Pod-level events per window" note="discrete occurrences, not a rate" height={170}>
                <BarChart data={series}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#2a2f3a" />
                  <XAxis dataKey="t" {...AXIS} minTickGap={40} />
                  <YAxis {...AXIS} allowDecimals={false} />
                  <Tooltip {...TIP} />
                  <Legend wrapperStyle={{ fontSize: 11 }} />
                  <Bar dataKey="oomkilled" name="OOMKilled" stackId="e" fill="#ef4444" isAnimationActive={false} />
                  <Bar dataKey="crashloop" name="CrashLoopBackOff" stackId="e" fill="#f59e0b" isAnimationActive={false} />
                  <Bar dataKey="pod_restarts" name="BackOff" stackId="e" fill="#6366f1" isAnimationActive={false} />
                  <Bar dataKey="unhealthy" name="Unhealthy" stackId="e" fill="#3b82f6" isAnimationActive={false} />
                </BarChart>
              </Chart>
            ) : (
              <p className="muted" style={{ margin: 0 }}>
                No pod-level event fired for <code>{service}</code> across the{" "}
                {series.length} buffered window{series.length === 1 ? "" : "s"} — all
                four counters flat at zero. That is the normal state, and it is why
                events are the sparsest pillar: they carry a great deal when they
                fire and nothing at all the rest of the time.
                {src?.real && <> A zero here can also mean the collector could not read
                  the namespace at all, which degrades to zeros by design; the
                  Kubernetes API needs in-cluster RBAC or a kubeconfig.</>}
              </p>
            )}
          </div>

          <h3>
            📜 Logs — <code>{service}</code>
            <span className="chip chip-green" style={{ marginLeft: 8 }}>Loki · LogQL</span>
          </h3>
          <div className="chart-box">
            <div className="pipes" style={{ margin: 0 }}>
              <Chart title="Log volume by kind" note="count_over_time, 2 m window, stacked to the total">
                <AreaChart data={series}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#2a2f3a" />
                  <XAxis dataKey="t" {...AXIS} minTickGap={40} />
                  <YAxis {...AXIS} />
                  <Tooltip {...TIP} />
                  <Legend wrapperStyle={{ fontSize: 11 }} />
                  <Area type="monotone" dataKey="request_logs" name="request" stackId="l" stroke="#3b82f6" fill="#3b82f6" fillOpacity={0.35} isAnimationActive={false} />
                  <Area type="monotone" dataKey="warn_logs" name="warn" stackId="l" stroke="#f59e0b" fill="#f59e0b" fillOpacity={0.45} isAnimationActive={false} />
                  <Area type="monotone" dataKey="error_logs" name="error" stackId="l" stroke="#ef4444" fill="#ef4444" fillOpacity={0.55} isAnimationActive={false} />
                  <Area type="monotone" dataKey="other_logs" name="other" stackId="l" stroke="#8a93a6" fill="#8a93a6" fillOpacity={0.2} isAnimationActive={false} />
                </AreaChart>
              </Chart>
              <Chart title="Error and warning lines" note="the same two series unstacked, on their own scale">
                <LineChart data={series}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#2a2f3a" />
                  <XAxis dataKey="t" {...AXIS} minTickGap={40} />
                  <YAxis {...AXIS} />
                  <Tooltip {...TIP} />
                  <Legend wrapperStyle={{ fontSize: 11 }} />
                  <Line type="monotone" dataKey="error_logs" name="error / exception" stroke="#ef4444" dot={false} isAnimationActive={false} />
                  <Line type="monotone" dataKey="warn_logs" name="warn" stroke="#f59e0b" dot={false} isAnimationActive={false} />
                </LineChart>
              </Chart>
            </div>
            <p className="muted" style={{ fontSize: 11, marginBottom: 0 }}>
              <code>other</code> is the total minus the three matched classes, so a
              stack that is mostly grey means the service is logging something none
              of the three LogQL filters names.
            </p>
          </div>

          <h3>
            🕸 Traces — <code>{service}</code>
            <span className="chip" style={{ marginLeft: 8, background: "rgba(99,102,241,.16)", color: "#6366f1" }}>
              Tempo · TraceQL
            </span>
          </h3>
          <div className="chart-box">
            <div className="pipes" style={{ margin: 0 }}>
              <Chart title="Span duration" note="over the traces this service is the resource of">
                <LineChart data={series}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#2a2f3a" />
                  <XAxis dataKey="t" {...AXIS} minTickGap={40} />
                  <YAxis {...AXIS} unit=" ms" />
                  <Tooltip {...TIP} />
                  <Legend wrapperStyle={{ fontSize: 11 }} />
                  <Line type="monotone" dataKey="mean_span_ms" name="mean" stroke="#6366f1" dot={false} isAnimationActive={false} />
                  <Line type="monotone" dataKey="p99_span_ms" name="p99" stroke="#ef4444" dot={false} isAnimationActive={false} />
                </LineChart>
              </Chart>
              <Chart title="Traces and error spans" note="error spans are the trace-only signal — an error originating here">
                <BarChart data={series}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#2a2f3a" />
                  <XAxis dataKey="t" {...AXIS} minTickGap={40} />
                  <YAxis {...AXIS} />
                  <Tooltip {...TIP} />
                  <Legend wrapperStyle={{ fontSize: 11 }} />
                  <Bar dataKey="trace_count" name="traces" fill="#3b82f6" isAnimationActive={false} />
                  <Bar dataKey="error_spans" name="error spans" fill="#ef4444" isAnimationActive={false} />
                </BarChart>
              </Chart>
            </div>
            <p className="muted" style={{ fontSize: 11, marginBottom: 0 }}>
              Error spans are what separate a service that <i>caused</i> a failure
              from one merely on its latency path: both show raised p99, only the
              origin emits the erroring span. No other pillar carries that
              distinction, which is why removing traces costs localisation more than
              it costs detection.
            </p>
          </div>

          {/* ---- the raw window, every field, with its query ---- */}
          <h3>🔬 The current window, unabridged — <code>{service}</code></h3>
          <div className="pipes">
            {pillars.map((p) => (
              <div className="pipe" key={p.key}>
                <h3 style={{ color: p.colour }}>{p.icon} {p.title}</h3>
                <div className="muted" style={{ fontSize: 11, marginBottom: 6 }}>{p.source}</div>
                <table className="table" style={{ margin: 0 }}>
                  <tbody>
                    {p.fields.map((f) => (
                      <tr key={f.key} title={f.query ? `${f.key} — ${f.query}` : f.key}>
                        <td className="muted" style={{ fontSize: 12 }}>
                          {f.label}
                          {f.config && <span className="chip chip-muted" style={{ marginLeft: 4 }}>{f.config}</span>}
                        </td>
                        <td style={{ textAlign: "right" }}>{fmt(cur?.[p.key]?.[f.key], f.scale)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ))}
          </div>
          <p className="muted" style={{ fontSize: 12 }}>
            Hover any row for the query that produced it. These are the collector's
            own values, rounded for display and otherwise untouched — the feature
            builder's derived columns (ratios, rolling deviations) are not shown,
            because they are the model's view of the window rather than the window.
          </p>
        </>
      )}
    </div>
  );
}
