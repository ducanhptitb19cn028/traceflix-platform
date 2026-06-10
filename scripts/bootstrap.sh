#!/usr/bin/env bash
# One-command build + deploy of the full TraceFlix platform.
# Works from any directory (it resolves the repo root itself).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

# --- Git Bash / Cygwin: convert a Windows-style JAVA_HOME to a POSIX path so
#     Maven's shell launcher can find "$JAVA_HOME/bin/java" ---
if [ -n "${JAVA_HOME:-}" ] && command -v cygpath >/dev/null 2>&1; then
  case "$JAVA_HOME" in
    *\\*|[A-Za-z]:*) JAVA_HOME="$(cygpath -u "$JAVA_HOME")"; export JAVA_HOME ;;
  esac
fi

# --- prerequisite checks (fail early with a clear message) ---
for tool in mvn docker kubectl; do
  command -v "$tool" >/dev/null 2>&1 || { echo "ERROR: '$tool' not found on PATH." >&2; exit 1; }
done
kubectl cluster-info >/dev/null 2>&1 || {
  echo "ERROR: kubectl cannot reach a cluster. Start one first (e.g. 'minikube start'" >&2
  echo "       or enable Kubernetes in Docker Desktop), then re-run." >&2
  exit 1
}

echo "[1/4] Building Java services (Maven)..."
( cd "$ROOT/services" && mvn -q clean package -DskipTests )

echo "[2/4] Building Docker images..."
# Use minikube's in-VM Docker daemon only if minikube is actually running;
# otherwise build into the default daemon (e.g. Docker Desktop, whose
# Kubernetes shares it — required for imagePullPolicy: Never).
if command -v minikube >/dev/null 2>&1 && minikube status >/dev/null 2>&1; then
  echo "    (minikube running -> building into its Docker daemon)"
  eval "$(minikube docker-env)"
fi
for svc in movie-service actor-service review-service; do
  jar=$(find "$ROOT/services/$svc/target" -maxdepth 1 -name '*.jar' 2>/dev/null | head -1)
  [ -n "$jar" ] || { echo "ERROR: no JAR in services/$svc/target — Maven build did not produce it." >&2; exit 1; }
  docker build -t "traceflix/$svc:1.0.0" "$ROOT/services/$svc"
done

# Docker Desktop's multi-node Kubernetes (and any kind cluster) runs each node as
# a separate 'kindest/node' container with its own containerd image store, so
# images in the host daemon are invisible to the kubelet (-> ErrImageNeverPull
# with imagePullPolicy: Never). Load the images into every kind node's store.
KIND_NODES=$(docker ps --filter ancestor=kindest/node --format '{{.Names}}' 2>/dev/null || true)
if [ -n "$KIND_NODES" ]; then
  echo "    kind/Docker-Desktop nodes detected -> loading images into node stores:"
  for node in $KIND_NODES; do
    for svc in movie-service actor-service review-service; do
      echo "      $svc -> $node"
      docker save "traceflix/$svc:1.0.0" | docker exec -i "$node" ctr -n k8s.io images import - >/dev/null
    done
  done
fi

echo "[3/4] Deploying observability stack + app services + gap fixes..."
kubectl apply -f "$ROOT/observability/on-demand-observability.yaml"
kubectl apply -f "$ROOT/aiops/k8s/load-generator-fixed.yaml"
kubectl apply -f "$ROOT/aiops/k8s/victoriametrics.yaml"

echo "[4/4] Installing Chaos Mesh (fault engine)..."
bash "$ROOT/aiops/scripts/install_chaos_mesh.sh" || true

echo
echo "Done. Next:"
echo "  kubectl get pods -n on-demand-observability -w     # wait for Running"
echo "  cd aiops && ./scripts/run_live_experiment.sh 30    # run the C1-C4 experiment"
