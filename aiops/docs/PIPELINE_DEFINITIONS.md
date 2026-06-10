# Pipeline Definitions — Online vs Offline

Short, precise definitions of the two anomaly-detection pipelines in this repo,
as they are actually implemented. For the full comparison and external sources
see [`ONLINE_VS_OFFLINE.md`](ONLINE_VS_OFFLINE.md); for the end-to-end walkthrough
see [`ONLINE_PIPELINE.md`](ONLINE_PIPELINE.md).

## Offline pipeline

> **Definition.** A *batch* learning pipeline that fits a model **once** on a
> fixed, historical snapshot of labelled telemetry, then serves predictions from
> that **frozen** model. Any adaptation to new data requires a full **re-fit** on
> a retained training buffer — either never (`offline_static`) or on a fixed
> schedule (`offline_periodic`).

**Characteristics**
- Learns from the **whole training set at once**; the model is immutable between fits.
- Must **retain a labelled data buffer** to re-fit.
- Cost is **bursty** — long stalls during each re-fit, near-zero between.
- **Decays under drift**: a boundary calibrated on the old "normal" misfires when
  the operating baseline shifts, until the next manual/scheduled re-fit.

**In this repo** — RandomForest (`models/detectors.py::BaselineModel`), driven in
three modes by `experiments/online_vs_offline.py`:
- `offline_static` — fit once on regime R0, frozen forever.
- `offline_periodic` — re-fit every `--retrain-every` windows on the last
  `--train-window` labelled windows (the realistic production compromise).
- `offline_full` — fit on a random split across *all* regimes; an unrealistic
  oracle ceiling used only to isolate drift as the cause of decay.

## Online pipeline

> **Definition.** A *streaming* learning pipeline that updates the model
> **incrementally, one window at a time**, under the prequential
> (test-then-train) protocol: predict the incoming window, then learn from its
> revealed label. It **never re-fits offline** and keeps **no training data
> buffer** — it adapts continuously from the incoming data pattern.

**Characteristics**
- Learns **per sample** via `partial_fit`; model state evolves every window.
- Retains **only model state**, not past data.
- Cost is **smooth** — a small, bounded amount of work every window.
- **Drift-robust**: tracks the *evolving* normal, so a fault stays a deviation in
  any regime.

**In this repo** — `online_adaptive` = `models/online.py::OnlineModel`, composed of
four mechanisms:
1. **Adaptive normalisation** — EW running mean/variance (`_EWStandardizer`)
   updated only from normal windows, tracking today's operating point.
2. **Incremental learning** — `SGDClassifier.partial_fit`, prequential.
3. **Dynamic parameter optimisation** — a pool of candidates; the champion is
   re-elected by recent windowed F1 (an online model-selection bandit).
4. **Drift-triggered acceleration** — a two-window error monitor that speeds
   re-centring after an abrupt shift.

## One-line contrast

> **Offline** trains a snapshot and ships it (re-fit to adapt); **online** learns
> continuously per window and never re-fits. On a non-stationary stream the
> offline model decays (F1 ≈ 0.5) while the online model holds at oracle level
> (F1 ≈ 0.98) — see [`ONLINE_PIPELINE.md`](ONLINE_PIPELINE.md).
