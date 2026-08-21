#!/usr/bin/env python3
"""Validate the fail-closed self-hosted production foundation."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


class ContractError(ValueError):
    """Raised when the self-hosted production contract is weakened."""


LOCKED_COMPONENTS = {
    "rke2": {"version": "v1.36.3+rke2r1"},
    "rook_operator": {
        "version": "v1.20.6",
        "digest": "83a16ee19dd8d621df4159504b33585d80da1bf7ed83c734a9e8d4828c724353",
    },
    "rook_cluster": {
        "version": "v1.20.6",
        "digest": "770a7ff55c773a20c192148f621551f5e201d940b9b5fd87dd7b63e5987381e5",
    },
    "ceph": {"image": "quay.io/ceph/ceph:v20.2.4"},
    "cert_manager": {"version": "v1.21.1"},
    "secrets_store_csi_driver": {"version": "1.6.0"},
    "openbao": {"version": "0.29.2", "app_version": "2.6.2"},
    "keycloak": {"version": "26.7.2"},
    "harbor": {"version": "1.19.2", "app_version": "2.15.2"},
}


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ContractError(message)


def _read(path: Path) -> str:
    _require(path.is_file(), f"missing contract file: {path}")
    return path.read_text(encoding="utf-8")


def _contains_all(text: str, requirements: tuple[str, ...], label: str) -> None:
    for requirement in requirements:
        _require(requirement in text, f"{label} is missing: {requirement}")


def _validate_lock(root: Path) -> None:
    lock = json.loads(_read(root / "infra/self-hosted/stack-lock.json"))
    _require(lock.get("schema_version") == 1, "unsupported self-hosted lock schema")
    _require(lock.get("kubernetes_schema") == "1.36.0", "Kubernetes schema drifted")
    components = lock.get("components")
    _require(isinstance(components, dict), "component lock is missing")
    _require(set(components) == set(LOCKED_COMPONENTS), "component inventory drifted")
    for name, expected in LOCKED_COMPONENTS.items():
        actual = components[name]
        for field, value in expected.items():
            _require(actual.get(field) == value, f"{name} {field} drifted")
        for field, value in actual.items():
            if field in {"repository", "release", "operator_source"}:
                _require(str(value).startswith("https://"), f"{name} source must use HTTPS")
            if field == "digest":
                _require(re.fullmatch(r"[0-9a-f]{64}", str(value)) is not None, f"{name} digest is invalid")


def _validate_rke2(root: Path) -> None:
    server = _read(root / "infra/self-hosted/rke2/server-config.yaml.example")
    agent = _read(root / "infra/self-hosted/rke2/agent-config.yaml.example")
    audit = _read(root / "infra/self-hosted/rke2/audit-policy.yaml")
    _contains_all(
        server,
        (
            "profile: cis",
            "token-file: /etc/rancher/rke2/token",
            'write-kubeconfig-mode: "0600"',
            "secrets-encryption: true",
            "secrets-encryption-provider: secretbox",
            "protect-kernel-defaults: true",
            "etcd-snapshot-compress: true",
            "CriticalAddonsOnly=true:NoExecute",
            "cni: canal",
            "disable-cloud-controller: true",
        ),
        "RKE2 server config",
    )
    _require(re.search(r"(?m)^token:\s*\S+", server) is None, "RKE2 config must not contain a join token")
    _contains_all(agent, ("token-file:", "REPLACE_WITH_FAILURE_DOMAIN"), "RKE2 agent config")
    _contains_all(
        audit,
        ("kind: Policy", "resources:\n          - secrets", "level: RequestResponse"),
        "RKE2 audit policy",
    )


def _validate_values(root: Path) -> None:
    rook_operator = _read(root / "infra/self-hosted/helm/rook-operator-values.yaml")
    rook_cluster = _read(root / "infra/self-hosted/helm/rook-cluster-values.yaml")
    openbao = _read(root / "infra/self-hosted/helm/openbao-values.yaml")
    openbao_csi = _read(root / "infra/self-hosted/helm/openbao-csi-values.yaml")
    harbor = _read(root / "infra/self-hosted/helm/harbor-values.yaml")

    _contains_all(
        rook_operator,
        ("tag: v1.20.6", "allowLoopDevices: false", "currentNamespaceOnly: true", "disableDeviceHotplug: true"),
        "Rook operator values",
    )
    _contains_all(
        rook_cluster,
        (
            "tag: v20.2.4",
            "allowUnsupported: false",
            "skipUpgradeChecks: false",
            "continueUpgradeAfterChecksEvenIfNotHealthy: false",
            'confirmation: ""',
            "allowUninstallWithVolumes: false",
            "useAllNodes: false",
            "useAllDevices: false",
            'encryptedDevice: "true"',
            "nodes: []",
            "name: thermoform-ceph-block",
            "reclaimPolicy: Retain",
            "volumeBindingMode: WaitForFirstConsumer",
            "preservePoolsOnDelete: true",
            "securePort: 443",
            "sslCertificateRef: thermoform-rgw-tls",
            "instances: 2",
        ),
        "Rook cluster values",
    )
    _require("useAllDevices: true" not in rook_cluster, "Ceph must not claim all disks")
    _require(rook_cluster.count("reclaimPolicy: Retain") >= 2, "Ceph storage must be retained")

    _contains_all(
        openbao,
        (
            "tlsDisable: false",
            'tag: "2.6.2"',
            "injector:\n  enabled: false",
            "csi:\n  enabled: false",
            "readinessProbe:\n    enabled: true\n    path: /v1/sys/health?standbyok=true\n",
            "livenessProbe:\n    enabled: true\n    path: /v1/sys/health?standbyok=true&sealedcode=204&uninitcode=204",
            "standalone:\n    enabled: false",
            "ha:\n    enabled: true\n    replicas: 3",
            "raft:\n      enabled: true",
            "tls_disable = 0",
            "secretName: openbao-server-tls",
            "storageClass: thermoform-ceph-block",
            "whenDeleted: Retain",
            "whenScaled: Retain",
            "maxUnavailable: 1",
            "ui:\n  enabled: false",
        ),
        "OpenBao values",
    )
    _require("devRootToken" not in openbao, "OpenBao values must not contain a development token")
    _contains_all(
        openbao_csi,
        (
            "tlsDisable: false",
            "externalBaoAddr: https://openbao.openbao.svc:8200",
            "injector:\n  enabled: false",
            "csi:\n  enabled: true",
            "secretName: openbao-client-ca",
            "- -ca-cert=/openbao/tls/ca.crt",
            'maxUnavailable: "1"',
        ),
        "OpenBao CSI values",
    )

    _contains_all(
        harbor,
        (
            "externalURL: https://harbor.thermoform.internal",
            "certSource: secret",
            "type: s3",
            "existingSecret: harbor-registry-s3",
            "rook-ceph-rgw-thermoform-objectstore.rook-ceph.svc:443",
            "skipverify: false",
            "existingSecretAdminPassword: harbor-admin",
            "secretName: harbor-token-service",
            "internalTLS:\n  enabled: true",
            "database:\n  type: external",
            "sslmode: verify-full",
            "redis:\n  type: external",
            "sentinelMasterSet: thermoform",
        ),
        "Harbor values",
    )
    _require(harbor.count("replicas: 2") >= 6, "Harbor HA replicas drifted")
    for forbidden in ("harborAdminPassword:", "accesskey:", "secretkey:", 'sslmode: "disable"'):
        _require(forbidden not in harbor, f"unsafe Harbor value: {forbidden}")


def _validate_keycloak_and_thanos(root: Path) -> None:
    keycloak = _read(root / "infra/self-hosted/keycloak/keycloak.yaml")
    namespaces = _read(root / "infra/self-hosted/kubernetes/namespaces.yaml")
    overlay = _read(root / "infra/kubernetes/overlays/rke2-ceph-openbao/kustomization.yaml")
    providers = _read(root / "infra/kubernetes/overlays/rke2-ceph-openbao/secret-provider-classes.yaml")
    _contains_all(
        keycloak,
        (
            "apiVersion: k8s.keycloak.org/v2beta1",
            "instances: 3",
            "vendor: postgres",
            "usernameSecret:",
            "passwordSecret:",
            "strict: true",
            "httpEnabled: false",
            "tlsSecret: keycloak-server-tls",
            "networkPolicy:\n    enabled: true",
        ),
        "Keycloak contract",
    )
    _require("kind: Secret" not in keycloak, "Keycloak contract must not embed a Secret")
    _require(
        namespaces.count('openbao-access: "true"') == 3,
        "OpenBao consumer namespaces must be explicitly allowed",
    )
    _contains_all(
        overlay,
        ("../../observability", "thermoform-ceph-block", "driver: secrets-store.csi.k8s.io"),
        "self-hosted Thanos overlay",
    )
    _require(providers.count("kind: SecretProviderClass") == 3, "expected three OpenBao secret providers")
    for role, path in {
        "thanos-receive": "kv/data/thanos/receive",
        "thanos-store": "kv/data/thanos/store",
        "thanos-compact": "kv/data/thanos/compact",
    }.items():
        _contains_all(providers, (f"roleName: {role}", f"secretPath: {path}"), f"{role} secret provider")
    _require(providers.count("filePermission: 0400") == 3, "Thanos secret files must be owner-read-only")


def _validate_rendered(args: argparse.Namespace) -> None:
    if args.rook_cluster:
        rendered = _read(args.rook_cluster)
        _contains_all(
            rendered,
            (
                "kind: CephCluster",
                'encryptedDevice: "true"',
                "useAllDevices: false",
                "useAllNodes: false",
                'confirmation: ""',
                "preservePoolsOnDelete: true",
                "securePort: 443",
            ),
            "rendered Ceph cluster",
        )
    if args.openbao:
        rendered = _read(args.openbao)
        _contains_all(
            rendered,
            (
                "replicas: 3",
                "tls_disable = 0",
                "storageClassName: thermoform-ceph-block",
                "secretName: openbao-server-tls",
            ),
            "rendered OpenBao",
        )
    if args.openbao_csi:
        rendered = _read(args.openbao_csi)
        _contains_all(
            rendered,
            (
                "kind: DaemonSet",
                "name: openbao-csi-provider",
                "https://openbao.openbao.svc:8200",
                "secretName: openbao-client-ca",
                "-ca-cert=/openbao/tls/ca.crt",
            ),
            "rendered OpenBao CSI provider",
        )
    if args.harbor:
        rendered = _read(args.harbor)
        _contains_all(
            rendered,
            (
                "https://harbor.thermoform.internal",
                "rook-ceph-rgw-thermoform-objectstore.rook-ceph.svc:443",
                "storageClassName: thermoform-ceph-block",
            ),
            "rendered Harbor",
        )


def validate(root: Path, args: argparse.Namespace) -> None:
    _validate_lock(root)
    _validate_rke2(root)
    _validate_values(root)
    _validate_keycloak_and_thanos(root)
    _validate_rendered(args)
    combined = "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted((root / "infra/self-hosted").rglob("*"))
        if path.is_file()
    ).lower()
    for forbidden in ("aws_access_key_id", "aws_secret_access_key", "harbor12345", "changeit"):
        _require(forbidden not in combined, f"forbidden credential marker: {forbidden}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--rook-cluster", type=Path)
    parser.add_argument("--openbao", type=Path)
    parser.add_argument("--openbao-csi", type=Path)
    parser.add_argument("--harbor", type=Path)
    args = parser.parse_args()
    try:
        validate(args.root.resolve(), args)
    except (OSError, json.JSONDecodeError, ContractError) as exc:
        parser.error(str(exc))
    print("Self-hosted production foundation contract is valid.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
