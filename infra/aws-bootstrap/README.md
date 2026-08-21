# AWS production Terraform bootstrap

This directory contains the independently managed CloudFormation foundation
for the production Terraform root. CloudFormation avoids the circular
dependency of using Terraform state to create its own backend.

The template creates or binds:

- a retained, versioned, private S3 state bucket with no automatic version
  expiry;
- a retained, rotation-enabled KMS key and retained TLS-only bucket policy;
- the account's standard GitHub OIDC provider, only when explicitly requested;
- one plan-only role with exact GitHub Environment trust, exact state/lock
  object access, and read-only refresh permissions for the Thanos resources.

It does not create the Thanos data bucket, EKS resources, an apply role, an AWS
access key, or a GitHub Environment. Stack deletion intentionally retains the
state bucket, KMS key, bucket policy, and any provider created by the stack.
Those retained resources require a separate audited retirement procedure.

## Exact OIDC subject

GitHub repositories created after 2026-07-15 use immutable owner and repository
IDs in the default OIDC subject. This repository was created on 2026-08-21 and
currently has owner ID `84989346` and repository ID `1341254721`, so its expected
subject is:

```text
repo:Tommy840602@84989346/heatsink@1341254721:environment:production-plan
```

Confirm those values immediately before creating a change set:

```bash
gh api repos/Tommy840602/heatsink \
  --jq '{owner_id: .owner.id, repository_id: .id, created_at: .created_at}'
```

Do not guess this value and do not use `*` or `StringLike`. A repository
transfer, rename, replacement, or GitHub subject customization requires a new
review of the live subject and trust policy.

## Credential-free validation

CI pins `cfn-lint` 1.55.1 and runs the semantic contract validator:

```bash
python -m pip install --disable-pip-version-check cfn-lint==1.55.1
cfn-lint --non-zero-exit-code warning \
  infra/aws-bootstrap/production-terraform-plan.yml
python scripts/validate_aws_bootstrap.py \
  infra/aws-bootstrap/production-terraform-plan.yml
```

These checks require no AWS credentials and create no resources.

## Reviewed bootstrap procedure

Use a separately authenticated human/bootstrap identity. First list IAM OIDC
providers and set `CreateGitHubOidcProvider=true` only when
`token.actions.githubusercontent.com` is absent. The default is `false`; if the
provider is absent, role creation fails closed.

Create a named CloudFormation change set with these reviewed parameters:

| Parameter | Required value |
|---|---|
| `StateBucketName` | Globally unique production state bucket |
| `StateKey` | `thermal-ai/production/thanos.tfstate` |
| `ThanosBucketName` | Future production Thanos data bucket; must differ |
| `GitHubOidcSubject` | Exact immutable subject above after live verification |
| `CreateGitHubOidcProvider` | `true` only if the account has no GitHub provider |
| `PlanRoleName` | `thermoform-production-plan` |
| `TerraformNamePrefix` | `thermoform-prod` |

`CAPABILITY_NAMED_IAM` is required because the template names the plan role.
Review the entire change set before a separately authorized operator executes
it. In particular, confirm there is one retained bucket/key, one plan role, no
unexpected replacement, and no managed-resource write permission.

The plan role has `PutObject` on the exact state object because the Terraform S3
backend requires it, plus Get/Put/Delete on only the adjacent `.tflock` object.
It has no state-object delete and no IAM, KMS, or Thanos bucket mutation action.
Because state overwrite remains possible, GitHub Environment approval, exact
subject trust, S3 versioning, and restricted `main` dispatch are all mandatory.

After execution, read the stack outputs and set the matching GitHub
`production-plan` Environment variables:

- `StateBucketName` → `TF_STATE_BUCKET`
- `StateKey` → `TF_STATE_KEY`
- `TerraformPlanRoleArn` → `TERRAFORM_PLAN_ROLE_ARN`

Set the remaining production variables described in the Terraform environment
README. Then independently verify bucket versioning, KMS encryption, public
access blocks, the TLS deny policy, OIDC audience/subject equality, and the
role's effective policy before dispatching a plan. Creating the foundation does
not authorize a Terraform plan or apply.
