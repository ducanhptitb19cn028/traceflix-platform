# Demo — RQ2: Which pillar makes root-cause localisation work?

> **RQ2.** *Which observability pillar makes a significant contribution to root-cause
> localisation, holding all other signals constant?*

> ## ⚠️ This result is WITHDRAWN
>
> **The experiment below does not answer RQ2.** Its headline number — top-1 localisation
> accuracy of **1.000** with traces — is **circular**: the feature the localiser ranks on
> is derived, inside the data generator, from the ground-truth label it is being asked to
> recover. The number measures the generator, not the method. **No conclusion about
> distributed tracing may be drawn from it.**
>
> This page is kept, and the result files are kept, so that the defect is inspectable
> rather than quietly deleted. Section 5.2 of the dissertation reports the same
> withdrawal. If you want the corrected experiment, see
> [What the fix looks like](#what-the-fix-looks-like) below.

---

## What the experiment does

Detection only says *something is wrong*. Localisation (RCA) says *which service is to
blame*. This experiment compares top-*k* RCA accuracy with traces **excluded (C2)** vs
**included (C3)** on the nine-service mesh, holding everything else fixed.

```bash
cd aiops
bash scripts/run_offline.sh 200          # produces rq2_localisation.csv
```

Result → **`aiops/data/results/rq2_localisation.csv`**.

```
approach                    k   topk_accuracy
metrics+logs (C2)           1   0.7692
metrics+logs (C2)           2   0.8974
metrics+logs (C2)           3   0.9487
metrics+logs+traces (C3)    1   1.0000    ← circular
metrics+logs+traces (C3)    2   1.0000    ← circular
metrics+logs+traces (C3)    3   1.0000    ← circular
```

*(n = 39 fault episodes. 0.7692 = 30/39; 0.8974 = 35/39; 0.9487 = 37/39.)*

---

## Why the C3 rows are circular

The localiser ranks services by an anomaly score. Under C3 the trace **error-span**
signal enters that score with a large weight
([`aiops/ml/rca/localiser.py`](aiops/ml/rca/localiser.py)):

```python
if use_traces:
    score += df_service.get("traces.error_spans", ...).mean() * 4.0
```

But in the generator ([`aiops/collectors/telemetry.py`](aiops/collectors/telemetry.py)),
that signal is assigned like this:

```python
"error_spans": (g(5.0, "err_rate", 0.3)
                if (fault != "normal" and is_origin)     # ← is_origin IS the label
                else g(0.2, "err_rate", 0.4)),
```

`is_origin` is true for **exactly** the service that RQ2 must identify. So
`error_spans` is the answer key, rescaled and given a little noise — roughly 5.0 at the
true root cause and 0.2 everywhere else, a 25× separation. A ranking that weights it
heavily cannot score anything *but* 1.000. **The perfect score is arithmetic, not
evidence.**

### The deeper modelling flaw

The circularity is a symptom. The real error is in how propagation is modelled: in the
generator, a service that inherits a fault's **latency** inherits almost none of its
**errors** (ancestors get `error_spans ≈ 0.2`, i.e. effectively none).

In a real mesh that is false. When your downstream dependency fails, **you return errors
too** — error spans appear all along the call path, and the origin is distinguishable
only as the *root of the error tree*, and then only noisily. The generator therefore
**removes precisely the ambiguity that makes root-cause attribution hard** — and it
removes it from the one experiment whose entire purpose was to measure that ambiguity.

---

## What actually survives

The **C2 row is not circular in the same way**, and it does carry a real (if modest)
finding about the *topology*:

- Top-1 is only **0.769**, and top-*k* **does not saturate** even at *k* = 3 (0.949).
- Mechanism: a fault at a leaf inflates the latency of **every ancestor on its path**, so
  four or five services look almost equally guilty and a dependent frequently ranks first.
- That a depth-four call graph makes latency-based attribution genuinely ambiguous is a
  property of the topology, which the generator reproduces faithfully. **That stands.**

What does **not** stand is any quantification of how much of that ambiguity *real*
distributed traces would resolve. On that question,
[Han et al. (2024), HolisticRCA](https://doi.org/10.1145/3691620.3695065) remain the
better evidence, and the dissertation says so.

---

## What the fix looks like

Two routes, both listed as future work (Chapter 7):

1. **Fix the generator.** Propagate error spans along the call path — a failing
   dependency should induce error spans in its callers — so that the origin is
   identifiable only as the *root* of the error tree, and only probabilistically. Then
   re-run. Localisation becomes a genuine inference problem and the top-*k* curve becomes
   informative.
2. **Collect live.** Run the campaign through the implemented `TF_LIVE=1` path against the
   real instrumented cluster, where error propagation is whatever it actually is rather
   than whatever we modelled it to be.

---

## Artifacts produced

| File | Shows |
|------|-------|
| `aiops/data/results/rq2_localisation.csv` | Top-*k* RCA accuracy, C2 vs C3. **C3 rows withdrawn** (circular); C2 rows valid. |

**Bottom line:** a perfect score is not a triumph, it is a defect report. The correct
response to top-1 = 1.000 was to go and find out why — and the answer was that the
feature was the label. The honest output of RQ2 is a documented negative result and a
corrected experiment to run, not a claim about distributed tracing.
