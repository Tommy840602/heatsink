#!/usr/bin/env python3
"""Run read-only EKS prerequisites checks before deploying Thanos."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from typing import Any


EBS_CSI_DRIVER = "ebs.csi.aws.com"
ZONE_LABEL = "topology.kubernetes.io/zone"


class PreflightError(ValueError):
    """Raised when the target cluster cannot satisfy the topology contract."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise PreflightError(message)


def validate_server_version(version: dict[str, Any]) -> str:
    server = version.get("serverVersion") or {}
    major = str(server.get("major", ""))
    minor = str(server.get("minor", ""))
    minor_match = re.match(r"[0-9]+", minor)
    _require(major == "1" and minor_match is not None, "cannot determine Kubernetes server version")
    parsed_minor = int(minor_match.group(0))
    _require(parsed_minor >= 34, "Kubernetes 1.34 or newer is required")
    return f"1.{parsed_minor}"


def eligible_nodes(nodes: dict[str, Any]) -> dict[str, str]:
    eligible: dict[str, str] = {}
    for node in nodes.get("items", []):
        metadata = node.get("metadata", {})
        spec = node.get("spec", {})
        labels = metadata.get("labels", {})
        conditions = node.get("status", {}).get("conditions", [])
        ready = any(
            condition.get("type") == "Ready" and condition.get("status") == "True"
            for condition in conditions
        )
        if spec.get("unschedulable") or not ready:
            continue
        if labels.get("kubernetes.io/os") != "linux":
            continue
        zone = labels.get(ZONE_LABEL)
        if zone:
            eligible[str(metadata.get("name", ""))] = str(zone)
    _require(len(eligible) >= 3, "at least three Ready schedulable Linux nodes are required")
    _require(len(set(eligible.values())) >= 3, "eligible nodes must span at least three zones")
    return eligible


def validate_storage_class(storage_class: dict[str, Any]) -> str:
    metadata = storage_class.get("metadata", {})
    parameters = storage_class.get("parameters", {})
    _require(storage_class.get("provisioner") == EBS_CSI_DRIVER, "StorageClass must use standard EBS CSI")
    _require(parameters.get("type") == "gp3", "StorageClass must provision gp3 volumes")
    _require(str(parameters.get("encrypted", "")).lower() == "true", "StorageClass must encrypt EBS volumes")
    _require(storage_class.get("reclaimPolicy") == "Retain", "StorageClass reclaimPolicy must be Retain")
    _require(storage_class.get("allowVolumeExpansion") is True, "StorageClass must allow volume expansion")
    _require(
        storage_class.get("volumeBindingMode") == "WaitForFirstConsumer",
        "StorageClass must wait for Pod scheduling before binding",
    )
    return str(metadata.get("name", ""))


def validate_csi_nodes(csi_nodes: dict[str, Any], required_nodes: dict[str, str]) -> int:
    registrations: dict[str, set[str]] = {}
    for node in csi_nodes.get("items", []):
        name = str(node.get("metadata", {}).get("name", ""))
        registrations[name] = {
            str(driver.get("name", "")) for driver in node.get("spec", {}).get("drivers", [])
        }
    missing = sorted(
        name for name in required_nodes if EBS_CSI_DRIVER not in registrations.get(name, set())
    )
    _require(not missing, f"EBS CSI is not registered on eligible nodes: {', '.join(missing)}")
    return len(required_nodes)


def _kubectl_json(context: str, *arguments: str) -> dict[str, Any]:
    command = ["kubectl", "--context", context, *arguments, "-o", "json"]
    try:
        result = subprocess.run(
            command,
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
        return json.loads(result.stdout)
    except subprocess.TimeoutExpired as exc:
        raise PreflightError(f"kubectl timed out: {' '.join(command)}") from exc
    except subprocess.CalledProcessError as exc:
        detail = exc.stderr.strip() or "kubectl command failed"
        raise PreflightError(detail) from exc
    except json.JSONDecodeError as exc:
        raise PreflightError("kubectl returned invalid JSON") from exc


def preflight(context: str, storage_class_name: str) -> dict[str, Any]:
    _require(bool(context.strip()), "an explicit kubectl context is required")
    _require(
        re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,252}[A-Za-z0-9]", storage_class_name)
        is not None,
        "invalid StorageClass name",
    )
    version = validate_server_version(_kubectl_json(context, "version"))
    nodes = eligible_nodes(_kubectl_json(context, "get", "nodes"))
    storage_class = validate_storage_class(
        _kubectl_json(context, "get", "storageclass", storage_class_name)
    )
    csi_nodes = validate_csi_nodes(_kubectl_json(context, "get", "csinodes"), nodes)
    return {
        "context": context,
        "kubernetes_version": version,
        "eligible_nodes": len(nodes),
        "zones": sorted(set(nodes.values())),
        "storage_class": storage_class,
        "ebs_csi_nodes": csi_nodes,
        "status": "ready",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--context", required=True, help="exact kubectl context to inspect")
    parser.add_argument("--storage-class", default="thermoform-ebs-gp3")
    args = parser.parse_args()
    try:
        result = preflight(args.context, args.storage_class)
    except PreflightError as exc:
        parser.error(str(exc))
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
