#!/usr/bin/env python3
"""Plan or execute one targeted, PDB-aware Thanos Receive staging eviction."""

from __future__ import annotations

import argparse
import json
import subprocess
import time
from typing import Any
from urllib.parse import quote


NAMESPACE = "thermoform-observability"
RECEIVE_SELECTOR = "app.kubernetes.io/name=thanos,app.kubernetes.io/component=receive"
EBS_CSI_DRIVER = "ebs.csi.aws.com"
ZONE_LABEL = "topology.kubernetes.io/zone"


class DrillError(ValueError):
    """Raised when the staging topology or explicit confirmation is unsafe."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise DrillError(message)


def _ready(condition_owner: dict[str, Any]) -> bool:
    return any(
        item.get("type") == "Ready" and item.get("status") == "True"
        for item in condition_owner.get("status", {}).get("conditions", [])
    )


def _schedulable_linux_nodes(nodes: dict[str, Any]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for node in nodes.get("items", []):
        labels = node.get("metadata", {}).get("labels", {})
        blocking_taint = any(
            taint.get("effect") in {"NoSchedule", "NoExecute"}
            for taint in node.get("spec", {}).get("taints", [])
        )
        if (
            _ready(node)
            and not node.get("spec", {}).get("unschedulable", False)
            and not blocking_taint
            and labels.get("kubernetes.io/os") == "linux"
            and labels.get(ZONE_LABEL)
        ):
            result[str(node["metadata"]["name"])] = node
    return result


def select_target(
    pods: dict[str, Any],
    nodes: dict[str, Any],
    csi_nodes: dict[str, Any],
    requested_pod: str | None = None,
) -> dict[str, str]:
    receive_pods = [
        pod
        for pod in pods.get("items", [])
        if _ready(pod)
        and not pod.get("metadata", {}).get("deletionTimestamp")
        and pod.get("spec", {}).get("nodeName")
    ]
    _require(len(receive_pods) == 3, "exactly three Ready Receive pods are required")
    ready_nodes = _schedulable_linux_nodes(nodes)
    placements: dict[str, str] = {}
    for pod in receive_pods:
        node_name = str(pod["spec"]["nodeName"])
        _require(node_name in ready_nodes, f"Receive pod uses an ineligible node: {node_name}")
        placements[node_name] = str(ready_nodes[node_name]["metadata"]["labels"][ZONE_LABEL])
    _require(len(placements) == 3, "Receive pods must occupy three different nodes")
    _require(len(set(placements.values())) == 3, "Receive pods must occupy three different zones")

    ordered = sorted(receive_pods, key=lambda item: str(item["metadata"]["name"]))
    if requested_pod:
        matching = [pod for pod in ordered if pod["metadata"]["name"] == requested_pod]
        _require(len(matching) == 1, "requested Receive pod is not Ready")
        target = matching[0]
    else:
        target = ordered[0]
    target_node = str(target["spec"]["nodeName"])
    target_zone = placements[target_node]

    csi_registered = {
        str(item.get("metadata", {}).get("name", ""))
        for item in csi_nodes.get("items", [])
        if any(
            driver.get("name") == EBS_CSI_DRIVER
            for driver in item.get("spec", {}).get("drivers", [])
        )
    }
    spare_nodes = sorted(
        name
        for name, node in ready_nodes.items()
        if name != target_node
        and name not in placements
        and node["metadata"]["labels"][ZONE_LABEL] == target_zone
        and name in csi_registered
    )
    _require(spare_nodes, f"zone {target_zone} needs a schedulable EBS CSI spare node")
    return {
        "pod": str(target["metadata"]["name"]),
        "pod_uid": str(target["metadata"]["uid"]),
        "node": target_node,
        "zone": target_zone,
        "spare_node": spare_nodes[0],
    }


def validate_confirmation(
    *,
    execute: bool,
    context: str,
    node: str,
    confirm_context: str | None,
    confirm_node: str | None,
) -> None:
    if not execute:
        return
    _require(confirm_context == context, "--confirm-context must exactly match --context")
    _require(confirm_node == node, "--confirm-node must exactly match the selected node")


def validate_pdb(pdb: dict[str, Any]) -> int:
    _require(pdb.get("spec", {}).get("minAvailable") == 2, "Receive PDB minAvailable must be two")
    allowed = int(pdb.get("status", {}).get("disruptionsAllowed", 0))
    _require(allowed >= 1, "Receive PDB currently allows no voluntary disruption")
    _require(
        int(pdb.get("status", {}).get("currentHealthy", 0)) >= 3,
        "Receive PDB does not report three healthy replicas",
    )
    return allowed


def _kubectl(context: str, *arguments: str, stdin: str | None = None) -> str:
    command = ["kubectl", "--context", context, *arguments]
    try:
        return subprocess.run(
            command,
            input=stdin,
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        ).stdout
    except subprocess.TimeoutExpired as exc:
        raise DrillError(f"kubectl timed out: {' '.join(command)}") from exc
    except subprocess.CalledProcessError as exc:
        raise DrillError(exc.stderr.strip() or f"kubectl failed: {' '.join(command)}") from exc


def _kubectl_json(context: str, *arguments: str) -> dict[str, Any]:
    try:
        return json.loads(_kubectl(context, *arguments, "-o", "json"))
    except json.JSONDecodeError as exc:
        raise DrillError("kubectl returned invalid JSON") from exc


def inspect(context: str, namespace: str, requested_pod: str | None) -> dict[str, str]:
    pods = _kubectl_json(
        context, "-n", namespace, "get", "pods", "-l", RECEIVE_SELECTOR
    )
    nodes = _kubectl_json(context, "get", "nodes")
    csi_nodes = _kubectl_json(context, "get", "csinodes")
    pdb = _kubectl_json(context, "-n", namespace, "get", "pdb", "thanos-receive")
    target = select_target(pods, nodes, csi_nodes, requested_pod)
    target["pdb_disruptions_allowed"] = str(validate_pdb(pdb))
    return target


def _wait_for_replacement(
    context: str,
    namespace: str,
    target: dict[str, str],
    timeout_seconds: int,
) -> dict[str, str]:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        pods = _kubectl_json(
            context, "-n", namespace, "get", "pods", "-l", RECEIVE_SELECTOR
        )
        matches = [
            pod
            for pod in pods.get("items", [])
            if pod.get("metadata", {}).get("name") == target["pod"]
            and pod.get("metadata", {}).get("uid") != target["pod_uid"]
            and _ready(pod)
        ]
        if matches:
            replacement_node = str(matches[0]["spec"]["nodeName"])
            nodes = _kubectl_json(context, "get", "node", replacement_node)
            replacement_zone = str(nodes["metadata"]["labels"][ZONE_LABEL])
            _require(replacement_node != target["node"], "replacement returned to cordoned node")
            _require(replacement_zone == target["zone"], "zonal EBS replacement changed zones")
            pdb = _kubectl_json(
                context, "-n", namespace, "get", "pdb", "thanos-receive"
            )
            if int(pdb.get("status", {}).get("currentHealthy", 0)) >= 3:
                return {
                    "replacement_node": replacement_node,
                    "replacement_zone": replacement_zone,
                }
        time.sleep(5)
    raise DrillError("replacement Receive pod did not become Ready before timeout")


def execute_eviction(
    context: str,
    namespace: str,
    target: dict[str, str],
    timeout_seconds: int,
) -> dict[str, str]:
    _kubectl(context, "cordon", target["node"])
    try:
        eviction = json.dumps(
            {
                "apiVersion": "policy/v1",
                "kind": "Eviction",
                "metadata": {"name": target["pod"], "namespace": namespace},
            }
        )
        path = (
            f"/api/v1/namespaces/{quote(namespace, safe='')}/pods/"
            f"{quote(target['pod'], safe='')}/eviction"
        )
        _kubectl(context, "create", "--raw", path, "-f", "-", stdin=eviction)
        return _wait_for_replacement(context, namespace, target, timeout_seconds)
    finally:
        _kubectl(context, "uncordon", target["node"])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--context", required=True)
    parser.add_argument("--namespace", default=NAMESPACE)
    parser.add_argument("--pod")
    parser.add_argument("--timeout-seconds", type=int, default=600)
    parser.add_argument("--execute-eviction", action="store_true")
    parser.add_argument("--confirm-context")
    parser.add_argument("--confirm-node")
    args = parser.parse_args()
    try:
        _require(bool(args.context.strip()), "an explicit kubectl context is required")
        _require(60 <= args.timeout_seconds <= 1800, "timeout must be between 60 and 1800 seconds")
        target = inspect(args.context, args.namespace, args.pod)
        validate_confirmation(
            execute=args.execute_eviction,
            context=args.context,
            node=target["node"],
            confirm_context=args.confirm_context,
            confirm_node=args.confirm_node,
        )
        result: dict[str, Any] = {
            "context": args.context,
            "mode": "execute" if args.execute_eviction else "plan",
            "status": "ready" if not args.execute_eviction else "running",
            "target": target,
        }
        if args.execute_eviction:
            result["replacement"] = execute_eviction(
                args.context, args.namespace, target, args.timeout_seconds
            )
            result["status"] = "passed"
        print(json.dumps(result, indent=2, sort_keys=True))
    except DrillError as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
