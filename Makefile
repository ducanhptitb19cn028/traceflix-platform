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
OLLAMA_MODEL    ?= qwen2.5:3b    # ollama-forward-bg: model the detector needs pulled
WEBUI_PORT      ?= 8000          # webui / webui-forward: host port
FRONTEND_PORT   ?= 5173          # frontend-forward: host port
GRAFANA_PORT    ?= 3000          # grafana-forward: host port
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
OLLAMA_MODEL    := $(strip $(OLLAMA_MODEL))
WEBUI_PORT      := $(strip $(WEBUI_PORT))
FRONTEND_PORT   := $(strip $(FRONTEND_PORT))
GRAFANA_PORT    := $(strip $(GRAFANA_PORT))
FRONTEND_IMG    := traceflix/frontend:1.0.0

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
        webui webui-build webui-forward \
        frontend-image frontend-up frontend-down frontend-forward \
        ollama-up ollama-down ollama-logs ollama-forward ollama-forward-bg ollama-forward-stop \
        grafana-forward grafana-forward-bg grafana-forward-stop \
        build-services compile-services images \
        test test-aiops test-services \
        deploy-up deploy-down mesh-up mesh-down telemetry-up telemetry-down \
        kafka-llm-up kafka-llm-down gateway-up gateway-down \
        bootstrap k8s-deploy k8s-delete chaos-install status \
        k8s-clean k8s-clean-images k8s-purge \
        live live-episodes inject inject-compose \
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
	@echo "  WEBUI        webui  webui-build  webui-forward  (forward = the in-cluster one;"
	@echo "                                                   webui auto-forwards ollama)"
	@echo "  FRONTEND     frontend-image  frontend-up  frontend-down  frontend-forward"
	@echo "  AIOPS (k8s)  aiops-up  aiops-down"
	@echo "  OLLAMA (k8s) ollama-up  ollama-down  ollama-logs  (needs ~3Gi free)"
	@echo "               ollama-forward  ollama-forward-bg  ollama-forward-stop  (-bg = detached)"
	@echo "  GRAFANA      grafana-forward  grafana-forward-bg  grafana-forward-stop"
	@echo "                              (Grafana UI on localhost:$(GRAFANA_PORT), admin/admin)"
	@echo "  JAVA         build-services  compile-services  images  test-services"
	@echo "  TESTS        test  test-aiops  test-services"
	@echo "  COMPOSE      deploy-up/down  mesh-up/down  telemetry-up/down"
	@echo "               kafka-llm-up/down  gateway-up/down"
	@echo "  KUBERNETES   bootstrap  k8s-deploy  k8s-delete  chaos-install  status"
	@echo "  K8S CLEAN    k8s-clean  k8s-clean-images  k8s-purge  (purge = both; destructive)"
	@echo "  FAULTS/LIVE  live-episodes  inject  inject-compose  (SVC= FAULT= DUR=)"
	@echo "               live-replay scores the result; 'live' is DEPRECATED (never was live)"
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
#   3. One out directory per campaign. build_live_windows resumes from
#      live_windows_cache.jsonl and returns EVERY window that cache holds, so a
#      second campaign pointed at an existing directory is scored against the
#      union of both -- silently, and the run still looks clean. results_live/
#      belongs to labels_live.csv; the check below keeps it that way.
live-replay:
	@if [ "$(LIVE_OUT)" = "data/results_live" ] && \
	    [ "$(LIVE_LABELS)" != "data/labels_live.csv" ]; then \
	  echo "[make] data/results_live is reserved for data/labels_live.csv --"; \
	  echo "       give this campaign its own LIVE_OUT, e.g. LIVE_OUT=data/results_live_mine"; \
	  exit 1; \
	fi
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
#   1. Ollama must serve $(OLLAMA_MODEL) at localhost:$(OLLAMA_PORT) -- run
#      'make ollama-forward' in another terminal FIRST (or 'make ollama-forward-bg'
#      here, which also checks the model is pulled) and confirm it responds:
#         curl -s http://localhost:$(OLLAMA_PORT)/api/tags
#      This target deliberately does NOT depend on -bg: a multi-hour run should
#      not start behind a forward nobody watched come up.
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
# Run the dashboard LOCALLY from source (hot source, no image rebuild). Needs the
# SPA built first (webui-build).
#
# The LLM path is handled for you: this copy runs OUTSIDE the cluster, where
# OLLAMA_URL defaults to http://localhost:$(OLLAMA_PORT) and nothing is bound, so
# ollama-forward-bg puts the in-cluster Qwen there before uvicorn starts. Without
# it the detector reports its heuristic fallback banner. The forward outlives the
# dashboard on purpose (restarting webui is common) -- 'make ollama-forward-stop'.
webui: ollama-forward-bg
	cd $(AIOPS) && $(PY) -m uvicorn webui.backend.app:app --port $(WEBUI_PORT)

# Reach the dashboard already running IN the cluster (svc/aiops, the Deployment
# applied by aiops-up) instead of running a second copy locally. Serves the SPA
# and the API on the same port, so http://localhost:$(WEBUI_PORT) is the whole
# dashboard. Do NOT run this alongside `make webui` -- they collide on the port.
# Blocks until interrupted; re-run it after an aiops pod restart.
webui-forward:
	@echo "[make] aiops dashboard -> http://localhost:$(WEBUI_PORT)  (Ctrl-C to stop)"
	kubectl -n $(NS) port-forward svc/aiops $(WEBUI_PORT):8000

webui-build:
	cd $(AIOPS)/webui/frontend && npm install && npm run build

# ---- TraceFlix web client (k8s) --------------------------------------------
# The nine-service mesh's own web client, deployed beside the services it calls.
# It serves the SPA and proxies /api/* to the mesh by Service DNS name, so ONE
# forward reaches the whole app -- the browser never addresses a service itself.
#
# Order on a fresh cluster: frontend-image (build + load), frontend-up (apply),
# frontend-forward (reach it). Re-run frontend-image then `kubectl -n $(NS)
# rollout restart deploy/frontend` after changing anything under services/frontend.
frontend-image:
	docker build -t $(FRONTEND_IMG) $(SERVICES)/frontend
	@echo "[make] loading $(FRONTEND_IMG) into the kind node stores (imagePullPolicy: Never)"
	@for n in $$(docker ps --format '{{.Names}}|{{.Image}}' | grep kindest/node | cut -d'|' -f1); do \
	  echo "  -> $$n"; \
	  docker save $(FRONTEND_IMG) | docker exec -i $$n ctr -n k8s.io images import - >/dev/null || \
	    echo "  !! load into $$n failed"; \
	done

frontend-up:
	kubectl apply -f $(SERVICES)/frontend/k8s/frontend.yaml
	kubectl -n $(NS) rollout status deploy/frontend --timeout=120s

frontend-down:
	kubectl delete -f $(SERVICES)/frontend/k8s/frontend.yaml --ignore-not-found

# Blocks until interrupted; re-run it after a frontend pod restart.
frontend-forward:
	@echo "[make] traceflix web client -> http://localhost:$(FRONTEND_PORT)  (Ctrl-C to stop)"
	kubectl -n $(NS) port-forward svc/frontend $(FRONTEND_PORT):5173

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

# The same forward, DETACHED, so a one-terminal `make webui` reaches the LLM.
# `webui` depends on this, so the usual way to get it is to change nothing.
#
# Idempotent: if :$(OLLAMA_PORT) already answers -- your own ollama-forward, a
# host Ollama, an earlier -bg -- it forwards nothing and returns.
#
# Never fails the build. An unreachable Ollama is a legitimate way to run the
# dashboard: the detector says so in its banner and scores windows with the
# rule-of-thumb test instead. It warns loudly in two cases the banner cannot
# distinguish for you: no forward at all, and a daemon that answers but has not
# pulled $(OLLAMA_MODEL) -- there every call errors and every window is reported
# normal, which looks like a healthy system rather than a broken detector.
ollama-forward-bg:
	@if curl -sf -m 2 http://localhost:$(OLLAMA_PORT)/api/tags >/dev/null 2>&1; then \
	  echo "[make] ollama already reachable on :$(OLLAMA_PORT)"; \
	elif ! kubectl -n $(NS) get deploy/ollama >/dev/null 2>&1; then \
	  echo "[make] deploy/ollama is not in $(NS) -- run 'make ollama-up' for the LLM detector;"; \
	  echo "[make] continuing without it (heuristic fallback)"; \
	  exit 0; \
	else \
	  echo "[make] port-forward svc/ollama -> localhost:$(OLLAMA_PORT) (background; 'make ollama-forward-stop')"; \
	  kubectl -n $(NS) port-forward svc/ollama $(OLLAMA_PORT):11434 >/dev/null 2>&1 & \
	  i=0; while [ $$i -lt 30 ]; do \
	    curl -sf -m 2 http://localhost:$(OLLAMA_PORT)/api/tags >/dev/null 2>&1 && break; \
	    sleep 1; i=$$((i+1)); \
	  done; \
	fi; \
	tags=$$(curl -sf -m 5 http://localhost:$(OLLAMA_PORT)/api/tags 2>/dev/null); \
	if [ -z "$$tags" ]; then \
	  echo "[make] !! ollama unreachable on :$(OLLAMA_PORT) -- detector will use the heuristic fallback"; \
	elif ! echo "$$tags" | grep -q '$(OLLAMA_MODEL)'; then \
	  echo "[make] !! ollama answers but $(OLLAMA_MODEL) is NOT pulled -- every call errors and"; \
	  echo "[make] !! every window reports normal. Watch the pull with 'make ollama-logs'"; \
	else \
	  echo "[make] ollama on :$(OLLAMA_PORT) serving $(OLLAMA_MODEL)"; \
	fi

# Stop the detached forward. Matches on the command line, so it also stops a
# foreground `make ollama-forward` running in another terminal -- there is no
# way to tell the two apart from here.
ollama-forward-stop:
	@pkill -f "port-forward svc/ollama" 2>/dev/null && echo "[make] background forward stopped" \
	  || echo "[make] no background forward running"

# ---- grafana ---------------------------------------------------------------
# Expose the in-cluster Grafana (deployed by k8s-deploy as part of
# observability/on-demand-observability.yaml) on the host, so the dashboards over
# Prometheus/Tempo/Loki can be opened in a browser -- the Service is ClusterIP,
# there is no Ingress. Log in with admin/admin (set in the Deployment's env).
# Blocks until interrupted; run it in its own terminal, and re-run it after a
# grafana pod restart (the forward dies with the pod).
#
# :3000 is a popular port. If something local already owns it, move the forward:
#   make grafana-forward GRAFANA_PORT=3001
grafana-forward:
	@echo "[make] grafana -> http://localhost:$(GRAFANA_PORT)  (admin/admin, Ctrl-C to stop)"
	kubectl -n $(NS) port-forward svc/grafana $(GRAFANA_PORT):3000

# The same forward, DETACHED, for a one-terminal demo run.
#
# Idempotent: if :$(GRAFANA_PORT) already answers -- your own grafana-forward, an
# earlier -bg, some other local server -- it forwards nothing and returns. It
# never fails the build: Grafana is for looking at, nothing in the pipeline reads
# it, so a missing deployment is a warning rather than an error.
grafana-forward-bg:
	@if curl -sf -m 2 http://localhost:$(GRAFANA_PORT)/api/health >/dev/null 2>&1; then \
	  echo "[make] grafana already reachable on :$(GRAFANA_PORT)"; \
	elif ! kubectl -n $(NS) get deploy/grafana >/dev/null 2>&1; then \
	  echo "[make] !! deploy/grafana is not in $(NS) -- run 'make k8s-deploy' first"; \
	  exit 0; \
	else \
	  echo "[make] port-forward svc/grafana -> localhost:$(GRAFANA_PORT) (background; 'make grafana-forward-stop')"; \
	  kubectl -n $(NS) port-forward svc/grafana $(GRAFANA_PORT):3000 >/dev/null 2>&1 & \
	  i=0; while [ $$i -lt 30 ]; do \
	    curl -sf -m 2 http://localhost:$(GRAFANA_PORT)/api/health >/dev/null 2>&1 && break; \
	    sleep 1; i=$$((i+1)); \
	  done; \
	  if curl -sf -m 2 http://localhost:$(GRAFANA_PORT)/api/health >/dev/null 2>&1; then \
	    echo "[make] grafana on http://localhost:$(GRAFANA_PORT) (admin/admin)"; \
	  else \
	    echo "[make] !! grafana did not answer on :$(GRAFANA_PORT) within 30s"; \
	  fi; \
	fi

# Stop the detached forward. Matches on the command line, so it also stops a
# foreground `make grafana-forward` running in another terminal.
grafana-forward-stop:
	@pkill -f "port-forward svc/grafana" 2>/dev/null && echo "[make] background forward stopped" \
	  || echo "[make] no background forward running"

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

# ---- k8s clean -------------------------------------------------------------
# `k8s-delete` above removes ONE namespace. These remove everything this project
# puts in a cluster, in the order that actually works:
#
#   1. Chaos experiment CRs first. A StressChaos/NetworkChaos carries a
#      finalizer that only the chaos-controller can clear, so deleting the
#      namespace while the controller is still up-and-then-gone leaves it
#      Terminating forever. Delete the CRs, then the release, then the ns.
#   2. The chaos-mesh helm release (its webhooks and ClusterRoles go with it).
#   3. The three namespaces: $(NS) (mesh + telemetry + aiops + ollama +
#      frontend + load-gen), devops-agent (VictoriaMetrics), chaos-mesh.
#   4. The chaos-mesh.org CRDs -- helm deliberately leaves CRDs behind.
#   5. PersistentVolumes left Released by the deleted PVCs (ollama-models).
#      Scoped by claimRef namespace, so no unrelated PV is touched.
#
# Nothing outside those namespaces is touched, and everything here is
# re-creatable with `make k8s-deploy` / `make run-platform`. Every step is
# prefixed `-` so a missing namespace or an absent helm is not an error.
K8S_NS_ALL  := $(NS) devops-agent
CHAOS_NS    := chaos-mesh
CHAOS_KINDS := podchaos networkchaos stresschaos iochaos httpchaos timechaos dnschaos jvmchaos kernelchaos schedule workflow
LOCAL_IMGS  := $(FRONTEND_IMG) traceflix/aiops-src:1.0.0 traceflix/aiops-dist:1.0.0 \
               $(foreach s,$(ALL_SVCS),traceflix/$(s)-service:1.0.0)

k8s-clean:
	@echo "[make] 1/5 deleting Chaos Mesh experiment CRs in $(NS) (finalizers block ns deletion)"
	-@for k in $(CHAOS_KINDS); do \
	   if kubectl get "$$k" -n $(NS) >/dev/null 2>&1; then \
	     kubectl delete "$$k" --all -n $(NS) --ignore-not-found --timeout=60s || true; \
	   fi; \
	 done
	@echo "[make] 2/5 uninstalling the chaos-mesh helm release"
	-@command -v helm >/dev/null 2>&1 && helm uninstall chaos-mesh -n $(CHAOS_NS) >/dev/null 2>&1 || true
	@echo "[make] 3/5 deleting namespaces: $(K8S_NS_ALL) $(CHAOS_NS)"
	-kubectl delete namespace $(K8S_NS_ALL) $(CHAOS_NS) --ignore-not-found --timeout=300s
	@echo "[make] 4/5 deleting the chaos-mesh.org CRDs (helm leaves them behind)"
	-@kubectl get crd -o name 2>/dev/null | grep 'chaos-mesh\.org' | \
	   xargs -r kubectl delete --ignore-not-found
	@echo "[make] 5/5 deleting PersistentVolumes released by the above"
	-@kubectl get pv -o jsonpath='{range .items[*]}{.metadata.name}{" "}{.status.phase}{" "}{.spec.claimRef.namespace}{"\n"}{end}' 2>/dev/null | \
	   awk '$$2=="Released" && ($$3=="$(NS)" || $$3=="devops-agent")   {print $$1}' | \
	   xargs -r kubectl delete pv
	@echo ""
	@echo "[make] cluster clean. Verify: kubectl get ns | grep -E 'observability|devops-agent|chaos-mesh'"

# Drop the locally built images. They are NOT in a registry -- every one is
# built here and side-loaded, so this is the only copy; re-create with
# `make images`, `make frontend-image` and `mk.ps1 aiops-image`. Removed from
# each kind node's containerd store (what the kubelet actually reads under
# imagePullPolicy: Never) and from the host daemon.
k8s-clean-images:
	@echo "[make] removing the locally built images from the kind node stores"
	-@for n in $$(docker ps --format '{{.Names}}|{{.Image}}' | grep kindest/node | cut -d'|' -f1); do \
	   echo "  -> $$n"; \
	   for i in $(LOCAL_IMGS); do \
	     docker exec "$$n" ctr -n k8s.io images rm "docker.io/$$i" >/dev/null 2>&1 || true; \
	   done; \
	 done
	@echo "[make] removing them from the host daemon"
	-@docker rmi $(LOCAL_IMGS) 2>/dev/null || true
	@echo "[make] images cleaned"

# Everything: cluster resources AND the locally built images.
k8s-purge: k8s-clean k8s-clean-images
	@echo "[make] k8s purge complete"

# ---- fault injection / live ------------------------------------------------
# DEPRECATED. This never ran the analysis against live telemetry. run_experiment
# accepts --labels and TF_LIVE but the join of collected windows to a labels CSV
# was never implemented (its own comment said "would go here"), so the target
# always scored a GENERATED stream -- and, having no --out, wrote it over
# data/results, the reported campaign. It is kept as a signpost rather than
# removed, because the name is in fullDemo.md, mk.ps1 and muscle memory.
#
# Refuses rather than warns: the failure it used to produce was a plausible-
# looking table, which is worse than no table.
live:
	@echo "[make] 'live' is deprecated and does nothing -- it never read live telemetry."
	@echo "       run_experiment has no live join; it also defaulted to --out data/results,"
	@echo "       so this target overwrote the reported campaign with a generated run."
	@echo ""
	@echo "       Score the DEPLOYED stack against a campaign you injected:"
	@echo "         make live-replay LIVE_LABELS=<your labels.csv> LIVE_OUT=<its own dir>"
	@echo "         (needs TF_LIVE + a reachable Prometheus still holding the window)"
	@echo "       Run the GENERATED campaign the write-up reports:"
	@echo "         make rq124            (-> $(OUT))"
	@false

# Drive Chaos Mesh fault episodes on the k8s deployment, recording ground truth.
live-episodes:
	cd $(AIOPS) && $(PY) faults/run_episodes.py --episodes $(LIVE_EPISODES) --labels data/labels.csv

# Inject a single fault into ANY service of the k8s deployment via Chaos Mesh,
# recording the same ground-truth row as live-episodes. Faults: cpu_saturation
# memory_leak latency_spike pod_kill network_partition.
#   make inject SVC=catalog-service FAULT=cpu_saturation DUR=120
inject:
	cd $(AIOPS) && $(PY) faults/inject.py $(SVC) $(FAULT) $(DUR) --labels data/labels.csv

# The compose/Pumba counterpart, for the VM2 mesh rather than the cluster. The
# recipe is invoked through $(BASH_BIN) because make hands recipes to cmd.exe on
# Windows, which cannot run ./inject-fault.sh.
inject-compose:
	"$(BASH_BIN)" -c 'cd $(DC_VM2) && ./inject-fault.sh $(SVC) $(FAULT) $(DUR)'

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
