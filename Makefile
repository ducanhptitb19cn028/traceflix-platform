# ============================================================================
# TraceFlix Platform - whole-project automation
# ============================================================================
# Layers:
#   services/        9 Spring Boot microservices (Java 21, OTel-instrumented)
#   observability/   Tempo/Loki/Prometheus/Grafana stack (k8s manifest)
#   aiops/           experiments, ML, streaming backbone, LLM, webui, tests
#   deploy/          Docker Compose overlay (vm1 gpu/kafka, vm2 services, vm3 tel)
#   paper/           LaTeX paper (Docker TeX Live)
#   dissertation/    md -> docx
#
# Run `make help` for a grouped target list. Recipes use POSIX sh + a few CLI
# tools (python, mvn, docker, kubectl); on Windows run from Git Bash / WSL.
# Override knobs inline, e.g.  make experiments EPISODES=120 DRIFT_EPISODES=240
# ============================================================================

# ---- configuration ---------------------------------------------------------
# (no inline comments after values - they would leak trailing whitespace)
PY              ?= python
EPISODES        ?= 200          # offline RQ1/RQ4 (run_experiment) + RQ2
RQ2_SEEDS       ?= 42,43,44,45,46 # RQ2 localisation seeds (rq2_localisation)
RQ3_SEEDS       ?= 42,43,44,45,46 # RQ3 seed variance (baselines_and_seeds)
DRIFT_EPISODES  ?= 320          # RQ3 drift stream (online_vs_offline, cost)
STREAM_EPISODES ?= 20           # streaming backbone demo
LIVE_EPISODES   ?= 30           # live fault-injection episodes
CONFIGS         ?= C1,C2,C3,C4
SWEEP_CONFIGS   ?= C1,C4        # drift sweep: thinnest vs richest is the contrast
SEED            ?= 42
OUT             ?= data/results # relative to aiops/
LLM_OUT         ?= data/results_llm # 'llm' target: NEVER $(OUT), see the target
SWEEP_OUT       ?= data/results_drift_sweep     # control: drift-magnitude sweep
BASELINES_OUT   ?= data/results_baselines_scaled # control: streaming baselines
ABLATION_OUT    ?= data/results_ablation        # control: component ablation
LIVE_OUT        ?= data/results_live            # control: live replay
LIVE_LABELS     ?= data/labels_live.csv         # live replay: recorded campaign
COST_SEEDS_OUT  ?= data/results_cost_seeds      # cost-seeds: per-seed cost tables
NS              ?= on-demand-observability # k8s namespace
SVC             ?= catalog-service         # inject: target service
FAULT           ?= cpu_saturation          # inject: fault type
DUR             ?= 120                      # inject: duration (s)
OLLAMA_PORT     ?= 11434         # ollama-forward: host port (detector default)
# strip the trailing whitespace the aligned comments above introduce
EPISODES        := $(strip $(EPISODES))
RQ2_SEEDS       := $(strip $(RQ2_SEEDS))
RQ3_SEEDS       := $(strip $(RQ3_SEEDS))
DRIFT_EPISODES  := $(strip $(DRIFT_EPISODES))
STREAM_EPISODES := $(strip $(STREAM_EPISODES))
LIVE_EPISODES   := $(strip $(LIVE_EPISODES))
SWEEP_CONFIGS   := $(strip $(SWEEP_CONFIGS))
OUT             := $(strip $(OUT))
SWEEP_OUT       := $(strip $(SWEEP_OUT))
BASELINES_OUT   := $(strip $(BASELINES_OUT))
ABLATION_OUT    := $(strip $(ABLATION_OUT))
LIVE_OUT        := $(strip $(LIVE_OUT))
LIVE_LABELS     := $(strip $(LIVE_LABELS))
COST_SEEDS_OUT  := $(strip $(COST_SEEDS_OUT))
NS              := $(strip $(NS))
SVC             := $(strip $(SVC))
FAULT           := $(strip $(FAULT))
DUR             := $(strip $(DUR))
OLLAMA_PORT     := $(strip $(OLLAMA_PORT))

# Shell for .sh helper scripts. On Windows the `bash` first on PATH is normally
# C:\Windows\System32\bash.exe (the WSL launcher); WSL can't see the Windows
# JDK/Maven/JAVA_HOME this build uses, so bootstrap dies with "JAVA_HOME ... not
# defined correctly". Force Git Bash by full path. Override if Git lives
# elsewhere, e.g.  make bootstrap BASH_BIN=/path/to/bash
ifeq ($(OS),Windows_NT)
BASH_BIN := C:/Program Files/Git/bin/bash.exe
else
BASH_BIN := bash
endif

# Windows-native project runner (run.ps1). Uses PowerShell directly so it does
# NOT depend on make's bash/WSL shell resolution. Pass flags via RUN_ARGS, e.g.
#   make run RUN_ARGS="-SkipExperiments"
ifeq ($(OS),Windows_NT)
PWSH := powershell -NoProfile -ExecutionPolicy Bypass -File
else
PWSH := pwsh -NoProfile -File
endif
RUN_ARGS ?=

AIOPS    := aiops
SERVICES := services
RESULTS  := $(AIOPS)/$(OUT)
NEW_SVCS := catalog auth user search recommendation gateway
ALL_SVCS := movie actor review $(NEW_SVCS)

# paper compile (Docker TeX Live). Override PAPER_DIR on Windows if the mount
# path needs a Windows-style absolute path.
PAPER_DIR ?= $(CURDIR)/paper
PAPER_IEEE_DIR ?= $(CURDIR)/paper/paper_IEEE
TEXIMG    := texlive/texlive:latest

# Pick the LaTeX toolchain at parse time (shell-agnostic: works whether make's
# recipe shell is sh or cmd.exe). Prefer a local tectonic install; fall back to
# Docker TeX Live. Force Docker with `make paper USE_DOCKER=1`.
ifeq ($(USE_DOCKER),1)
HAS_TECTONIC := 0
else
HAS_TECTONIC := $(shell $(PY) -c "import shutil;print(1 if shutil.which('tectonic') else 0)")
endif

DC_VM1 := deploy/virtfusion/vm1-gpu
DC_VM2 := deploy/virtfusion/vm2-services
DC_VM3 := deploy/virtfusion/vm3-telemetry
DC_VM4 := deploy/virtfusion/vm4-gateway

.DEFAULT_GOAL := help
.PHONY: help all run run-platform run-experiments run-down aiops-up aiops-down setup setup-llm \
        experiments experiments-full repro quick rq124 rq2 rq3 cost plots figures \
        controls seeds sweep baselines ablation live-replay cost-seeds cost-seeds-agg \
        streaming llm lora \
        webui webui-build \
        ollama-up ollama-down ollama-logs ollama-forward \
        build-services compile-services images \
        test test-aiops test-services \
        deploy-up deploy-down mesh-up mesh-down telemetry-up telemetry-down \
        kafka-llm-up kafka-llm-down gateway-up gateway-down \
        bootstrap k8s-deploy k8s-delete chaos-install status \
        live live-episodes inject \
        paper paper-pages paper-clean \
        paper_IEEE paper_IEEE-pages paper_IEEE-clean dissertation \
        clean clean-results clean-all

# ---- help ------------------------------------------------------------------
help:
	@echo "TraceFlix - whole-project automation. Targets by area:"
	@echo ""
	@echo "  RUN (win)    run  run-platform  run-experiments  run-down   (RUN_ARGS=...)"
	@echo "  SETUP        setup  setup-llm"
	@echo "  EXPERIMENTS  experiments  repro  quick  rq124  rq2  rq3  cost  plots  figures"
	@echo "  RQ3 CONTROLS controls  seeds  sweep  baselines  ablation   (experiments-full = both)"
	@echo "               cost-seeds  cost-seeds-agg   (five-seed cost ranges; -agg re-reads only)"
	@echo "               live-replay   (needs TF_LIVE + a reachable Prometheus)"
	@echo "  STREAM/LLM   streaming  llm  lora"
	@echo "  WEBUI        webui  webui-build"
	@echo "  AIOPS (k8s)  aiops-up  aiops-down"
	@echo "  OLLAMA (k8s) ollama-up  ollama-down  ollama-logs  ollama-forward  (needs ~3Gi free)"
	@echo "  JAVA         build-services  compile-services  images  test-services"
	@echo "  TESTS        test  test-aiops  test-services"
	@echo "  COMPOSE      deploy-up/down  mesh-up/down  telemetry-up/down"
	@echo "               kafka-llm-up/down  gateway-up/down"
	@echo "  KUBERNETES   bootstrap  k8s-deploy  k8s-delete  chaos-install  status"
	@echo "  FAULTS/LIVE  live  live-episodes  inject  (SVC= FAULT= DUR=)"
	@echo "  PAPER/DOCS   paper  paper-pages  paper-clean  dissertation"
	@echo "  CLEAN        clean  clean-results  clean-all"
	@echo ""
	@echo "  Knobs: EPISODES=$(EPISODES) DRIFT_EPISODES=$(DRIFT_EPISODES) SEED=$(SEED) CONFIGS=$(CONFIGS)"

# build the core deliverables: Java services, offline results, paper
all: build-services experiments paper

# ---- run: one-command local k8s platform + experiments (run.ps1) -----------
# The whole project on the local docker-desktop cluster (on-demand-observability
# namespace) plus the offline experiments. Pass extra flags with RUN_ARGS.
run:
	$(PWSH) run.ps1 $(RUN_ARGS)

run-platform:
	$(PWSH) run.ps1 -SkipExperiments $(RUN_ARGS)

run-experiments:
	$(PWSH) run.ps1 -SkipDeploy $(RUN_ARGS)

run-down:
	$(PWSH) run.ps1 -Teardown

# ---- setup -----------------------------------------------------------------
setup:
	$(PY) -m pip install -r $(AIOPS)/requirements.txt

setup-llm:
	$(PY) -m pip install -r $(AIOPS)/llm/requirements-llm.txt

# ---- experiments (aiops, offline) -----------------------------------------
experiments: rq124 rq2 rq3 cost plots
	@echo ""
	@echo "[make] experiments complete -> $(RESULTS)/"

repro: setup experiments test

quick:
	$(MAKE) experiments EPISODES=60 DRIFT_EPISODES=120

rq124:
	cd $(AIOPS) && $(PY) -m ml.experiments.run_experiment --episodes $(EPISODES) --seed $(SEED) --out $(OUT)

# RQ2 (corrected): localisation on the propagating generator. The RQ2 rows emitted
# by rq124 above are the WITHDRAWN original, kept only so the defect is inspectable.
rq2:
	cd $(AIOPS) && $(PY) -m ml.experiments.rq2_localisation --episodes $(EPISODES) --seeds $(RQ2_SEEDS) --out $(OUT)

rq3:
	cd $(AIOPS) && $(PY) -m ml.experiments.online_vs_offline --episodes $(DRIFT_EPISODES) --configs $(CONFIGS) --out $(OUT)

cost:
	cd $(AIOPS) && $(PY) -m ml.experiments.cost_compare --episodes $(DRIFT_EPISODES) --configs $(CONFIGS) --out $(OUT)

plots:
	cd $(AIOPS) && $(PY) -m ml.eval.plots $(OUT)

figures:
	$(PY) paper/make_figures.py

# ---- RQ3 controls ----------------------------------------------------------
# The four experiments that bound how much of the RQ3 headline may be claimed.
# They are NOT part of `experiments`: `sweep` alone regenerates the drift stream
# eight times per config, so the set costs hours where `experiments` costs
# minutes. Run them deliberately -- `make experiments-full` does both in order.
#
# Each writes to its OWN directory, never $(OUT). `results/` holds the committed
# artefacts behind the paper's tables, and none of these targets should be able
# to overwrite them by accident. `seeds` is the exception and is safe: it writes
# rq3_baselines/rq3_seeds only, which no other target produces.
controls: seeds sweep baselines ablation
	@echo ""
	@echo "[make] RQ3 controls complete:"
	@echo "         floor + seed variance -> $(AIOPS)/$(OUT)/rq3_{baselines,seeds}*"
	@echo "         drift sweep           -> $(AIOPS)/$(SWEEP_OUT)/"
	@echo "         streaming baselines   -> $(AIOPS)/$(BASELINES_OUT)/"
	@echo "         component ablation    -> $(AIOPS)/$(ABLATION_OUT)/"

experiments-full: experiments controls

# Trivial always-alarm floor, the ORACLE threshold-recalibration control, and
# five-seed variance. Note: baselines_and_seeds hardcodes n_episodes=320, so
# EPISODES/DRIFT_EPISODES do NOT apply here -- a shorter run needs a code change.
seeds:
	cd $(AIOPS) && $(PY) -u -m ml.experiments.baselines_and_seeds --seeds $(RQ3_SEEDS) --configs $(CONFIGS) --out $(OUT)

# Drift-magnitude sweep: rescales every regime multiplier toward 1 so the single
# reported operating point becomes a curve. Answers "we set the drift as large as
# the fault" with a measurement -- and shows the frozen model winning below a
# ~1.15x baseline shift. Slowest control by far; it regenerates the stream per
# alpha (8 by default) per config, and checkpoints the CSV as it goes.
sweep:
	cd $(AIOPS) && $(PY) -u -m ml.experiments.drift_sweep --episodes $(DRIFT_EPISODES) --seed $(SEED) --configs $(SWEEP_CONFIGS) --out $(SWEEP_OUT)

# Off-the-shelf incremental learners on the identical stream, each scored twice:
# raw, and behind a running StandardScaler. The scaled arm is the fair contrast
# (our detector carries an EW normaliser); the raw arm shows what scaling alone
# is worth. Read with `ablation` this gives the whole ladder.
baselines:
	cd $(AIOPS) && $(PY) -u -m ml.experiments.baseline_streaming --episodes $(DRIFT_EPISODES) --seed $(SEED) --configs $(CONFIGS) --out $(BASELINES_OUT)

# The online detector with its own mechanisms switched off in turn (champion
# pool, drift monitor). Both flags default to True in OnlineModel, so no
# published RQ3 number moves unless an ablation explicitly asks otherwise.
ablation:
	cd $(AIOPS) && $(PY) -u -m ml.experiments.ablate_online --episodes $(DRIFT_EPISODES) --seed $(SEED) --configs $(CONFIGS) --out $(ABLATION_OUT)

# Five-seed cost profile: the min-max RANGES the write-up quotes (580-880 ms
# periodic spikes, an online tail never above 78 ms, 10-48x tail, ~120-390x
# footprint, 4.1-4.8x CPU). `cost` profiles ONE seed and cannot produce any of
# them. This is cost_compare once per seed, so it is the most expensive target
# here -- budget hours.
#
# Reuses cost_compare.run_config, so a per-seed row IS the row `make cost`
# reports for that seed. Writes the aggregate to $(OUT) and each seed's full
# table to $(COST_SEEDS_OUT), which the aggregate discards columns from.
#
# Structural columns (train events, retained windows, model size) reproduce
# exactly; the wall-clock ones -- and so tail_ratio and cpu_ratio -- are
# properties of the machine and will NOT match the committed numbers to the
# decimal. That is why the write-up quotes an order of magnitude, not a
# millisecond.
cost-seeds:
	cd $(AIOPS) && $(PY) -u -m ml.experiments.cost_seeds --seeds $(RQ3_SEEDS) --configs $(CONFIGS) --episodes $(DRIFT_EPISODES) --out $(OUT) --per-seed-out $(COST_SEEDS_OUT)

# Re-derive the aggregate + summary from per-seed tables that already exist in
# $(COST_SEEDS_OUT). Seconds, not hours: it re-reads CSVs, fits nothing.
cost-seeds-agg:
	cd $(AIOPS) && $(PY) -m ml.experiments.cost_seeds --seeds $(RQ3_SEEDS) --from-dir $(COST_SEEDS_OUT) --out $(OUT)

# Replay a RECORDED fault-injection campaign against historical PromQL: each
# query is evaluated at the instant its window represents, so this scores
# MEASURED telemetry rather than the generator. The only such result in the repo.
#
# Preconditions:
#   1. TF_LIVE=1 (set below) and a reachable Prometheus holding the campaign's
#      retention window -- otherwise every window collects zeros and the run is
#      a silent no-op rather than an error.
#   2. $(LIVE_LABELS) must be the ground truth for THAT campaign; the join is by
#      timestamp, so labels from a different run mislabel every window.
#
# Scope is C1 only, on purpose: collect_metrics_live takes an `at` timestamp but
# the Loki/Tempo/k8s-event collectors do not, so C2-C4 would mix present-moment
# values into a past window with nothing downstream to catch it. Collection is
# checkpointed to live_windows_cache.jsonl -- an interrupted replay resumes.
live-replay:
	cd $(AIOPS) && TF_LIVE=1 \
	  PROM_URL=$${PROM_URL:-http://localhost:9090} \
	  VM_URL=$${VM_URL:-http://localhost:8428} \
	  $(PY) -u -m ml.experiments.live_replay --labels $(LIVE_LABELS) --out $(LIVE_OUT)

# ---- streaming / LLM -------------------------------------------------------
streaming:
	cd $(AIOPS) && $(PY) -m streaming.run_pipeline --episodes $(STREAM_EPISODES)

# RQ4 model-family comparison WITH the local-LLM detector as a sixth family.
#
# Preconditions, both of which fail silently if unmet:
#   1. Ollama must serve qwen2.5:3b at localhost:$(OLLAMA_PORT) -- run
#      'make ollama-forward' in another terminal FIRST and check it responds:
#         curl -s http://localhost:$(OLLAMA_PORT)/api/tags
#      With nothing bound, the detector falls back to the z-score heuristic and
#      the row is labelled '(heuristic)' -- a wasted multi-hour run.
#   2. The forward must stay up for the WHOLE run. LLMDetector.mode is fixed at
#      __init__ and never re-checked, and a per-window request failure returns
#      {"anomaly": false} rather than raising -- so a mid-run drop yields a row
#      still labelled '(llm)' whose recall has silently collapsed.
#
# Writes to $(LLM_OUT), never $(OUT): run_experiment rewrites rq1/rq2/rq4 CSVs
# and summary.json, and $(OUT) holds the committed artefacts behind the paper's
# tables. Compare the two, then promote deliberately.
#
# Cost: CPU inference of a 3B model is ~5-6 s/window; the 200-episode test split
# is ~6.5k windows, so budget ~10 h on a laptop. Use a GPU host if you have one.
#
# After the run, verify before using any number:
#   grep llm $(AIOPS)/$(LLM_OUT)/rq4_model_family.csv   # must say (llm)
#   diff <(cut -d, -f1-4 $(AIOPS)/$(OUT)/rq4_model_family.csv) \
#        <(cut -d, -f1-4 $(AIOPS)/$(LLM_OUT)/rq4_model_family.csv)
# rf/gb/xgb/multimodal_fusion are deterministic at seed 42 and must reproduce;
# lstm is stochastic and will not.
llm:
	cd $(AIOPS) && ENABLE_LLM=1 $(PY) -m ml.experiments.run_experiment --episodes $(EPISODES) --out $(LLM_OUT)

lora:
	cd $(AIOPS) && $(PY) -m llm.build_dataset --episodes 400 --out llm/data
	cd $(AIOPS) && $(PY) -m llm.train_lora --data llm/data --out llm/adapters/qwen2.5-3b-traceflix

# ---- webui -----------------------------------------------------------------
webui:
	cd $(AIOPS) && $(PY) -m uvicorn webui.backend.app:app --port 8000

webui-build:
	cd $(AIOPS)/webui/frontend && npm install && npm run build

# ---- AIOps (local k8s) -----------------------------------------------------
# Re-apply / remove the in-cluster AIOps engine + dashboard in the $(NS) namespace.
# NOTE: the dashboard SPA is injected by an initContainer using the local image
# traceflix/aiops-dist:1.0.0, which must already be built and loaded into the kind
# nodes -- `make run-platform` (run.ps1) does that. Use these for a quick re-apply.
aiops-up:
	kubectl apply -f $(AIOPS)/k8s/aiops.yaml

aiops-down:
	kubectl delete -f $(AIOPS)/k8s/aiops.yaml --ignore-not-found

# ---- Ollama (local k8s, opt-in) -------------------------------------------
# Serves qwen2.5:3b for the AIOps LLM detector at http://ollama:11434, which is
# what aiops.yaml points OLLAMA_URL at. Part of the k8s deployment (k8s-deploy
# and run.ps1's manifest list); these targets are for a standalone re-apply,
# the same way aiops-up/-down complement the full deploy.
#
# Sizing warning: the pod requests 3Gi and the qwen2.5:3b pull adds ~2Gi more.
# On a memory-capped Docker Desktop / WSL2 VM that is enough to OOM the VM and
# take the Docker engine -- and with it the whole cluster -- down. Check the
# headroom before a deploy:
#   wsl -d docker-desktop --exec free -m       # Windows
#   docker run --rm alpine free -m             # otherwise
ollama-up:
	kubectl apply -f $(AIOPS)/k8s/ollama.yaml
	kubectl -n $(NS) rollout status deploy/ollama --timeout=300s
	@echo "[make] ollama up; the qwen2.5:3b pull (~2 GB) runs as job/ollama-pull -- watch it with 'make ollama-logs'"

ollama-down:
	kubectl delete -f $(AIOPS)/k8s/ollama.yaml --ignore-not-found

# Follow the one-shot model pull. Empty output means the Job is not scheduled yet.
ollama-logs:
	kubectl -n $(NS) logs job/ollama-pull -f

# Expose the in-cluster Ollama on the host, for a webui/detector run OUTSIDE the
# cluster (make webui): there OLLAMA_URL defaults to http://localhost:$(OLLAMA_PORT),
# and without this forward the detector reports its heuristic fallback instead.
# Pods deployed in-cluster do NOT need this -- aiops.yaml already points them at
# the Service DNS name. Blocks until interrupted; run it in its own terminal, and
# re-run it after an ollama pod restart (the forward dies with the pod).
ollama-forward:
	@echo "[make] ollama -> http://localhost:$(OLLAMA_PORT)  (Ctrl-C to stop)"
	kubectl -n $(NS) port-forward svc/ollama $(OLLAMA_PORT):11434

# ---- Java services ---------------------------------------------------------
build-services:
	cd $(SERVICES) && mvn -q clean package -DskipTests

compile-services:
	cd $(SERVICES) && mvn -q compile

images: build-services
	cd $(SERVICES) && for s in $(ALL_SVCS); do docker build -t traceflix/$$s-service:1.0.0 $$s-service; done

# ---- tests -----------------------------------------------------------------
test: test-aiops test-services

test-aiops:
	cd $(AIOPS) && $(PY) -m pytest tests/ -q

test-services:
	cd $(SERVICES) && mvn -q test

# ---- deploy: Docker Compose (deploy/virtfusion) ---------------------------
# Single-host stack = telemetry backends + the nine-service mesh.
deploy-up: telemetry-up mesh-up
deploy-down: mesh-down telemetry-down

mesh-up:
	cd $(DC_VM2) && docker compose -f docker-compose.yml -f docker-compose.mesh.yml --env-file ../.env up -d

mesh-down:
	cd $(DC_VM2) && docker compose -f docker-compose.yml -f docker-compose.mesh.yml down

telemetry-up:
	cd $(DC_VM3) && docker compose --env-file ../.env up -d

telemetry-down:
	cd $(DC_VM3) && docker compose down

kafka-llm-up:
	cd $(DC_VM1) && docker compose -f docker-compose.kafka-llm.yml up -d

kafka-llm-down:
	cd $(DC_VM1) && docker compose -f docker-compose.kafka-llm.yml down

gateway-up:
	cd $(DC_VM4) && docker compose --env-file ../.env up -d

gateway-down:
	cd $(DC_VM4) && docker compose down

# ---- deploy: Kubernetes ----------------------------------------------------
bootstrap:
	"$(BASH_BIN)" scripts/bootstrap.sh

k8s-deploy:
	kubectl apply -f $(SERVICES)/deployment.yaml
	kubectl apply -f observability/on-demand-observability.yaml
	kubectl apply -f $(AIOPS)/k8s/victoriametrics.yaml
	kubectl apply -f $(AIOPS)/k8s/load-generator-fixed.yaml
	kubectl apply -f $(AIOPS)/k8s/ollama.yaml

k8s-delete:
	-kubectl delete namespace $(NS)

chaos-install:
	cd $(AIOPS) && "$(BASH_BIN)" scripts/install_chaos_mesh.sh

# Show all pods in the project namespace.
status:
	kubectl get pods -n $(NS) -o wide

# ---- fault injection / live ------------------------------------------------
# Run the analysis against live PromQL/LogQL/TraceQL (point the URLs at your stack).
live:
	cd $(AIOPS) && TF_LIVE=1 \
	  PROM_URL=$${PROM_URL:-http://localhost:9090} \
	  LOKI_URL=$${LOKI_URL:-http://localhost:3100} \
	  TEMPO_URL=$${TEMPO_URL:-http://localhost:3200} \
	  VM_URL=$${VM_URL:-http://localhost:8428} \
	  $(PY) -m ml.experiments.run_experiment --labels data/labels.csv

# Drive Chaos Mesh fault episodes on the k8s deployment, recording ground truth.
live-episodes:
	cd $(AIOPS) && $(PY) faults/run_episodes.py --episodes $(LIVE_EPISODES) --labels data/labels.csv

# Inject a single fault into a Compose-deployed service via Pumba.
inject:
	cd $(DC_VM2) && ./inject-fault.sh $(SVC) $(FAULT) $(DUR)

# ---- paper / dissertation --------------------------------------------------
paper:
# 	$(PY) paper/make_figures.py
# ifeq ($(HAS_TECTONIC),1)
# 	tectonic -X compile --keep-logs "$(PAPER_DIR)/sn-article.tex"
# else
	docker run --rm -v "$(PAPER_DIR):/data" -w /data $(TEXIMG) sh -c "\
	  pdflatex -interaction=nonstopmode sn-article.tex && \
	  bibtex sn-article && \
	  pdflatex -interaction=nonstopmode sn-article.tex && \
	  pdflatex -interaction=nonstopmode sn-article.tex"
# endif


paper_IEEE:
# 	$(PY) paper/make_figures.py
# ifeq ($(HAS_TECTONIC),1)
# 	tectonic -X compile --keep-logs "$(PAPER_IEEE_DIR)/bare_jrnl.tex"
# else
	docker run --rm -v "$(PAPER_IEEE_DIR):/data" -w /data $(TEXIMG) sh -c "\
	  pdflatex -interaction=nonstopmode bare_jrnl.tex && \
	  bibtex bare_jrnl && \
	  pdflatex -interaction=nonstopmode bare_jrnl.tex && \
	  pdflatex -interaction=nonstopmode bare_jrnl.tex"
# endif

paper-pages:
	@$(PY) -c "import re;t=open('paper/sn-article.log',encoding='utf-8',errors='replace').read();m=re.findall(r'\((\d+)\s+pages?',t);print((m[-1]+' pages') if m else 'no page count (compile first)')"

paper_IEEE-pages:
	@$(PY) -c "import re;t=open('paper/paper_IEEE/bare_jrnl.log',encoding='utf-8',errors='replace').read();m=re.findall(r'\((\d+)\s+pages?',t);print((m[-1]+' pages') if m else 'no page count (compile first)')"

paper-clean:
	-$(PY) -c "import os,sys;[os.remove(f) for f in sys.argv[1:] if os.path.exists(f)]" paper/sn-article.aux paper/sn-article.bbl paper/sn-article.blg paper/sn-article.log paper/sn-article.out

paper_IEEE-clean:
	-$(PY) -c "import os,sys;[os.remove(f) for f in sys.argv[1:] if os.path.exists(f)]" paper/paper_IEEE/bare_jrnl.aux paper/paper_IEEE/bare_jrnl.bbl paper/paper_IEEE/bare_jrnl.blg paper/paper_IEEE/bare_jrnl.log paper/paper_IEEE/bare_jrnl.out

dissertation:
	cd dissertation && $(PY) md2docx.py

# ---- clean -----------------------------------------------------------------
clean:
	-cd $(SERVICES) && mvn -q clean
	-$(PY) -c "import shutil,pathlib,sys;[shutil.rmtree(p,ignore_errors=True) for p in pathlib.Path(sys.argv[1]).rglob('__pycache__')]" $(AIOPS)

clean-results:
	-$(PY) -c "import glob,os,sys;[os.remove(f) for pat in sys.argv[1:] for f in glob.glob(pat)]" "$(RESULTS)/*.csv" "$(RESULTS)/*.json" "$(RESULTS)/figures/*.png"

clean-all: clean clean-results paper-clean
