# Online vs Offline Learning — and where the techniques come from

This note explains the difference between **offline (batch)** and **online
(streaming)** learning as used in this repo's RQ4 pipeline, and links to the
external sources for every technique the online model is built on.

## The core difference

| | Offline (batch) | Online (streaming) |
|--|--|--|
| **When it learns** | Once, on a fixed historical snapshot, then frozen | Continuously, one sample at a time |
| **Update unit** | Whole dataset re-fit | Single window (`partial_fit`) |
| **Reaction to drift** | None until a manual/scheduled re-fit | Adapts as the data pattern changes |
| **Memory of data** | Must retain a labelled training buffer to re-fit | Keeps only model state; data discarded after use |
| **Latency profile** | Bursty — long stalls during each refit | Smooth — bounded per-window cost |
| **Failure mode** | Decays when "normal" drifts (false alarms on new normal) | Tracks the evolving normal |
| **In this repo** | `offline_static`, `offline_periodic`, `offline_full` (RandomForest) | `online_adaptive` (`OnlineModel`) |

The RQ4 result: on a non-stationary stream, the frozen batch model collapses to
**F1 ≈ 0.5** even with full MELT, scheduled retraining recovers to **~0.89** but
lags at every regime shift, and the online model reaches **~0.98** at oracle
level — updating per sample with zero retained data. See
[`ONLINE_PIPELINE.md`](ONLINE_PIPELINE.md) for the full pipeline.

## Why offline breaks under drift

A batch detector's decision boundary is calibrated on the operating point that
held *when it was trained*. When operations move that baseline — a release
regresses latency, autoscaling doubles throughput, data growth raises the JVM
memory footprint — the new **normal** crosses the old boundary and gets flagged
as anomalous. This is **concept/covariate drift**, and it is why "train a
snapshot, ship it" decays in production. Online learning answers it structurally
by re-centring on the current normal instead of a stale one.

## Where the techniques come from (source links)

The `OnlineModel` is not a novel algorithm — it composes well-established
streaming-ML building blocks. Sources for each:

> **Access note:** all links below point to the correct, canonical resources. The
> **ACM** DOIs (Gama 2014, West 1979) block automated crawlers and may only open
> in a normal browser, and the **Springer** article (Gama 2013) is behind a
> login/paywall requiring institutional access — these are access restrictions,
> not broken links. The scikit-learn, Wikipedia, River, and scikit-multiflow
> links are openly accessible.

### 1. Incremental learning — `SGDClassifier.partial_fit`
- scikit-learn, *Incremental / out-of-core learning*:
  https://scikit-learn.org/stable/computing/scaling_strategies.html#incremental-learning
- `SGDClassifier` API (the per-sample log-loss learner used by each candidate):
  https://scikit-learn.org/stable/modules/generated/sklearn.linear_model.SGDClassifier.html

### 2. Prequential (test-then-train) evaluation & concept-drift adaptation
- Gama, Žliobaitė, Bifet, Pechenizkiy, Bouchachia (2014), *A survey on concept
  drift adaptation*, ACM Computing Surveys — the reference cited in
  `ml/models/online.py`:
  https://dl.acm.org/doi/10.1145/2523813
- Gama, Sebastião, Rodrigues (2013), *On evaluating stream learning algorithms*
  (prequential error): https://link.springer.com/article/10.1007/s10994-012-5320-9

### 3. Exponentially-weighted running mean/variance (adaptive normalisation)
- West (1979), *Updating mean and variance estimates: an improved method*,
  Communications of the ACM — the EW variance update in `_EWStandardizer`:
  https://dl.acm.org/doi/10.1145/359146.359153
- Welford's / incremental moments background:
  https://en.wikipedia.org/wiki/Algorithms_for_calculating_variance#Welford's_online_algorithm

### 4. Online model selection (the champion-by-F1 bandit)
- Multi-armed bandit overview:
  https://en.wikipedia.org/wiki/Multi-armed_bandit

### 5. General online / streaming ML libraries (the ecosystem this mirrors)
- **River** — the standard Python online-ML library (the canonical reference
  implementation of these patterns): https://riverml.xyz/
  - GitHub: https://github.com/online-ml/river
- **scikit-multiflow** (predecessor, drift detectors / streaming evaluation):
  https://scikit-multiflow.github.io/

### 6. Drift detectors (the family our two-window monitor belongs to)
- DDM / EDDM and ADWIN are the classic drift detectors; River's drift module is
  the practical reference:
  https://riverml.xyz/latest/api/drift/ADWIN/

> Note: the `OnlineModel` in this repo implements these ideas directly on top of
> NumPy + scikit-learn (rather than depending on River) to keep the experiment
> self-contained, but River is the place to look for production-grade,
> battle-tested versions of every mechanism above.
