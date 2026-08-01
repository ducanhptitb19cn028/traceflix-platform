import { useEffect, useState } from "react";
import {
  Bar, BarChart, CartesianGrid, Legend, Line, LineChart, ReferenceLine,
  ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";
import { figureUrl, getJSON } from "../api.js";

const TABS = [
  "Headline", "Per-regime", "Controls", "Drift sweep",
  "Cost", "RQ2 localisation", "Live pilot", "Figures",
];
const MODELS = ["offline_static", "offline_periodic", "online_adaptive", "offline_full"];
const COLORS = {
  offline_static: "#ef4444", offline_periodic: "#f59e0b",
  online_adaptive: "#22c55e", offline_full: "#6366f1",
};
const ARM_COLORS = {
  "C2": "#ef4444", "C2 + graph-aware": "#f59e0b",
  "C3": "#3b82f6", "C3 + graph-aware": "#22c55e",
};
const AXIS = "#8a93a6";
const TIP = { background: "#1b1f29", border: "1px solid #2a2f3a" };

const f = (v, d = 3) => (typeof v === "number" ? v.toFixed(d) : "—");
const CHART = { strokeDasharray: "3 3", stroke: "#2a2f3a" };

/** A control that has not been run yet, told apart from one that failed. */
function NotRun({ what, cmd }) {
  return (
    <div className="hint">
      <b>{what}</b> has not been run yet. Start it in <b>Offline Mode</b>, or from a
      shell: <code>{cmd}</code>
    </div>
  );
}

export default function ResultComparison() {
  const [data, setData] = useState(null);
  const [rq2, setRq2] = useState(null);
  const [ctl, setCtl] = useState(null);
  const [err, setErr] = useState(null);
  const [tab, setTab] = useState(0);
  const [tlConfig, setTlConfig] = useState("C4");
  const [sweepConfig, setSweepConfig] = useState("C4");
  const [bg, setBg] = useState(0.1);

  useEffect(() => {
    getJSON("/api/results/comparison").then(setData).catch((e) => setErr(e.message));
    // These two never 404 — each block carries its own availability flag, so a
    // control that has not been run renders as "not run" rather than breaking
    // the page.
    getJSON("/api/results/rq2").then(setRq2).catch(() => setRq2({ available: false }));
    getJSON("/api/results/controls").then(setCtl).catch(() => setCtl(null));
  }, []);

  if (err) return <div className="page"><h1>📊 Result Comparison</h1>
    <div className="hint">No results yet ({err}). Generate them in <b>Offline Mode</b>
      (run <i>RQ3 — static vs periodic vs online detection under drift</i>).</div></div>;
  if (!data) return <div className="page"><h1>📊 Result Comparison</h1><div className="hint">Loading…</div></div>;

  const f1 = data.f1_by_config;
  const floor = data.floor;
  const timelineConfigs = [...new Set(data.timeline.map((r) => r.config))];
  const tl = data.timeline.filter((r) => r.config === tlConfig);

  return (
    <div className="page">
      <h1>📊 Result Comparison — offline vs online</h1>

      <div className="callout warn">
        <b>These results are generated, not measured.</b> Every table below except
        the <b>Live pilot</b> tab comes from the synthetic generator
        (<code>collectors/telemetry.py</code>), which is the default backend. The live
        path emits the identical window schema, but the reported campaign was not run
        through it.
      </div>

      <div className="tabs">
        {TABS.map((t, i) => (
          <button key={t} className={"tab" + (tab === i ? " active" : "")} onClick={() => setTab(i)}>{t}</button>
        ))}
      </div>

      {/* ---------------------------------------------------------------- */}
      {tab === 0 && (
        <>
          <h3>Detection F1 on the operational future (R1–R3)</h3>
          <table className="table">
            <thead><tr><th>Config</th>{MODELS.map((m) => <th key={m}>{m}</th>)}</tr></thead>
            <tbody>
              {f1.map((r) => (
                <tr key={r.config}>
                  <td>{r.config} — {r.name}</td>
                  {MODELS.map((m) => <td key={m}>{f(r[m])}</td>)}
                </tr>
              ))}
              {floor != null && (
                <tr>
                  <td className="muted">always-alarm floor (flags every window)</td>
                  <td className="muted" colSpan={MODELS.length}>{f(floor)}</td>
                </tr>
              )}
            </tbody>
          </table>
          <ResponsiveContainer width="100%" height={360}>
            <BarChart data={f1}>
              <CartesianGrid {...CHART} />
              <XAxis dataKey="name" stroke={AXIS} />
              <YAxis domain={[0, 1]} stroke={AXIS} />
              <Tooltip contentStyle={TIP} />
              <Legend />
              {MODELS.map((m) => <Bar key={m} dataKey={m} fill={COLORS[m]} />)}
              {floor != null && (
                <ReferenceLine y={floor} stroke={AXIS} strokeDasharray="5 5"
                  label={{ value: `always-alarm floor ${f(floor)}`, fill: AXIS, fontSize: 11, position: "insideTopRight" }} />
              )}
            </BarChart>
          </ResponsiveContainer>

          <div className="callout">
            <b>Read the frozen model against the floor, not against zero.</b> A detector
            that alarms on every window scores {f(floor)}; the frozen model reaches
            ~0.36. Its collapse is not "degraded accuracy" — it is barely above ignoring
            the data.
            <br /><br />
            <b>The paradigm comparison is confounded with model family.</b> Static and
            periodic are Random Forests; the online arm is a linear SGD model with an
            adaptive normaliser — it must be, since no batch learner updates one window
            at a time. The clean contrast, same family and same features, differing only
            in whether it refits, is <b>static vs periodic: 0.36 → 0.92</b>.
          </div>

          <h3 style={{ marginTop: 24 }}>Rolling F1 over the drifting stream</h3>
          <label className="inline">Config&nbsp;
            <select value={tlConfig} onChange={(e) => setTlConfig(e.target.value)}>
              {timelineConfigs.map((c) => <option key={c} value={c}>{c}</option>)}
            </select>
          </label>
          <ResponsiveContainer width="100%" height={320}>
            <LineChart data={tl}>
              <CartesianGrid {...CHART} />
              <XAxis dataKey="t_center" stroke={AXIS} />
              <YAxis domain={[0, 1]} stroke={AXIS} />
              <Tooltip contentStyle={TIP} />
              <Legend />
              <Line type="monotone" dataKey="online_adaptive_f1" stroke="#22c55e" dot={false} isAnimationActive={false} />
              <Line type="monotone" dataKey="offline_periodic_f1" stroke="#f59e0b" dot={false} isAnimationActive={false} />
              <Line type="monotone" dataKey="offline_static_f1" stroke="#ef4444" dot={false} isAnimationActive={false} />
              {floor != null && <ReferenceLine y={floor} stroke={AXIS} strokeDasharray="5 5" />}
            </LineChart>
          </ResponsiveContainer>
        </>
      )}

      {/* ---------------------------------------------------------------- */}
      {tab === 1 && (
        <>
          <h3>F1 by future regime</h3>
          <table className="table">
            <thead><tr><th>Config</th><th>Regime</th><th>offline_static</th><th>offline_periodic</th><th>online_adaptive</th></tr></thead>
            <tbody>
              {data.per_regime.map((r, i) => (
                <tr key={i}>
                  <td>{r.config}</td><td>{r.segment}</td>
                  <td>{f(r.offline_static)}</td>
                  <td>{f(r.offline_periodic)}</td>
                  <td>{f(r.online_adaptive)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}

      {/* ---------------------------------------------------------------- */}
      {tab === 2 && <Controls ctl={ctl} f1={f1} />}
      {tab === 3 && <Sweep ctl={ctl} config={sweepConfig} setConfig={setSweepConfig} />}
      {tab === 4 && <Cost data={data} />}
      {tab === 5 && <Rq2 rq2={rq2} bg={bg} setBg={setBg} />}
      {tab === 6 && <LivePilot ctl={ctl} />}

      {/* ---------------------------------------------------------------- */}
      {tab === 7 && (
        <div className="figures">
          {data.figures.length === 0
            ? <div className="hint">No figures — run <i>Plots</i> in Offline Mode.</div>
            : data.figures.map((f_) => (
                <figure key={f_}>
                  <img src={figureUrl(f_)} alt={f_} />
                  <figcaption>
                    {f_}
                    {f_ === "rq2_localisation.png" && (
                      <div className="chip chip-red" style={{ marginTop: 6 }}>
                        withdrawn — plots RQ2's circular first attempt, not the reported result
                      </div>
                    )}
                  </figcaption>
                </figure>
              ))}
        </div>
      )}
    </div>
  );
}

/* ------------------------------------------------------------------------- */
/* Controls: the floor, the recalibration control, seed variance, and the     */
/* ladder that says how much of the online margin the adaptive machinery owns */
function Controls({ ctl, f1 }) {
  if (!ctl) return <div className="hint">Loading controls…</div>;
  const { floor_recalibration: fr, seed_variance: sv, ablation, streaming_baselines: sb } = ctl;
  const detectorF1 = Object.fromEntries(f1.map((r) => [r.config, r.online_adaptive]));

  return (
    <>
      <h3>The trivial floor and the recalibration control</h3>
      {!fr.available ? <NotRun what="The floor + seed-variance control" cmd="make seeds" /> : (
        <>
          <table className="table">
            <thead><tr>
              <th>Config</th><th>Prevalence</th><th>Always-alarm F1</th>
              <th>Static frozen F1</th><th>Static AUC</th><th>+ oracle re-threshold</th>
            </tr></thead>
            <tbody>
              {fr.rows.map((r) => (
                <tr key={r.config}>
                  <td>{r.config}</td><td>{f(r.prevalence)}</td>
                  <td>{f(r.always_alarm_f1)}</td>
                  <td>{f(r.static_frozen_f1)}</td>
                  <td>{f(r.static_auc)}</td>
                  <td>{f(r.static_recalibrated_f1)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <div className="callout">
            <b>Why re-tuning a threshold is not a substitute for re-learning.</b> The
            frozen model still ranks windows well (AUC ≈ 0.86), so the obvious objection
            is that only its cut-point is stale. Measured rather than argued: an
            <i> oracle</i> threshold — chosen with knowledge of the test labels, so
            unattainable in deployment and an upper bound on any recalibration scheme —
            recovers it only to 0.44–0.56, against the online detector's 0.97. The
            decision boundary is the wrong <b>shape</b>, not merely in the wrong
            <b> place</b>.
          </div>
        </>
      )}

      <h3>Seed variance — five independent seeds</h3>
      {!sv.available || !sv.summary ? <NotRun what="Seed variance" cmd="make seeds" /> : (
        <>
          <table className="table">
            <thead><tr>
              <th>Config</th><th>offline_static</th><th>offline_periodic</th>
              <th>online_adaptive</th><th>online − periodic</th>
            </tr></thead>
            <tbody>
              {Object.entries(sv.summary.headline_f1_mean_sd).map(([cfg, v]) => {
                const d = v.online_adaptive.mean - v.offline_periodic.mean;
                const tied = Math.abs(d) < (v.online_adaptive.sd + v.offline_periodic.sd);
                return (
                  <tr key={cfg}>
                    <td>{cfg}</td>
                    <td>{f(v.offline_static.mean)} ± {f(v.offline_static.sd, 4)}</td>
                    <td>{f(v.offline_periodic.mean)} ± {f(v.offline_periodic.sd, 4)}</td>
                    <td>{f(v.online_adaptive.mean)} ± {f(v.online_adaptive.sd, 4)}</td>
                    <td>
                      {d >= 0 ? "+" : ""}{f(d)}{" "}
                      <span className={"chip " + (tied ? "chip-muted" : "chip-green")}>
                        {tied ? "inside the spread" : "clear"}
                      </span>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          <p className="muted">
            Seed variance corrected a single-seed claim: under thin telemetry (C1, C2)
            online and periodic are <b>tied</b>, not "periodic narrowly ahead". The
            online advantage is real only at C3/C4.
          </p>
        </>
      )}

      <h3>Off-the-shelf incremental learners on the identical stream</h3>
      {!sb.available ? <NotRun what="The streaming baselines" cmd="make baselines" /> : (
        <>
          <StreamingTable rows={sb.rows} />
          <table className="table">
            <thead><tr><th>Config</th><th>Best off-the-shelf (scaled)</th><th>F1</th><th>Our detector</th><th>Margin</th></tr></thead>
            <tbody>
              {(sb.summary?.best_off_the_shelf_per_config ?? []).map((b) => (
                <tr key={b.config}>
                  <td>{b.config}</td><td>{b.model}</td><td>{f(b.f1)}</td>
                  <td>{f(detectorF1[b.config])}</td>
                  <td>{detectorF1[b.config] != null
                    ? (detectorF1[b.config] - b.f1 >= 0 ? "+" : "") + f(detectorF1[b.config] - b.f1)
                    : "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <div className="callout">
            <b>Adaptive normalisation is what carries the online policy.</b> Unnormalised,
            all three linear learners sit at F1 0.30–0.31 at <i>every</i> configuration —
            barely above the floor, and flat in telemetry richness. Put a running
            standardiser in front of the identical learner and they reach 0.76–0.80 at C1
            and 0.96–0.97 at C3. The whole detector's remaining margin over the best
            off-the-shelf scaled arm is small and shrinks with richness.
            <br /><br />
            <b>Read the Gaussian-NB rows with the NaN column open.</b> It degenerates
            completely at C4, and every scaled arm emits NaN scores floored to 0.5 before
            metrics. The claim rests on the three linear learners, which emit none.
          </div>
        </>
      )}

      <h3>Ablation — what each mechanism is worth</h3>
      {!ablation.available ? <NotRun what="The component ablation" cmd="make ablation" /> : (
        <>
          <table className="table">
            <thead><tr><th>Config</th><th>Arm</th><th>Precision</th><th>Recall</th><th>F1</th><th>AUC</th><th>Adapt events</th></tr></thead>
            <tbody>
              {ablation.rows.map((r, i) => (
                <tr key={i}>
                  <td>{r.config}</td><td>{r.arm}</td>
                  <td>{f(r.precision)}</td><td>{f(r.recall)}</td>
                  <td>{f(r.f1)}</td><td>{f(r.auc_roc)}</td><td>{r.adapt_events}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {ablation.summary && (
            <table className="table">
              <thead><tr><th>Config</th><th>Drift monitor (full − no_drift)</th><th>+ champion pool (full − neither)</th></tr></thead>
              <tbody>
                {Object.keys(ablation.summary.delta_full_minus_no_drift).map((cfg) => (
                  <tr key={cfg}>
                    <td>{cfg}</td>
                    <td>{f(ablation.summary.delta_full_minus_no_drift[cfg], 4)}</td>
                    <td>{f(ablation.summary.delta_full_minus_no_drift_no_champion[cfg], 4)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          <p className="muted">
            Champion re-election is worth +0.013 at C1 and nothing at C3/C4. The drift
            monitor is worth nothing anywhere — its adapt events are diagnostic, not
            load-bearing.
          </p>
        </>
      )}
    </>
  );
}

/** Raw vs scaled, side by side, because the pair is the point. */
function StreamingTable({ rows }) {
  const configs = [...new Set(rows.map((r) => r.config))];
  const models = [...new Set(rows.map((r) => r.model.replace(/_scaled$/, "")))];
  const at = (c, m, scaled) =>
    rows.find((r) => r.config === c && r.scaled === scaled && r.model.replace(/_scaled$/, "") === m);

  return (
    <table className="table">
      <thead><tr>
        <th>Config</th><th>Learner</th><th>F1 raw</th><th>F1 scaled</th><th>Lift</th>
        <th>NaN scores (raw / scaled)</th>
      </tr></thead>
      <tbody>
        {configs.flatMap((c) => models.map((m) => {
          const raw = at(c, m, false), sc = at(c, m, true);
          const lift = raw && sc ? sc.f1 - raw.f1 : null;
          const nan = (r) => (r?.nan_scores
            ? <span className="chip chip-amber">{r.nan_scores.toLocaleString()}</span>
            : <span className="muted">0</span>);
          return (
            <tr key={c + m}>
              <td>{c}</td><td>{m}</td>
              <td>{f(raw?.f1)}</td><td>{f(sc?.f1)}</td>
              <td>{lift == null ? "—" : (lift >= 0 ? "+" : "") + f(lift)}</td>
              <td>{nan(raw)} / {nan(sc)}</td>
            </tr>
          );
        }))}
      </tbody>
    </table>
  );
}

/* ------------------------------------------------------------------------- */
/* The drift-magnitude sweep: one operating point becomes a curve.            */
function Sweep({ ctl, config, setConfig }) {
  if (!ctl) return <div className="hint">Loading…</div>;
  const sw = ctl.drift_sweep;
  if (!sw.available) return (
    <>
      <h3>Drift-magnitude sweep</h3>
      <NotRun what="The drift sweep" cmd="make sweep" />
      <p className="muted">Slowest control by far — it regenerates the stream once per
        alpha per config.</p>
    </>
  );

  const configs = [...new Set(sw.rows.map((r) => r.config))];
  const cfg = configs.includes(config) ? config : configs[0];
  const rows = sw.rows.filter((r) => r.config === cfg).sort((a, b) => a.alpha - b.alpha);
  const alarmFloor = sw.summary?.always_alarm_f1;
  const per = sw.summary?.per_config?.[cfg];

  return (
    <>
      <h3>Drift magnitude vs detector F1</h3>
      <p className="muted">
        <code>alpha</code> interpolates every regime multiplier toward 1 — <code>0</code> is
        stationary, <code>1</code> reproduces the reported campaign, <code>&gt;1</code>{" "}
        extrapolates. Labels are assigned before the regime factors are applied and the
        generator draws the same random numbers either way, so the <b>fault schedule is
        identical at every alpha</b>: the only thing that varies is how far the healthy
        baseline has moved.
      </p>
      <label className="inline">Config&nbsp;
        <select value={cfg} onChange={(e) => setConfig(e.target.value)}>
          {configs.map((c) => <option key={c} value={c}>{c}</option>)}
        </select>
      </label>
      <ResponsiveContainer width="100%" height={340}>
        <LineChart data={rows}>
          <CartesianGrid {...CHART} />
          <XAxis dataKey="r3_amplitude" stroke={AXIS}
            label={{ value: "R3 operating-point shift (×)", fill: AXIS, fontSize: 11, position: "insideBottom", dy: 10 }} />
          <YAxis domain={[0, 1]} stroke={AXIS} />
          <Tooltip contentStyle={TIP} />
          <Legend />
          <Line type="monotone" dataKey="offline_static_f1" stroke={COLORS.offline_static} dot isAnimationActive={false} />
          <Line type="monotone" dataKey="offline_periodic_f1" stroke={COLORS.offline_periodic} dot isAnimationActive={false} />
          <Line type="monotone" dataKey="online_adaptive_f1" stroke={COLORS.online_adaptive} dot isAnimationActive={false} />
          {alarmFloor != null && (
            <ReferenceLine y={alarmFloor} stroke={AXIS} strokeDasharray="5 5"
              label={{ value: `floor ${f(alarmFloor)}`, fill: AXIS, fontSize: 11, position: "insideBottomRight" }} />
          )}
        </LineChart>
      </ResponsiveContainer>

      <table className="table">
        <thead><tr>
          <th>alpha</th><th>R3 amplitude</th><th>static</th><th>periodic</th><th>online</th><th>Adapt events</th>
        </tr></thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.alpha}>
              <td>{r.alpha}</td><td>{f(r.r3_amplitude, 2)}×</td>
              <td>{f(r.offline_static_f1)}</td>
              <td>{f(r.offline_periodic_f1)}</td>
              <td>{f(r.online_adaptive_f1)}</td>
              <td>{r.adapt_events}</td>
            </tr>
          ))}
        </tbody>
      </table>

      <div className="callout">
        <b>Why the sweep exists.</b> In the reported campaign the drift amplitude and the
        fault amplitude are the same size, so under R3 the healthy operating point lands
        on top of the fault signature the static model was fit to detect. Its collapse is
        <i> entailed by that choice</i> rather than measured. One operating point cannot
        separate "drift defeats frozen detectors" from "we set the drift as large as the
        fault".
        <br /><br />
        <b>At alpha = 0 the frozen model is the best of the three.</b> Continual
        adaptation is worth having because the stream drifts, not because it is
        continual.
        {per && (
          <>
            <br /><br />
            At <b>{cfg}</b> the frozen model last holds twice the floor at alpha{" "}
            <b>{per.largest_alpha_static_above_2x_floor}</b> (a {f(per.amplitude_there, 2)}×
            shift). The reported campaign sits well past that.
          </>
        )}
      </div>
    </>
  );
}

/* ------------------------------------------------------------------------- */
function Cost({ data }) {
  const s = data.cost_seeds_summary;
  const range = (v) => (Array.isArray(v) ? `${v[0]} – ${v[1]}` : "—");

  return (
    <>
      <h3>Cost: online vs periodic retraining</h3>
      {s ? (
        <>
          <p className="muted">
            The write-up quotes <b>ranges</b>, and they come from here — five seeds ×
            four configs, {s.n_cells} cells. The single-seed table below cannot produce
            them.
          </p>
          <div className="cards">
            <div className="card">
              <div className="kpi amber">{range(s.periodic_max_ms)}</div>
              <div className="kpi-label">Periodic worst window (ms) — the blocking refit</div>
            </div>
            <div className="card">
              <div className="kpi green">{range(s.online_max_ms)}</div>
              <div className="kpi-label">Online worst window (ms)</div>
            </div>
            <div className="card">
              <div className="kpi">{range(s.tail_ratio)}×</div>
              <div className="kpi-label">Tail ratio (periodic / online)</div>
            </div>
            <div className="card">
              <div className="kpi">{range(s.size_ratio)}×</div>
              <div className="kpi-label">Model-size ratio</div>
            </div>
            <div className="card">
              <div className="kpi red">{range(s.cpu_ratio)}×</div>
              <div className="kpi-label">Total-CPU ratio (online / periodic)</div>
            </div>
          </div>
          <div className="callout warn">
            <b>What reproduces and what does not.</b> The structural columns — train
            events, retained windows, model size — follow from the policy and reproduce
            exactly. The wall-clock columns, and so the tail and CPU ratios, are
            properties of the machine and the run. Re-profiling will not reproduce these
            to the decimal, which is why the claim is an order-of-magnitude tail gap
            rather than a millisecond.
          </div>
        </>
      ) : (
        <NotRun what="The five-seed cost profile" cmd="make cost-seeds-agg" />
      )}

      <h3>Single-seed profile (seed 42)</h3>
      {data.cost.length === 0
        ? <div className="hint">Run <i>RQ3 — cost comparison, single seed</i> in Offline Mode.</div>
        : <table className="table">
            <thead><tr>{Object.keys(data.cost[0]).map((k) => <th key={k}>{k}</th>)}</tr></thead>
            <tbody>
              {data.cost.map((r, i) => (
                <tr key={i}>{Object.values(r).map((v, j) => <td key={j}>{typeof v === "number" ? v.toLocaleString() : v}</td>)}</tr>
              ))}
            </tbody>
          </table>}
      <p className="muted">
        Online: continuous cheap updates, a bounded per-window tail, no retained training
        data — at a higher steady CPU total. Periodic: cheap on average but bursty
        blocking refits, and a 2,880-window buffer it must keep to refit from.
      </p>
    </>
  );
}

/* ------------------------------------------------------------------------- */
/* RQ2 on the propagating generator — the rebuild, not the circular original. */
function Rq2({ rq2, bg, setBg }) {
  if (!rq2) return <div className="hint">Loading…</div>;
  if (!rq2.available) return (
    <>
      <h3>RQ2 — root-cause localisation</h3>
      <NotRun what="The RQ2 rebuild" cmd="make rq2" />
      {rq2.withdrawn_present && (
        <div className="callout warn">
          <code>rq2_localisation.csv</code> is on disk, but it is RQ2's <b>withdrawn</b>{" "}
          first attempt — its ranking feature was derived from the label, so C3 scores
          1.000 at every <i>k</i> by construction. Draw no conclusion from it.
        </div>
      )}
    </>
  );

  const backgrounds = rq2.backgrounds;
  const b = backgrounds.includes(bg) ? bg : backgrounds[0];
  const rows = rq2.topk.filter((r) => r.background === b);
  const ks = [...new Set(rows.map((r) => r.k))].sort((x, y) => x - y);
  const chart = ks.map((k) => {
    const o = { k: `top-${k}` };
    rq2.arms.forEach((a) => { o[a] = rows.find((r) => r.k === k && r.arm === a)?.topk_accuracy; });
    return o;
  });
  const randomFloor = rq2.summary?.random_floor;

  return (
    <>
      <h3>RQ2 — top-<i>k</i> localisation on the propagating generator</h3>
      <p className="muted">
        Errors travel up the call path attenuating {rq2.summary?.attenuation_per_hop ?? 0.6}{" "}
        per hop, so every service on the path emits spans and the origin has to be
        inferred as the root of the error tree — it is no longer readable off a single
        feature. Mean over {rq2.summary?.seeds?.length ?? 5} seeds.
      </p>

      <div className="callout warn">
        <b><code>background</code> is the realism knob</b> — the per-episode probability
        that a service <i>off</i> the fault's call path errors on its own account. At{" "}
        <b>0.0</b> the mesh carries exactly one error path, so its root is unique
        <i> by construction</i> and the graph-aware 1.000 is a boundary condition, not a
        result. <b>Report background ≥ 0.1.</b>
      </div>

      <label className="inline">Background incident rate&nbsp;
        <select value={b} onChange={(e) => setBg(Number(e.target.value))}>
          {backgrounds.map((x) => (
            <option key={x} value={x}>{x}{x === 0 ? "  (boundary condition)" : ""}</option>
          ))}
        </select>
      </label>

      <ResponsiveContainer width="100%" height={340}>
        <BarChart data={chart}>
          <CartesianGrid {...CHART} />
          <XAxis dataKey="k" stroke={AXIS} />
          <YAxis domain={[0, 1]} stroke={AXIS} />
          <Tooltip contentStyle={TIP} />
          <Legend />
          {rq2.arms.map((a) => <Bar key={a} dataKey={a} fill={ARM_COLORS[a] ?? "#6366f1"} />)}
          {randomFloor != null && (
            <ReferenceLine y={randomFloor} stroke={AXIS} strokeDasharray="5 5"
              label={{ value: `random guess ${randomFloor}`, fill: AXIS, fontSize: 11, position: "insideTopRight" }} />
          )}
        </BarChart>
      </ResponsiveContainer>

      <table className="table">
        <thead><tr><th>k</th>{rq2.arms.map((a) => <th key={a}>{a}</th>)}</tr></thead>
        <tbody>
          {ks.map((k) => (
            <tr key={k}>
              <td>top-{k}</td>
              {rq2.arms.map((a) => {
                const r = rows.find((x) => x.k === k && x.arm === a);
                return <td key={a}>{f(r?.topk_accuracy)} {r?.sd != null && <span className="muted">± {f(r.sd, 3)}</span>}</td>;
              })}
            </tr>
          ))}
        </tbody>
      </table>

      <div className="callout">
        <b>Traces lift localisation at every background rate</b> — that is the answer to
        RQ2, in direction. Graph-awareness is not a free win: it helps only while the mesh
        is quiet and <i>inverts</i> against flat ranking by background 0.5, because it
        cannot tell a real root from a spurious one. The attenuation rate and background
        rate are <b>inputs</b> — the ordering transfers, the magnitudes do not.
      </div>
    </>
  );
}

/* ------------------------------------------------------------------------- */
/* The only measured result in the repository.                               */
function LivePilot({ ctl }) {
  if (!ctl) return <div className="hint">Loading…</div>;
  const lp = ctl.live_pilot;
  if (!lp.available || !lp.summary) return (
    <>
      <h3>RQ1 live-replay pilot</h3>
      <NotRun what="The live replay" cmd="make live-replay" />
      <p className="muted">
        Needs a reachable Prometheus still holding the campaign's retention window.
        Without one, every window collects zeros and the run is a silent no-op rather
        than an error.
      </p>
    </>
  );

  const s = lp.summary;
  return (
    <>
      <h3>RQ1 live-replay pilot — measured telemetry</h3>
      <div className="callout">
        <b>This is the only measured result here.</b> Every other tab is generated. The
        replay joins the ground truth from a recorded fault-injection campaign to
        historical PromQL, evaluating each query at the instant its window represents, so
        a past campaign is reconstructed rather than filled with present-moment
        telemetry.
      </div>

      <div className="cards">
        <div className="card"><div className="kpi green">{f(s.f1)}</div>
          <div className="kpi-label">F1 — RF at C1, on measured telemetry</div></div>
        <div className="card"><div className="kpi">{f(s.precision)} / {f(s.recall)}</div>
          <div className="kpi-label">Precision / recall</div></div>
        <div className="card"><div className="kpi">{f(s.auc_roc)}</div>
          <div className="kpi-label">AUC</div></div>
        <div className="card"><div className="kpi amber">{f(s.always_alarm_f1)}</div>
          <div className="kpi-label">This campaign's own always-alarm floor</div></div>
        <div className="card"><div className="kpi">{s.n_windows} / {s.n_test}</div>
          <div className="kpi-label">Windows / test windows ({s.episodes} episodes)</div></div>
      </div>

      <div className="callout warn">
        <b>Its scope is narrow on purpose, and the narrowness is the point.</b>
        <ul>
          <li><b>C1 only.</b> Only the metric collector takes a timestamp. The log, trace
            and event collectors would silently mix present-moment values into a past
            window — so this pilot says <i>nothing</i> about the trace increment, the one
            RQ1 magnitude the write-up discounts.</li>
          <li><b>Origin-only labelling.</b> A window is anomalous iff its service is the
            injected root cause; ancestors degraded by the fault are labelled normal.
            Conservative by construction — it can only depress apparent precision.</li>
          <li><b>{s.episodes} episodes.</b> A feasibility measurement, far too small to
            carry a confidence interval, and not a replacement for the reported
            320-episode campaign.</li>
        </ul>
        So: F1 {f(s.f1)} at nearly five times its own floor, on real telemetry, at the
        configuration the synthetic campaign scores 0.896. That is evidence the pipeline
        works end to end on genuine data — and it is <b>not</b> evidence about any number
        in the paper.
      </div>
    </>
  );
}
