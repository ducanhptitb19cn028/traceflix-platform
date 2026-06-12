// Visualisation of the OFFLINE batch pipeline (ml.experiments.online_vs_offline et al.).
// Mirrors the live online PipelineFlow, but for the bursty, blocking batch flow:
//   generate drifting MELT -> build features (per config) -> warm split ->
//   batch-fit detectors -> batch evaluate -> write outputs.
// Stages light up by matching the experiment's real stdout (lines prop), so the
// diagram tracks the run instead of being a static picture.

import { Fragment } from "react";

const STAGES = [
  { n: 1, icon: "📦", title: "Generate drifting MELT", sub: "episodes → windows + regimes R0–R3",
    match: [/drifting stream/i, /windows across/i, /operational regimes/i] },
  { n: 2, icon: "🧮", title: "Build features", sub: "per observability config · MELT → X, y",
    match: [/^\s*\[\*\]\s*config /i, /\bconfig [Cc]\d/] },
  { n: 3, icon: "✂️", title: "Warm split", sub: "train on R0 normal · hold out the future",
    match: [/warm/i, /train.*window/i, /refit every/i] },
  { n: 4, icon: "🌲", title: "Batch-fit detectors", sub: "RandomForest fit on the training window",
    match: [/retrain/i, /fit/i, /periodic/i] },
  { n: 5, icon: "🧪", title: "Batch evaluate", sub: "score future / all-regime → P · R · F1 · RCA",
    match: [/precision/i, /recall/i, /\bf1\b/i, /auc/i] },
  { n: 6, icon: "📤", title: "Write outputs", sub: "CSV + figures → data/results",
    match: [/results\s*->/i, /->\s*data\/results/i, /\.csv/i, /\.xlsx/i] },
];

// pick the furthest stage whose keywords appear in the most recent log lines
function activeStage(lines, running, done) {
  if (done) return STAGES.length - 1;
  if (!running) return -1;
  let idx = 3; // while running but ambiguous, assume the fit/eval core is busy
  const recent = lines.slice(-8);
  for (let s = 0; s < STAGES.length; s++) {
    if (recent.some((l) => STAGES[s].match.some((re) => re.test(l)))) idx = Math.max(idx, s);
  }
  return idx;
}

function Stage({ s, state }) {
  // state: "pending" | "active" | "done"
  return (
    <div className={"stage" + (state === "active" ? " active alert" : "")}>
      <div className="stage-head">
        <span className="stage-n">{state === "done" ? "✓" : s.n}</span>
        <span className="stage-icon">{s.icon}</span>
        <span className="stage-title">{s.title}</span>
      </div>
      <div className="stage-sub">{s.sub}</div>
      <div className={"chip " + (state === "active" ? "chip-amber"
        : state === "done" ? "chip-green" : "chip-muted")}>
        {state === "active" ? "⏳ running" : state === "done" ? "done" : "queued"}
      </div>
    </div>
  );
}

const Arrow = ({ on }) => <div className={"flow-arrow" + (on ? " on" : "")}>→</div>;

export default function OfflinePipeline({ lines = [], running, done, result }) {
  const active = activeStage(lines, running, done);
  const stateOf = (i) =>
    active < 0 ? "pending" : i < active ? "done" : i === active ? "active" : "pending";

  const row = (group) => (
    <div className="pipeline-row">
      {group.map((s, j) => {
        const i = STAGES.indexOf(s);
        return (
          <Fragment key={s.n}>
            <Stage s={s} state={stateOf(i)} />
            {j < group.length - 1 && <Arrow on={active > i} />}
          </Fragment>
        );
      })}
    </div>
  );

  return (
    <div className="pipeline">
      {row(STAGES.slice(0, 3))}
      {row(STAGES.slice(3, 6))}

      <div className="pipeline-legend">
        <span><b>Offline</b> = one bursty batch pass; the trained model is then <b>frozen</b>.</span>
        <span className="chip chip-red">🔴 static — fit once, never updates</span>
        <span className="chip chip-amber">🟠 periodic — blocking batch refit every N windows</span>
        <span className="chip chip-green">🟢 online — continuous partial_fit (see Online Mode)</span>
        <span className="chip chip-blue">🟣 oracle — per-regime refit (upper bound)</span>
      </div>

      {done && result && (
        <div className={"chip " + (result.code === 0 ? "chip-green" : "chip-red")}
             style={{ marginTop: 10 }}>
          {result.code === 0 ? "✓ batch pass complete" : `✗ exited ${result.code}`}
          {result.outputs?.length ? ` · ${result.outputs.length} output(s) written` : ""}
        </div>
      )}
    </div>
  );
}
