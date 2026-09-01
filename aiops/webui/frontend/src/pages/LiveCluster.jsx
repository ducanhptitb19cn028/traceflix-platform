import { useEffect, useRef, useState } from "react";
import {
  CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";
import { getJSON, liveControl, liveStreamUrl } from "../api.js";

// Seconds between collected instants. Not windows/sec like the generated pages:
// a window here costs a PromQL round trip per metric, so the knob that matters is
// how often to go and ask, not how fast to replay something already in memory.
const CADENCES = [5, 10, 20, 30, 60];

export default function LiveCluster() {
  const [info, setInfo] = useState(null);
  const [snap, setSnap] = useState(null);
  const [history, setHistory] = useState([]);
  const [connected, setConnected] = useState(false);
  const [apiError, setApiError] = useState(null);
  const esRef = useRef(null);

  useEffect(() => {
    getJSON("/api/live/cluster/info").then(setInfo).catch((e) => setApiError(String(e)));
    const es = new EventSource(liveStreamUrl("cluster"));
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

  const control = (opts) => liveControl("cluster", opts)
    .then((s) => setSnap((p) => ({ ...(p ?? {}), ...s }))).catch(() => {});

  const status = snap?.status ?? info?.engine;
  const dets = snap?.detectors ?? [];
  const active = snap?.active_faults ?? info?.active_faults ?? [];
  const training = snap?.training ?? info?.training;
  const chaosOk = snap?.chaos_ok ?? info?.chaos_ok;
  const isLive = info?.live;

  return (
    <div className="page">
      <h1>🛰 Live detection — the deployed cluster</h1>
      <p className="subtitle">
        The same six detectors as <b>Live ML</b>, on the opposite kind of data.
        There, the engine invents the fault and therefore has to invent the signals
        too, and the F1 it reports is a statement about the generator. Here neither
        half is invented: the telemetry is whatever PromQL returns for the running
        services, and the truth column is read from the <b>Chaos Mesh resources
        actually injected into the cluster</b>. Inject a fault with{" "}
        <code>make inject SVC=… FAULT=… DUR=300</code> and it appears below.
      </p>

      {/* ---- the three things that decide whether any of this means anything ---- */}
      <div style={{ margin: "4px 0 14px" }}>
        <span className={"chip " + (isLive ? "chip-green" : "chip-red")}
          title="TF_LIVE=1 — without it the collectors return generated telemetry">
          {isLive ? "TF_LIVE=1 — reading the real stack" : "TF_LIVE unset — cannot read the cluster"}
        </span>
        <span className={"chip " + (chaosOk ? "chip-green" : "chip-red")}
          title="ground truth is read from the live Chaos Mesh custom resources">
          {chaosOk ? "Chaos Mesh readable — ground truth is real"
            : "Chaos Mesh unreadable — every window would be labelled normal"}
        </span>
        {training && (
          <span className="chip chip-muted"
            title="the models are fitted on windows collected from this cluster, never on the generator">
            fitted on {training.windows?.toLocaleString()} live windows
            {training.anomalous != null && <> · {training.anomalous} anomalous</>}
            {training.prevalence != null && <> ({(training.prevalence * 100).toFixed(1)}%)</>}
          </span>
        )}
        <span className="chip chip-muted">
          {info?.namespace} · {info?.config ?? "C1"} · every {snap?.cadence_s ?? info?.cadence_s}s
        </span>
      </div>

      {!chaosOk && info && (
        <div className="callout warn">
          ⚠ <b>Ground truth cannot be read</b>{info.chaos_reason && <> — <code>{info.chaos_reason}</code></>}.
          Every window will be labelled <code>normal</code>, so precision, recall and
          F1 below are meaningless until this is fixed. The detectors themselves keep
          working; only the scoring against truth is affected.
        </div>
      )}

      <div className="controls">
        <span className={"chip " + (
          status === "live" ? "chip-green"
            : status === "error" ? "chip-red" : "chip-amber")}
          style={{ alignSelf: "center" }}>
          {status === "training" ? "⏳ fitting on live windows…"
            : status === "live" ? (snap?.paused ? "⏸ paused" : "🟢 watching the cluster")
            : status === "error" ? "⚠ engine error" : "… starting"}
        </span>
        {snap && (
          <span className="chip chip-muted" style={{ alignSelf: "center" }}>
            {snap.processed?.toLocaleString()} windows scored · up {snap.uptime_s}s
            {!connected && " · reconnecting…"}
          </span>
        )}
        <label>Collect every
          <select value={snap?.cadence_s ?? info?.cadence_s ?? 10}
            onChange={(e) => control({ rate: e.target.value })}>
            {CADENCES.map((c) => <option key={c} value={c}>{c}s</option>)}
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
          ⚠ <b>The backend has no <code>/api/live/cluster</code> endpoints</b> ({apiError}).
          Restart it so the new routes are picked up: <code>./scripts/run_webui.ps1</code>{" "}
          (or <code>python -m uvicorn webui.backend.app:app --port 8000</code> from{" "}
          <code>aiops/</code>).
        </div>
      )}
      {status === "error" && (
        <div className="callout">
          ⚠ The engine stopped: <code>{snap?.error ?? info?.error}</code>
        </div>
      )}

      {/* ---- what the cluster says is broken, right now ---- */}
      <h3>Injected faults, right now</h3>
      {active.length === 0 ? (
        <p className="muted">
          Nothing is injected — every window below is genuinely normal, so the
          detectors can only be scored on false alarms. Run{" "}
          <code>make inject SVC=catalog-service FAULT=cpu_saturation DUR=300</code>{" "}
          and watch the truth column change. Allow about a minute: the OpenTelemetry
          export interval and the collector&apos;s 2-minute rate windows mean a fault
          is not visible in the metrics the instant it lands.
        </p>
      ) : (
        <div className="cards">
          {active.map((a) => (
            <div className="card" key={a.service} style={{ borderColor: "var(--red)" }}>
              <div className="kpi" style={{ color: "var(--red)" }}>{a.fault}</div>
              <div className="kpi-label"><code>{a.service}</code></div>
              <div className="muted" style={{ fontSize: 11, marginTop: 3 }}>
                read from the live Chaos Mesh resource
              </div>
            </div>
          ))}
        </div>
      )}

      {/* ---- live verdicts ---- */}
      <h3>Current window</h3>
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
        {dets.length === 0 && (
          <div className="card">
            <div className="kpi">…</div>
            <div className="kpi-label">
              {status === "training" ? "fitting the detectors on live windows"
                : status === "error" ? "engine stopped — see above"
                : "attaching to the cluster engine"}
            </div>
          </div>
        )}
      </div>

      <div className="chart-box">
        <h3>Rolling F1 on real telemetry</h3>
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

      {snap?.feed?.length > 0 && (
        <>
          <h3>Recent windows — real services, real truth</h3>
          <div className="feed">
            <table className="table" style={{ margin: 0 }}>
              <thead>
                <tr>
                  <th>#</th><th>service</th><th>truth (Chaos Mesh)</th>
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

      <div className="callout" style={{ marginTop: 18 }}>
        <b>How to read this page.</b> Configuration is fixed at <b>C1 (metrics
        only)</b>: the models are fitted on the replay caches, whose log, trace and
        event pillars carry values from replay time rather than from the episode
        they are labelled with, so anything above C1 would be trained on telemetry
        that does not belong to its label. Every window this page collects is
        appended to <code>{info?.record_path ?? "data/live_stream_cache.jsonl"}</code>{" "}
        in the replay&apos;s own format, so the live training set grows the longer
        the page runs — and once it is large enough, the restriction can be lifted.
        With a thin training set the scores are indicative, not results.
      </div>
    </div>
  );
}
