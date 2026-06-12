// Live visualisation of the OnlineModel's per-window pipeline (ml/models/online.py).
// Each window flows through: ingest -> adaptive-normalise -> champion predict ->
// incremental learn -> champion re-election (bandit) -> drift monitor.

function Stage({ n, icon, title, sub, children, active, alert }) {
  return (
    <div className={"stage" + (active ? " active" : "") + (alert ? " alert" : "")}>
      <div className="stage-head">
        <span className="stage-n">{n}</span>
        <span className="stage-icon">{icon}</span>
        <span className="stage-title">{title}</span>
      </div>
      {sub && <div className="stage-sub">{sub}</div>}
      {children}
    </div>
  );
}

const Arrow = ({ on }) => <div className={"flow-arrow" + (on ? " on" : "")}>→</div>;

// Stage blueprint — shared by the idle skeleton and (for reference) the live view.
const STAGES = [
  { n: 1, icon: "📥", title: "Ingest window", sub: "one MELT window arrives, label revealed" },
  { n: 2, icon: "📏", title: "Adaptive normalise", sub: "EW mean/var tracks the evolving normal" },
  { n: 3, icon: "🎯", title: "Champion predict (test)", sub: "current best learner scores it" },
  { n: 4, icon: "🔁", title: "Incremental learn", sub: "partial_fit on every candidate" },
  { n: 5, icon: "🏆", title: "Champion re-election", sub: "best recent windowed-F1 serves next" },
  { n: 6, icon: "🌊", title: "Drift monitor", sub: "prequential-error test → boost on drift" },
];

function IdleSkeleton({ includePeriodic }) {
  const withArrows = (group) =>
    group.flatMap((s, j) => [
      <Stage key={s.n} n={s.n} icon={s.icon} title={s.title} sub={s.sub}>
        <div className="chip chip-muted">idle</div>
      </Stage>,
      j < group.length - 1 ? <Arrow key={"a" + s.n} /> : null,
    ]);
  return (
    <div className="pipeline">
      <div className="pipeline-row">{withArrows(STAGES.slice(0, 3))}</div>
      <div className="pipeline-row">{withArrows(STAGES.slice(3, 6))}</div>
      <div className="pipeline-legend">
        <span>▶ Press <b>Start live stream</b> to drive each window through this
          continuous loop — no stored data, no batch refit.</span>
        {includePeriodic && (
          <span className="periodic-tag">🟠 Offline-periodic retrains in blocking bursts (for contrast)</span>
        )}
      </div>
    </div>
  );
}

export default function PipelineFlow({ snap, includePeriodic }) {
  if (!snap) return <IdleSkeleton includePeriodic={includePeriodic} />;
  const anomaly = snap.true_label === 1;
  const predAnom = snap.pred === 1;
  const boosting = snap.boost > 0;
  const pct = (snap.proba * 100).toFixed(0);

  return (
    <div className="pipeline">
      <div className="pipeline-row">
        <Stage n="1" icon="📥" title="Ingest window" active
          sub={`window #${snap.i.toLocaleString()} · ${snap.regime_name}`}>
          <div className={"chip " + (anomaly ? "chip-red" : "chip-green")}>
            truth: {anomaly ? "ANOMALY" : "normal"}
          </div>
        </Stage>
        <Arrow on />
        <Stage n="2" icon="📏" title="Adaptive normalise" active={boosting} alert={boosting}
          sub="EW mean/var tracks the evolving normal">
          <div className="chip chip-blue">z-score vs today's normal</div>
          {boosting
            ? <div className="chip chip-amber">⚡ BOOST ×8 ({snap.boost} left)</div>
            : <div className="chip chip-muted">decay ×1 (steady)</div>}
        </Stage>
        <Arrow on />
        <Stage n="3" icon="🎯" title="Champion predict (test)" active
          sub={`η₀ ${snap.champion.eta0} · α ${snap.champion.alpha}`}>
          <div className={"chip " + (predAnom ? "chip-red" : "chip-green")}>
            predicts: {predAnom ? "ANOMALY" : "normal"}
          </div>
          <div className="proba">
            <div className="proba-bar" style={{ width: pct + "%" }} />
            <span>p(anomaly) {pct}%</span>
          </div>
          <div className={"chip " + (snap.correct ? "chip-green" : "chip-red")}>
            {snap.correct ? "✓ correct" : "✗ miss"}
          </div>
        </Stage>
      </div>

      <div className="pipeline-row">
        <Stage n="4" icon="🔁" title="Incremental learn" active
          sub="partial_fit on every candidate (test-then-train)">
          <div className="chip chip-green">updates: {snap.online_updates.toLocaleString()}</div>
          <div className="chip chip-muted">retained data: 0 windows</div>
        </Stage>
        <Arrow on />
        <Stage n="5" icon="🏆" title="Champion re-election (bandit)" active
          sub="best recent windowed-F1 serves next">
          <div className="pool">
            {snap.candidates?.map((c, i) => (
              <div key={i} className={"cand" + (c.champion ? " champ" : "")}
                title={`η₀ ${c.eta0} · α ${c.alpha} · F1 ${c.score}`}>
                <div className="cand-bar" style={{ height: Math.max(4, c.score * 60) + "px" }} />
                <div className="cand-lbl">{c.score.toFixed(2)}</div>
                {c.champion && <div className="cand-crown">👑</div>}
              </div>
            ))}
          </div>
          <div className="stage-sub small">6 learners · η₀∈{`{.01,.05,.1}`} × α∈{`{1e-4,1e-3}`}</div>
        </Stage>
        <Arrow on />
        <Stage n="6" icon="🌊" title="Drift monitor" active={snap.just_adapted} alert={snap.just_adapted}
          sub="two-window prequential-error test">
          {snap.just_adapted
            ? <div className="chip chip-amber">⚡ DRIFT detected → boost</div>
            : <div className="chip chip-green">stable</div>}
          <div className="chip chip-muted">adaptations: {snap.adapt_events}</div>
        </Stage>
      </div>

      <div className="pipeline-legend">
        <span><b>Online</b> = continuous per-window loop above (no stored data, no batch refit).</span>
        {includePeriodic && (
          <span className={"periodic-tag" + (snap.just_retrained ? " fire" : "")}>
            {snap.just_retrained
              ? `🛑 Offline-periodic is BLOCKING on a full batch refit (#${snap.periodic_retrains})`
              : `🟠 Offline-periodic: next batch refit in ${snap.next_retrain_in} windows`}
          </span>
        )}
      </div>
    </div>
  );
}
