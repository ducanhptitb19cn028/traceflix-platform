# Online vs Offline Model Pipeline: Consolidated Results (RQ1, RQ2, RQ3)

This document collects **all** experimental results for the anomaly-detection
study: detection completeness across telemetry configurations (**RQ1**),
root-cause localisation (**RQ2**), and the head-to-head comparison between the
**offline (batch)** and **online (streaming)** pipelines across all four
configurations and four operating regimes (**RQ3**). It ends with a single
overall conclusion.

- **Source data:** `aiops/data/results/` (`rq1_completeness.csv`, `rq2_localisation.csv`,
  `rq3_online_vs_offline.csv`, `rq3_cost.csv`, `rq3_timeline.csv`,
  `summary.json`, `rq3_summary.json`, `rq3_cost_summary.json`)
- **Conceptual background:** [`ONLINE_VS_OFFLINE.md`](ONLINE_VS_OFFLINE.md),
  [`ONLINE_PIPELINE.md`](ONLINE_PIPELINE.md)

---

## 1. Experiment setup

| Parameter | Value |
|--|--|
| Mode | Synthetic, prequential (test-then-train) |
| Episodes | 320 |
| Windows evaluated | 11,520 (2,880 warm-up R0 + 8,640 future) |
| Services | `movie-service`, `actor-service`, `review-service` |
| Regimes | R0 baseline → R1 latency regression → R2 scale-out → R3 combined load |
| Periodic retrain | every 500 windows (17 refits), on a 2,880-window training buffer |

### Telemetry configurations (feature sets)

| Config | Name | Features |
|--|--|--|
| **C1** | Metrics-Only | 10 |
| **C2** | Metrics + Logs | 14 |
| **C3** | Metrics + Logs + Traces | 18 |
| **C4** | Full MELT | 23 |

### Models compared

| Model | Family | Learning |
|--|--|--|
| `offline_static` | RandomForest | Train once on R0, then frozen |
| `offline_periodic` | RandomForest | Re-fit every 500 windows on a 2,880-window buffer |
| `online_adaptive` | `OnlineModel` (SGD + EW normalisation + champion bandit) | `partial_fit`, one window at a time |
| `offline_full` | RandomForest | Oracle — trained on all regimes (reference ceiling) |

---

## 2. RQ1 — Detection completeness vs telemetry richness

Does adding more telemetry signals (metrics → logs → traces → full MELT) improve
detection? Single-pass detection quality on the held-out set (`rq1_completeness.csv`).
Best-performing batch model per config. Higher is better.

| Config | Name | Features | Precision | Recall | F1 | AUC-ROC |
|--|--|--|--|--|--|--|
| **C1** | Metrics-Only | 10 | 0.9509 | 0.8659 | 0.9064 | 0.9740 |
| **C2** | Metrics + Logs | 14 | 0.9601 | 0.9078 | 0.9332 | 0.9847 |
| **C3** | Metrics + Logs + Traces | 18 | 0.9847 | 0.9916 | 0.9882 | 0.9994 |
| **C4** | Full MELT | 23 | 0.9944 | 0.9930 | **0.9937** | 0.9993 |

**Reading:** detection quality rises **monotonically** with telemetry richness.
The biggest jump is **adding traces** (C2→C3: F1 0.933 → 0.988), which lifts both
precision and recall together — traces resolve the cross-service signal that
metrics and logs alone miss. Full MELT (C4) is marginally the best at F1 ≈ 0.994.
This is the stationary, single-pass ceiling; RQ3 below shows how that ceiling
behaves once the stream drifts.

---

## 3. RQ2 — Root-cause localisation (top-k accuracy)

Once an anomaly is detected, can the pipeline name the culprit service? Top-k
localisation accuracy over the injected fault episodes (`rq2_localisation.csv`). Higher is
better.

| Approach | top-1 accuracy | top-2 accuracy |
|--|--|--|
| metrics + logs (C2) | 0.9068 | 1.0000 |
| metrics + logs + traces (C3) | **1.0000** | **1.0000** |

**Reading:** with metrics + logs alone the correct service is ranked #1 in ~91%
of cases and is always within the top 2. **Adding traces makes localisation
perfect** — top-1 accuracy reaches 100%, because span-level dependency
information pinpoints the originating service directly rather than inferring it
from correlated symptoms. This mirrors RQ1: traces are the decisive signal.

---

## 4. RQ3 — Headline result: F1 on the future (drifted) stream

F1 over the 8,640 post-warm-up windows (`overall_future`). Higher is better.

| Config | offline_static | offline_periodic | online_adaptive | Online gain vs static | Online gain vs periodic |
|--|--|--|--|--|--|
| **C1** Metrics-Only | 0.4894 | 0.7574 | **0.8174** | +0.3280 | +0.0600 |
| **C2** Metrics+Logs | 0.4921 | 0.7776 | **0.8347** | +0.3426 | +0.0571 |
| **C3** Metrics+Logs+Traces | 0.5097 | 0.8904 | **0.9817** | +0.4720 | +0.0913 |
| **C4** Full MELT | 0.5112 | 0.8905 | **0.9834** | +0.4722 | +0.0929 |

**Reading:** the frozen batch model collapses to **F1 ≈ 0.49–0.51** on the drifted
stream regardless of how much telemetry it is given. Scheduled retraining recovers
substantially (up to ~0.89), but the online model wins at every configuration,
reaching **~0.98** under full MELT — and even beats the all-regime oracle
(`offline_full` = 0.939 at C4).

---

## 5. RQ3 — Per-regime F1 breakdown

F1 by model × regime, per configuration. Bold marks the best learner in each regime.

### C1 — Metrics-Only
| Regime | offline_static | offline_periodic | online_adaptive |
|--|--|--|--|
| R1 latency regression | 0.4446 | 0.6950 | **0.8294** |
| R2 scale-out | 0.5743 | **0.8003** | 0.7912 |
| R3 combined load | 0.4751 | 0.7942 | **0.8286** |

### C2 — Metrics + Logs
| Regime | offline_static | offline_periodic | online_adaptive |
|--|--|--|--|
| R1 latency regression | 0.4484 | 0.7131 | **0.8548** |
| R2 scale-out | 0.5797 | **0.8153** | 0.7997 |
| R3 combined load | 0.4750 | 0.8201 | **0.8458** |

### C3 — Metrics + Logs + Traces
| Regime | offline_static | offline_periodic | online_adaptive |
|--|--|--|--|
| R1 latency regression | 0.4351 | 0.7961 | **0.9858** |
| R2 scale-out | 0.6842 | 0.9610 | **0.9772** |
| R3 combined load | 0.4782 | 0.9310 | **0.9819** |

### C4 — Full MELT
| Regime | offline_static | offline_periodic | online_adaptive |
|--|--|--|--|
| R1 latency regression | 0.4350 | 0.7942 | **0.9885** |
| R2 scale-out | 0.6939 | 0.9610 | **0.9793** |
| R3 combined load | 0.4778 | 0.9335 | **0.9825** |

**Reading:** the online model is best in **10 of the 12** regime × config cells.
The two exceptions are both **R2 scale-out** under thin telemetry (C1, C2), where
periodic retraining narrowly leads — coherent rather than anomalous, because
scale-out is predominantly **virtual drift** (feature baselines shift but the
concept does not), so a batch refit recovers the boundary as well as continuous
updating. By contrast **R1 latency regression** is **real concept drift**, and it
is there that `offline_static` is hurt most (F1 ≈ 0.44, its lowest) while
`online_adaptive` holds 0.83–0.99. The static model's high recall but very low
precision (it flags almost everything as anomalous once the baseline drifts) is
the classic "stale normal" failure mode.

---

## 6. RQ3 — Cost / efficiency comparison (periodic vs online)

Operational measurements (latency, footprint, retained windows, CPU) come from a
dedicated cost-profiling run (`rq3_cost.csv`, `rq3_cost_summary.json`); because
they reflect the *mechanism* rather than the dataset size, they are reported here
alongside the Run-B `overall_future` F1 (§4) so a single F1 value is used
throughout.

| Config | Model | F1 | Max ms/window | Model size (KB) | Retained windows | Total time (s) |
|--|--|--|--|--|--|--|
| C1 | offline_periodic | 0.7574 | 621.0 | 8290.4 | 2880 | 6.48 |
| C1 | online_adaptive | 0.8174 | 31.3 | 14.9 | 0 | 36.72 |
| C2 | offline_periodic | 0.7776 | 621.4 | 7979.2 | 2880 | 6.50 |
| C2 | online_adaptive | 0.8347 | 36.9 | 15.2 | 0 | 37.86 |
| C3 | offline_periodic | 0.8904 | 646.5 | 3047.0 | 2880 | 6.52 |
| C3 | online_adaptive | 0.9817 | 28.7 | 15.4 | 0 | 36.87 |
| C4 | offline_periodic | 0.8905 | 594.0 | 3588.8 | 2880 | 6.28 |
| C4 | online_adaptive | 0.9834 | 18.9 | 15.7 | 0 | 27.60 |

### Cost ratios (periodic ÷ online unless noted)

| Config | F1 gain (online−periodic) | Max-latency ratio (periodic/online) | Model-size ratio (periodic/online) | Retained windows (periodic vs online) | Total CPU ratio (online/periodic) |
|--|--|--|--|--|--|
| C1 | +0.0600 | 19.8× | 556.4× | 2880 vs 0 | 5.7× |
| C2 | +0.0571 | 16.8× | 524.9× | 2880 vs 0 | 5.8× |
| C3 | +0.0913 | 22.6× | 197.9× | 2880 vs 0 | 5.7× |
| C4 | +0.0929 | 31.5× | 228.6× | 2880 vs 0 | 4.4× |

**Reading the cost trade-off:**
- **Tail latency:** periodic retraining produces huge per-window spikes (up to
  ~650 ms when a refit lands) — **17–32× worse** than the online model's bounded
  per-window cost (≤37 ms). Online learning has a smooth latency profile; batch
  retraining is bursty.
- **Memory / footprint:** the online model is **~200–550× smaller** (≈15 KB vs
  3–8 MB) and retains **zero** historical windows, versus the 2,880-window
  labelled buffer the periodic model must keep to refit.
- **Total CPU:** the online model does pay more *aggregate* CPU (≈4–6× the
  periodic total, because it updates on every one of 8,640 future windows rather
  than ~17 batch refits) — but it spends that cost *smoothly and predictably* and
  never stalls the pipeline with a multi-hundred-millisecond spike.

So the online model buys **higher accuracy, far lower tail latency, far smaller
footprint, and no data-retention requirement**, at the cost of modestly higher
steady-state CPU.

---

## 7. RQ3 — Online-model adaptation behaviour

From `rq3_summary.json` (`per_config`). The champion-by-F1 bandit re-selects
hyper-parameters as drift appears; richer telemetry needs fewer corrective
adapt events.

| Config | Features | Periodic retrains | Online adapt events | Final champion (eta0, alpha) |
|--|--|--|--|--|
| C1 | 10 | 17 | 4 | eta0=0.10, alpha=1e-4 |
| C2 | 14 | 17 | 2 | eta0=0.01, alpha=1e-4 |
| C3 | 18 | 17 | 0 | eta0=0.05, alpha=1e-4 |
| C4 | 23 | 17 | 0 | eta0=0.05, alpha=1e-4 |

**Reading:** with thin telemetry (C1) the online model has to switch champions
four times to keep up with drift, twice at C2; once traces are added (C3/C4) the
signal is rich enough that no re-selection is needed at all. Richer telemetry
both raises accuracy and stabilises the adaptation process.

---

## 8. Conclusion

**RQ1 (completeness)** and **RQ2 (localisation)** establish that telemetry
richness drives both detection and root-cause quality: F1 climbs monotonically
from 0.906 (Metrics-Only) to 0.994 (Full MELT), and **traces are the decisive
signal** — they push detection F1 from 0.933 to 0.988 and root-cause top-1
accuracy from 0.91 to a perfect 1.0. But RQ1 measures a *stationary* ceiling;
RQ3 shows what happens once the stream drifts.

Across **every** configuration and the **large majority of regimes**, the **online
adaptive pipeline dominates the offline pipelines** on detection quality, and it
does so while being dramatically cheaper on the operational axes that matter in
production:

1. **Accuracy.** Online F1 ranges **0.82 → 0.98** vs **0.49 → 0.51** for the
   frozen batch model and **0.76 → 0.89** for scheduled retraining. The online
   model wins at every configuration and is best in **10 of 12** regime×config
   cells (the two exceptions are virtual-drift scale-out under thin telemetry),
   and under full MELT it even exceeds the all-regime *oracle* batch model
   (0.983 vs 0.939).

2. **Drift is the deciding factor.** The offline_static model's collapse is not a
   tuning problem — it is structural. Once operations move the baseline (latency
   regression, scale-out, combined load), the stale decision boundary flags the
   *new normal* as anomalous (high recall ~0.97–1.00, low precision ~0.33–0.34).
   Adding more telemetry (C1→C4) does **not** rescue the frozen model; only
   *relearning* does.

3. **More telemetry helps, but only with adaptation.** Going Metrics-Only →
   Full MELT lifts online F1 from 0.82 to 0.98 and collapses the residual gap to
   the oracle. The same telemetry barely moves the static model (0.49→0.51).
   Telemetry richness and continual learning are complementary; neither alone is
   sufficient.

4. **Operational cost favours online.** The online model is **17–32× better on
   tail latency**, **~200–550× smaller**, and retains **no historical data**,
   versus a periodic model that must hold a 2,880-window buffer and stalls the
   pipeline with ~600 ms refit spikes. Its only cost is ~4–6× higher *steady*
   CPU — spent smoothly, never in a stall.

**Bottom line:** for a non-stationary observability stream, the **online
streaming pipeline is the recommended production design**. Offline static
detection is unsafe under drift, and offline periodic retraining is a partial,
expensive, and laggy patch. The online pipeline delivers near-oracle accuracy
with bounded latency, a tiny footprint, and zero data retention.
