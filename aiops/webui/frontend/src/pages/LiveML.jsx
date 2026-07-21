import { useEffect, useRef, useState } from "react";
import {
  CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";
import { getJSON, liveControl, liveStreamUrl } from "../api.js";

const RATES = [1, 2, 4, 10, 25];

export default function LiveML() {
  const [info, setInfo] = useState(null);
  const [snap, setSnap] = useState(null);
  const [history, setHistory] = useState([]);
  const [shownKeys, setShownKeys] = useState(null);   // null = show every detector
  const [connected, setConnected] = useState(false);
  const [apiError, setApiError] = useState(null);
  const esRef = useRef(null);

  // Attach on mount: the engine is already detecting, we just start watching it.
  useEffect(() => {
    getJSON("/api/live/ml/info").then(setInfo).catch((e) => setApiError(String(e)));
    const es = new EventSource(liveStreamUrl("ml"));
    esRef.current = es;
    es.onopen = () => setConnected(true);
    es.onmessage = (e) => {
      const ev = JSON.parse(e.data);
      if (ev.type === "start") {
        setHistory(ev.history ?? []);
        if (ev.detectors) setSnap(ev);
      } else if (ev.type === "snapshot") {
        setSnap(ev);
        const point = { window: ev.processed };
        ev.detectors.forEach((d) => { point[d.key] = d.f1; });
        setHistory((h) => [...h.slice(-400), point]);
      }
    };
    es.onerror = () => setConnected(false);
    return () => es.close();
  }, []);

  // merge onto whatever we have — the controls must respond even before the first
  // snapshot lands (the engine may still be fitting)
  const control = (opts) => liveControl("ml", opts)
    .then((s) => setSnap((p) => ({ ...(p ?? {}), ...s }))).catch(() => {});

  const toggle = (key, all) => setShownKeys((cur) => {
    const set = new Set(cur ?? all);
    set.has(key) ? set.delete(key) : set.add(key);
    return [...set];
  });

  const status = snap?.status ?? info?.engine;
  const dets = (snap?.detectors ?? []).filter(
    (d) => !shownKeys || shownKeys.includes(d.key));
  const allKeys = (snap?.detectors ?? []).map((d) => d.key);

  return (
    <div className="page">
      <h1>🧠 Live ML detection — always on</h1>
      <p className="subtitle">
        Telemetry never stops arriving, so neither does this. Every detector scores
        each window as it lands. The batch learners (RandomForest, GradientBoosting,
        XGBoost, LSTM, fusion) were fitted <b>once</b>, when the backend started, and
        then frozen — how they are actually deployed — while <b>Online SGD</b> keeps
        learning from every window it scores. Nothing to launch: the counters below
        belong to the running detector, and survive a page reload.
      </p>

      <div className="controls">
        <span className={"chip " + (
          status === "live" ? "chip-green"
            : status === "error" ? "chip-red" : "chip-amber")}
          style={{ alignSelf: "center" }}>
          {status === "training" ? "⏳ fitting the frozen models…"
            : status === "live" ? (snap?.paused ? "⏸ paused" : "🟢 detecting")
            : status === "error" ? "⚠ engine error" : "… starting"}
        </span>
        {snap && (
          <span className="chip chip-muted" style={{ alignSelf: "center" }}
            title="measured throughput — a detector costing 200 ms a window cannot be driven faster than 5/s whatever the target says">
            {snap.processed?.toLocaleString()} windows scored · {snap.actual_rate}/s actual
            {" "}· up {snap.uptime_s}s{!connected && " · reconnecting…"}
          </span>
        )}
        <label>Observability config
          <select value={snap?.config ?? info?.config ?? "C4"}
            onChange={(e) => { setHistory([]); control({ config: e.target.value }); }}>
            {(info?.configs ?? []).map((c) =>
              <option key={c.key} value={c.key}>{c.key} — {c.name}</option>)}
          </select>
        </label>
        <label>Target rate (windows/sec)
          <select value={snap?.rate ?? info?.rate ?? 4}
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

      {apiError && (
        <div className="callout">
          ⚠ <b>The backend has no <code>/api/live/ml</code> endpoints</b> ({apiError}).
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

      {snap?.detectors && (
        <div style={{ margin: "4px 0 14px" }}>
          <span className={"chip " + (snap.label === "anomaly" ? "chip-red" : "chip-green")}>
            current window: {snap.label_fault}
          </span>
          <span className="chip chip-blue">service: {snap.service}</span>
          <span className="chip chip-muted">
            {snap.config} {snap.config_name && `(${snap.config_name})`} · {snap.n_features}{" "}
            features · frozen models fitted on {snap.bootstrap_windows?.toLocaleString()}{" "}
            windows in {snap.train_ms} ms
          </span>
          <span className="chip chip-muted">
            online adaptations: {snap.adapt_events}
            {snap.champion && <> · champion η={snap.champion.eta0} α={snap.champion.alpha}</>}
          </span>
        </div>
      )}

      {/* ---- live verdicts ---- */}
      <div className="cards">
        {dets.map((d) => (
          <div className="card" key={d.key}
            style={{ borderColor: d.pred === 1 ? "var(--red)" : undefined }}>
            <div className="kpi" style={{ color: d.pred === 1 ? "var(--red)" : "var(--green)" }}>
              {d.pred === 1 ? "ANOMALY" : "normal"}
            </div>
            <div className="kpi-label" style={{ color: d.color }}>{d.name}</div>
            <div className="proba" title="anomaly probability">
              <div className="proba-bar" style={{ width: Math.round(d.proba * 100) + "%" }} />
              <span>p={d.proba.toFixed(2)}</span>
            </div>
            <div className="muted" style={{ fontSize: 12 }}>
              F1 <b>{d.f1.toFixed(3)}</b> · acc <b>{d.acc.toFixed(3)}</b>
            </div>
            <div className="muted" style={{ fontSize: 11, marginTop: 3 }}>
              {d.latency_ms} ms/window · {d.family}
            </div>
          </div>
        ))}
        {!snap?.detectors && (
          <div className="card">
            <div className="kpi">…</div>
            <div className="kpi-label">
              {status === "training"
                ? "fitting the frozen models on the bootstrap sample"
                : "attaching to the detection engine"}
            </div>
          </div>
        )}
      </div>

      {/* ---- which detectors to show ---- */}
      {allKeys.length > 0 && (
        <div className="controls" style={{ alignItems: "flex-start" }}>
          {snap.detectors.map((d) => (
            <label key={d.key} className="check"
              title={info?.detectors?.find((x) => x.key === d.key)?.note}>
              <input type="checkbox"
                checked={!shownKeys || shownKeys.includes(d.key)}
                onChange={() => toggle(d.key, allKeys)} />
              <span style={{ color: d.color }}><b>{d.name}</b></span>
            </label>
          ))}
        </div>
      )}

      {/* ---- rolling F1 ---- */}
      <div className="chart-box">
        <h3>Rolling F1 — every detector, same stream</h3>
        <ResponsiveContainer width="100%" height={320}>
          <LineChart data={history}>
            <CartesianGrid strokeDasharray="3 3" stroke="#2a2f3a" />
            <XAxis dataKey="window" stroke="#8a93a6" />
            <YAxis domain={[0, 1]} stroke="#8a93a6" />
            <Tooltip contentStyle={{ background: "#1b1f29", border: "1px solid #2a2f3a" }} />
            <Legend />
            {dets.map((d) => (
              <Line key={d.key} type="monotone" dataKey={d.key} name={d.name}
                stroke={d.color} dot={false} strokeWidth={2} isAnimationActive={false} />
            ))}
          </LineChart>
        </ResponsiveContainer>
      </div>

      {/* ---- running scoreboard ---- */}
      {dets.length > 0 && (
        <>
          <h3>Running scoreboard</h3>
          <table className="table">
            <thead>
              <tr>
                <th>detector</th><th>family</th>
                <th style={{ textAlign: "right" }}>precision</th>
                <th style={{ textAlign: "right" }}>recall</th>
                <th style={{ textAlign: "right" }}>F1</th>
                <th style={{ textAlign: "right" }}>acc</th>
                <th style={{ textAlign: "right" }}>TP</th>
                <th style={{ textAlign: "right" }}>FP</th>
                <th style={{ textAlign: "right" }}>FN</th>
                <th style={{ textAlign: "right" }}>ms/win</th>
              </tr>
            </thead>
            <tbody>
              {[...dets].sort((a, b) => b.f1 - a.f1).map((d) => (
                <tr key={d.key}>
                  <td style={{ color: d.color }}><b>{d.name}</b></td>
                  <td className="muted" style={{ fontSize: 12 }}>{d.family}</td>
                  <td style={{ textAlign: "right" }}>{d.precision.toFixed(3)}</td>
                  <td style={{ textAlign: "right" }}>{d.recall.toFixed(3)}</td>
                  <td style={{ textAlign: "right" }}><b>{d.f1.toFixed(3)}</b></td>
                  <td style={{ textAlign: "right" }}>{d.acc.toFixed(3)}</td>
                  <td style={{ textAlign: "right" }}>{d.tp}</td>
                  <td style={{ textAlign: "right" }}>{d.fp}</td>
                  <td style={{ textAlign: "right" }}>{d.fn}</td>
                  <td style={{ textAlign: "right" }}>{d.latency_ms}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}

      {/* ---- verdict feed ---- */}
      {snap?.feed?.length > 0 && (
        <>
          <h3>Recent windows — who called what</h3>
          <div className="feed">
            <table className="table" style={{ margin: 0 }}>
              <thead>
                <tr>
                  <th>#</th><th>service</th><th>truth</th>
                  {dets.map((d) => <th key={d.key} style={{ color: d.color }}>{d.name}</th>)}
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
                    {dets.map((d) => (
                      <td key={d.key}>
                        <span className={"chip " + (
                          f.preds[d.key] === f.label ? "chip-green"
                            : f.preds[d.key] === 1 ? "chip-amber" : "chip-red")}
                          title={f.preds[d.key] === f.label ? "correct"
                            : f.preds[d.key] === 1 ? "false alarm" : "missed"}>
                          {f.preds[d.key] === 1 ? "ANOM" : "norm"}
                        </span>
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}

      {info?.detectors && (
        <ul className="muted" style={{ fontSize: 12, margin: "16px 0 0 18px" }}>
          {info.detectors.map((d) => (
            <li key={d.key} style={{ opacity: d.available ? 1 : 0.6 }}>
              <b>{d.name}</b> — {d.note}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
