import { useEffect, useRef, useState } from "react";
import { getJSON, offlineRunUrl } from "../api.js";
import OfflinePipeline from "../components/OfflinePipeline.jsx";

export default function OfflineMode() {
  const [experiments, setExperiments] = useState([]);
  const [params, setParams] = useState({ key: "rq4", episodes: 200, configs: "C1,C2,C3,C4" });
  const [log, setLog] = useState([]);
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState(null);
  const esRef = useRef(null);
  const logEnd = useRef(null);

  useEffect(() => {
    getJSON("/api/experiments").then((x) => {
      setExperiments(x);
      if (x.length) setParams((p) => ({ ...p, key: x.find((e) => e.key === "rq4")?.key || x[0].key }));
    }).catch(() => {});
    return () => esRef.current?.close();
  }, []);

  useEffect(() => { logEnd.current?.scrollIntoView({ behavior: "smooth" }); }, [log]);

  const stop = () => { esRef.current?.close(); esRef.current = null; setRunning(false); };

  const run = () => {
    stop();
    setLog([]); setResult(null); setRunning(true);
    const es = new EventSource(offlineRunUrl(params));
    esRef.current = es;
    es.onmessage = (e) => {
      const ev = JSON.parse(e.data);
      if (ev.type === "start") setLog((l) => [...l, "$ " + ev.cmd]);
      else if (ev.type === "log") setLog((l) => [...l, ev.line]);
      else if (ev.type === "done") { setResult(ev); stop(); }
    };
    es.onerror = () => { setLog((l) => [...l, "[stream error / disconnected]"]); stop(); };
  };

  const up = (k) => (e) => {
    const v = e.target.type === "number" || e.target.type === "range"
      ? Number(e.target.value) : e.target.value;
    setParams((p) => ({ ...p, [k]: v }));
  };

  const current = experiments.find((x) => x.key === params.key);
  const needsConfigs = ["rq4", "cost"].includes(params.key);

  return (
    <div className="page">
      <h1>🔵 Offline Mode — run the ML pipeline</h1>
      <p className="subtitle">
        Send commands to train/evaluate the offline (and online) models, then inspect results.
      </p>

      <div className="controls">
        <label>Experiment / command
          <select value={params.key} onChange={up("key")} disabled={running}>
            {experiments.map((x) => <option key={x.key} value={x.key}>{x.label}</option>)}
          </select>
        </label>
        <label>Episodes: {params.episodes}
          <input type="range" min="80" max="320" step="20"
            value={params.episodes} onChange={up("episodes")} disabled={running} />
        </label>
        {needsConfigs && (
          <label>Configs
            <input type="text" value={params.configs} onChange={up("configs")} disabled={running} />
          </label>
        )}
        {!running
          ? <button className="btn primary" onClick={run}>▶ Run command</button>
          : <button className="btn danger" onClick={stop}>■ Stop</button>}
      </div>

      {current && (
        <div className="cmd">python -m {current.module}{" "}
          {params.episodes && `--episodes ${params.episodes} `}
          {needsConfigs && `--configs ${params.configs} `}
          {["rq123", "rq4", "cost", "observability"].includes(params.key) ? "--out data/results" : "data/results"}
        </div>
      )}

      <h3>Offline ML pipeline — bursty batch process</h3>
      <OfflinePipeline lines={log} running={running} done={!!result} result={result} />

      <div className="terminal">
        {log.length === 0 && !running &&
          <span className="muted">Pick an experiment and press Run. Logs stream live here.</span>}
        {log.map((l, i) => <div key={i} className="logline">{l}</div>)}
        <div ref={logEnd} />
      </div>

      {result && (
        <div className={"result " + (result.code === 0 ? "ok" : "err")}>
          {result.code === 0 ? "✅ Completed (exit 0)." : `❌ Exited with code ${result.code}.`}
          {result.outputs?.length > 0 && (
            <div className="outputs">
              <b>Outputs in data/results/:</b>
              <ul>{result.outputs.map((o) => <li key={o}>{o}</li>)}</ul>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
