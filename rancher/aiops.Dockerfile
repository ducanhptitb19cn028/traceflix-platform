# AIOps engine + dashboard image for Kubernetes.
#
# Unlike the Compose deploy (deploy/virtfusion/vm1-gpu) which bind-mounts the host
# source, k8s has no host mount -- so this image BAKES the aiops source in (incl. the
# prebuilt React dashboard at aiops/webui/frontend/dist). The upstream project is not
# modified; this Dockerfile is part of the additive rancher/ overlay.
#
# Build from the REPO ROOT (build context must include aiops/):
#   docker build -f rancher/aiops.Dockerfile -t <registry>/traceflix-aiops:gpu .
#   docker push <registry>/traceflix-aiops:gpu
FROM nvidia/cuda:12.1.1-cudnn8-runtime-ubuntu22.04

ENV DEBIAN_FRONTEND=noninteractive \
    PIP_NO_CACHE_DIR=1 \
    PYTHONUNBUFFERED=1 \
    PYTHON=python3 \
    PORT=8000

RUN apt-get update && apt-get install -y --no-install-recommends \
        python3 python3-pip git curl ca-certificates bash \
    && rm -rf /var/lib/apt/lists/*

# CUDA torch first so the project's `torch>=2.2` requirement is already satisfied
# (GPU LSTM/fusion for RQ4, and the optional LoRA fine-tune).
RUN python3 -m pip install --upgrade pip \
    && python3 -m pip install "torch>=2.2" --index-url https://download.pytorch.org/whl/cu121

WORKDIR /opt/traceflix/aiops
COPY aiops/requirements.txt /tmp/requirements.txt
RUN python3 -m pip install -r /tmp/requirements.txt

# Bake the source (includes the prebuilt SPA the FastAPI backend serves).
COPY aiops/ /opt/traceflix/aiops/

EXPOSE 8000
# Serve the dashboard (API + SPA). Live collectors activate when TF_LIVE=1 + URLs are set.
CMD ["python3", "-m", "uvicorn", "webui.backend.app:app", "--host", "0.0.0.0", "--port", "8000"]
