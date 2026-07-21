# Demo — RQ2: What does distributed tracing contribute to root-cause localisation?

> **RQ2.** *Which observability pillar makes a significant contribution to root-cause
> localisation, holding all other signals constant?*

> ## Status: answered — after the experiment was rebuilt
>
> **RQ2 has an answer: traces improve localisation at every noise level tested.**
> It took two attempts to get there. The **first** experiment returned a top-1 of
> **1.000** and was circular — the ranking feature was derived, inside the generator,
> from the ground-truth label. A perfect score is not a finding but a warning.
>
> The generator was rebuilt (commit `984fef5`) so that errors **propagate up the call
> path**, and the experiment re-run on it. This page carries **both**: [the experiment
> that answers RQ2](#the-experiment) and [the first attempt and why it failed](#the-circular-first-attempt),
> set out on the record rather than quietly deleted.
>
> | | First attempt | Rebuilt (reported) |
> |---|---|---|
> | Generator | `ml.dataset.generate_run` (error spans gated on `is_origin`) | `ml.dataset.generate_rca_run` (errors propagate up the call path) |
> | Experiment | `ml/experiments/run_experiment.py::localisation` | `ml/experiments/rq2_localisation.py` |
> | Output | `rq2_localisation.csv` — superseded | `rq2_localisation_propagating.csv` |
> | Top-1 with traces | 1.000 (arithmetic) | **0.563** at a 10 % background-incident rate (inferred) |
>
> The answer is **directional, and bounded in magnitude**: a weaker claim than the
> original 1.000, and the only one the design supports. §5.2 of the dissertation
> reports it the same way.

---

## What localisation is, and why this mesh makes it hard

Detection only says *something is wrong*. Localisation (RCA) says *which service is
to blame*. On the nine-service mesh a fault at a leaf inflates the latency of **every
ancestor on its call path**, so four or five services look almost equally guilty:

```
gateway ─┬─► movie ──► actor, review
         ├─► user ───► recommendation ─► catalog
         │         └─► auth
         └─► search ─────────────────► catalog   (shared fan-in; depth 4)
```

A random guess over nine services scores **0.111**. That is the floor every number
below is read against.

---

## The experiment

```bash
cd aiops
python -m ml.experiments.rq2_localisation --seeds 42,43,44,45,46 --episodes 200
```

Result → **`aiops/data/results/rq2_localisation_propagating.csv`** (+
`rq2_propagating_summary.json`). Roughly 120 fault episodes per seed; five seeds;
mean ± sd reported throughout.

Two things changed, and both were necessary.

**1. Errors now propagate.** In `generate_rca_run`, the fault's errors travel *up*
the call path and attenuate by 0.6 per hop, so **every service on the path emits
error spans**. The origin is no longer the unique emitter — it is distinguished only
by sitting at the **root of the error tree**, which has to be inferred from the call
graph. `is_origin` is not consulted at all on this path. Attenuation is 0.6 per hop
against a noise σ of 0.45, so adjacent hops overlap heavily and *magnitude alone*
does not identify the origin.

**2. The mesh is no longer silent.** `--backgrounds` sets the per-episode
probability that a service *off* the fault's call path errors on its own account.
This is the honesty knob. At `0.0` the mesh contains exactly one error path, which
makes the root of that tree recoverable almost surely — a property of the generator,
not of tracing. Raising it introduces **spurious competing roots**, which is what a
real mesh presents.

Four arms are crossed so that "traces help" is not confounded with "using the call
graph helps":

| | flat ranking | graph-aware (root-of-error-tree) |
|---|---|---|
| **C2** metrics+logs | signal baseline | topology only |
| **C3** + traces | signal effect | signal + topology |

The graph-aware rule scores a service by how much *more* anomalous it is than its
most anomalous callee — `score(s) = anomaly(s) − max{anomaly(c) : c ∈ callees(s)}` —
which peaks where the anomaly *starts* rather than at everything that inherits it.
The functional form is identical with and without traces; `use_traces` changes only
which features reach the scorer, so the C2-vs-C3 contrast isolates the **signal**.

## Results

**Top-1 accuracy vs the background-incident rate** (mean over 5 seeds; random floor
0.111):

```
approach                                bg=0.0   bg=0.1   bg=0.25  bg=0.5
Metrics+Logs (C2)                        0.387    0.359    0.337    0.340
Metrics+Logs+Traces (C3)                 0.626    0.563    0.496    0.456
Metrics+Logs (C2), graph-aware           0.446    0.391    0.274    0.207
Metrics+Logs+Traces (C3), graph-aware    1.000    0.736    0.486    0.335
```

**Top-*k* at `bg = 0.1`** — one episode in ten carries an unrelated incident, the
setting we treat as the honest default:

| approach | top-1 | top-2 | top-3 |
|---|:---:|:---:|:---:|
| Metrics+Logs (C2) | 0.359 ± 0.039 | 0.519 ± 0.032 | 0.724 ± 0.041 |
| Metrics+Logs+Traces (C3) | **0.563 ± 0.022** | 0.791 ± 0.034 | 0.951 ± 0.013 |
| Metrics+Logs (C2), graph-aware | 0.391 ± 0.050 | 0.495 ± 0.057 | 0.532 ± 0.050 |
| Metrics+Logs+Traces (C3), graph-aware | **0.736 ± 0.026** | 0.923 ± 0.027 | 0.948 ± 0.018 |

### What this says — the answer to RQ2

- **Traces contribute, and the contribution is robust.** At every background level C3
  beats C2 on top-1 — +0.24 at bg = 0.0, +0.20 at 0.1, +0.16 at 0.25, +0.12 at 0.5 —
  against seed spreads of 0.02–0.05. No metrics-and-logs arm passes 0.45, whereas the
  same ranker given traces reaches 0.626. **That is the answer to RQ2**, reached by a
  controlled ablation rather than by varying the model, and it agrees in direction
  with the multimodal RCA literature (Han et al. 2024; Wang et al. 2018). The
  **magnitude is a property of the parameterisation**, not a field measurement.
- **Nothing saturates.** The best realistic arm reaches top-1 0.736 and top-3 0.948.
  Without traces, top-1 sits near 0.36 — barely three times the guess floor on a
  nine-service graph. Depth-four fan-in ambiguity is real and survives the fix.
- **The perfect score comes back at bg = 0.0 — and that is the point.** C3 +
  graph-aware scores exactly 1.000 when the mesh carries a single error path,
  because then the root of the error tree is unique by construction. It is no longer
  a *hidden* circularity: it is a visible boundary condition of a silent mesh, and
  the moment one episode in ten carries an unrelated incident it falls to 0.736.
  **Read the bg = 0 column as a sanity check on the rule, never as a result.**
- **Structural reasoning is not free** — the least expected result. Graph-awareness
  dominates on a quiet mesh (1.000 vs 0.626) but decays faster than flat ranking and
  by bg = 0.5 *inverts*: 0.335 against 0.456. The subtraction rule rewards any
  erroring service whose dependencies are clean — and a background incident is
  exactly that — so it promotes spurious roots as readily as true ones, while the
  flat ranker degrades gracefully. **Whether the call graph helps or hurts depends on
  how noisy the mesh is**, a conclusion no single operating point would have exposed,
  and one that qualifies the dependency-graph enthusiasm in the RCA literature.

---

## The circular first attempt

On the record, not suppressed. The localiser ranks services by an anomaly score. Under C3 the
trace **error-span** signal entered that score with a large weight
([`aiops/ml/rca/localiser.py`](aiops/ml/rca/localiser.py)):

```python
if use_traces:
    score += df_service.get("traces.error_spans", ...).mean() * 4.0
```

But in the base generator ([`aiops/collectors/telemetry.py`](aiops/collectors/telemetry.py)),
that signal was assigned like this:

```python
"error_spans": (g(5.0, "err_rate", 0.3)
                if (fault != "normal" and is_origin)     # ← is_origin IS the label
                else g(0.2, "err_rate", 0.4)),
```

`is_origin` is true for **exactly** the service that RQ2 must identify. So
`error_spans` was the answer key, rescaled and given a little noise — roughly 5.0 at
the true root cause and 0.2 everywhere else, a 25× separation. A ranking that weights
it heavily cannot score anything *but* 1.000. **The perfect score was arithmetic, not
evidence.**

The old numbers, retained in `rq2_localisation.csv`:

```
approach                    k   topk_accuracy
metrics+logs (C2)           1   0.7692
metrics+logs (C2)           2   0.8974
metrics+logs (C2)           3   0.9487
metrics+logs+traces (C3)    1   1.0000    ← circular, superseded
metrics+logs+traces (C3)    2   1.0000    ← circular, superseded
metrics+logs+traces (C3)    3   1.0000    ← circular, superseded
```

*(n = 39 fault episodes, single seed.)* Note that even the C2 row is superseded: on
the propagating generator, with every ancestor now emitting errors, metrics+logs
top-1 falls from 0.769 to **0.359**. The original C2 number was flattered by the same
modelling choice — ancestors that inherit latency but almost no errors are far easier
to rule out than real ones.

### The deeper modelling flaw

The circularity was a symptom. The real error was in how propagation was modelled:
a service that inherited a fault's **latency** inherited almost none of its
**errors** (ancestors got `error_spans ≈ 0.2`, i.e. effectively none).

In a real mesh that is false. When your downstream dependency fails, **you return
errors too** — error spans appear all along the call path, and the origin is
distinguishable only as the *root of the error tree*, and then only noisily. The old
generator **removed precisely the ambiguity that makes root-cause attribution hard**
— and removed it from the one experiment whose purpose was to measure that
ambiguity. That is what `generate_rca_run` puts back.

---

## Answered in direction, bounded in magnitude

RQ2 is answered — but the scope of the answer is worth stating precisely.

- **What is claimed:** traces improve localisation at every noise level tested, and
  the graph rule converts that signal into a near-certain answer only where the mesh
  is quiet enough for a single error tree to stand out.
- **What is not:** the magnitudes. Attenuation-per-hop (0.6), the noise, and the
  background rate β are *inputs*, and the trace lift moves with all three. β's
  production value is unknown and is not claimed here. What transfers is the
  **ordering** and the **shape of the degradation**.
- **What would settle it:** a live campaign through the implemented `TF_LIVE=1` path
  would locate a real mesh on the β sweep — the single measurement that turns RQ2's
  direction into a magnitude. That remains the study's principal outstanding
  experiment.
- On the absolute magnitude,
  [Han et al. (2024), HolisticRCA](https://doi.org/10.1145/3691620.3695065) remain
  the stronger evidence, and the dissertation says so.

---

## Artifacts produced

| File | Shows |
|------|-------|
| `aiops/data/results/rq2_localisation_propagating.csv` | **The reported result.** Top-*k* accuracy per (background, seed, arm), 5 seeds × 4 background rates × 4 arms. |
| `aiops/data/results/rq2_propagating_summary.json` | Mean ± sd per arm, plus generator settings and the random floor. |
| `aiops/data/results/rq2_localisation.csv` | The circular first attempt, superseded. Retained so the defect stays inspectable. |

**Bottom line:** a perfect score is not a triumph, it is a defect report. The correct
response to top-1 = 1.000 was to find out why — the feature was the label — then
rebuild the generator and re-run. **RQ2 is answered: traces improve localisation on a
deep mesh (+0.20 top-1 at β = 0.1, positive at every β), the help shrinks as the mesh
gets noisier, structural reasoning inverts once it is noisy enough, and nothing about
it is perfect.** A weaker claim than 1.000, and the only one the design supports.
