# Demo — RQ4: Which model family best exploits multimodal telemetry?

> **RQ4.** *Which model family best exploits rich, multimodal observability features,
> and what does that choice imply for the model that must run in the online setting?*

RQ3 established that production demands a detector that **keeps learning**. RQ4 closes
the loop: under the richest configuration (**C4, full MELT**), which model family is
strongest on the offline tabular task — and what does that imply for the *online*
detector RQ3 showed to be necessary? This demo fixes the telemetry (C4) and varies only
the model.

Contestants: **RandomForest (RF)**, **GradientBoosting (GB)**, **XGBoost (XGB)**,
**LSTM** (sequence model), and a **multimodal late-fusion** detector (HolisticRCA-style
per-pillar heads combined).

---

## Run it (no cluster needed)

```bash
cd aiops
bash scripts/run_offline.sh 200          # produces rq4_model_family.csv
```

Result is written to **`aiops/data/results/rq4_model_family.csv`**.

> `xgb` requires `xgboost` and `lstm` requires `torch`; both are optional. If `torch`
> is absent the LSTM row is skipped (it is shown here only as a contrast).

---

## What you see

```
model                precision  recall   f1      auc_roc
rf                   0.994      0.993    0.994   0.999     ← strongest
gb                   0.993      0.989    0.991   0.999
xgb                  0.992      0.990    0.991   0.999
multimodal_fusion    0.994      0.894    0.941   0.988
lstm                 0.323      0.075    0.122   —         ← needs torch / much more data
```

---

## Why this happens (talking points)

- **Ensemble trees dominate on multimodal *tabular* telemetry.** RF, GB and XGB all land
  at F1 ≈ 0.99. The C4 feature vector is 23 flat, window-local aggregates (rates,
  percentiles, counts, baseline deviations) — exactly the heterogeneous,
  mixed-scale tabular regime where gradient-boosted / bagged trees excel. **RF is the
  strongest family** (F1 = 0.994).
- **Late fusion is precise but lower recall** (0.94 F1): combining per-pillar heads
  keeps precision high (0.994) but misses more anomalies (recall 0.894) than a single
  tree over the joint feature space — extra architecture, no accuracy gain here.
- **LSTM underperforms badly** (F1 = 0.12) — a deep sequence model is starved on this
  amount of data and adds nothing over trees on already-aggregated window features. A
  cautionary result: deep ≠ better when the representation is tabular and data is finite.
- **The twist — why the offline winner is *not* the online detector.** RF wins offline,
  but a RandomForest cannot update incrementally per window; refitting one is the very
  ~0.5 s blocking stall that sinks `offline_periodic` in RQ3. So the online setting RQ3
  mandates calls for a model that supports `partial_fit` with bounded per-window cost —
  **a lightweight normalised linear / SGD model, not a tree.** RQ4 therefore *reconciles*
  the evidence: trees are best for a one-shot offline fit, but the constraint that the
  detector must keep learning per sample is exactly why the deployed `online_adaptive`
  detector is a streaming linear model (with adaptive normalisation + a self-selecting
  hyper-parameter pool), and RQ3 shows that model reaches the same F1 ≈ 0.98 online.

---

## Artifacts produced

| File | Shows |
|------|-------|
| `aiops/data/results/rq4_model_family.csv` | F1/precision/recall/AUC for RF / GB / XGB / LSTM / fusion at C4 |

**Bottom line:** **ensemble trees (RF) are the strongest family** on rich multimodal
tabular telemetry (F1 ≈ 0.99) — and that is precisely *why a lightweight normalised
linear model, not a tree, is the right detector for the online setting* RQ3 proved
necessary: the best batch model can't `partial_fit`, so the streaming constraint, not
raw offline accuracy, picks the deployed model.
