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
EPISODES        ?= 200          # offline RQ1/RQ2/RQ4 (run_experiment)
DRIFT_EPISODES  ?= 320          # RQ3 drift stream (online_vs_offline, cost)
STREAM_EPISODES ?= 20           # streaming backbone demo
LIVE_EPISODES   ?= 30           # live fault-injection episodes
CONFIGS         ?= C1,C2,C3,C4
SEED            ?= 42
OUT             ?= data/results # relative to aiops/
NS              ?= on-demand-observability # k8s namespace
SVC             ?= catalog-service         # inject: target service
FAULT           ?= cpu_saturation          # inject: fault type
DUR             ?= 120                      # inject: duration (s)
# strip the trailing whitespace the aligned comments above introduce
EPISODES        := $(strip $(EPISODES))
DRIFT_EPISODES  := $(strip $(DRIFT_EPISODES))
STREAM_EPISODES := $(strip $(STREAM_EPISODES))
LIVE_EPISODES   := $(strip $(LIVE_EPISODES))
OUT             := $(strip $(OUT))
NS              := $(strip $(NS))
SVC             := $(strip $(SVC))
FAULT           := $(strip $(FAULT))
DUR             := $(strip $(DUR))

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
.PHONY: help all setup setup-llm \
        experiments repro quick rq124 rq3 cost plots figures \
        streaming llm lora \
        webui webui-build \
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
	@echo "  SETUP        setup  setup-llm"
	@echo "  EXPERIMENTS  experiments  repro  quick  rq124  rq3  cost  plots  figures"
	@echo "  STREAM/LLM   streaming  llm  lora"
	@echo "  WEBUI        webui  webui-build"
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

# ---- setup -----------------------------------------------------------------
setup:
	$(PY) -m pip install -r $(AIOPS)/requirements.txt

setup-llm:
	$(PY) -m pip install -r $(AIOPS)/llm/requirements-llm.txt

# ---- experiments (aiops, offline) -----------------------------------------
experiments: rq124 rq3 cost plots
	@echo ""
	@echo "[make] experiments complete -> $(RESULTS)/"

repro: setup experiments test

quick:
	$(MAKE) experiments EPISODES=60 DRIFT_EPISODES=120

rq124:
	cd $(AIOPS) && $(PY) -m ml.experiments.run_experiment --episodes $(EPISODES) --seed $(SEED) --out $(OUT)

rq3:
	cd $(AIOPS) && $(PY) -m ml.experiments.online_vs_offline --episodes $(DRIFT_EPISODES) --configs $(CONFIGS) --out $(OUT)

cost:
	cd $(AIOPS) && $(PY) -m ml.experiments.cost_compare --episodes $(DRIFT_EPISODES) --configs $(CONFIGS) --out $(OUT)

plots:
	cd $(AIOPS) && $(PY) -m ml.eval.plots $(OUT)

figures:
	$(PY) paper/make_figures.py

# ---- streaming / LLM -------------------------------------------------------
streaming:
	cd $(AIOPS) && $(PY) -m streaming.run_pipeline --episodes $(STREAM_EPISODES)

# Requires Ollama serving qwen2.5:3b; without it the LLM row reports a heuristic.
llm:
	cd $(AIOPS) && ENABLE_LLM=1 $(PY) -m ml.experiments.run_experiment --episodes $(EPISODES) --out $(OUT)

lora:
	cd $(AIOPS) && $(PY) -m llm.build_dataset --episodes 400 --out llm/data
	cd $(AIOPS) && $(PY) -m llm.train_lora --data llm/data --out llm/adapters/qwen2.5-3b-traceflix

# ---- webui -----------------------------------------------------------------
webui:
	cd $(AIOPS) && $(PY) -m uvicorn webui.backend.app:app --port 8000

webui-build:
	cd $(AIOPS)/webui/frontend && npm install && npm run build

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
	bash scripts/bootstrap.sh

k8s-deploy:
	kubectl apply -f $(SERVICES)/deployment.yaml
	kubectl apply -f observability/on-demand-observability.yaml
	kubectl apply -f $(AIOPS)/k8s/victoriametrics.yaml
	kubectl apply -f $(AIOPS)/k8s/load-generator-fixed.yaml

k8s-delete:
	-kubectl delete namespace $(NS)

chaos-install:
	cd $(AIOPS) && bash scripts/install_chaos_mesh.sh

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
