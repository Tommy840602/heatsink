# Self-hosted production foundation

This foundation replaces the AWS-specific production path with RKE2, Rook-managed Ceph, OpenBao, Keycloak, and Harbor. It is a reviewed configuration and render contract, not evidence that a production cluster exists. Nothing in this directory contacts or mutates a Kubernetes cluster.

## Architecture

```text
Users / CI
    |
HAProxy + Keepalived VIP (operator-owned)
    |
RKE2: 3 control-plane nodes + at least 3 worker/storage nodes
    |
    +-- Rook/Ceph: encrypted raw OSDs, replicated RBD, RGW S3
    +-- OpenBao: 3-node Raft, TLS, audit volume, CSI provider
    +-- Keycloak: 3 instances, external PostgreSQL, TLS/OIDC
    +-- Harbor: 2+ replicas, external PostgreSQL/Valkey, Ceph RGW
    +-- Thanos: Ceph RBD + Ceph RGW credentials mounted from OpenBao
```

The five selected products are not a complete production platform by themselves. The environment must also provide:

- a stable TCP registration/API address for RKE2, normally HAProxy plus Keepalived;
- authoritative DNS and an operator-controlled CA or ACME issuer;
- cert-manager and the Secrets Store CSI Driver at the versions in `stack-lock.json`;
- an HA PostgreSQL service for separate Keycloak and Harbor databases;
- an HA Valkey service with Sentinel for Harbor;
- an independent backup target outside the Ceph cluster.

The repository deliberately does not select a PostgreSQL or Valkey operator yet. Installing Harbor or Keycloak against single-pod embedded data services would misrepresent this foundation as highly available.

## Version and supply-chain contract

`stack-lock.json` pins every selected release and official chart digest. Resolve artifacts from the listed HTTPS repositories, compare the repository index digest, mirror the verified images into Harbor, and then replace mutable tag references with Harbor digest references in an environment-owned overlay. Never allow an automatic chart or Keycloak Operator upgrade in production.

RKE2 is pinned to `v1.36.3+rke2r1`. Download its release artifacts and checksum file separately, verify them before installation, and use the exact version on all nodes. Do not pipe the network installer directly to a privileged shell.

## Hardware boundary

The cluster requires three control-plane nodes and three or more worker/storage nodes. Label every worker with a real `topology.kubernetes.io/zone` failure domain. Ceph requires one or more dedicated raw disks on at least three distinct nodes; the operating-system disk must never be offered to Rook.

`rook-cluster-values.yaml` intentionally has both `useAllNodes` and `useAllDevices` disabled and an empty `nodes` list. It creates no OSD until an operator adds exact node names and stable `/dev/disk/by-id/...` paths in a private environment override. This fail-closed placeholder is mandatory because an incorrect Ceph disk selection is destructive.

Before the first Ceph install, record for every candidate disk:

- host and failure domain;
- `/dev/disk/by-id` path and serial number;
- size, firmware health, and absence of mounted filesystems;
- explicit approval that all existing data may be destroyed.

## Bootstrap order

1. Prepare hosts, firewall rules, time synchronization, DNS, VIP, kernel settings, and raw Ceph disks.
2. Verify RKE2 release checksums. Install the same pinned release on three control-plane nodes, then join workers using a token stored only in `/etc/rancher/rke2/token` with mode `0600`.
3. Confirm etcd quorum, encrypted Kubernetes secrets, the CIS profile, API audit logging, snapshots, and failure-domain labels.
4. Install cert-manager and issue the internal service certificates. Keep the root CA key offline.
5. Install the pinned Rook operator. Apply a reviewed private Ceph device override, install the Ceph cluster, and wait for `HEALTH_OK` before creating consumers.
6. Test an RBD PVC, retained snapshot, RGW TLS, bucket versioning, and deletion denial in disposable test resources.
7. Install the Secrets Store CSI Driver, followed by OpenBao in TLS-enabled three-node Raft mode. Keep the server release in the restricted `openbao` namespace; render `openbao-csi-values.yaml` as a separate external-mode release in `kube-system`, where its node-level host paths are expected.
8. Initialize OpenBao once. Split unseal/recovery shares between independent custodians; do not store enough shares in Kubernetes, Ceph, Git, Harbor, or the same password manager. Enable audit logging before writing application secrets.
9. Configure Kubernetes auth roles and distinct least-privilege policies for Thanos Receive, Store, and Compactor. Store each complete `object-store.yml` under its separate KV path.
10. Provision HA PostgreSQL and Valkey, then materialize the specifically named bootstrap Secrets from OpenBao into their target namespaces through an approved workflow.
11. Install the pinned Keycloak Operator by immutable Git commit, apply `keycloak/keycloak.yaml`, create the initial realm through a reviewed realm export, and verify issuer/audience/redirect URIs.
12. Install Harbor with `harbor-values.yaml`, enable OIDC against Keycloak, create immutable projects, enforce vulnerability scanning and retention, and mirror every production image.
13. Render and apply `infra/kubernetes/overlays/rke2-ceph-openbao` only after OpenBao auth and Ceph RGW permissions pass. Query has no object-store identity; Compactor is the only Thanos identity allowed to delete blocks.

## Required secrets

No value for these objects belongs in Git:

| Namespace | Secret | Purpose |
|---|---|---|
| `rook-ceph` | `thermoform-rgw-tls` | RGW server TLS |
| `openbao` | `openbao-server-tls` | OpenBao server/cluster TLS and CA |
| `kube-system` | `openbao-client-ca` | CA-only trust bundle for the OpenBao CSI Provider |
| `keycloak` | `keycloak-database` | PostgreSQL username/password |
| `keycloak` | `keycloak-server-tls` | Keycloak TLS |
| `harbor` | `harbor-admin`, `harbor-token-service`, and Harbor runtime secrets | initial/admin, token signing, and component secrets |
| `harbor` | `harbor-database`, `harbor-valkey` | external data services |
| `harbor` | `harbor-registry-s3`, `thermoform-rgw-ca` | Ceph RGW access and trust |
| `harbor` | `harbor-*-tls` | ingress and internal component TLS |

Kubernetes Secrets remain materialized data, even when sourced from OpenBao. RKE2 secret encryption protects etcd at rest but does not remove the need for namespace RBAC, audit logs, rotation, and backup encryption.

The OpenBao server certificate must cover `openbao`, `openbao.openbao`, `openbao.openbao.svc`, `openbao-active`, every `openbao-N.openbao-internal` peer name, and the equivalent namespace-qualified peer names. The RGW certificate must cover `rook-ceph-rgw-thermoform-objectstore.rook-ceph.svc`. Keycloak and Harbor certificates must match their configured external hostnames. Never set a TLS skip-verification option to work around a missing SAN.

## Render-only validation

These commands download pinned public charts and render to a temporary directory. They do not use a kubeconfig and do not contact a cluster.

```bash
runtime_dir="$(mktemp -d)"

helm template rook-ceph rook-ceph \
  --repo https://charts.rook.io/release --version v1.20.6 \
  --namespace rook-ceph --include-crds \
  -f infra/self-hosted/helm/rook-operator-values.yaml \
  > "$runtime_dir/rook-operator.yaml"

helm template rook-ceph-cluster rook-ceph-cluster \
  --repo https://charts.rook.io/release --version v1.20.6 \
  --namespace rook-ceph \
  -f infra/self-hosted/helm/rook-cluster-values.yaml \
  > "$runtime_dir/rook-cluster.yaml"

helm template openbao openbao \
  --repo https://openbao.github.io/openbao-helm --version 0.29.2 \
  --namespace openbao -f infra/self-hosted/helm/openbao-values.yaml \
  > "$runtime_dir/openbao.yaml"

helm template openbao-csi openbao \
  --repo https://openbao.github.io/openbao-helm --version 0.29.2 \
  --namespace kube-system -f infra/self-hosted/helm/openbao-csi-values.yaml \
  > "$runtime_dir/openbao-csi.yaml"

helm template harbor harbor \
  --repo https://helm.goharbor.io --version 1.19.2 \
  --namespace harbor -f infra/self-hosted/helm/harbor-values.yaml \
  > "$runtime_dir/harbor.yaml"

kubectl kustomize infra/kubernetes/overlays/rke2-ceph-openbao \
  > "$runtime_dir/thanos.yaml"

python scripts/validate_self_hosted_stack.py \
  --rook-cluster "$runtime_dir/rook-cluster.yaml" \
  --openbao "$runtime_dir/openbao.yaml" \
  --openbao-csi "$runtime_dir/openbao-csi.yaml" \
  --harbor "$runtime_dir/harbor.yaml"

python scripts/validate_kubernetes_observability.py "$runtime_dir/thanos.yaml"
```

Do not treat a successful render as deployment evidence. Production acceptance additionally requires node, disk, quorum, TLS, backup/restore, denied-permission, drain, upgrade, and disaster-recovery drills.

## Backup and recovery gates

- RKE2: copy encrypted etcd snapshots and the server token to an offline, access-controlled target. Perform a full restore rehearsal on isolated hosts.
- Ceph: snapshots are not backups when they remain in the same cluster. Replicate RGW buckets and export critical RBD data to an independent failure domain.
- OpenBao: take Raft snapshots after configuration changes and before upgrades. Restore tests require the matching unseal/recovery material.
- Keycloak and Harbor: use transactionally consistent PostgreSQL backups and test schema-compatible restores before every upgrade.
- Harbor: preserve its S3 objects, PostgreSQL database, runtime secrets, token-signing material, and CA chain as one recovery set.

No component may be upgraded while Ceph is degraded, OpenBao lacks quorum, PostgreSQL backup verification is stale, or the previous version cannot be restored in staging.
