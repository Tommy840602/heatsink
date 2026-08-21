# Production Thanos topology

This Kustomize base moves the long-term metrics path from the same-host Compose reference to Kubernetes failure domains. It deploys three fixed Thanos Receive ingesters with replication factor three, two Store Gateways, two stateless Query replicas, and exactly one Compactor. It does not deploy Prometheus, Grafana, an ingress, a bucket, or cloud credentials.

## Production prerequisites

- Kubernetes 1.34 or newer, with at least three schedulable nodes in three zones labelled with `topology.kubernetes.io/zone`.
- A default `ReadWriteOnce` StorageClass, or an environment overlay that sets `storageClassName` for the Receive and Compactor claims. Store Gateway cache is rebuildable `emptyDir` state.
- A CNI that enforces `NetworkPolicy` and permits kubelet health probes under the selected policy implementation.
- One strongly consistent S3-compatible bucket and prefix shared by Receive, Store Gateway, and Compactor.
- Four independently bound workload identities. Query has no bucket access; it also has service-account token automount disabled.

The checked-in base contains neither a Kubernetes `Secret` nor static cloud credentials. A deployment pipeline must create `thermoform-thanos-object-store` and add provider-specific workload-identity annotations to the ServiceAccounts before starting the workloads.

| ServiceAccount | Minimum object-store authority |
|---|---|
| `thanos-receive` | list, read, and write blocks; no delete |
| `thanos-store` | list and read only |
| `thanos-query` | none |
| `thanos-compact` | list, read, write, and delete |

If SSE-KMS is enabled, grant only the matching KMS operations and key to the three bucket clients that require them. Provider lifecycle rules must not expire current Thanos blocks; Compactor owns retention and deletion.

## Render and validate

From the repository root:

```bash
mkdir -p .runtime/thanos
docker run --rm \
  -v "$PWD:/workspace:ro" \
  registry.k8s.io/kubectl:v1.34.1 \
  kustomize /workspace/infra/kubernetes/observability \
  > .runtime/thanos/kubernetes.yml
docker run --rm \
  -v "$PWD/.runtime/thanos/kubernetes.yml:/work/manifests.yml:ro" \
  ghcr.io/yannh/kubeconform:v0.7.0 \
  -strict -summary -kubernetes-version 1.34.0 \
  /work/manifests.yml
python scripts/validate_kubernetes_observability.py \
  .runtime/thanos/kubernetes.yml
```

The contract validator rejects topology drift, a reduced Receive replication factor, multiple Compactors, object-store access on Query, unpinned images, public services, privileged pods, and static S3 credential fields.

## Prepare runtime configuration

Create the namespace and render the same credential-free S3 configuration used by the Compose production contract:

```bash
kubectl apply -f infra/kubernetes/observability/namespace.yaml
python scripts/render_thanos_s3_config.py \
  --bucket thermoform-metrics-prod \
  --endpoint s3.ap-northeast-1.amazonaws.com \
  --region ap-northeast-1 \
  --prefix thermoform/metrics \
  --output .runtime/thanos/object-store.yml
kubectl -n thermoform-observability create secret generic \
  thermoform-thanos-object-store \
  --from-file=object-store.yml=.runtime/thanos/object-store.yml \
  --dry-run=client -o yaml | kubectl apply -f -
```

Do not add the generated Secret manifest or runtime object-store file to Git. Validate bucket list/read/write operations from the actual Receive identity and list/read operations from the Store identity before rollout. Validate deletion only in a disposable prefix with the Compactor identity.

Create an environment overlay that imports this base and patches each ServiceAccount with the provider's workload-identity binding. The base intentionally omits AWS-, GCP-, and Azure-specific annotations. Patch storage classes, resource requests, and the `thanos-retention` ConfigMap in the same overlay. Before selecting finite retention, run:

```bash
python scripts/validate_thanos_retention.py \
  --raw 365d --five-minutes 365d --one-hour 365d
```

All three resolutions must remain `0d`, or use the same whole-day value of at least 10 days.

## Network integration

The base denies ingress by default and permits:

- traffic between observability pods;
- remote write on TCP `19291` from namespaces labelled `thermoform.io/metrics-write=true`;
- Thanos HTTP metrics and Query access on TCP `10902` from namespaces labelled `thermoform.io/metrics-read=true`.

Label only intended client namespaces:

```bash
kubectl label namespace monitoring thermoform.io/metrics-write=true
kubectl label namespace monitoring thermoform.io/metrics-read=true
kubectl label namespace grafana thermoform.io/metrics-read=true
```

Prometheus remote write target:

```text
http://thanos-receive.thermoform-observability.svc.cluster.local:19291/api/v1/receive
```

Grafana or internal clients query:

```text
http://thanos-query.thermoform-observability.svc.cluster.local:10902
```

Keep both Services internal. TLS and authentication for cross-namespace or externally routed traffic belong in the cluster gateway or service mesh; the base creates no `LoadBalancer`, `NodePort`, or ingress.

## Rollout invariants

- Receive uses a fixed three-member StatefulSet DNS hashring. Keep `replicas: 3`; scaling requires an atomic hashring change or Thanos Receive Controller design.
- Receive has strict zone and hostname spreading. Pods intentionally remain Pending when three eligible zones are unavailable.
- Store Gateway and Query prefer zones and require separate nodes, but can run in a degraded two-zone cluster.
- Compactor is a singleton. Never scale it, horizontally autoscale it, or run an ad-hoc Compactor against the same bucket.
- Receive and Compactor PVCs are retained when their StatefulSets are deleted or scaled. A manifest rollback does not delete PVCs or bucket blocks.
- PDBs protect only voluntary evictions. They do not prevent node loss, direct pod deletion, a bad rollout, or application failure.

Apply the reviewed environment overlay, wait for all replicas, and verify the hashring and bucket path:

```bash
kubectl apply -k infra/kubernetes/overlays/production
kubectl -n thermoform-observability rollout status statefulset/thanos-receive
kubectl -n thermoform-observability rollout status statefulset/thanos-store
kubectl -n thermoform-observability rollout status deployment/thanos-query
kubectl -n thermoform-observability rollout status statefulset/thanos-compact
kubectl -n thermoform-observability get pods -o wide
```

`infra/kubernetes/overlays/production` is an environment-owned example path, not a checked-in universal overlay. The cloud identity, zones, StorageClass, resource sizing, and ingress trust boundary must be explicit for the target cluster.

For standard Amazon EKS managed nodes, use the checked-in [`../overlays/aws-eks`](../overlays/aws-eks/README.md) overlay and its fail-closed IRSA renderer instead of inventing an environment overlay from scratch.
