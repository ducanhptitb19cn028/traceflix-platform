#!/usr/bin/env bash
# Install Chaos Mesh into the cluster (required for fault injection on the 3 services).
set -euo pipefail
helm repo add chaos-mesh https://charts.chaos-mesh.org
helm repo update
kubectl create ns chaos-mesh --dry-run=client -o yaml | kubectl apply -f -
helm install chaos-mesh chaos-mesh/chaos-mesh -n chaos-mesh \
  --set chaosDaemon.runtime=containerd \
  --set chaosDaemon.socketPath=/run/containerd/containerd.sock
echo "Chaos Mesh installed. Verify: kubectl get pods -n chaos-mesh"
