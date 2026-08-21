# Production Thanos Terraform root

This root wires the reviewed `aws-thanos-storage` module to an encrypted S3
backend with native lockfiles. It is intentionally operated by the manual
`Production Terraform plan` GitHub Actions workflow. That workflow can create a
saved plan for review, but it has no apply path and uploads no plan artifact.

## Bootstrap boundary

Create the remote-state foundation before using this root through the
separately reviewed CloudFormation contract in `../../../aws-bootstrap`. The
state bucket must be distinct from the Thanos data bucket and must have public
access blocked, versioning enabled, TLS-only access, encryption, and recovery
monitoring. Do not manage that bucket from the state it stores.

The backend is partially configured in Git. The workflow supplies only the
reviewed bucket, key, and region at `terraform init`; no backend credentials or
account-specific values belong in this directory. S3 native locking uses the
state key plus `.tflock`; DynamoDB locking is not used.

The plan role's backend policy should be limited to:

- `s3:ListBucket` for the exact state prefix;
- `s3:GetObject`, `s3:GetObjectVersion`, and `s3:PutObject` for the exact state
  object;
- `s3:GetObject`, `s3:PutObject`, and `s3:DeleteObject` for only its exact
  `.tflock` object.

It must not be able to delete the state object. Add only the AWS read/list/get
permissions Terraform needs to refresh this root. The plan workflow must not be
given IAM, KMS, or S3 create/update/delete permissions for managed resources.
Use a different, separately approved workflow and role if apply is added in a
future phase.

## GitHub Environment gate

Create a GitHub Environment named `production-plan` with:

- required reviewers and self-review prevention where available;
- deployment branches restricted to the protected `main` branch;
- no AWS access keys or long-lived credentials;
- the following environment variables.

| Variable | Contract |
|---|---|
| `AWS_ACCOUNT_ID` | Exact non-placeholder 12-digit production account |
| `AWS_REGION` | Region containing the EKS cluster |
| `TERRAFORM_PLAN_ROLE_ARN` | OIDC role in `AWS_ACCOUNT_ID`, plan permissions only |
| `TF_STATE_BUCKET` | Pre-existing state bucket, distinct from Thanos data |
| `TF_STATE_KEY` | Safe relative path ending in `.tfstate` |
| `THANOS_BUCKET_NAME` | Globally unique production data bucket to create |
| `THANOS_OBJECT_PREFIX` | Production block prefix, for example `thermoform/metrics` |
| `EKS_OIDC_PROVIDER_ARN` | Existing EKS IAM OIDC provider in the same account/region |
| `EKS_OIDC_ISSUER_URL` | Exact HTTPS issuer matching that provider ARN |

The AWS plan role must trust GitHub's OIDC provider only for audience
`sts.amazonaws.com` and the exact live `production-plan` Environment subject.
For this post-2026-07-15 repository that currently means
`repo:Tommy840602@84989346/heatsink@1341254721:environment:production-plan`.
Reconfirm the owner/repository IDs and current GitHub subject format before
bootstrap; wildcards, branch-only subjects, and organization-wide trust are
forbidden.

## Run a plan

1. Merge and validate the workflow on protected `main`.
2. Open **Actions → Production Terraform plan → Run workflow** and select
   `main`.
3. Paste the exact 40-character `main` commit SHA and select `PLAN_ONLY`.
4. Review and approve the `production-plan` Environment deployment.
5. Review the value-free step summary. Any delete, replacement, more than 50
   resource changes, account mismatch, lock-file drift, or input mismatch stops
   the job.

The saved binary plan and JSON exist only in the runner's temporary directory
and are removed in an `always()` cleanup step. They are never uploaded. This
workflow is evidence for a later apply review, not apply authorization.

## Credential-free validation

```bash
terraform_dir="$PWD/infra/terraform"
docker run --rm -v "$terraform_dir:/work:ro" -w /work \
  hashicorp/terraform:1.15.8 fmt -check -diff -recursive

runtime_dir="$(mktemp -d)"
cp -R "$terraform_dir" "$runtime_dir/terraform"
docker run --rm -v "$runtime_dir/terraform:/work" \
  -w /work/environments/production hashicorp/terraform:1.15.8 \
  init -backend=false -input=false
docker run --rm -v "$runtime_dir/terraform:/work" \
  -w /work/environments/production hashicorp/terraform:1.15.8 validate
python scripts/validate_production_plan_contract.py \
  infra/terraform/environments/production \
  .github/workflows/terraform-production-plan.yml
```

Copy `terraform.tfvars.example` only for disposable local inspection and keep
the populated file outside Git. A local validation is not a production plan.
