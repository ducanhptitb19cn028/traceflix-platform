# Review list — new verified references (2023–2026) for fortifying the paper

All entries verified against DBLP (authoritative authors/venue/year/DOI). None fabricated.
Source bib: `verified.bib`. Existing paper refs: 16 → **with these 19, total ≈ 35**.

## Observability + pipeline/cost (5)
| key | cite | supports |
|--|--|--|
| faseeha2025observability | Faseeha et al., *Observability in Microservices* (survey), IEEE Access 13, 2025 | recent observability survey (§2.1) |
| hausenblas2023roi | Hausenblas, *Return on Investment Driven Observability*, arXiv 2303.13402, 2023 | observability is a cost (§2.1–2.2) |
| ashok2024traceweaver | Ashok et al., *TraceWeaver*, ACM SIGCOMM, 2024 | distributed-tracing mechanics (§2.2) |
| huang2025mint | Huang et al., *Mint: Cost-Efficient Tracing*, ASPLOS, 2025 | tracing cost / all-vs-sampled (§2.2) |
| wu2025tracesampling | Wu et al., *Trace Sampling 2.0*, arXiv 2509.13852, 2025 | sampling shapes trace features (§2.2) |

## Anomaly detection — modalities (3)
| key | cite | supports |
|--|--|--|
| akmeemana2025galmad | Akmeemana et al., *GAL-MAD* (graph attention), arXiv 2504.00058, 2025 | deep/graph AD; interpretability (§2.3) |
| guan2024logllm | Guan et al., *LogLLM* (LLM log AD), arXiv 2411.08561, 2024 | log-based AD with LLMs (§2.3) |
| wette2024omlad | Wette & Heinrichs, *OML-AD* (online ML AD), arXiv 2409.09742, 2024 | online beats batch under drift (§2.5, RQ4) |

## Root-cause analysis (5)
| key | cite | supports |
|--|--|--|
| chen2024rca | Chen et al., *Automatic RCA via LLMs for Cloud Incidents*, EuroSys, 2024 | LLM-based RCA (§2.4) |
| pham2024rca | Pham et al., *RCA via Causal Inference: How Far Are We?*, ASE, 2024 | causal RCA; 21-method benchmark (§2.4) |
| yao2024chainofevent | Yao et al., *Chain-of-Event*, FSE Companion, 2024 | interpretable event-causal-graph RCA (§2.4) |
| zhang2025thinkfl | Zhang et al., *ThinkFL*, arXiv 2504.18776, 2025 | recent failure localization (§2.4) |
| wang2024rcasurvey | Wang & Qi, *Comprehensive Survey on RCA in (Micro)Services*, arXiv 2408.00803, 2024 | RCA landscape (§2.4) |

## AIOps (1)
| key | cite | supports |
|--|--|--|
| zhang2024aiops | Zhang et al., *A Survey of AIOps for Failure Management in the Era of LLMs*, arXiv 2406.11213, 2024 | AIOps framing; adaptability gap (§2.3, §2.5) |

## Concept drift + online/continual learning + model decay (4)
| key | cite | supports |
|--|--|--|
| arora2024drift | Arora et al., *Systematic review of concept-drift detection & adaptation*, WIREs DMKD 14(4), 2024 | drift types/detection (§2.5, §3.2) |
| lukats2025drift | Lukats et al., *Benchmark & survey of unsupervised drift detectors*, Int. J. Data Sci. Anal. 19, 2025 | drift detection methods (§2.5) |
| li2023autoencoder | Li et al., *Autoencoder AD in streaming data w/ incremental learning + drift adaptation*, IJCNN, 2023 | incremental learning under drift (§2.5) |
| leest2025mlmonitoring | Leest et al., *Monitoring & Observability of ML Systems: Practices and Gaps*, arXiv 2510.24142, 2025 | model decay / MLOps monitoring (§2.5, §6.3) |

## Evaluation infrastructure (1)
| key | cite | supports |
|--|--|--|
| owotogbe2026chaos | Owotogbe et al., *Chaos Engineering: A Multi-Vocal Literature Review*, ACM Comput. Surv. 58(7), 2026 | chaos/fault injection for evaluation (§4.3) |

---
## Still to gather (next rounds, to push toward ~60 total)
multimodal MELT-fusion AD (UACAD/IEEE TSC); metric/MTS-AD survey (MDPI Sensors 2025);
log-AD survey; datasets/benchmarks (AnoMod; large-scale cloud benchmark); class-imbalance/
evaluation metrics for AD; streaming-ensemble & Hoeffding/ADWIN method refs; **industry/standards**
(OpenTelemetry spec, CNCF survey, DORA deployment-frequency) for the practice claims.
