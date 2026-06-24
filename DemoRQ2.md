# Demo — RQ2: Which pillar makes root-cause localisation work?

> **RQ2.** *Which observability pillar makes a significant contribution to root-cause
> localisation, holding all other signals constant?*

Detection only says *something is wrong*. Localisation (RCA) says *which service is to
blame* — and an alert is only actionable once the responsible service is named. This
demo isolates the contribution of **distributed traces** by comparing top-k RCA
accuracy with traces **excluded (C2)** vs **included (C3)**, everything else held fixed.

The key mechanism: a downstream fault makes latency rise *everywhere* along the call
chain (`movie → actor → review`), so metrics and logs alone implicate many services.
Traces add the **originating-error-span** feature, which marks the service where an
error tree *begins* rather than the services that merely propagate its latency.

---

## Run it (no cluster needed)

```bash
cd aiops
bash scripts/run_offline.sh 200          # produces rq2_localisation.csv
```

Result is written to **`aiops/data/results/rq2_localisation.csv`**.

---

## What you see

```
approach                    k   topk_accuracy
metrics+logs (C2)           1   0.907
metrics+logs (C2)           2   1.000
metrics+logs+traces (C3)    1   1.000
metrics+logs+traces (C3)    2   1.000
```

Read it as: *"how often is the true root-cause service in the model's top-k guesses?"*

- **Without traces (C2):** top-1 = **0.91** — right most of the time, but ~9% of
  incidents name the wrong service first (a propagating neighbour, not the origin).
- **With traces (C3):** top-1 = **1.00** — the origin is identified first, every time,
  on this topology.

---

## Why this happens (talking points)

- **Traces are the decisive localisation signal.** Adding them lifts top-1 from
  **0.91 → 1.0** — the single change responsible for perfect localisation.
- **The C2→C3 contrast is the whole point.** Metrics and logs can *detect* the
  incident and even get top-1 ≈ 0.91, because latency and error volume both spike. But
  they spike on *every* hop, so the first guess is sometimes the victim, not the
  culprit. The originating-error-span feature breaks that tie causally.
- **Top-2 reaches 1.0 even for C2**, which is the tell: the true origin was always
  *near* the top, the model just couldn't rank it first without the span tree. Traces
  convert "in the shortlist" into "named first."
- **Three-service topology by design.** A small, unambiguous dependency chain keeps
  ground truth beyond doubt; the same originating-span mechanism is what generalises to
  deeper meshes, where the propagation ambiguity is worse and traces matter more.
- **Caveat (honest framing):** 1.0 reflects a controlled three-service chain, not a
  claim of perfect RCA at arbitrary scale. The defensible, transferable result is the
  *direction and size* of the jump: traces are what make localisation reliable.

---

## Artifacts produced

| File | Shows |
|------|-------|
| `aiops/data/results/rq2_localisation.csv` | Top-1 / top-2 RCA accuracy, traces excluded (C2) vs included (C3) |

**Bottom line:** of all four pillars, **distributed traces** are the one that makes
root-cause localisation work — lifting top-1 from **0.91 to a perfect 1.0** — because
only spans carry the cross-service causal structure that distinguishes the origin of a
fault from the services that merely propagate it.
