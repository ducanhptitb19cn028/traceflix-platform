# Sidecar image carrying the CURRENT aiops source, injected into the AIOps pod.
#
# The published :gpu image bakes the backend as it stood when that image was
# built. This one is copied over /opt/traceflix/aiops by the initContainer in
# aiops.yaml (`cp -a /src/. /app/`), so the pod runs today's code against the
# image's already-installed dependencies -- no multi-GB CUDA rebuild to pick up a
# backend change.
#
# It supersedes aiops-dist.Dockerfile, which carried only webui/frontend/dist:
# dist/ lives inside the source, so injecting the source injects the SPA too.
#
# Build from the REPO ROOT (the context must include aiops/):
#   docker build -f aiops/k8s/aiops-src.Dockerfile -t traceflix/aiops-src:1.0.0 .
# or just:  .\mk.ps1 aiops-image
FROM busybox:1.36

# Copied path by path rather than as `COPY aiops /src`, because the repo has no
# .dockerignore and one added at the root would change what every other image in
# the project builds. The two directories left out are the ones that must not
# ship: webui/frontend/node_modules (hundreds of MB, and the pod serves the built
# dist/, never the sources) and tests/ (never executed in the pod).
COPY aiops/__init__.py       /src/__init__.py
COPY aiops/requirements.txt  /src/requirements.txt
COPY aiops/collectors        /src/collectors
COPY aiops/ml                /src/ml
COPY aiops/streaming         /src/streaming
COPY aiops/faults            /src/faults
COPY aiops/llm               /src/llm
COPY aiops/scripts           /src/scripts
COPY aiops/docs              /src/docs
COPY aiops/webui/backend     /src/webui/backend

# The built SPA. `.\mk.ps1 aiops-image` refuses to run if this is missing, since
# a pod serving a stale dist while running today's backend is the confusing case:
# the tabs render but their endpoints 404.
COPY aiops/webui/frontend/dist /src/webui/frontend/dist

# Results and recorded live windows. The dashboard's result pages read
# data/results*/ directly, and the cluster detector fits on the live caches in
# data/results_live*/ -- without these the in-cluster page has no training set and
# refuses to start. `cp -a /src/. /app/` merges rather than replaces, so anything
# the pod recorded itself under data/ survives a refresh unless a file of the same
# name is shipped here.
COPY aiops/data              /src/data
