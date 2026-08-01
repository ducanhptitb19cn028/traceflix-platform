export default function Home() {
  return (
    <div className="page">
      <h1>Observability & Anomaly Detection</h1>
      <p className="subtitle">
        <em>"Does Observability Matter?"</em> — online vs offline ML on a
        non-stationary, drifting MELT stream.
      </p>

      <div className="callout warn">
        <b>The committed results are generated, not measured.</b> They come from the
        synthetic generator (<code>collectors/telemetry.py</code>), which is the default
        backend. The live path emits the identical window schema but the reported
        campaign was not run through it — the one exception is the <b>live-replay
        pilot</b> under Result Comparison, which scores telemetry Prometheus actually
        recorded. Judge the results by reading <code>telemetry.py</code> and{" "}
        <code>drift.py</code> before the models.
      </div>

      <div className="cards">
        <div className="card">
          <div className="kpi">R0 → R3</div>
          <div className="kpi-label">Operational regimes (drift injected)</div>
        </div>
        <div className="card">
          <div className="kpi">C1 – C4</div>
          <div className="kpi-label">Observability configs (metrics → full MELT)</div>
        </div>
        <div className="card">
          <div className="kpi">4</div>
          <div className="kpi-label">Models: static · periodic · online · oracle</div>
        </div>
        <div className="card">
          <div className="kpi amber">≈ 0.29</div>
          <div className="kpi-label">Always-alarm floor — the yardstick for every F1 here</div>
        </div>
      </div>

      <h2>Navigate</h2>
      <table className="table">
        <thead>
          <tr><th>Page</th><th>What it does</th></tr>
        </thead>
        <tbody>
          <tr>
            <td>🟢 <b>Online Mode</b></td>
            <td>Realtime view of the online ML pipeline auto-retraining — per-window
              incremental updates, champion hyper-parameter re-election, drift-triggered
              adaptation — next to a frozen offline model and a bursty periodic-retrain model.</td>
          </tr>
          <tr>
            <td>🔵 <b>Offline Mode</b></td>
            <td>Run any experiment behind the write-up as a background process and stream
              its logs: the reported campaign (RQ1–RQ4), the RQ3 controls that bound what
              it may claim — trivial floor, oracle re-threshold, seed variance, drift
              sweep, streaming baselines, component ablation — the live replay, and the
              exports.</td>
          </tr>
          <tr>
            <td>🧠 <b>Live ML</b></td>
            <td>Watch anomaly detection happen window by window across the classical
              model families — online SGD, RandomForest, GradientBoosting, XGBoost,
              LSTM, multimodal fusion — all deciding on the same stream, with running
              precision/recall/F1 and per-window cost.</td>
          </tr>
          <tr>
            <td>🤖 <b>Live LLM</b></td>
            <td>Watch the local LLM detector decide: the raw MELT signals it is handed,
              the strict JSON verdict it returns, its per-call latency, and which
              injected fault types it actually catches.</td>
          </tr>
          <tr>
            <td>📊 <b>Result Comparison</b></td>
            <td>The evidence, with its own controls beside it: the headline F1 against
              the always-alarm floor, the per-regime breakdown, the drift-magnitude
              sweep, the five-seed cost ranges, RQ2 localisation on the propagating
              generator, and the measured live-replay pilot.</td>
          </tr>
        </tbody>
      </table>

      <h2>What the campaign found</h2>
      <div className="callout">
        On clean stationary data every model looks great (F1 ≈ 0.99). The moment the
        system <em>operates</em>, the telemetry baseline drifts and a detector trained
        once on a snapshot decays to <b>F1 ≈ 0.36</b> — barely above the ≈ 0.29 scored by
        a detector that alarms on every window and reads nothing. A model that keeps
        learning recovers to oracle level (F1 ≈ 0.98).
      </div>
      <div className="callout warn">
        <b>Two caveats the headline does not carry on its own.</b>
        <ul>
          <li><b>The paradigm comparison is confounded with model family.</b> Static and
            periodic are Random Forests; the online arm is a linear SGD model with an
            adaptive normaliser — it must be, since no batch learner updates one window
            at a time. The clean contrast, same family and features, differing only in
            whether it refits, is <b>static 0.36 → periodic 0.92</b>.</li>
          <li><b>The drift is as large as the fault.</b> At the reported operating point
            the drifted healthy baseline lands on top of the fault signature the frozen
            model was fit to detect, so its collapse is entailed by that choice rather
            than measured. The <i>drift sweep</i> turns that single point into a curve —
            and at zero drift the frozen model is the best of the three.</li>
        </ul>
      </div>
    </div>
  );
}
