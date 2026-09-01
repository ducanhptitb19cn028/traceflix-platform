"""
Ground truth from the cluster: which service is under which fault, right now.

The synthetic pipeline knows the label because it invented the fault. Against the
deployed mesh nothing invents anything, so the label has to be *read* from the
thing that actually caused it -- the live Chaos Mesh custom resources. This is
the counterpart of the labels CSV faults/inject.py writes after the fact: same
taxonomy, but answerable while the episode is still running, which is what a live
detector needs.

A CR is only counted while the fault is genuinely in the pod. Chaos Mesh keeps
the resource around through its whole lifecycle, so `desiredPhase == Run` alone
would include an experiment that has been created but whose stressor has not been
injected yet, and would keep counting one that has already recovered. Both would
put a fault label on telemetry that carries no fault -- the exact mislabelling
the offline path avoids by trimming a margin off each end of an episode.

Degrades to "no faults" if the cluster is unreachable, matching
collect_events_live: a detector that cannot read ground truth should report
everything as normal, not crash the page.
"""
from __future__ import annotations

# Chaos Mesh resource plurals we drive from faults/inject.py and
# faults/run_episodes.py, and how each maps back onto the fault taxonomy in
# ml.configs.FAULT_TYPES. The kind alone is not enough: StressChaos is
# cpu_saturation or memory_leak depending on the stressor, and NetworkChaos is
# latency_spike or network_partition depending on the action.
_PLURALS = ("stresschaos", "networkchaos", "podchaos")

GROUP = "chaos-mesh.org"
VERSION = "v1alpha1"


def _fault_of(kind: str, spec: dict) -> str | None:
    """The taxonomy name for one CR, or None if it is not one of ours."""
    if kind == "StressChaos":
        stressors = spec.get("stressors") or {}
        if "cpu" in stressors:
            return "cpu_saturation"
        if "memory" in stressors:
            return "memory_leak"
        return None
    if kind == "NetworkChaos":
        return {"delay": "latency_spike",
                "loss": "network_partition"}.get(spec.get("action"))
    if kind == "PodChaos":
        return "pod_kill" if spec.get("action") == "pod-kill" else None
    return None


def _injected(status: dict) -> bool:
    """True while the stressor is in the pod, rather than merely scheduled.

    `desiredPhase` is what the controller was *asked* for; the conditions are
    what it achieved. Requiring AllInjected and not-AllRecovered is what keeps
    the label aligned with the telemetry rather than with the manifest.
    """
    if (status.get("experiment") or {}).get("desiredPhase") != "Run":
        return False
    cond = {c.get("type"): c.get("status") == "True"
            for c in status.get("conditions") or []}
    return cond.get("AllInjected", False) and not cond.get("AllRecovered", True)


def active_faults_checked(namespace: str) -> tuple[bool, dict[str, str]]:
    """(could the CRs be read, service -> fault) for `namespace`.

    Both halves matter and they are not the same question. An empty mapping means
    "nothing is injected" when the first element is True and "I cannot see what is
    injected" when it is False -- and only the first is a ground truth. Collapsing
    them, as returning a bare dict does, is how a page ends up scoring every
    window as normal and reporting a confident F1 over labels it never read.

    Services absent from the mapping are normal. A service targeted by two
    overlapping experiments keeps the first fault found; the campaigns this
    drives inject one at a time, and inventing a compound label for a case that
    does not arise would be worse than the arbitrary choice.
    """
    try:
        from kubernetes import client, config  # type: ignore

        try:
            config.load_incluster_config()
        except Exception:
            config.load_kube_config()
        api = client.CustomObjectsApi()
    except Exception:
        return False, {}

    ok = False
    out: dict[str, str] = {}
    for plural in _PLURALS:
        try:
            items = api.list_namespaced_custom_object(
                GROUP, VERSION, namespace, plural).get("items", [])
        except Exception:
            continue        # one kind may be absent; another may still answer
        ok = True
        for it in items:
            spec = it.get("spec") or {}
            fault = _fault_of(it.get("kind", ""), spec)
            if fault is None or not _injected(it.get("status") or {}):
                continue
            svc = ((spec.get("selector") or {})
                   .get("labelSelectors") or {}).get("app")
            if svc and svc not in out:
                out[svc] = fault
    return ok, out


def active_faults(namespace: str) -> dict[str, str]:
    """The mapping alone, for callers that already know the CRs are readable."""
    return active_faults_checked(namespace)[1]


def chaos_reachable(namespace: str) -> tuple[bool, str]:
    """Whether ground truth can be read at all, and why not if it cannot.

    The live page has to distinguish "no fault is running" from "I cannot see
    whether a fault is running": the first is a real label, the second makes
    every score meaningless and has to be said out loud.
    """
    try:
        from kubernetes import client, config  # type: ignore
    except Exception:
        return False, "the kubernetes python client is not installed"
    try:
        try:
            config.load_incluster_config()
        except Exception:
            config.load_kube_config()
        client.CustomObjectsApi().list_namespaced_custom_object(
            GROUP, VERSION, namespace, "stresschaos")
        return True, ""
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"[:200]
