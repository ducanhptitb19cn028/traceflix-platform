# KairosBench: the interactive context

This application is one of four in the [KairosBench](../kairosbench) suite. It
occupies the **interactive** time-sensitivity context and carries AI workload
class **A1** (classical ML on the critical path). This file covers what a
measurement campaign here produces, how to run one, and what is known to be
wrong with the result if you read it carelessly. The shared protocol lives in
the harness, in `kairosbench/docs/campaign.md`; nothing here repeats it.

Two experiments run against this application, each documented in full:

- [experiment 3 — the interactive detection matrix](../kairosbench/docs/experiment-interactive-detection-matrix.md):
  the control row group, and the only one injected with Chaos Mesh.
- [experiment 5 — request-class characterisation](../kairosbench/docs/experiment-request-class-characterisation.md):
  topology and telemetry volume for the browse class.

    $env:TF_LIVE = "1"                        # PowerShell; the gate is enforced
    python scripts/kb_campaign.py --check     # preconditions
    python scripts/kb_campaign.py             # the interactive matrix, ~2 h
    python scripts/kb_campaign.py --analyse   # cells from the runs on disk

## What this application is for, in the suite

It is the **control**. Interactive is the incumbent context — the one every
existing microservice benchmark suite occupies, and the one latency-based
tooling was designed for. The suite's claim is that indicator families which
work here fail in other contexts. That claim is worth nothing unless they
demonstrably work here, against the same taxonomy, on the same schedule.

It is also the only application in the suite that has the topology the fault
taxonomy assumes: nine services with real fan-out, no shared datastore on the
measured path, and every fault applicable to a single service. In the
regulatory application the mechanism forces a different target per fault; here
it does not, so a difference between rows is attributable to the fault alone.

## The live-mode gate

**Every number previously reported from this repository came from the `_synth`
telemetry simulator, not from the running cluster.** The harness refuses to
record a run unless `TF_LIVE=1` is set, and the campaign script refuses to
start without it. Do not remove the gate. It is the single cheapest protection
against publishing generated numbers as measured ones, and this project has
already been bitten once by exactly that failure.

## What a campaign here measures

`interactive-detection-matrix` applies the common fault taxonomy through
**Chaos Mesh**, which is the mechanism the paper declares — this is the one
application in the suite where no substitution is needed. Five configurations,
three repetitions, randomised order.

| Fault | Target | Chaos Mesh resource |
|---|---|---|
| F1 latency injection | movie-service | NetworkChaos `delay`, 100 ms + 50 ms jitter |
| F2 error injection | movie-service | HTTPChaos `abort` on every request (the 1.0 level) |
| F3 resource exhaustion | movie-service | StressChaos, 2 CPU workers at 95 % |
| F4 network partition | gateway-service ↔ movie-service | NetworkChaos `partition`, both directions |
| F5 dependency stall | movie-service | NetworkChaos `loss` 100 % on its egress |

`movie-service` is the target throughout because it sits one hop below the
entry point and itself calls actor-service and review-service, so a fault there
is neither at the edge nor at a leaf.

**F5 is not a partition.** Total loss on the target's egress means requests
still arrive and are still processed, and every reply is dropped: nothing is
refused, no connection is closed, and the caller waits on a dependency that is
working and silent. An earlier version of this fault used Chaos Mesh's
`direction: from` with the caller as the target; Chaos Mesh reported it as
injected and it had no observable effect on any request. It is recorded in the
fault mapping because "the mechanism reports success" and "the fault reached
the system" are different claims, and only the second licenses reading a cell.

## What it found

Full detail, provenance and deviations: `kairosbench/docs/campaign-log.md`,
run 005. Three repetitions per configuration, all injections verified.

| Fault | Latency | Error | client failures | p99 during injection |
|---|---|---|---|---|
| F1 delay | **yes, 15 s** | no | 0 % | 0.70 s |
| F2 abort | no | **yes, 15 s** | 99 % | 0.04 s |
| F3 CPU | no | no | 0 % | 0.05 s |
| F4 partition | no | no | **97 %** | 0.04 s |
| F5 stall | **yes, 67 s** | **yes, 67 s** | 97 % | 6.7 s |

**The incumbent context misses two of five faults, and one of them is
catastrophic.** Under F4, 97 % of client requests fail and neither
objective-bearing family breaches; latency reads 1.4 standard deviations
*better* than baseline. A histogram records a request when it finishes, a
partition makes requests hang rather than fail, and the percentile is therefore
computed over the minority that still complete. The only indicator that moves
is throughput, which has no objective. In all three repetitions latency did
breach — during *recovery*, at the histogram's top bucket, as the backlog
drained after the fault was removed.

F2 and F5 are worth reading together: both fail ~98 % of client requests, but
an aborted request is a fast request (latency reads better than baseline and
only the error family fires) while a dropped reply is a slow one (both families
fire, at 6.7 s). The same fault class is detected in ERP's transactional
context and missed here, and the difference is this gateway's lack of a
downstream timeout, not the context.

## Two corrections this campaign forced

**The descriptor's request classes were wrong.** `/api/catalog/movies`,
`/api/search` and `/api/recommendations` all return 404 at the gateway: they
were written from the service-level APIs rather than from the routes the
gateway exposes. As deployed the gateway exposes exactly one route,
`GET /api/browse?userId=N`, and a trace of it fans out across all nine services
**including recommendation-service**. There is therefore no entry point that
avoids the ML tier, and the class cannot be labelled A0 — the A0/A1 separation
the suite needs for the topology table is not available at the gateway until a
non-recommending route is exposed.

**The telemetry could not resolve a time-to-detect.** The OpenTelemetry Java
agent exports metrics every 60 s by default, and every indicator in the
interactive profile is a `rate(...[1m])` on top of that, so an unmodified
deployment cannot resolve anything faster than about two minutes and a matrix
cell would report the export interval rather than the fault. The campaign
script sets the gateway's `OTEL_METRIC_EXPORT_INTERVAL` to 5 s for the duration
and restores it afterwards. It is applied to every phase of every run, so it
cancels in the within-run comparison, and it is recorded in provenance either
way. Run with `--no-set-export-interval` to measure the deployment as it
normally stands, and expect coarse detection times.

## What the harness does not change

The two load generators deployed alongside the application are **left running**.
They offer a constant few requests per second to the same entry point in every
phase of every run, which is what makes a p99 over a one-minute window a
percentile rather than the maximum of a handful of samples. They are part of
the measured baseline. The harness adds its own two requests per five-second
tick on top, so that it has a client-side view — how many requests failed from
outside the system — independent of anything the system reports about itself.

## Reading the output

Two readings are specific to this application and easy to get wrong.

**`10 s` is a bound, not a measurement.** The OpenTelemetry histogram's largest
finite bucket is 10 seconds, so any percentile at or above it means "at least
10 s" and nothing more precise.

**A family can go absent rather than bad.** A histogram records a request when
it *finishes*. A fault that makes requests hang produces no completed request,
so the series empties and the percentile becomes undefined — the analysis
reports `no data`, which is not a non-detection. Where that happens, read the
throughput column and the client-side failure ratio in the diagnostics block
instead: they are what still moves. Note that `throughput` carries
`objective: null` in the profile, so it cannot breach and cannot fill a cell,
by declaration.

## Provenance

This deployment is applied to the cluster by `run.ps1` from `traceflix/*:1.0.0`
images built at an unrecorded commit, so the harness records the **image ID of
every workload measured** rather than a configuration digest. That pins the
bits; nothing pins them to a source revision until the repository is tagged and
the images are rebuilt from the tag. `apps/traceflix-platform.yaml` in the
harness still reads `commit: TBD-tag-the-repository-first`, and that is the
main provenance gap for this application.
