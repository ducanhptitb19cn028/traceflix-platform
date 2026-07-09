import { useEffect, useRef, useState } from "react";
import {
  CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";
import { getJSON, streamingStreamUrl } from "../api.js";

const SPEEDS = { slow: 240, normal: 90, fast: 30, max: 0 };

// MELT pillar metadata: icon + the raw signal fields worth surfacing per pillar.
const PILLARS = [
  { key: "metrics", icon: "📈", title: "Metrics",
    fields: ["req_rate", "err_rate", "p50_latency", "p99_latency", "cpu", "mem", "gc_pause", "threads"] },
  { key: "events", icon: "🔔", title: "Events",
    fields: ["oomkilled", "crashloop", "pod_restarts", "unhealthy"] },
  { key: "logs", icon: "📜", title: "Logs",
    fields: ["log_volume", "error_logs", "warn_logs", "request_logs"] },
  { key: "traces", icon: "🕸️", title: "Traces",
    fields: ["trace_count", "mean_span_ms", "p99_span_ms", "error_spans"] },
];

const fmt = (v) =>
  v == null ? "—" : Math.abs(v) >= 1e6 ? (v / 1e6).toFixed(1) + "M"
    : Math.abs(v) >= 1000 ? Math.round(v).toLocaleString()
    : Number.isInteger(v) ? v : v.toFixed(3);

function Verdict({ name, color, v, label }) {
  const anomalous = v?.pred === 1;
  return (
    <div className="card">
      <div className={"kpi " + color}>{v ? (anomalous ? "ANOMALY" : "normal") : "—"}</div>
      <div className="kpi-label">{name}</div>
      {v && (
        <>
          <div className="proba" title="anomaly probability">
            <div className="proba-bar" style={{ width: Math.round((v.proba ?? 0) * 100) + "%" }} />
            <span>p={v.proba?.toFixed(2)}</span>
          </div>
          <div className="muted" style={{ fontSize: 12 }}>
            F1 <b>{v.f1?.toFixed(3)}</b> · acc <b>{v.acc?.toFixed(3)}</b>
            {v.mode && <> · <span className={"chip " + (v.mode === "llm" ? "chip-green" : "chip-amber")}>{v.mode}</span></>}
          </div>
        </>
      )}
      {label && <div className="muted" style={{ fontSize: 11, marginTop: 4 }}>truth: {label}</div>}
    </div>
  );
}

export default function Streaming() {
  const [info, setInfo] = useState(null);
  const [params, setParams] = useState({ episodes: 40, maxWindows: 2000, speed: "fast" });
  const [snap, setSnap] = useState(null);
  const [history, setHistory] = useState([]);
  const [running, setRunning] = useState(false);
  const [done, setDone] = useState(false);
  const esRef = useRef(null);

  useEffect(() => {
    getJSON("/api/streaming/info").then(setInfo).catch(() => {});
    return () => esRef.current?.close();
  }, []);

  const stop = () => { esRef.current?.close(); esRef.current = null; setRunning(false); };

  const start = () => {
    stop();
    setHistory([]); setSnap(null); setDone(false); setRunning(true);
    const es = new EventSource(streamingStreamUrl({ ...params, delayMs: SPEEDS[params.speed] }));
    esRef.current = es;
    es.onmessage = (e) => {
      const ev = JSON.parse(e.data);
      if (ev.type === "snapshot") {
        setSnap(ev);
        setHistory((h) => [...h.slice(-400), {
          window: ev.processed, ml: ev.ml.f1, llm: ev.llm.f1,
        }]);
      } else if (ev.type === "done") { setDone(true); stop(); }
    };
    es.onerror = () => stop();
  };

  const up = (k) => (e) => {
    const v = e.target.type === "number" || e.target.type === "range"
      ? Number(e.target.value) : e.target.value;
    setParams((p) => ({ ...p, [k]: v }));
  };

  const pct = snap ? Math.round((snap.processed / snap.total) * 100) : 0;
  const llmMode = snap?.llm?.mode ?? info?.llm?.mode;
  const backend = snap?.backend ?? info?.backend;
  const bootstrap = snap?.bootstrap ?? info?.bootstrap;
  const kafkaLive = backend === "kafka";

  return (
    <div className="page">
      <h1>🌊 Streaming — Kafka event backbone (MELT · Topics · LLM)</h1>
      <p className="subtitle">
        Telemetry windows flow through Kafka topics to two parallel binary detectors:
        the online ML model and a local-LLM detector (Qwen2.5-3B) reasoning over raw signals.
        The <b>⚡ Kafka</b> and <b>LLM</b> chips below show whether it is wired to a live broker
        + real Ollama, or the in-process / heuristic fallbacks.
      </p>

      <div className="controls">
        <label>Episodes: {params.episodes}
          <input type="range" min="20" max="120" step="20"
            value={params.episodes} onChange={up("episodes")} disabled={running} />
        </label>
        <label>Max windows: {params.maxWindows}
          <input type="range" min="200" max="4000" step="200"
            value={params.maxWindows} onChange={up("maxWindows")} disabled={running} />
        </label>
        <label>Speed
          <select value={params.speed} onChange={up("speed")}>
            {Object.keys(SPEEDS).map((s) => <option key={s} value={s}>{s}</option>)}
          </select>
        </label>
        {!running
          ? <button className="btn primary" onClick={start}>▶ Start backbone</button>
          : <button className="btn danger" onClick={stop}>■ Stop</button>}
        {backend && (
          <span className={"chip " + (kafkaLive ? "chip-green" : "chip-amber")}
            style={{ alignSelf: "center" }}
            title={kafkaLive ? "verdicts are produced to a real Kafka broker"
                             : "no broker reachable — using the in-process bus"}>
            {kafkaLive ? `⚡ Kafka: ${bootstrap || "live"}` : "in-memory bus"}
          </span>
        )}
        {llmMode && (
          <span className={"chip " + (llmMode === "llm" ? "chip-green" : "chip-amber")}
            style={{ alignSelf: "center" }}>
            LLM: {info?.llm?.model} ({llmMode})
          </span>
        )}
      </div>

      {/* ---- TOPICS ---- */}
      <h3>📨 Topics — the event backbone</h3>
      <div className="cards">
        {(snap?.topics ?? info?.topics ?? []).map((t) => (
          <div className="card" key={t.name}>
            <div className="kpi">{(t.messages ?? 0).toLocaleString?.() ?? 0}</div>
            <div className="kpi-label"><code>{t.name}</code></div>
            <div className="muted" style={{ fontSize: 11, marginTop: 4 }}>{t.role}</div>
          </div>
        ))}
      </div>

      {snap && (
        <div className="progress">
          <div className="progress-bar" style={{ width: pct + "%" }} />
          <span>window {snap.processed.toLocaleString()}/{snap.total.toLocaleString()} ({pct}%)
            · current service <b>{snap.service}</b></span>
        </div>
      )}

      {/* ---- LIVE VERDICT FEED (messages landing on tf.anomalies) ---- */}
      {snap?.feed?.length > 0 && (
        <>
          <h3>📨 <code>tf.anomalies</code> — live verdict feed
            <span className={"chip " + (kafkaLive ? "chip-green" : "chip-amber")}
              style={{ marginLeft: 8 }}>
              {kafkaLive ? "produced to Kafka" : "in-memory"}
            </span>
          </h3>
          <div className="feed">
            <table className="table" style={{ margin: 0 }}>
              <thead>
                <tr>
                  <th>detector</th><th>service</th><th>verdict</th>
                  <th style={{ textAlign: "right" }}>p</th><th>truth</th>
                </tr>
              </thead>
              <tbody>
                {snap.feed.map((f, idx) => (
                  <tr key={idx}>
                    <td><span className={"chip " + (f.detector === "llm" ? "chip-amber" : "chip-green")}>
                      {f.detector}</span></td>
                    <td><code>{f.service}</code></td>
                    <td><span className={"chip " + (f.y_pred === 1 ? "chip-red" : "chip-green")}>
                      {f.y_pred === 1 ? "ANOMALY" : "normal"}</span></td>
                    <td style={{ textAlign: "right" }}>{f.proba?.toFixed(2)}</td>
                    <td className="muted" style={{ fontSize: 12 }}>{f.label === 1 ? "anomaly" : "normal"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}

      {/* ---- MELT ---- */}
      <h3>🔭 MELT — the current window's four pillars
        {snap && <span className={"chip " + (snap.label === "anomaly" ? "chip-red" : "chip-green")}
          style={{ marginLeft: 8 }}>{snap.service}: {snap.label_fault}</span>}
      </h3>
      <div className="pipes">
        {PILLARS.map((p) => (
          <div className="pipe" key={p.key}>
            <h3>{p.icon} {p.title}</h3>
            <table className="table" style={{ margin: 0 }}>
              <tbody>
                {p.fields.map((f) => (
                  <tr key={f}>
                    <td className="muted" style={{ fontSize: 12 }}>{f}</td>
                    <td style={{ textAlign: "right" }}>{fmt(snap?.melt?.[p.key]?.[f])}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ))}
      </div>

      {/* ---- LLM ---- */}
      <h3>🤖 LLM detector vs online ML detector</h3>
      <div className="cards">
        <Verdict name="🟢 Online ML (online_sgd)" color="green" v={snap?.ml} />
        <Verdict name="🤖 LLM (Qwen2.5-3B)" color="amber" v={snap?.llm} label={snap?.label} />
        <div className="card">
          <div className="kpi">{snap ? Math.round(snap.agreement * 100) + "%" : "—"}</div>
          <div className="kpi-label">ML ↔ LLM agreement</div>
          {snap?.llm?.explanation && (
            <div className="muted" style={{ fontSize: 11, marginTop: 6 }}>{snap.llm.explanation}</div>
          )}
        </div>
      </div>

      {/* ---- Fig 4.4b: single-window LLM inference — raw MELT window → strict JSON ---- */}
      {snap?.llm?.json && (
        <>
          <h3>🔬 Single-window LLM inference — one raw MELT window → strict JSON verdict
            <span className={"chip " + (llmMode === "llm" ? "chip-green" : "chip-amber")}
              style={{ marginLeft: 8 }}>{snap.llm.model} ({llmMode})</span>
          </h3>
          <div className="pipes">
            <div className="pipe">
              <h3>📥 INPUT — raw MELT signals · <code>{snap.service}</code></h3>
              <div style={{ maxHeight: 260, overflowY: "auto" }}>
                <table className="table" style={{ margin: 0 }}>
                  <tbody>
                    {Object.entries(snap.llm.signals ?? {}).map(([k, v]) => (
                      <tr key={k}>
                        <td className="muted" style={{ fontSize: 12 }}>{k}</td>
                        <td style={{ textAlign: "right" }}>{fmt(v)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
            <div className="pipe">
              <h3>📤 OUTPUT — strict JSON verdict</h3>
              <pre className={"verdict-json " + (snap.llm.pred === 1 ? "anom" : "ok")}>
{JSON.stringify(JSON.parse(snap.llm.json), null, 2)}
              </pre>
              <div className="muted" style={{ fontSize: 12 }}>
                {llmMode === "llm"
                  ? <>Ollama <code>/api/chat</code> · <code>format=json</code> · temp=0</>
                  : <>heuristic fallback (no LLM reachable)</>}
                {" "}· ground truth: <b>{snap.label}</b>
              </div>
            </div>
          </div>
        </>
      )}

      <div className="chart-box">
        <h3>Rolling F1 — both detectors over the stream</h3>
        <ResponsiveContainer width="100%" height={300}>
          <LineChart data={history}>
            <CartesianGrid strokeDasharray="3 3" stroke="#2a2f3a" />
            <XAxis dataKey="window" stroke="#8a93a6" />
            <YAxis domain={[0, 1]} stroke="#8a93a6" />
            <Tooltip contentStyle={{ background: "#1b1f29", border: "1px solid #2a2f3a" }} />
            <Legend />
            <Line type="monotone" dataKey="ml" name="online ML" stroke="#22c55e" dot={false} strokeWidth={2} isAnimationActive={false} />
            <Line type="monotone" dataKey="llm" name="LLM" stroke="#f59e0b" dot={false} strokeWidth={2} isAnimationActive={false} />
          </LineChart>
        </ResponsiveContainer>
      </div>

      {done && <div className="callout">✅ Backbone run complete. Both detectors emitted a
        binary verdict per window to <code>tf.anomalies</code>; the LLM ran in
        {llmMode === "llm" ? " real Qwen2.5-3B" : " heuristic"} mode.</div>}
      {!snap && !running && <div className="hint">Press <b>Start backbone</b> to drive the
        in-memory event bus window-by-window. Set <code>TF_KAFKA_BOOTSTRAP</code> /
        <code>OLLAMA_URL</code> on the backend to use a real Kafka broker + Qwen2.5-3B.</div>}
    </div>
  );
}
