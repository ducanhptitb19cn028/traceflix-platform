import { useEffect, useRef, useState } from "react";
import {
  Bar, BarChart, CartesianGrid, Legend, Line, LineChart, ResponsiveContainer,
  Tooltip, XAxis, YAxis,
} from "recharts";
import { getJSON, liveControl, liveStreamUrl } from "../api.js";

const RATES = [0.5, 1, 2, 5, 10];

const fmt = (v) =>
  v == null ? "—" : Math.abs(v) >= 1e6 ? (v / 1e6).toFixed(1) + "M"
    : Math.abs(v) >= 1000 ? Math.round(v).toLocaleString()
    : Number.isInteger(v) ? v : v.toFixed(3);

export default function LiveLLM() {
  const [info, setInfo] = useState(null);
  const [snap, setSnap] = useState(null);
  const [history, setHistory] = useState([]);
  const [connected, setConnected] = useState(false);
  const [apiError, setApiError] = useState(null);
  const esRef = useRef(null);

  // Attach on mount: the detector is already running, we just start watching it.
  useEffect(() => {
    getJSON("/api/live/llm/info").then(setInfo).catch((e) => setApiError(String(e)));
    const es = new EventSource(liveStreamUrl("llm"));
    esRef.current = es;
    es.onopen = () => setConnected(true);
    es.onmessage = (e) => {
      const ev = JSON.parse(e.data);
      if (ev.type === "start") {
        setHistory(ev.history ?? []);
        if (ev.verdict) setSnap(ev);
      } else if (ev.type === "snapshot") {
        setSnap(ev);
        setHistory((h) => [...h.slice(-400), {
          window: ev.processed, f1: ev.score.f1, acc: ev.score.acc,
          ms: ev.latency.last_ms,
        }]);
      }
    };
    es.onerror = () => setConnected(false);
    return () => es.close();
  }, []);

  // merge onto whatever we have — the controls must respond even before the first
  // snapshot lands
  const control = (opts) => liveControl("llm", opts)
    .then((s) => setSnap((p) => ({ ...(p ?? {}), ...s }))).catch(() => {});

  const status = snap?.status ?? info?.engine;
  const mode = snap?.mode ?? info?.mode;
  const model = snap?.model ?? info?.model;
  const url = snap?.url ?? info?.url;
  const reason = snap?.mode_reason ?? info?.mode_reason;
  const live = mode === "llm";
  const s = snap?.score;
  const v = snap?.verdict;

  return (
    <div className="page">
      <h1>🤖 Live LLM detection — always on</h1>
      <p className="subtitle">
        The local LLM is handed the <b>raw MELT signals</b> of each window as it
        arrives — no engineered features, no training split — and answers one
        question: is this window anomalous. Nothing to launch; the detector is
        already running. Below is the window it is looking at right now, the strict
        JSON it returned, what each call costs, and which injected faults it catches.
      </p>

      <div className="controls">
        <span className={"chip " + (
          status === "live" ? "chip-green"
            : status === "error" ? "chip-red" : "chip-amber")}
          style={{ alignSelf: "center" }}>
          {status === "live" ? (snap?.paused ? "⏸ paused" : "🟢 detecting")
            : status === "error" ? "⚠ engine error" : "… starting"}
        </span>
        {mode && (
          <span className={"chip " + (live ? "chip-green" : "chip-amber")}
            style={{ alignSelf: "center" }}
            title={reason || (live ? `Ollama reachable at ${url}`
                                   : "clearly-marked heuristic fallback")}>
            {live ? `${model} via Ollama` : "⚠ heuristic fallback (no LLM reachable)"}
          </span>
        )}
        {snap && (
          <span className="chip chip-muted" style={{ alignSelf: "center" }}
            title="measured throughput — a real LLM call takes far longer than the target interval">
            {snap.processed?.toLocaleString()} windows classified · {snap.actual_rate}/s actual
            {" "}· up {snap.uptime_s}s{!connected && " · reconnecting…"}
          </span>
        )}
        <label>Target rate (windows/sec)
          <select value={snap?.rate ?? info?.rate ?? 2}
            onChange={(e) => control({ rate: e.target.value })}>
            {RATES.map((r) => <option key={r} value={r}>{r}/s</option>)}
          </select>
        </label>
        <button className="btn" onClick={() => control({ paused: !snap?.paused })}>
          {snap?.paused ? "▶ Resume" : "⏸ Pause"}
        </button>
        <button className="btn danger" onClick={() => { setHistory([]); control({ reset: true }); }}>
          ⟲ Reset stats
        </button>
      </div>

      {mode && !live && (
        <div className="callout">
          <b>Heuristic fallback.</b> The verdicts below come from the marked
          rule-of-thumb test, <b>not</b> from {model}.
          {reason && <> Reason: <code>{reason}</code></>}
          <br />
          The engine re-checks every 15 seconds and switches over on its own — no
          restart — and clears the statistics when it does, because the two modes are
          different detectors and pooling their verdicts would misreport both. It
          requires the model to actually be pulled, not merely that Ollama answers:
          with the daemon up but no model, every call errors and the detector would
          report "normal" for every window.
        </div>
      )}
      {live && snap?.mode_age_s != null && snap.mode_age_s < 120 && (
        <div className="callout">
          ✅ Ollama came up — switched to {model} {Math.round(snap.mode_age_s)}s ago and
          the counters were reset. The numbers below are the real model's.
        </div>
      )}
      {apiError && (
        <div className="callout">
          ⚠ <b>The backend has no <code>/api/live/llm</code> endpoints</b> ({apiError}).
          The usual cause is a backend process started before these were added —
          uvicorn only picks up code changes when it is run with <code>--reload</code>.
          Restart it: <code>./scripts/run_webui.ps1</code> (or{" "}
          <code>python -m uvicorn webui.backend.app:app --port 8000</code> from{" "}
          <code>aiops/</code>).
        </div>
      )}
      {status === "error" && (
        <div className="callout">⚠ The detection engine stopped: <code>{snap?.error}</code></div>
      )}

      {snap && v ? (
        <>
          <div className="cards">
            <div className="card">
              <div className={"kpi " + (v.pred === 1 ? "red" : "green")}>
                {v.pred === 1 ? "ANOMALY" : "normal"}
              </div>
              <div className="kpi-label">current window · <code>{snap.service}</code></div>
              <div className="proba" title="model confidence">
                <div className="proba-bar" style={{ width: Math.round(v.confidence * 100) + "%" }} />
                <span>conf={v.confidence.toFixed(2)}</span>
              </div>
              <div className="muted" style={{ fontSize: 12 }}>
                truth <b>{snap.label_fault}</b> ·{" "}
                <span className={"chip " + (snap.correct ? "chip-green" : "chip-red")}>
                  {snap.correct ? "correct" : "wrong"}
                </span>
              </div>
            </div>
            <div className="card">
              <div className="kpi">{s.f1.toFixed(3)}</div>
              <div className="kpi-label">running F1</div>
              <div className="muted" style={{ fontSize: 12 }}>
                acc <b>{s.acc.toFixed(3)}</b> · P <b>{s.precision.toFixed(3)}</b>
                {" "}· R <b>{s.recall.toFixed(3)}</b>
              </div>
            </div>
            <div className="card">
              <div className="kpi">{snap.latency.last_ms} ms</div>
              <div className="kpi-label">last inference</div>
              <div className="muted" style={{ fontSize: 12 }}>
                mean <b>{snap.latency.mean_ms} ms</b> · p95 <b>{snap.latency.p95_ms} ms</b>
              </div>
            </div>
            <div className="card">
              <div className="kpi">{s.tp}/{s.fp}/{s.fn}</div>
              <div className="kpi-label">TP / FP / FN</div>
              <div className="muted" style={{ fontSize: 12 }}>TN {s.tn}</div>
            </div>
          </div>

          {/* ---- input → output ---- */}
          <div className="pipes">
            <div className="pipe">
              <h3>📥 INPUT — raw MELT signals · <code>{snap.service}</code></h3>
              <div style={{ maxHeight: 300, overflowY: "auto" }}>
                <table className="table" style={{ margin: 0 }}>
                  <tbody>
                    {Object.entries(snap.signals).map(([k, val]) => (
                      <tr key={k}>
                        <td className="muted" style={{ fontSize: 12 }}>{k}</td>
                        <td style={{ textAlign: "right" }}>{fmt(val)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
            <div className="pipe">
              <h3>📤 OUTPUT — strict JSON verdict</h3>
              <pre className={"verdict-json " + (v.pred === 1 ? "anom" : "ok")}>
{JSON.stringify(v.json, null, 2)}
              </pre>
              {v.explanation && (
                <div className="muted" style={{ fontSize: 12, marginBottom: 8 }}>
                  {v.explanation}
                </div>
              )}
              <div className="muted" style={{ fontSize: 12 }}>
                {live
                  ? <>Ollama <code>/api/chat</code> · <code>format=json</code> · temp=0</>
                  : <>heuristic fallback (no LLM reachable)</>}
              </div>
              <details style={{ marginTop: 10 }}>
                <summary className="muted" style={{ fontSize: 12, cursor: "pointer" }}>
                  show the prompt line sent to the model
                </summary>
                <pre className="verdict-json" style={{ whiteSpace: "pre-wrap" }}>
Window: {snap.prompt}
                </pre>
              </details>
            </div>
          </div>
        </>
      ) : (
        <div className="hint">Attaching to the detection engine…</div>
      )}

      <div className="chart-box">
        <h3>Rolling accuracy and per-call latency</h3>
        <ResponsiveContainer width="100%" height={280}>
          <LineChart data={history}>
            <CartesianGrid strokeDasharray="3 3" stroke="#2a2f3a" />
            <XAxis dataKey="window" stroke="#8a93a6" />
            <YAxis yAxisId="l" domain={[0, 1]} stroke="#8a93a6" />
            <YAxis yAxisId="r" orientation="right" stroke="#8a93a6" />
            <Tooltip contentStyle={{ background: "#1b1f29", border: "1px solid #2a2f3a" }} />
            <Legend />
            <Line yAxisId="l" type="monotone" dataKey="f1" name="F1" stroke="#f59e0b"
              dot={false} strokeWidth={2} isAnimationActive={false} />
            <Line yAxisId="l" type="monotone" dataKey="acc" name="accuracy" stroke="#3b82f6"
              dot={false} strokeWidth={2} isAnimationActive={false} />
            <Line yAxisId="r" type="monotone" dataKey="ms" name="latency (ms)" stroke="#8a93a6"
              dot={false} strokeWidth={1} isAnimationActive={false} />
          </LineChart>
        </ResponsiveContainer>
      </div>

      {/* ---- per-fault breakdown ---- */}
      {snap?.by_fault?.length > 0 && (
        <div className="chart-box">
          <h3>Which faults it gets right — accuracy per injected fault type</h3>
          <ResponsiveContainer width="100%" height={260}>
            <BarChart data={snap.by_fault.map((b) => ({
              fault: b.fault, accuracy: b.n ? +(b.hit / b.n).toFixed(3) : 0, n: b.n,
            }))}>
              <CartesianGrid strokeDasharray="3 3" stroke="#2a2f3a" />
              <XAxis dataKey="fault" stroke="#8a93a6" />
              <YAxis domain={[0, 1]} stroke="#8a93a6" />
              <Tooltip contentStyle={{ background: "#1b1f29", border: "1px solid #2a2f3a" }} />
              <Bar dataKey="accuracy" fill="#f59e0b" isAnimationActive={false} />
            </BarChart>
          </ResponsiveContainer>
          <div className="muted" style={{ fontSize: 12 }}>
            windows seen per type: {snap.by_fault.map((b) => `${b.fault} ${b.n}`).join(" · ")}
          </div>
        </div>
      )}

      {/* ---- feed ---- */}
      {snap?.feed?.length > 0 && (
        <>
          <h3>Recent verdicts</h3>
          <div className="feed">
            <table className="table" style={{ margin: 0 }}>
              <thead>
                <tr>
                  <th>#</th><th>service</th><th>truth</th><th>verdict</th>
                  <th style={{ textAlign: "right" }}>conf</th>
                  <th style={{ textAlign: "right" }}>ms</th>
                </tr>
              </thead>
              <tbody>
                {snap.feed.map((f) => (
                  <tr key={f.window}>
                    <td className="muted">{f.window}</td>
                    <td><code>{f.service}</code></td>
                    <td>
                      <span className={"chip " + (f.label === 1 ? "chip-red" : "chip-green")}>
                        {f.fault}
                      </span>
                    </td>
                    <td>
                      <span className={"chip " + (
                        f.pred === f.label ? "chip-green"
                          : f.pred === 1 ? "chip-amber" : "chip-red")}
                        title={f.pred === f.label ? "correct"
                          : f.pred === 1 ? "false alarm" : "missed"}>
                        {f.pred === 1 ? "ANOMALY" : "normal"}
                      </span>
                    </td>
                    <td style={{ textAlign: "right" }}>{f.conf.toFixed(2)}</td>
                    <td style={{ textAlign: "right" }}>{f.ms}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  );
}
