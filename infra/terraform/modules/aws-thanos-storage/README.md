# AWS Thanos storage and IRSA module

This Terraform module creates the AWS resources consumed by the EKS Thanos overlay:

- one private, versioned S3 bucket with TLS-only access;
- one rotation-enabled KMS key and alias;
- exact-subject IRSA roles for Receive, Store Gateway, and Compactor;
- prefix-scoped S3 and KMS policies with delete reserved for Compactor;
- lifecycle cleanup for incomplete multipart uploads and old noncurrent versions only.

It deliberately creates no EKS cluster, Kubernetes object, static credential, current-object expiration, replication bucket, CloudTrail, or Terraform backend. Consume it from an environment root that already has reviewed remote state, AWS provider configuration, approvals, and account guardrails.

## Example root configuration

```hcl
terraform {
  backend "s3" {}
}

provider "aws" {
  region = "ap-northeast-1"
}

module "thanos_storage" {
  source = "../../modules/aws-thanos-storage"

  bucket_name                = "thermoform-metrics-prod"
  object_prefix              = "thermoform/metrics"
  cluster_oidc_provider_arn  = "arn:aws:iam::123456789012:oidc-provider/oidc.eks.ap-northeast-1.amazonaws.com/id/EXAMPLE"
  cluster_oidc_issuer_url    = "https://oidc.eks.ap-northeast-1.amazonaws.com/id/EXAMPLE"
  name_prefix                = "thermoform-prod"

  tags = {
    Environment = "production"
    Owner       = "thermal-platform"
  }
}
```

Configure the backend through reviewed `-backend-config` inputs and commit the root module's `.terraform.lock.hcl`. Never use local state for a production apply.

## Validate without AWS credentials

```bash
module_dir="$PWD/infra/terraform/modules/aws-thanos-storage"
docker run --rm -v "$module_dir:/work:ro" -w /work \
  hashicorp/terraform:1.15.8 fmt -check -diff

runtime_dir="$(mktemp -d)"
cp "$module_dir"/*.tf "$runtime_dir"/
docker run --rm -v "$runtime_dir:/work" -w /work \
  hashicorp/terraform:1.15.8 init -backend=false -input=false
docker run --rm -v "$runtime_dir:/work" -w /work \
  hashicorp/terraform:1.15.8 validate
python scripts/validate_terraform_thanos.py "$module_dir"
```

Terraform and the AWS provider are bounded to the versions validated in CI. Provider installation occurs only in the disposable validation directory, so `.terraform/` and a module-level lock file are not written into the source module.

## Plan and apply gate

1. Confirm the AWS account, region, EKS cluster, OIDC issuer, remote-state backend, and state-lock mechanism independently.
2. Generate and review a saved Terraform plan in CI. It must contain one bucket, one KMS key, three roles, their inline policies, and the bucket controls; it must not replace any existing bucket or key.
3. Review the three trust policies. Each `sub` must identify exactly one ServiceAccount in `thermoform-observability`; wildcard subjects are forbidden.
4. Review IAM actions. Receive cannot delete, Store cannot write or delete, and only Compactor has `s3:DeleteObject`.
5. Apply through the environment's approval workflow. The module's bucket and KMS key have `prevent_destroy`; intentional retirement requires a separate code review and data-retention plan.
6. Feed the outputs into `render_thanos_s3_config.py` and `render_eks_thanos_manifest.py`. Role ARNs and resource identifiers are not secrets, but generated runtime manifests remain outside Git.

Example output handoff:

```bash
python scripts/render_thanos_s3_config.py \
  --bucket "$(terraform output -raw bucket_name)" \
  --endpoint s3.ap-northeast-1.amazonaws.com \
  --region ap-northeast-1 \
  --prefix "$(terraform output -raw object_prefix)" \
  --sse-kms-key-id "$(terraform output -raw kms_key_arn)" \
  --output .runtime/thanos/object-store.yml
```

S3 versioning is not a replacement for a tested backup or cross-region recovery design. The lifecycle rule never expires current objects; it only aborts incomplete multipart uploads and removes noncurrent versions after a minimum 30-day recovery window. Compactor remains responsible for current Thanos block retention.
