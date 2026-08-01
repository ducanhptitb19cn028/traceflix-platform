import { useEffect, useRef, useState } from "react";
import { getJSON, offlineRunUrl } from "../api.js";
import OfflinePipeline from "../components/OfflinePipeline.jsx";

// How loudly to warn before someone starts a job by accident. `seconds` and
// `minutes` pass without comment; the rest are worth a chip.
const COST_CHIP = {
  seconds: null,
  minutes: null,
  "tens of minutes": "chip-amber",
  hours: "chip-red",
};

export default function OfflineMode() {
  const [experiments, setExperiments] = useState([]);
  const [params, setParams] = useState({
    key: "rq3", episodes: 200, configs: "C1,C2,C3,C4", seeds: "42,43,44,45,46",
  });
  const [log, setLog] = useState([]);
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState(null);
  const esRef = useRef(null);
  const logEnd = useRef(null);

  useEffect(() => {
    getJSON("/api/experiments").then((x) => {
      setExperiments(x);
      if (x.length) setParams((p) => ({ ...p, key: x.find((e) => e.key === "rq3")?.key || x[0].key }));
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
  // Which controls to render comes from the experiment itself, not from a list
  // of keys kept in step by hand -- baselines_and_seeds takes --seeds but no
  // --episodes, live_replay takes neither.
  const takes = (p) => current?.params?.includes(p) ?? false;
  const groups = [...new Set(experiments.map((x) => x.group))];
  const costChip = current && COST_CHIP[current.cost];

  return (
    <div className="page">
      <h1>🔵 Offline Mode — run the ML pipeline</h1>
      <p className="subtitle">
        Run any experiment behind the write-up — the reported campaign, the controls that
        bound what it may claim, and the exports — then inspect the results.
      </p>

      <div className="controls">
        <label>Experiment / command
          <select value={params.key} onChange={up("key")} disabled={running}>
            {groups.map((g) => (
              <optgroup key={g} label={g}>
                {experiments.filter((x) => x.group === g).map((x) => (
                  <option key={x.key} value={x.key}>{x.label}</option>
                ))}
              </optgroup>
            ))}
          </select>
        </label>
        {takes("episodes") && (
          <label>Episodes: {params.episodes}
            <input type="range" min="80" max="320" step="20"
              value={params.episodes} onChange={up("episodes")} disabled={running} />
          </label>
        )}
        {takes("configs") && (
          <label>Configs
            <input type="text" value={params.configs} onChange={up("configs")} disabled={running} />
          </label>
        )}
        {takes("seeds") && (
          <label>Seeds
            <input type="text" value={params.seeds} onChange={up("seeds")} disabled={running} />
          </label>
        )}
        {!running
          ? <button className="btn primary" onClick={run}>▶ Run command</button>
          : <button className="btn danger" onClick={stop}>■ Stop</button>}
      </div>

      {current && (
        <>
          <div className="cmd">
            {current.preview
              .replace("{episodes}", params.episodes)
              .replace("{configs}", params.configs)
              .replace("{seeds}", params.seeds)}
          </div>
          <div style={{ marginBottom: 12 }}>
            <span className="chip chip-blue">writes to {current.out}/</span>
            <span className={"chip " + (costChip || "chip-muted")}>≈ {current.cost}</span>
            {current.env && Object.entries(current.env).map(([k, v]) => (
              <span key={k} className="chip chip-muted">{k}={v}</span>
            ))}
          </div>
          {current.note && <div className="callout warn">{current.note}</div>}
        </>
      )}

      <h3>Offline ML pipeline — bursty batch process</h3>
      <OfflinePipeline lines={log} running={running} done={!!result} result={result}
        out={current?.out ?? "data/results"} />

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
              <b>Outputs in {result.out ?? "data/results"}/:</b>
              <ul>{result.outputs.map((o) => <li key={o}>{o}</li>)}</ul>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
