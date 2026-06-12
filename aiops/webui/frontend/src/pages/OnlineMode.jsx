import { useEffect, useRef, useState } from "react";
import {
  CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";
import { getJSON, onlineStreamUrl } from "../api.js";
import PipelineFlow from "../components/PipelineFlow.jsx";

const SPEEDS = { slow: 300, normal: 120, fast: 40, max: 0 };

export default function OnlineMode() {
  const [configs, setConfigs] = useState([]);
  const [params, setParams] = useState({
    config: "C4", episodes: 320, includePeriodic: true, maxWindows: 3000, speed: "fast",
  });
  const [snap, setSnap] = useState(null);
  const [history, setHistory] = useState([]);
  const [running, setRunning] = useState(false);
  const [done, setDone] = useState(false);
  const esRef = useRef(null);

  useEffect(() => {
    getJSON("/api/configs").then(setConfigs).catch(() => {});
    return () => esRef.current?.close();
  }, []);

  const stop = () => {
    esRef.current?.close();
    esRef.current = null;
    setRunning(false);
  };

  const start = () => {
    stop();
    setHistory([]); setSnap(null); setDone(false); setRunning(true);
    const url = onlineStreamUrl({ ...params, delayMs: SPEEDS[params.speed] });
    const es = new EventSource(url);
    esRef.current = es;
    es.onmessage = (e) => {
      const ev = JSON.parse(e.data);
      if (ev.type === "snapshot") {
        setSnap(ev);
        setHistory((h) => [
          ...h,
          {
            window: ev.processed,
            online: ev.f1_online,
            static: ev.f1_static,
            periodic: ev.f1_periodic,
          },
        ]);
      } else if (ev.type === "done") {
        setDone(true); stop();
      }
    };
    es.onerror = () => stop();
  };

  const up = (k) => (e) => {
    const v = e.target.type === "checkbox" ? e.target.checked
      : e.target.type === "number" || e.target.type === "range" ? Number(e.target.value)
      : e.target.value;
    setParams((p) => ({ ...p, [k]: v }));
  };

  const pct = snap ? Math.round((snap.processed / snap.total) * 100) : 0;

  return (
    <div className="page">
      <h1>🟢 Online Mode — realtime self-adapting ML pipeline</h1>
      <p className="subtitle">
        Per-window incremental learning vs frozen offline vs bursty periodic retrain.
      </p>

      <div className="controls">
        <label>Config
          <select value={params.config} onChange={up("config")} disabled={running}>
            {configs.map((c) => (
              <option key={c.key} value={c.key}>{c.key} — {c.name}</option>
            ))}
          </select>
        </label>
        <label>Episodes: {params.episodes}
          <input type="range" min="80" max="320" step="40"
            value={params.episodes} onChange={up("episodes")} disabled={running} />
        </label>
        <label>Max windows: {params.maxWindows}
          <input type="range" min="500" max="8640" step="500"
            value={params.maxWindows} onChange={up("maxWindows")} disabled={running} />
        </label>
        <label>Speed
          <select value={params.speed} onChange={up("speed")}>
            {Object.keys(SPEEDS).map((s) => <option key={s} value={s}>{s}</option>)}
          </select>
        </label>
        <label className="check">
          <input type="checkbox" checked={params.includePeriodic}
            onChange={up("includePeriodic")} disabled={running} />
          Include periodic-retrain model
        </label>
        {!running
          ? <button className="btn primary" onClick={start}>▶ Start live stream</button>
          : <button className="btn danger" onClick={stop}>■ Stop</button>}
      </div>

      <h3>Online ML pipeline — per-window process</h3>
      <PipelineFlow snap={snap} includePeriodic={params.includePeriodic} />

      {snap && (
        <>
          <div className="progress">
            <div className="progress-bar" style={{ width: pct + "%" }} />
            <span>Regime <b>{snap.regime_name}</b> · window {snap.processed.toLocaleString()}/{snap.total.toLocaleString()} ({pct}%)</span>
          </div>

          <div className="cards">
            <div className="card"><div className="kpi green">{snap.f1_online?.toFixed(3)}</div><div className="kpi-label">🟢 Online F1</div></div>
            <div className="card"><div className="kpi red">{snap.f1_static?.toFixed(3)}</div><div className="kpi-label">🔴 Offline-static F1</div></div>
            <div className="card"><div className="kpi amber">{params.includePeriodic ? snap.f1_periodic?.toFixed(3) : "—"}</div><div className="kpi-label">🟠 Periodic F1</div></div>
            <div className="card"><div className="kpi">{snap.champion.eta0} / {snap.champion.alpha}</div><div className="kpi-label">Champion η₀ / α</div></div>
            <div className="card"><div className="kpi">{snap.adapt_events}</div><div className="kpi-label">Drift adaptations</div></div>
          </div>

          <div className="pipes">
            <div className={"pipe online" + (snap.just_adapted ? " flash" : "")}>
              <h3>🟢 Online pipeline</h3>
              <div className="status ok">
                {snap.just_adapted ? "⚡ DRIFT — re-centring boost" : "🔄 updating (partial_fit)"}
              </div>
              <p>Incremental updates: <b>{snap.online_updates.toLocaleString()}</b><br/>
                Retained training data: <b>0 windows</b></p>
            </div>
            <div className={"pipe periodic" + (snap.just_retrained ? " flash" : "")}>
              <h3>🟠 Periodic pipeline</h3>
              {!params.includePeriodic ? <div className="status muted">disabled</div>
                : snap.just_retrained
                  ? <div className="status err">🛑 RETRAINING — full batch refit (blocks detection) · refit #{snap.periodic_retrains}</div>
                  : <div className="status warn">serving frozen model · next refit in <b>{snap.next_retrain_in}</b> windows · refits: <b>{snap.periodic_retrains}</b></div>}
            </div>
          </div>

          <div className="chart-box">
            <h3>Rolling F1 over the drifting stream</h3>
            <ResponsiveContainer width="100%" height={320}>
              <LineChart data={history}>
                <CartesianGrid strokeDasharray="3 3" stroke="#2a2f3a" />
                <XAxis dataKey="window" stroke="#8a93a6" />
                <YAxis domain={[0, 1]} stroke="#8a93a6" />
                <Tooltip contentStyle={{ background: "#1b1f29", border: "1px solid #2a2f3a" }} />
                <Legend />
                <Line type="monotone" dataKey="online" stroke="#22c55e" dot={false} strokeWidth={2} isAnimationActive={false} />
                <Line type="monotone" dataKey="static" stroke="#ef4444" dot={false} strokeWidth={2} isAnimationActive={false} />
                {params.includePeriodic &&
                  <Line type="monotone" dataKey="periodic" stroke="#f59e0b" dot={false} strokeWidth={2} isAnimationActive={false} />}
              </LineChart>
            </ResponsiveContainer>
          </div>

          {snap.events?.length > 0 && (
            <div className="events">
              <h3>Adaptation / retrain events</h3>
              <table className="table">
                <thead><tr><th>Window</th><th>Event</th><th>Regime</th></tr></thead>
                <tbody>
                  {[...snap.events].reverse().map((ev, i) => (
                    <tr key={i}><td>{ev.window}</td><td>{ev.event}</td><td>{ev.regime}</td></tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}

      {done && <div className="callout">✅ Stream complete. The online model tracked the
        drift; the static model decayed; the periodic model recovered in sawtooth steps
        with blocking refits.</div>}
      {!snap && !running && <div className="hint">Set parameters and press
        <b> Start live stream</b>. Runs in-process on the backend (no cluster needed).</div>}
    </div>
  );
}
