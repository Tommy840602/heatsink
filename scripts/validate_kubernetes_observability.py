#!/usr/bin/env python3
"""Validate the rendered production Thanos Kubernetes topology contract."""

from __future__ import annotations

import argparse
import re
from pathlib import Path


class ContractError(ValueError):
    """Raised when a rendered manifest violates the production contract."""


def _documents(manifest: str) -> dict[tuple[str, str], str]:
    documents: dict[tuple[str, str], str] = {}
    for raw_document in re.split(r"^---\s*$", manifest, flags=re.MULTILINE):
        kind_match = re.search(r"^kind:\s*([^\s]+)\s*$", raw_document, re.MULTILINE)
        metadata_match = re.search(
            r"^metadata:\s*\n(?:^[ \t]+.*\n)*?^[ \t]+name:\s*([^\s]+)\s*$",
            raw_document,
            re.MULTILINE,
        )
        if kind_match and metadata_match:
            key = (kind_match.group(1), metadata_match.group(1))
            if key in documents:
                raise ContractError(f"duplicate resource: {key[0]}/{key[1]}")
            documents[key] = raw_document
    return documents


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ContractError(message)


def _resource(documents: dict[tuple[str, str], str], kind: str, name: str) -> str:
    key = (kind, name)
    _require(key in documents, f"missing resource: {kind}/{name}")
    return documents[key]


def validate(manifest: str) -> None:
    documents = _documents(manifest)
    eks_storage_key = ("StorageClass", "thermoform-ebs-gp3")
    self_hosted_secret_keys = {
        ("SecretProviderClass", "thanos-receive-object-store"),
        ("SecretProviderClass", "thanos-store-object-store"),
        ("SecretProviderClass", "thanos-compact-object-store"),
    }
    self_hosted = self_hosted_secret_keys.issubset(documents)
    expected_resources = 27 if self_hosted else 25 if eks_storage_key in documents else 24
    _require(
        len(documents) == expected_resources,
        f"expected {expected_resources} resources, found {len(documents)}",
    )

    namespace = _resource(documents, "Namespace", "thermoform-observability")
    for mode in ("enforce", "audit", "warn"):
        _require(
            f"pod-security.kubernetes.io/{mode}: restricted" in namespace,
            f"namespace must use restricted Pod Security {mode}",
        )

    service_accounts = {
        name: _resource(documents, "ServiceAccount", name)
        for name in ("thanos-receive", "thanos-store", "thanos-query", "thanos-compact")
    }
    _require(
        "automountServiceAccountToken: false" in service_accounts["thanos-query"],
        "Query must not receive an API token",
    )

    if eks_storage_key in documents:
        role_arns: list[str] = []
        for name in ("thanos-receive", "thanos-store", "thanos-compact"):
            account = service_accounts[name]
            role_match = re.search(
                r"eks\.amazonaws\.com/role-arn:\s*"
                r"(arn:(?:aws|aws-us-gov|aws-cn):iam::[0-9]{12}:role/"
                r"[A-Za-z0-9+=,.@_/-]+)",
                account,
            )
            _require(role_match is not None, f"{name} must have a complete IRSA role ARN")
            role_arns.append(role_match.group(1))
            _require(
                'eks.amazonaws.com/sts-regional-endpoints: "true"' in account,
                f"{name} must use regional STS",
            )
        _require(len(set(role_arns)) == 3, "EKS bucket clients must use distinct IAM roles")
        _require(
            len({role.split(":", 2)[1] for role in role_arns}) == 1,
            "EKS bucket clients must use one AWS partition",
        )
        _require(
            "eks.amazonaws.com/role-arn:" not in service_accounts["thanos-query"],
            "Query must not have an IRSA role",
        )

    if self_hosted:
        expected_roles = {
            "thanos-receive": "kv/data/thanos/receive",
            "thanos-store": "kv/data/thanos/store",
            "thanos-compact": "kv/data/thanos/compact",
        }
        for name, secret_path in expected_roles.items():
            provider = _resource(documents, "SecretProviderClass", f"{name}-object-store")
            for requirement in (
                "provider: openbao",
                f"roleName: {name}",
                f"secretPath: {secret_path}",
                "secretKey: object-store.yml",
                "filePermission: 0400",
            ):
                _require(requirement in provider, f"unsafe {name} OpenBao secret contract")

    receive = _resource(documents, "StatefulSet", "thanos-receive")
    store = _resource(documents, "StatefulSet", "thanos-store")
    query = _resource(documents, "Deployment", "thanos-query")
    compact = _resource(documents, "StatefulSet", "thanos-compact")

    _require("replicas: 3" in receive, "Receive must have exactly three replicas")
    _require(
        "--receive.replication-factor=3" in receive,
        "Receive replication factor must remain three",
    )
    _require("--receive.hashrings-file=" in receive, "Receive must use the fixed hashring")
    _require("minDomains: 3" in receive, "Receive must require three zones")
    _require(
        "topologyKey: topology.kubernetes.io/zone" in receive
        and "topologyKey: kubernetes.io/hostname" in receive
        and receive.count("whenUnsatisfiable: DoNotSchedule") >= 2,
        "Receive must strictly spread across zones and nodes",
    )
    _require("replicas: 2" in store, "Store Gateway must have two replicas")
    _require("replicas: 2" in query, "Query must have two replicas")
    _require("replicas: 1" in compact, "Compactor must remain a singleton")

    if eks_storage_key in documents:
        _require(
            "storageClassName: thermoform-ebs-gp3" in receive,
            "Receive must use the encrypted EBS StorageClass",
        )
        _require(
            "storageClassName: thermoform-ebs-gp3" in compact,
            "Compactor must use the encrypted EBS StorageClass",
        )
        storage_class = documents[eks_storage_key]
        for requirement in (
            "provisioner: ebs.csi.aws.com",
            "type: gp3",
            'encrypted: "true"',
            "reclaimPolicy: Retain",
            "allowVolumeExpansion: true",
            "volumeBindingMode: WaitForFirstConsumer",
        ):
            _require(requirement in storage_class, f"unsafe EBS StorageClass: {requirement}")

    if self_hosted:
        for name, workload in {
            "Receive": receive,
            "Store Gateway": store,
            "Compactor": compact,
        }.items():
            _require(
                "driver: secrets-store.csi.k8s.io" in workload,
                f"{name} must mount its OpenBao CSI secret",
            )
        for workload in (receive, compact):
            _require(
                "storageClassName: thermoform-ceph-block" in workload,
                "persistent Thanos state must use the retained Ceph block class",
            )

    for name, workload in {
        "Receive": receive,
        "Store Gateway": store,
        "Compactor": compact,
    }.items():
        if not self_hosted:
            _require(
                "secretName: thermoform-thanos-object-store" in workload,
                f"{name} must use the shared object-store Secret",
            )
    _require(
        "secretName: thermoform-thanos-object-store" not in query,
        "Query must not receive object-store credentials",
    )

    configuration = _resource(documents, "ConfigMap", "thanos-receive-hashring")
    for ordinal in range(3):
        endpoint = (
            f"thanos-receive-{ordinal}.thanos-receive-headless."
            "thermoform-observability.svc.cluster.local:10901"
        )
        _require(endpoint in configuration, f"hashring is missing Receive ordinal {ordinal}")

    endpoints = _resource(documents, "ConfigMap", "thanos-query-endpoints")
    for ordinal in range(3):
        _require(f"thanos-receive-{ordinal}." in endpoints, "Query must discover all Receive pods")
    for ordinal in range(2):
        _require(f"thanos-store-{ordinal}." in endpoints, "Query must discover both Store pods")

    for workload in (receive, store, query, compact):
        _require(
            "image: quay.io/thanos/thanos:v0.42.4" in workload,
            "every Thanos workload must use the pinned image",
        )
        _require("runAsNonRoot: true" in workload, "every workload must run as non-root")
        _require(
            "readOnlyRootFilesystem: true" in workload,
            "every workload must use a read-only root filesystem",
        )

    for name, minimum in {
        "thanos-receive": 2,
        "thanos-store": 1,
        "thanos-query": 1,
    }.items():
        budget = _resource(documents, "PodDisruptionBudget", name)
        _require(f"minAvailable: {minimum}" in budget, f"invalid PDB for {name}")

    _resource(documents, "NetworkPolicy", "default-deny-ingress")
    _resource(documents, "NetworkPolicy", "allow-observability-internal")
    write_policy = _resource(documents, "NetworkPolicy", "allow-metrics-writers")
    read_policy = _resource(documents, "NetworkPolicy", "allow-metrics-readers-and-scrapers")
    _require("thermoform.io/metrics-write: \"true\"" in write_policy, "missing write namespace selector")
    _require("thermoform.io/metrics-read: \"true\"" in read_policy, "missing read namespace selector")

    lowered = manifest.lower()
    _require(
        re.search(r"(?m)^kind:\s*secret\s*$", lowered) is None,
        "forbidden manifest content: kind: secret",
    )
    for forbidden in (
        "access_key:",
        "secret_key:",
        "session_token:",
        "type: loadbalancer",
        "type: nodeport",
        "hostnetwork: true",
        "hostpath:",
        "privileged: true",
        "replace_with_",
        "000000000000",
    ):
        _require(forbidden not in lowered, f"forbidden manifest content: {forbidden}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path, help="kubectl kustomize output")
    args = parser.parse_args()
    try:
        validate(args.manifest.read_text(encoding="utf-8"))
    except (OSError, ContractError) as exc:
        parser.error(str(exc))
    resource_count = len(_documents(args.manifest.read_text(encoding="utf-8")))
    print(f"Kubernetes observability contract is valid ({resource_count} resources).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
