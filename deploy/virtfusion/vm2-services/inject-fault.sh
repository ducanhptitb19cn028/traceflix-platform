#!/usr/bin/env bash
# Fault injection for the compose mesh (the Pumba analog of aiops/faults/run_episodes.py).
# Targets ANY of the 9 services by container name -- including the new generic nodes
# (gateway/user/search/recommendation/auth/catalog) -- and records a ground-truth
# label row identical to the k8s harness, so the same C1-C4 analysis joins against it.
#
#   ./inject-fault.sh <service> <fault> [duration_s] [labels_csv]
#   ./inject-fault.sh catalog-service cpu_saturation 120
#   ./inject-fault.sh recommendation-service pod_kill
#
# Faults mirror aiops/faults/scenarios/*.yaml. Pumba runs against the Docker socket.
set -euo pipefail

SVC="${1:?service name, e.g. catalog-service}"
FAULT="${2:?fault, one of: cpu_saturation memory_leak latency_spike pod_kill network_partition}"
DUR="${3:-120}"
LABELS="${4:-./data/labels.csv}"
PUMBA="docker run --rm -v /var/run/docker.sock:/var/run/docker.sock gaiaadm/pumba"
TC_IMAGE="gaiadocker/iproute2"
RE="re2:${SVC}"

start=$(date +%s)
echo "[inject] $FAULT -> $SVC for ${DUR}s"
case "$FAULT" in
  latency_spike)
    $PUMBA netem --duration "${DUR}s" --tc-image "$TC_IMAGE" delay --time 300 "$RE" ;;
  network_partition)
    $PUMBA netem --duration "${DUR}s" --tc-image "$TC_IMAGE" loss --percent 100 "$RE" ;;
  cpu_saturation)
    $PUMBA stress --duration "${DUR}s" --stressors "--cpu 4" "$RE" ;;
  memory_leak)
    $PUMBA stress --duration "${DUR}s" --stressors "--vm 2 --vm-bytes 256M" "$RE" ;;
  pod_kill)
    $PUMBA kill --signal SIGKILL "$RE"; sleep "$DUR" ;;
  *) echo "unknown fault: $FAULT" >&2; exit 2 ;;
esac
end=$(date +%s)

mkdir -p "$(dirname "$LABELS")"
[ -f "$LABELS" ] || echo "fault,root_cause,start_ts,end_ts" > "$LABELS"
echo "${FAULT},${SVC},${start}.000,${end}.000" >> "$LABELS"
echo "[inject] cleared; labelled -> $LABELS"
