#!/usr/bin/env bash
# Build and push the TraceFlix images (nine services + the AIOps engine) for the
# Rancher GPU k8s deploy.  Linux / macOS / Git Bash.
#
#   ./rancher/build-push.sh <registry> [tag]
#   ./rancher/build-push.sh registry.example.com/traceflix
#   SKIP_BUILD=1 NO_PUSH=1 ./rancher/build-push.sh myreg/traceflix
#
# Env toggles: SKIP_BUILD=1 (reuse jars), SERVICES_ONLY=1 (skip aiops), NO_PUSH=1.
set -euo pipefail

REG="${1:-${REG:-}}"
TAG="${2:-1.0.0}"
AIOPS_TAG="${AIOPS_TAG:-gpu}"
if [ -z "$REG" ]; then
  echo "usage: $0 <registry> [tag]   (or set REG=...)" >&2
  exit 2
fi

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

SERVICES="movie actor review gateway user search recommendation auth catalog"

if [ "${SKIP_BUILD:-0}" != "1" ]; then
  echo "==> mvn package (nine services)"
  ( cd services && mvn clean package -DskipTests )
fi

for s in $SERVICES; do
  img="$REG/$s-service:$TAG"
  echo "==> $img"
  docker build -t "$img" "services/$s-service"
  [ "${NO_PUSH:-0}" = "1" ] || docker push "$img"
done

if [ "${SERVICES_ONLY:-0}" != "1" ]; then
  ai="$REG/traceflix-aiops:$AIOPS_TAG"
  echo "==> $ai"
  docker build -f rancher/aiops.Dockerfile -t "$ai" .
  [ "${NO_PUSH:-0}" = "1" ] || docker push "$ai"
fi

echo "Done. Use:  --set image.registry=$REG"
