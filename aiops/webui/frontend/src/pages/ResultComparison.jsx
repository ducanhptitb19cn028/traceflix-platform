import { useEffect, useState } from "react";
import {
  Bar, BarChart, CartesianGrid, Legend, Line, LineChart,
  ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";
import { figureUrl, getJSON } from "../api.js";

const TABS = ["F1 by config", "Per-regime", "Cost", "Figures"];
const MODELS = ["offline_static", "offline_periodic", "online_adaptive", "offline_full"];
const COLORS = { offline_static: "#ef4444", offline_periodic: "#f59e0b", online_adaptive: "#22c55e", offline_full: "#6366f1" };

export default function ResultComparison() {
  const [data, setData] = useState(null);
  const [err, setErr] = useState(null);
  const [tab, setTab] = useState(0);
  const [tlConfig, setTlConfig] = useState("C4");

  useEffect(() => {
    getJSON("/api/results/comparison").then(setData).catch((e) => setErr(e.message));
  }, []);

  if (err) return <div className="page"><h1>📊 Result Comparison</h1>
    <div className="hint">No results yet ({err}). Generate them in <b>Offline Mode</b>
      (run <i>RQ4 — offline vs online detection</i>).</div></div>;
  if (!data) return <div className="page"><h1>📊 Result Comparison</h1><div className="hint">Loading…</div></div>;

  const f1 = data.f1_by_config;
  const timelineConfigs = [...new Set(data.timeline.map((r) => r.config))];
  const tl = data.timeline.filter((r) => r.config === tlConfig);

  return (
    <div className="page">
      <h1>📊 Result Comparison — offline vs online</h1>

      <div className="tabs">
        {TABS.map((t, i) => (
          <button key={t} className={"tab" + (tab === i ? " active" : "")} onClick={() => setTab(i)}>{t}</button>
        ))}
      </div>

      {tab === 0 && (
        <>
          <h3>Detection F1 on the operational future (R1–R3)</h3>
          <table className="table">
            <thead><tr><th>Config</th>{MODELS.map((m) => <th key={m}>{m}</th>)}</tr></thead>
            <tbody>
              {f1.map((r) => (
                <tr key={r.config}>
                  <td>{r.config} — {r.name}</td>
                  {MODELS.map((m) => <td key={m}>{r[m]?.toFixed?.(3) ?? "—"}</td>)}
                </tr>
              ))}
            </tbody>
          </table>
          <ResponsiveContainer width="100%" height={360}>
            <BarChart data={f1}>
              <CartesianGrid strokeDasharray="3 3" stroke="#2a2f3a" />
              <XAxis dataKey="name" stroke="#8a93a6" />
              <YAxis domain={[0, 1]} stroke="#8a93a6" />
              <Tooltip contentStyle={{ background: "#1b1f29", border: "1px solid #2a2f3a" }} />
              <Legend />
              {MODELS.map((m) => <Bar key={m} dataKey={m} fill={COLORS[m]} />)}
            </BarChart>
          </ResponsiveContainer>

          <h3 style={{ marginTop: 24 }}>Rolling F1 over the drifting stream</h3>
          <label className="inline">Config&nbsp;
            <select value={tlConfig} onChange={(e) => setTlConfig(e.target.value)}>
              {timelineConfigs.map((c) => <option key={c} value={c}>{c}</option>)}
            </select>
          </label>
          <ResponsiveContainer width="100%" height={320}>
            <LineChart data={tl}>
              <CartesianGrid strokeDasharray="3 3" stroke="#2a2f3a" />
              <XAxis dataKey="t_center" stroke="#8a93a6" />
              <YAxis domain={[0, 1]} stroke="#8a93a6" />
              <Tooltip contentStyle={{ background: "#1b1f29", border: "1px solid #2a2f3a" }} />
              <Legend />
              <Line type="monotone" dataKey="online_adaptive_f1" stroke="#22c55e" dot={false} isAnimationActive={false} />
              <Line type="monotone" dataKey="offline_periodic_f1" stroke="#f59e0b" dot={false} isAnimationActive={false} />
              <Line type="monotone" dataKey="offline_static_f1" stroke="#ef4444" dot={false} isAnimationActive={false} />
            </LineChart>
          </ResponsiveContainer>
        </>
      )}

      {tab === 1 && (
        <>
          <h3>F1 by future regime</h3>
          <table className="table">
            <thead><tr><th>Config</th><th>Regime</th><th>offline_static</th><th>offline_periodic</th><th>online_adaptive</th></tr></thead>
            <tbody>
              {data.per_regime.map((r, i) => (
                <tr key={i}>
                  <td>{r.config}</td><td>{r.segment}</td>
                  <td>{r.offline_static?.toFixed?.(3)}</td>
                  <td>{r.offline_periodic?.toFixed?.(3)}</td>
                  <td>{r.online_adaptive?.toFixed?.(3)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}

      {tab === 2 && (
        <>
          <h3>Cost: online vs periodic retraining</h3>
          {data.cost.length === 0
            ? <div className="hint">Run <i>RQ4 — cost comparison</i> in Offline Mode.</div>
            : <table className="table">
                <thead><tr>{Object.keys(data.cost[0]).map((k) => <th key={k}>{k}</th>)}</tr></thead>
                <tbody>
                  {data.cost.map((r, i) => (
                    <tr key={i}>{Object.values(r).map((v, j) => <td key={j}>{typeof v === "number" ? v.toLocaleString() : v}</td>)}</tr>
                  ))}
                </tbody>
              </table>}
          <p className="muted">Online: continuous cheap updates, bounded latency, 0 retained
            data, higher F1 — at higher steady CPU. Periodic: bursty blocking refits, a
            2880-window retained buffer.</p>
        </>
      )}

      {tab === 3 && (
        <div className="figures">
          {data.figures.length === 0
            ? <div className="hint">No figures — run <i>Plots</i> in Offline Mode.</div>
            : data.figures.map((f) => (
                <figure key={f}><img src={figureUrl(f)} alt={f} /><figcaption>{f}</figcaption></figure>
              ))}
        </div>
      )}
    </div>
  );
}
