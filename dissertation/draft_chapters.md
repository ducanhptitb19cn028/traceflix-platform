# Draft Chapters — Literature Review & Methodology

**Dissertation:** *Does Observability Matter? An Empirical Study of Real-Time Anomaly Detection in Cloud-Native Systems*
**Author:** Ngoc Duc Anh Nguyen (c7621164) · **Supervisor:** Satish Kumar
**Submission type:** Single formative draft for supervisor feedback

> **Note on scope.** These chapters are written to the scope agreed in the
> Dissertation Proposal (April 2026): research questions RQ1–RQ3 and the
> six-service testbed. Where the implementation has since evolved, this is
> flagged in clearly marked **Implementation evolution** call-outs rather than
> silently rewriting the proposed scope, so that the proposed design and its
> realisation can both be assessed.

---

# Chapter 2 — Literature Review

## 2.1 Introduction

This chapter critically reviews the body of work at the intersection of three
fields: observability in cloud-native systems, machine-learning-based anomaly
detection, and root cause analysis (RCA). The review is organised thematically
rather than chronologically. Section 2.2 establishes what observability is and
how it is operationalised through the MELT data model. Section 2.3 surveys the
spectrum of anomaly-detection techniques, from classical machine learning to
deep and graph-based architectures, and evaluates them against the requirements
of cloud-native environments. Section 2.4 examines RCA as the downstream task
that anomaly detection serves, with particular attention to multimodal
approaches. Section 2.5 considers the persistent divide between synthetic
benchmark evaluation and real-world operational data. Section 2.6 synthesises
these strands into the specific research gap this dissertation addresses: the
absence of any controlled study isolating *observability completeness* as an
independent variable in detection effectiveness.

The reviewed literature is drawn predominantly from peer-reviewed venues in
software engineering, services computing, and communications systems published
between 2018 and 2026, including two recent systematic studies (Kosińska et al.,
2023; Hrusto et al., 2026) that provide the field's current cartography.

## 2.2 Observability in Cloud-Native Systems

The concept of observability originates in control theory, where a system is
*observable* if its internal state can be reconstructed in finite time from its
external outputs alone (Kosińska et al., 2023). Transposed to distributed
software, this framing is instructive: a cloud-native application's internal
state — which service is saturated, which request path is failing — must be
inferred from emitted telemetry rather than observed directly, because the
system is too large, too dynamic, and too ephemeral to inspect by hand.

Kosińska et al. (2023), in a systematic mapping study of 56 primary studies,
establish that cloud-native observability is operationalised through three
principal domains: monitoring (metrics), logging, and distributed tracing.
Critically, their analysis reveals a *research imbalance*: monitoring receives
disproportionate scholarly attention relative to logging and tracing, despite
the latter two being essential for reconstructing behaviour in distributed
request flows. This imbalance is significant for the present study, because it
foreshadows a corresponding *evaluation* imbalance — if most techniques are
built and tested on metrics alone, the marginal value of logs and traces remains
empirically uncharacterised.

The literature converges on a four-layer observability architecture: (i)
telemetry sources (instrumented applications and runtimes), (ii) collectors
(notably OpenTelemetry, now the de facto vendor-neutral instrumentation
standard), (iii) backends (storage and query engines such as Prometheus, Loki,
and Tempo), and (iv) analysis and visualisation tools (Kosińska et al., 2023).
Collectively the telemetry signals are described by the MELT model — Metrics,
Events, Logs, Traces — which frames the configuration axis used throughout this
dissertation.

Kosińska et al. (2023) also catalogue the benefits and costs of observability.
On the benefit side: visibility, improved alerting, support for self-healing
automation, and — most relevant here — the provision of structured data suitable
for machine-learning analysis. On the cost side, three tensions recur across the
literature and bear directly on this study's motivation. First, **integration
difficulty**: metrics, logs, and traces are emitted by separate subsystems with
heterogeneous schemas, making correlation non-trivial. Second, **data-engineering
load**: the volume, velocity, and variety of telemetry impose substantial
storage and processing demands. Third, and most fundamental, the **observability–
performance tension**: active instrumentation imposes runtime overhead on the
observed system, so deeper observability is not free. This last point is the
economic premise of the entire dissertation — if richer telemetry carries a real
cost, then practitioners need evidence on its detection *benefit* in order to
make rational instrumentation decisions.

## 2.3 Anomaly Detection Techniques for Cloud-Native Systems

### 2.3.1 A requirements lens

Raeiszadeh, Estrada-Solano and Glitho (2026) provide the most current taxonomy
of ML-based anomaly detection for cloud-native architectures and, valuably,
frame it against six requirements: adaptability to dynamic topologies,
distributed operation, interpretability, scalability with high-velocity
telemetry, real-time detection latency, and cross-layer telemetry integration.
Their central finding is that existing approaches *systematically* fail on
adaptability, distributed operation, and interpretability. This requirements lens
is adopted in the present review as an evaluative yardstick, because it exposes
that strong benchmark accuracy and operational fitness are distinct properties —
a distinction that much of the primary literature elides.

### 2.3.2 Classical machine learning

Traditional algorithms — Support Vector Machines, Isolation Forest, and Random
Forest — remain competitive for metric-based detection. Lomio et al. (2022)
train ML models on 168 runtime metrics from Kafka and Zookeeper, reporting AUC
above 95% for performance anomalies with training times of 8–17 minutes. Their
result is a useful baseline but also illustrates the field's characteristic
limitations: the evaluation is *single-modality* (metrics only) and *batch*
(a model trained once on a static snapshot). Neither property survives contact
with a streaming, multimodal, non-stationary production environment, a point
returned to in Section 2.6.

### 2.3.3 Deep and temporal models

Deep learning has attracted interest for its capacity to model temporal and
spatial structure. Dkmak et al. (2025) introduce the *Night's Watch* algorithm,
a Variational-Autoencoder architecture integrating multi-source data with
temporal features, reporting precision up to 92% in microservice anomaly
detection. Recurrent architectures (LSTM, GRU) capture temporal dependencies in
metric streams, while Graph Neural Networks encode service-topology relations.
Pedroso et al. (2025) combine LLM-based log analysis with Bayesian networks for
probabilistic root cause inference, demonstrating that large language models can
extract structure from heterogeneous event data.

A critical observation across this sub-field is the *accuracy–interpretability–
cost* trilemma. Deep models report strong precision but are opaque (violating the
interpretability requirement of Raeiszadeh et al., 2026) and expensive to train,
and frequently require the very multimodal data whose marginal value has not been
isolated. The literature thus offers increasingly sophisticated *models* while
leaving the prior question — how much *signal* they actually need — unanswered.

### 2.3.4 Observability-integrated, proactive detection

Mart et al. (2020) address anomaly detection in Kubernetes clusters using
Prometheus metrics, observing that most monitoring systems remain *reactive*,
depending on human intervention and triggering only once defects are imminent.
They propose time-series forecasting on Prometheus metrics for earlier
detection. Their contribution is conceptual as much as technical: it reframes
detection as a proactive, observability-integrated capability rather than a
threshold alarm — a framing this dissertation inherits.

## 2.4 Root Cause Analysis Through Observability Data

Anomaly detection is rarely an end in itself; it serves the downstream task of
RCA, whose effectiveness is tightly coupled to observability data quality.
Han et al. (2024) propose **HolisticRCA**, which formalises RCA along three
dimensions: resource-entity localisation (*which* service, pod, or node failed),
observability-feature identification (*which* metric, log, or trace feature
signals the fault), and fault-type classification (*what kind* of failure). The
framework uses a Graph Attention Network to map heterogeneous trace, metric, and
log features into a shared vector space.

HolisticRCA's most consequential finding for the present work is that *single-
modal RCA is internally inconsistent*: a metric-based localiser may implicate one
entity while a log-based classifier indicates a different fault type. Jointly
modelling all three modalities resolves this inconsistency and yields
state-of-the-art results on public datasets. This is the strongest existing
evidence that modalities are *complementary* rather than redundant — but it is
demonstrated through a single fused architecture, not through a controlled
ablation of which modalities contribute what. The marginal contribution of, in
particular, *traces* therefore remains entangled with the model design.

Complementary approaches reinforce the value of dependency structure. Wang et al.
(2018) construct Bayesian networks from performance metrics (CloudRanger),
showing that service-dependency graphs derived from observability data improve
fault localisation. Chen et al. (2025) extend multi-source detection to
end-to-end service-function chains (cSFCAD), integrating data-plane and
control-plane signals across virtualised network functions. Together these works
establish that *topology* and *multi-source fusion* improve RCA — yet none varies
observability completeness as a controlled factor.

## 2.5 Monitoring Data and Real-World Evaluation

Hrusto et al. (2026) provide the field's most recent systematic mapping (104
papers), focused specifically on anomaly detection evaluated with *real-world*
monitoring data. Their central argument is methodological: synthetic datasets do
not adequately represent the complexity of operational cloud environments, and
results obtained on them may not transfer. They taxonomise monitoring data by
structure (time-series, unstructured text, semi-structured logs), type (metrics,
logs, traces, events), and origin (application, infrastructure, platform),
mapping each to suitable preprocessing and detection techniques.

Islam et al. (2021) corroborate this from industrial practice, reporting on
anomaly detection at IBM Cloud scale and finding threshold-based monitoring
inadequate for the heterogeneity and scale of real environments. Their
experience underscores the gap this dissertation targets: individual techniques
perform well on *isolated* datasets, but there is no systematic evidence on how
the *configuration and completeness of the observability pipeline itself* shapes
detection outcomes.

> **Critical tension.** Sections 2.3–2.5 expose a methodological double bind.
> Hrusto et al. (2026) argue persuasively that synthetic data limits external
> validity, yet *controlled* manipulation of observability completeness is only
> cleanly achievable when the data-generating process is itself controlled — i.e.
> in a testbed with deliberate fault injection. This dissertation resolves the
> tension by using a production-representative testbed (real OpenTelemetry
> instrumentation, real Prometheus/Loki/Tempo backends) under controlled fault
> injection, rather than either a purely synthetic benchmark or uncontrolled
> production logs.

## 2.6 Synthesis and Identified Research Gap

Three convergent gaps emerge from the reviewed literature.

**Gap 1 — Observability completeness is never the controlled variable.** The
majority of techniques are evaluated on a single modality (Lomio et al., 2022),
while the strongest multimodal evidence (HolisticRCA; Han et al., 2024) varies
the *model* rather than the *signal set*. No study holds the model fixed and
systematically varies observability completeness (metrics-only → metrics+logs →
+traces → full MELT) to measure the marginal detection value of each pillar.

**Gap 2 — The synthetic-versus-operational divide.** Few studies employ
production-representative telemetry under controlled conditions; evaluation is
typically either synthetic-and-controlled or operational-and-uncontrolled, rarely
both (Hrusto et al., 2026; Islam et al., 2021).

**Gap 3 — No practical guidance on minimum viable observability.** Practitioners
face a real instrumentation cost (Section 2.2) with no evidence base for the
detection benefit of each additional pillar, leaving instrumentation investment
decisions unsupported.

This dissertation addresses Gap 1 directly and Gaps 2–3 as consequences, through
a controlled experiment that fixes the ML pipeline and varies observability
completeness across four configurations (C1–C4), on a production-representative,
fault-injected testbed. The research questions follow:

- **RQ1** — How does the completeness of observability data (single-modal versus
  multimodal MELT) affect the accuracy and timeliness of ML-based anomaly
  detection?
- **RQ2** — Which ML algorithms and architectures prove most effective for
  anomaly classification on multimodal observability data?
- **RQ3** — To what extent does distributed trace data improve root-cause
  localisation relative to metrics-and-logs-only approaches?

> **Implementation evolution (Ch. 2).** During implementation, a fourth question
> emerged from the literature's *batch*-evaluation limitation (Section 2.3.2):
> whether detection must be **online** (continuously self-adapting) rather than a
> frozen batch model, given that production telemetry is non-stationary. This
> extends Gap 1 along a temporal axis (the *learning paradigm* as a variable
> alongside the *signal set*) and is operationalised as an additional study
> (RQ4) in the implemented system. It is noted here for completeness; the core
> contribution of the dissertation remains RQ1–RQ3 as proposed.

---

# Chapter 3 — Research Methodology

## 3.1 Research Philosophy and Approach

This research adopts a **positivist** philosophy with a **deductive** approach.
The relationship between observability completeness and detection effectiveness
is expressed as testable hypotheses and evaluated through controlled
experimentation, consistent with the epistemology of empirical software
engineering. The methodology is **quantitative**: detection accuracy, false-
positive rate, root-cause localisation precision, and detection latency are
measured across observability configurations and compared statistically.

The choice is justified by the research questions, which are causal and
comparative ("does completeness *affect* accuracy?"). A positivist–deductive,
experimental design isolates the independent variable (observability
completeness) while holding confounds (model, fault scenarios, traffic, random
seed) constant — the only design that licenses causal attribution of any
performance difference to the observability configuration itself.

## 3.2 Research Design Overview

The study is a **controlled, repeated-measures experiment**. The independent
variable is observability completeness, operationalised as four ordered
configurations C1–C4 (Section 3.5). The dependent variables are the evaluation
metrics of Section 3.7. Control variables — the ML pipeline, the fault-injection
scenarios, the load profile, and the random seed — are held fixed across
configurations so that *identical episodes* are observed at differing levels of
telemetry completeness. This within-subjects design is deliberate: because every
configuration sees the same underlying faults, performance differences cannot be
attributed to sampling variation between scenario sets.

The overall flow is: (i) deploy the instrumented testbed (3.3); (ii) inject
labelled faults under realistic load (3.4); (iii) collect MELT telemetry and
derive the four configuration views (3.5); (iv) train and evaluate the ML
pipeline per configuration (3.6); (v) compute and statistically compare metrics
(3.7).

## 3.3 Experimental Testbed Design

The platform is based on **TraceFlix**, a Kubernetes microservices application
representing a realistic cloud-native system. As proposed, the testbed comprises
multiple interconnected services (gateway, authentication, catalogue, streaming,
billing, recommendation) deployed on Kubernetes with full observability
instrumentation:

- **Prometheus** — metrics (CPU, memory, network, latency, error rates, and
  custom application metrics);
- **Loki** — log aggregation (structured application logs, container logs,
  Kubernetes event logs);
- **Tempo** — distributed tracing (OpenTelemetry-instrumented service-to-service
  call traces);
- **VictoriaMetrics** — long-range time-series storage for historical trend
  analysis and downsampled metrics;
- **Redis Streams** — message queue for real-time telemetry streaming from
  TraceFlix to the detection pipeline.

Instrumentation uses the **OpenTelemetry** Java agent, providing vendor-neutral,
auto-instrumented metrics, logs, and traces without modifying service code. This
choice maximises external validity: the telemetry schema matches what a real
OpenTelemetry deployment emits, addressing the synthetic-data concern of Hrusto
et al. (2026).

> **Implementation evolution (§3.3).** The realised testbed uses **three**
> instrumented services — `movie-service`, `actor-service`, and `review-service`
> — rather than the six listed in the proposal. The topology is preserved and
> remains representative: `movie-service` issues N sequential calls to
> `actor-service` plus a call to `review-service`, giving a genuine multi-hop
> request path with caller/callee dependencies for RCA propagation. The
> reduction was made to keep fault attribution unambiguous and the chaos
> experiments tractable within the project timeline; it does not affect the C1–C4
> manipulation, which is orthogonal to service count. One consequence is noted in
> §3.7: with three services, Top-2 RCA accuracy saturates, so **Top-1 becomes the
> discriminating localisation metric**.

## 3.4 Fault Injection and Ground-Truth Labelling

Ground-truth anomaly labels are generated through **controlled fault injection**,
following the methodology of Pedroso et al. (2025). Faults are injected into the
running pods with precise start/stop timestamps, which are recorded as the
labels against which detector output is scored. The targeted fault categories
are: memory leaks, CPU saturation, latency spikes, error bursts, OOMKilled
events, CrashLoopBackOff, connection-pool exhaustion, and network partitions —
spanning resource-exhaustion, performance-degradation, and availability failure
modes.

Realistic traffic is generated continuously by a load generator so that
episodes carry signal even under normal operation, and each fault rides on a live
request stream rather than an idle system. Each experimental **episode** is a
labelled window-sequence: a service is selected as the fault origin, the fault is
applied, and dependent services on the call path exhibit secondary effects
(e.g. induced latency), reproducing realistic fault *propagation* for the RCA
task.

> **Implementation evolution (§3.4).** **Chaos Mesh** was selected as the
> fault-injection engine (over the proposed Chaos Mesh / LitmusChaos
> alternatives) for its Kubernetes-native CRD model and fine-grained timing
> control. To support the OOMKilled/CrashLoopBackOff event signals (the **E** in
> MELT used by C4), container resource limits are patched so that memory-leak
> faults escalate to genuine OOMKills, producing real Kubernetes events rather
> than simulated ones.

## 3.5 Experimental Design — Observability Configurations

The core experiment varies the observability input to the *same* pipeline across
four ordered configurations:

| Configuration | Signals | Data sources | Represents |
|---|---|---|---|
| **C1: Metrics-Only** | M | Prometheus + VictoriaMetrics | Basic infrastructure monitoring |
| **C2: Metrics + Logs** | M + L | Prometheus + Loki | Intermediate observability maturity |
| **C3: Metrics + Logs + Traces** | M + L + T | Prometheus + Loki + Tempo | Full three-pillar observability |
| **C4: Full MELT** | M + E + L + T | All sources + K8s events + VictoriaMetrics history | Advanced observability with historical context |

For each configuration the identical ML pipeline is trained and evaluated on
identical fault-injection episodes, enabling direct attribution of any
performance difference to observability completeness. Feature engineering is
**configuration-aware**: only the feature families permitted by the active
configuration are assembled, so an identical telemetry window yields different
feature vectors per configuration. This is the mechanism that isolates *signal
availability* as the sole independent variable for RQ1. The configurations are
deliberately *nested* (each is a superset of the previous), so that the marginal
contribution of each added pillar — logs (C1→C2), traces (C2→C3), and
events+history (C3→C4) — is measurable as an incremental difference.

## 3.6 ML Pipeline Design

The detection pipeline implements and compares multiple approaches on the
features extracted from each configuration:

- **Baseline classifiers** — Random Forest and Gradient Boosting (XGBoost) on
  engineered features. These address RQ1 (held fixed across C1–C4) and
  contribute to RQ2.
- **Temporal models** — LSTM/GRU networks for time-series detection on metric
  streams, capturing temporal dependencies (RQ2).
- **Multimodal fusion** — feature concatenation and attention-based fusion of
  metric, log, and trace embeddings, drawing on the HolisticRCA building-blocks
  strategy (Han et al., 2024), evaluated under C4 for RQ2.

For RQ3, root-cause localisation is performed by ranking candidate fault entities
(services), comparing a metrics-and-logs-only localiser (C2-style features)
against one that additionally consumes trace-derived signals (originating
error-spans), thereby quantifying the marginal RCA value of distributed tracing.

To control for confounds, every model is trained and evaluated under a fixed
random seed, an identical train/test protocol, and the same feature pre-
processing, so that cross-configuration differences reflect signal availability
rather than stochastic training variation.

> **Implementation evolution (§3.6).** An additional **online (streaming)**
> pipeline was implemented to answer RQ4 (§2.6 note): a prequential
> test-then-train detector with adaptive normalisation, incremental learning,
> dynamic hyper-parameter selection, and drift-triggered adaptation, evaluated
> against frozen-batch and periodically-retrained baselines on a *non-stationary*
> stream. This extends the RQ2 model comparison along the *learning-paradigm*
> axis. It is documented separately (`aiops/docs/ONLINE_PIPELINE.md`) and does not
> alter the RQ1–RQ3 design above.

## 3.7 Evaluation Metrics

Detection performance is evaluated with **precision**, **recall**, **F1-score**,
and **AUC-ROC** for anomaly classification. Root-cause localisation is measured
with **Top-k accuracy** (whether the true root-cause entity appears in the top-k
ranked predictions). **Detection latency** (time from fault injection to
detection) and the **false-positive rate** under normal operation are also
reported. All metrics are computed **per configuration** to enable direct C1–C4
comparison, and differences are assessed for statistical significance.

F1-score is treated as the headline classification metric because anomaly data
are class-imbalanced (normal windows dominate), under which accuracy is
misleading — a trivial always-normal predictor scores highly on accuracy but has
zero recall. AUC-ROC complements F1 by characterising the precision–recall trade-
off across thresholds.

> **Implementation evolution (§3.7).** Because the realised testbed has three
> services (§3.3), Top-2 localisation covers two-thirds of the mesh and
> saturates near 1.0; consequently **Top-1 accuracy is reported as the
> discriminating RCA metric**, which is the more demanding and informative
> measure in any case.

## 3.8 Threats to Validity

**Internal validity.** Held-constant control variables (model, seed, scenarios,
load) and the nested within-subjects design mean cross-configuration differences
are attributable to observability completeness. Residual risk: fault-injection
timing jitter could blur labels; this is mitigated by recording exact CRD
start/stop timestamps.

**External validity.** A testbed cannot reproduce the full heterogeneity of
production (Hrusto et al., 2026). This is mitigated by using real OpenTelemetry
instrumentation and unmodified backends so the telemetry schema is
production-representative, and by injecting a fault taxonomy drawn from documented
real-world failure modes. The reduced service count (§3.3) limits topological
generalisation, which is acknowledged as a boundary condition.

**Construct validity.** "Detection effectiveness" is multidimensional; using F1,
AUC-ROC, latency, and false-positive rate together avoids over-reliance on any
single construct.

**Conclusion validity.** Statistical significance testing across configurations,
with a fixed seed for reproducibility, guards against over-interpreting noise.

## 3.9 Ethical Considerations

The research involves no human participants, personal data, or sensitive
information. All experiments run on a self-contained testbed generating synthetic
operational data, with fault injection confined to an isolated environment having
no impact on production systems. No ethical approval is required; the work adheres
to Leeds Beckett University's Research Ethics guidelines. All tools are
open-source, and produced datasets and pipeline code will be released for
reproducibility in line with open-science principles.

---

## References

Chen, X., Kou, J., Li, H., Zhang, Y., Ma, J., Li, C. and Tu, B. (2025) 'End-to-end anomaly detection of service function chain through multi-source data in cloud-native systems', *Computers & Security*, 155, p. 104461. Available at: https://doi.org/10.1016/j.cose.2025.104461

Dkmak, G., Can, B., Sevinc, O., Egeli, C.B., Baday, F. and Cetintav, B. (2025) 'AI-Driven Anomaly Detection in Cloud-Native Microservices: The Night's Watch Algorithm', *Applied Sciences*, 15(23), p. 12762. Available at: https://doi.org/10.3390/app152312762

Han, Y., Du, Q., Huang, Y., Li, P., Shi, X., Wu, J., Fang, P., Tian, F. and He, C. (2024) 'Holistic Root Cause Analysis for Failures in Cloud-Native Systems Through Observability Data', *IEEE Transactions on Services Computing*, 17(6), pp. 3789–3802. Available at: https://doi.org/10.1109/TSC.2024.3476599

Hrusto, A., Ali, N.B., Engström, E. and Wang, Y. (2026) 'Monitoring Data for Anomaly Detection in Cloud-Based Systems: A Systematic Mapping Study', *ACM Transactions on Software Engineering and Methodology*, 35(4), Article 91. Available at: https://doi.org/10.1145/3744556

Islam, M.S., Pourmajidi, W., Zhang, L., Steinbacher, J., Erwin, T. and Miranskyy, A. (2021) 'Anomaly Detection in a Large-scale Cloud Platform', in *2021 IEEE/ACM 43rd International Conference on Software Engineering: Software Engineering in Practice (ICSE-SEIP)*. Madrid: IEEE, pp. 150–159. Available at: https://doi.org/10.1109/ICSE-SEIP52600.2021.00024

Kosińska, J., Baliś, B., Konieczny, M., Malawski, M. and Zieliński, S. (2023) 'Toward the Observability of Cloud-Native Applications: The Overview of the State-of-the-Art', *IEEE Access*, 11, pp. 73036–73058. Available at: https://doi.org/10.1109/ACCESS.2023.3281860

Lomio, F., Moreschini, S., Li, X. and Lenarduzzi, V. (2022) 'Anomaly Detection in Cloud-Native Systems', in *2022 48th Euromicro Conference on Software Engineering and Advanced Applications (SEAA)*. IEEE, pp. 100–103. Available at: https://doi.org/10.1109/SEAA56994.2022.00022

Mart, O., Negru, C., Pop, F. and Castiglione, A. (2020) 'Observability in Kubernetes Cluster: Automatic Anomalies Detection using Prometheus', in *2020 IEEE 22nd International Conference on High Performance Computing and Communications (HPCC/SmartCity/DSS)*. IEEE, pp. 565–570. Available at: https://doi.org/10.1109/HPCC-SmartCity-DSS50907.2020.00071

Pedroso, D.F., Almeida, L., Pulcinelli, L.E.G., Aisawa, W.A.A., Dutra, I. and Bruschi, S.M. (2025) 'Anomaly Detection and Root Cause Analysis in Cloud-Native Environments Using Large Language Models and Bayesian Networks', *IEEE Access*, 13, pp. 77550–77571. Available at: https://doi.org/10.1109/ACCESS.2025.3556193

Raeiszadeh, M., Estrada-Solano, F. and Glitho, R.H. (2026) 'Anomalies Detection in Cloud-Native Architectures: Background, State-of-the-Art, and Research Directions', *IEEE Communications Magazine* (Early Access). Available at: https://users.encs.concordia.ca/~glitho/research.htm

Wang, P., Xu, J., Ma, M., Lin, W., Pan, D., Wang, Y. and Chen, P. (2018) 'CloudRanger: Root Cause Identification for Cloud Native Systems', in *2018 18th IEEE/ACM International Symposium on Cluster, Cloud and Grid Computing (CCGrid)*. IEEE, pp. 492–502. Available at: https://doi.org/10.1109/CCGRID.2018.00076
