# AWS EKS production overlay

This overlay binds the production Thanos topology to standard Amazon EKS managed nodes using IAM Roles for Service Accounts (IRSA) and the standard Amazon EBS CSI driver. It does not support EKS Auto Mode's different `ebs.csi.eks.amazonaws.com` provisioner.

The checked-in role ARNs are deliberate fail-closed placeholders. Do not apply the raw Kustomize output. `render_eks_thanos_manifest.py` requires three complete, distinct IAM role ARNs and removes every placeholder before producing an applyable manifest.

## Prerequisites

- An EKS cluster running Kubernetes 1.34 or newer with an IAM OIDC provider.
- At least three Ready, schedulable Linux nodes across three `topology.kubernetes.io/zone` values.
- The standard EBS CSI add-on registered as `ebs.csi.aws.com` on every eligible node.
- Three IAM roles whose trust policies match exactly these subjects:
  - `system:serviceaccount:thermoform-observability:thanos-receive`
  - `system:serviceaccount:thermoform-observability:thanos-store`
  - `system:serviceaccount:thermoform-observability:thanos-compact`
- IMDS restricted at the node/network boundary so a Pod cannot fall back to the node role.

Scope S3 access to the selected bucket and Thanos prefix. Receive needs `s3:ListBucket`, `s3:GetObject`, and `s3:PutObject`; Store needs only list/get; Compactor needs list/get/put/delete. Only grant KMS operations when the matching S3 configuration uses SSE-KMS. Compactor remains the only identity with `s3:DeleteObject`.

## Render

From the repository root:

```bash
mkdir -p .runtime/thanos
docker run --rm \
  -v "$PWD:/workspace:ro" \
  registry.k8s.io/kubectl:v1.34.1 \
  kustomize /workspace/infra/kubernetes/overlays/aws-eks \
  > .runtime/thanos/eks-template.yml

python scripts/render_eks_thanos_manifest.py \
  --template .runtime/thanos/eks-template.yml \
  --receive-role-arn arn:aws:iam::123456789012:role/thermoform-thanos-receive \
  --store-role-arn arn:aws:iam::123456789012:role/thermoform-thanos-store \
  --compact-role-arn arn:aws:iam::123456789012:role/thermoform-thanos-compact \
  --output .runtime/thanos/eks-production.yml

python scripts/validate_kubernetes_observability.py \
  .runtime/thanos/eks-production.yml
```

Replace the example account and role names. The generated file contains role ARNs but no credentials and is ignored by Git through `.runtime/`.

The overlay creates `thermoform-ebs-gp3` with encrypted gp3 volumes, `Retain`, expansion enabled, and `WaitForFirstConsumer`. Receive and Compactor use that class. Store Gateway's index cache remains a bounded, rebuildable `emptyDir` and does not own a PVC.

## Read-only cluster preflight

Apply only the StorageClass after reviewing it, then run the preflight against an explicit context:

```bash
kubectl --context <eks-context> apply \
  -f infra/kubernetes/overlays/aws-eks/storageclass.yaml
python scripts/preflight_eks_thanos.py \
  --context <eks-context> \
  --storage-class thermoform-ebs-gp3
```

The preflight performs only `version` and `get` operations. It rejects an old API server, fewer than three eligible zones, an unsafe StorageClass, or missing EBS CSI registration on any candidate node.

## Deploy

Create the namespace and runtime object-store Secret first, following the base deployment guide. Confirm the current context again, then apply the rendered file:

```bash
kubectl --context <eks-context> config current-context
kubectl --context <eks-context> apply -f .runtime/thanos/eks-production.yml
kubectl --context <eks-context> -n thermoform-observability \
  rollout status statefulset/thanos-receive --timeout=10m
kubectl --context <eks-context> -n thermoform-observability \
  rollout status statefulset/thanos-store --timeout=10m
kubectl --context <eks-context> -n thermoform-observability \
  rollout status deployment/thanos-query --timeout=10m
kubectl --context <eks-context> -n thermoform-observability \
  rollout status statefulset/thanos-compact --timeout=10m
```

Before sending production remote write, inspect the Pods for injected `AWS_ROLE_ARN` and `AWS_WEB_IDENTITY_TOKEN_FILE`, verify each role ARN matches its ServiceAccount, and run a read-only bucket listing through each workload. Test denied write/delete permissions only against a disposable prefix and never against live Thanos blocks.

Do not treat a successful render as a successful cloud deployment. The production gate additionally requires the three-zone placement, one-node drain drill, recent and historical queries, remote-write backlog recovery, and Compactor singleton checks in the observability runbook.
