# VM1 (GPU) — AIOps engine + dashboard backend.
# CUDA base so torch trains LSTM / fusion (RQ4) and XGBoost on the GPU.
# Installs the CUDA torch wheel FIRST, so the upstream aiops/requirements.txt
# `torch>=2.2` line is already satisfied — the project itself is never modified.
FROM nvidia/cuda:12.1.1-cudnn8-runtime-ubuntu22.04

ENV DEBIAN_FRONTEND=noninteractive \
    PIP_NO_CACHE_DIR=1 \
    PYTHONUNBUFFERED=1

# Python 3 + Node 20 (the dashboard builds the React SPA via scripts/run_webui.sh)
RUN apt-get update && apt-get install -y --no-install-recommends \
        python3 python3-pip python3-venv git curl ca-certificates gnupg bash \
    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/*

# CUDA-enabled torch BEFORE the project requirements (so -r requirements.txt is a no-op for torch)
RUN python3 -m pip install --upgrade pip \
    && python3 -m pip install torch>=2.2 --index-url https://download.pytorch.org/whl/cu121

WORKDIR /opt/traceflix/aiops
# requirements installed at build for layer caching; source is bind-mounted at runtime.
COPY aiops/requirements.txt /tmp/requirements.txt
RUN python3 -m pip install -r /tmp/requirements.txt

ENV PYTHON=python3 PORT=8000
EXPOSE 8000
# scripts/run_webui.sh (prod): builds the SPA then serves API+SPA on :8000
CMD ["bash", "scripts/run_webui.sh"]
