# Tiny sidecar image carrying ONLY the prebuilt React dashboard (dist).
# An initContainer copies it into the AIOps pod so the FastAPI backend serves the
# SPA at / -- WITHOUT rebuilding the multi-GB CUDA aiops image.
#
# Build from the REPO ROOT (context must include aiops/webui/frontend/dist):
#   docker build -f aiops/k8s/aiops-dist.Dockerfile -t traceflix/aiops-dist:1.0.0 .
FROM busybox:1.36
COPY aiops/webui/frontend/dist /dist
