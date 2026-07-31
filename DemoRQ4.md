# Demo — RQ4: Which model family best exploits multimodal telemetry?

> **RQ4.** *Which model family best exploits rich, multimodal observability features,
> and what does that choice imply for the model that must run in the online setting?*

RQ3 established that production demands a detector that **keeps learning**. RQ4 closes
the loop: under the richest configuration (**C4, full MELT**), which model family is
strongest on the offline tabular task — and what does that imply for the *online*
detector RQ3 showed to be necessary? This demo fixes the telemetry (C4) and varies only
the model.

Contestants: **RandomForest (RF)**, **GradientBoosting (GB)**, **XGBoost (XGB)**,
**LSTM** (sequence model), a **multimodal late-fusion** detector (HolisticRCA-style
per-pillar heads combined), and — opt-in — a **local LLM detector** (Qwen2.5-3B via
Ollama) reading the *raw* signals rather than engineered features.

---

## Run it (no cluster needed)

```bash
cd aiops
bash scripts/run_offline.sh 200          # produces rq4_model_family.csv (5 families)
```

Result is written to **`aiops/data/results/rq4_model_family.csv`**.

> `xgb` requires `xgboost` and `lstm` requires `torch`; both are optional. If `torch`
> is absent the LSTM row is skipped (it is shown here only as a contrast).

The sixth family needs Ollama reachable and costs ~9 s/window, so it runs separately
and writes to its own directory — it cannot overwrite the committed artefacts:

```bash
make ollama-forward                        # terminal 1 — leave running
make llm OUT=data/results_llm              # terminal 2 — ~10 h on laptop CPU
```

---

## What you see

**Five families, full held-out split** (`rq4_model_family.csv`):

```
model                precision  recall   f1      auc_roc
gb                   0.995      0.980    0.988   0.999     ← leading family
rf                   0.989      0.982    0.986   0.998
xgb                  0.989      0.979    0.984   0.999
multimodal_fusion    0.999      0.804    0.891   0.992
lstm                 0.173      0.328    0.227   —         ← mis-specified; see below
```

**Six families, the paper's table** — all scored on the *same* 3,000-window subsample,
because the LLM costs seconds per window (`results_uniform/` + `results_llm/`):

```
model                precision  recall   f1      note
gb                   1.000      0.980    0.990   leading family
rf                   0.986      0.982    0.984   representative ensemble
xgb                  0.990      0.978    0.984   within noise of the above
multimodal_fusion    0.997      0.805    0.891   high precision, low recall
llm  (Qwen2.5-3B)    0.372      0.540    0.440   RAW signals, no features
lstm (temporal)      0.166      0.361    0.227   mis-specified; see below
```

> A family appearing in both tables differs in the third decimal — they are different
> samples, not drift. Never quote a row from one against a row from the other.

---

## Why this happens (talking points)

- **Ensemble trees dominate on multimodal *tabular* telemetry.** GB, RF and XGB cluster
  within 0.006 F1, each above 0.98 precision. The C4 feature vector is 23 flat,
  window-local aggregates (rates, percentiles, counts, baseline deviations) — exactly
  the heterogeneous, mixed-scale tabular regime where boosted/bagged trees excel.
  Their mutual separation is **smaller than the run-to-run spread**, so we claim **the
  family, not a member of it**.
- **Late fusion is precise but low-recall** (0.891 F1): per-pillar heads keep precision
  at 0.997 but miss far more anomalies (recall 0.805) than a single tree over the joint
  feature space — extra architecture, no accuracy gain here.
- **The LLM is a working detector, not a competitive one** (0.440). It reads the raw
  MELT signals rather than engineered features, and lands *above* the always-alarm floor
  of 0.292 but far below every tree. Two things to say with it: its row name carries its
  own audit trail (`llm_qwen2.5:3b(llm,err=0/300,n=3000/6480)` — it must read `llm`, not
  `heuristic`, with `err=0`), and because it consumes attacker-influenceable text it
  carries a **prompt-injection exposure** the feature-based classifiers do not.
- **The LSTM row is a mis-specification, not a negative result** (0.227). It scores
  *below* the always-alarm floor because our stream **interleaves per-service windows**,
  so the temporal ordering an LSTM exists to exploit is largely absent from what it was
  shown. A per-service sequential representation was **not** evaluated, so this study
  offers **no** evidence about temporal models. Do not let anyone read it as one.
- **The twist — why the offline winner is *not* the online detector.** Trees win
  offline, but a Random Forest cannot update incrementally per window; refitting one is
  the very 580–880 ms blocking stall that burdens `offline_periodic` in RQ3. The online
  setting prizes a **bounded** per-window update, which a normalised linear model gives
  at `O(d)` and ~15 KB of footprint — the configuration-aware features having already
  done the non-linear work. RQ4 therefore *reconciles* the evidence: **the strongest
  batch model and the strongest streaming model are deliberately not the same**, and
  conflating them is one way single-snapshot evaluations mislead.

---

## Artifacts produced

| File | Shows |
|------|-------|
| `aiops/data/results/rq4_model_family.csv` | F1/precision/recall/AUC for RF / GB / XGB / LSTM / fusion at C4, full split |
| `aiops/data/results_uniform/rq4_model_family.csv` | the same five families at `limit=3000`, the paper's subsample |
| `aiops/data/results_llm/rq4_llm_row.csv` | the LLM row, identical split and prefix |

**Bottom line:** **ensemble trees are the strongest family** on rich multimodal tabular
telemetry (F1 ≈ 0.99, no ordering claimed within them) — and that is precisely *why a
lightweight normalised linear model, not a tree, is the right detector for the online
setting* RQ3 proved necessary: the best batch model can't `partial_fit`, so the
streaming constraint, not raw offline accuracy, picks the deployed model.
