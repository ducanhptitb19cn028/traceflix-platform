export default function Home() {
  return (
    <div className="page">
      <h1>Observability & Anomaly Detection</h1>
      <p className="subtitle">
        <em>"Does Observability Matter?"</em> — online vs offline ML on a
        non-stationary, drifting MELT stream.
      </p>

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
            <td>Send commands to run the ML experiments (RQ1–RQ4, cost, exports) as
              background processes, stream their logs, and inspect produced outputs.</td>
          </tr>
          <tr>
            <td>📊 <b>Result Comparison</b></td>
            <td>Side-by-side offline-vs-online results: F1 by configuration, per-regime
              breakdown, the cost trade-off, and the generated figures.</td>
          </tr>
        </tbody>
      </table>

      <div className="callout">
        On clean stationary data every model looks great (F1 ≈ 0.99). The moment the
        system <em>operates</em>, the telemetry baseline drifts — a detector trained once
        on a snapshot decays (F1 ≈ 0.5), while the online model recovers to oracle level
        (F1 ≈ 0.98) by learning continuously.
      </div>
    </div>
  );
}
