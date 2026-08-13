#!/usr/bin/env python3
"""Run a KairosBench campaign against this application.

TraceFlix runs on the local Kubernetes cluster, so a campaign needs three
things that the harness deliberately does not know how to do: port-forwards
into the namespace, a check that Chaos Mesh is present to inject with, and the
live-mode assertion that stops simulator output being recorded as measurement.
This script does those and then hands over to the harness.

    python scripts/kb_campaign.py                     # the interactive matrix
    python scripts/kb_campaign.py --campaign interactive-smoke
    python scripts/kb_campaign.py --check             # preconditions only
    python scripts/kb_campaign.py --analyse           # re-read existing runs

WHAT IT DOES NOT DO
-------------------
It does not deploy the application: `make run-platform` does that, and a
campaign measures what is already running. It does not build images. It does
not decide anything about the experiment -- the faults, the schedule and the
repetitions live in the harness, in `campaigns/interactive-detection-matrix.yaml`
and `faults/mappings/traceflix-platform.yaml`, because they are properties of
the experiment rather than of this repository.

THE MEASUREMENT CONFIGURATION IT APPLIES
----------------------------------------
The OpenTelemetry Java agent exports metrics every 60 s by default. Every
indicator in the interactive profile is a rate over a one-minute window on top
of that, so an unmodified deployment cannot resolve a time-to-detect below
about two minutes, and a matrix cell measured that way would report the export
interval rather than the fault. `--set-export-interval` (on by default) sets
the gateway's interval to 5 s for the campaign and restores it afterwards. It
is applied to every phase of every run, so it cancels in the within-run
comparison; it is recorded in the run's provenance either way.

Stdlib only, so it runs in any interpreter without installing anything.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
HARNESS = Path(os.environ.get("KB_HOME", REPO.parent / "kairosbench"))
NAMESPACE = "on-demand-observability"

# local port -> (kubernetes service, service port)
FORWARDS = {
    8080: ("gateway-service", 8080),
    9090: ("prometheus", 9090),
    3200: ("tempo", 3200),
}

ENTRY = "http://localhost:8080/api/browse?userId=1"
PROM = "http://localhost:9090"
EXPORT_INTERVAL_MS = "5000"


# ---------------------------------------------------------------------------
# port forwards
# ---------------------------------------------------------------------------

class Forwarder:
    """Keeps `kubectl port-forward` alive for the length of a campaign.

    A forward that dies silently three hours into a run takes the run with it,
    and the samples it leaves behind look like an application that stopped
    answering rather than a tunnel that closed. Each one is supervised and
    restarted; the probe treats the gap as a failed scrape and drops the
    window, which is the right reading of an interrupted measurement.
    """

    def __init__(self, namespace: str) -> None:
        self.namespace = namespace
        self.stop = threading.Event()
        self.threads: list[threading.Thread] = []
        self.restarts: dict[int, int] = {}
        self.adopted: list[int] = []

    @staticmethod
    def _port_taken(local: int) -> bool:
        """Is something already listening here?

        A forward that cannot bind exits immediately, and a supervisor that
        only knows how to restart it will do so for the length of the
        campaign -- thousands of times, while a tunnel somebody else started
        quietly carries the traffic. That is survivable but it is not
        measurable: nothing in the run records which tunnel served it. So an
        occupied port is adopted deliberately and reported, or it is a failure.
        """
        import socket
        with socket.socket() as sock:
            sock.settimeout(1.0)
            return sock.connect_ex(("127.0.0.1", local)) == 0

    def _run(self, local: int, service: str, remote: int) -> None:
        if self._port_taken(local):
            self.adopted.append(local)
            return
        while not self.stop.is_set():
            proc = subprocess.Popen(
                ["kubectl", "port-forward", "-n", self.namespace,
                 f"svc/{service}", f"{local}:{remote}"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            while not self.stop.is_set() and proc.poll() is None:
                time.sleep(1)
            if proc.poll() is None:
                proc.terminate()
                return
            if not self.stop.is_set():
                self.restarts[local] = self.restarts.get(local, 0) + 1
                time.sleep(2)

    def start(self) -> None:
        for local, (service, remote) in FORWARDS.items():
            t = threading.Thread(target=self._run, args=(local, service, remote),
                                 daemon=True)
            t.start()
            self.threads.append(t)

    def wait_ready(self, timeout_s: float = 90.0) -> bool:
        deadline = time.time() + timeout_s
        while time.time() < deadline:
            if http_ok(ENTRY) and http_ok(f"{PROM}/-/ready"):
                return True
            time.sleep(2)
        return False

    def close(self) -> None:
        self.stop.set()


def http_ok(url: str, timeout: float = 5.0) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return r.status < 300
    except Exception:
        return False


# ---------------------------------------------------------------------------
# preconditions
# ---------------------------------------------------------------------------

def sh(*args: str, timeout: float = 60.0) -> tuple[int, str]:
    p = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def preconditions() -> list[str]:
    """Everything that must hold before a run is worth starting."""
    problems: list[str] = []

    rc, out = sh("kubectl", "get", "ns", NAMESPACE)
    if rc != 0:
        problems.append(f"namespace {NAMESPACE} not found -- deploy with "
                        "`make run-platform`")
        return problems

    rc, out = sh("kubectl", "get", "pods", "-n", NAMESPACE, "-o", "json")
    if rc == 0:
        not_ready = []
        for item in json.loads(out).get("items", []):
            phase = item.get("status", {}).get("phase")
            if phase not in ("Running", "Succeeded"):
                not_ready.append(f"{item['metadata']['name']}={phase}")
        if not_ready:
            problems.append("pods not running: " + ", ".join(not_ready[:6]))

    rc, _ = sh("kubectl", "get", "crd", "networkchaos.chaos-mesh.org")
    if rc != 0:
        problems.append("Chaos Mesh is not installed; the fault mapping for this "
                        "application has no other mechanism")

    if os.environ.get("TF_LIVE") != "1":
        problems.append("TF_LIVE=1 is not set. The harness refuses to record a "
                        "run without it, because this repository's numbers have "
                        "previously come from the _synth simulator")

    if not (HARNESS / "campaigns").is_dir():
        problems.append(f"harness not found at {HARNESS}; set KB_HOME")

    return problems


# ---------------------------------------------------------------------------
# measurement configuration
# ---------------------------------------------------------------------------

def get_export_interval() -> str | None:
    rc, out = sh("kubectl", "get", "deploy", "gateway-service", "-n", NAMESPACE,
                 "-o", "jsonpath={.spec.template.spec.containers[0].env}")
    if rc != 0:
        return None
    try:
        for env in json.loads(out or "[]"):
            if env.get("name") == "OTEL_METRIC_EXPORT_INTERVAL":
                return env.get("value")
    except ValueError:
        pass
    return None


def set_export_interval(value: str | None) -> None:
    """Set, or with None remove, the gateway's metric export interval."""
    arg = (f"OTEL_METRIC_EXPORT_INTERVAL={value}" if value
           else "OTEL_METRIC_EXPORT_INTERVAL-")
    rc, out = sh("kubectl", "set", "env", "deployment/gateway-service",
                 "-n", NAMESPACE, arg)
    if rc != 0:
        print(f"  ! could not set export interval: {out.strip()}", file=sys.stderr)
        return
    sh("kubectl", "rollout", "status", "deployment/gateway-service",
       "-n", NAMESPACE, "--timeout=180s", timeout=200)


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--campaign", default="interactive-detection-matrix")
    ap.add_argument("--check", action="store_true",
                    help="verify preconditions and exit")
    ap.add_argument("--analyse", action="store_true",
                    help="collapse existing runs into cells and exit")
    ap.add_argument("--reps", type=int, default=None)
    ap.add_argument("--only", default="")
    ap.add_argument("--into", default="")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--no-set-export-interval", action="store_true",
                    help="leave the gateway's telemetry configuration alone; "
                         "time-to-detect is then bounded by the 60 s default")
    args = ap.parse_args()

    kb = [sys.executable, "-m", "kairosbench.cli"]
    env = {**os.environ, "PYTHONPATH": str(HARNESS / "src")}

    if args.analyse:
        return subprocess.run(kb + ["analyse", args.campaign],
                              cwd=str(HARNESS), env=env).returncode

    print("preconditions")
    problems = preconditions()
    for p in problems:
        print(f"  FAIL {p}")
    if problems:
        print("\nnot starting.", file=sys.stderr)
        return 1
    print("  ok   namespace, pods, Chaos Mesh, live-mode gate, harness")
    if args.check:
        return 0

    original = get_export_interval()
    changed = False
    forwarder = Forwarder(NAMESPACE)
    try:
        if not args.no_set_export_interval and original != EXPORT_INTERVAL_MS:
            print(f"measurement configuration: gateway metric export interval "
                  f"{original or '60000 (default)'} -> {EXPORT_INTERVAL_MS} ms")
            set_export_interval(EXPORT_INTERVAL_MS)
            changed = True

        print("port-forwards: " + ", ".join(
            f"{svc}:{remote}->localhost:{local}"
            for local, (svc, remote) in FORWARDS.items()))
        forwarder.start()
        if not forwarder.wait_ready():
            print("port-forwards did not come up", file=sys.stderr)
            return 1

        cmd = kb + ["run", args.campaign, "--no-infra"]
        if args.reps is not None:
            cmd += ["--reps", str(args.reps)]
        if args.only:
            cmd += ["--only", args.only]
        if args.into:
            cmd += ["--into", args.into]
        if args.dry_run:
            cmd += ["--dry-run"]
        print(f"$ {' '.join(cmd[2:])}\n")
        rc = subprocess.run(cmd, cwd=str(HARNESS), env=env).returncode

        if forwarder.restarts:
            print(f"\nport-forward restarts during the run: {forwarder.restarts}")
        return rc
    finally:
        forwarder.close()
        if changed:
            print(f"restoring gateway metric export interval to "
                  f"{original or 'the default'}")
            set_export_interval(original)


if __name__ == "__main__":
    raise SystemExit(main())
