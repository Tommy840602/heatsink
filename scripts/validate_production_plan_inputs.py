#!/usr/bin/env python3
"""Validate fail-closed inputs for the production Terraform plan workflow."""

from __future__ import annotations

import json
import os
import re


SHA_PATTERN = re.compile(r"^[0-9a-f]{40}$")
ACCOUNT_PATTERN = re.compile(r"^[0-9]{12}$")
REGION_PATTERN = re.compile(r"^[a-z]{2}(?:-gov)?-[a-z]+-[0-9]$")
ROLE_PATTERN = re.compile(
    r"^arn:(aws|aws-us-gov|aws-cn):iam::([0-9]{12}):role/"
    r"[A-Za-z0-9+=,.@_/-]{1,512}$"
)
BUCKET_PATTERN = re.compile(r"^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$")
PREFIX_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,254}[A-Za-z0-9]$")
OIDC_PROVIDER_PATTERN = re.compile(
    r"^arn:(aws|aws-us-gov|aws-cn):iam::([0-9]{12}):oidc-provider/"
    r"(oidc\.eks\.([a-z0-9-]+)\.amazonaws\.com(?:\.cn)?/id/[A-Za-z0-9]+)$"
)


class InputError(ValueError):
    """Raised when a production plan input is absent or unsafe."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise InputError(message)


def _safe_bucket(value: str, label: str) -> str:
    _require(BUCKET_PATTERN.fullmatch(value) is not None, f"{label} is not a valid S3 bucket name")
    _require(not re.fullmatch(r"[0-9]{1,3}(?:\.[0-9]{1,3}){3}", value), f"{label} must not look like an IP address")
    _require(not any(item in value for item in ("..", ".-", "-.")), f"{label} has invalid separators")
    _require(
        not value.startswith(("xn--", "sthree-", "amzn-s3-demo-"))
        and not value.endswith(("-s3alias", "--ol-s3", ".mrap", "--x-s3", "--table-s3")),
        f"{label} uses an AWS-reserved name",
    )
    return value


def validate(values: dict[str, str]) -> dict[str, str]:
    expected_sha = values.get("EXPECTED_COMMIT_SHA", "")
    github_sha = values.get("GITHUB_SHA", "")
    _require(values.get("CONFIRMATION") == "PLAN_ONLY", "confirmation must be PLAN_ONLY")
    _require(values.get("GITHUB_REF") == "refs/heads/main", "production plans must run from main")
    _require(SHA_PATTERN.fullmatch(expected_sha) is not None, "expected commit SHA must be 40 lowercase hex characters")
    _require(expected_sha == github_sha, "expected commit SHA must exactly match GITHUB_SHA")

    account = values.get("AWS_ACCOUNT_ID", "")
    region = values.get("AWS_REGION", "")
    _require(ACCOUNT_PATTERN.fullmatch(account) is not None and account != "000000000000", "invalid AWS account ID")
    _require(REGION_PATTERN.fullmatch(region) is not None, "invalid AWS region")

    role = values.get("TERRAFORM_PLAN_ROLE_ARN", "")
    role_match = ROLE_PATTERN.fullmatch(role)
    _require(role_match is not None, "invalid Terraform plan role ARN")
    _require(role_match.group(2) == account, "Terraform plan role belongs to the wrong account")

    state_bucket = _safe_bucket(values.get("TF_STATE_BUCKET", ""), "state bucket")
    thanos_bucket = _safe_bucket(values.get("THANOS_BUCKET_NAME", ""), "Thanos bucket")
    _require(state_bucket != thanos_bucket, "state and Thanos data must use different buckets")
    state_key = values.get("TF_STATE_KEY", "")
    _require(
        PREFIX_PATTERN.fullmatch(state_key) is not None
        and state_key.endswith(".tfstate")
        and "//" not in state_key
        and all(segment not in {".", ".."} for segment in state_key.split("/")),
        "state key must be a safe relative .tfstate path",
    )
    object_prefix = values.get("THANOS_OBJECT_PREFIX", "")
    _require(
        PREFIX_PATTERN.fullmatch(object_prefix) is not None
        and "//" not in object_prefix
        and all(segment not in {".", ".."} for segment in object_prefix.split("/")),
        "invalid Thanos object prefix",
    )

    provider_arn = values.get("EKS_OIDC_PROVIDER_ARN", "")
    issuer = values.get("EKS_OIDC_ISSUER_URL", "")
    provider_match = OIDC_PROVIDER_PATTERN.fullmatch(provider_arn)
    _require(provider_match is not None, "invalid EKS OIDC provider ARN")
    _require(provider_match.group(2) == account, "EKS OIDC provider belongs to the wrong account")
    _require(provider_match.group(4) == region, "EKS OIDC provider belongs to the wrong region")
    _require(issuer == f"https://{provider_match.group(3)}", "EKS OIDC issuer and provider ARN do not match")

    return {
        "account": account,
        "commit": github_sha,
        "environment": "production-plan",
        "region": region,
        "state_key": state_key,
        "status": "validated",
    }


def main() -> int:
    try:
        result = validate(dict(os.environ))
    except InputError as exc:
        raise SystemExit(f"production plan input error: {exc}") from exc
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
