import { Link } from "react-router-dom";
import PipelineFlow from "../components/PipelineFlow.jsx";
import OfflinePipeline from "../components/OfflinePipeline.jsx";

// Side-by-side structural comparison of the two pipelines. The diagrams render
// in their idle form here; press ▶ in Online / Offline Mode to watch them animate.

const ROWS = [
  ["Trigger", "every incoming window", "one batch job (then re-run manually / on a schedule)"],
  ["Learning", "continuous partial_fit (test-then-train)", "fit once on the training window, then frozen"],
  ["Retained data", "0 windows (streaming)", "full training window buffered (e.g. 2880)"],
  ["Adapts to drift", "yes — drift monitor boosts re-centring", "no (static) / only on the next blocking refit (periodic)"],
  ["Latency on drift", "~1 window to start recovering", "until the next scheduled refit completes"],
  ["F1 under drift", "recovers to ≈ oracle (~0.98)", "static decays (~0.5); periodic sawtooths"],
  ["Cost profile", "steady, bounded per-window CPU", "idle, then bursty blocking refit spikes"],
];

export default function PipelineComparison() {
  return (
    <div className="page">
      <h1>🔀 Pipeline Comparison — online vs offline</h1>
      <p className="subtitle">
        The same drifting MELT stream, two detection strategies: a continuous
        self-adapting loop versus a bursty batch pass that freezes its model.
      </p>

      <h2>🟢 Online — continuous per-window loop</h2>
      <p className="muted">
        Each window is scored by the champion, then every candidate learns from it
        incrementally; a bandit re-elects the best learner and a drift monitor
        triggers faster re-centring. Watch it live in{" "}
        <Link to="/online">Online Mode</Link>.
      </p>
      <PipelineFlow snap={null} includePeriodic />

      <h2 style={{ marginTop: 28 }}>🔵 Offline — bursty batch pass</h2>
      <p className="muted">
        One pass builds features, fits the detector on a warm window, evaluates the
        future, and writes results — then the model is frozen until the next run.
        Drive it in <Link to="/offline">Offline Mode</Link>.
      </p>
      <OfflinePipeline />

      <h2 style={{ marginTop: 28 }}>Head-to-head</h2>
      <table className="table">
        <thead>
          <tr><th>Dimension</th><th>🟢 Online (adaptive)</th><th>🔵 Offline (static / periodic)</th></tr>
        </thead>
        <tbody>
          {ROWS.map(([dim, on, off]) => (
            <tr key={dim}><td><b>{dim}</b></td><td>{on}</td><td>{off}</td></tr>
          ))}
        </tbody>
      </table>

      <div className="callout">
        On clean stationary data both look great (F1 ≈ 0.99). Once the system
        <em> operates</em> and the telemetry baseline drifts, the frozen offline model
        decays while the online loop keeps pace — see the numbers in{" "}
        <Link to="/comparison">Result Comparison</Link>.
      </div>
    </div>
  );
}
