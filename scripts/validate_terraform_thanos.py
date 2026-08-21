#!/usr/bin/env python3
"""Validate the safety contract of the AWS Thanos Terraform module."""

from __future__ import annotations

import argparse
from pathlib import Path
import re


class ContractError(ValueError):
    """Raised when the Terraform module violates a safety invariant."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ContractError(message)


def validate(module_dir: Path) -> None:
    main = module_dir.joinpath("main.tf").read_text(encoding="utf-8")
    variables = module_dir.joinpath("variables.tf").read_text(encoding="utf-8")
    versions = module_dir.joinpath("versions.tf").read_text(encoding="utf-8")
    outputs = module_dir.joinpath("outputs.tf").read_text(encoding="utf-8")
    combined = "\n".join((main, variables, versions, outputs))

    _require('version = "= 6.55.0"' in versions, "AWS provider must be exactly pinned")
    _require(
        'required_version = ">= 1.15.0, < 1.16.0"' in versions,
        "Terraform minor version must be bounded",
    )
    _require(main.count("prevent_destroy = true") == 2, "bucket and KMS key must prevent destroy")
    for requirement in (
        "block_public_acls       = true",
        "block_public_policy     = true",
        "ignore_public_acls      = true",
        "restrict_public_buckets = true",
        'object_ownership = "BucketOwnerEnforced"',
        'status = "Enabled"',
        'sse_algorithm     = "aws:kms"',
        "bucket_key_enabled = true",
        'test     = "Bool"',
        'variable = "aws:SecureTransport"',
        'values   = ["false"]',
        "noncurrent_version_expiration",
        "abort_incomplete_multipart_upload",
    ):
        _require(requirement in main, f"missing S3 safety control: {requirement}")
    _require(
        re.search(r"(?m)^\s+expiration\s*\{", main) is None,
        "current Thanos objects must not have an S3 expiration rule",
    )

    _require(main.count('"s3:DeleteObject"') == 1, "only one workload may delete objects")
    compact_actions = main.split("compact = [", 1)[1].split("]", 1)[0]
    _require('"s3:DeleteObject"' in compact_actions, "only Compactor may delete objects")
    receive_actions = main.split("receive = [", 1)[1].split("]", 1)[0]
    store_actions = main.split("store = [", 1)[1].split("]", 1)[0]
    _require("DeleteObject" not in receive_actions, "Receive must not delete objects")
    _require("DeleteObject" not in store_actions, "Store must not delete objects")
    _require('query' not in main.split("service_accounts = {", 1)[1].split("}", 1)[0], "Query must not receive an IAM role")

    for requirement in (
        'test     = "StringEquals"',
        'values   = ["sts.amazonaws.com"]',
        'values   = ["system:serviceaccount:${var.namespace}:${each.value}"]',
        "endswith(var.cluster_oidc_provider_arn",
    ):
        _require(requirement in main, f"missing exact IRSA trust control: {requirement}")
    _require('identifiers = ["*"]' in main, "TLS deny policy must cover every principal")
    _require('effect = "Deny"' in main, "wildcard TLS principal must only appear in a deny")
    _require('effect = "Allow"\n    actions = ["s3:*"]' not in main, "IAM roles must not allow s3 wildcard actions")
    _require("noncurrent_version_retention_days >= 30" in variables, "recovery window must be at least 30 days")

    for name in (
        "bucket_name",
        "object_prefix",
        "kms_key_arn",
        "receive_role_arn",
        "store_role_arn",
        "compact_role_arn",
    ):
        _require(f'output "{name}"' in outputs, f"missing renderer output: {name}")
    for forbidden in ("access_key", "secret_key", "aws_access_key_id", "aws_secret_access_key"):
        _require(forbidden not in combined.lower(), f"static credential field found: {forbidden}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("module_dir", type=Path)
    args = parser.parse_args()
    try:
        validate(args.module_dir)
    except (OSError, ContractError) as exc:
        parser.error(str(exc))
    print("AWS Thanos Terraform safety contract is valid.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
